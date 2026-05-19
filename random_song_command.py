from __future__ import annotations

import discord
from discord import app_commands

from messages import get_message
from random_song import GENRE_CHOICES, RandomSongError, choose_random_song


DIFFICULTY_SUGGESTIONS = [
    ("BASIC", "BASIC"),
    ("ADVANCED", "ADVANCED"),
    ("EXPERT", "EXPERT"),
    ("MASTER", "MASTER"),
    ("RE:MASTER / ULTIMA", "RE:MASTER/ULTIMA"),
    ("MASTER + RE:MASTER / ULTIMA", "MASTER RE:MASTER/ULTIMA"),
]

TYPE_SUGGESTIONS = [
    ("STANDARD", "STANDARD"),
    ("DELUXE", "DELUXE"),
    ("UTAGE / WORLD'S END", "UTAGE/WORLD'S END"),
    ("STANDARD + DELUXE", "STANDARD DELUXE"),
    ("STANDARD + UTAGE / WORLD'S END", "STANDARD UTAGE/WORLD'S END"),
    ("DELUXE + UTAGE / WORLD'S END", "DELUXE UTAGE/WORLD'S END"),
    ("STANDARD + DELUXE + UTAGE / WORLD'S END", "STANDARD DELUXE UTAGE/WORLD'S END"),
]


def _matches_current_input(current: str, name: str, value: str) -> bool:
    current = current.casefold()
    return current in name.casefold() or current in value.casefold()


async def difficulty_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return [
        app_commands.Choice(name=name, value=value)
        for name, value in DIFFICULTY_SUGGESTIONS
        if _matches_current_input(current, name, value)
    ][:25]


async def chart_type_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return [
        app_commands.Choice(name=name, value=value)
        for name, value in TYPE_SUGGESTIONS
        if _matches_current_input(current, name, value)
    ][:25]


def register_random_song_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="랜덤선곡",
        description=get_message("slash.random_song_description"),
    )
    @app_commands.rename(
        game="게임",
        min_level="최소_보면상수",
        genre="장르",
        difficulty="난이도",
        chart_type="유형",
        partner_level="2p_난이도",
    )
    @app_commands.describe(
        game=get_message("random_song.option_game"),
        min_level=get_message("random_song.option_min_level"),
        genre=get_message("random_song.option_genre"),
        difficulty=get_message("random_song.option_difficulty"),
        chart_type=get_message("random_song.option_chart_type"),
        partner_level=get_message("random_song.option_partner_level"),
    )
    @app_commands.choices(
        game=[
            app_commands.Choice(name="maimai DX", value="maimai"),
            app_commands.Choice(name="CHUNITHM", value="chunithm"),
        ],
        genre=[
            app_commands.Choice(name=config["label"], value=genre_key)
            for genre_key, config in GENRE_CHOICES.items()
        ],
    )
    @app_commands.autocomplete(
        difficulty=difficulty_autocomplete,
        chart_type=chart_type_autocomplete,
    )
    async def random_song_command(
        interaction: discord.Interaction,
        game: app_commands.Choice[str] | None = None,
        min_level: float = 1.0,
        genre: app_commands.Choice[str] | None = None,
        difficulty: str | None = None,
        chart_type: str | None = None,
        partner_level: float | None = None,
    ):
        await interaction.response.defer(thinking=True)

        try:
            embeds = await choose_random_song(
                game=game.value if game else "maimai",
                min_level=min_level,
                genre=genre.value if genre else None,
                difficulty=difficulty,
                chart_type=chart_type,
                partner_level=partner_level,
            )
        except RandomSongError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            await interaction.followup.send(
                get_message("random_song.error_fetch_failed"),
                ephemeral=True,
            )
            return

        await interaction.followup.send(embeds=embeds)
