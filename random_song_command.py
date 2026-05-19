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

MAIMAI_VERSION_SUGGESTIONS = [
    ("신곡 (PRiSM PLUS + CiRCLE)", "new"),
    ("구곡 (~PRiSM)", "old"),
    ("maimai", "maimai"),
    ("maimai PLUS", "maimai PLUS"),
    ("GreeN", "GreeN"),
    ("GreeN PLUS", "GreeN PLUS"),
    ("ORANGE", "ORANGE"),
    ("ORANGE PLUS", "ORANGE PLUS"),
    ("PiNK", "PiNK"),
    ("PiNK PLUS", "PiNK PLUS"),
    ("MURASAKi", "MURASAKi"),
    ("MURASAKi PLUS", "MURASAKi PLUS"),
    ("MiLK", "MiLK"),
    ("MiLK PLUS", "MiLK PLUS"),
    ("FiNALE", "FiNALE"),
    ("maimaiでらっくす", "maimaiでらっくす"),
    ("maimaiでらっくす PLUS", "maimaiでらっくす PLUS"),
    ("Splash", "Splash"),
    ("Splash PLUS", "Splash PLUS"),
    ("UNiVERSE", "UNiVERSE"),
    ("UNiVERSE PLUS", "UNiVERSE PLUS"),
    ("FESTiVAL", "FESTiVAL"),
    ("FESTiVAL PLUS", "FESTiVAL PLUS"),
    ("BUDDiES", "BUDDiES"),
    ("BUDDiES PLUS", "BUDDiES PLUS"),
    ("PRiSM", "PRiSM"),
    ("PRiSM PLUS", "PRiSM PLUS"),
    ("CiRCLE", "CiRCLE"),
    ("CiRCLE PLUS", "CiRCLE PLUS"),
]

CHUNITHM_VERSION_SUGGESTIONS = [
    ("신곡 (X-VERSE-X)", "new"),
    ("구곡 (X-VERSE-X 제외)", "old"),
    ("CHUNITHM", "CHUNITHM"),
    ("CHUNITHM PLUS", "CHUNITHM PLUS"),
    ("AIR", "AIR"),
    ("AIR PLUS", "AIR PLUS"),
    ("STAR", "STAR"),
    ("STAR PLUS", "STAR PLUS"),
    ("AMAZON", "AMAZON"),
    ("AMAZON PLUS", "AMAZON PLUS"),
    ("CRYSTAL", "CRYSTAL"),
    ("CRYSTAL PLUS", "CRYSTAL PLUS"),
    ("PARADISE", "PARADISE"),
    ("PARADISE LOST", "PARADISE LOST"),
    ("CHUNITHM NEW", "CHUNITHM NEW"),
    ("CHUNITHM NEW PLUS", "CHUNITHM NEW PLUS"),
    ("SUN", "SUN"),
    ("SUN PLUS", "SUN PLUS"),
    ("LUMINOUS", "LUMINOUS"),
    ("LUMINOUS PLUS", "LUMINOUS PLUS"),
    ("VERSE", "VERSE"),
    ("X-VERSE", "X-VERSE"),
    ("X-VERSE-X", "X-VERSE-X"),
]

MAIMAI_VERSION_CHOICES = [
    app_commands.Choice(name=name, value=value)
    for name, value in MAIMAI_VERSION_SUGGESTIONS
]
CHUNITHM_VERSION_CHOICES = [
    app_commands.Choice(name=name, value=value)
    for name, value in CHUNITHM_VERSION_SUGGESTIONS
]


def _matches_current_input(current: str, name: str, value: str) -> bool:
    current = current.casefold()
    return current in name.casefold() or current in value.casefold()


async def maimai_version_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return [
        choice
        for choice in MAIMAI_VERSION_CHOICES
        if _matches_current_input(current, choice.name, choice.value)
    ][:25]


async def chunithm_version_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    return [
        choice
        for choice in CHUNITHM_VERSION_CHOICES
        if _matches_current_input(current, choice.name, choice.value)
    ][:25]


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
    if "maimai_version" in preset:
        parts.append(f"마이버전={_choice_name(MAIMAI_VERSION_CHOICES, preset['maimai_version'])}")
    if "chunithm_version" in preset:
        parts.append(f"츄니버전={_choice_name(CHUNITHM_VERSION_CHOICES, preset['chunithm_version'])}")
    if "level_fixed" in preset:
        parts.append(f"난이도 고정={preset['level_fixed']}")
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
    maimai_version: str | None,
    chunithm_version: str | None,
    level_fixed: bool | None,
    partner_level: float | None,
) -> dict[str, object]:
    return {
        "game": game.value if game else None,
        "min_level": min_level,
        "genre": genre.value if genre else None,
        "difficulty": difficulty.value if difficulty else None,
        "chart_type": chart_type.value if chart_type else None,
        "maimai_version": maimai_version,
        "chunithm_version": chunithm_version,
        "level_fixed": level_fixed,
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
        "maimai_version": options.get("maimai_version") if options.get("maimai_version") is not None else preset.get("maimai_version"),
        "chunithm_version": options.get("chunithm_version") if options.get("chunithm_version") is not None else preset.get("chunithm_version"),
        "level_fixed": options.get("level_fixed") if options.get("level_fixed") is not None else preset.get("level_fixed", False),
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
        maimai_version="마이버전",
        chunithm_version="츄니버전",
        level_fixed="난이도_고정",
        partner_level="2p_난이도",
    )
    @app_commands.describe(
        game=get_message("random_song.option_game"),
        min_level=get_message("random_song.option_min_level"),
        genre=get_message("random_song.option_genre"),
        difficulty=get_message("random_song.option_difficulty"),
        chart_type=get_message("random_song.option_chart_type"),
        maimai_version=get_message("random_song.option_maimai_version"),
        chunithm_version=get_message("random_song.option_chunithm_version"),
        level_fixed=get_message("random_song.option_level_fixed"),
        partner_level=get_message("random_song.option_partner_level"),
    )
    @app_commands.choices(
        game=GAME_CHOICES,
        genre=GENRE_APP_CHOICES,
        difficulty=DIFFICULTY_CHOICES,
        chart_type=TYPE_CHOICES,
    )
    @app_commands.autocomplete(
        maimai_version=maimai_version_autocomplete,
        chunithm_version=chunithm_version_autocomplete,
    )
    async def random_song_command(
        interaction: discord.Interaction,
        game: app_commands.Choice[str] | None = None,
        min_level: float | None = None,
        genre: app_commands.Choice[str] | None = None,
        difficulty: app_commands.Choice[str] | None = None,
        chart_type: app_commands.Choice[str] | None = None,
        maimai_version: str | None = None,
        chunithm_version: str | None = None,
        level_fixed: bool | None = None,
        partner_level: float | None = None,
    ):
        await interaction.response.defer(thinking=True)
        options = _random_song_options(
            game,
            min_level,
            genre,
            difficulty,
            chart_type,
            maimai_version,
            chunithm_version,
            level_fixed,
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
                maimai_version=str(merged_options["maimai_version"]) if merged_options.get("maimai_version") is not None else None,
                chunithm_version=str(merged_options["chunithm_version"]) if merged_options.get("chunithm_version") is not None else None,
                level_fixed=bool(merged_options["level_fixed"]),
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
        maimai_version="마이버전",
        chunithm_version="츄니버전",
        level_fixed="난이도_고정",
        partner_level="2p_난이도",
    )
    @app_commands.describe(
        game=get_message("random_song.option_game"),
        min_level=get_message("random_song.option_min_level"),
        genre=get_message("random_song.option_genre"),
        difficulty=get_message("random_song.option_difficulty"),
        chart_type=get_message("random_song.option_chart_type"),
        maimai_version=get_message("random_song.option_maimai_version"),
        chunithm_version=get_message("random_song.option_chunithm_version"),
        level_fixed=get_message("random_song.option_level_fixed"),
        partner_level=get_message("random_song.option_partner_level"),
    )
    @app_commands.choices(
        game=GAME_CHOICES,
        genre=GENRE_APP_CHOICES,
        difficulty=DIFFICULTY_CHOICES,
        chart_type=TYPE_CHOICES,
    )
    @app_commands.autocomplete(
        maimai_version=maimai_version_autocomplete,
        chunithm_version=chunithm_version_autocomplete,
    )
    async def random_song_preset_command(
        interaction: discord.Interaction,
        game: app_commands.Choice[str] | None = None,
        min_level: float | None = None,
        genre: app_commands.Choice[str] | None = None,
        difficulty: app_commands.Choice[str] | None = None,
        chart_type: app_commands.Choice[str] | None = None,
        maimai_version: str | None = None,
        chunithm_version: str | None = None,
        level_fixed: bool | None = None,
        partner_level: float | None = None,
    ):
        options = _compact_options(
            _random_song_options(
                game,
                min_level,
                genre,
                difficulty,
                chart_type,
                maimai_version,
                chunithm_version,
                level_fixed,
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
