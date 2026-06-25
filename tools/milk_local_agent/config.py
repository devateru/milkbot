from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(".env")
        load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    except Exception:
        return


def _get_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    value = env.get(key)
    if value is None:
        return default

    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _get_int(env: Mapping[str, str], key: str, default: int, *, minimum: int = 0) -> int:
    value = env.get(key)
    if not value:
        return default

    try:
        parsed = int(value)
    except ValueError:
        return default

    return max(minimum, parsed)


def _get_str(env: Mapping[str, str], key: str, default: str = "") -> str:
    value = env.get(key)
    if value is None:
        return default

    return value.strip()


@dataclass(frozen=True)
class LocalAgentConfig:
    host: str = "127.0.0.1"
    port: int = 18080
    token: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    ollama_timeout_sec: int = 120
    ollama_max_prompt_chars: int = 12000
    ollama_max_concurrency: int = 1
    context_dir: Path = Path("data/milk_context")
    web_search_enabled: bool = False
    web_search_provider: str = "disabled"
    google_search_api_key: str = ""
    google_search_engine_id: str = ""
    serpapi_api_key: str = ""
    tavily_api_key: str = ""

    @classmethod
    def from_env(cls) -> "LocalAgentConfig":
        load_dotenv_if_available()
        return cls.from_mapping(os.environ)

    @classmethod
    def from_mapping(cls, env: Mapping[str, str]) -> "LocalAgentConfig":
        return cls(
            host=_get_str(env, "MILK_LOCAL_AGENT_HOST", "127.0.0.1"),
            port=_get_int(env, "MILK_LOCAL_AGENT_PORT", 18080, minimum=1),
            token=_get_str(env, "MILK_AGENT_TOKEN"),
            ollama_base_url=_get_str(
                env,
                "OLLAMA_BASE_URL",
                "http://127.0.0.1:11434",
            ).rstrip("/"),
            ollama_model=_get_str(env, "OLLAMA_MODEL"),
            ollama_timeout_sec=_get_int(env, "OLLAMA_TIMEOUT_SEC", 120, minimum=1),
            ollama_max_prompt_chars=_get_int(
                env,
                "OLLAMA_MAX_PROMPT_CHARS",
                12000,
                minimum=1000,
            ),
            ollama_max_concurrency=_get_int(
                env,
                "OLLAMA_MAX_CONCURRENCY",
                1,
                minimum=1,
            ),
            context_dir=Path(_get_str(env, "MILK_CONTEXT_DIR", "data/milk_context")),
            web_search_enabled=_get_bool(env, "WEB_SEARCH_ENABLED", False),
            web_search_provider=_get_str(env, "WEB_SEARCH_PROVIDER", "disabled"),
            google_search_api_key=_get_str(env, "GOOGLE_SEARCH_API_KEY"),
            google_search_engine_id=_get_str(env, "GOOGLE_SEARCH_ENGINE_ID"),
            serpapi_api_key=_get_str(env, "SERPAPI_API_KEY"),
            tavily_api_key=_get_str(env, "TAVILY_API_KEY"),
        )
