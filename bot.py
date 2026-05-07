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


ENABLE_DEBUG_COMMAND = False

SEGA_MAINTENANCE_START_HOUR = 4
SEGA_MAINTENANCE_END_HOUR = 7

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def is_sega_maintenance_time() -> bool:
    now = datetime.now(livecheck.KST)
    return SEGA_MAINTENANCE_START_HOUR <= now.hour < SEGA_MAINTENANCE_END_HOUR


@client.event
async def on_ready():
    synced = await tree.sync()
    print(f"Logged in as {client.user}")
    print(f"Synced commands: {[cmd.name for cmd in synced]}")


@tree.command(name="ping", description="밀크봇 부르기")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong")


if ENABLE_DEBUG_COMMAND:
    @tree.command(name="겜플디버그", description="게임플라자 라이브 조회 디버그 정보를 확인합니다.")
    async def gameplaza_debug(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)

        try:
            items = await asyncio.to_thread(livecheck.fetch_gameplaza_live_status, True)
        except Exception as e:
            await interaction.followup.send(
                f"디버그 실패:\n```{type(e).__name__}: {e}```",
                ephemeral=True,
            )
            return

        status_lines = [
            f"{item['label']}: {'LIVE' if item['is_live'] else 'OFFLINE'} | {item['url'] or '-'}"
            for item in items
        ]

        debug_text = "\n".join(
            status_lines
            + ["", "--- RAW ENTRIES ---"]
            + livecheck.get_debug_rows(35)
        )

        if len(debug_text) > 1900:
            debug_text = debug_text[:1900] + "\n... truncated"

        await interaction.followup.send(f"```text\n{debug_text}\n```", ephemeral=True)


@tree.command(name="겜플라이브", description="밀크봇한테 겜플 츄마이 라이브 현황 확인시키기")
@app_commands.describe(
    ignore_no_stream_notice="스트림이 감지되지 않아도 경고를 띄우지 않는 옵션; 기본값은 꺼짐 (False) 이에요."
)
async def gameplaza_live(
    interaction: discord.Interaction,
    ignore_no_stream_notice: bool = False,
):
    if is_sega_maintenance_time():
        await interaction.response.send_message(
            "SEGA 서버 점검 시간이에요;; 잠이나 자세요;;;;"
        )
        return

    await interaction.response.defer(thinking=True)

    try:
        items = await asyncio.to_thread(livecheck.fetch_gameplaza_live_status)

        if livecheck.should_send_no_stream_warning() and not ignore_no_stream_notice:
            await interaction.followup.send(
                livecheck.get_no_stream_warning_text(),
                ephemeral=True,
            )
            return

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

    def format_machine_link(item: dict) -> str:
        match = re.search(r"(\d+)번기", item["label"])
        machine_name = f"{match.group(1)}번기" if match else item["label"]

        if item["is_live"] and item["url"]:
            return f"[{machine_name}]({item['url']})"

        return "[----]"

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


client.run(TOKEN)