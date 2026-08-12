from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import unittest

from maishift.diff import diff_snapshots
from maishift.embeds import build_maishift_update_embeds
from tests.test_maishift_diff import entry, snapshot


class MaishiftEmbedTests(unittest.TestCase):
    def test_play_only_embed_and_discord_limits(self) -> None:
        before = snapshot(new=[entry("chart:1", "AiAe", 320)])
        after = replace(
            before,
            play_count=14,
            last_update_raw="8/12/2026, 2:31:00 PM",
            last_update_datetime=before.last_update_datetime + timedelta(minutes=1),
        )
        embeds = build_maishift_update_embeds(diff_snapshots(before, after), after)
        self.assertEqual(len(embeds), 1)
        data = embeds[0].to_dict()
        self.assertIn("🎮", data["title"])
        self.assertTrue(any(field["name"] == "BEST 50" for field in data["fields"]))
        self.assertLessEqual(len(data["title"]), 256)
        self.assertLessEqual(len(data.get("description", "")), 4096)
        self.assertLessEqual(len(data["fields"]), 25)
        self.assertTrue(all(len(field["value"]) <= 1024 for field in data["fields"]))
