from __future__ import annotations

import discord
from discord import app_commands

from messages import get_message
from random_song import (
    CHUNITHM_GENRE_CHOICES,
    MAIMAI_GENRE_CHOICES,
    RandomSongError,
    calculate_level_probabilities,
    choose_random_song_response,
)
from storage import (
    get_random_song_preset,
    set_random_song_preset,
)


MAIMAI_DIFFICULTY_SUGGESTIONS = [
    ("BASIC", "BASIC"),
    ("ADVANCED", "ADVANCED"),
    ("EXPERT", "EXPERT"),
    ("MASTER", "MASTER"),
    ("RE:MASTER", "RE:MASTER"),
    ("MAS ~ RE:MAS", "MAS~RE:MAS"),
    ("EXP ~ RE:MAS", "EXP~RE:MAS"),
]

CHUNITHM_DIFFICULTY_SUGGESTIONS = [
    ("BASIC", "BASIC"),
    ("ADVANCED", "ADVANCED"),
    ("EXPERT", "EXPERT"),
    ("MASTER", "MASTER"),
    ("ULTIMA", "ULTIMA"),
    ("MAS ~ ULT", "MAS~ULT"),
    ("EXP ~ ULT", "EXP~ULT"),
]

MAIMAI_TYPE_SUGGESTIONS = [
    ("STANDARD", "STANDARD"),
    ("DELUXE", "DELUXE"),
    ("UTAGE", "UTAGE/WORLD'S END"),
]

CHUNITHM_TYPE_SUGGESTIONS = [
    ("STANDARD", "STANDARD"),
    ("WORLD'S END", "UTAGE/WORLD'S END"),
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
    ("구곡 (~X-VERSE)", "old"),
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


def _choices(suggestions: list[tuple[str, str]]) -> list[app_commands.Choice[str]]:
    return [
        app_commands.Choice(name=name, value=value)
        for name, value in suggestions
    ]


MAIMAI_GENRE_APP_CHOICES = [
    app_commands.Choice(name=config["label"], value=genre_key)
    for genre_key, config in MAIMAI_GENRE_CHOICES.items()
]
CHUNITHM_GENRE_APP_CHOICES = [
    app_commands.Choice(name=config["label"], value=genre_key)
    for genre_key, config in CHUNITHM_GENRE_CHOICES.items()
]
MAIMAI_DIFFICULTY_CHOICES = _choices(MAIMAI_DIFFICULTY_SUGGESTIONS)
CHUNITHM_DIFFICULTY_CHOICES = _choices(CHUNITHM_DIFFICULTY_SUGGESTIONS)
MAIMAI_TYPE_CHOICES = _choices(MAIMAI_TYPE_SUGGESTIONS)
CHUNITHM_TYPE_CHOICES = _choices(CHUNITHM_TYPE_SUGGESTIONS)
MAIMAI_VERSION_CHOICES = _choices(MAIMAI_VERSION_SUGGESTIONS)
CHUNITHM_VERSION_CHOICES = _choices(CHUNITHM_VERSION_SUGGESTIONS)


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


def _preset_summary(
    preset: dict[str, object],
    *,
    genre_choices: list[app_commands.Choice[str]],
    difficulty_choices: list[app_commands.Choice[str]],
    type_choices: list[app_commands.Choice[str]],
    version_choices: list[app_commands.Choice[str]],
) -> str:
    parts: list[str] = []

    if "min_level" in preset:
        parts.append(f"최소 보면상수={preset['min_level']}")
    if "max_level" in preset:
        parts.append(f"최대 보면상수={preset['max_level']}")
    if "genre" in preset:
        parts.append(f"장르={_choice_name(genre_choices, preset['genre'])}")
    if "difficulty" in preset:
        parts.append(f"난이도={_choice_name(difficulty_choices, preset['difficulty'])}")
    if "chart_type" in preset:
        parts.append(f"유형={_choice_name(type_choices, preset['chart_type'])}")
    if "version" in preset:
        parts.append(f"버전={_choice_name(version_choices, preset['version'])}")
    if "partner_level" in preset:
        parts.append(f"2P 난이도={preset['partner_level']}")

    return ", ".join(parts)


def _format_preset_value(
    key: str,
    value: object,
    *,
    genre_choices: list[app_commands.Choice[str]],
    difficulty_choices: list[app_commands.Choice[str]],
    type_choices: list[app_commands.Choice[str]],
    version_choices: list[app_commands.Choice[str]],
) -> str:
    if key == "genre":
        return _choice_name(genre_choices, value)
    if key == "difficulty":
        return _choice_name(difficulty_choices, value)
    if key == "chart_type":
        return _choice_name(type_choices, value)
    if key == "version":
        return _choice_name(version_choices, value)

    return str(value)


def _preset_changes_summary(
    before: dict[str, object],
    touched: dict[str, object],
    *,
    genre_choices: list[app_commands.Choice[str]],
    difficulty_choices: list[app_commands.Choice[str]],
    type_choices: list[app_commands.Choice[str]],
    version_choices: list[app_commands.Choice[str]],
) -> str:
    labels = {
        "min_level": "최소 보면상수",
        "max_level": "최대 보면상수",
        "genre": "장르",
        "difficulty": "난이도",
        "chart_type": "유형",
        "version": "버전",
        "partner_level": "2P 난이도",
    }
    changes: list[str] = []

    for key, new_value in touched.items():
        old_value = before.get(key)
        if old_value == new_value:
            continue

        old_text = (
            _format_preset_value(
                key,
                old_value,
                genre_choices=genre_choices,
                difficulty_choices=difficulty_choices,
                type_choices=type_choices,
                version_choices=version_choices,
            )
            if old_value is not None
            else "없음"
        )
        new_text = _format_preset_value(
            key,
            new_value,
            genre_choices=genre_choices,
            difficulty_choices=difficulty_choices,
            type_choices=type_choices,
            version_choices=version_choices,
        )
        changes.append(f"{labels[key]}: {old_text} → {new_text}")

    return ", ".join(changes)


def _recommendation_content(
    game_label: str,
    applied_preset: dict[str, object],
    *,
    genre_choices: list[app_commands.Choice[str]],
    difficulty_choices: list[app_commands.Choice[str]],
    type_choices: list[app_commands.Choice[str]],
    version_choices: list[app_commands.Choice[str]],
) -> str:
    lines = [
        get_message(
            "random_song.recommendation_text",
            game=game_label,
        )
    ]
    preset_summary = _preset_summary(
        applied_preset,
        genre_choices=genre_choices,
        difficulty_choices=difficulty_choices,
        type_choices=type_choices,
        version_choices=version_choices,
    )

    if preset_summary:
        lines.append(
            get_message(
                "random_song.preset_applied",
                preset=preset_summary,
            )
        )

    return "\n".join(lines)


def _random_song_options(
    min_level: float | None,
    max_level: float | None,
    genre: app_commands.Choice[str] | None,
    difficulty: app_commands.Choice[str] | None,
    chart_type: app_commands.Choice[str] | None,
    version: str | None,
    partner_level: float | None,
) -> dict[str, object]:
    return {
        "min_level": min_level,
        "max_level": max_level,
        "genre": genre.value if genre else None,
        "difficulty": difficulty.value if difficulty else None,
        "chart_type": chart_type.value if chart_type else None,
        "version": version,
        "partner_level": partner_level,
    }


def _compact_options(options: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in options.items()
        if value is not None
    }


def _format_probability_percent(value: float) -> str:
    percent = value * 100
    if percent >= 10:
        return f"{percent:.1f}".rstrip("0").rstrip(".")

    return f"{percent:.2f}".rstrip("0").rstrip(".")


def _merge_with_preset(
    game: str,
    uid: int,
    options: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    preset = get_random_song_preset(game, uid)
    applied_preset = {
        key: value
        for key, value in preset.items()
        if options.get(key) is None
    }
    merged = {
        "min_level": options.get("min_level") if options.get("min_level") is not None else preset.get("min_level"),
        "max_level": options.get("max_level") if options.get("max_level") is not None else preset.get("max_level"),
        "genre": options.get("genre") if options.get("genre") is not None else preset.get("genre"),
        "difficulty": options.get("difficulty") if options.get("difficulty") is not None else preset.get("difficulty"),
        "chart_type": options.get("chart_type") if options.get("chart_type") is not None else preset.get("chart_type"),
        "version": options.get("version") if options.get("version") is not None else preset.get("version"),
        "partner_level": options.get("partner_level") if options.get("partner_level") is not None else preset.get("partner_level"),
    }

    return merged, applied_preset


async def _build_probability_table_embed(
    uid: int,
    *,
    game: str,
    title: str,
    description: str,
    genre_choices: list[app_commands.Choice[str]],
    difficulty_choices: list[app_commands.Choice[str]],
    type_choices: list[app_commands.Choice[str]],
    version_choices: list[app_commands.Choice[str]],
) -> discord.Embed:
    options = _random_song_options(None, None, None, None, None, None, None)
    merged_options, applied_preset = _merge_with_preset(game, uid, options)
    probabilities = await calculate_level_probabilities(
        game=game,
        min_level=float(merged_options["min_level"]) if merged_options.get("min_level") is not None else None,
        max_level=float(merged_options["max_level"]) if merged_options.get("max_level") is not None else None,
        genre=str(merged_options["genre"]) if merged_options.get("genre") is not None else None,
        difficulty=str(merged_options["difficulty"]) if merged_options.get("difficulty") is not None else None,
        chart_type=str(merged_options["chart_type"]) if merged_options.get("chart_type") is not None else None,
        version=str(merged_options["version"]) if merged_options.get("version") is not None else None,
        partner_level=float(merged_options["partner_level"]) if merged_options.get("partner_level") is not None else None,
    )
    preset_summary = _preset_summary(
        applied_preset,
        genre_choices=genre_choices,
        difficulty_choices=difficulty_choices,
        type_choices=type_choices,
        version_choices=version_choices,
    )
    if preset_summary:
        description += f"\n프리셋: {preset_summary}"

    embed = discord.Embed(
        title=title,
        description=description,
        color=0xD78CFF,
    )
    rows = [
        f"`{level:g}`  {_format_probability_percent(probability)}%"
        for level, probability in sorted(probabilities.items())
    ]

    for index in range(0, len(rows), 20):
        embed.add_field(
            name="보면상수" if index == 0 else "보면상수 계속",
            value="\n".join(rows[index:index + 20]),
            inline=True,
        )

    return embed


async def build_maimai_probability_table_embed(uid: int) -> discord.Embed:
    return await _build_probability_table_embed(
        uid,
        game="maimai",
        title="마이마이 확률표",
        description="현재 마이선곡 프리셋 기준입니다.",
        genre_choices=MAIMAI_GENRE_APP_CHOICES,
        difficulty_choices=MAIMAI_DIFFICULTY_CHOICES,
        type_choices=MAIMAI_TYPE_CHOICES,
        version_choices=MAIMAI_VERSION_CHOICES,
    )


async def build_chunithm_probability_table_embed(uid: int) -> discord.Embed:
    return await _build_probability_table_embed(
        uid,
        game="chunithm",
        title="츄니즘 확률표",
        description="현재 츄니선곡 프리셋 기준입니다.",
        genre_choices=CHUNITHM_GENRE_APP_CHOICES,
        difficulty_choices=CHUNITHM_DIFFICULTY_CHOICES,
        type_choices=CHUNITHM_TYPE_CHOICES,
        version_choices=CHUNITHM_VERSION_CHOICES,
    )


async def _send_random_song(
    interaction: discord.Interaction,
    *,
    game: str,
    game_label: str,
    options: dict[str, object],
    genre_choices: list[app_commands.Choice[str]],
    difficulty_choices: list[app_commands.Choice[str]],
    type_choices: list[app_commands.Choice[str]],
    version_choices: list[app_commands.Choice[str]],
) -> None:
    await interaction.response.defer(thinking=True)
    merged_options, applied_preset = _merge_with_preset(game, interaction.user.id, options)

    try:
        response = await choose_random_song_response(
            game=game,
            min_level=float(merged_options["min_level"]) if merged_options.get("min_level") is not None else None,
            max_level=float(merged_options["max_level"]) if merged_options.get("max_level") is not None else None,
            genre=str(merged_options["genre"]) if merged_options.get("genre") is not None else None,
            difficulty=str(merged_options["difficulty"]) if merged_options.get("difficulty") is not None else None,
            chart_type=str(merged_options["chart_type"]) if merged_options.get("chart_type") is not None else None,
            version=str(merged_options["version"]) if merged_options.get("version") is not None else None,
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
        content=_recommendation_content(
            game_label,
            applied_preset,
            genre_choices=genre_choices,
            difficulty_choices=difficulty_choices,
            type_choices=type_choices,
            version_choices=version_choices,
        ),
        embeds=response.embeds,
        files=response.files,
    )


async def _save_preset(
    interaction: discord.Interaction,
    *,
    game: str,
    options: dict[str, object],
    genre_choices: list[app_commands.Choice[str]],
    difficulty_choices: list[app_commands.Choice[str]],
    type_choices: list[app_commands.Choice[str]],
    version_choices: list[app_commands.Choice[str]],
) -> None:
    compact_options = _compact_options(options)
    current_preset = get_random_song_preset(game, interaction.user.id)

    if not compact_options:
        message_key = "random_song.preset_current" if current_preset else "random_song.preset_empty"
        await interaction.response.send_message(
            get_message(
                message_key,
                preset=_preset_summary(
                    current_preset,
                    genre_choices=genre_choices,
                    difficulty_choices=difficulty_choices,
                    type_choices=type_choices,
                    version_choices=version_choices,
                ),
            ),
            ephemeral=True,
        )
        return

    updated_preset = {**current_preset, **compact_options}
    changes = _preset_changes_summary(
        current_preset,
        compact_options,
        genre_choices=genre_choices,
        difficulty_choices=difficulty_choices,
        type_choices=type_choices,
        version_choices=version_choices,
    )
    set_random_song_preset(game, interaction.user.id, updated_preset)
    await interaction.response.send_message(
        get_message(
            "random_song.preset_saved",
            preset=_preset_summary(
                updated_preset,
                genre_choices=genre_choices,
                difficulty_choices=difficulty_choices,
                type_choices=type_choices,
                version_choices=version_choices,
            ),
            changes=changes or get_message("random_song.preset_no_changes"),
        ),
        ephemeral=True,
    )


def register_random_song_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="마이선곡",
        description=get_message("slash.maimai_song_description"),
    )
    @app_commands.rename(
        min_level="최소_보면상수",
        max_level="최대_보면상수",
        genre="장르",
        difficulty="난이도",
        chart_type="유형",
        version="버전",
        partner_level="2p_난이도",
    )
    @app_commands.describe(
        min_level=get_message("random_song.option_min_level"),
        max_level=get_message("random_song.option_max_level"),
        genre=get_message("random_song.option_genre"),
        difficulty=get_message("random_song.option_maimai_difficulty"),
        chart_type=get_message("random_song.option_maimai_chart_type"),
        version=get_message("random_song.option_maimai_version"),
        partner_level=get_message("random_song.option_partner_level"),
    )
    @app_commands.choices(
        genre=MAIMAI_GENRE_APP_CHOICES,
        difficulty=MAIMAI_DIFFICULTY_CHOICES,
        chart_type=MAIMAI_TYPE_CHOICES,
    )
    @app_commands.autocomplete(version=maimai_version_autocomplete)
    async def maimai_song_command(
        interaction: discord.Interaction,
        min_level: float | None = None,
        max_level: float | None = None,
        genre: app_commands.Choice[str] | None = None,
        difficulty: app_commands.Choice[str] | None = None,
        chart_type: app_commands.Choice[str] | None = None,
        version: str | None = None,
        partner_level: float | None = None,
    ):
        await _send_random_song(
            interaction,
            game="maimai",
            game_label="maimai DX",
            options=_random_song_options(min_level, max_level, genre, difficulty, chart_type, version, partner_level),
            genre_choices=MAIMAI_GENRE_APP_CHOICES,
            difficulty_choices=MAIMAI_DIFFICULTY_CHOICES,
            type_choices=MAIMAI_TYPE_CHOICES,
            version_choices=MAIMAI_VERSION_CHOICES,
        )

    @tree.command(
        name="츄니선곡",
        description=get_message("slash.chunithm_song_description"),
    )
    @app_commands.rename(
        min_level="최소_보면상수",
        max_level="최대_보면상수",
        genre="장르",
        difficulty="난이도",
        chart_type="유형",
        version="버전",
        partner_level="2p_난이도",
    )
    @app_commands.describe(
        min_level=get_message("random_song.option_min_level"),
        max_level=get_message("random_song.option_max_level"),
        genre=get_message("random_song.option_genre"),
        difficulty=get_message("random_song.option_chunithm_difficulty"),
        chart_type=get_message("random_song.option_chunithm_chart_type"),
        version=get_message("random_song.option_chunithm_version"),
        partner_level=get_message("random_song.option_partner_level"),
    )
    @app_commands.choices(
        genre=CHUNITHM_GENRE_APP_CHOICES,
        difficulty=CHUNITHM_DIFFICULTY_CHOICES,
        chart_type=CHUNITHM_TYPE_CHOICES,
    )
    @app_commands.autocomplete(version=chunithm_version_autocomplete)
    async def chunithm_song_command(
        interaction: discord.Interaction,
        min_level: float | None = None,
        max_level: float | None = None,
        genre: app_commands.Choice[str] | None = None,
        difficulty: app_commands.Choice[str] | None = None,
        chart_type: app_commands.Choice[str] | None = None,
        version: str | None = None,
        partner_level: float | None = None,
    ):
        await _send_random_song(
            interaction,
            game="chunithm",
            game_label="CHUNITHM",
            options=_random_song_options(min_level, max_level, genre, difficulty, chart_type, version, partner_level),
            genre_choices=CHUNITHM_GENRE_APP_CHOICES,
            difficulty_choices=CHUNITHM_DIFFICULTY_CHOICES,
            type_choices=CHUNITHM_TYPE_CHOICES,
            version_choices=CHUNITHM_VERSION_CHOICES,
        )

    @tree.command(
        name="마이선곡-프리셋",
        description=get_message("slash.maimai_song_preset_description"),
    )
    @app_commands.rename(
        min_level="최소_보면상수",
        max_level="최대_보면상수",
        genre="장르",
        difficulty="난이도",
        chart_type="유형",
        version="버전",
        partner_level="2p_난이도",
    )
    @app_commands.describe(
        min_level=get_message("random_song.option_min_level"),
        max_level=get_message("random_song.option_max_level"),
        genre=get_message("random_song.option_genre"),
        difficulty=get_message("random_song.option_maimai_difficulty"),
        chart_type=get_message("random_song.option_maimai_chart_type"),
        version=get_message("random_song.option_maimai_version"),
        partner_level=get_message("random_song.option_partner_level"),
    )
    @app_commands.choices(
        genre=MAIMAI_GENRE_APP_CHOICES,
        difficulty=MAIMAI_DIFFICULTY_CHOICES,
        chart_type=MAIMAI_TYPE_CHOICES,
    )
    @app_commands.autocomplete(version=maimai_version_autocomplete)
    async def maimai_song_preset_command(
        interaction: discord.Interaction,
        min_level: float | None = None,
        max_level: float | None = None,
        genre: app_commands.Choice[str] | None = None,
        difficulty: app_commands.Choice[str] | None = None,
        chart_type: app_commands.Choice[str] | None = None,
        version: str | None = None,
        partner_level: float | None = None,
    ):
        await _save_preset(
            interaction,
            game="maimai",
            options=_random_song_options(min_level, max_level, genre, difficulty, chart_type, version, partner_level),
            genre_choices=MAIMAI_GENRE_APP_CHOICES,
            difficulty_choices=MAIMAI_DIFFICULTY_CHOICES,
            type_choices=MAIMAI_TYPE_CHOICES,
            version_choices=MAIMAI_VERSION_CHOICES,
        )

    @tree.command(
        name="츄니선곡-프리셋",
        description=get_message("slash.chunithm_song_preset_description"),
    )
    @app_commands.rename(
        min_level="최소_보면상수",
        max_level="최대_보면상수",
        genre="장르",
        difficulty="난이도",
        chart_type="유형",
        version="버전",
        partner_level="2p_난이도",
    )
    @app_commands.describe(
        min_level=get_message("random_song.option_min_level"),
        max_level=get_message("random_song.option_max_level"),
        genre=get_message("random_song.option_genre"),
        difficulty=get_message("random_song.option_chunithm_difficulty"),
        chart_type=get_message("random_song.option_chunithm_chart_type"),
        version=get_message("random_song.option_chunithm_version"),
        partner_level=get_message("random_song.option_partner_level"),
    )
    @app_commands.choices(
        genre=CHUNITHM_GENRE_APP_CHOICES,
        difficulty=CHUNITHM_DIFFICULTY_CHOICES,
        chart_type=CHUNITHM_TYPE_CHOICES,
    )
    @app_commands.autocomplete(version=chunithm_version_autocomplete)
    async def chunithm_song_preset_command(
        interaction: discord.Interaction,
        min_level: float | None = None,
        max_level: float | None = None,
        genre: app_commands.Choice[str] | None = None,
        difficulty: app_commands.Choice[str] | None = None,
        chart_type: app_commands.Choice[str] | None = None,
        version: str | None = None,
        partner_level: float | None = None,
    ):
        await _save_preset(
            interaction,
            game="chunithm",
            options=_random_song_options(min_level, max_level, genre, difficulty, chart_type, version, partner_level),
            genre_choices=CHUNITHM_GENRE_APP_CHOICES,
            difficulty_choices=CHUNITHM_DIFFICULTY_CHOICES,
            type_choices=CHUNITHM_TYPE_CHOICES,
            version_choices=CHUNITHM_VERSION_CHOICES,
        )
