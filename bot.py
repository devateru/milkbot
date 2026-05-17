import asyncio
import os

import discord
from discord import app_commands
from dotenv import load_dotenv

from dev_commands import handle_developer_dm_command
from help_commands import build_server_help_embeds
from messages import get_message
from treat import handle_notreat, handle_user_dm_command
from youtube_live import YouTubeLiveError, YouTubeLiveVideo, get_gameplaza_live_video


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
        live_video = await asyncio.to_thread(get_gameplaza_live_video)
    except YouTubeLiveError:
        await interaction.followup.send(
            get_message("slash.gameplaza_error", url=GAMEPLAZA_YOUTUBE_URL)
        )
        return

    if live_video is None:
        await interaction.followup.send(
            get_message("slash.gameplaza_offline", url=GAMEPLAZA_YOUTUBE_URL)
        )
        return

    await interaction.followup.send(embed=build_gameplaza_live_embed(live_video))


def build_gameplaza_live_embed(live_video: YouTubeLiveVideo) -> discord.Embed:
    description = live_video.description.strip()
    if len(description) > 300:
        description = f"{description[:297]}..."

    embed = discord.Embed(
        title=live_video.title,
        url=live_video.url,
        description=description or get_message("slash.gameplaza_live"),
    )
    embed.add_field(name="채널", value=live_video.channel_title, inline=True)

    if live_video.actual_start_time is not None:
        started_at = int(live_video.actual_start_time.timestamp())
        embed.add_field(name="시작", value=f"<t:{started_at}:R>", inline=True)

    if live_video.concurrent_viewers is not None:
        try:
            viewers = f"{int(live_video.concurrent_viewers):,}명"
        except ValueError:
            viewers = f"{live_video.concurrent_viewers}명"

        embed.add_field(
            name="시청자",
            value=viewers,
            inline=True,
        )

    if live_video.thumbnail_url:
        embed.set_image(url=live_video.thumbnail_url)

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
