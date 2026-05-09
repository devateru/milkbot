import json
import os
import re
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv


load_dotenv(".env")

TOKEN = os.getenv("DISCORD_TOKEN")
BOT_DEVELOPER_ID = os.getenv("BOT_DEVELOPER_ID")
GAMEPLAZA_YOUTUBE_URL = os.getenv("GAMEPLAZA_YOUTUBE_URL", "https://www.youtube.com/@GAMEPLAZA_C/streams")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in .env")

if not BOT_DEVELOPER_ID:
    raise RuntimeError("BOT_DEVELOPER_ID is not set in .env")

BOT_DEVELOPER_ID = int(BOT_DEVELOPER_ID)

STATE_FILE = Path("milkbot_state.json")
ACTIVE_SONIC_SESSIONS = set()


def default_state() -> dict:
    return {
        "notreat_rules": {}
    }


def load_state() -> dict:
    if not STATE_FILE.exists():
        return default_state()

    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return default_state()

    rules = data.get("notreat_rules", {})

    fixed_rules = {}
    for uid, treats in rules.items():
        if isinstance(treats, list):
            fixed_rules[str(uid)] = [str(t).strip() for t in treats if str(t).strip()]
        elif isinstance(treats, str) and treats.strip():
            fixed_rules[str(uid)] = [treats.strip()]

    return {
        "notreat_rules": fixed_rules
    }


def save_state() -> None:
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


state = load_state()

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


@tree.command(name="ping", description="밀크봇 부르기")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong")


@tree.command(name="겜플라이브", description="게임플라자 라이브 상태를 확인합니다.")
async def gameplaza_live(interaction: discord.Interaction):
    await interaction.response.send_message(
        "현재 유튜브 라이브 조회 기능은 수리중입니다.\n"
        f"{GAMEPLAZA_YOUTUBE_URL}"
    )


def is_developer_dm(message: discord.Message) -> bool:
    return (
        message.guild is None
        and message.author.id == BOT_DEVELOPER_ID
    )


def parse_uid(text: str) -> int | None:
    text = text.strip()

    mention_match = re.fullmatch(r"<@!?(\d+)>", text)
    if mention_match:
        return int(mention_match.group(1))

    if text.isdigit():
        return int(text)

    return None


def get_treats(uid: int) -> list[str]:
    return state.setdefault("notreat_rules", {}).setdefault(str(uid), [])


def format_treat_list(uid: int) -> str:
    treats = get_treats(uid)

    if not treats:
        return "등록된 treat이 없습니다."

    return "\n".join(f"{idx + 1}. `{treat}`" for idx, treat in enumerate(treats))


async def send_help(message: discord.Message):
    embed = discord.Embed(
        title="밀크봇 개발자 명령어",
        description="아래 명령어는 봇 개발자 DM에서만 동작합니다.",
    )

    embed.add_field(
        name="!m help",
        value="명령어 도움말을 출력합니다.",
        inline=False,
    )

    embed.add_field(
        name="!m sonic {uid}",
        value=(
            "해당 유저의 treat 목록을 열고, "
            "`treat 추가`, `treat 삭제`, `명령어 종료` 중 하나를 입력받습니다."
        ),
        inline=False,
    )

    await message.reply(
        embed=embed,
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none(),
    )


async def prompt_sonic_action(message: discord.Message, uid: int):
    embed = discord.Embed(
        title="sonic 설정",
        description=f"대상 UID: `{uid}`",
    )

    embed.add_field(
        name="현재 treat 목록",
        value=format_treat_list(uid),
        inline=False,
    )

    embed.add_field(
        name="유저에 대한 액션을 정해주세요",
        value=(
            "`treat 추가`\n"
            "`treat 삭제`\n"
            "`명령어 종료`"
        ),
        inline=False,
    )

    await message.reply(
        embed=embed,
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none(),
    )


async def wait_for_developer_reply(channel: discord.abc.Messageable) -> discord.Message:
    def check(msg: discord.Message) -> bool:
        return (
            msg.guild is None
            and msg.author.id == BOT_DEVELOPER_ID
            and msg.channel.id == channel.id
        )

    return await client.wait_for("message", check=check)


async def run_sonic_session(message: discord.Message, uid: int):
    channel_id = message.channel.id

    if channel_id in ACTIVE_SONIC_SESSIONS:
        await message.reply(
            "이미 이 DM 채널에서 sonic 설정이 진행 중입니다. 먼저 `명령어 종료`를 입력해주세요.",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return

    ACTIVE_SONIC_SESSIONS.add(channel_id)

    try:
        get_treats(uid)
        save_state()

        await prompt_sonic_action(message, uid)

        while True:
            action_message = await wait_for_developer_reply(message.channel)
            action = action_message.content.strip()

            if action == "명령어 종료":
                await action_message.reply(
                    "sonic 설정을 종료했습니다.",
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                break

            if action == "treat 추가":
                await action_message.reply(
                    "추가할 treat 텍스트를 입력해주세요.",
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )

                treat_message = await wait_for_developer_reply(message.channel)
                treat = treat_message.content.strip()

                if not treat:
                    await treat_message.reply(
                        "빈 treat은 추가할 수 없습니다.",
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    await prompt_sonic_action(treat_message, uid)
                    continue

                treats = get_treats(uid)

                if treat in treats:
                    await treat_message.reply(
                        f"`{treat}`은 이미 등록되어 있습니다.",
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                else:
                    treats.append(treat)
                    save_state()

                    await treat_message.reply(
                        f"`{treat}`을 추가했습니다.",
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )

                await prompt_sonic_action(treat_message, uid)
                continue

            if action == "treat 삭제":
                treats = get_treats(uid)

                if not treats:
                    await action_message.reply(
                        "삭제할 treat이 없습니다.",
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    await prompt_sonic_action(action_message, uid)
                    continue

                await action_message.reply(
                    "삭제할 treat 텍스트를 입력해주세요.\n\n"
                    f"{format_treat_list(uid)}",
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )

                delete_message = await wait_for_developer_reply(message.channel)
                treat_to_delete = delete_message.content.strip()

                treats = get_treats(uid)

                if treat_to_delete not in treats:
                    await delete_message.reply(
                        f"`{treat_to_delete}`은 등록되어 있지 않습니다.",
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                else:
                    treats.remove(treat_to_delete)
                    save_state()

                    await delete_message.reply(
                        f"`{treat_to_delete}`을 삭제했습니다.",
                        mention_author=False,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )

                await prompt_sonic_action(delete_message, uid)
                continue

            await action_message.reply(
                "알 수 없는 액션입니다.\n"
                "`treat 추가`, `treat 삭제`, `명령어 종료` 중 하나를 입력해주세요.",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    finally:
        ACTIVE_SONIC_SESSIONS.discard(channel_id)


async def handle_developer_dm_command(message: discord.Message):
    if not is_developer_dm(message):
        return False

    content = message.content.strip()

    if content == "!m help":
        await send_help(message)
        return True

    if content.startswith("!m sonic "):
        raw_uid = content[len("!m sonic "):].strip()
        uid = parse_uid(raw_uid)

        if uid is None:
            await message.reply(
                "UID 형식이 올바르지 않습니다. 예: `!m sonic 123456789012345678`",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return True

        await run_sonic_session(message, uid)
        return True

    if content.startswith("!m"):
        await message.reply(
            "알 수 없는 명령어입니다. `!m help`로 도움말을 확인하세요.",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True

    return False


async def handle_notreat(message: discord.Message):
    if message.guild is None:
        return

    rules = state.get("notreat_rules", {})
    author_uid = str(message.author.id)

    if author_uid not in rules:
        return

    text = message.content.strip()
    treats = rules.get(author_uid, [])

    for treat in treats:
        if text == treat or text == f"{treat}?":
            await message.reply(
                f"no {treat}",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    handled = await handle_developer_dm_command(message)

    if handled:
        return

    await handle_notreat(message)


client.run(TOKEN)