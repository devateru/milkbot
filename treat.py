import random

import discord

from messages import get_command_lines, get_message
from storage import add_treat, get_allowed_guild_ids, get_treats

TREAT_YES_RATE = 0.03


def format_treat_list(uid: int) -> str:
    treats = get_treats(uid)

    if not treats:
        return get_message("treat.empty_list")

    return "\n".join(f"{idx + 1}. `{treat}`" for idx, treat in enumerate(treats))


async def is_member_of_allowed_guild(client: discord.Client, user_id: int) -> bool:
    for guild_id in get_allowed_guild_ids():
        guild = client.get_guild(int(guild_id))

        if guild is None:
            continue

        if guild.get_member(user_id) is not None:
            return True

        try:
            await guild.fetch_member(user_id)
            return True
        except discord.NotFound:
            continue
        except discord.Forbidden:
            continue
        except discord.HTTPException:
            continue

    return False


async def get_user_text_command_lines(client: discord.Client, user_id: int) -> list[str]:
    if not await is_member_of_allowed_guild(client, user_id):
        return []

    return get_command_lines("user_treat_list", "user_treat_add", "user_treat_help")


async def send_user_command_menu(message: discord.Message, client: discord.Client) -> None:
    command_lines = await get_user_text_command_lines(client, message.author.id)

    if not command_lines:
        await message.reply(
            get_message("treat.no_access"),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return

    await message.reply(
        get_message("treat.available_commands", commands="\n".join(command_lines)),
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none(),
    )


async def handle_user_dm_command(message: discord.Message, client: discord.Client) -> bool:
    content = message.content.strip()

    if content != "!m" and not content.startswith("!m "):
        return False

    if content == "!m":
        await send_user_command_menu(message, client)
        return True

    if content != "!m treat" and not content.startswith("!m treat "):
        await message.reply(
            get_message("treat.unknown_user_command"),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True

    if not await is_member_of_allowed_guild(client, message.author.id):
        await message.reply(
            get_message("treat.no_access"),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True

    raw_treat = content[len("!m treat"):].strip()

    if not raw_treat:
        await message.reply(
            get_message("treat.list", treats=format_treat_list(message.author.id)),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True

    if raw_treat == "help":
        await message.reply(
            get_message("treat.help_url"),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True

    if add_treat(message.author.id, raw_treat):
        response = get_message("treat.added", treat=raw_treat)
    else:
        response = get_message("treat.already_exists", treat=raw_treat)

    await message.reply(
        response,
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none(),
    )
    return True


async def handle_notreat(message: discord.Message) -> None:
    if message.guild is None:
        return

    text = message.content.strip()

    for treat in get_treats(message.author.id):
        if text == treat or text == f"{treat}?":
            message_key = (
                "treat.yes_reply"
                if random.random() < TREAT_YES_RATE
                else "treat.notreat_reply"
            )
            await message.reply(
                get_message(message_key, treat=treat),
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
