from __future__ import annotations

import discord

from maishift.sample import build_maishift_test_embeds
from maishift.tracker import MaishiftTracker


def _chunks(lines: list[str], *, limit: int = 1900) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


async def handle_maishift_developer_dm(
    message: discord.Message,
    developer_id: int,
    tracker: MaishiftTracker,
) -> bool:
    if message.guild is not None or message.author.id != developer_id:
        return False
    content = message.content.strip()
    if content == "마싶테스트":
        await message.reply(
            embeds=build_maishift_test_embeds(),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True
    if content != "마싶동기화":
        return False
    await message.reply(
        "🔄 maishift 기록 재동기화를 시작할게.",
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none(),
    )
    result = await tracker.manual_resync()
    lines = [
        "✅ maishift 재동기화 완료",
        f"대상 프로필: {len(result.profiles)}개",
        f"성공: {result.success_count}개",
        f"실패: {result.failure_count}개",
        "구독 관계: 그대로 유지됨",
        "일반 채널 알림: 전송하지 않음",
    ]
    if result.profiles:
        lines.append("")
    for item in result.profiles:
        if item.success:
            lines.append(
                f"{item.profile_name}: {item.before_rating:,} → {item.after_rating:,}"
            )
        else:
            lines.append(f"{item.profile_name}: 실패 — {item.error}")
    for chunk in _chunks(lines):
        await message.reply(
            chunk,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    return True
