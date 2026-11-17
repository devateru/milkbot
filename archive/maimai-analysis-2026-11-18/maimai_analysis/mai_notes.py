"""Read the public mai-notes catalog and its server-rendered Simai field."""

from dataclasses import dataclass
from html.parser import HTMLParser
import json
import re
from threading import Lock
from time import monotonic
import unicodedata
from urllib.parse import urlsplit

from note_scoring import calculate_note_scores
from song_lookup import title_key

from .simai import Simai, parse_simai

BASE = 'https://mai-notes.com'
TTL = 3600
UUID = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'


@dataclass(frozen=True)
class CachedChart:
    url: str
    source: str
    chart: Simai


class SimaiField(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reading = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'textarea':
            self.reading = dict(attrs).get('id') == 'simaiInput'

    def handle_endtag(self, tag):
        if tag == 'textarea':
            self.reading = False

    def handle_data(self, data):
        if self.reading:
            self.parts.append(data)


def chart_url(value: str) -> tuple[str, str]:
    parts = urlsplit(value.strip())
    match = re.fullmatch(f'/player/({UUID})/?', parts.path, flags=re.IGNORECASE)
    if parts.scheme != 'https' or parts.netloc.lower() != 'mai-notes.com' or not match:
        raise ValueError('https://mai-notes.com/player/채보ID 형식의 링크를 입력해주세요.')
    identifier = match[1].lower()
    return f'{BASE}/player/{identifier}', identifier


def field_key(value: str) -> str:
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def scores_match(chart: Simai, fields: dict) -> bool:
    return chart.counts == calculate_note_scores(fields)['counts']


def same_chart(meta, sheet, chart, artist):
    kind = {'standard': 'std', 'deluxe': 'dx'}.get(meta.get('type'))
    return (title_key(meta['title']) == title_key(chart.title) and
            (not artist or field_key(meta['artist']) == field_key(artist)) and kind == chart.kind and
            field_key(sheet['difficulty']).replace(':', '') == chart.difficulty)


class MaiNotes:
    def __init__(self, store):
        self.store = store
        self.lock = Lock()
        self.manifest = None
        self.expires = 0

    @staticmethod
    def get_text(url, limit):
        import requests

        with requests.get(url, stream=True, timeout=(5, 10), allow_redirects=False) as response:
            if response.status_code != 200:
                raise ValueError(f'mai-notes에서 채보를 읽을 수 없습니다. (HTTP {response.status_code})')
            data = bytearray()
            for block in response.iter_content(65536):
                data.extend(block)
                if len(data) > limit:
                    raise ValueError('mai-notes 응답 크기가 지원 범위를 벗어났습니다.')
        return data.decode('utf-8-sig')

    def catalog(self):
        with self.lock:
            if self.manifest is None or monotonic() >= self.expires:
                manifest = json.loads(self.get_text(f'{BASE}/data/manifest.json', 12 * 1024 * 1024))
                self.manifest = manifest['songs'], {row['id']: row for row in manifest['charts']}
                self.expires = monotonic() + TTL
            return self.manifest

    def metadata(self, identifier):
        songs, charts = self.catalog()
        sheet = charts.get(identifier)
        if sheet is None or not sheet.get('has_chart_data'):
            raise ValueError('mai-notes 목록에 simai 데이터가 있는 채보를 찾을 수 없습니다.')
        return songs[sheet['song_id']], sheet

    def find_link(self, chart, song):
        import requests

        try:
            songs, charts = self.catalog()
            matches = [identifier for identifier, row in charts.items() if row.get('has_chart_data') and
                       same_chart(songs[row['song_id']], row, chart, song.get('artist'))]
        except (KeyError, TypeError, ValueError, requests.RequestException) as error:
            raise ValueError('mai-notes 목록에서 링크를 조회할 수 없습니다. 채보링크를 직접 입력해주세요.') from error
        if len(matches) != 1:
            reason = '여러 개입니다' if matches else '없습니다'
            raise ValueError(f'일치하는 mai-notes 채보가 {reason}. 채보링크를 직접 입력해주세요.')
        return chart_url(f'{BASE}/player/{matches[0]}')[0]

    def load(self, value, chart, song, selected) -> CachedChart:
        import requests

        url, identifier = chart_url(value)
        cached = self.store.cached_chart(url, chart.key)
        if cached is not None:
            if selected.get('noteCounts') and not scores_match(cached.chart, selected['noteCounts']):
                raise ValueError('캐시한 채보와 현재 곡 DB의 노트 수가 일치하지 않습니다.')
            return cached
        try:
            meta, sheet = self.metadata(identifier)
            if not same_chart(meta, sheet, chart, song.get('artist')):
                raise ValueError('mai-notes의 곡·아티스트·ST/DX·난이도가 선택한 채보와 일치하지 않습니다.')
            parser = SimaiField()
            parser.feed(self.get_text(url, 2 * 1024 * 1024))
            simai = ''.join(parser.parts).strip()
            if not simai:
                raise ValueError('mai-notes 페이지의 simai 입력란에서 채보를 읽을 수 없습니다.')
            parsed = parse_simai(simai, chart.difficulty)
            listed = {'tap': sheet['taps'], 'hold': sheet['hold'], 'slide': sheet['slide'],
                      'touch': sheet['touch'], 'break': sheet['breaks'], 'total': sheet['notes']}
            if not scores_match(parsed, listed):
                raise ValueError('simai와 mai-notes 목록의 유형별 노트 수가 일치하지 않습니다.')
            if selected.get('noteCounts') and not scores_match(parsed, selected['noteCounts']):
                raise ValueError('simai와 곡 DB의 유형별 노트 수가 일치하지 않습니다.')
        except (KeyError, TypeError, requests.RequestException) as error:
            raise ValueError('mai-notes 목록 또는 페이지에서 채보 데이터를 확인할 수 없습니다.') from error
        cached = CachedChart(url, simai, parsed)
        self.store.cache_chart(chart.key, cached)
        return cached
