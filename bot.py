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


@client.event
async def on_ready():
    global _synced

    if not _synced:
        await tree.sync()
        _synced = True

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
