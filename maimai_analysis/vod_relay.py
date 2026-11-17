"""Read YouTube frames on a PC through a loopback-only SSH forward."""

from contextlib import closing
from dataclasses import replace
from functools import lru_cache
from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import chain
import json
import logging
import math
import os
from struct import Struct
from threading import BoundedSemaphore, Lock
import time
from urllib.parse import parse_qs, urlsplit
import zlib

import requests
from urllib3.exceptions import HTTPError

from youtube_live import YouTubeLiveError, get_broadcast_start

from .media import DVRRangeError, Decoder, Image, MediaError, Source, resolve
from .youtube import VIDEO_ID, Video


log = logging.getLogger(__name__)
PROTOCOL = 'vod-relay'
PACKET = Struct('!ddBI')
TIMEOUT = (3, 55)
VOD_WINDOW = 120


def relay_error(response, default):
    if response.headers.get('Content-Type') == 'application/json':
        try:
            data = response.json()
            message = data['error']
            if isinstance(message, str):
                return (DVRRangeError if data.get('outside_dvr') else MediaError)(message)
        except (ValueError, TypeError, KeyError):
            pass
    return MediaError(default)


@lru_cache(maxsize=64)
def verified_start(video_id):
    stamp = get_broadcast_start(video_id)
    if stamp is None:
        raise YouTubeLiveError('YouTube did not report an actual start')
    return stamp


def with_verified_start(video, source, live):
    if not live or source.epoch is None:
        return source
    try:
        actual = verified_start(video.id)
    except (YouTubeLiveError, ValueError):
        return source
    return replace(source, actual_epoch=actual) if abs(actual - source.epoch) <= 2 else source


def resolve_for_bot(video, live, height):
    port = os.getenv('MAIMAI_VOD_RELAY_PORT')
    if not port:
        return with_verified_start(video, resolve(video, live, height), live)
    token = os.getenv('MAIMAI_VOD_RELAY_TOKEN')
    if not token:
        raise MediaError('Windows PC 영상 연결의 인증 설정을 확인해주세요.')
    url = f'http://127.0.0.1:{int(port)}/video/{video.id}'
    headers = {'Authorization': f'Bearer {token}'}
    try:
        response = requests.get(url, headers=headers, params={'height': height, 'live': int(live)}, timeout=TIMEOUT,
                                allow_redirects=False)
    except requests.RequestException:
        log.warning('maimai Windows VOD relay unavailable video=%s', video.id)
        try:
            return with_verified_start(video, resolve(video, live, height), live)
        except MediaError as problem:
            raise MediaError(f'{problem} Windows PC의 영상 연결도 확인할 수 없습니다.') from problem
    if response.status_code == 401:
        raise MediaError('Windows PC 영상 연결의 인증 설정을 확인해주세요.')
    if response.status_code != 200:
        raise relay_error(response, 'Windows PC에서도 YouTube 영상을 열 수 없습니다.')
    try:
        metadata = response.json()
        timing = float(metadata['epoch' if live else 'duration'])
    except (ValueError, TypeError, KeyError) as problem:
        raise MediaError('Windows PC에서 돌아온 영상 길이를 확인할 수 없습니다.') from problem
    if not math.isfinite(timing) or timing <= 0:
        raise MediaError('Windows PC에서 돌아온 영상 길이를 확인할 수 없습니다.')
    return with_verified_start(video, Source(url, headers, None if live else timing, timing if live else None,
                                             PROTOCOL), live)


def read_frames(source, start, end, width, height, fps, *, live=False):
    frame_size = width * height
    params = {'start': start, 'end': end, 'width': width, 'height': height, 'fps': fps, 'live': int(live),
              'actual_epoch': source.actual_epoch if live else None}
    try:
        with requests.get(source.url + '/frames', headers=source.headers, params=params,
                          timeout=TIMEOUT, allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise relay_error(response, 'Windows PC에서 영상 프레임을 읽지 못했습니다.')
            while header := response.raw.read(PACKET.size):
                if len(header) != PACKET.size:
                    break
                timestamp, epoch, discontinuity, length = PACKET.unpack(header)
                if not length:
                    return
                if length > frame_size + 65536 or not math.isfinite(timestamp) or not math.isfinite(epoch):
                    break
                zipped = zlib.decompressobj()
                frame = zipped.decompress(response.raw.read(length), frame_size + 1)
                if len(frame) != frame_size or not zipped.eof:
                    break
                yield Image(timestamp, frame, epoch or None, bool(discontinuity))
    except (requests.RequestException, HTTPError, OSError, zlib.error) as problem:
        raise MediaError('Windows PC에서 영상 프레임을 받다가 연결이 끊겼습니다.') from problem
    raise MediaError('Windows PC에서 영상 프레임을 끝까지 받지 못했습니다.')


def read_vod_frames(source, start, end, width, height, fps, *, stop=None):
    end = source.duration if end is None else end
    last = float('-inf')
    while start < end:
        if stop is not None and stop.is_set():
            return
        boundary = min(start + VOD_WINDOW, end)
        cursor = start
        stalled = 0
        while True:
            previous = last
            try:
                with closing(read_frames(source, cursor, boundary, width, height, fps)) as frames:
                    for frame in frames:
                        if frame.time > last:
                            last = frame.time
                            cursor = min(last, math.nextafter(boundary, start))
                            yield frame
                if last < boundary - max(.15, 2 / fps):
                    raise MediaError('Windows PC에서 요청한 구간의 마지막 프레임을 받지 못했습니다.')
                break
            except MediaError as problem:
                if stop is not None and stop.is_set():
                    return
                stalled = 0 if last > previous else stalled + 1
                log.warning('maimai Windows VOD relay interrupted position=%.3f stalled=%d', cursor, stalled)
                if stalled >= 3:
                    raise MediaError(f'{problem} 영상 시각 {cursor:.1f}초에서 재시도를 완료하지 못했습니다.') from problem
                if stop is None:
                    time.sleep(2)
                elif stop.wait(2):
                    return
        start = boundary


def serve(port, token):
    authorization = f'Bearer {token}'.encode()
    stream_lock = Lock()
    live_slots = BoundedSemaphore(8)

    @lru_cache(maxsize=8)
    def lookup(video_id, live, height, slot):
        return resolve(Video(video_id, 0), live, height)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send_json(self, status, data):
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

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
                live = query.get('live', ['0'])[0] == '1'
                if not 180 <= height <= 1080:
                    raise ValueError
                if len(route) == 4:
                    width, fps = (int(query[name][0]) for name in ('width', 'fps'))
                    start = float(query['start'][0]) if 'start' in query else None
                    end = None if live else float(query['end'][0])
                    if (not (320 <= width <= 1920 and 2 <= fps <= 30)
                            or (start is not None and not 0 <= start < math.inf)
                            or (not live and (start is None or not start < end < math.inf))):
                        raise ValueError
            except (ValueError, KeyError):
                self.send_error(400)
                return
            try:
                source = lookup(route[2], live, height, int(time.monotonic() // 900))
                if not (source.epoch if live else source.duration):
                    raise MediaError('YouTube 다시보기의 영상 길이를 확인하지 못했습니다.')
            except MediaError as problem:
                self.send_json(502, {'error': str(problem)})
                return
            except requests.RequestException:
                self.send_error(502)
                return
            if len(route) == 3:
                self.send_json(200, {'duration': source.duration, 'epoch': source.epoch})
                return
            if live and 'actual_epoch' in query:
                try:
                    actual = float(query['actual_epoch'][0])
                except ValueError:
                    self.send_error(400)
                    return
                if abs(actual - source.epoch) <= 2:
                    source = replace(source, actual_epoch=actual)
            slot = live_slots if live else stream_lock
            if not slot.acquire(blocking=False):
                self.send_error(503)
                return
            try:
                self.stream(source, start, end, width, height, fps, live)
            finally:
                slot.release()

        def stream(self, source, start, end, width, height, fps, live):
            started = False
            decoder = Decoder(width=width, height=height, fps=fps)
            try:
                with closing(decoder.live(source, start) if live else decoder.vod(source, start, end)) as frames:
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
                        self.wfile.write(PACKET.pack(frame.time, frame.epoch or 0, frame.discontinuity, len(data))
                                         + data)
                    self.wfile.write(PACKET.pack(0, 0, 0, 0))
            except OSError:
                return
            except (MediaError, requests.RequestException) as problem:
                lookup.cache_clear()
                log.warning('maimai Windows VOD relay decode failed: %s', type(problem).__name__)
                if not started:
                    if isinstance(problem, MediaError):
                        self.send_json(502, {'error': str(problem), 'outside_dvr': isinstance(problem, DVRRangeError)})
                    else:
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
