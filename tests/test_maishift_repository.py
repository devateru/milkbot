from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import unittest

from maishift.client import normalize_profile_key, profile_urls
from maishift.models import MaishiftBestEntry, MaishiftSnapshot
from maishift.repository import MaishiftRepository


def sample_snapshot() -> MaishiftSnapshot:
    item = MaishiftBestEntry(
        "chart:1", 1, "곡", "DX", "MASTER", "14.0", Decimal("100.0000"), "SSS", 300
    )
    return MaishiftSnapshot(
        "shiftpsh", "shiftpsh", "https://example/p", "PLAYER", 300, 1, None,
        "raw", datetime.now(timezone.utc), "v", (item,), ()
    )


class MaishiftRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = MaishiftRepository(Path(self.temp.name) / "state.sqlite3")

    def tearDown(self) -> None:
        self.repo.close()
        self.temp.cleanup()

    def test_channel_subscription_unique_and_profile_poll_deduplicated(self) -> None:
        snap = sample_snapshot()
        self.assertTrue(self.repo.add_subscription(snap, guild_id=1, channel_id=10, created_by=3, etag=None, last_modified=None, baseline_update_id="baseline"))
        self.assertFalse(self.repo.claim_delivery("baseline", 10, "shiftpsh"))
        self.assertFalse(self.repo.add_subscription(snap, guild_id=1, channel_id=10, created_by=3, etag=None, last_modified=None))
        for channel in range(11, 21):
            self.repo.add_subscription(snap, guild_id=1, channel_id=channel, created_by=3, etag=None, last_modified=None)
        self.assertEqual(len(self.repo.subscriptions_for_profile("shiftpsh")), 11)
        self.assertEqual(len(self.repo.tracked_profiles()), 1)

    def test_persistence_remove_and_delivery_idempotency(self) -> None:
        snap = sample_snapshot()
        self.repo.add_subscription(snap, guild_id=1, channel_id=10, created_by=3, etag="e", last_modified="m")
        self.assertTrue(self.repo.claim_delivery("update", 10, "shiftpsh"))
        self.assertFalse(self.repo.claim_delivery("update", 10, "shiftpsh"))
        self.assertTrue(self.repo.remove_subscription(10, "shiftpsh"))
        self.assertIsNotNone(self.repo.get_profile("shiftpsh"))

    def test_profile_url_encodes_one_path_segment(self) -> None:
        internal, public = profile_urls(" ../한 글?:#% ")
        self.assertIn("%2F", internal)
        self.assertIn("%3F", internal)
        self.assertIn("%23", internal)
        self.assertIn("%25", internal)
        self.assertNotIn(" ../", internal)
        self.assertTrue(public.startswith("https://maimai.shiftpsh.com/profile/"))
        self.assertEqual(normalize_profile_key(" Å "), normalize_profile_key("Å"))


class MaishiftRepositoryMigrationTests(unittest.TestCase):
    def test_delivery_retry_columns_are_added_without_losing_subscriptions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE maishift_profiles (
                    profile_key TEXT PRIMARY KEY, profile_name TEXT NOT NULL,
                    profile_url TEXT NOT NULL, latest_snapshot_json TEXT NOT NULL,
                    source_last_update TEXT NOT NULL, etag TEXT, last_modified TEXT,
                    last_checked_at TEXT NOT NULL, consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TEXT, rollback_snapshot_json TEXT,
                    rollback_seen_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE maishift_subscriptions (
                    guild_id INTEGER NOT NULL, channel_id INTEGER NOT NULL,
                    profile_key TEXT NOT NULL, created_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL, UNIQUE(channel_id, profile_key)
                );
                CREATE TABLE maishift_deliveries (
                    update_id TEXT NOT NULL, channel_id INTEGER NOT NULL,
                    profile_key TEXT NOT NULL, status TEXT NOT NULL,
                    attempted_at TEXT NOT NULL, PRIMARY KEY(update_id, channel_id)
                );
                """
            )
            snapshot = sample_snapshot()
            connection.execute(
                "INSERT INTO maishift_profiles VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, 0, NULL, NULL, 0)",
                (
                    snapshot.profile_key,
                    snapshot.profile_name,
                    snapshot.profile_url,
                    snapshot.to_json(),
                    snapshot.source_last_update,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.execute(
                "INSERT INTO maishift_subscriptions VALUES (1, 10, ?, 3, ?)",
                (snapshot.profile_key, datetime.now(timezone.utc).isoformat()),
            )
            connection.commit()
            connection.close()

            repository = MaishiftRepository(path)
            try:
                columns = {
                    row[1]
                    for row in repository._connection.execute(
                        "PRAGMA table_info(maishift_deliveries)"
                    )
                }
                self.assertTrue(
                    {"attempt_count", "last_error", "next_retry_at", "payload_json"}
                    <= columns
                )
                self.assertEqual(repository.subscription_count(), 1)
                self.assertEqual(len(repository.all_subscribed_profiles()), 1)
            finally:
                repository.close()
