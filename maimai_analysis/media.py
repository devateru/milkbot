"""Bounded YouTube HTTP reads and timestamped FFmpeg grayscale samples."""

from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from queue import Queue
import re
import subprocess
from threading import Thread
import time
from urllib.parse import urlsplit

from .youtube import Video, parse_hls

log = logging.getLogger(__name__)
RANGE_SIZE = 4 * 1024 * 1024
HTTP_TIMEOUT = (6, 10)
PTS = re.compile(rb'\bn:\s*\d+\s+pts:\s*-?\d+\s+pts_time:([\d.eE+-]+)')


class MediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class Source:
    url: str
    headers: dict[str, str]
    duration: float | None
    epoch: float | None
    protocol: str = 'https'


@dataclass(frozen=True)
class Image:
    time: float
    pixels: bytes
    epoch: float | None = None
    discontinuity: bool = False


def resolve(video: Video, live: bool, height: int) -> Source:
    import yt_dlp

    fmt = (f'b[protocol^=m3u8][height<={height}]/bv[protocol^=m3u8][height<={height}]'
           if live else f'bv[protocol=https][vcodec^=avc1][height<={height}]/'
                        f'b[protocol=https][height<={height}]/b[protocol^=m3u8][height<={height}]')
    options = {'quiet': True, 'no_warnings': True, 'noplaylist': True, 'format': fmt,
               'socket_timeout': 10, 'extractor_retries': 1}
    runtime = os.getenv('MAIMAI_YOUTUBE_DENO')
    if runtime:
        options['js_runtimes'] = {'deno': {'path': runtime}}
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            row = downloader.extract_info(video.url, download=False)
    except yt_dlp.utils.DownloadError as error:
        raise MediaError('YouTube 영상 스트림을 열 수 없습니다. 공개 범위와 미디어 형식을 확인해주세요.') from error
    if row.get('is_live', False) != live:
        raise MediaError('현재 방송 중인 영상만 라이브 분석에서 열 수 있습니다.' if live else
                         '라이브 방송은 /라이브분석에서 열어주세요.')
    epoch = row.get('release_timestamp')
    if live and not epoch:
        raise MediaError('YouTube가 실제 방송 시작 시각을 제공하지 않았습니다.')
    if urlsplit(row['url']).scheme != 'https':
        raise MediaError('HTTPS YouTube 스트림이 필요합니다.')
    return Source(row['url'], row.get('http_headers', {}), row.get('duration'), epoch, row.get('protocol', 'https'))


@contextmanager
def vod_input(source: Source):
    """Expose bounded CDN range requests as a seekable input for FFmpeg."""
    import requests

    def fetch(session, start, last):
        return session.get(source.url, headers={**source.headers, 'Range': f'bytes={start}-{last}'},
                           stream=True, timeout=HTTP_TIMEOUT)

    with requests.Session() as probe, fetch(probe, 0, 0) as response:
        span = re.fullmatch(r'bytes 0-0/(\d+)', response.headers.get('Content-Range', ''))
        if response.status_code != 206 or not span:
            raise MediaError('YouTube 다시보기에서 바이트 범위 요청을 사용할 수 없습니다.')
        size = int(span[1])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', self.headers.get('Range', 'bytes=0-'))
            start = int(match[1]) if match else size
            end = min(int(match[2]), size - 1) if match and match[2] else size - 1
            if self.path != '/video' or not 0 <= start <= end:
                self.send_error(416)
                return
            try:
                with requests.Session() as session:
                    for cursor in range(start, end + 1, RANGE_SIZE):
                        last = min(cursor + RANGE_SIZE - 1, end)
                        with fetch(session, cursor, last) as response:
                            if (response.status_code != 206 or response.headers.get('Content-Range')
                                    != f'bytes {cursor}-{last}/{size}'):
                                if cursor == start:
                                    self.send_error(502)
                                break
                            if cursor == start:
                                self.send_response(206)
                                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                                self.send_header('Content-Length', str(end - start + 1))
                                self.send_header('Content-Type', response.headers.get('Content-Type', 'video/mp4'))
                                self.end_headers()
                            for block in response.iter_content(65536):
                                self.wfile.write(block)
            except (OSError, requests.RequestException):
                # Seeking or stopping FFmpeg commonly closes an outstanding request.
                return

    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}/video'
        finally:
            server.shutdown()
            thread.join()


class Decoder:
    def __init__(self, width=1280, height=720, fps=6):
        self.width, self.height, self.fps = width, height, fps
        self.ffmpeg = os.getenv('MAIMAI_FFMPEG', 'ffmpeg')

    def frames(self, url, offset, length=None, *, headers=None, epoch=None):
        command = [self.ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'info',
                   '-rw_timeout', '12000000', '-threads', '2', '-filter_threads', '1']
        if headers:
            command += ['-headers', ''.join(f'{k}: {v}\r\n' for k, v in headers.items())]
        if epoch is None:
            command += ['-ss', str(offset)]
        command += ['-i', url, '-an', '-sn', '-dn']
        if length is not None:
            command += ['-t', str(length)]
        interval = 1 / self.fps
        filters = (f"select='isnan(prev_selected_t)+gte(t-prev_selected_t+0.000001,{interval})',"
                   f'scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,'
                   f'pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,format=gray,showinfo')
        command += ['-vf', filters, *passthrough_option(self.ffmpeg), '-c:v', 'rawvideo',
                    '-threads', '1', '-f', 'rawvideo', 'pipe:1']
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError as error:
            raise MediaError('FFmpeg 실행 파일을 찾지 못했습니다.') from error
        timestamps = Queue()
        failure = []

        def read_timestamps():
            for line in process.stderr:
                if match := PTS.search(line):
                    timestamps.put(float(match[1]))
                elif b'corrupt' in line.lower() or b'error while decoding' in line.lower():
                    failure.append(True)
            timestamps.put(None)

        logs = Thread(target=read_timestamps, daemon=True)
        logs.start()
        count = 0
        try:
            frame_size = self.width * self.height
            while (data := process.stdout.read(frame_size)) and len(data) == frame_size:
                pts = timestamps.get(timeout=15)
                if pts is None:
                    raise MediaError('FFmpeg 프레임의 영상 시각이 누락되었습니다.')
                count += 1
                yield Image(offset + pts, data, epoch + pts if epoch is not None else None)
            if process.wait(timeout=15) or not count or failure:
                raise MediaError('FFmpeg에서 영상 프레임을 읽지 못했거나 프레임 손상이 감지되었습니다.')
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            logs.join(timeout=2)
            process.stdout.close()
            process.stderr.close()

    def vod(self, source, start, end):
        if source.duration is not None and start >= source.duration:
            raise MediaError('분석할 시작 시간이 영상 길이를 벗어납니다.')
        end = min(end, source.duration) if end is not None and source.duration else end
        length = end - start if end is not None else None
        if source.protocol.startswith('m3u8'):
            import requests

            response = requests.get(source.url, headers=source.headers, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            segments, ended = parse_hls(response.text, response.url)
            if not ended or segments[0].sequence != 0:
                raise MediaError('종료한 방송의 처음부터 재생 가능한 다시보기 목록이 아직 준비되지 않았습니다.')
            yield from self.frames(source.url, start, length, headers=source.headers)
            return
        with vod_input(source) as url:
            yield from self.frames(url, start, length)

    def live(self, source, requested, *, stop=None, busy=None):
        import requests

        with requests.Session() as session:
            sequence = last_end = None
            url = source.url
            stale_since = time.monotonic()
            failures = 0
            while stop is None or not stop.is_set():
                response = session.get(url, headers=source.headers, timeout=HTTP_TIMEOUT)
                response.raise_for_status()
                # yt-dlp normally resolves the media playlist. Some entries return a master.
                if (variant := re.search(r'(?m)^#EXT-X-STREAM-INF:[^\n]*\n([^#\r\n]+)', response.text)):
                    from urllib.parse import urljoin
                    url = urljoin(response.url, variant[1].strip())
                    continue
                segments, ended = parse_hls(response.text, response.url)
                if sequence is None:
                    if segments[0].sequence != 0:
                        raise MediaError('DVR에서 영상 0초에 해당하는 세그먼트를 확인하지 못했습니다.')
                    origin = segments[0].epoch
                    if abs(origin - source.epoch) > 120:
                        raise MediaError('라이브 DVR과 방송 시작 시각이 일치하지 않습니다.')
                    first, edge = segments[0].epoch - origin, segments[-1].epoch - origin
                    if requested is not None and not first - 0.5 <= requested <= edge + segments[-1].duration:
                        raise MediaError(f'요청 시각이 DVR 범위({max(0, int(first))}~{int(edge)}초)를 벗어났습니다.')
                    sequence = (segments[-1].sequence if requested is None else next(
                        (s.sequence for s in segments if s.epoch + s.duration - origin > requested),
                        segments[-1].sequence))
                    log.info('live DVR range first=%.3f edge=%.3f sequence=%d', first, edge, sequence)
                for segment in segments:
                    if segment.sequence < sequence:
                        continue
                    offset = segment.epoch - origin
                    gap = (segment.discontinuity or segment.sequence > sequence or
                           (last_end is not None and abs(offset - last_end) > 0.45))
                    if busy:
                        busy.set()
                    try:
                        for image in self.frames(segment.url, offset, segment.duration + 0.15,
                                                 headers=source.headers, epoch=segment.epoch):
                            if stop is not None and stop.is_set():
                                return
                            if image.time >= 0:
                                yield Image(image.time, image.pixels, image.epoch, gap)
                                gap = False
                        last_end = offset + segment.duration
                        failures = 0
                    except MediaError:
                        last_end = offset - 60  # mark the next usable image as discontinuous
                        failures += 1
                        log.warning('live segment failed sequence=%d offset=%.3f', segment.sequence, offset)
                        if failures >= 3:
                            raise TimeoutError('라이브 세그먼트를 연속해서 읽지 못했습니다.')
                    finally:
                        if busy:
                            busy.clear()
                    sequence = segment.sequence + 1
                    stale_since = time.monotonic()
                if ended:
                    return
                if time.monotonic() - stale_since > 45:
                    raise MediaError('45초 동안 새 라이브 세그먼트를 받지 못했습니다.')
                if stop is not None:
                    stop.wait(0.8)
                else:
                    time.sleep(0.8)


@lru_cache(maxsize=4)
def passthrough_option(ffmpeg):
    try:
        result = subprocess.run([ffmpeg, '-hide_banner', '-h', 'full'], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MediaError('FFmpeg 실행 파일을 열 수 없습니다.') from error
    return ('-fps_mode', 'passthrough') if b'-fps_mode' in result.stdout else ('-vsync', '0')
