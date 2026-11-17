from threading import Thread
from unittest import TestCase
from unittest.mock import Mock, patch

import requests

from maimai_analysis.media import Decoder, Image, MediaError, Source
from maimai_analysis.vod_relay import resolve_for_bot, serve
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
                        output = list(Decoder(width=320, height=180).vod(remote, 18.25, 19, fps=30))
                    self.assertEqual(output, frames)
                    self.assertEqual(remote.duration, 100)
                    lookup.assert_called_once_with(self.video, False, 180)
                    windows.vod.assert_called_once_with(self.source, 18.25, 19)
                    decoder.assert_called_once_with(width=320, height=180, fps=30)
                finally:
                    server.shutdown()
                    runner.join()

    def test_live_stays_local_and_unavailable_relay_falls_back_for_vod(self):
        environment = {'MAIMAI_VOD_RELAY_PORT': '18765', 'MAIMAI_VOD_RELAY_TOKEN': 'local-test-token'}
        with patch.dict('os.environ', environment), \
                patch('maimai_analysis.vod_relay.requests.get', side_effect=requests.ConnectionError) as request, \
                patch('maimai_analysis.vod_relay.resolve', return_value=self.source) as lookup:
            self.assertEqual(resolve_for_bot(self.video, True, 720), self.source)
            request.assert_not_called()
            self.assertEqual(resolve_for_bot(self.video, False, 720), self.source)
            self.assertEqual(lookup.call_args.args, (self.video, False, 720))
            lookup.side_effect = MediaError('YouTube가 이 서버에 로그인 확인을 요구합니다.')
            with self.assertRaisesRegex(MediaError, 'Windows PC'):
                resolve_for_bot(self.video, False, 720)
