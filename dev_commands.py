import re

import discord

from messages import build_embed, get_message
from storage import add_allowed_guild, get_allowed_guild_ids, remove_allowed_guild, remove_treat
from storage import add_treat, get_treats, save_state
from treat import format_treat_list


ACTIVE_SONIC_SESSIONS = set()


def parse_uid(text: str) -> int | None:
    text = text.strip()

    mention_match = re.fullmatch(r"<@!?(\d+)>", text)
    if mention_match:
        return int(mention_match.group(1))

    if text.isdigit():
        return int(text)

    return None


def parse_guild_id(text: str) -> int | None:
    text = text.strip()

    if text.isdigit():
        return int(text)

    return None


def is_developer_dm(message: discord.Message, developer_id: int) -> bool:
    return message.guild is None and message.author.id == developer_id


async def delete_message_quietly(message: discord.Message) -> None:
    try:
        await message.delete()
    except discord.DiscordException:
        pass


async def wait_for_developer_reply(
    client: discord.Client,
    channel: discord.abc.Messageable,
    developer_id: int,
) -> discord.Message:
    def check(msg: discord.Message) -> bool:
        return (
            msg.guild is None
            and msg.author.id == developer_id
            and msg.channel.id == channel.id
        )

    return await client.wait_for("message", check=check)


def private_response_kwargs(interaction: discord.Interaction) -> dict:
    return {"ephemeral": interaction.guild is not None}


def build_developer_help_embed() -> discord.Embed:
    command_values = {
        "dev_help": get_message("commands.dev_help"),
        "dev_sonic": get_message("commands.dev_sonic"),
        "dev_guild_list": get_message("commands.dev_guild_list"),
        "dev_guild_add": get_message("commands.dev_guild_add"),
        "dev_guild_remove": get_message("commands.dev_guild_remove"),
    }
    return build_embed("developer_help", **command_values)


def build_sonic_intro_embed() -> discord.Embed:
    return build_embed("sonic_intro")


def build_sonic_menu_embed(uid: int) -> discord.Embed:
    return build_embed("sonic_menu", uid=uid, treats=format_treat_list(uid))


class SonicConfigView(discord.ui.View):
    def __init__(self, client: discord.Client, uid: int, channel_id: int, developer_id: int):
        super().__init__(timeout=300)
        self.client = client
        self.uid = uid
        self.channel_id = channel_id
        self.developer_id = developer_id

        add_button = discord.ui.Button(
            label=get_message("buttons.sonic_add"),
            style=discord.ButtonStyle.primary,
        )
        add_button.callback = self.add_treat_callback
        self.add_item(add_button)

        delete_button = discord.ui.Button(
            label=get_message("buttons.sonic_delete"),
            style=discord.ButtonStyle.danger,
        )
        delete_button.callback = self.delete_treat_callback
        self.add_item(delete_button)

        close_button = discord.ui.Button(
            label=get_message("buttons.sonic_close"),
            style=discord.ButtonStyle.secondary,
        )
        close_button.callback = self.close_callback
        self.add_item(close_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.developer_id:
            return True

        await interaction.response.send_message(
            get_message("developer.sonic_not_developer"),
            **private_response_kwargs(interaction),
        )
        return False

    async def on_timeout(self) -> None:
        ACTIVE_SONIC_SESSIONS.discard(self.channel_id)

        for item in self.children:
            item.disabled = True

    async def update_menu(self, interaction: discord.Interaction) -> None:
        await interaction.message.edit(
            embed=build_sonic_menu_embed(self.uid),
            view=self,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def prompt_for_treat(self, interaction: discord.Interaction, prompt: str) -> str | None:
        await interaction.response.defer()

        prompt_message = await interaction.channel.send(prompt)
        reply_message = await wait_for_developer_reply(
            self.client,
            interaction.channel,
            self.developer_id,
        )
        treat = reply_message.content.strip()

        await delete_message_quietly(prompt_message)
        await delete_message_quietly(reply_message)

        return treat or None

    async def add_treat_callback(self, interaction: discord.Interaction) -> None:
        treat = await self.prompt_for_treat(
            interaction,
            get_message("developer.sonic_add_prompt"),
        )

        if treat is None:
            await interaction.followup.send(
                get_message("developer.sonic_add_empty"),
                **private_response_kwargs(interaction),
            )
            return

        if add_treat(self.uid, treat):
            response = get_message("developer.sonic_added", treat=treat)
        else:
            response = get_message("developer.sonic_already_exists", treat=treat)

        await interaction.followup.send(response, **private_response_kwargs(interaction))
        await self.update_menu(interaction)

    async def delete_treat_callback(self, interaction: discord.Interaction) -> None:
        if not get_treats(self.uid):
            await interaction.response.send_message(
                get_message("developer.sonic_delete_no_items"),
                **private_response_kwargs(interaction),
            )
            return

        treat = await self.prompt_for_treat(
            interaction,
            get_message("developer.sonic_delete_prompt"),
        )

        if treat is None:
            await interaction.followup.send(
                get_message("developer.sonic_delete_empty"),
                **private_response_kwargs(interaction),
            )
            return

        if remove_treat(self.uid, treat):
            response = get_message("developer.sonic_deleted", treat=treat)
        else:
            response = get_message("developer.sonic_not_registered", treat=treat)

        await interaction.followup.send(response, **private_response_kwargs(interaction))
        await self.update_menu(interaction)

    async def close_callback(self, interaction: discord.Interaction) -> None:
        ACTIVE_SONIC_SESSIONS.discard(self.channel_id)

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            embed=build_sonic_menu_embed(self.uid),
            view=self,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.stop()


async def send_help(message: discord.Message) -> None:
    await message.reply(
        embed=build_developer_help_embed(),
        mention_author=False,
        allowed_mentions=discord.AllowedMentions.none(),
    )


async def run_sonic_session(
    message: discord.Message,
    client: discord.Client,
    developer_id: int,
    initial_uid: int | None = None,
) -> None:
    channel_id = message.channel.id

    if channel_id in ACTIVE_SONIC_SESSIONS:
        await message.reply(
            get_message("developer.sonic_already_active"),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return

    ACTIVE_SONIC_SESSIONS.add(channel_id)

    try:
        menu_message = await message.reply(
            embed=build_sonic_intro_embed(),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        if initial_uid is None:
            target_message = await wait_for_developer_reply(client, message.channel, developer_id)
            initial_uid = parse_uid(target_message.content)
            await delete_message_quietly(target_message)

        if initial_uid is None:
            await menu_message.edit(
                content=get_message("developer.sonic_invalid_uid"),
                embed=None,
                view=None,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        get_treats(initial_uid)
        save_state()

        view = SonicConfigView(client, initial_uid, channel_id, developer_id)
        await menu_message.edit(
            embed=build_sonic_menu_embed(initial_uid),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await view.wait()

    finally:
        ACTIVE_SONIC_SESSIONS.discard(channel_id)


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
    client: discord.Client,
    developer_id: int,
) -> bool:
    if not is_developer_dm(message, developer_id):
        return False

    content = message.content.strip()

    if content in ("!m", "!m help"):
        await send_help(message)
        return True

    if content == "!m sonic" or content.startswith("!m sonic "):
        raw_uid = content[len("!m sonic"):].strip()
        uid = parse_uid(raw_uid) if raw_uid else None
        await run_sonic_session(message, client, developer_id, uid)
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
