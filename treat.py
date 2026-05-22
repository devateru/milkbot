from collections import Counter

import discord
from discord import app_commands

from messages import get_message
from storage import (
    add_guild_treat,
    get_allowed_guild_ids,
    get_guild_treat_rules,
    remove_guild_treat,
)


def is_treat_enabled_guild(guild_id: int) -> bool:
    return str(guild_id) in get_allowed_guild_ids()


def _format_flexible_label(flexible: bool) -> str:
    message_key = "treat.flexible_on" if flexible else "treat.flexible_off"
    return get_message(message_key)


def format_guild_treat_list(guild_id: int) -> str:
    rules = get_guild_treat_rules(guild_id)

    if not rules:
        return get_message("treat.empty_list")

    return "\n".join(
        f"{idx + 1}. `{rule['treat']}` ({_format_flexible_label(bool(rule['flexible']))})"
        for idx, rule in enumerate(rules)
    )


async def _enabled_guild_id(interaction: discord.Interaction) -> int | None:
    if interaction.guild is None:
        await interaction.response.send_message(
            get_message("treat.guild_only"),
            ephemeral=True,
        )
        return None

    if not is_treat_enabled_guild(interaction.guild.id):
        await interaction.response.send_message(
            get_message("treat.no_access"),
            ephemeral=True,
        )
        return None

    return interaction.guild.id


treat_group = app_commands.Group(
    name="treat",
    description=get_message("slash.treat_description"),
)


@treat_group.command(name="add", description=get_message("slash.treat_add_description"))
@app_commands.describe(
    treat=get_message("treat.option_treat_add"),
    flexible=get_message("treat.option_flexible"),
)
async def treat_add_command(
    interaction: discord.Interaction,
    treat: str,
    flexible: bool = False,
) -> None:
    guild_id = await _enabled_guild_id(interaction)

    if guild_id is None:
        return

    treat = treat.strip()

    if not treat:
        await interaction.response.send_message(
            get_message("treat.empty_rejected"),
            ephemeral=True,
        )
        return

    if add_guild_treat(guild_id, treat, flexible):
        response = get_message(
            "treat.added",
            treat=treat,
            flexible=_format_flexible_label(flexible),
        )
    else:
        response = get_message("treat.already_exists", treat=treat)

    await interaction.response.send_message(response, ephemeral=True)


@treat_group.command(name="delete", description=get_message("slash.treat_delete_description"))
@app_commands.describe(treat=get_message("treat.option_treat_delete"))
async def treat_delete_command(
    interaction: discord.Interaction,
    treat: str,
) -> None:
    guild_id = await _enabled_guild_id(interaction)

    if guild_id is None:
        return

    treat = treat.strip()

    if not treat:
        await interaction.response.send_message(
            get_message("treat.empty_rejected"),
            ephemeral=True,
        )
        return

    if remove_guild_treat(guild_id, treat):
        response = get_message("treat.deleted", treat=treat)
    else:
        response = get_message("treat.not_registered", treat=treat)

    await interaction.response.send_message(response, ephemeral=True)


@treat_group.command(name="list", description=get_message("slash.treat_list_description"))
async def treat_list_command(interaction: discord.Interaction) -> None:
    guild_id = await _enabled_guild_id(interaction)

    if guild_id is None:
        return

    await interaction.response.send_message(
        get_message("treat.list", treats=format_guild_treat_list(guild_id)),
        ephemeral=True,
    )


def register_treat_command(tree: app_commands.CommandTree) -> None:
    tree.add_command(treat_group)


def _contains_treat_characters(message_text: str, treat: str) -> bool:
    message_counts = Counter(char for char in message_text if not char.isspace())
    treat_counts = Counter(char for char in treat if not char.isspace())

    return bool(treat_counts) and all(
        message_counts[char] >= count
        for char, count in treat_counts.items()
    )


def _message_matches_treat(message_text: str, treat: str, flexible: bool) -> bool:
    if flexible:
        return _contains_treat_characters(message_text, treat)

    return message_text == treat or message_text == f"{treat}?"


async def handle_notreat(message: discord.Message) -> None:
    if message.guild is None or not is_treat_enabled_guild(message.guild.id):
        return

    text = message.content.strip()

    for rule in get_guild_treat_rules(message.guild.id):
        treat = str(rule.get("treat", "")).strip()
        flexible = bool(rule.get("flexible", False))

        if treat and _message_matches_treat(text, treat, flexible):
            await message.reply(
                get_message("treat.notreat_reply", treat=treat),
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
