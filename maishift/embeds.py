from __future__ import annotations

from decimal import Decimal

import discord

from .diff import EntryChange, MaishiftDiff, SectionDiff
from .models import MaishiftSnapshot


def _delta(value: int) -> str:
    return f"{value:+,}"


def _achievement_delta(value: Decimal) -> str:
    return f"{value:+.4f}%"


def _change_lines(change: EntryChange) -> list[str]:
    old, new = change.old, change.new
    if change.rating_only:
        return [
            f"↔ **{new.title}** · 레이팅 값 변경",
            f"달성률 {new.achievement:.4f}% 유지",
            f"Rating {old.rating} → {new.rating} ({_delta(change.rating_delta)})",
        ]
    arrow = "↑" if change.achievement_delta > 0 or change.rating_delta > 0 else "↓"
    lines = [
        f"{arrow} **{new.title}**",
        f"{old.achievement:.4f}% → {new.achievement:.4f}% ({_achievement_delta(change.achievement_delta)})",
        f"Rating {old.rating} → {new.rating} ({_delta(change.rating_delta)})",
    ]
    if old.grade != new.grade:
        lines.append(f"등급 {old.grade} → {new.grade}")
    return lines


def _section_value(section: SectionDiff) -> str:
    blocks: list[str] = []
    events = 0
    for change in sorted(section.changes, key=lambda item: (item.rating_delta, item.achievement_delta), reverse=True):
        if events >= 5:
            break
        blocks.append("\n".join(_change_lines(change)))
        events += 1
    for entry in section.added:
        if events >= 8:
            break
        blocks.append(f"IN **{entry.title}** · {entry.rating}")
        events += 1
    for entry in section.removed:
        if events >= 8:
            break
        blocks.append(f"OUT **{entry.title}** · {entry.rating}")
        events += 1
    total_events = len(section.changes) + len(section.added) + len(section.removed)
    if total_events > events:
        blocks.append(f"외 {total_events - events}개 변경")
    blocks.append(f"섹션 레이팅 변화: **{_delta(section.rating_delta)}**")
    value = "\n\n".join(blocks)
    return value[:1021] + "..." if len(value) > 1024 else value


def build_maishift_update_embeds(
    diff: MaishiftDiff,
    snapshot: MaishiftSnapshot,
) -> list[discord.Embed]:
    icon = "📈" if diff.total_rating_delta else "🎮"
    if len(diff.new_section.changes) + len(diff.old_section.changes) > 8:
        icon = "📊"
    embed = discord.Embed(
        title=f"{icon} maishift 갱신 — {snapshot.player_name}"[:256],
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
    version_changes = [item for item in diff.metadata_changes if item[0] == "game_version"]
    if version_changes:
        _, before, after = version_changes[0]
        embed.add_field(
            name="게임 버전/레이팅 환경 변경",
            value=f"{before or '-'} → {after or '-'}"[:1024],
            inline=False,
        )
    if not diff.b50_changed:
        embed.add_field(name="BEST 50", value="변화 없음", inline=False)
    embed.set_footer(text=f"총 레이팅 변화: {_delta(diff.total_rating_delta)}")
    return [embed]
