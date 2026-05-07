import asyncio
import os
import re
from datetime import datetime

import discord
from discord import app_commands
from dotenv import load_dotenv

import livecheck


load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in .env")


# 명령어 표시 여부는 bot.py에서 한 번에 관리합니다.
ENABLE_DEBUG_COMMAND = False


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


@tree.command(name="겜플라이브", description="밀크봇한테 겜플 츄마이 라이브 현황 확인시키기")
async def gameplaza_live(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    try:
        items = await asyncio.to_thread(livecheck.fetch_gameplaza_live_status)
        image_buffer = await asyncio.to_thread(livecheck.make_gameplaza_grid_image, items)
    except Exception as e:
        embed = discord.Embed(
            title="게임플라자 라이브 상태 확인 실패",
            description=f"처리 중 오류가 발생했습니다.\n\n```{type(e).__name__}: {e}```",
            color=discord.Color.red(),
        )
        await interaction.followup.send(embed=embed)
        return

    now = datetime.now(livecheck.KST).strftime("%Y-%m-%d %H:%M:%S KST")
    live_count = sum(1 for item in items if item["is_live"])

    embed = discord.Embed(
        title="게임플라자 라이브 상태",
        description=(
            f"[@GAMEPLAZA_C/streams]({livecheck.CHANNEL_STREAMS_URL})\n"
            f"확인 시각: `{now}`\n"
            f"라이브: `{live_count}/8`"
        ),
        color=discord.Color.blue(),
    )

    maimai_items = [item for item in items if item["group"] == "마이마이 디럭스"]
    chunithm_items = [item for item in items if item["group"] == "츄니즘"]

    embed.add_field(
        name="마이마이 디럭스",
        value=" / ".join(format_machine_link(item) for item in maimai_items),
        inline=False,
    )

    embed.add_field(
        name="츄니즘",
        value=" / ".join(format_machine_link(item) for item in chunithm_items),
        inline=False,
    )

    file = discord.File(fp=image_buffer, filename="gameplaza_live_grid.jpg")
    embed.set_image(url="attachment://gameplaza_live_grid.jpg")

    footer_text = livecheck.get_response_footer_text()
    if footer_text:
        embed.set_footer(text=footer_text)

    await interaction.followup.send(embed=embed, file=file)


def format_machine_link(item: dict) -> str:
    match = re.search(r"(\d+)번기", item["label"])
    machine_name = f"{match.group(1)}번기" if match else item["label"]

    if item["is_live"] and item["url"]:
        return f"[{machine_name}]({item['url']})"

    return "[----]"


if ENABLE_DEBUG_COMMAND:
    @tree.command(name="겜플디버그", description="게임플라자 /streams 조회 디버그 정보를 확인합니다.")
    async def gameplaza_debug(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            items = await asyncio.to_thread(livecheck.fetch_gameplaza_live_status, True)
        except Exception as e:
            await interaction.followup.send(f"디버그 실패:\n```{type(e).__name__}: {e}```", ephemeral=True)
            return

        status_lines = [
            f"{item['label']}: {'LIVE' if item['is_live'] else 'OFFLINE'} | {item['url'] or '-'}"
            for item in items
        ]

        debug_text = "\n".join(status_lines + ["", "--- RAW ENTRIES ---"] + livecheck.get_debug_rows(limit=35))

        if len(debug_text) > 1900:
            debug_text = debug_text[:1900] + "\n... truncated"

        await interaction.followup.send(f"```text\n{debug_text}\n```", ephemeral=True)


client.run(TOKEN)
