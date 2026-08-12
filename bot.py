import asyncio
import os
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from dotenv import load_dotenv

from dev_commands import handle_developer_dm_command
from emoji_text import register_emoji_text_command
from help_commands import build_server_help_embeds
from milk_agent_client import MilkAgentConfig, MilkAgentMessageHandler
from messages import get_message
from maishift.client import MaishiftClient
from maishift.repository import MaishiftRepository
from maishift.tracker import MaishiftTracker
from maishift_commands import register_maishift_commands
from random_song_command import (
    build_chunithm_probability_table_embed,
    build_maimai_probability_table_embed,
    register_random_song_command,
)
from storage import (
    get_allowed_guild_ids,
)
from thumbnail_board import build_gameplaza_thumbnail_board
from treat import handle_notreat, register_treat_command
from utage_command import register_utage_command
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

class MilkBotClient(discord.Client):
    maishift_tracker: MaishiftTracker | None = None
    _maishift_closed = False

    async def close(self) -> None:
        if self.maishift_tracker is not None and not self._maishift_closed:
            await self.maishift_tracker.stop()
            self.maishift_tracker.repository.close()
            self._maishift_closed = True
        await super().close()


client = MilkBotClient(intents=intents)
tree = app_commands.CommandTree(client)
milk_agent_handler = MilkAgentMessageHandler(MilkAgentConfig.from_env())
maishift_repository = MaishiftRepository(
    os.getenv("MAISHIFT_DB_PATH", "data/maishift.sqlite3")
)
maishift_client = MaishiftClient(
    timeout=float(os.getenv("MAISHIFT_HTTP_TIMEOUT_SEC", "10")),
    concurrency=int(os.getenv("MAISHIFT_HTTP_CONCURRENCY", "5")),
)
maishift_tracker = MaishiftTracker(
    client,
    maishift_repository,
    maishift_client,
    interval=float(os.getenv("MAISHIFT_POLL_INTERVAL_SEC", "60")),
)
client.maishift_tracker = maishift_tracker

_synced = False
_update_dm_sent = False

register_random_song_command(tree)
register_utage_command(tree)
register_emoji_text_command(tree)
register_maishift_commands(tree, maishift_repository, maishift_client)


@client.event
async def on_ready():
    global _synced, _update_dm_sent

    if not _synced:
        await tree.sync()
        await sync_all_treat_commands()
        _synced = True

    if not _update_dm_sent:
        await notify_developer_update()
        _update_dm_sent = True

    await maishift_tracker.start()

    print(f"Logged in as {client.user}")


def get_current_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "log", "-1", "--oneline"],
            text=True,
            timeout=3,
        ).strip()
    except Exception:
        return "커밋 정보를 확인하지 못했습니다."


async def notify_developer_update() -> None:
    try:
        user = client.get_user(BOT_DEVELOPER_ID) or await client.fetch_user(BOT_DEVELOPER_ID)
        commit = await asyncio.to_thread(get_current_commit)
        await user.send(f"밀크봇 업데이트 완료!\n`{commit}`")
    except Exception:
        return


async def sync_treat_command_for_guild(guild_id: int) -> None:
    guild = discord.Object(id=guild_id)
    tree.remove_command("treat", type=discord.AppCommandType.chat_input, guild=guild)

    if str(guild_id) in get_allowed_guild_ids():
        register_treat_command(tree, guild)

    await tree.sync(guild=guild)


async def sync_all_treat_commands() -> None:
    for guild_id_text in get_allowed_guild_ids():
        if guild_id_text.isdigit():
            await sync_treat_command_for_guild(int(guild_id_text))


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
        enabled_guild_ids_before = set(get_allowed_guild_ids())
        handled = await handle_developer_dm_command(message, client, BOT_DEVELOPER_ID)

        if handled:
            enabled_guild_ids_after = set(get_allowed_guild_ids())
            changed_guild_ids = enabled_guild_ids_before ^ enabled_guild_ids_after

            for guild_id_text in changed_guild_ids:
                if guild_id_text.isdigit():
                    await sync_treat_command_for_guild(int(guild_id_text))

        return

    content = message.content.strip()
    if await milk_agent_handler.handle_message(message):
        return

    if content == "마이마이 확률표":
        try:
            embed = await build_maimai_probability_table_embed(message.author.id)
        except Exception:
            await message.channel.send(get_message("random_song.error_fetch_failed"))
            return

        await message.channel.send(embed=embed)
        return

    if content == "츄니즘 확률표":
        try:
            embed = await build_chunithm_probability_table_embed(message.author.id)
        except Exception:
            await message.channel.send(get_message("random_song.error_fetch_failed"))
            return

        await message.channel.send(embed=embed)
        return

    await handle_notreat(message)


client.run(TOKEN)
