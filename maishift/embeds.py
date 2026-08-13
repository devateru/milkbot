from __future__ import annotations

from decimal import Decimal

import discord

from .diff import EntryChange, MaishiftDiff, SectionDiff
from .models import MaishiftBestEntry, MaishiftSnapshot


def _delta(value: int) -> str:
    return f"{value:+,}"


def _achievement_delta(value: Decimal) -> str:
    return f"{value:+.4f}%"


def _change_lines(change: EntryChange) -> list[str]:
    old, new = change.old, change.new
    lines = [
        (
            f"[{old.rating} → {new.rating}] **{new.title}** "
            f"({new.chart_type}, {new.difficulty_label}) · "
            f"Rating {_delta(change.rating_delta)}"
        ),
    ]
    if old.achievement == new.achievement:
        lines.append(f"{new.achievement:.4f}% 유지")
    else:
        lines.append(
            f"{old.achievement:.4f}% → {new.achievement:.4f}% "
            f"({_achievement_delta(change.achievement_delta)})"
        )
    if old.grade != new.grade:
        lines.append(f"{old.grade} → {new.grade}")
    return lines


def _entry_line(entry: MaishiftBestEntry, *, prefix: str = "") -> str:
    return (
        f"{prefix}[{entry.rating}] **{entry.title}** "
        f"({entry.chart_type}, {entry.difficulty_label}) "
        f"{entry.achievement:.4f}%"
    )


def _replacement_lines(removed: MaishiftBestEntry, added: MaishiftBestEntry) -> str:
    replacement_delta = added.rating - removed.rating
    return "\n".join(
        (
            _entry_line(removed, prefix="   "),
            f"→ {_entry_line(added)} **({_delta(replacement_delta)})**",
        )
    )


def _section_value(section: SectionDiff) -> str:
    blocks: list[str] = []
    displayed_events = 0
    for change in sorted(section.changes, key=lambda item: (item.rating_delta, item.achievement_delta), reverse=True):
        if displayed_events >= 5:
            break
        blocks.append("\n".join(_change_lines(change)))
        displayed_events += 1

    if (
        len(section.removed) == 1
        and len(section.added) == 1
        and displayed_events <= 6
    ):
        blocks.append(_replacement_lines(section.removed[0], section.added[0]))
        displayed_events += 2
    else:
        # Multiple entries have no reliable one-to-one replacement relationship.
        for entry in section.removed:
            if displayed_events >= 8:
                break
            blocks.append(_entry_line(entry, prefix="OUT "))
            displayed_events += 1
        for entry in section.added:
            if displayed_events >= 8:
                break
            blocks.append(_entry_line(entry, prefix="IN  "))
            displayed_events += 1

    total_events = len(section.changes) + len(section.added) + len(section.removed)
    if total_events > displayed_events:
        blocks.append(f"외 {total_events - displayed_events}개 변경")
    blocks.append(f"섹션 레이팅 변화: **{_delta(section.rating_delta)}**")
    value = "\n\n".join(blocks)
    return value[:1021] + "..." if len(value) > 1024 else value


def build_maishift_update_embeds(
    diff: MaishiftDiff,
    snapshot: MaishiftSnapshot,
    *,
    test: bool = False,
) -> list[discord.Embed]:
    icon = "📈" if diff.total_rating_delta else "🎮"
    if len(diff.new_section.changes) + len(diff.old_section.changes) > 8:
        icon = "📊"
    title_prefix = "🧪 [TEST] " if test else ""
    embed = discord.Embed(
        title=f"{title_prefix}{icon} maishift 갱신 — {snapshot.player_name}"[:256],
        url=snapshot.profile_url,
        colour=discord.Colour.green() if diff.total_rating_delta >= 0 else discord.Colour.orange(),
    )
    embed.add_field(
        name="레이팅",
        value=(
            f"{diff.total_rating_before:,} → {diff.total_rating_after:,} "
            f"(**{_delta(diff.total_rating_delta)}**)"
        ),
        inline=True,
    )
    embed.add_field(
        name="플레이/크레딧",
        value=(
            f"{diff.play_count_before:,} → {diff.play_count_after:,} "
            f"(**{_delta(diff.play_count_delta)}**)"
        ),
        inline=True,
    )
    embed.add_field(name="마지막 갱신", value=snapshot.last_update_raw[:1024], inline=False)
    if diff.new_section.changes or diff.new_section.added or diff.new_section.removed:
        embed.add_field(name="신곡 BEST", value=_section_value(diff.new_section), inline=False)
    if diff.old_section.changes or diff.old_section.added or diff.old_section.removed:
        embed.add_field(name="구곡 BEST", value=_section_value(diff.old_section), inline=False)
    if diff.section_migrations:
        lines = [
            f"{item.entry.title}: {'신곡' if item.from_section == 'new' else '구곡'} → "
            f"{'신곡' if item.to_section == 'new' else '구곡'}"
            for item in diff.section_migrations[:10]
        ]
        if len(diff.section_migrations) > 10:
            lines.append(f"외 {len(diff.section_migrations) - 10}개 이동")
        embed.add_field(name="BEST 섹션 이동", value="\n".join(lines)[:1024], inline=False)
    if not diff.b50_changed:
        embed.add_field(name="BEST 50", value="변화 없음", inline=False)
    return [embed]
