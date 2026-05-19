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
from random_song import GENRE_CHOICES, RandomSongError, choose_random_song
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


@tree.command(name="랜덤선곡", description="국제판 수록곡 중 조건에 맞는 곡을 랜덤으로 골라줍니다.")
@app_commands.rename(
    game="게임",
    min_level="최소_보면상수",
    genre="장르",
    difficulty="난이도",
    chart_type="유형",
    partner_level="2p_난이도",
)
@app_commands.describe(
    game="maimai DX 또는 CHUNITHM. 기본값은 maimai DX.",
    min_level="이 보면상수 이상에서 선곡합니다. 기본값은 1.",
    genre="게임별 장르를 maimai 기준으로 통합한 필터입니다.",
    difficulty="하나 이상 입력 가능: MASTER, RE:MASTER처럼 공백/쉼표로 구분.",
    chart_type="STANDARD, DELUXE, UTAGE/WORLD'S END 중 하나 이상. 공백/쉼표로 구분.",
    partner_level="2P용 기준 보면상수. 기준값 -0.5부터 +1.0까지의 보면을 함께 찾습니다.",
)
@app_commands.choices(
    game=[
        app_commands.Choice(name="maimai DX", value="maimai"),
        app_commands.Choice(name="CHUNITHM", value="chunithm"),
    ],
    genre=[
        app_commands.Choice(name=config["label"], value=genre_key)
        for genre_key, config in GENRE_CHOICES.items()
    ],
)
async def random_song_command(
    interaction: discord.Interaction,
    game: app_commands.Choice[str] | None = None,
    min_level: float = 1.0,
    genre: app_commands.Choice[str] | None = None,
    difficulty: str | None = None,
    chart_type: str | None = None,
    partner_level: float | None = None,
):
    await interaction.response.defer(thinking=True)

    try:
        embeds = await choose_random_song(
            game=game.value if game else "maimai",
            min_level=min_level,
            genre=genre.value if genre else None,
            difficulty=difficulty,
            chart_type=chart_type,
            partner_level=partner_level,
        )
    except RandomSongError as exc:
        await interaction.followup.send(str(exc), ephemeral=True)
        return
    except Exception:
        await interaction.followup.send(
            "arcade-songs 데이터를 가져오는 중 문제가 생겼어요. 잠시 뒤 다시 시도해줘요.",
            ephemeral=True,
        )
        return

    await interaction.followup.send(embeds=embeds)


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


async def resolve_sega_facebook_channel(
    interaction: discord.Interaction,
    channel_id: str | None,
) -> discord.TextChannel | None:
    if channel_id:
        channel_id = channel_id.strip()

        if not channel_id.isdigit():
            return None

        channel = client.get_channel(int(channel_id))

        if channel is None:
            try:
                channel = await client.fetch_channel(int(channel_id))
            except discord.DiscordException:
                return None

        return channel if isinstance(channel, discord.TextChannel) else None

    return interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None


def user_can_manage_sega_facebook(
    interaction: discord.Interaction,
    target_channel: discord.TextChannel,
) -> bool:
    if interaction.user.id == BOT_DEVELOPER_ID:
        return True

    if interaction.guild is None:
        return False

    if interaction.guild.id != target_channel.guild.id:
        return False

    return can_manage_server(interaction)


def format_sega_facebook_status(
    interaction: discord.Interaction,
    target_channel: discord.TextChannel | None,
) -> str:
    channels = get_sega_facebook_channels()
    token_status = "설정됨" if FACEBOOK_ACCESS_TOKEN else "없음"

    if target_channel is not None:
        enabled_text = "켜짐" if str(target_channel.id) in channels else "꺼짐"
        channel_text = target_channel.mention
    else:
        enabled_text = "확인할 채널 없음"
        channel_text = "-"

    guild_id = interaction.guild.id if interaction.guild else None
    enabled_channels = [
        f"<#{channel_id}>"
        for channel_id, stored_guild_id in channels.items()
        if guild_id is not None and stored_guild_id == str(guild_id)
    ]

    if interaction.guild is None:
        enabled_channels = [f"<#{channel_id}>" for channel_id in channels]

    enabled_channel_text = ", ".join(enabled_channels) if enabled_channels else "-"

    return (
        f"이 채널 상태: {enabled_text}\n"
        f"확인 채널: {channel_text}\n"
        f"알림 켜진 채널: {enabled_channel_text}\n"
        f"Facebook 토큰: {token_status}\n"
        f"확인 주기: {SEGA_FACEBOOK_POLL_SECONDS}초"
    )


@tree.command(name="세가페북", description="세가 리듬게임 Facebook 새 게시물 알림을 관리합니다.")
@app_commands.rename(action="동작", channel_id="채널id")
@app_commands.describe(
    action="비워두면 상태를 확인합니다.",
    channel_id="DM에서 켜거나 끌 서버 채널 ID입니다. 서버에서는 비워두면 현재 채널을 사용합니다.",
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="상태", value="status"),
        app_commands.Choice(name="켜기", value="enable"),
        app_commands.Choice(name="끄기", value="disable"),
    ]
)
async def sega_facebook_command(
    interaction: discord.Interaction,
    action: app_commands.Choice[str] | None = None,
    channel_id: str | None = None,
):
    selected_action = action.value if action else "status"
    target_channel = await resolve_sega_facebook_channel(interaction, channel_id)

    if selected_action == "status":
        if interaction.guild is None and interaction.user.id != BOT_DEVELOPER_ID:
            await interaction.response.send_message(
                "DM에서는 봇 관리자만 세가 Facebook 알림 상태를 확인할 수 있습니다.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            format_sega_facebook_status(interaction, target_channel),
            ephemeral=True,
        )
        return

    if target_channel is None:
        await interaction.response.send_message(
            "알림을 관리할 텍스트 채널을 찾지 못했습니다. DM에서는 `채널id`를 함께 입력해주세요.",
            ephemeral=True,
        )
        return

    if not user_can_manage_sega_facebook(interaction, target_channel):
        await interaction.response.send_message(
            "서버 관리 권한이 있거나 봇 관리자일 때만 이 채널 알림을 변경할 수 있습니다.",
            ephemeral=True,
        )
        return

    if selected_action == "enable":
        permissions = target_channel.permissions_for(target_channel.guild.me)

        if not permissions.send_messages or not permissions.embed_links:
            await interaction.response.send_message(
                f"{target_channel.mention}에 메시지와 임베드를 보낼 권한이 필요합니다.",
                ephemeral=True,
            )
            return

        set_sega_facebook_channel(target_channel.guild.id, target_channel.id)

        if FACEBOOK_ACCESS_TOKEN:
            note = "새 게시물 확인은 폴링 주기에 따라 진행됩니다."
        else:
            note = "다만 아직 `FACEBOOK_ACCESS_TOKEN`이 설정되지 않아 실제 확인은 시작되지 않았습니다."

        await interaction.response.send_message(
            f"세가 Facebook 알림을 {target_channel.mention} 채널에 켰습니다. {note}",
            ephemeral=True,
        )
        return

    removed = remove_sega_facebook_channel(target_channel.id)

    if removed:
        message = f"세가 Facebook 알림을 {target_channel.mention} 채널에서 껐습니다."
    else:
        message = f"{target_channel.mention} 채널에는 켜진 세가 Facebook 알림이 없습니다."

    await interaction.response.send_message(message, ephemeral=True)


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
