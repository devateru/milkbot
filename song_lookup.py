"""Alias-aware song autocomplete and deterministic chart selection."""

from difflib import SequenceMatcher
import hashlib
import json
import logging
from pathlib import Path
import re
import unicodedata

from song_search import get_data


ALIAS_PATH = Path(__file__).resolve().with_name('song_aliases.json')
DIFFICULTIES = {'basic', 'advanced', 'expert', 'master', 'remaster'}
INITIALS = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'


def normalize(text):
    text = unicodedata.normalize('NFKC', text).casefold()
    text = ''.join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ヶ' else c for c in text)
    compact = ''.join(c for c in text if c.isalnum())
    return compact or ''.join(text.split())


def initials(text):
    return ''.join(INITIALS[(ord(c) - 0xAC00) // 588] if '가' <= c <= '힣' else c
                   for c in text)


def title_key(text):
    return unicodedata.normalize('NFKC', re.sub(r'\s*\((DX|STD)\)\s*$', '', text)).casefold().strip()


def match_score(query, term):
    if query == term:
        return 0.0
    if term.startswith(query):
        return 1 + len(term) / 10000
    if query in term:
        return 2 + term.index(query) / 10000
    if len(query) >= 3:
        similarity = SequenceMatcher(None, query, term).ratio()
        if similarity >= 0.72:
            return 3 + (1 - similarity)
    return None


class SongLookup:
    def __init__(self, songs, aliases, region='intl'):
        self.songs = songs
        self.alias_path = None
        self.alias_stamp = None
        self.region = region
        self.entries = []
        self.selections = {}
        by_title = {}
        catalog_keys = {title_key(song['title']) for song in songs}
        catalog_normalized = {}
        for key in catalog_keys:
            catalog_normalized.setdefault(normalize(key), set()).add(key)
        for row in aliases:
            terms = [row['title'], *row.get('aliases', [])]
            key = title_key(row['title'])
            targets = {key} if key in catalog_keys else catalog_normalized.get(normalize(key), set())
            if not targets:
                # Some wiki titles differ from the game's title. Match against
                # the row's aliases only when its own title has no catalog match.
                targets = {title_key(term) for term in terms if title_key(term) in catalog_keys}
                if not targets:
                    targets = set().union(*(catalog_normalized.get(normalize(title_key(term)), set())
                                           for term in terms))
            if len(targets) == 1:
                by_title.setdefault(next(iter(targets)), set()).update(terms)
        for song in songs:
            title = song['title']
            terms = by_title.get(title_key(title), set())
            search_terms = {normalize(t) for t in [title, *terms]}
            search_terms.update(normalize(initials(t)) for t in list(search_terms))
            types = {s['type'] for s in song['sheets'] if self.available(s)
                     and s['type'] in {'dx', 'std'} and s['difficulty'] in DIFFICULTIES}
            for type_ in ('dx', 'std'):
                if type_ not in types:
                    continue
                identity = song.get('songId', title)
                value = type_ + ':' + hashlib.sha256(identity.encode('utf-8')).hexdigest()
                label = f"[{'DX' if type_ == 'dx' else 'ST'}] {title}"
                self.selections[value] = (song, type_)
                self.entries.append({'name': label if len(label) <= 100 else label[:99] + '…',
                                     'value': value, 'terms': search_terms, 'title': title})

    def available(self, sheet):
        return not self.region or sheet.get('regions', {}).get(self.region, False)

    def autocomplete(self, query, limit=25):
        """Return [{name, value}], one option per available song/type pair."""
        self.reload_aliases_if_changed()
        query = normalize(query)
        ranked = []
        for entry in self.entries:
            scores = [score for term in entry['terms']
                      if (score := match_score(query, term)) is not None]
            if scores:
                ranked.append((min(scores), entry['title'].casefold(), entry['value'], entry))
        ranked.sort(key=lambda item: item[:3])
        return [{'name': entry['name'], 'value': entry['value']}
                for *_, entry in ranked[:max(0, min(limit, 25))]]

    def reload_aliases_if_changed(self):
        if self.alias_path is None:
            return
        try:
            stamp = alias_file_stamp(self.alias_path)
            if stamp == self.alias_stamp:
                return
            # Keep the last valid index if the file is temporarily incomplete.
            self.alias_stamp = stamp
            updated = SongLookup(self.songs, read_aliases(self.alias_path), self.region)
            self.entries = updated.entries
        except (OSError, ValueError):
            logging.getLogger(__name__).exception('유사어 JSON을 읽지 못해 기존 검색 목록을 유지합니다.')

    def select(self, value, difficulty='master'):
        """Return (song, sheet, fell_back_to_master) for an autocomplete value."""
        if value not in self.selections:
            raise ValueError('곡 자동완성 목록에서 DX/ST 항목을 선택해주세요.')
        if difficulty not in DIFFICULTIES:
            raise ValueError('지원하지 않는 난이도입니다.')
        song, type_ = self.selections[value]
        sheets = {s['difficulty']: s for s in song['sheets']
                  if s['type'] == type_ and self.available(s)}
        fallback = difficulty == 'remaster' and difficulty not in sheets
        selected = sheets.get('master' if fallback else difficulty)
        if selected is None:
            raise ValueError('선택한 채보에 해당 난이도가 없습니다.')
        # Use international chart constants, without mutating the source data.
        selected = {**selected, **selected.get('regionOverrides', {}).get(self.region, {})}
        return song, selected, fallback


def alias_file_stamp(path):
    try:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    except FileNotFoundError:
        return None


def read_aliases(path):
    if not path.exists():
        return []
    rows = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or not isinstance(row.get('title'), str)
        or not isinstance(row.get('aliases', []), list)
        or any(not isinstance(alias, str) for alias in row.get('aliases', [])) for row in rows
    ):
        raise ValueError('유사어 JSON은 title 문자열과 aliases 문자열 목록을 가진 리스트여야 합니다.')
    return rows


def load_song_lookup(alias_path=ALIAS_PATH, region='intl'):
    path = Path(alias_path)
    stamp = alias_file_stamp(path)
    aliases = read_aliases(path)
    songs, _ = get_data()
    index = SongLookup(songs, aliases, region)
    index.alias_path, index.alias_stamp = path, stamp
    return index
