import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from dotenv import load_dotenv

from dev_commands import handle_developer_dm_command
from help_commands import build_server_help_embeds
from messages import get_message
from sega_facebook import poll_forever
from storage import (
    get_sega_facebook_channels,
    remove_sega_facebook_channel,
    set_sega_facebook_channel,
)
from thumbnail_board import build_gameplaza_thumbnail_board
from treat import handle_notreat, handle_user_dm_command
from youtube_live import (
    MachineStatus,
    YouTubeLiveError,
    get_gameplaza_machine_statuses,
)


load_dotenv(".env")

TOKEN = os.getenv("DISCORD_TOKEN")
BOT_DEVELOPER_ID = os.getenv("BOT_DEVELOPER_ID")
GAMEPLAZA_YOUTUBE_URL = os.getenv(
    "GAMEPLAZA_YOUTUBE_URL",
    "https://www.youtube.com/@GAMEPLAZA_C/streams",
)
FACEBOOK_ACCESS_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")
SEGA_FACEBOOK_POLL_SECONDS = int(os.getenv("SEGA_FACEBOOK_POLL_SECONDS", "60"))

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in .env")

if not BOT_DEVELOPER_ID:
    raise RuntimeError("BOT_DEVELOPER_ID is not set in .env")

BOT_DEVELOPER_ID = int(BOT_DEVELOPER_ID)

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.dm_messages = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

_synced = False
_sega_facebook_task: asyncio.Task | None = None


@client.event
async def on_ready():
    global _sega_facebook_task, _synced

    if not _synced:
        await tree.sync()
        _synced = True

    if _sega_facebook_task is None or _sega_facebook_task.done():
        _sega_facebook_task = asyncio.create_task(
            poll_forever(client, FACEBOOK_ACCESS_TOKEN, SEGA_FACEBOOK_POLL_SECONDS)
        )

    print(f"Logged in as {client.user}")


@tree.command(name="ping", description=get_message("slash.ping_description"))
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(get_message("slash.ping_response"))


@tree.command(name="겜플라이브", description=get_message("slash.gameplaza_description"))
async def gameplaza_live(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    try:
        statuses = await asyncio.to_thread(get_gameplaza_machine_statuses)
    except YouTubeLiveError:
        await interaction.followup.send(
            get_message("slash.gameplaza_error", url=GAMEPLAZA_YOUTUBE_URL)
        )
        return

    checked_at = datetime.now(ZoneInfo("Asia/Seoul"))
    timestamp = checked_at.strftime("%Y-%m-%d %H:%M:%S")
    thumbnail_board = await asyncio.to_thread(
        build_gameplaza_thumbnail_board,
        statuses,
        timestamp,
    )
    file = discord.File(thumbnail_board, filename="gameplaza_live.jpg")
    embed = build_gameplaza_live_embed(statuses, checked_at)

    await interaction.followup.send(embed=embed, file=file)


def _format_status(status: MachineStatus) -> str:
    machine_name = f"{status.number}번기"

    if not status.is_live or status.live_url is None:
        return "[---]"

    return f"[{machine_name}]({status.live_url})"


def build_gameplaza_live_embed(
    statuses: list[MachineStatus],
    checked_at: datetime,
) -> discord.Embed:
    live_count = sum(1 for status in statuses if status.is_live)
    embed = discord.Embed(
        title="게임플라자 라이브 상태",
        description=(
            f"[@GAMEPLAZA_C/streams]({GAMEPLAZA_YOUTUBE_URL})\n"
            f"확인 시각: {checked_at.strftime('%Y-%m-%d %H:%M KST')}\n"
            f"라이브: {live_count}/8"
        ),
    )
    maimai_statuses = statuses[:5]
    chunithm_statuses = statuses[5:]

    embed.add_field(
        name="마이마이 디럭스",
        value=" / ".join(_format_status(status) for status in maimai_statuses),
        inline=False,
    )
    embed.add_field(
        name="츄니즘",
        value=" / ".join(_format_status(status) for status in chunithm_statuses),
        inline=False,
    )
    embed.set_image(url="attachment://gameplaza_live.jpg")

    return embed


def can_manage_server(interaction: discord.Interaction) -> bool:
    if interaction.user.id == BOT_DEVELOPER_ID:
        return True

    permissions = interaction.user.guild_permissions
    return permissions.administrator or permissions.manage_guild


sega_facebook_group = app_commands.Group(
    name="세가페북",
    description="세가 리듬게임 Facebook 새 게시물 알림을 관리합니다.",
)


@sega_facebook_group.command(name="켜기", description="이 서버에 세가 Facebook 게시물 알림을 켭니다.")
async def sega_facebook_enable(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("서버에서만 사용할 수 있는 명령어입니다.", ephemeral=True)
        return

    if not can_manage_server(interaction):
        await interaction.response.send_message("서버 관리 권한이 있는 멤버만 사용할 수 있습니다.", ephemeral=True)
        return

    target_channel = interaction.channel

    if not isinstance(target_channel, discord.TextChannel):
        await interaction.response.send_message("텍스트 채널에서만 알림을 켤 수 있습니다.", ephemeral=True)
        return

    permissions = target_channel.permissions_for(interaction.guild.me)

    if not permissions.send_messages or not permissions.embed_links:
        await interaction.response.send_message(
            f"{target_channel.mention}에 메시지와 임베드를 보낼 권한이 필요합니다.",
            ephemeral=True,
        )
        return

    set_sega_facebook_channel(interaction.guild.id, target_channel.id)

    if FACEBOOK_ACCESS_TOKEN:
        note = "새 게시물 확인은 폴링 주기에 따라 진행됩니다."
    else:
        note = "다만 아직 `FACEBOOK_ACCESS_TOKEN`이 설정되지 않아 실제 확인은 시작되지 않았습니다."

    await interaction.response.send_message(
        f"세가 Facebook 알림을 {target_channel.mention}에 켰습니다. {note}",
        ephemeral=True,
    )


@sega_facebook_group.command(name="끄기", description="이 서버의 세가 Facebook 게시물 알림을 끕니다.")
async def sega_facebook_disable(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("서버에서만 사용할 수 있는 명령어입니다.", ephemeral=True)
        return

    if not can_manage_server(interaction):
        await interaction.response.send_message("서버 관리 권한이 있는 멤버만 사용할 수 있습니다.", ephemeral=True)
        return

    removed = remove_sega_facebook_channel(interaction.guild.id)

    if removed:
        message = "이 서버의 세가 Facebook 알림을 껐습니다."
    else:
        message = "이 서버에는 켜진 세가 Facebook 알림이 없습니다."

    await interaction.response.send_message(message, ephemeral=True)


@sega_facebook_group.command(name="상태", description="이 서버의 세가 Facebook 게시물 알림 상태를 확인합니다.")
async def sega_facebook_status(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("서버에서만 사용할 수 있는 명령어입니다.", ephemeral=True)
        return

    channel_id = get_sega_facebook_channels().get(str(interaction.guild.id))
    token_status = "설정됨" if FACEBOOK_ACCESS_TOKEN else "없음"

    if channel_id:
        channel_text = f"<#{channel_id}>"
        enabled_text = "켜짐"
    else:
        channel_text = "-"
        enabled_text = "꺼짐"

    await interaction.response.send_message(
        (
            f"상태: {enabled_text}\n"
            f"채널: {channel_text}\n"
            f"Facebook 토큰: {token_status}\n"
            f"확인 주기: {SEGA_FACEBOOK_POLL_SECONDS}초"
        ),
        ephemeral=True,
    )


tree.add_command(sega_facebook_group)


@tree.command(name="help", description=get_message("slash.help_description"))
async def help_command(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(get_message("slash.help_guild_only"))
        return

    await interaction.response.send_message(
        embeds=build_server_help_embeds(interaction.guild.id),
        ephemeral=True,
    )


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.guild is None:
        handled = await handle_developer_dm_command(message, client, BOT_DEVELOPER_ID)

        if handled:
            return

        await handle_user_dm_command(message, client)
        return

    await handle_notreat(message)


client.run(TOKEN)
