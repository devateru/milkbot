import discord

from messages import build_embed, get_message
from storage import add_allowed_guild, get_allowed_guild_ids, remove_allowed_guild


def parse_guild_id(text: str) -> int | None:
    text = text.strip()

    if text.isdigit():
        return int(text)

    return None


def is_developer_dm(message: discord.Message, developer_id: int) -> bool:
    return message.guild is None and message.author.id == developer_id


def build_developer_help_embed() -> discord.Embed:
    command_values = {
        "dev_help": get_message("commands.dev_help"),
        "dev_guild_list": get_message("commands.dev_guild_list"),
        "dev_guild_add": get_message("commands.dev_guild_add"),
        "dev_guild_remove": get_message("commands.dev_guild_remove"),
    }
    return build_embed("developer_help", **command_values)


async def send_help(message: discord.Message) -> None:
    await message.reply(
        embed=build_developer_help_embed(),
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none(),
    )


async def handle_guild_allow_command(message: discord.Message, content: str) -> bool:
    if content == "!m guild list":
        guild_ids = get_allowed_guild_ids()

        if not guild_ids:
            response = get_message("developer.allowed_guild_list_empty")
        else:
            response = get_message(
                "developer.allowed_guild_list",
                guilds="\n".join(f"- `{guild_id}`" for guild_id in guild_ids),
            )

        await message.reply(
            response,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True

    for prefix, action in (
        ("!m guild add ", add_allowed_guild),
        ("!m guild remove ", remove_allowed_guild),
    ):
        if not content.startswith(prefix):
            continue

        guild_id = parse_guild_id(content[len(prefix):])

        if guild_id is None:
            response = get_message("developer.allowed_guild_invalid")
        elif action(guild_id):
            message_key = (
                "developer.allowed_guild_added"
                if action is add_allowed_guild
                else "developer.allowed_guild_removed"
            )
            response = get_message(message_key, guild_id=guild_id)
        else:
            message_key = (
                "developer.allowed_guild_exists"
                if action is add_allowed_guild
                else "developer.allowed_guild_missing"
            )
            response = get_message(message_key, guild_id=guild_id)

        await message.reply(
            response,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True

    return False


async def handle_developer_dm_command(
    message: discord.Message,
    _client: discord.Client,
    developer_id: int,
) -> bool:
    if not is_developer_dm(message, developer_id):
        return False

    content = message.content.strip()

    if content in ("!m", "!m help"):
        await send_help(message)
        return True

    if await handle_guild_allow_command(message, content):
        return True

    if content.startswith("!m"):
        await message.reply(
            get_message("developer.unknown_command"),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True

    return False
