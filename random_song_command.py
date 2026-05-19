from __future__ import annotations

import discord
from discord import app_commands

from messages import get_message
from random_song import GENRE_CHOICES, RandomSongError, choose_random_song_response
from storage import (
    get_random_song_preset,
    remove_random_song_preset,
    set_random_song_preset,
)


DIFFICULTY_SUGGESTIONS = [
    ("BASIC", "BASIC"),
    ("ADVANCED", "ADVANCED"),
    ("EXPERT", "EXPERT"),
    ("MASTER", "MASTER"),
    ("RE:MASTER / ULTIMA", "RE:MASTER/ULTIMA"),
    ("MAS ~ RE:MAS / ULT", "MAS~RE:MAS/ULT"),
    ("EXP ~ RE:MAS / ULT", "EXP~RE:MAS/ULT"),
]

TYPE_SUGGESTIONS = [
    ("STANDARD", "STANDARD"),
    ("DELUXE (maimai only)", "DELUXE"),
    ("UTAGE / WORLD'S END", "UTAGE/WORLD'S END"),
]

GAME_CHOICES = [
    app_commands.Choice(name="maimai DX", value="maimai"),
    app_commands.Choice(name="CHUNITHM", value="chunithm"),
]

GENRE_APP_CHOICES = [
    app_commands.Choice(name=config["label"], value=genre_key)
    for genre_key, config in GENRE_CHOICES.items()
]

DIFFICULTY_CHOICES = [
    app_commands.Choice(name=name, value=value)
    for name, value in DIFFICULTY_SUGGESTIONS
]

TYPE_CHOICES = [
    app_commands.Choice(name=name, value=value)
    for name, value in TYPE_SUGGESTIONS
]


def _choice_name(choices: list[app_commands.Choice[str]], value: object) -> str:
    for choice in choices:
        if choice.value == value:
            return choice.name

    return str(value)


def _preset_summary(preset: dict[str, object], *, include_game: bool = True) -> str:
    parts: list[str] = []

    if include_game and "game" in preset:
        parts.append(f"게임={_choice_name(GAME_CHOICES, preset['game'])}")
    if "min_level" in preset:
        parts.append(f"최소 보면상수={preset['min_level']}")
    if "genre" in preset:
        parts.append(f"장르={_choice_name(GENRE_APP_CHOICES, preset['genre'])}")
    if "difficulty" in preset:
        parts.append(f"난이도={_choice_name(DIFFICULTY_CHOICES, preset['difficulty'])}")
    if "chart_type" in preset:
        parts.append(f"유형={_choice_name(TYPE_CHOICES, preset['chart_type'])}")
    if "partner_level" in preset:
        parts.append(f"2P 난이도={preset['partner_level']}")

    return ", ".join(parts)


def _recommendation_content(game: object, applied_preset: dict[str, object]) -> str:
    lines = [
        get_message(
            "random_song.recommendation_text",
            game=_choice_name(GAME_CHOICES, game),
        )
    ]
    preset_summary = _preset_summary(applied_preset, include_game=False)

    if preset_summary:
        lines.append(
            get_message(
                "random_song.preset_applied",
                preset=preset_summary,
            )
        )

    return "\n".join(lines)


def _random_song_options(
    game: app_commands.Choice[str] | None,
    min_level: float | None,
    genre: app_commands.Choice[str] | None,
    difficulty: app_commands.Choice[str] | None,
    chart_type: app_commands.Choice[str] | None,
    partner_level: float | None,
) -> dict[str, object]:
    return {
        "game": game.value if game else None,
        "min_level": min_level,
        "genre": genre.value if genre else None,
        "difficulty": difficulty.value if difficulty else None,
        "chart_type": chart_type.value if chart_type else None,
        "partner_level": partner_level,
    }


def _compact_options(options: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in options.items()
        if value is not None
    }


def _merge_with_preset(
    uid: int,
    options: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    preset = get_random_song_preset(uid)
    applied_preset = {
        key: value
        for key, value in preset.items()
        if options.get(key) is None
    }
    merged = {
        "game": options.get("game") or preset.get("game") or "maimai",
        "min_level": options.get("min_level") if options.get("min_level") is not None else preset.get("min_level", 1.0),
        "genre": options.get("genre") if options.get("genre") is not None else preset.get("genre"),
        "difficulty": options.get("difficulty") if options.get("difficulty") is not None else preset.get("difficulty"),
        "chart_type": options.get("chart_type") if options.get("chart_type") is not None else preset.get("chart_type"),
        "partner_level": options.get("partner_level") if options.get("partner_level") is not None else preset.get("partner_level"),
    }

    return merged, applied_preset


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
        game=GAME_CHOICES,
        genre=GENRE_APP_CHOICES,
        difficulty=DIFFICULTY_CHOICES,
        chart_type=TYPE_CHOICES,
    )
    async def random_song_command(
        interaction: discord.Interaction,
        game: app_commands.Choice[str] | None = None,
        min_level: float | None = None,
        genre: app_commands.Choice[str] | None = None,
        difficulty: app_commands.Choice[str] | None = None,
        chart_type: app_commands.Choice[str] | None = None,
        partner_level: float | None = None,
    ):
        await interaction.response.defer(thinking=True)
        options = _random_song_options(
            game,
            min_level,
            genre,
            difficulty,
            chart_type,
            partner_level,
        )
        merged_options, applied_preset = _merge_with_preset(interaction.user.id, options)

        try:
            response = await choose_random_song_response(
                game=str(merged_options["game"]),
                min_level=float(merged_options["min_level"]),
                genre=str(merged_options["genre"]) if merged_options.get("genre") is not None else None,
                difficulty=str(merged_options["difficulty"]) if merged_options.get("difficulty") is not None else None,
                chart_type=str(merged_options["chart_type"]) if merged_options.get("chart_type") is not None else None,
                partner_level=float(merged_options["partner_level"]) if merged_options.get("partner_level") is not None else None,
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

        await interaction.followup.send(
            content=_recommendation_content(merged_options["game"], applied_preset),
            embeds=response.embeds,
            files=response.files,
        )

    @tree.command(
        name="랜덤선곡-프리셋",
        description=get_message("slash.random_song_preset_description"),
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
        game=GAME_CHOICES,
        genre=GENRE_APP_CHOICES,
        difficulty=DIFFICULTY_CHOICES,
        chart_type=TYPE_CHOICES,
    )
    async def random_song_preset_command(
        interaction: discord.Interaction,
        game: app_commands.Choice[str] | None = None,
        min_level: float | None = None,
        genre: app_commands.Choice[str] | None = None,
        difficulty: app_commands.Choice[str] | None = None,
        chart_type: app_commands.Choice[str] | None = None,
        partner_level: float | None = None,
    ):
        options = _compact_options(
            _random_song_options(
                game,
                min_level,
                genre,
                difficulty,
                chart_type,
                partner_level,
            )
        )

        if not options:
            removed = remove_random_song_preset(interaction.user.id)
            message_key = "random_song.preset_cleared" if removed else "random_song.preset_empty"
            await interaction.response.send_message(
                get_message(message_key),
                ephemeral=True,
            )
            return

        set_random_song_preset(interaction.user.id, options)
        await interaction.response.send_message(
            get_message("random_song.preset_saved", preset=_preset_summary(options)),
            ephemeral=True,
        )
