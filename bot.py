import asyncio
import os
import subprocess
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from dotenv import load_dotenv

from thumbnail_board import build_gameplaza_thumbnail_board
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
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
_synced = False
_update_dm_sent = False


# ---------------------------------------------------------------------------
# 새 슬래시 명령어를 추가하는 곳
# ---------------------------------------------------------------------------
# 명령어는 모두 전역 Application Command로 등록하고,
# allowed_installs / allowed_contexts로 설치 방식과 실행 위치를 구분합니다.
#
# [1] 서버 설치(Guild Install) 전용
#
# @tree.command(name="서버명령어", description="서버에서만 사용하는 명령어입니다.")
# @app_commands.allowed_installs(guilds=True, users=False)
# @app_commands.allowed_contexts(
#     guilds=True,
#     dms=False,
#     private_channels=False,
# )
# async def guild_only_command(interaction: discord.Interaction) -> None:
#     await interaction.response.send_message("서버 전용 명령어")
#
#
# [2] 사용자 설치(User Install) 전용
# 사용자가 밀크봇을 자기 계정에 설치한 뒤, 봇이 들어가 있지 않은 서버나
# DM/GDM 등에서도 사용할 개인용 명령어에 사용합니다.
#
# @tree.command(name="개인명령어", description="개인 앱으로 사용하는 명령어입니다.")
# @app_commands.allowed_installs(guilds=False, users=True)
# @app_commands.allowed_contexts(
#     guilds=True,
#     dms=True,
#     private_channels=True,
# )
# async def user_only_command(interaction: discord.Interaction) -> None:
#     await interaction.response.send_message("사용자 설치 전용 명령어")
#
#
# [3] 서버 설치 + 사용자 설치 모두 허용
# 조회/계산처럼 서버 권한이 필요 없는 명령어에 적합합니다.
#
# @tree.command(name="공용명령어", description="어디서나 사용할 수 있는 명령어입니다.")
# @app_commands.allowed_installs(guilds=True, users=True)
# @app_commands.allowed_contexts(
#     guilds=True,
#     dms=True,
#     private_channels=True,
# )
# async def shared_command(interaction: discord.Interaction) -> None:
#     await interaction.response.send_message("공용 명령어")
#
#
# name은 Discord에 표시할 명령어 이름, description은 명령어 설명입니다.
# 사용자가 입력할 옵션은 함수 매개변수로 추가할 수 있습니다.
# 처리 시간이 길면 interaction.response.defer() 후
# interaction.followup.send(...)로 결과를 전송하세요.
#
# 명령어를 추가한 뒤 봇을 재시작하면 on_ready()의 tree.sync()가
# Discord의 전역 Application Command 목록을 동기화합니다.

@tree.command(name="임베드테스트", description="곡 선택 임베드 테스트용")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(
    guilds=True,
    dms=True,
    private_channels=True,
)
async def foo(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="**系ぎて** <:dx1:1541721576771162152><:dx2:1541721578595942452><:dx3:1541721580156223508><:dx4:1541721581493952523>",
        url=r"https://arcade-songs.zetaraku.dev/maimai/song/?id=%E7%B3%BB%E3%81%8E%E3%81%A6",
        color=0xba67f8,
    )
    embed.set_image(url="https://dp4p6x0xfi5o9.cloudfront.net/maimai/img/cover/3a914643f53b41ab5b3f0be0bb501b895a52660f8c78f8317a87a7669efc7930.png")
    embed.set_footer(text="song by rintaro soma")

    view = discord.ui.View()

    view.add_item(
    discord.ui.Button(
        label="자세히 보기",
        style=discord.ButtonStyle.secondary,
        custom_id="detail",
        )
    )

    view.add_item(
        discord.ui.Button(
            label="다시 뽑기",
            style=discord.ButtonStyle.secondary,
            custom_id="reroll",
        )
    )

    await interaction.response.send_message(content="<:remas1:1541815179506094202><:remas2:1541815181292736637><:remas3:1541815184153382952>:one::five:", embed=embed, view=view)

@tree.command(name="겜플라이브", description="게임플라자 라이브 상태를 확인합니다.")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(
    guilds=True,
    dms=True,
    private_channels=True,
)
async def gameplaza_live(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)

    try:
        statuses = await asyncio.to_thread(get_gameplaza_machine_statuses)
    except YouTubeLiveError:
        await interaction.followup.send(
            "유튜브 라이브 상태를 확인하지 못했습니다. 잠시 후 다시 시도해주세요.\n"
            f"{GAMEPLAZA_YOUTUBE_URL}"
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
    if not status.is_live or status.live_url is None:
        return "[---]"

    return f"[{status.number}번기]({status.live_url})"


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
    embed.add_field(
        name="마이마이 디럭스",
        value=" / ".join(_format_status(status) for status in statuses[:5]),
        inline=False,
    )
    embed.add_field(
        name="츄니즘",
        value=" / ".join(_format_status(status) for status in statuses[5:]),
        inline=False,
    )
    embed.set_image(url="attachment://gameplaza_live.jpg")
    return embed


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
        user = client.get_user(BOT_DEVELOPER_ID) or await client.fetch_user(
            BOT_DEVELOPER_ID
        )
        commit = await asyncio.to_thread(get_current_commit)
        await user.send(f"밀크봇 업데이트 완료!\n`{commit}`")
    except Exception:
        # DM 차단, 잘못된 사용자 ID 등의 문제로 봇 자체가 종료되지는 않게 합니다.
        return


@client.event
async def on_ready() -> None:
    global _synced, _update_dm_sent

    if not _synced:
        await tree.sync()
        for guild in client.guilds:
            await tree.sync(guild=guild)
        _synced = True

    if not _update_dm_sent:
        await notify_developer_update()
        _update_dm_sent = True

    print(f"Logged in as {client.user}")


client.run(TOKEN)