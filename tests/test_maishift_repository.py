from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
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
