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
from maimai_analysis.commands import parse_times, goals_embed, register_analysis
from maimai_analysis.delivery import Delivery
from maimai_analysis.hud import score_digits, early_judgments
from maimai_analysis.jobs import Job, play_key
from maimai_analysis.mai_notes import CachedChart
from maimai_analysis.media import Decoder, Image as VideoFrame, MediaError, Source, resolve
from maimai_analysis.scoring import Sample
from maimai_analysis.service import AnalysisService, resource_usage
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
        service.busy[self.video] = Event()
        plays = []
        scanner = asyncio.create_task(asyncio.to_thread(
            service.scan, self.video, Mock(), None, None, True, lambda: (job,),
            lambda event, play: plays.append(play) if event == 'finish' else None))
        self.assertTrue(await asyncio.to_thread(started.wait, 2))
        self.assertFalse(await service.toggle_guest(1))
        toggled.set()
        await scanner
        self.assertEqual([job.matches(play) for play in plays], [True, False])

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
        mocked.vod = Mock(side_effect=lambda *args: (f for f in frames))
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
        ])
        self.store.save_target(1, self.chart.key, self.cached, parse_sections('1:-.1,3:-.1', self.simai))
        await delivery.waiting(job)
        await delivery.started(job, play)
        self.store.save_target(1, self.chart.key, self.cached, parse_sections('1:-.3,3:-.3', self.simai))
        await delivery.finished(job, play)
        self.assertEqual(str(sent[0].id), job.reports[play_key(play)])
        self.assertEqual(sent[0].edit.await_count, 2)
        self.assertNotIn('미달성', sent[0].edit.call_args.kwargs['embed'].description)
