import asyncio
import os
from datetime import datetime
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
GAMEPLAZA_YOUTUBE_URL = os.getenv(
    "GAMEPLAZA_YOUTUBE_URL",
    "https://www.youtube.com/@GAMEPLAZA_C/streams",
)

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in .env")


intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
_synced = False


# ---------------------------------------------------------------------------
# 새 슬래시 명령어를 추가하는 곳
# ---------------------------------------------------------------------------
# 1. 아래 예시처럼 @tree.command(...) 데코레이터를 붙인 async 함수를 만드세요.
# 2. name은 Discord에 표시할 명령어 이름, description은 명령어 설명입니다.
# 3. 사용자가 입력할 옵션은 함수 매개변수로 추가할 수 있습니다.
# 4. 최초 응답은 interaction.response.send_message(...)로 전송합니다.
# 5. 처리 시간이 길면 먼저 interaction.response.defer()를 호출한 뒤
#    interaction.followup.send(...)로 결과를 전송하세요.
# 6. 명령어를 추가한 뒤 봇을 재시작하면 on_ready()의 tree.sync()가 Discord에
#    명령어 목록을 반영합니다. 기존 명령어가 바로 사라지지 않으면 Discord 쪽
#    동기화에 잠시 시간이 걸릴 수 있습니다.
#
# 예시:
# @tree.command(name="안녕", description="인사를 합니다.")
# async def hello(interaction: discord.Interaction, 이름: str = "친구") -> None:
#     await interaction.response.send_message(f"안녕하세요, {이름}님!")


@tree.command(name="겜플라이브", description="게임플라자 라이브 상태를 확인합니다.")
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


@client.event
async def on_ready() -> None:
    global _synced

    if not _synced:
        await tree.sync()
        _synced = True

    print(f"Logged in as {client.user}")


client.run(TOKEN)
