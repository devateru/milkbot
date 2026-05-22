import asyncio
import os
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from dotenv import load_dotenv

from dev_commands import handle_developer_dm_command
from help_commands import build_server_help_embeds
from messages import get_message
from random_song_command import (
    build_chunithm_probability_table_embed,
    build_maimai_probability_table_embed,
    register_random_song_command,
)
from storage import (
    get_twitter_update_channel_config,
    get_twitter_update_channel_configs,
    get_twitter_update_dm_channel_config,
    get_twitter_update_dm_channel_configs,
    normalize_handle_text,
    set_twitter_update_channel_config,
    set_twitter_update_dm_channel_config,
)
from thumbnail_board import build_gameplaza_thumbnail_board
from treat import handle_notreat, register_treat_command
from twitter_updates import (
    DEFAULT_HANDLES,
    SPECIAL_DEFAULT_CHANNEL_ID,
    SPECIAL_GUILD_ID,
    default_handles_for_guild,
    poll_forever as poll_twitter_updates_forever,
)
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
X_TOKEN = os.getenv("X_TOKEN")
TWITTER_UPDATE_POLL_SECONDS = int(os.getenv("TWITTER_UPDATE_POLL_SECONDS", "60"))

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
_twitter_update_task: asyncio.Task | None = None
_update_dm_sent = False

register_random_song_command(tree)
register_treat_command(tree)


@client.event
async def on_ready():
    global _synced, _twitter_update_task, _update_dm_sent

    if not _synced:
        await tree.sync()
        _synced = True

    if _twitter_update_task is None or _twitter_update_task.done():
        _twitter_update_task = asyncio.create_task(
            poll_twitter_updates_forever(
                client,
                X_TOKEN,
                TWITTER_UPDATE_POLL_SECONDS,
                get_twitter_update_targets,
            )
        )

    if not _update_dm_sent:
        await notify_developer_update()
        _update_dm_sent = True

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


def _handles_from_channel_config(
    guild_id: int,
    channel_id: int,
    config: dict[str, object] | None,
) -> list[str]:
    if config is None:
        if guild_id == SPECIAL_GUILD_ID and channel_id == SPECIAL_DEFAULT_CHANNEL_ID:
            return default_handles_for_guild(guild_id)

        return []

    handles = config.get("handles", [])

    if not isinstance(handles, list):
        return default_handles_for_guild(guild_id)

    fixed_handles: list[str] = []

    for handle in handles:
        handle_text = normalize_handle_text(handle)

        if handle_text and handle_text not in fixed_handles:
            fixed_handles.append(handle_text)

    return fixed_handles


def _handles_from_dm_config(config: dict[str, object] | None) -> list[str]:
    if config is None:
        return []

    handles = config.get("handles", [])

    if not isinstance(handles, list):
        return list(DEFAULT_HANDLES)

    fixed_handles: list[str] = []

    for handle in handles:
        handle_text = normalize_handle_text(handle)

        if handle_text and handle_text not in fixed_handles:
            fixed_handles.append(handle_text)

    return fixed_handles


def is_twitter_update_channel_enabled(
    guild_id: int,
    channel_id: int,
    config: dict[str, object] | None,
) -> bool:
    if config is None:
        return guild_id == SPECIAL_GUILD_ID and channel_id == SPECIAL_DEFAULT_CHANNEL_ID

    return bool(config.get("enabled", False))


def is_twitter_update_dm_enabled(config: dict[str, object] | None) -> bool:
    if config is None:
        return False

    return bool(config.get("enabled", False))


def get_twitter_update_targets() -> list[dict[str, object]]:
    targets: list[dict[str, object]] = []

    for guild in client.guilds:
        channels = get_twitter_update_channel_configs(guild.id)

        if guild.id == SPECIAL_GUILD_ID:
            channels.setdefault(str(SPECIAL_DEFAULT_CHANNEL_ID), {})

        for channel_id_text, config in channels.items():
            if not channel_id_text.isdigit():
                continue

            channel_id = int(channel_id_text)
            stored_config = get_twitter_update_channel_config(guild.id, channel_id)

            if not is_twitter_update_channel_enabled(guild.id, channel_id, stored_config):
                continue

            handles = _handles_from_channel_config(guild.id, channel_id, stored_config)

            if not handles:
                continue

            targets.append(
                {
                    "kind": "guild",
                    "guild_id": guild.id,
                    "channel_id": channel_id,
                    "handles": handles,
                }
            )

    for channel_id_text, config in get_twitter_update_dm_channel_configs().items():
        if not channel_id_text.isdigit() or not is_twitter_update_dm_enabled(config):
            continue

        user_id = str(config.get("user_id", "")).strip()
        handles = _handles_from_dm_config(config)

        if not user_id.isdigit() or not handles:
            continue

        targets.append(
            {
                "kind": "dm",
                "channel_id": int(channel_id_text),
                "user_id": int(user_id),
                "handles": handles,
            }
        )

    return targets


async def resolve_twitter_update_channel(
    interaction: discord.Interaction,
    channel_id: str | None,
) -> discord.TextChannel | None:
    if channel_id:
        channel_id_text = channel_id.strip()

        if not channel_id_text.isdigit():
            return None

        channel = client.get_channel(int(channel_id_text))

        if channel is None:
            try:
                channel = await client.fetch_channel(int(channel_id_text))
            except discord.DiscordException:
                return None

        return channel if isinstance(channel, discord.TextChannel) else None

    return interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None


def can_manage_twitter_update(interaction: discord.Interaction, guild: discord.Guild) -> bool:
    if interaction.user.id == BOT_DEVELOPER_ID:
        return True

    if interaction.guild is None:
        return False

    if interaction.guild.id != guild.id:
        return False

    return can_manage_server(interaction)


def format_handle_list(handles: list[str]) -> str:
    if not handles:
        return "추적 중인 계정이 없습니다."

    return "\n".join(f"- @{handle} - <https://x.com/{handle}>" for handle in handles)


def twitter_update_has_enabled_channel(guild_id: int) -> bool:
    channels = get_twitter_update_channel_configs(guild_id)

    if guild_id == SPECIAL_GUILD_ID:
        channels.setdefault(str(SPECIAL_DEFAULT_CHANNEL_ID), {})

    for channel_id_text in channels:
        if not channel_id_text.isdigit():
            continue

        channel_id = int(channel_id_text)
        config = get_twitter_update_channel_config(guild_id, channel_id)

        if is_twitter_update_channel_enabled(guild_id, channel_id, config):
            return True

    return False


def default_handles_for_new_channel(guild_id: int, channel_id: int) -> list[str]:
    if guild_id == SPECIAL_GUILD_ID and channel_id == SPECIAL_DEFAULT_CHANNEL_ID:
        return default_handles_for_guild(guild_id)

    if twitter_update_has_enabled_channel(guild_id):
        return []

    return list(DEFAULT_HANDLES)


def format_twitter_update_status(channel: discord.TextChannel) -> str:
    config = get_twitter_update_channel_config(channel.guild.id, channel.id)
    enabled = is_twitter_update_channel_enabled(channel.guild.id, channel.id, config)
    handles = _handles_from_channel_config(channel.guild.id, channel.id, config)
    token_status = "설정됨" if X_TOKEN else "없음"

    return (
        f"서버: {channel.guild.name} (`{channel.guild.id}`)\n"
        f"채널: {channel.mention} (`{channel.id}`)\n"
        f"상태: {'활성화' if enabled else '비활성화'}\n"
        f"X 토큰: {token_status}\n"
        f"확인 주기: {TWITTER_UPDATE_POLL_SECONDS}초\n\n"
        f"{format_handle_list(handles)}"
    )


def format_twitter_update_dm_status(channel: discord.abc.Messageable) -> str:
    config = get_twitter_update_dm_channel_config(channel.id)
    enabled = is_twitter_update_dm_enabled(config)
    handles = _handles_from_dm_config(config)

    return (
        f"DM 채널: `{channel.id}`\n"
        f"상태: {'활성화' if enabled else '비활성화'}\n"
        f"X 토큰: {'설정됨' if X_TOKEN else '없음'}\n"
        f"확인 주기: {TWITTER_UPDATE_POLL_SECONDS}초\n\n"
        f"{format_handle_list(handles)}"
    )


@tree.command(name="트위터업뎃", description="현재 추적 중인 X 계정 목록을 확인합니다.")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def twitter_update_status(interaction: discord.Interaction):
    if isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message(
            format_twitter_update_status(interaction.channel),
            ephemeral=True,
        )
        return

    if interaction.guild is None and interaction.channel is not None:
        await interaction.response.send_message(
            format_twitter_update_dm_status(interaction.channel),
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        "현재 채널의 트위터 업뎃 상태를 확인할 수 없습니다.",
        ephemeral=True,
    )


@tree.command(name="트위터업뎃-활성화", description="이 서버의 X 게시물 알림을 활성화합니다.")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def twitter_update_enable(interaction: discord.Interaction):
    if interaction.guild is None and interaction.channel is not None:
        config = get_twitter_update_dm_channel_config(interaction.channel.id)
        handles = _handles_from_dm_config(config)

        if not handles and config is None:
            handles = list(DEFAULT_HANDLES)

        set_twitter_update_dm_channel_config(
            interaction.channel.id,
            interaction.user.id,
            enabled=True,
            handles=handles,
        )

        if X_TOKEN:
            note = "새 게시물 확인은 폴링 주기에 따라 진행됩니다."
        else:
            note = "다만 아직 `X_TOKEN`이 설정되지 않아 실제 확인은 시작되지 않았습니다."

        await interaction.response.send_message(f"이 DM에 트위터 업뎃을 활성화했습니다. {note}", ephemeral=True)
        return

    channel = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None

    if channel is None:
        await interaction.response.send_message("알림을 보낼 텍스트 채널을 찾지 못했습니다.", ephemeral=True)
        return

    guild = channel.guild

    if not can_manage_twitter_update(interaction, guild):
        await interaction.response.send_message(
            "서버 관리 권한이 있거나 봇 관리자일 때만 트위터 업뎃을 활성화할 수 있습니다.",
            ephemeral=True,
        )
        return

    me = guild.me

    if me is None and client.user is not None:
        me = guild.get_member(client.user.id)

    if me is None and client.user is not None:
        try:
            me = await guild.fetch_member(client.user.id)
        except discord.DiscordException:
            me = None

    if me is None:
        await interaction.response.send_message("이 서버의 봇 권한을 확인하지 못했습니다.", ephemeral=True)
        return

    permissions = channel.permissions_for(me)

    if not permissions.send_messages or not permissions.embed_links:
        await interaction.response.send_message(
            f"{channel.mention}에 메시지와 임베드를 보낼 권한이 필요합니다.",
            ephemeral=True,
        )
        return

    config = get_twitter_update_channel_config(guild.id, channel.id)
    handles = _handles_from_channel_config(guild.id, channel.id, config)

    if not handles and config is None:
        handles = default_handles_for_new_channel(guild.id, channel.id)

    set_twitter_update_channel_config(guild.id, channel.id, enabled=True, handles=handles)

    if X_TOKEN:
        note = "새 게시물 확인은 폴링 주기에 따라 진행됩니다."
    else:
        note = "다만 아직 `X_TOKEN`이 설정되지 않아 실제 확인은 시작되지 않았습니다."

    await interaction.response.send_message(
        f"트위터 업뎃을 {channel.mention} 채널에 활성화했습니다. {note}",
        ephemeral=True,
    )


@tree.command(name="트위터업뎃-추가", description="서버의 X 게시물 알림 추적 계정을 추가합니다.")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.rename(account="계정", channel_id="채널id")
@app_commands.describe(
    account="추가할 계정 링크 또는 핸들입니다.",
    channel_id="DM에서 수정할 서버 채널 ID입니다. 서버에서는 비워두면 현재 채널을 수정합니다.",
)
async def twitter_update_add(
    interaction: discord.Interaction,
    account: str,
    channel_id: str | None = None,
):
    channel = await resolve_twitter_update_channel(interaction, channel_id)
    handle = normalize_handle_text(account)

    if channel is None:
        await interaction.response.send_message(
            "수정할 채널을 찾지 못했습니다. DM에서는 `채널id`를 함께 입력해주세요.",
            ephemeral=True,
        )
        return

    if not handle:
        await interaction.response.send_message("계정 링크 또는 핸들 형식을 확인해주세요.", ephemeral=True)
        return

    if not can_manage_twitter_update(interaction, channel.guild):
        await interaction.response.send_message(
            "서버 관리 권한이 있거나 봇 관리자일 때만 트위터 업뎃 목록을 수정할 수 있습니다.",
            ephemeral=True,
        )
        return

    config = get_twitter_update_channel_config(channel.guild.id, channel.id)
    handles = _handles_from_channel_config(channel.guild.id, channel.id, config)

    if handle in handles:
        await interaction.response.send_message(f"`@{handle}`은 이미 추적 중입니다.", ephemeral=True)
        return

    handles.append(handle)
    set_twitter_update_channel_config(
        channel.guild.id,
        channel.id,
        enabled=is_twitter_update_channel_enabled(channel.guild.id, channel.id, config),
        handles=handles,
    )

    await interaction.response.send_message(f"`@{handle}`을 트위터 업뎃 목록에 추가했습니다.", ephemeral=True)


@tree.command(name="트위터업뎃-삭제", description="서버의 X 게시물 알림 추적 계정을 삭제합니다.")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.rename(account="계정", channel_id="채널id")
@app_commands.describe(
    account="삭제할 계정 링크 또는 핸들입니다.",
    channel_id="DM에서 수정할 서버 채널 ID입니다. 서버에서는 비워두면 현재 채널을 수정합니다.",
)
async def twitter_update_remove(
    interaction: discord.Interaction,
    account: str,
    channel_id: str | None = None,
):
    channel = await resolve_twitter_update_channel(interaction, channel_id)
    handle = normalize_handle_text(account)

    if channel is None:
        await interaction.response.send_message(
            "수정할 채널을 찾지 못했습니다. DM에서는 `채널id`를 함께 입력해주세요.",
            ephemeral=True,
        )
        return

    if not handle:
        await interaction.response.send_message("계정 링크 또는 핸들 형식을 확인해주세요.", ephemeral=True)
        return

    if not can_manage_twitter_update(interaction, channel.guild):
        await interaction.response.send_message(
            "서버 관리 권한이 있거나 봇 관리자일 때만 트위터 업뎃 목록을 수정할 수 있습니다.",
            ephemeral=True,
        )
        return

    config = get_twitter_update_channel_config(channel.guild.id, channel.id)
    handles = _handles_from_channel_config(channel.guild.id, channel.id, config)

    if handle not in handles:
        await interaction.response.send_message(f"`@{handle}`은 현재 추적 목록에 없습니다.", ephemeral=True)
        return

    handles.remove(handle)
    set_twitter_update_channel_config(
        channel.guild.id,
        channel.id,
        enabled=is_twitter_update_channel_enabled(channel.guild.id, channel.id, config),
        handles=handles,
    )

    await interaction.response.send_message(f"`@{handle}`을 트위터 업뎃 목록에서 삭제했습니다.", ephemeral=True)


@tree.command(name="트위터업뎃-비활성화", description="이 서버의 X 게시물 알림을 비활성화합니다.")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.rename(channel_id="채널id")
@app_commands.describe(channel_id="DM에서 비활성화할 서버 채널 ID입니다. 서버에서는 비워두면 현재 채널을 비활성화합니다.")
async def twitter_update_disable(
    interaction: discord.Interaction,
    channel_id: str | None = None,
):
    channel = await resolve_twitter_update_channel(interaction, channel_id)

    if channel is None:
        await interaction.response.send_message(
            "비활성화할 채널을 찾지 못했습니다. DM에서는 `채널id`를 함께 입력해주세요.",
            ephemeral=True,
        )
        return

    if not can_manage_twitter_update(interaction, channel.guild):
        await interaction.response.send_message(
            "서버 관리 권한이 있거나 봇 관리자일 때만 트위터 업뎃을 비활성화할 수 있습니다.",
            ephemeral=True,
        )
        return

    config = get_twitter_update_channel_config(channel.guild.id, channel.id)
    set_twitter_update_channel_config(
        channel.guild.id,
        channel.id,
        enabled=False,
        handles=_handles_from_channel_config(channel.guild.id, channel.id, config),
    )

    await interaction.response.send_message(f"{channel.mention} 채널의 트위터 업뎃을 비활성화했습니다.", ephemeral=True)


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
        await handle_developer_dm_command(message, client, BOT_DEVELOPER_ID)
        return

    content = message.content.strip()
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
