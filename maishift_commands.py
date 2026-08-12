from __future__ import annotations

from zoneinfo import ZoneInfo

import discord
from discord import app_commands

from maishift.client import FetchStatus, MaishiftClient, normalize_profile_key
from maishift.repository import MaishiftRepository
from maishift.tracker import make_update_id


INVALID_MESSAGE = (
    "❌ 해당 maishift 프로필을 확인할 수 없어.\n"
    "프로필명이 잘못되었거나 프로필이 비공개 상태일 수 있어."
)
TEMPORARY_MESSAGE = (
    "⚠️ 지금은 maishift 프로필을 확인하지 못했어.\n"
    "잠시 후 다시 시도해 줘."
)


async def _check_context(interaction: discord.Interaction) -> bool:
    if interaction.guild is None or interaction.channel_id is None:
        await interaction.response.send_message(
            "❌ 이 명령어는 서버의 메시지를 보낼 수 있는 채널에서만 사용할 수 있어.",
            ephemeral=True,
        )
        return False
    permissions = interaction.app_permissions
    if not (permissions.send_messages or permissions.send_messages_in_threads) or not permissions.embed_links:
        await interaction.response.send_message(
            "❌ 이 채널에서 추적하려면 봇에 `메시지 보내기`와 `링크 임베드` 권한이 필요해.",
            ephemeral=True,
        )
        return False
    return True


def _format_update(snapshot) -> str:
    if snapshot.last_update_datetime is None:
        return snapshot.last_update_raw
    return snapshot.last_update_datetime.astimezone(ZoneInfo("Asia/Seoul")).strftime(
        "%Y-%m-%d %H:%M"
    )


def register_maishift_commands(
    tree: app_commands.CommandTree,
    repository: MaishiftRepository,
    client: MaishiftClient,
) -> None:
    @tree.command(name="마이시프트추적", description="이 채널에서 공개 maishift 프로필을 추적해요")
    @app_commands.rename(profile_name="프로필명")
    @app_commands.describe(profile_name="추적할 maishift 프로필명")
    async def track_maishift(interaction: discord.Interaction, profile_name: str) -> None:
        if not await _check_context(interaction):
            return
        profile_name = profile_name.strip()
        if not profile_name:
            await interaction.response.send_message("❌ 프로필명을 입력해 줘.", ephemeral=True)
            return
        profile_key = normalize_profile_key(profile_name)
        if any(
            item.profile_key == profile_key
            for item in repository.list_channel_subscriptions(interaction.channel_id)
        ):
            await interaction.response.send_message(
                f"ℹ️ 이 채널에서는 이미 {profile_name} 프로필을 추적하고 있어.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        result = await client.fetch(profile_name)
        if result.status == FetchStatus.INVALID_OR_PRIVATE:
            await interaction.followup.send(INVALID_MESSAGE, ephemeral=True)
            return
        if result.status != FetchStatus.VALID_PUBLIC or result.snapshot is None:
            await interaction.followup.send(TEMPORARY_MESSAGE, ephemeral=True)
            return
        snapshot = result.snapshot
        added = repository.add_subscription(
            snapshot,
            guild_id=interaction.guild.id,
            channel_id=interaction.channel_id,
            created_by=interaction.user.id,
            etag=result.etag,
            last_modified=result.last_modified,
            baseline_update_id=make_update_id(snapshot),
        )
        if not added:
            await interaction.followup.send(
                f"ℹ️ 이 채널에서는 이미 {snapshot.profile_name} 프로필을 추적하고 있어.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="✅ maishift 추적을 시작했어!",
            url=snapshot.profile_url,
            colour=discord.Colour.green(),
        )
        embed.description = (
            f"프로필: [{snapshot.profile_name}]({snapshot.profile_url})\n"
            f"레이팅: **{snapshot.total_rating:,}**\n"
            f"플레이 수: **{snapshot.play_count:,}**\n"
            f"마지막 갱신: **{_format_update(snapshot)}**"
        )
        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @tree.command(name="마이시프트추적해제", description="이 채널의 maishift 프로필 추적을 해제해요")
    @app_commands.rename(profile_name="프로필명")
    @app_commands.describe(profile_name="추적을 해제할 maishift 프로필명")
    async def untrack_maishift(interaction: discord.Interaction, profile_name: str) -> None:
        if not await _check_context(interaction):
            return
        profile_name = profile_name.strip()
        if not profile_name:
            await interaction.response.send_message("❌ 프로필명을 입력해 줘.", ephemeral=True)
            return
        removed = repository.remove_subscription(
            interaction.channel_id, normalize_profile_key(profile_name)
        )
        message = (
            f"✅ 이 채널에서 {profile_name} 프로필 추적을 해제했어."
            if removed
            else f"ℹ️ 이 채널에서는 {profile_name} 프로필을 추적하고 있지 않아."
        )
        await interaction.response.send_message(message, ephemeral=True)

    @tree.command(name="마이시프트추적목록", description="이 채널에서 추적 중인 maishift 프로필을 보여줘요")
    async def list_maishift(interaction: discord.Interaction) -> None:
        if not await _check_context(interaction):
            return
        subscriptions = repository.list_channel_subscriptions(interaction.channel_id)
        if not subscriptions:
            message = "이 채널에서 추적 중인 maishift 프로필이 없어."
        else:
            lines = [
                f"• [{item.profile_name}]({item.profile_url})" for item in subscriptions
            ]
            message = "**이 채널에서 추적 중인 maishift 프로필**\n\n" + "\n".join(lines)
        await interaction.response.send_message(
            message,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
