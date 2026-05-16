import json
from pathlib import Path
from typing import Any

import discord


MESSAGES_FILE = Path("messages.json")


def load_messages() -> dict[str, Any]:
    with MESSAGES_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


MESSAGES = load_messages()


def get_message(key: str, **kwargs: object) -> str:
    value: object = MESSAGES

    for part in key.split("."):
        if not isinstance(value, dict):
            raise KeyError(key)
        value = value[part]

    if not isinstance(value, str):
        raise TypeError(f"{key} is not a string message")

    return value.format(**kwargs)


def get_command_lines(*keys: str) -> list[str]:
    return [get_message(f"commands.{key}") for key in keys]


def build_embed(key: str, **kwargs: object) -> discord.Embed:
    data: object = MESSAGES

    for part in f"embeds.{key}".split("."):
        if not isinstance(data, dict):
            raise KeyError(key)
        data = data[part]

    if not isinstance(data, dict):
        raise TypeError(f"{key} is not an embed message")

    embed = discord.Embed(
        title=str(data.get("title", "")).format(**kwargs),
        description=str(data.get("description", "")).format(**kwargs),
    )

    fields = data.get("fields", [])
    if isinstance(fields, list):
        for field in fields:
            if not isinstance(field, dict):
                continue

            embed.add_field(
                name=str(field.get("name", "")).format(**kwargs),
                value=str(field.get("value", "")).format(**kwargs),
                inline=bool(field.get("inline", False)),
            )

    return embed
