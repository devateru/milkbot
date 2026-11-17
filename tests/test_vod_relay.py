from threading import Thread
from unittest import TestCase
from unittest.mock import Mock, patch

import requests

from maimai_analysis.media import Decoder, Image, MediaError, Source
from maimai_analysis.vod_relay import read_vod_frames, resolve_for_bot, serve
from maimai_analysis.youtube import Video


class VodRelayTests(TestCase):
    video = Video('O-ErNwyDSCU', 0)
    source = Source('https://example.com/replay', {}, 100, None)

    def test_server_replays_windows_frames_with_original_times_and_bytes(self):
        frames = [Image(18.25, bytes(320 * 180)), Image(18.5, bytes([255]) * (320 * 180))]
        windows = Mock(vod=Mock(return_value=(frame for frame in frames)))
        with patch('maimai_analysis.vod_relay.resolve', return_value=self.source) as lookup, \
                patch('maimai_analysis.vod_relay.Decoder', return_value=windows) as decoder:
            with serve(0, 'local-test-token') as server:
                runner = Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
                runner.start()
                try:
                    base = f'http://127.0.0.1:{server.server_port}'
                    reply = requests.get(f'{base}/video/{self.video.id}', timeout=2)
                    self.assertEqual(reply.status_code, 401)
                    with patch.dict('os.environ', {'MAIMAI_VOD_RELAY_PORT': str(server.server_port),
                                                   'MAIMAI_VOD_RELAY_TOKEN': 'local-test-token'}):
                        remote = resolve_for_bot(self.video, False, 180)
                        output = list(Decoder(width=320, height=180).vod(remote, 18.25, 18.6, fps=30))
                    self.assertEqual(output, frames)
                    self.assertEqual(remote.duration, 100)
                    lookup.assert_called_once_with(self.video, False, 180)
                    windows.vod.assert_called_once_with(self.source, 18.25, 18.6)
                    decoder.assert_called_once_with(width=320, height=180, fps=30)
                finally:
                    server.shutdown()
                    runner.join()

    def test_windows_live_relay_preserves_epoch_and_discontinuity(self):
        source = Source('https://example.com/live', {}, None, 1700000000, 'm3u8')
        frames = [Image(18.25, bytes(320 * 180), 1700000018.25, True)]
        windows = Mock(live=Mock(return_value=(frame for frame in frames)))
        with patch('maimai_analysis.vod_relay.resolve', return_value=source) as lookup, \
                patch('maimai_analysis.vod_relay.Decoder', return_value=windows):
            with serve(0, 'local-test-token') as server:
                runner = Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
                runner.start()
                try:
                    with patch.dict('os.environ', {'MAIMAI_VOD_RELAY_PORT': str(server.server_port),
                                                   'MAIMAI_VOD_RELAY_TOKEN': 'local-test-token'}):
                        remote = resolve_for_bot(self.video, True, 180)
                        self.assertEqual(list(Decoder(width=320, height=180).live(remote, None)), frames)
                    lookup.assert_called_once_with(self.video, True, 180)
                    windows.live.assert_called_once_with(source, None)
                finally:
                    server.shutdown()
                    runner.join()

    def test_vod_retries_from_last_timestamp_without_replaying_frames(self):
        def interrupted():
            yield Image(0, b'a')
            yield Image(0.25, b'b')
            raise MediaError('interrupted')

        with patch('maimai_analysis.vod_relay.read_frames', side_effect=[
                interrupted(), (frame for frame in [Image(0.25, b'b'), Image(0.5, b'c'), Image(0.75, b'd')])]) as read, \
                patch('maimai_analysis.vod_relay.time.sleep'):
            result = list(read_vod_frames(self.source, 0, 1, 320, 180, 4))
        self.assertEqual([frame.time for frame in result], [0, .25, .5, .75])
        self.assertAlmostEqual(read.call_args.args[1], .25)

    def test_unavailable_relay_falls_back_for_live_and_vod(self):
        environment = {'MAIMAI_VOD_RELAY_PORT': '18765', 'MAIMAI_VOD_RELAY_TOKEN': 'local-test-token'}
        with patch.dict('os.environ', environment), \
                patch('maimai_analysis.vod_relay.requests.get', side_effect=requests.ConnectionError) as request, \
                patch('maimai_analysis.vod_relay.resolve', return_value=self.source) as lookup:
            self.assertEqual(resolve_for_bot(self.video, True, 720), self.source)
            request.assert_called_once()
            self.assertEqual(resolve_for_bot(self.video, False, 720), self.source)
            self.assertEqual(lookup.call_args.args, (self.video, False, 720))
            lookup.side_effect = MediaError('YouTube가 이 서버에 로그인 확인을 요구합니다.')
            with self.assertRaisesRegex(MediaError, 'Windows PC'):
                resolve_for_bot(self.video, False, 720)
