from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import unittest

from maishift.diff import diff_snapshots
from maishift.models import MaishiftBestEntry, MaishiftSnapshot


def entry(key: str, title: str, rating: int, achievement: str = "100.5000", grade: str = "SSS+"):
    return MaishiftBestEntry(
        stable_key=key,
        chart_id=int(key.split(":")[1]),
        title=title,
        chart_type="DX",
        difficulty="MASTER",
        difficulty_label="14.0",
        achievement=Decimal(achievement),
        grade=grade,
        rating=rating,
    )


def snapshot(new=(), old=(), *, play=10, version="CiRCLE"):
    entries = tuple(new) + tuple(old)
    return MaishiftSnapshot(
        profile_key="p",
        profile_name="p",
        profile_url="https://example/p",
        player_name="PLAYER",
        total_rating=sum(item.rating for item in entries),
        play_count=play,
        secondary_play_count=None,
        last_update_raw="raw",
        last_update_datetime=datetime(2026, 8, 12, tzinfo=timezone.utc),
        game_version=version,
        new_best=tuple(new),
        old_best=tuple(old),
    )


class MaishiftDiffTests(unittest.TestCase):
    def test_achievement_and_rating_improvement(self) -> None:
        before = snapshot(new=[entry("chart:1", "AiAe", 320, "100.5000", "SSS")])
        after = snapshot(new=[entry("chart:1", "AiAe", 324, "100.7000", "SSS+")])
        change = diff_snapshots(before, after).new_section.changes[0]
        self.assertEqual(change.achievement_delta, Decimal("0.2000"))
        self.assertEqual(change.rating_delta, 4)
        self.assertFalse(change.rating_only)

    def test_new_and_old_replacements_and_multiple_entries(self) -> None:
        before = snapshot(
            new=[entry("chart:1", "OUT N1", 310), entry("chart:2", "OUT N2", 300)],
            old=[entry("chart:3", "OUT O1", 315), entry("chart:4", "KEEP", 320)],
        )
        after = snapshot(
            new=[entry("chart:5", "IN N1", 317), entry("chart:6", "IN N2", 305)],
            old=[entry("chart:7", "IN O1", 312), entry("chart:4", "KEEP", 320)],
        )
        diff = diff_snapshots(before, after)
        self.assertEqual(diff.new_section.rating_delta, 12)
        self.assertEqual(diff.old_section.rating_delta, -3)
        self.assertEqual(len(diff.new_section.added), 2)
        self.assertEqual(len(diff.new_section.removed), 2)

    def test_play_only_and_no_change(self) -> None:
        before = snapshot(new=[entry("chart:1", "곡", 320)])
        play_only = replace(before, play_count=14)
        diff = diff_snapshots(before, play_only)
        self.assertEqual(diff.play_count_delta, 4)
        self.assertFalse(diff.b50_changed)
        self.assertTrue(diff.has_changes)
        self.assertFalse(diff_snapshots(before, before).has_changes)

    def test_total_rating_decrease(self) -> None:
        before = snapshot(new=[entry("chart:1", "곡", 320)])
        after = snapshot(new=[entry("chart:1", "곡", 317)])
        self.assertEqual(diff_snapshots(before, after).total_rating_delta, -3)

    def test_rating_only_change(self) -> None:
        before = snapshot(old=[entry("chart:1", "ATLAS RUSH", 330, "100.5113")])
        after = snapshot(old=[entry("chart:1", "ATLAS RUSH", 333, "100.5113")])
        self.assertTrue(diff_snapshots(before, after).old_section.changes[0].rating_only)

    def test_new_old_migration_is_not_added_and_removed(self) -> None:
        song = entry("chart:1", "Re：End of a Dream", 324)
        diff = diff_snapshots(snapshot(old=[song]), snapshot(new=[song], version="CiRCLE PLUS"))
        self.assertEqual(len(diff.section_migrations), 1)
        self.assertFalse(diff.new_section.added)
        self.assertFalse(diff.old_section.removed)
        self.assertEqual(diff.metadata_changes[0][0], "game_version")

    def test_unicode_titles_keep_distinct_stable_keys(self) -> None:
        songs = [
            entry("chart:1", "Åntinomiε", 320),
            entry("chart:2", "鬼女紅妖", 321),
            entry("chart:3", "Re：End of a Dream", 322),
        ]
        self.assertFalse(diff_snapshots(snapshot(new=songs), snapshot(new=songs)).has_changes)
