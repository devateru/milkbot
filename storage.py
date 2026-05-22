import json
from pathlib import Path
from typing import Any


STATE_FILE = Path("milkbot_state.json")


def default_state() -> dict[str, Any]:
    return {
        "treat_allowed_guild_ids": [],
        "guild_treat_rules": {},
        "random_song_presets": {},
        "random_song_unconfigured_warnings": {},
    }


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return default_state()

    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return default_state()

    if not isinstance(data, dict):
        return default_state()

    guild_ids = data.get("treat_allowed_guild_ids", [])
    fixed_guild_ids: list[str] = []

    if isinstance(guild_ids, list):
        for guild_id in guild_ids:
            guild_id = str(guild_id).strip()
            if guild_id.isdigit() and guild_id not in fixed_guild_ids:
                fixed_guild_ids.append(guild_id)

    guild_treat_rules = data.get("guild_treat_rules", {})
    fixed_guild_treat_rules: dict[str, list[dict[str, object]]] = {}

    if isinstance(guild_treat_rules, dict):
        for guild_id, rules in guild_treat_rules.items():
            guild_id_text = str(guild_id).strip()

            if not guild_id_text.isdigit() or not isinstance(rules, list):
                continue

            fixed_rules: list[dict[str, object]] = []
            seen_treats: set[str] = set()

            for rule in rules:
                if isinstance(rule, dict):
                    treat = str(rule.get("treat", "")).strip()
                    flexible = bool(rule.get("flexible", False))
                elif isinstance(rule, str):
                    treat = rule.strip()
                    flexible = False
                else:
                    continue

                if not treat or treat in seen_treats:
                    continue

                fixed_rules.append({"treat": treat, "flexible": flexible})
                seen_treats.add(treat)

            if fixed_rules:
                fixed_guild_treat_rules[guild_id_text] = fixed_rules

    random_song_presets = data.get("random_song_presets", {})
    fixed_random_song_presets: dict[str, dict[str, dict[str, object]]] = {}

    if isinstance(random_song_presets, dict):
        allowed_keys = {
            "min_level",
            "max_level",
            "genre",
            "difficulty",
            "chart_type",
            "version",
            "partner_level",
        }

        for game in ("maimai", "chunithm"):
            game_presets = random_song_presets.get(game)
            if not isinstance(game_presets, dict):
                continue

            fixed_game_presets: dict[str, dict[str, object]] = {}
            for uid, preset in game_presets.items():
                if not isinstance(preset, dict):
                    continue

                uid_text = str(uid).strip()
                fixed_preset = {
                    key: value
                    for key, value in preset.items()
                    if key in allowed_keys and value is not None
                }

                if uid_text.isdigit() and fixed_preset:
                    fixed_game_presets[uid_text] = fixed_preset

            if fixed_game_presets:
                fixed_random_song_presets[game] = fixed_game_presets

    random_song_unconfigured_warnings = data.get("random_song_unconfigured_warnings", {})
    fixed_random_song_unconfigured_warnings: dict[str, dict[str, str]] = {}

    if isinstance(random_song_unconfigured_warnings, dict):
        for game in ("maimai", "chunithm"):
            game_warnings = random_song_unconfigured_warnings.get(game)
            if not isinstance(game_warnings, dict):
                continue

            fixed_game_warnings: dict[str, str] = {}
            for uid, date_text in game_warnings.items():
                uid_text = str(uid).strip()
                date_text = str(date_text).strip()
                if uid_text.isdigit() and date_text:
                    fixed_game_warnings[uid_text] = date_text

            if fixed_game_warnings:
                fixed_random_song_unconfigured_warnings[game] = fixed_game_warnings

    return {
        "treat_allowed_guild_ids": fixed_guild_ids,
        "guild_treat_rules": fixed_guild_treat_rules,
        "random_song_presets": fixed_random_song_presets,
        "random_song_unconfigured_warnings": fixed_random_song_unconfigured_warnings,
    }


state = load_state()


def save_state() -> None:
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _get_guild_treat_rules_for_update(guild_id: int) -> list[dict[str, object]]:
    rules_by_guild = state.setdefault("guild_treat_rules", {})

    if not isinstance(rules_by_guild, dict):
        rules_by_guild = {}
        state["guild_treat_rules"] = rules_by_guild

    guild_id_text = str(guild_id)
    rules = rules_by_guild.setdefault(guild_id_text, [])

    if not isinstance(rules, list):
        rules = []
        rules_by_guild[guild_id_text] = rules

    return rules


def get_guild_treat_rules(guild_id: int) -> list[dict[str, object]]:
    rules_by_guild = state.get("guild_treat_rules", {})

    if not isinstance(rules_by_guild, dict):
        return []

    rules = rules_by_guild.get(str(guild_id), [])

    if not isinstance(rules, list):
        return []

    return [dict(rule) for rule in rules if isinstance(rule, dict)]


def add_guild_treat(guild_id: int, treat: str, flexible: bool = False) -> bool:
    treat = treat.strip()

    if not treat:
        return False

    rules = _get_guild_treat_rules_for_update(guild_id)

    if any(rule.get("treat") == treat for rule in rules):
        return False

    rules.append({"treat": treat, "flexible": flexible})
    save_state()
    return True


def remove_guild_treat(guild_id: int, treat: str) -> bool:
    rules_by_guild = state.setdefault("guild_treat_rules", {})

    if not isinstance(rules_by_guild, dict):
        return False

    guild_id_text = str(guild_id)
    rules = rules_by_guild.get(guild_id_text, [])

    if not isinstance(rules, list):
        return False

    for index, rule in enumerate(rules):
        if isinstance(rule, dict) and rule.get("treat") == treat:
            del rules[index]

            if not rules:
                del rules_by_guild[guild_id_text]

            save_state()
            return True

    return False


def get_allowed_guild_ids() -> list[str]:
    guild_ids = state.setdefault("treat_allowed_guild_ids", [])
    return list(guild_ids)


def add_allowed_guild(guild_id: int) -> bool:
    guild_ids = state.setdefault("treat_allowed_guild_ids", [])
    guild_id_text = str(guild_id)

    if guild_id_text in guild_ids:
        return False

    guild_ids.append(guild_id_text)
    save_state()
    return True


def remove_allowed_guild(guild_id: int) -> bool:
    guild_ids = state.setdefault("treat_allowed_guild_ids", [])
    guild_id_text = str(guild_id)

    if guild_id_text not in guild_ids:
        return False

    guild_ids.remove(guild_id_text)
    save_state()
    return True


def get_random_song_preset(game: str, uid: int) -> dict[str, object]:
    presets = state.setdefault("random_song_presets", {})
    game_presets = presets.setdefault(game, {})
    if not isinstance(game_presets, dict):
        presets[game] = {}
        return {}

    preset = game_presets.get(str(uid), {}) if isinstance(game_presets, dict) else {}
    return dict(preset) if isinstance(preset, dict) else {}


def set_random_song_preset(game: str, uid: int, preset: dict[str, object]) -> None:
    presets = state.setdefault("random_song_presets", {})
    game_presets = presets.setdefault(game, {})
    if not isinstance(game_presets, dict):
        game_presets = {}
        presets[game] = game_presets

    game_presets[str(uid)] = {
        key: value
        for key, value in preset.items()
        if value is not None
    }
    save_state()


def remove_random_song_preset(game: str, uid: int) -> bool:
    presets = state.setdefault("random_song_presets", {})
    game_presets = presets.setdefault(game, {})
    if not isinstance(game_presets, dict):
        presets[game] = {}
        return False

    uid_text = str(uid)

    if uid_text not in game_presets:
        return False

    del game_presets[uid_text]
    save_state()
    return True


def has_random_song_unconfigured_warning(game: str, uid: int, date_text: str) -> bool:
    warnings = state.setdefault("random_song_unconfigured_warnings", {})
    game_warnings = warnings.setdefault(game, {})
    if not isinstance(game_warnings, dict):
        warnings[game] = {}
        return False

    return game_warnings.get(str(uid)) == date_text


def set_random_song_unconfigured_warning(game: str, uid: int, date_text: str) -> None:
    warnings = state.setdefault("random_song_unconfigured_warnings", {})
    game_warnings = warnings.setdefault(game, {})
    if not isinstance(game_warnings, dict):
        game_warnings = {}
        warnings[game] = game_warnings

    game_warnings[str(uid)] = date_text
    save_state()
