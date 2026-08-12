from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import threading

from .models import MaishiftSnapshot


@dataclass(frozen=True, slots=True)
class ProfileRecord:
    profile_key: str
    profile_name: str
    profile_url: str
    snapshot: MaishiftSnapshot
    etag: str | None
    last_modified: str | None
    consecutive_failures: int
    next_retry_at: datetime | None


@dataclass(frozen=True, slots=True)
class Subscription:
    guild_id: int
    channel_id: int
    profile_key: str
    profile_name: str
    profile_url: str


class MaishiftRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS maishift_profiles (
                    profile_key TEXT PRIMARY KEY,
                    profile_name TEXT NOT NULL,
                    profile_url TEXT NOT NULL,
                    latest_snapshot_json TEXT NOT NULL,
                    source_last_update TEXT NOT NULL,
                    etag TEXT,
                    last_modified TEXT,
                    last_checked_at TEXT NOT NULL,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TEXT,
                    rollback_snapshot_json TEXT,
                    rollback_seen_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS maishift_subscriptions (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    profile_key TEXT NOT NULL REFERENCES maishift_profiles(profile_key) ON DELETE CASCADE,
                    created_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(channel_id, profile_key)
                );
                CREATE INDEX IF NOT EXISTS idx_maishift_subscriptions_profile
                    ON maishift_subscriptions(profile_key);

                CREATE TABLE IF NOT EXISTS maishift_deliveries (
                    update_id TEXT NOT NULL,
                    channel_id INTEGER NOT NULL,
                    profile_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempted_at TEXT NOT NULL,
                    PRIMARY KEY(update_id, channel_id)
                );
                """
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    @staticmethod
    def _profile(row: sqlite3.Row) -> ProfileRecord:
        return ProfileRecord(
            profile_key=row["profile_key"],
            profile_name=row["profile_name"],
            profile_url=row["profile_url"],
            snapshot=MaishiftSnapshot.from_json(row["latest_snapshot_json"]),
            etag=row["etag"],
            last_modified=row["last_modified"],
            consecutive_failures=row["consecutive_failures"],
            next_retry_at=MaishiftRepository._parse_datetime(row["next_retry_at"]),
        )

    def add_subscription(
        self,
        snapshot: MaishiftSnapshot,
        *,
        guild_id: int,
        channel_id: int,
        created_by: int,
        etag: str | None,
        last_modified: str | None,
        baseline_update_id: str | None = None,
    ) -> bool:
        now = self._now().isoformat()
        with self._lock, self._connection:
            active = self._connection.execute(
                "SELECT COUNT(*) FROM maishift_subscriptions WHERE profile_key=?",
                (snapshot.profile_key,),
            ).fetchone()[0]
            if active:
                self._connection.execute(
                    """
                    INSERT INTO maishift_profiles (
                        profile_key, profile_name, profile_url, latest_snapshot_json,
                        source_last_update, etag, last_modified, last_checked_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(profile_key) DO UPDATE SET
                        profile_name=excluded.profile_name,
                        profile_url=excluded.profile_url
                    """,
                    (
                        snapshot.profile_key, snapshot.profile_name, snapshot.profile_url,
                        snapshot.to_json(), snapshot.source_last_update, etag, last_modified, now,
                    ),
                )
            else:
                self._connection.execute(
                    """
                    INSERT INTO maishift_profiles (
                        profile_key, profile_name, profile_url, latest_snapshot_json,
                        source_last_update, etag, last_modified, last_checked_at,
                        consecutive_failures, next_retry_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
                    ON CONFLICT(profile_key) DO UPDATE SET
                        profile_name=excluded.profile_name,
                        profile_url=excluded.profile_url,
                        latest_snapshot_json=excluded.latest_snapshot_json,
                        source_last_update=excluded.source_last_update,
                        etag=excluded.etag,
                        last_modified=excluded.last_modified,
                        last_checked_at=excluded.last_checked_at,
                        consecutive_failures=0,
                        next_retry_at=NULL
                    """,
                    (
                        snapshot.profile_key, snapshot.profile_name, snapshot.profile_url,
                        snapshot.to_json(), snapshot.source_last_update, etag, last_modified, now,
                    ),
                )
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO maishift_subscriptions (
                    guild_id, channel_id, profile_key, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, channel_id, snapshot.profile_key, created_by, now),
            )
            added = cursor.rowcount == 1
            if added and baseline_update_id:
                self._connection.execute(
                    """
                    INSERT OR IGNORE INTO maishift_deliveries
                        (update_id, channel_id, profile_key, status, attempted_at)
                    VALUES (?, ?, ?, 'baseline', ?)
                    """,
                    (baseline_update_id, channel_id, snapshot.profile_key, now),
                )
            return added

    def remove_subscription(self, channel_id: int, profile_key: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM maishift_subscriptions WHERE channel_id=? AND profile_key=?",
                (channel_id, profile_key),
            )
            return cursor.rowcount == 1

    def remove_channel(self, channel_id: int) -> int:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM maishift_subscriptions WHERE channel_id=?",
                (channel_id,),
            )
            return cursor.rowcount

    def list_channel_subscriptions(self, channel_id: int) -> list[Subscription]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT s.guild_id, s.channel_id, p.profile_key, p.profile_name, p.profile_url
                FROM maishift_subscriptions s
                JOIN maishift_profiles p ON p.profile_key=s.profile_key
                WHERE s.channel_id=? ORDER BY p.profile_name COLLATE NOCASE
                """,
                (channel_id,),
            ).fetchall()
        return [Subscription(**dict(row)) for row in rows]

    def subscriptions_for_profile(self, profile_key: str) -> list[Subscription]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT s.guild_id, s.channel_id, p.profile_key, p.profile_name, p.profile_url
                FROM maishift_subscriptions s
                JOIN maishift_profiles p ON p.profile_key=s.profile_key
                WHERE s.profile_key=? ORDER BY s.channel_id
                """,
                (profile_key,),
            ).fetchall()
        return [Subscription(**dict(row)) for row in rows]

    def tracked_profiles(self, *, now: datetime | None = None) -> list[ProfileRecord]:
        now_text = (now or self._now()).isoformat()
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT p.* FROM maishift_profiles p
                WHERE EXISTS (
                    SELECT 1 FROM maishift_subscriptions s WHERE s.profile_key=p.profile_key
                ) AND (p.next_retry_at IS NULL OR p.next_retry_at <= ?)
                ORDER BY p.profile_key
                """,
                (now_text,),
            ).fetchall()
        return [self._profile(row) for row in rows]

    def get_profile(self, profile_key: str) -> ProfileRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM maishift_profiles WHERE profile_key=?", (profile_key,)
            ).fetchone()
        return self._profile(row) if row else None

    def record_checked(
        self,
        profile_key: str,
        *,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE maishift_profiles SET
                    etag=COALESCE(?, etag), last_modified=COALESCE(?, last_modified),
                    last_checked_at=?, consecutive_failures=0, next_retry_at=NULL
                WHERE profile_key=?
                """,
                (etag, last_modified, self._now().isoformat(), profile_key),
            )

    def record_failure(self, profile_key: str, *, retry_after: float | None = None) -> datetime:
        profile = self.get_profile(profile_key)
        failures = (profile.consecutive_failures if profile else 0) + 1
        delay = retry_after if retry_after is not None else min(3600.0, 60.0 * (2 ** min(failures - 1, 6)))
        next_retry = self._now() + timedelta(seconds=max(60.0, delay))
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE maishift_profiles SET consecutive_failures=?, next_retry_at=?, last_checked_at=?
                WHERE profile_key=?
                """,
                (failures, next_retry.isoformat(), self._now().isoformat(), profile_key),
            )
        return next_retry

    def record_rollback(self, profile_key: str, snapshot: MaishiftSnapshot) -> None:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT rollback_snapshot_json, rollback_seen_count FROM maishift_profiles WHERE profile_key=?",
                (profile_key,),
            ).fetchone()
            same = row is not None and row["rollback_snapshot_json"] == snapshot.to_json()
            count = int(row["rollback_seen_count"]) + 1 if same else 1
            self._connection.execute(
                """
                UPDATE maishift_profiles SET rollback_snapshot_json=?, rollback_seen_count=?, last_checked_at=?
                WHERE profile_key=?
                """,
                (snapshot.to_json(), count, self._now().isoformat(), profile_key),
            )

    def save_snapshot(
        self,
        snapshot: MaishiftSnapshot,
        *,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE maishift_profiles SET
                    profile_name=?, profile_url=?, latest_snapshot_json=?, source_last_update=?,
                    etag=?, last_modified=?, last_checked_at=?, consecutive_failures=0,
                    next_retry_at=NULL, rollback_snapshot_json=NULL, rollback_seen_count=0
                WHERE profile_key=?
                """,
                (
                    snapshot.profile_name,
                    snapshot.profile_url,
                    snapshot.to_json(),
                    snapshot.source_last_update,
                    etag,
                    last_modified,
                    self._now().isoformat(),
                    snapshot.profile_key,
                ),
            )

    def claim_delivery(self, update_id: str, channel_id: int, profile_key: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO maishift_deliveries
                    (update_id, channel_id, profile_key, status, attempted_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (update_id, channel_id, profile_key, self._now().isoformat()),
            )
            return cursor.rowcount == 1

    def finish_delivery(self, update_id: str, channel_id: int, status: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE maishift_deliveries SET status=?, attempted_at=?
                WHERE update_id=? AND channel_id=?
                """,
                (status, self._now().isoformat(), update_id, channel_id),
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()
