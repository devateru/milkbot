"""Read YouTube VOD frames on a PC through a loopback-only SSH forward."""

from contextlib import closing
from functools import lru_cache
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import chain
import json
import logging
import math
import os
from struct import Struct
from threading import Lock
import time
from urllib.parse import parse_qs, urlsplit
import zlib

import requests
from urllib3.exceptions import HTTPError

from .media import Decoder, Image, MediaError, Source, resolve
from .youtube import VIDEO_ID, Video


log = logging.getLogger(__name__)
PROTOCOL = 'vod-relay'
PACKET = Struct('!dI')
TIMEOUT = (3, 50)


def resolve_for_bot(video, live, height):
    port = os.getenv('MAIMAI_VOD_RELAY_PORT')
    if live or not port:
        return resolve(video, live, height)
    token = os.getenv('MAIMAI_VOD_RELAY_TOKEN')
    if not token:
        raise MediaError('Windows PC 영상 연결의 인증 설정을 확인해주세요.')
    url = f'http://127.0.0.1:{int(port)}/video/{video.id}'
    headers = {'Authorization': f'Bearer {token}'}
    try:
        response = requests.get(url, headers=headers, params={'height': height}, timeout=TIMEOUT,
                                allow_redirects=False)
    except requests.RequestException:
        log.warning('maimai Windows VOD relay unavailable video=%s', video.id)
        try:
            return resolve(video, live, height)
        except MediaError as problem:
            raise MediaError(f'{problem} Windows PC의 다시보기 연결도 확인할 수 없습니다.') from problem
    if response.status_code == 401:
        raise MediaError('Windows PC 영상 연결의 인증 설정을 확인해주세요.')
    if response.status_code != 200:
        raise MediaError('Windows PC에서도 YouTube 다시보기를 열 수 없습니다.')
    try:
        duration = float(response.json()['duration'])
    except (ValueError, TypeError, KeyError) as problem:
        raise MediaError('Windows PC에서 돌아온 영상 길이를 확인할 수 없습니다.') from problem
    if not math.isfinite(duration) or duration <= 0:
        raise MediaError('Windows PC에서 돌아온 영상 길이를 확인할 수 없습니다.')
    return Source(url, headers, duration, None, PROTOCOL)


def read_frames(source, start, end, width, height, fps):
    frame_size = width * height
    params = {'start': start, 'end': end if end is not None else source.duration,
              'width': width, 'height': height, 'fps': fps}
    try:
        with requests.get(source.url + '/frames', headers=source.headers, params=params,
                          timeout=TIMEOUT, allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise MediaError('Windows PC에서 다시보기 프레임을 읽지 못했습니다.')
            while header := response.raw.read(PACKET.size):
                if len(header) != PACKET.size:
                    break
                timestamp, length = PACKET.unpack(header)
                if not length:
                    return
                if length > frame_size + 65536 or not math.isfinite(timestamp):
                    break
                zipped = zlib.decompressobj()
                frame = zipped.decompress(response.raw.read(length), frame_size + 1)
                if len(frame) != frame_size or not zipped.eof:
                    break
                yield Image(timestamp, frame)
    except (requests.RequestException, HTTPError, OSError, zlib.error) as problem:
        raise MediaError('Windows PC에서 다시보기 프레임을 받다가 연결이 끊겼습니다.') from problem
    raise MediaError('Windows PC에서 다시보기 프레임을 끝까지 받지 못했습니다.')


def serve(port, token):
    authorization = f'Bearer {token}'.encode()
    stream_lock = Lock()

    @lru_cache(maxsize=8)
    def lookup(video_id, height, slot):
        return resolve(Video(video_id, 0), False, height)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if not compare_digest(self.headers.get('Authorization', '').encode(), authorization):
                self.send_error(401)
                return
            parts = urlsplit(self.path)
            route = parts.path.split('/')
            if (len(route) not in (3, 4) or route[1] != 'video' or not VIDEO_ID.fullmatch(route[2])
                    or (len(route) == 4 and route[3] != 'frames')):
                self.send_error(404)
                return
            query = parse_qs(parts.query)
            try:
                height = int(query['height'][0])
                if not 180 <= height <= 1080:
                    raise ValueError
                if len(route) == 4:
                    width, fps = (int(query[name][0]) for name in ('width', 'fps'))
                    start, end = (float(query[name][0]) for name in ('start', 'end'))
                    if not (320 <= width <= 1920 and 2 <= fps <= 30 and 0 <= start < end < math.inf):
                        raise ValueError
            except (ValueError, KeyError):
                self.send_error(400)
                return
            try:
                source = lookup(route[2], height, int(time.monotonic() // 900))
                if not source.duration:
                    raise MediaError('YouTube 다시보기의 영상 길이를 확인하지 못했습니다.')
            except (MediaError, requests.RequestException):
                self.send_error(502)
                return
            if len(route) == 3:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'duration': source.duration}).encode())
                return
            if not stream_lock.acquire(blocking=False):
                self.send_error(503)
                return
            try:
                self.stream(source, start, end, width, height, fps)
            finally:
                stream_lock.release()

        def stream(self, source, start, end, width, height, fps):
            started = False
            try:
                with closing(Decoder(width=width, height=height, fps=fps).vod(source, start, end)) as frames:
                    first = next(frames, None)
                    if first is None:
                        self.send_error(502)
                        return
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.end_headers()
                    started = True
                    for frame in chain((first,), frames):
                        data = zlib.compress(frame.pixels, 1)
                        self.wfile.write(PACKET.pack(frame.time, len(data)) + data)
                    self.wfile.write(PACKET.pack(0, 0))
            except OSError:
                return
            except (MediaError, requests.RequestException) as problem:
                log.warning('maimai Windows VOD relay decode failed: %s', type(problem).__name__)
                if not started:
                    self.send_error(502)

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    import argparse
    import shutil
    import subprocess
    from threading import Event, Thread

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18765)
    parser.add_argument('--ssh-host')
    parser.add_argument('--ssh-key')
    args = parser.parse_args()
    token = os.getenv('MAIMAI_VOD_RELAY_TOKEN')
    if not token or bool(args.ssh_host) != bool(args.ssh_key):
        parser.error('Set MAIMAI_VOD_RELAY_TOKEN and provide both SSH options when using a tunnel')
    if not os.getenv('MAIMAI_FFMPEG') and not shutil.which('ffmpeg'):
        import imageio_ffmpeg

        os.environ['MAIMAI_FFMPEG'] = imageio_ffmpeg.get_ffmpeg_exe()
    os.environ.pop('MAIMAI_YOUTUBE_COOKIES', None)
    logging.basicConfig(level=logging.INFO)
    stop = Event()

    def tunnel():
        forward = f'127.0.0.1:{args.port}:127.0.0.1:{args.port}'
        command = ['ssh', '-N', '-R', forward, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                   '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
                   '-i', args.ssh_key, args.ssh_host]
        while not stop.is_set():
            with subprocess.Popen(command) as process:
                while process.poll() is None:
                    if stop.wait(2):
                        process.terminate()
                        break
            stop.wait(5)

    with serve(args.port, token) as server:
        forwarder = Thread(target=tunnel, daemon=True) if args.ssh_host else None
        if forwarder:
            forwarder.start()
        try:
            server.serve_forever()
        finally:
            stop.set()
            if forwarder:
                forwarder.join()


if __name__ == '__main__':
    main()
