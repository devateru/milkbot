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
) -> MaishiftBestEntry:
    return MaishiftBestEntry(
        stable_key=f"chart:{chart_id}",
        chart_id=chart_id,
        title=title,
        chart_type="DX",
        difficulty="MASTER",
        difficulty_label="14.4",
        achievement=Decimal(achievement),
        grade=grade,
        rating=rating,
    )


def build_maishift_test_embeds():
    timestamp = datetime(2026, 8, 13, 8, 42, tzinfo=timezone.utc)
    aiae = _entry(1, "AiAe", "100.5410", "SSS", 324)
    old_new_song = _entry(2, "Old New-Song", "100.5000", "SSS+", 310)
    credits = _entry(3, "Credits", "100.1000", "SSS", 328)
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
        new_best=(aiae, old_new_song),
        old_best=(credits,),
        created_at=timestamp,
        updated_at=timestamp,
    )
    after = replace(
        before,
        total_rating=16126,
        play_count=2629,
        last_update_raw="2026-08-13 17:42",
        new_best=(
            replace(
                aiae,
                achievement=Decimal("100.7234"),
                grade="SSS+",
                rating=326,
            ),
            _entry(4, "New New-Song", "100.6000", "SSS+", 315),
        ),
        old_best=(
            replace(
                credits,
                achievement=Decimal("100.2000"),
                grade="SSS+",
                rating=330,
            ),
        ),
    )
    return build_maishift_update_embeds(diff_snapshots(before, after), after, test=True)
