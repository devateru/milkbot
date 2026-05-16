import json
from pathlib import Path
from typing import Any


STATE_FILE = Path("milkbot_state.json")


def default_state() -> dict[str, Any]:
    return {
        "notreat_rules": {},
        "treat_allowed_guild_ids": [],
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

    return {
        "notreat_rules": fixed_rules,
        "treat_allowed_guild_ids": fixed_guild_ids,
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
