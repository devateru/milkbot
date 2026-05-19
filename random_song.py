from __future__ import annotations

import json
import random
import re
import urllib.request
from asyncio import to_thread
from dataclasses import dataclass
from typing import Any

import discord

from messages import get_message


DATA_SOURCES = {
    "maimai": "https://dp4p6x0xfi5o9.cloudfront.net/maimai",
    "chunithm": "https://dp4p6x0xfi5o9.cloudfront.net/chunithm",
}

DIFFICULTY_COLORS = {
    "basic": 0x22BB5B,
    "advanced": 0xFB9C2D,
    "expert": 0xF64861,
    "master": 0x9E45E2,
    "remaster": 0xBA67F8,
    "ultima": 0x111111,
}

DIFFICULTY_LABELS = {
    "basic": "BASIC",
    "advanced": "ADVANCED",
    "expert": "EXPERT",
    "master": "MASTER",
    "remaster": "Re:MASTER",
    "ultima": "ULTIMA",
}

HIGH_DIFFICULTIES = {
    "maimai": "remaster",
    "chunithm": "ultima",
}

GENRE_CHOICES = {
    "pops": {
        "label": "POPS & ANIME",
        "maimai": {"POPS＆アニメ"},
        "chunithm": {"POPS & ANIME"},
    },
    "niconico": {
        "label": "niconico & VOCALOID",
        "maimai": {"niconico＆ボーカロイド"},
        "chunithm": {"niconico"},
    },
    "touhou": {
        "label": "東方Project",
        "maimai": {"東方Project"},
        "chunithm": {"東方Project"},
    },
    "variety": {
        "label": "GAME & VARIETY",
        "maimai": {"ゲーム＆バラエティ"},
        "chunithm": {"VARIETY"},
    },
    "original": {
        "label": "ORIGINAL",
        "maimai": {"maimai"},
        "chunithm": {"ORIGINAL", "イロドリミドリ"},
    },
    "gekimai": {
        "label": "GEKICHUMAI",
        "maimai": {"オンゲキ＆CHUNITHM"},
        "chunithm": {"ゲキマイ"},
    },
}

DIFFICULTY_ALIASES = {
    "bas": "basic",
    "basic": "basic",
    "adv": "advanced",
    "advanced": "advanced",
    "exp": "expert",
    "expert": "expert",
    "mas": "master",
    "master": "master",
    "remas": "high",
    "re:master": "high",
    "remaster": "high",
    "re": "high",
    "ultimaremaster": "high",
    "remasterultima": "high",
    "re:masterultima": "high",
    "ultima/re:master": "high",
    "re:master/ultima": "high",
    "high": "high",
    "ultima": "high",
    "ult": "high",
}

DIFFICULTY_CHOICE_ALIASES = {
    "basic": ("basic",),
    "advanced": ("advanced",),
    "expert": ("expert",),
    "master": ("master",),
    "remasterultima": ("high",),
    "remasult": ("high",),
    "mas~remasult": ("master", "high"),
    "master~remasterultima": ("master", "high"),
    "exp~remasult": ("expert", "master", "high"),
    "expert~remasterultima": ("expert", "master", "high"),
}

TYPE_ALIASES = {
    "standard": "std",
    "std": "std",
    "deluxe": "dx",
    "dx": "dx",
    "utage": "special",
    "宴": "special",
    "utageworldsend": "special",
    "we": "special",
    "worldsend": "special",
    "world'send": "special",
    "world's end": "special",
    "worlds end": "special",
}


class RandomSongError(RuntimeError):
    pass


@dataclass(frozen=True)
class SongPick:
    game: str
    song: dict[str, Any]
    sheet: dict[str, Any]
    partner_sheet: dict[str, Any] | None
    data_source_url: str
    update_time: str


def _normalize_compact(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", value.strip().lower())


def _normalize_choice(value: str) -> str:
    return re.sub(r"[\s_\-/:'’]+", "", value.strip().lower())


def _resolve_difficulty(value: str, game: str) -> str:
    if value == "high":
        return HIGH_DIFFICULTIES[game]

    return value


def parse_difficulties(value: str | None, game: str) -> set[str]:
    if not value:
        return {"master", HIGH_DIFFICULTIES[game]}

    choice_key = _normalize_choice(value)
    choice_difficulties = DIFFICULTY_CHOICE_ALIASES.get(choice_key)
    if choice_difficulties is not None:
        return {_resolve_difficulty(difficulty, game) for difficulty in choice_difficulties}

    difficulties: set[str] = set()
    normalized_value = re.sub(
        r"re\s*:?\s*master\s*/\s*ultima|ultima\s*/\s*re\s*:?\s*master",
        "high",
        value,
        flags=re.IGNORECASE,
    )
    for raw_token in re.split(r"[,/| ]+", normalized_value):
        token = _normalize_compact(raw_token)
        if not token:
            continue
        difficulty = DIFFICULTY_ALIASES.get(token)
        if difficulty is None:
            raise RandomSongError(get_message("random_song.error_unknown_difficulty", value=raw_token))
        difficulties.add(_resolve_difficulty(difficulty, game))

    return difficulties


def parse_types(value: str | None, game: str) -> set[str] | None:
    if game == "chunithm" and not value:
        return {"std"}

    if not value:
        return None

    compact = _normalize_choice(value)
    chart_type = TYPE_ALIASES.get(compact) or TYPE_ALIASES.get(value.strip().lower())
    if chart_type is None:
        raise RandomSongError(get_message("random_song.error_unknown_type", value=value))

    if game == "chunithm":
        return {"we"} if chart_type == "special" else {"std"}

    return {"utage"} if chart_type == "special" else {chart_type}


def selected_type_for_default() -> set[str]:
    return {"std"} if random.random() < 0.2 else {"dx"}


async def fetch_game_data(game: str) -> dict[str, Any]:
    data_source_url = DATA_SOURCES[game]

    def load_data() -> dict[str, Any]:
        with urllib.request.urlopen(f"{data_source_url}/data.json", timeout=15) as response:
            return json.load(response)

    return await to_thread(load_data)


def _is_intl(sheet: dict[str, Any]) -> bool:
    return bool(sheet.get("regions", {}).get("intl"))


def _chart_level(sheet: dict[str, Any]) -> float | None:
    value = sheet.get("internalLevelValue")
    if value is None:
        value = sheet.get("levelValue")

    return float(value) if value is not None else None


def _song_category(song: dict[str, Any]) -> str | None:
    return song.get("category")


def _matches_genre(song: dict[str, Any], game: str, genre: str | None) -> bool:
    if not genre:
        return True

    genre_config = GENRE_CHOICES.get(genre)
    if genre_config is None:
        raise RandomSongError(get_message("random_song.error_unknown_genre", value=genre))

    return _song_category(song) in genre_config[game]


def _matches_type(sheet: dict[str, Any], allowed_types: set[str]) -> bool:
    return sheet.get("type") in allowed_types


def _matches_difficulty(sheet: dict[str, Any], allowed_difficulties: set[str], ignore: bool) -> bool:
    return ignore or sheet.get("difficulty") in allowed_difficulties


def _find_partner_sheet(
    song: dict[str, Any],
    primary_sheet: dict[str, Any],
    min_level: float,
    max_level: float,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for sheet in song.get("sheets", []):
        if sheet is primary_sheet or not _is_intl(sheet):
            continue

        level = _chart_level(sheet)
        if level is not None and min_level <= level <= max_level:
            candidates.append(sheet)

    return random.choice(candidates) if candidates else None


def _choose_level(levels: list[float]) -> float:
    unique_levels = sorted(set(levels))
    if not unique_levels:
        raise RandomSongError(get_message("random_song.error_no_matches"))

    if len(unique_levels) >= 3 and random.random() < 0.035:
        return random.choice(unique_levels[-min(5, len(unique_levels)):])

    max_rank = len(unique_levels) - 1
    weights: list[float] = []
    for rank, level in enumerate(unique_levels):
        distance = rank + 1
        weight = 1 / (distance**1.35)
        if rank == max_rank:
            weight *= 1.8
        weights.append(weight)

    return random.choices(unique_levels, weights=weights, k=1)[0]


def pick_random_song(
    data: dict[str, Any],
    *,
    game: str,
    min_level: float,
    genre: str | None,
    difficulties: set[str],
    chart_types: set[str],
    partner_min_level: float | None,
    partner_max_level: float | None,
) -> SongPick:
    ignore_difficulty = bool(chart_types & {"utage", "we"})
    candidates_by_level: dict[float, list[tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]]] = {}

    for song in data.get("songs", []):
        if not _matches_genre(song, game, genre):
            continue

        for sheet in song.get("sheets", []):
            level = _chart_level(sheet)
            if level is None or level < min_level:
                continue
            if not _is_intl(sheet):
                continue
            if not _matches_type(sheet, chart_types):
                continue
            if not _matches_difficulty(sheet, difficulties, ignore_difficulty):
                continue

            partner_sheet = None
            if partner_min_level is not None and partner_max_level is not None:
                partner_sheet = _find_partner_sheet(song, sheet, partner_min_level, partner_max_level)
                if partner_sheet is None:
                    continue

            candidates_by_level.setdefault(level, []).append((song, sheet, partner_sheet))

    selected_level = _choose_level(list(candidates_by_level))
    song, sheet, partner_sheet = random.choice(candidates_by_level[selected_level])
    return SongPick(
        game=game,
        song=song,
        sheet=sheet,
        partner_sheet=partner_sheet,
        data_source_url=DATA_SOURCES[game],
        update_time=data.get("updateTime", ""),
    )


def _cover_url(pick: SongPick) -> str | None:
    image_name = pick.song.get("imageName")
    if not image_name:
        return None

    return f"{pick.data_source_url}/img/cover/{image_name}"


def _version(song: dict[str, Any], sheet: dict[str, Any]) -> str:
    intl_override = sheet.get("regionOverrides", {}).get("intl", {})
    return intl_override.get("version") or sheet.get("version") or song.get("version") or "-"


def _field_value(value: Any) -> str:
    if value is None or value == "":
        return "-"

    return str(value)


def _format_difficulty(sheet: dict[str, Any]) -> str:
    difficulty = str(sheet.get("difficulty", "")).lower()
    difficulty_label = DIFFICULTY_LABELS.get(difficulty, _field_value(sheet.get("difficulty")))
    return get_message(
        "random_song.difficulty_value",
        difficulty=difficulty_label,
        level=_field_value(sheet.get("level")),
        constant=_field_value(_chart_level(sheet)),
    )


def build_song_embeds(pick: SongPick) -> list[discord.Embed]:
    embeds = [_build_primary_embed(pick)]

    if pick.partner_sheet is not None:
        embeds.append(_build_partner_embed(pick))

    return embeds


def _build_primary_embed(pick: SongPick) -> discord.Embed:
    song = pick.song
    sheet = pick.sheet
    difficulty = str(sheet.get("difficulty", "")).lower()
    title = _field_value(song.get("title"))
    embed = discord.Embed(
        title=title,
        color=DIFFICULTY_COLORS.get(difficulty, 0x1976D2),
    )

    embed.add_field(name=get_message("random_song.field_genre"), value=_field_value(song.get("category")), inline=True)
    embed.add_field(name=get_message("random_song.field_bpm"), value=_field_value(song.get("bpm")), inline=True)
    embed.add_field(name=get_message("random_song.field_artist"), value=_field_value(song.get("artist")), inline=False)
    embed.add_field(name=get_message("random_song.field_difficulty"), value=_format_difficulty(sheet), inline=True)
    embed.add_field(name=get_message("random_song.field_note_designer"), value=_field_value(sheet.get("noteDesigner")), inline=True)
    embed.add_field(name=get_message("random_song.field_version"), value=_version(song, sheet), inline=True)

    cover_url = _cover_url(pick)
    if cover_url:
        embed.set_image(url=cover_url)

    return embed


def _build_partner_embed(pick: SongPick) -> discord.Embed:
    song = pick.song
    sheet = pick.partner_sheet
    assert sheet is not None

    difficulty = str(sheet.get("difficulty", "")).lower()
    embed = discord.Embed(
        title=get_message("random_song.partner_embed_title"),
        color=DIFFICULTY_COLORS.get(difficulty, 0x1976D2),
    )
    embed.add_field(name=get_message("random_song.field_difficulty"), value=_format_difficulty(sheet), inline=True)
    embed.add_field(name=get_message("random_song.field_note_designer"), value=_field_value(sheet.get("noteDesigner")), inline=True)

    primary_version = _version(song, pick.sheet)
    partner_version = _version(song, sheet)
    if partner_version != primary_version:
        embed.add_field(name=get_message("random_song.field_version"), value=partner_version, inline=True)

    return embed


async def choose_random_song(
    *,
    game: str,
    min_level: float,
    genre: str | None,
    difficulty: str | None,
    chart_type: str | None,
    partner_level: float | None,
) -> list[discord.Embed]:
    if game not in DATA_SOURCES:
        raise RandomSongError(get_message("random_song.error_invalid_game"))

    partner_min_level = partner_level - 0.5 if partner_level is not None else None
    partner_max_level = partner_level + 1.0 if partner_level is not None else None

    difficulties = parse_difficulties(difficulty, game)
    chart_types = parse_types(chart_type, game) or selected_type_for_default()

    data = await fetch_game_data(game)
    pick = pick_random_song(
        data,
        game=game,
        min_level=min_level,
        genre=genre,
        difficulties=difficulties,
        chart_types=chart_types,
        partner_min_level=partner_min_level,
        partner_max_level=partner_max_level,
    )
    return build_song_embeds(pick)
