import json
from pathlib import Path
from typing import Any


STATE_FILE = Path("milkbot_state.json")


def default_state() -> dict[str, Any]:
    return {
        "notreat_rules": {},
        "treat_allowed_guild_ids": [],
        "sega_facebook_channels": {},
        "sega_facebook_seen_post_ids": {},
        "random_song_presets": {},
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

    rules = data.get("notreat_rules", {})
    fixed_rules: dict[str, list[str]] = {}

    if isinstance(rules, dict):
        for uid, treats in rules.items():
            if isinstance(treats, list):
                fixed_rules[str(uid)] = [str(t).strip() for t in treats if str(t).strip()]
            elif isinstance(treats, str) and treats.strip():
                fixed_rules[str(uid)] = [treats.strip()]

    guild_ids = data.get("treat_allowed_guild_ids", [])
    fixed_guild_ids: list[str] = []

    if isinstance(guild_ids, list):
        for guild_id in guild_ids:
            guild_id = str(guild_id).strip()
            if guild_id.isdigit() and guild_id not in fixed_guild_ids:
                fixed_guild_ids.append(guild_id)

    facebook_channels = data.get("sega_facebook_channels", {})
    fixed_facebook_channels: dict[str, str] = {}

    if isinstance(facebook_channels, dict):
        for channel_id, guild_id in facebook_channels.items():
            channel_id_text = str(channel_id).strip()
            guild_id_text = str(guild_id).strip()

            if guild_id_text.isdigit() and channel_id_text.isdigit():
                fixed_facebook_channels[channel_id_text] = guild_id_text

    seen_post_ids = data.get("sega_facebook_seen_post_ids", {})
    fixed_seen_post_ids: dict[str, str] = {}

    if isinstance(seen_post_ids, dict):
        for page_id, post_id in seen_post_ids.items():
            page_id_text = str(page_id).strip()
            post_id_text = str(post_id).strip()

            if page_id_text and post_id_text:
                fixed_seen_post_ids[page_id_text] = post_id_text

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

    return {
        "notreat_rules": fixed_rules,
        "treat_allowed_guild_ids": fixed_guild_ids,
        "sega_facebook_channels": fixed_facebook_channels,
        "sega_facebook_seen_post_ids": fixed_seen_post_ids,
        "random_song_presets": fixed_random_song_presets,
    }


state = load_state()


def save_state() -> None:
    with STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_treats(uid: int) -> list[str]:
    return state.setdefault("notreat_rules", {}).setdefault(str(uid), [])


def add_treat(uid: int, treat: str) -> bool:
    treats = get_treats(uid)

    if treat in treats:
        return False

    treats.append(treat)
    save_state()
    return True


def remove_treat(uid: int, treat: str) -> bool:
    treats = get_treats(uid)

    if treat not in treats:
        return False

    treats.remove(treat)
    save_state()
    return True


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


def get_sega_facebook_channels() -> dict[str, str]:
    channels = state.setdefault("sega_facebook_channels", {})
    return dict(channels)


def set_sega_facebook_channel(guild_id: int, channel_id: int) -> None:
    channels = state.setdefault("sega_facebook_channels", {})
    channels[str(channel_id)] = str(guild_id)
    save_state()


def remove_sega_facebook_channel(channel_id: int) -> bool:
    channels = state.setdefault("sega_facebook_channels", {})
    channel_id_text = str(channel_id)

    if channel_id_text not in channels:
        return False

    del channels[channel_id_text]
    save_state()
    return True


def get_sega_facebook_seen_post_id(page_id: str) -> str | None:
    seen_post_ids = state.setdefault("sega_facebook_seen_post_ids", {})
    value = seen_post_ids.get(page_id)
    return str(value) if value else None


def set_sega_facebook_seen_post_id(page_id: str, post_id: str) -> None:
    seen_post_ids = state.setdefault("sega_facebook_seen_post_ids", {})
    seen_post_ids[page_id] = post_id
    save_state()


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
