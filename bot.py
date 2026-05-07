import asyncio
import os
import re
import unicodedata
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from dotenv import load_dotenv
from yt_dlp import YoutubeDL


load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in .env")


CHANNEL_STREAMS_URL = "https://www.youtube.com/@GAMEPLAZA_C/streams"

TARGET_STREAMS = [
    "광주 게임플라자 마이마이 디럭스 maimai DX (1번기) LIVE",
    "광주 게임플라자 마이마이 디럭스 maimai DX (2번기) LIVE",
    "광주 게임플라자 마이마이 디럭스 maimai DX (3번기) LIVE",
    "광주 게임플라자 마이마이 디럭스 maimai DX (4번기) LIVE",
    "광주 게임플라자 마이마이 디럭스 maimai DX (5번기) LIVE",
    "광주 게임플라자 츄니즘 CHUNITHM (1번기) LIVE",
    "광주 게임플라자 츄니즘 CHUNITHM (2번기) LIVE",
    "광주 게임플라자 츄니즘 CHUNITHM (3번기) LIVE",
]


KST = timezone(timedelta(hours=9))


def normalize_title(text: str) -> str:
    """
    YouTube 제목 비교용 정규화 함수입니다.
    공백 차이, 유니코드 정규화 차이 때문에 exact match가 실패하는 것을 줄입니다.
    """
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_video_url(entry: dict) -> str | None:
    video_id = entry.get("id")
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"

    url = entry.get("url")
    if url:
        if url.startswith("http"):
            return url
        return f"https://www.youtube.com/watch?v={url}"

    return None


def is_live_entry(entry: dict) -> bool:
    """
    yt-dlp가 주는 live_status / is_live 값을 기준으로 현재 라이브 여부를 판단합니다.
    """
    live_status = entry.get("live_status")
    is_live = entry.get("is_live")

    if is_live is True:
        return True

    if live_status == "is_live":
        return True

    return False


def fetch_gameplaza_live_status() -> dict[str, str | None]:
    """
    GAMEPLAZA_C /streams 페이지에서 현재 라이브 중인 대상 방송 링크를 찾습니다.

    return:
        {
            "방송 제목": "https://www.youtube.com/watch?v=..." 또는 None
        }
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "ignoreerrors": True,
        "playlistend": 50,
        "socket_timeout": 20,
        "retries": 1,
        "extractor_retries": 1,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(CHANNEL_STREAMS_URL, download=False)

    entries = info.get("entries", []) if info else []

    live_by_title: dict[str, str] = {}

    for entry in entries:
        if not entry:
            continue

        title = normalize_title(entry.get("title", ""))
        if not title:
            continue

        if not is_live_entry(entry):
            continue

        url = get_video_url(entry)
        if not url:
            continue

        live_by_title[title] = url

    result: dict[str, str | None] = {}

    for target in TARGET_STREAMS:
        normalized_target = normalize_title(target)
        result[target] = live_by_title.get(normalized_target)

    return result


intents = discord.Intents.default()

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@client.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {client.user}")


@tree.command(name="ping", description="밀크봇 부르기")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong")


@tree.command(name="겜플라이브", description="밀크봇한테 츄마이 방송 현황 확인시키기")
async def gameplaza_live(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    try:
        status = await asyncio.to_thread(fetch_gameplaza_live_status)
    except Exception as e:
        embed = discord.Embed(
            title="게임플라자 라이브 상태 확인 실패",
            description=f"유튜브 스트림 목록을 가져오는 중 오류가 발생했습니다.\n\n```{type(e).__name__}: {e}```",
            color=discord.Color.red(),
        )
        await interaction.followup.send(embed=embed)
        return

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")

    embed = discord.Embed(
        title="게임플라자 라이브 상태",
        description=f"[채널 스트림 목록]({CHANNEL_STREAMS_URL})\n확인 시각: `{now}`",
        color=discord.Color.blue(),
    )

    for title, url in status.items():
        short_name = title.replace("광주 게임플라자 ", "")

        if url:
            value = f"[라이브 링크]({url})"
        else:
            value = "오프라인"

        embed.add_field(
            name=short_name,
            value=value,
            inline=False,
        )

    embed.set_footer(text="YouTube /streams 목록 기준")

    await interaction.followup.send(embed=embed)


client.run(TOKEN)