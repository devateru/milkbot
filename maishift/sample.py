from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

from .diff import diff_snapshots
from .embeds import build_maishift_update_embeds
from .models import MaishiftBestEntry, MaishiftSnapshot


def _entry(
    chart_id: int,
    title: str,
    achievement: str,
    grade: str,
    rating: int,
    difficulty_label: str,
) -> MaishiftBestEntry:
    return MaishiftBestEntry(
        stable_key=f"chart:{chart_id}",
        chart_id=chart_id,
        title=title,
        chart_type="DX",
        difficulty="MASTER",
        difficulty_label=difficulty_label,
        achievement=Decimal(achievement),
        grade=grade,
        rating=rating,
    )


def build_maishift_test_embeds():
    timestamp = datetime(2026, 8, 13, 8, 42, tzinfo=timezone.utc)
    test_song_a = _entry(1, "Test Song A", "99.1384", "SS+", 307, "14.1")
    test_song_b = _entry(2, "Test Song B", "100.5674", "SSS+", 310, "13.8")
    before = MaishiftSnapshot(
        profile_key="milk-test",
        profile_name="milk-test",
        profile_url="https://maimai.shiftpsh.com/profile/milk-test/home",
        player_name="MILK TEST",
        total_rating=16117,
        play_count=2625,
        secondary_play_count=45,
        last_update_raw="2026-08-13 17:38",
        last_update_datetime=timestamp,
        game_version="CiRCLE PLUS week #2",
        new_best=(),
        old_best=(test_song_a, test_song_b),
        created_at=timestamp,
        updated_at=timestamp,
    )
    after = replace(
        before,
        total_rating=16134,
        play_count=2629,
        last_update_raw="2026-08-13 17:42",
        old_best=(
            replace(
                test_song_a,
                achievement=Decimal("100.5384"),
                grade="SSS+",
                rating=317,
            ),
            _entry(3, "Test Song C", "100.5384", "SSS+", 317, "14.1"),
        ),
    )
    return build_maishift_update_embeds(diff_snapshots(before, after), after, test=True)
