import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
from threading import Event
import unittest
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from maimai_analysis.capture import CaptureAlignment
from maimai_analysis.commands import CANCELLED, SwitchAnalysis, goals_embed, parse_times, register_analysis, request_analysis
from maimai_analysis.delivery import Delivery
from maimai_analysis.hud import score_digits, early_judgments
from maimai_analysis.jobs import Job, play_key
from maimai_analysis.mai_notes import CachedChart
from maimai_analysis.media import Decoder, Image as VideoFrame, MediaError, Source, resolve
from maimai_analysis.scoring import Sample
from maimai_analysis.service import AnalysisBusy, AnalysisService, resource_usage
from maimai_analysis.simai import parse_sections, parse_simai
from maimai_analysis.store import Store
from maimai_analysis.tracking import Chart, Frame, Play
from maimai_analysis.vision import ScoreMode
from maimai_analysis.youtube import Video
from song_lookup import SongLookup


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name) / 'test.db')
        self.chart = Chart('std:abc:master', 'Credits', 'std', 'master', '14.6')
        self.simai = parse_simai('(120){4},1,2,3,4,E')
        self.cached = CachedChart('https://mai-notes.com/player/test', '', self.simai)
        self.video = 'lxMVGRpRHiM'

    def test_multi_timestamp(self):
        self.assertEqual(parse_times('1:02, 1:03.25\n64'), [62, 63.25, 64])

    async def test_discord_reuses_autocomplete_and_default_master(self):
        with patch.dict(os.environ, {'DISCORD_TOKEN': 'test', 'BOT_DEVELOPER_ID': '1'}), \
                patch('discord.Client.run'), patch('dotenv.load_dotenv'):
            namespace = runpy.run_path('bot.py', run_name='bot_maimai_test')
        index = SongLookup([{'title': 'Credits', 'artist': 'Frums', 'imageName': 'cover.png',
                             'sheets': [{'type': 'std', 'difficulty': 'master',
                                         'internalLevelValue': 14.6, 'regions': {'intl': True}}]}], [])
        tree = namespace['tree']
        namespace['autocomplete_song'].__globals__['_song_lookup'] = index
        for name in ('목표설정', '구간확인', '라이브분석'):
            command = tree.get_command(name)
            param = next(p for p in command.parameters if p.name == 'song')
            self.assertIs(command._params['song'].autocomplete, namespace['autocomplete_song'])
            self.assertTrue(param.autocomplete)
            self.assertEqual(next(p for p in command.parameters if p.name == 'difficulty').default, 'master')
        self.assertFalse(next(p for p in tree.get_command('목표설정').parameters if p.name == 'chart_link').required)
        self.assertEqual({p.display_name for p in tree.get_command('영상분석').parameters},
                         {'영상링크', '종료시간', '플레이어명', '게스트허용'})
        self.assertEqual(tree.get_command('라이브분석-게스트토글').parameters[0].display_name, '라이브링크')
        option = index.autocomplete('credits')[0]['value']
        song, sheet, _ = index.select(option)
        simai = parse_simai('(120){4}12,3,4,E')
        empty = goals_embed(namespace['make_song_embed'], song, sheet, self.cached, ())
        self.assertIsNone(empty.footer.text)
        target = goals_embed(namespace['make_song_embed'], song, sheet, self.cached,
                             parse_sections('1:-.1,2:-.1', simai))
        self.assertEqual(target.fields[0].name, 'MASTER 14.6')
        self.assertIn('노트 3~4', target.fields[-1].value)
        self.assertIn('2 → 3', target.footer.text)
        app = AnalysisService(self.store, lambda: index, AsyncMock())
        app.notes.find_link = Mock(return_value=self.cached.url)
        app.notes.load = Mock(return_value=self.cached)
        for name in ('목표설정', '구간확인', '영상분석', '라이브분석', '라이브분석-게스트토글'):
            tree.remove_command(name)
        register_analysis(tree, AsyncMock(return_value=app), lambda: index,
                          namespace['autocomplete_song'], namespace['make_song_embed'])
        interaction = Mock()
        interaction.user.id = 1
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        await tree.get_command('구간확인').callback(interaction, 'Credits', f'https://youtu.be/{self.video}',
                                                 '12', first_note='12')
        self.assertIn('1번', interaction.followup.send.call_args.kwargs['embed'].description)
        self.assertIsNone(self.store.target(1, f'{option}:master'))
        app.calibrate_for_interaction = AsyncMock(side_effect=MediaError('YouTube 영상 스트림을 열 수 없습니다.'))
        await tree.get_command('구간확인').callback(interaction, option, f'https://youtu.be/{self.video}', '12')
        self.assertIn('첫노트시간', interaction.followup.send.call_args.args[0])
        await tree.get_command('목표설정').callback(interaction, '[ST] Credits', goals='2개:-0.1 나머지:-0.05')
        saved = self.store.target(1, f'{option}:master')
        self.assertEqual([(section.first, section.last) for section in saved.sections], [(1, 2), (3, 4)])

    def test_cropped_gameplaza_hud_and_score_type(self):
        import numpy as np

        with Image.open(Path(__file__).parent / 'fixtures' / 'maimai-gameplaza-rois.pgm') as fixture:
            pixels = np.array(fixture)
        self.assertEqual(score_digits(pixels[:42]), '101.0000')
        self.assertEqual(score_digits(pixels[42:84]), '100.8830')
        self.assertEqual(score_digits(pixels[84:126]), '100.8462')
        self.assertEqual(early_judgments(pixels[126:162, :191]), 0)
        self.assertEqual(early_judgments(pixels[162:198, :191]), 2)
        self.assertIsNone(score_digits(np.zeros((42, 199), dtype=np.uint8)))
        detector = ScoreMode()
        self.assertEqual(detector.add(0, '100.0000', 0), ())
        self.assertEqual(detector.add(.2, '99.9999', .2), ())
        self.assertEqual(detector.add(.4, '99.9900', .4), ())
        detector = ScoreMode()
        self.assertFalse(detector.add(0, '101.0000', 0))
        self.assertEqual([reading.mode for reading in detector.add(.2, '101.0000', .2)], ['-', '-'])

    def test_ffmpeg_preserves_seek_timestamp(self):
        decoder = Decoder(width=320, height=180, fps=4)
        if not shutil.which(decoder.ffmpeg):
            self.skipTest('FFmpeg executable is required')
        output = self.store.path.with_suffix('.mp4')
        subprocess.run([decoder.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin',
                        '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24',
                        '-threads', '1', '-c:v', 'mpeg4', '-t', '2', str(output)],
                       check=True, timeout=20)
        frames = list(decoder.frames(str(output), 0.5, 1))
        self.assertEqual([round(frame.time, 3) for frame in frames], [0.5, 0.75, 1, 1.25])
        self.assertTrue(all(len(frame.pixels) == 320 * 180 for frame in frames))

    def test_ffmpeg_stops_when_no_frames_arrive(self):
        from io import BytesIO

        stopped = Event()
        process = Mock(stderr=BytesIO())
        process.stdout.read.side_effect = lambda _size: stopped.wait(3) and b''
        process.kill.side_effect = stopped.set
        process.poll.side_effect = lambda: 1 if stopped.is_set() else None
        decoder = Decoder(width=320, height=180)
        with patch('maimai_analysis.media.subprocess.Popen', return_value=process), \
                patch('maimai_analysis.media.passthrough_option', return_value=()), \
                patch('maimai_analysis.media.FRAME_TIMEOUT', .05):
            with self.assertRaisesRegex(MediaError, 'FFmpeg.*프레임'):
                list(decoder.frames('dummy.mp4', 0))
        process.kill.assert_called_once()

    def test_resolve_prefers_seekable_vod_hls_with_video_only_variant(self):
        from yt_dlp import YoutubeDL

        direct = {'url': 'https://example.com/video.mp4', 'protocol': 'https',
                  'vcodec': 'avc1.640020', 'acodec': 'none', 'height': 720}
        hls = {**direct, 'url': 'https://example.com/video.m3u8', 'protocol': 'm3u8_native'}

        def extract_info(downloader, url, download):
            select = downloader.build_format_selector(downloader.params['format'])
            return next(select({'formats': [direct, hls]}))

        with patch.object(YoutubeDL, 'extract_info', extract_info):
            self.assertEqual(resolve(Video(self.video, 0), False, 720).protocol, 'm3u8_native')

    def test_youtube_login_challenge_reports_the_actual_cause(self):
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError

        challenge = DownloadError('Sign in to confirm you’re not a bot.')
        with patch.dict(os.environ, {'MAIMAI_YOUTUBE_COOKIES': ''}), \
                patch.object(YoutubeDL, 'extract_info', side_effect=challenge), \
                self.assertLogs('maimai_analysis.media', level='WARNING'):
            with self.assertRaisesRegex(MediaError, 'YouTube.*로그인 확인'):
                resolve(Video(self.video, 0), False, 720)

    def test_youtube_uses_the_configured_cookie_file_without_rewriting_it(self):
        from yt_dlp import YoutubeDL

        cookies = self.store.path.with_name('test-cookies.txt')
        contents = '# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tTEST\tsynthetic\n'
        cookies.write_text(contents, encoding='utf-8')
        row = {'url': 'https://example.com/video.m3u8', 'protocol': 'm3u8_native', 'availability': 'public'}

        def extract_info(downloader, url, download):
            self.assertEqual(downloader.cookiejar.get_cookie_header('https://www.youtube.com/watch'), 'TEST=synthetic')
            return row

        with patch.dict(os.environ, {'MAIMAI_YOUTUBE_COOKIES': str(cookies)}), \
                patch.object(YoutubeDL, 'extract_info', extract_info):
            self.assertEqual(resolve(Video(self.video, 0), False, 720).protocol, 'm3u8_native')
            self.assertEqual(cookies.read_text(encoding='utf-8'), contents)
            row['availability'] = 'private'
            with self.assertRaisesRegex(MediaError, '공개'):
                resolve(Video(self.video, 0), False, 720)

    def test_complete_vod_hls_uses_relative_time_without_program_dates(self):
        source = Source('https://example.com/video.m3u8', {}, 110, None, 'm3u8_native')
        playlist = '#EXTM3U\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXTINF:5.5,\na.ts\n#EXT-X-ENDLIST\n'
        decoder = Decoder()
        response = Mock(text=playlist, url=source.url)
        with patch('requests.get', return_value=response), patch.object(decoder, 'frames', return_value=iter(())) as frames:
            list(decoder.vod(source, 35, 88))
            frames.assert_called_once_with(source.url, 35, 53, headers={}, fps=None)
            for invalid in (playlist.replace('#EXT-X-ENDLIST', ''),
                            playlist.replace('#EXTINF:', '#EXT-X-MEDIA-SEQUENCE:7\n#EXTINF:')):
                with self.subTest(playlist=invalid), self.assertRaises(MediaError):
                    response.text = invalid
                    list(decoder.vod(source, 35, 88))

    async def test_section_lookup_synchronizes_a_capture_without_broadcast_hud(self):
        import cv2
        import numpy as np

        chart = parse_simai('(180){8},4,4,5,3,8,1,1,6,2,7,5,12,6,8,1,4,7,6,E')
        lanes = (4, 4, 5, 3, 8, 1, 1, 6, 2, 7, 5, 1, 2, 6, 8, 1, 4, 7, 6)
        width, height = 320, 180
        center, radius = (160, 90), 78
        origin = 1.8
        background = np.zeros((height, width), np.uint8)
        cv2.circle(background, center, radius, 200, 1, cv2.LINE_AA)
        angles = np.deg2rad(np.arange(8) * 45 - 67.5)
        points = np.round(np.array(center) + radius * np.column_stack((np.cos(angles), np.sin(angles)))).astype(int)
        for point in points:
            cv2.circle(background, tuple(point), 2, 235, -1)

        def stream(source, start, end, **kwargs):
            for step in range(180):
                timestamp = step / 30
                pixels = background.copy()
                for note, lane in zip(chart.notes, lanes):
                    if 0 < origin + note.time - timestamp < 0.055:
                        cv2.circle(pixels, tuple(points[lane - 1]), 7, 235, 3, cv2.LINE_AA)
                yield VideoFrame(timestamp, pixels.tobytes())

        decoder = Mock(width=width, height=height, fps=8, vod=Mock(side_effect=stream))
        vision = Mock()
        vision.inspect_seats.return_value = {}
        source = Source('https://example.com/capture', {}, 6, None)
        service = AnalysisService(self.store, lambda: SongLookup([], []), AsyncMock(), decoder, lambda: vision,
                                  resolve_source=Mock(return_value=source))
        times = (2.45, 3.8, 4.6)
        self.assertAlmostEqual(await service.calibrate(Video(self.video, 0), self.chart.key, chart, times),
                               origin, delta=0.035)
        decoder.vod.assert_called_once()
        different = parse_simai('(180){8},1,6,4,5,3,7,8,2,6,1,4,78,2,4,7,5,3,1,E')
        with self.assertRaisesRegex(ValueError, '첫노트시간'):
            await service.calibrate(Video(self.video, 0), self.chart.key, different, times)

    def test_capture_refuses_two_matching_offsets(self):
        chart = parse_simai('(120){8}4,5,2,3,7,6,1,8,E')
        capture = CaptureAlignment(320, 180, chart, (3.25, 3.5))
        for time, lane in capture.anchors:
            capture.events[lane].extend((2 + time, 3 + time))
        self.assertIsNone(capture.origin())

    def test_capture_lanes_can_be_read_from_existing_chart_cache(self):
        source = '(120){4}14,8b,C,1-5[4:1],E'
        chart = asdict(parse_simai(source))
        for note in chart['notes']:
            del note['lane']
        with self.store.connection(write=True) as sql:
            sql.execute('INSERT INTO charts VALUES (?, ?, ?, ?)',
                        (self.cached.url, self.chart.key, source, json.dumps(chart)))
        cached = self.store.cached_chart(self.cached.url, self.chart.key)
        self.assertEqual([note.lane for note in cached.chart.notes], [1, 4, 8, None, 1, None])

    async def test_failed_vod_history_reports_the_input_error(self):
        channel = Mock(send=AsyncMock(return_value=Mock(id=1)))
        delivery = Delivery(self.store, AsyncMock(return_value=channel))
        job = Job(1, self.video, False, 0, None, 'Milk', None,
                  error='YouTube에서 분석 가능한 스트림을 가져오지 못했습니다.')
        await delivery.history(job)
        report = channel.send.await_args.kwargs['embed'].description
        self.assertIn(job.error, report)
        self.assertNotIn('설정에 맞는 플레이를 확인하지 못했습니다.', report)

    async def test_restart_keeps_settings_and_forgets_playback_jobs(self):
        self.store.set_nickname(1, 'Milk')
        self.store.save_target(1, self.chart.key, self.cached, parse_sections('1:-.1', self.simai))
        resolver = Mock(side_effect=AssertionError('Video jobs must be resubmitted'))
        service = AnalysisService(Store(self.store.path), lambda: None, AsyncMock(), resolve_source=resolver)
        self.addAsyncCleanup(service.close)
        await service.start()
        await asyncio.sleep(0)
        self.assertEqual(service.store.nickname(1), 'Milk')
        self.assertEqual(service.store.target(1, self.chart.key).sections[0].first, 1)
        self.assertEqual(service.pending, [])
        self.assertEqual(service.live_jobs, {})
        resolver.assert_not_called()

    async def test_switch_waits_for_the_running_analysis_to_close(self):
        worker_stopped = Event()
        began = Event()
        service = AnalysisService(self.store, lambda: None, AsyncMock(),
                                  resolve_source=Mock(return_value=Mock(duration=20)))

        def scan(*args, cancel, **kwargs):
            began.set()
            self.assertTrue(cancel.wait(3))
            worker_stopped.set()

        service.scan = Mock(side_effect=scan)
        service.delivery.history = AsyncMock()
        await service.start()
        self.addAsyncCleanup(service.close)
        await service.submit(1, Video(self.video, 0), False, None, None, 'Milk')
        self.assertTrue(await asyncio.to_thread(began.wait, 2))
        another = Video('O-ErNwyDSCU', 0)
        with self.assertRaises(AnalysisBusy) as blocked:
            await service.submit(1, another, False, None, None, None)
        self.assertFalse(worker_stopped.is_set())
        with self.assertRaisesRegex(ValueError, '요청한 사람'):
            await service.submit(2, another, False, None, None, 'Rival', replace_run=blocked.exception.run)
        service.scan.side_effect = None
        running_scan = service.scan.call_args.kwargs['cancel']
        await service.submit(1, another, False, None, None, None, replace_run=blocked.exception.run)
        self.assertTrue(running_scan.is_set())
        self.assertTrue(worker_stopped.is_set())

    async def test_switch_buttons_only_replace_after_confirmation(self):
        requester = Mock()
        requester.user.id = 1
        requester.followup.send = AsyncMock()
        requester.response.edit_message = AsyncMock()
        conflict = AnalysisBusy(object())

        for confirm in (False, True):
            action = AsyncMock(side_effect=[conflict, 'started'])

            async def wait_for_click(view):
                button = view.replace if confirm else view.keep
                await button.callback(requester)
                return False

            with patch.object(SwitchAnalysis, 'wait', wait_for_click):
                result = await request_analysis(requester, action)
            if confirm:
                self.assertEqual(result, 'started')
                self.assertEqual(action.await_args.kwargs, {'replace_run': conflict.run})
            else:
                self.assertIs(result, CANCELLED)
                action.assert_awaited_once()

    async def test_live_guest_toggle_is_user_and_broadcast_specific(self):
        service = AnalysisService(self.store, lambda: None, AsyncMock())
        self.addAsyncCleanup(service.close)
        my_job = Job(1, self.video, True, None, None, 'Milk', None)
        other = Job(2, self.video, True, None, None, 'Someone', None)
        service.live_jobs[self.video] = (my_job, other)
        self.assertTrue(await service.toggle_guest(1))
        self.assertTrue(my_job.include_guest)
        self.assertFalse(other.include_guest)
        second = '5-w74xyV8hw'
        service.live_jobs[second] = (Job(1, second, True, None, None, 'Milk', None),)
        with self.assertRaisesRegex(ValueError, '라이브링크'):
            await service.toggle_guest(1)
        self.assertFalse(await service.toggle_guest(1, self.video))

    async def test_live_toggle_during_guest_track_keeps_current_track_and_excludes_next(self):
        index = SongLookup([{'title': 'Credits', 'artist': 'Frums',
                             'sheets': [{'type': 'std', 'difficulty': 'master', 'regions': {'intl': True}}]}], [])
        started, toggled = Event(), Event()
        decoder = Mock(width=640, height=360, fps=6)
        frames = (
            Frame(0, 'ready', nickname='GUEST', confidence=98, rating=0, track=1, title='Credits', difficulty='master'),
            Frame(.5, 'ready', nickname='GUEST', confidence=98, rating=0, track=1, title='Credits', difficulty='master'),
            Frame(1, 'start'), Frame(2, 'result'),
            Frame(2.5, 'ready', title='Credits', difficulty='master', track=2),
            Frame(3, 'start'), Frame(4, 'result')
        )

        def stream(*args, **kwargs):
            for frame in frames:
                if frame.time == 2:
                    started.set()
                    if not toggled.wait(3):
                        raise AssertionError('toggle did not run')
                yield frame

        decoder.live.side_effect = stream
        vision = Mock()
        vision.inspect_seats.side_effect = lambda frame, *_: {'right': frame}
        service = AnalysisService(self.store, lambda: index, AsyncMock(), decoder, lambda: vision)
        self.addAsyncCleanup(service.close)
        job = Job(1, self.video, True, None, None, 'Milk', None, include_guest=True)
        service.live_jobs[self.video] = (job,)
        plays = []
        scanner = asyncio.create_task(asyncio.to_thread(
            service.scan, self.video, Mock(), None, None, True, lambda: (job,),
            lambda event, play: plays.append(play) if event == 'finish' else None))
        self.assertTrue(await asyncio.to_thread(started.wait, 2))
        self.assertFalse(await service.toggle_guest(1))
        toggled.set()
        await scanner
        self.assertEqual([job.matches(play) for play in plays], [True, False])

    async def test_calibration_timeout_stops_worker_before_releasing_slot(self):
        service = AnalysisService(self.store, lambda: None, AsyncMock())
        abandoned = Event()

        async def calibrate(*args, cancel):
            await asyncio.to_thread(cancel.wait, 2)
            if cancel.is_set():
                abandoned.set()

        service.calibrate = calibrate
        with patch('maimai_analysis.service.CALIBRATION_TIMEOUT', .025), self.assertRaises(TimeoutError):
            await service.calibrate_for_interaction(Video(self.video, 0), self.chart.key, self.simai, [12], user_id=1)
        await asyncio.gather(*service.sync_jobs)
        self.assertTrue(abandoned.is_set())
        self.assertIsNone(service.current)

    def test_live_reconnect_jumps_to_live_edge_and_marks_gap(self):
        def disconnect():
            yield VideoFrame(120, b'', 1700000120)
            raise MediaError('temporary failure')

        decoder = Mock(width=640, height=360, fps=8)
        decoder.live.side_effect = [disconnect(), (frame for frame in [
            VideoFrame(120, b'', 1700000120), VideoFrame(120.125, b'', 1700000120.125)])]
        service = AnalysisService(self.store, lambda: None, AsyncMock(), decoder=decoder,
                                  resolve_source=Mock(return_value=Mock()))
        stop = Mock(is_set=Mock(return_value=False))
        result = list(service.live_frames(self.video, None, 119, stop))
        self.assertEqual([(frame.time, frame.discontinuity) for frame in result], [(120, False), (120.125, True)])
        self.assertEqual([call.args[1] for call in decoder.live.call_args_list], [119, None])

    def test_late_dvr_uses_verified_broadcast_start(self):
        from datetime import datetime, timezone
        origin = 1700000000
        stamp = datetime.fromtimestamp(origin + 60, timezone.utc).isoformat()
        response = Mock(text=f'#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:10\n#EXT-X-PROGRAM-DATE-TIME:{stamp}\n'
                             '#EXTINF:6,\nfirst.ts\n#EXT-X-ENDLIST',
                        url='https://example.com/live.m3u8')
        decoder = Decoder()
        with patch('requests.Session.get', return_value=response), \
                patch.object(decoder, 'frames', return_value=iter([VideoFrame(60, b'', origin + 60)])):
            unverified = Source(response.url, {}, None, origin, 'm3u8')
            with self.assertRaisesRegex(MediaError, '검증'):
                list(decoder.live(unverified, None))
            source = Source(response.url, {}, None, origin, 'm3u8', actual_epoch=origin)
            self.assertEqual([frame.time for frame in decoder.live(source, None)], [60])

    def test_slow_live_decoder_jumps_to_latest_segment(self):
        from datetime import datetime, timezone

        origin = 1700000000
        stamp = datetime.fromtimestamp(origin, timezone.utc).isoformat()
        url = 'https://example.com/live.m3u8'
        manifest = f'#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\n#EXT-X-PROGRAM-DATE-TIME:{stamp}\n'
        segments = ''.join(f'#EXTINF:6,\n{seq}.ts\n' for seq in range(4))
        source = Source(url, {}, None, origin, 'm3u8')
        decoder = Decoder()
        for start, expected in [(None, [(0, False), (18, True)]),
                                (0, [(0, False), (6, False), (12, False), (18, False)])]:
            with patch('requests.Session.get', side_effect=[
                    Mock(text=manifest + '#EXTINF:6,\n0.ts\n', url=url),
                    Mock(text=manifest + segments + '#EXT-X-ENDLIST', url=url)]), \
                    patch('maimai_analysis.media.time.sleep'), \
                    patch.object(decoder, 'frames', side_effect=lambda _, t, *args, **kw:
                                 iter([VideoFrame(t, b'', kw['epoch'])])):
                self.assertEqual([(f.time, f.discontinuity) for f in decoder.live(source, start)], expected)

    async def test_vod_shares_inflight_decoder_and_rescans_on_new_command(self):
        index = SongLookup([{'title': 'Credits', 'artist': 'Frums',
                             'sheets': [{'type': 'std', 'difficulty': 'master', 'regions': {'intl': True}}]},
                            {'title': 'Rival', 'artist': 'A',
                             'sheets': [{'type': 'std', 'difficulty': 'master', 'regions': {'intl': True}}]}], [])
        target_key = index.autocomplete('Credits')[0]['value'] + ':master'
        self.store.save_target(1, target_key, self.cached, parse_sections('1:-.1', self.simai))
        waiting, has_joined = Event(), Event()

        def source(video, live, size):
            waiting.set()
            if not has_joined.wait(3):
                raise AssertionError('shared watcher did not join')
            return Mock(duration=12)

        frames = [
            Frame(0, 'profile', nickname='Milk', confidence=98),
            Frame(.5, 'profile', nickname='Milk', confidence=98),
            Frame(1, 'ready', title='Credits', kind='std', difficulty='master'),
            Frame(2, 'start', origin=2), Frame(3, 'playing'), Frame(4, 'result'),
            Frame(4.5, 'ready', title='Rival', kind='std', difficulty='master'),
            Frame(5, 'start'), Frame(6, 'playing'), Frame(7, 'result'),
            Frame(7.5, 'ready', title='Credits', kind='std', difficulty='master'),
            Frame(8, 'start', origin=8), Frame(9, 'playing'), Frame(10, 'skip'),
            Frame(11, 'credit_end'), Frame(11.6)
        ]
        mocked = Mock(width=640, height=360, fps=6)
        mocked.vod = Mock(side_effect=lambda *args, **kwargs: (f for f in frames))
        vision = Mock()
        vision.inspect_seats.side_effect = lambda frame, trackers, live: {
            'left': Frame(frame.time, 'playing', samples=(Sample(frame.time, '-', '100'),))
            if frame.phase == 'playing' and trackers['left'].accepts_score(frame) else frame
        }
        service = AnalysisService(self.store, lambda: index, AsyncMock(), mocked, lambda: vision, source)
        self.addAsyncCleanup(service.close)
        service.delivery.history = AsyncMock()
        service.delivery.finished = AsyncMock()
        await service.start()
        video = Video(self.video, 0)
        await service.submit(1, video, False, None, None, 'Milk')
        self.assertTrue(await asyncio.to_thread(waiting.wait, 2))
        await service.submit(2, video, False, None, None, 'Milk')
        has_joined.set()
        for _ in range(100):
            if service.delivery.history.await_count == 2:
                break
            await asyncio.sleep(.02)
        self.assertEqual(service.delivery.history.await_count, 2)
        self.assertEqual(mocked.vod.call_count, 1)
        plays = [call.args[1] for call in service.delivery.finished.await_args_list if call.args[0].user_id == 1]
        self.assertEqual([play.chart.title for play in plays], ['Credits', 'Rival', 'Credits'])
        self.assertEqual([len(play.samples) for play in plays], [1, 0, 1])
        self.assertEqual(plays[-1].status, 'skipped')
        await service.submit(1, video, False, None, None, 'Milk')
        for _ in range(100):
            if service.delivery.history.await_count == 3:
                break
            await asyncio.sleep(.02)
        self.assertEqual(mocked.vod.call_count, 2)
        self.assertGreater(resource_usage()[1], 0)

    async def test_live_dm_reuses_message_and_reads_latest_goal_before_finish(self):
        channel = Mock()
        sent = []
        async def send(**kwargs):
            message = Mock(id=len(sent) + 1, jump_url=f'https://discord.com/channels/@me/1/{len(sent) + 1}')
            message.edit = AsyncMock()
            sent.append(message)
            return message
        channel.send = AsyncMock(side_effect=send)
        channel.fetch_message = AsyncMock(side_effect=lambda i: sent[i - 1])
        delivery = Delivery(self.store, AsyncMock(return_value=channel))
        job = Job(1, self.video, True, None, None, 'Milk', None)
        play = Play(self.chart, 'Milk', 95, 10, 12.6, 10, 'finished', [
            Sample(10, '-', '100'), Sample(11.25, '-', '100'),
            Sample(11.75, '-', '99.8260'), Sample(12.25, '-', '99.8260')
        ], gaps=[(10.1, 10.8)])
        self.store.save_target(1, self.chart.key, self.cached, parse_sections('1:-.1,3:-.1', self.simai))
        await delivery.waiting(job)
        await delivery.started(job, play)
        self.store.save_target(1, self.chart.key, self.cached, parse_sections('1:-.3,3:-.3', self.simai))
        play.end_epoch, play.result_epoch, play.received_end = 982, 984, 997
        with patch('maimai_analysis.delivery.time.time', return_value=1000), \
                self.assertLogs('maimai_analysis.delivery', level='INFO') as log:
            await delivery.finished(job, play)
        self.assertIn('youtube_seconds=13.000 result_wait_seconds=2.000 processing_dm_seconds=3.000 total_seconds=18.000',
                      log.output[0])
        self.assertEqual(str(sent[0].id), job.reports[play_key(play)])
        self.assertEqual(sent[0].edit.await_count, 2)
        description = sent[0].edit.call_args.kwargs['embed'].description
        self.assertIn('영상 일부 유실', description)
        self.assertEqual(description.count('목표 달성'), 2)
