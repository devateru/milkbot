"""SQLite persistence for nicknames, goals, and verified chart data."""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3

from .mai_notes import CachedChart
from .simai import Note, Simai, Section, parse_simai
from .tracking import identity_name, identity_key


SCHEMA = '''
CREATE TABLE IF NOT EXISTS profiles (
    user_id TEXT PRIMARY KEY, nickname TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS charts (
    url TEXT NOT NULL, chart_key TEXT NOT NULL, source TEXT NOT NULL, chart TEXT NOT NULL,
    PRIMARY KEY (url, chart_key)
);
CREATE TABLE IF NOT EXISTS targets (
    user_id TEXT NOT NULL, chart_key TEXT NOT NULL, revision INTEGER NOT NULL,
    url TEXT NOT NULL, sections TEXT NOT NULL, PRIMARY KEY (user_id, chart_key),
    FOREIGN KEY (url, chart_key) REFERENCES charts (url, chart_key)
);
'''


def pack(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def decode_chart(value, source, chart_key) -> Simai:
    # Older cache entries retain the source but did not store note lanes.
    if source and 'lane' not in value['notes'][0]:
        return parse_simai(source, chart_key.rsplit(':', 1)[-1])
    return Simai(tuple(Note(**note) for note in value['notes']), value['end'], value['first'])


@dataclass(frozen=True)
class Target:
    cached: CachedChart
    sections: tuple[Section, ...]


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode = WAL')
            db.executescript(SCHEMA)

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys = ON')
            if write:
                db.execute('BEGIN IMMEDIATE')
            with db:
                yield db
        finally:
            db.close()

    def nickname(self, user_id):
        with self.connection() as db:
            row = db.execute('SELECT nickname FROM profiles WHERE user_id = ?', (str(user_id),)).fetchone()
        return row[0] if row else None

    def set_nickname(self, user_id, value):
        name = identity_name(value)
        if identity_key(name) == 'guest':
            raise ValueError('GUEST는 플레이어명 대신 게스트 포함 옵션을 사용해주세요.')
        if not name or len(name) > 32 or any(not char.isprintable() for char in name):
            raise ValueError('플레이어명은 화면에 표시되는 이름을 1~32자로 입력해주세요.')
        with self.connection(write=True) as db:
            db.execute('INSERT INTO profiles VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET nickname = excluded.nickname',
                       (str(user_id), name))
        return name

    def cache_chart(self, chart_key, cached):
        with self.connection(write=True) as db:
            db.execute('INSERT OR IGNORE INTO charts VALUES (?, ?, ?, ?)',
                       (cached.url, chart_key, cached.source, pack(asdict(cached.chart))))

    def cached_chart(self, url, chart_key):
        with self.connection() as db:
            row = db.execute('SELECT source, chart FROM charts WHERE url = ? AND chart_key = ?',
                             (url, chart_key)).fetchone()
        return CachedChart(url, row['source'], decode_chart(json.loads(row['chart']), row['source'], chart_key)) if row else None

    def save_target(self, user_id, chart_key, cached, sections):
        self.cache_chart(chart_key, cached)
        with self.connection(write=True) as db:
            sections = pack([asdict(s) for s in sections])
            db.execute('''INSERT INTO targets VALUES (?, ?, 1, ?, ?)
                ON CONFLICT(user_id, chart_key) DO UPDATE SET url = excluded.url,
                sections = excluded.sections''', (str(user_id), chart_key, cached.url, sections))

    def target(self, user_id, chart_key):
        with self.connection() as db:
            row = db.execute('''SELECT targets.url, targets.sections, charts.source, charts.chart FROM targets
                JOIN charts USING (url, chart_key) WHERE user_id = ? AND chart_key = ?''',
                             (str(user_id), chart_key)).fetchone()
        if row:
            return Target(CachedChart(row['url'], row['source'], decode_chart(json.loads(row['chart']), row['source'], chart_key)),
                          tuple(Section(**section) for section in json.loads(row['sections'])))
        return None

    def target_keys(self):
        with self.connection() as db:
            rows = db.execute("SELECT user_id, chart_key FROM targets WHERE sections <> '[]'").fetchall()
        return {(int(row[0]), row[1]) for row in rows}
