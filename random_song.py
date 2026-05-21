from __future__ import annotations

import json
import random
import re
import urllib.parse
import urllib.request
from asyncio import to_thread
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import discord

from messages import get_message


DATA_SOURCES = {
    "maimai": "https://dp4p6x0xfi5o9.cloudfront.net/maimai",
    "chunithm": "https://dp4p6x0xfi5o9.cloudfront.net/chunithm",
}

GAME_SEARCH_LABELS = {
    "maimai": "maimai",
    "chunithm": "CHUNITHM",
}

MAIMAI_NEW_VERSIONS = {"PRiSM PLUS", "CiRCLE", "CiRCLE PLUS"}
CHUNITHM_NEW_VERSIONS = {"X-VERSE-X"}

LEVEL_SCALE_MAX = {
    "maimai": 15.0,
    "chunithm": 15.7,
}
LEVEL_WEIGHT_X_MIN = 0.13
RIDICULOUS_LEVEL_MIN = {
    "maimai": 14.9,
    "chunithm": 15.6,
}
RIDICULOUS_LEVEL_POOL_PROBABILITY = 0.01

DIFFICULTY_COLORS = {
    "basic": 0x22BB5B,
    "advanced": 0xFB9C2D,
    "expert": 0xF64861,
    "master": 0x9E45E2,
    "remaster": 0xD78CFF,
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

CHART_TYPE_LABELS = {
    "std": "STANDARD",
    "dx": "DELUXE",
    "utage": "UTAGE",
    "we": "WORLD'S END",
}

HIGH_DIFFICULTIES = {
    "maimai": "remaster",
    "chunithm": "ultima",
}

DATA_DIFFICULTIES = {
    "maimai": {"basic", "advanced", "expert", "master", "remaster"},
    "chunithm": {"basic", "advanced", "expert", "master", "ultima"},
}

MAIMAI_GENRE_CHOICES = {
    "pops": {
        "label": "POPS & ANIME",
        "categories": {"POPS＆アニメ"},
    },
    "niconico": {
        "label": "niconico & VOCALOID",
        "categories": {"niconico＆ボーカロイド"},
    },
    "touhou": {
        "label": "東方Project",
        "categories": {"東方Project"},
    },
    "variety": {
        "label": "GAME & VARIETY",
        "categories": {"ゲーム＆バラエティ"},
    },
    "original": {
        "label": "maimai",
        "categories": {"maimai"},
    },
    "gekimai": {
        "label": "ONGEKI & CHUNITHM",
        "categories": {"オンゲキ＆CHUNITHM"},
    },
}

CHUNITHM_GENRE_CHOICES = {
    "pops": {
        "label": "POPS & ANIME",
        "categories": {"POPS & ANIME"},
    },
    "niconico": {
        "label": "niconico",
        "categories": {"niconico"},
    },
    "touhou": {
        "label": "東方Project",
        "categories": {"東方Project"},
    },
    "variety": {
        "label": "VARIETY",
        "categories": {"VARIETY"},
    },
    "original": {
        "label": "ORIGINAL",
        "categories": {"ORIGINAL"},
    },
    "irodorimidori": {
        "label": "イロドリミドリ",
        "categories": {"イロドリミドリ"},
    },
    "gekimai": {
        "label": "ゲキマイ",
        "categories": {"ゲキマイ"},
    },
}

GENRE_CHOICES_BY_GAME = {
    "maimai": MAIMAI_GENRE_CHOICES,
    "chunithm": CHUNITHM_GENRE_CHOICES,
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
    "remaster": ("high",),
    "re:master": ("high",),
    "ultima": ("high",),
    "ult": ("high",),
    "mas~remasult": ("master", "high"),
    "mas~remas": ("master", "high"),
    "mas~remaster": ("master", "high"),
    "mas~ult": ("master", "high"),
    "mas~ultima": ("master", "high"),
    "master~remasterultima": ("master", "high"),
    "exp~remasult": ("expert", "master", "high"),
    "exp~remas": ("expert", "master", "high"),
    "exp~remaster": ("expert", "master", "high"),
    "exp~ult": ("expert", "master", "high"),
    "exp~ultima": ("expert", "master", "high"),
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
    data: dict[str, Any]
    data_source_url: str
    update_time: str
    requested_level: float | None
    max_level: float | None
    selected_level_probability: float


@dataclass(frozen=True)
class RandomSongResponse:
    embeds: list[discord.Embed]
    files: list[discord.File]
    pick: SongPick
    data: dict[str, Any]


@dataclass(frozen=True)
class SongLocationCandidate:
    folder: str
    sort: str
    index: int
    total: int

    @property
    def edge_distance(self) -> int:
        return min(self.index, self.total - self.index + 1)

    @property
    def edge_label(self) -> str:
        right_index = self.total - self.index + 1
        if self.index <= right_index:
            return get_message("random_song.location_from_left", count=self.index)

        return get_message("random_song.location_from_right", count=right_index)


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
        return set(DATA_DIFFICULTIES[game])

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


def parse_version_filter(
    game: str,
    version: str | None,
    data: dict[str, Any],
) -> set[str] | None:
    if not version:
        return None

    versions = {
        version["version"]
        for version in data.get("versions", [])
        if isinstance(version, dict) and version.get("version")
    }

    if game == "maimai":
        if version == "new":
            return MAIMAI_NEW_VERSIONS & versions
        if version == "old":
            return versions - MAIMAI_NEW_VERSIONS
    else:
        if version == "new":
            return CHUNITHM_NEW_VERSIONS & versions
        if version == "old":
            return versions - CHUNITHM_NEW_VERSIONS

    if version in versions:
        return {version}

    raise RandomSongError(get_message("random_song.error_unknown_version", value=version))


def selected_type_for_default() -> set[str]:
    return {"std"} if random.random() < 0.2 else {"dx"}


def selected_type_for_default_with_probability(game: str) -> tuple[set[str], float]:
    if game == "chunithm":
        return {"std"}, 1.0

    if random.random() < 0.2:
        return {"std"}, 0.2

    return {"dx"}, 0.8


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


def _song_title(song: dict[str, Any]) -> str:
    return _field_value(song.get("title"))


def _sort_text(value: Any) -> str:
    return _field_value(value).casefold()


def _sort_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _matches_genre(song: dict[str, Any], game: str, genre: str | None) -> bool:
    if not genre:
        return True

    genre_config = GENRE_CHOICES_BY_GAME.get(game, {}).get(genre)
    if genre_config is None:
        raise RandomSongError(get_message("random_song.error_unknown_genre", value=genre))

    return _song_category(song) in genre_config["categories"]


def _matches_type(sheet: dict[str, Any], allowed_types: set[str]) -> bool:
    return sheet.get("type") in allowed_types


def _matches_difficulty(sheet: dict[str, Any], allowed_difficulties: set[str], ignore: bool) -> bool:
    return ignore or sheet.get("difficulty") in allowed_difficulties


def _find_partner_sheet(
    song: dict[str, Any],
    primary_sheet: dict[str, Any],
    min_level: float,
    max_level: float,
    *,
    expected_direction: int,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    primary_level = _chart_level(primary_sheet)
    for sheet in song.get("sheets", []):
        if sheet is primary_sheet or not _is_intl(sheet):
            continue
        if sheet.get("type") != primary_sheet.get("type"):
            continue

        level = _chart_level(sheet)
        if level is None or not min_level <= level <= max_level:
            continue
        if primary_level is not None and expected_direction > 0 and level <= primary_level:
            continue
        if primary_level is not None and expected_direction < 0 and level >= primary_level:
            continue

        candidates.append(sheet)

    return random.choice(candidates) if candidates else None


def _partner_direction(primary_min_level: float | None, partner_min_level: float | None) -> int:
    if primary_min_level is None or partner_min_level is None:
        return 0

    partner_requested_level = partner_min_level + 0.5
    if partner_requested_level > primary_min_level:
        return 1
    if partner_requested_level < primary_min_level:
        return -1
    return 0


def _level_probabilities(
    levels: list[float],
    *,
    game: str,
    min_level: float | None,
) -> dict[float, float]:
    unique_levels = sorted(set(levels))
    if not unique_levels:
        raise RandomSongError(get_message("random_song.error_no_matches"))

    scale_min = min_level if min_level is not None else unique_levels[0]
    scale_max = max(LEVEL_SCALE_MAX.get(game, unique_levels[-1]), unique_levels[-1])
    weights_by_level: dict[float, float] = {}
    for level in unique_levels:
        if scale_max <= scale_min:
            x = 1.0
        else:
            position = (level - scale_min) / (scale_max - scale_min)
            x = LEVEL_WEIGHT_X_MIN + max(0.0, min(position, 1.0)) * (10 - LEVEL_WEIGHT_X_MIN)
        weight = 1 / x
        weights_by_level[level] = weight

    weight_sum = sum(weights_by_level.values())
    probabilities = {
        level: weight / weight_sum
        for level, weight in weights_by_level.items()
    }

    ridiculous_level_min = RIDICULOUS_LEVEL_MIN.get(game)
    if ridiculous_level_min is not None:
        ridiculous_levels = {
            level
            for level in probabilities
            if level >= ridiculous_level_min
        }
        ridiculous_probability = sum(probabilities[level] for level in ridiculous_levels)
        other_probability_sum = 1 - ridiculous_probability
        if 0 < ridiculous_probability < 1 and other_probability_sum > 0:
            remaining_probability = 1 - RIDICULOUS_LEVEL_POOL_PROBABILITY
            probabilities = {
                level: (
                    probability / ridiculous_probability * RIDICULOUS_LEVEL_POOL_PROBABILITY
                    if level in ridiculous_levels
                    else probability / other_probability_sum * remaining_probability
                )
                for level, probability in probabilities.items()
            }

    return probabilities


def _choose_level(
    levels: list[float],
    *,
    game: str,
    min_level: float | None,
) -> tuple[float, float]:
    probabilities = _level_probabilities(levels, game=game, min_level=min_level)
    selected_level = random.choices(
        list(probabilities.keys()),
        weights=list(probabilities.values()),
        k=1,
    )[0]
    return selected_level, probabilities[selected_level]


def _choose_uniform_level(levels: list[float]) -> tuple[float, float]:
    unique_levels = sorted(set(levels))
    if not unique_levels:
        raise RandomSongError(get_message("random_song.error_no_matches"))

    selected_level = random.choice(unique_levels)
    return selected_level, 1 / len(unique_levels)


def _probabilities_for_levels(
    levels: list[float],
    *,
    game: str,
    min_level: float | None,
    max_level: float | None,
) -> dict[float, float]:
    if max_level is not None:
        unique_levels = sorted(set(levels))
        if not unique_levels:
            raise RandomSongError(get_message("random_song.error_no_matches"))
        probability = 1 / len(unique_levels)
        return {level: probability for level in unique_levels}

    return _level_probabilities(levels, game=game, min_level=min_level)


def _candidate_levels(
    data: dict[str, Any],
    *,
    game: str,
    min_level: float | None,
    max_level: float | None,
    genre: str | None,
    difficulties: set[str],
    chart_types: set[str],
    version_filter: set[str] | None,
    partner_min_level: float | None,
    partner_max_level: float | None,
) -> dict[float, list[tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]]]:
    ignore_difficulty = bool(chart_types & {"utage", "we"})
    partner_direction = _partner_direction(min_level, partner_min_level)
    candidates_by_level: dict[float, list[tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]]] = {}

    for song in data.get("songs", []):
        if not _matches_genre(song, game, genre):
            continue
        if version_filter is not None and song.get("version") not in version_filter:
            continue

        for sheet in song.get("sheets", []):
            level = _chart_level(sheet)
            if level is None:
                continue
            if min_level is not None and level < min_level:
                continue
            if max_level is not None and level > max_level:
                continue
            if not _is_intl(sheet):
                continue
            if not _matches_type(sheet, chart_types):
                continue
            if not _matches_difficulty(sheet, difficulties, ignore_difficulty):
                continue

            partner_sheet = None
            if partner_min_level is not None and partner_max_level is not None:
                partner_sheet = _find_partner_sheet(
                    song,
                    sheet,
                    partner_min_level,
                    partner_max_level,
                    expected_direction=partner_direction,
                )
                if partner_sheet is None:
                    continue

            candidates_by_level.setdefault(level, []).append((song, sheet, partner_sheet))

    if not candidates_by_level:
        raise RandomSongError(get_message("random_song.error_no_matches"))

    return candidates_by_level


def pick_random_song(
    data: dict[str, Any],
    *,
    game: str,
    min_level: float | None,
    max_level: float | None,
    genre: str | None,
    difficulties: set[str],
    chart_types: set[str],
    version_filter: set[str] | None,
    partner_min_level: float | None,
    partner_max_level: float | None,
) -> SongPick:
    candidates_by_level = _candidate_levels(
        data,
        game=game,
        min_level=min_level,
        max_level=max_level,
        genre=genre,
        difficulties=difficulties,
        chart_types=chart_types,
        version_filter=version_filter,
        partner_min_level=partner_min_level,
        partner_max_level=partner_max_level,
    )
    if max_level is not None:
        selected_level, selected_probability = _choose_uniform_level(list(candidates_by_level))
    else:
        selected_level, selected_probability = _choose_level(
            list(candidates_by_level),
            game=game,
            min_level=min_level,
        )
    song, sheet, partner_sheet = random.choice(candidates_by_level[selected_level])
    return SongPick(
        game=game,
        song=song,
        sheet=sheet,
        partner_sheet=partner_sheet,
        data=data,
        data_source_url=DATA_SOURCES[game],
        update_time=data.get("updateTime", ""),
        requested_level=min_level,
        max_level=max_level,
        selected_level_probability=selected_probability,
    )


async def calculate_level_probabilities(
    *,
    game: str,
    min_level: float | None,
    max_level: float | None,
    genre: str | None,
    difficulty: str | None,
    chart_type: str | None,
    version: str | None,
    partner_level: float | None,
) -> dict[float, float]:
    if game not in DATA_SOURCES:
        raise RandomSongError(get_message("random_song.error_invalid_game"))

    partner_min_level = partner_level - 0.5 if partner_level is not None else None
    partner_max_level = partner_level + 1.0 if partner_level is not None else None
    difficulties = parse_difficulties(difficulty, game)
    data = await fetch_game_data(game)
    version_filter = parse_version_filter(game, version, data)

    if chart_type is None and game == "maimai":
        chart_type_options = [({"std"}, 0.2), ({"dx"}, 0.8)]
    else:
        chart_type_options = [(parse_types(chart_type, game) or {"std"}, 1.0)]

    combined_probabilities: dict[float, float] = {}
    for chart_types, type_probability in chart_type_options:
        candidates_by_level = _candidate_levels(
            data,
            game=game,
            min_level=min_level,
            max_level=max_level,
            genre=genre,
            difficulties=difficulties,
            chart_types=chart_types,
            version_filter=version_filter,
            partner_min_level=partner_min_level,
            partner_max_level=partner_max_level,
        )
        probabilities = _probabilities_for_levels(
            list(candidates_by_level),
            game=game,
            min_level=min_level,
            max_level=max_level,
        )
        for level, probability in probabilities.items():
            combined_probabilities[level] = combined_probabilities.get(level, 0) + probability * type_probability

    probability_sum = sum(combined_probabilities.values())
    if probability_sum <= 0:
        raise RandomSongError(get_message("random_song.error_no_matches"))

    return {
        level: probability / probability_sum
        for level, probability in combined_probabilities.items()
    }


def _same_location_tab(pick: SongPick, song: dict[str, Any], sheet: dict[str, Any]) -> bool:
    if not _is_intl(sheet):
        return False
    if (song.get("isLocked") is True) != (pick.song.get("isLocked") is True):
        return False
    if sheet.get("difficulty") != pick.sheet.get("difficulty"):
        return False

    pick_type = pick.sheet.get("type")
    if pick_type in {"utage", "we"}:
        return sheet.get("type") == pick_type

    return sheet.get("type") not in {"utage", "we"}


def _location_entries(data: dict[str, Any], pick: SongPick) -> list[tuple[int, dict[str, Any], dict[str, Any]]]:
    entries: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    order = 0
    for song in data.get("songs", []):
        for sheet in song.get("sheets", []):
            if _same_location_tab(pick, song, sheet):
                entries.append((order, song, sheet))
                order += 1

    return entries


def _location_folder_candidates(
    entries: list[tuple[int, dict[str, Any], dict[str, Any]]],
    pick: SongPick,
) -> list[tuple[str, list[tuple[int, dict[str, Any], dict[str, Any]]]]]:
    pick_level = _field_value(pick.sheet.get("level"))
    pick_version = _version(pick.song, pick.sheet)
    return [
        (
            get_message("random_song.location_folder_genre", value=_field_value(pick.song.get("category"))),
            [entry for entry in entries if entry[1].get("category") == pick.song.get("category")],
        ),
        (
            get_message("random_song.location_folder_level", value=pick_level),
            [entry for entry in entries if _field_value(entry[2].get("level")) == pick_level],
        ),
        (
            get_message("random_song.location_folder_version", value=pick_version),
            [entry for entry in entries if _version(entry[1], entry[2]) == pick_version],
        ),
        (
            get_message("random_song.location_folder_all"),
            entries,
        ),
    ]


def _location_sort_candidates() -> list[tuple[str, Any]]:
    return [
        (get_message("random_song.location_sort_recommended"), lambda entry: (entry[0],)),
        (get_message("random_song.location_sort_title"), lambda entry: (_sort_text(entry[1].get("title")), entry[0])),
        (
            get_message("random_song.location_sort_level"),
            lambda entry: (
                _sort_number(entry[2].get("levelValue")),
                _sort_number(_chart_level(entry[2])),
                _sort_text(entry[1].get("title")),
                entry[0],
            ),
        ),
        (
            get_message("random_song.location_sort_release"),
            lambda entry: (_field_value(entry[1].get("releaseDate")), _sort_text(entry[1].get("title")), entry[0]),
        ),
        (
            get_message("random_song.location_sort_bpm"),
            lambda entry: (_sort_number(entry[1].get("bpm")), _sort_text(entry[1].get("title")), entry[0]),
        ),
    ]


def _is_picked_entry(entry: tuple[int, dict[str, Any], dict[str, Any]], pick: SongPick) -> bool:
    return entry[1] is pick.song and entry[2] is pick.sheet


def song_location_candidates(pick: SongPick, data: dict[str, Any], limit: int = 3) -> list[SongLocationCandidate]:
    entries = _location_entries(data, pick)
    candidates: list[SongLocationCandidate] = []
    for folder_label, folder_entries in _location_folder_candidates(entries, pick):
        if not folder_entries:
            continue
        for sort_label, sort_key in _location_sort_candidates():
            sorted_entries = sorted(folder_entries, key=sort_key)
            for index, entry in enumerate(sorted_entries, start=1):
                if _is_picked_entry(entry, pick):
                    candidates.append(
                        SongLocationCandidate(
                            folder=folder_label,
                            sort=sort_label,
                            index=index,
                            total=len(sorted_entries),
                        )
                    )
                    break

    candidates.sort(key=lambda candidate: (candidate.edge_distance, candidate.total, candidate.folder, candidate.sort))
    return candidates[:limit]


def build_song_location_text(pick: SongPick, data: dict[str, Any]) -> str:
    candidates = song_location_candidates(pick, data)
    if not candidates:
        return get_message("random_song.location_no_matches")

    lines = [
        get_message("random_song.location_header", title=_song_title(pick.song)),
        get_message("random_song.location_assumption"),
    ]
    for order, candidate in enumerate(candidates, start=1):
        lines.append(
            get_message(
                "random_song.location_line",
                order=order,
                folder=candidate.folder,
                sort=candidate.sort,
                index=candidate.index,
                total=candidate.total,
                edge=candidate.edge_label,
            )
        )

    return "\n".join(lines)


def _cover_url(pick: SongPick) -> str | None:
    image_name = pick.song.get("imageName")
    if not image_name:
        return None

    return f"{pick.data_source_url}/img/cover/{image_name}"


async def _cover_file(pick: SongPick) -> discord.File | None:
    cover_url = _cover_url(pick)
    if cover_url is None:
        return None

    def load_cover() -> discord.File:
        with urllib.request.urlopen(cover_url, timeout=15) as response:
            data = response.read()

        return discord.File(BytesIO(data), filename="random_song_cover.png")

    try:
        return await to_thread(load_cover)
    except Exception:
        return None


def _version(song: dict[str, Any], sheet: dict[str, Any]) -> str:
    intl_override = sheet.get("regionOverrides", {}).get("intl", {})
    return intl_override.get("version") or sheet.get("version") or song.get("version") or "-"


def _youtube_search_url(pick: SongPick) -> str:
    difficulty = str(pick.sheet.get("difficulty", "")).lower()
    query = " ".join(
        [
            GAME_SEARCH_LABELS[pick.game],
            _youtube_search_title(pick.song.get("title")),
            DIFFICULTY_LABELS.get(difficulty, _field_value(pick.sheet.get("difficulty"))),
        ]
    )
    return "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query})


def _youtube_search_title(value: Any) -> str:
    title = _field_value(value).strip()

    while len(title) >= 2 and title[-1] == title[-2] and not title[-1].isalnum():
        title = title[:-1]

    return title


def _format_probability(value: float) -> str:
    percent = value * 100

    if percent >= 10:
        return f"{percent:.1f}".rstrip("0").rstrip(".")

    return f"{percent:.2f}".rstrip("0").rstrip(".")


def _field_value(value: Any) -> str:
    if value is None or value == "":
        return "-"

    return str(value)


def _chart_type_value(sheet: dict[str, Any]) -> str:
    return CHART_TYPE_LABELS.get(str(sheet.get("type", "")), _field_value(sheet.get("type")))


def _genre_value(song: dict[str, Any]) -> str:
    value = _field_value(song.get("category"))
    if song.get("isLocked") is True:
        return f"{value} 🔒"

    return value


def _format_difficulty(sheet: dict[str, Any]) -> str:
    if sheet.get("type") == "we":
        difficulty = _field_value(sheet.get("difficulty")).strip("【】")
        level = _field_value(sheet.get("level"))
        return f"World's End [{difficulty} {level}]"

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
        url=_youtube_search_url(pick),
        color=DIFFICULTY_COLORS.get(difficulty, 0x1976D2),
    )

    embed.add_field(name=get_message("random_song.field_genre"), value=_genre_value(song), inline=True)
    embed.add_field(name=get_message("random_song.field_bpm"), value=_field_value(song.get("bpm")), inline=True)
    embed.add_field(name=get_message("random_song.field_artist"), value=_field_value(song.get("artist")), inline=False)
    embed.add_field(name=get_message("random_song.field_difficulty"), value=_format_difficulty(sheet), inline=True)
    if pick.game == "maimai":
        embed.add_field(name=get_message("random_song.field_chart_type"), value=_chart_type_value(sheet), inline=True)
    embed.add_field(name=get_message("random_song.field_note_designer"), value=_field_value(sheet.get("noteDesigner")), inline=True)
    embed.add_field(name=get_message("random_song.field_version"), value=_version(song, sheet), inline=True)
    cover_url = _cover_url(pick)
    if cover_url:
        embed.set_image(url=cover_url)

    selected_level = _chart_level(sheet)
    if (
        selected_level is not None
        and pick.requested_level is not None
        and pick.max_level is None
        and selected_level > pick.requested_level
    ):
        embed.set_footer(
            text=get_message(
                "random_song.higher_level_footer",
                probability=_format_probability(pick.selected_level_probability),
                level=_field_value(selected_level),
            )
        )

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
    min_level: float | None,
    max_level: float | None,
    genre: str | None,
    difficulty: str | None,
    chart_type: str | None,
    version: str | None,
    partner_level: float | None,
) -> list[discord.Embed]:
    pick = await choose_random_song_pick(
        game=game,
        min_level=min_level,
        max_level=max_level,
        genre=genre,
        difficulty=difficulty,
        chart_type=chart_type,
        version=version,
        partner_level=partner_level,
    )
    return build_song_embeds(pick)


async def choose_random_song_response(
    *,
    game: str,
    min_level: float | None,
    max_level: float | None,
    genre: str | None,
    difficulty: str | None,
    chart_type: str | None,
    version: str | None,
    partner_level: float | None,
) -> RandomSongResponse:
    pick = await choose_random_song_pick(
        game=game,
        min_level=min_level,
        max_level=max_level,
        genre=genre,
        difficulty=difficulty,
        chart_type=chart_type,
        version=version,
        partner_level=partner_level,
    )
    embeds = build_song_embeds(pick)
    cover_file = await _cover_file(pick)

    if cover_file is not None:
        embeds[0].set_image(url=f"attachment://{cover_file.filename}")
        return RandomSongResponse(embeds=embeds, files=[cover_file], pick=pick, data=pick.data)

    return RandomSongResponse(embeds=embeds, files=[], pick=pick, data=pick.data)


async def choose_random_song_pick(
    *,
    game: str,
    min_level: float | None,
    max_level: float | None,
    genre: str | None,
    difficulty: str | None,
    chart_type: str | None,
    version: str | None,
    partner_level: float | None,
) -> SongPick:
    if game not in DATA_SOURCES:
        raise RandomSongError(get_message("random_song.error_invalid_game"))

    partner_min_level = partner_level - 0.5 if partner_level is not None else None
    partner_max_level = partner_level + 1.0 if partner_level is not None else None

    difficulties = parse_difficulties(difficulty, game)
    parsed_types = parse_types(chart_type, game)
    if parsed_types is None:
        chart_types, type_probability = selected_type_for_default_with_probability(game)
    else:
        chart_types = parsed_types
        type_probability = 1.0
    data = await fetch_game_data(game)
    version_filter = parse_version_filter(game, version, data)

    pick = pick_random_song(
        data,
        game=game,
        min_level=min_level,
        max_level=max_level,
        genre=genre,
        difficulties=difficulties,
        chart_types=chart_types,
        version_filter=version_filter,
        partner_min_level=partner_min_level,
        partner_max_level=partner_max_level,
    )
    probabilities = await calculate_level_probabilities(
        game=game,
        min_level=min_level,
        max_level=max_level,
        genre=genre,
        difficulty=difficulty,
        chart_type=chart_type,
        version=version,
        partner_level=partner_level,
    )
    selected_level = _chart_level(pick.sheet)
    selected_level_probability = (
        probabilities.get(selected_level, pick.selected_level_probability)
        if selected_level is not None
        else pick.selected_level_probability
    )

    return SongPick(
        game=pick.game,
        song=pick.song,
        sheet=pick.sheet,
        partner_sheet=pick.partner_sheet,
        data=pick.data,
        data_source_url=pick.data_source_url,
        update_time=pick.update_time,
        requested_level=pick.requested_level,
        max_level=pick.max_level,
        selected_level_probability=selected_level_probability,
    )
