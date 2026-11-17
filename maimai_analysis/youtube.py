"""Validate user video URLs and map live HLS segments to YouTube time."""

from dataclasses import dataclass
from datetime import datetime
import math
import re
from urllib.parse import parse_qs, urljoin, urlsplit


VIDEO_ID = re.compile(r'[A-Za-z0-9_-]{11}')
YOUTUBE_HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'}


@dataclass(frozen=True)
class Video:
    id: str
    start: int

    @property
    def url(self) -> str:
        return f'https://www.youtube.com/watch?v={self.id}'


def parse_time(value: str) -> float:
    value = value.strip()
    if re.fullmatch(r'\d+(?:\.\d{1,3})?', value):
        time = float(value)
    elif re.fullmatch(r'(?:\d+:)?\d+:\d{2}(?:\.\d{1,3})?', value):
        components = value.split(':')
        if float(components[-1]) >= 60 or (len(components) == 3 and int(components[-2]) >= 60):
            raise ValueError('타임스탬프의 분/초가 60 이상입니다.')
        time = sum(float(item) * 60 ** i for i, item in enumerate(reversed(components)))
    elif re.fullmatch(r'(?=\d)(?:\d+h)?(?:\d+m)?(?:\d+s)?', value):
        time = sum(int(number) * {'h': 3600, 'm': 60, 's': 1}[unit]
                   for number, unit in re.findall(r'(\d+)([hms])', value))
    else:
        raise ValueError('시간은 초, MM:SS 또는 HH:MM:SS 형식으로 입력해주세요.')
    if not math.isfinite(time) or time > 7 * 24 * 3600:
        raise ValueError('영상 시간이 지원 범위를 벗어났습니다.')
    return time


def parse_video(url: str) -> Video:
    parts = urlsplit(url.strip())
    query = parse_qs(parts.query)
    path = parts.path.strip('/').split('/')
    video_id = ''
    if parts.scheme in {'https', 'http'} and parts.netloc.lower() in YOUTUBE_HOSTS:
        if parts.netloc.lower() == 'youtu.be' and len(path) == 1:
            video_id = path[0]
        elif path == ['watch']:
            video_id = query.get('v', [''])[0]
        elif len(path) == 2 and path[0] in {'live', 'shorts', 'embed'}:
            video_id = path[1]
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError('개별 YouTube 영상 또는 라이브 링크를 입력해주세요.')
    fragment = parse_qs(parts.fragment)
    offset = (query.get('t') or query.get('start') or fragment.get('t') or ['0'])[0]
    return Video(video_id, int(parse_time(offset)))


def video_link(video_id: str, seconds: float) -> str:
    return f'https://www.youtube.com/watch?v={video_id}&t={max(0, int(seconds))}'


@dataclass(frozen=True)
class Segment:
    sequence: int
    epoch: float
    duration: float
    url: str
    discontinuity: bool


def parse_hls(text: str, base: str) -> tuple[list[Segment], bool]:
    """Read a timestamped, independently decodable MPEG-TS media playlist."""
    if not text.startswith('#EXTM3U'):
        raise ValueError('YouTube HLS 재생 목록을 읽지 못했습니다.')
    sequence = 0
    epoch = None
    length = None
    broken = ended = False
    pending = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('#EXT-X-MEDIA-SEQUENCE:'):
            sequence = int(line.split(':', 1)[1])
        elif line.startswith('#EXT-X-PROGRAM-DATE-TIME:'):
            stamp = datetime.fromisoformat(line.split(':', 1)[1].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('라이브 세그먼트의 시간대가 누락되었습니다.')
            epoch = stamp.timestamp()
            # HLS allows the first anchor to appear after preceding segments.
            for i in range(len(pending) - 1, -1, -1):
                seq, known, duration, uri, discontinuity = pending[i]
                if known is not None or broken:
                    break
                known = (epoch if i == len(pending) - 1 else pending[i + 1][1]) - duration
                pending[i] = (seq, known, duration, uri, discontinuity)
                if discontinuity:
                    break
        elif line.startswith('#EXTINF:'):
            length = float(line.split(':', 1)[1].split(',', 1)[0])
        elif line == '#EXT-X-DISCONTINUITY':
            epoch = None
            broken = True
        elif line == '#EXT-X-ENDLIST':
            ended = True
        elif line.startswith(('#EXT-X-MAP:', '#EXT-X-BYTERANGE:', '#EXT-X-KEY:')):
            raise ValueError('이 HLS 세그먼트 형식은 지원하지 않습니다.')
        elif line and not line.startswith('#') and length is not None:
            if not 0 < length <= 30:
                raise ValueError('HLS 세그먼트 길이가 올바르지 않습니다.')
            uri = urljoin(base, line)
            if urlsplit(uri).scheme != 'https':
                raise ValueError('HTTPS 라이브 세그먼트가 필요합니다.')
            pending.append((sequence, epoch, length, uri, broken))
            if epoch is not None:
                epoch += length
            sequence += 1
            length = None
            broken = False
    if not pending or any(row[1] is None for row in pending):
        raise ValueError('라이브 DVR의 영상 시각을 확인할 프로그램 타임스탬프가 없습니다.')
    return [Segment(*row) for row in pending], ended
