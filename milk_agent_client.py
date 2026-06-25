from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode


UNAVAILABLE_MESSAGE = "zzz (ollama 비활성화)"
DEFAULT_TRIGGER_PREFIX = "밀크짱"
DEFAULT_EMPTY_REQUEST_MESSAGE = "무엇을 도와줄까?"
DISCORD_MESSAGE_CHUNK_SIZE = 1900

logger = logging.getLogger(__name__)


class MilkAgentUnavailable(Exception):
    """Raised when the local milk agent cannot be used."""


def _parse_id_set(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()

    return frozenset(part.strip() for part in value.split(",") if part.strip())


def _parse_float(value: str | None, default: float) -> float:
    if not value:
        return default

    try:
        return float(value)
    except ValueError:
        return default


def _parse_int(value: str | None, default: int) -> int:
    if not value:
        return default

    try:
        parsed = int(value)
    except ValueError:
        return default

    return max(0, parsed)


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default

    return value.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class MilkAgentConfig:
    trigger_prefix: str = DEFAULT_TRIGGER_PREFIX
    base_url: str = "http://127.0.0.1:18080"
    timeout_sec: float = 150
    token: str = ""
    max_messages_after_last_context: int = 100
    include_bot_messages_in_context: bool = True
    allowed_channel_ids: frozenset[str] = field(default_factory=frozenset)
    allowed_role_ids: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_env(cls) -> "MilkAgentConfig":
        return cls(
            trigger_prefix=os.getenv("MILK_TRIGGER_PREFIX", DEFAULT_TRIGGER_PREFIX),
            base_url=os.getenv(
                "MILK_AGENT_BASE_URL",
                "http://127.0.0.1:18080",
            ).rstrip("/"),
            timeout_sec=_parse_float(os.getenv("MILK_AGENT_TIMEOUT_SEC"), 150),
            token=os.getenv("MILK_AGENT_TOKEN", ""),
            max_messages_after_last_context=_parse_int(
                os.getenv("MILK_MAX_MESSAGES_AFTER_LAST_CONTEXT"),
                100,
            ),
            include_bot_messages_in_context=_parse_bool(
                os.getenv("MILK_INCLUDE_BOT_MESSAGES_IN_CONTEXT"),
                True,
            ),
            allowed_channel_ids=_parse_id_set(os.getenv("ALLOWED_CHANNEL_IDS")),
            allowed_role_ids=_parse_id_set(os.getenv("ALLOWED_ROLE_IDS")),
        )


def extract_user_request(content: str, trigger_prefix: str) -> str | None:
    if not content.startswith(trigger_prefix):
        return None

    return content[len(trigger_prefix):].strip()


def split_discord_message(
    text: str,
    max_length: int = DISCORD_MESSAGE_CHUNK_SIZE,
) -> list[str]:
    if not text:
        return []

    chunks: list[str] = []
    remaining = text

    while len(remaining) > max_length:
        split_at = remaining.rfind("\n", 0, max_length + 1)
        if split_at <= 0:
            split_at = max_length

        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()

    if remaining:
        chunks.append(remaining)

    return chunks


def _message_id(message: Any) -> str:
    return str(getattr(message, "id", ""))


def _message_content(message: Any) -> str:
    return str(getattr(message, "content", "") or "")


def _message_attachments(message: Any) -> list[Any]:
    attachments = getattr(message, "attachments", []) or []
    return list(attachments)


def is_history_message_usable(
    message: Any,
    *,
    current_message_id: str | None = None,
    include_bot_messages: bool = True,
    excluded_author_ids: set[str] | None = None,
) -> bool:
    if current_message_id is not None and _message_id(message) == str(current_message_id):
        return False

    author = getattr(message, "author", None)
    author_id = str(getattr(author, "id", ""))
    if excluded_author_ids and author_id in excluded_author_ids:
        return False

    if bool(getattr(author, "bot", False)) and not include_bot_messages:
        return False

    content = _message_content(message).strip()
    attachments = _message_attachments(message)
    return bool(content or attachments)


def select_history_messages(
    messages: list[Any],
    *,
    current_message_id: str | None = None,
    include_bot_messages: bool = True,
    excluded_author_ids: set[str] | None = None,
    limit: int = 100,
) -> list[Any]:
    usable = [
        message
        for message in messages
        if is_history_message_usable(
            message,
            current_message_id=current_message_id,
            include_bot_messages=include_bot_messages,
            excluded_author_ids=excluded_author_ids,
        )
    ]

    if limit <= 0:
        return []

    return usable[-limit:]


def _attachment_payload(attachment: Any) -> dict[str, str]:
    return {
        "filename": str(getattr(attachment, "filename", "")),
        "url": str(getattr(attachment, "url", "")),
    }


def _author_display_name(author: Any) -> str:
    return str(
        getattr(author, "display_name", None)
        or getattr(author, "name", None)
        or author
    )


def build_message_payload(message: Any) -> dict[str, Any]:
    author = getattr(message, "author", None)
    created_at = getattr(message, "created_at", None)
    created_at_text = created_at.isoformat() if created_at is not None else ""

    return {
        "id": _message_id(message),
        "created_at": created_at_text,
        "author_id": str(getattr(author, "id", "")),
        "author_display_name": _author_display_name(author),
        "author_is_bot": bool(getattr(author, "bot", False)),
        "content": _message_content(message),
        "attachments": [
            _attachment_payload(attachment)
            for attachment in _message_attachments(message)
        ],
    }


def build_current_message_payload(message: Any, user_request: str) -> dict[str, Any]:
    payload = build_message_payload(message)
    payload["content"] = user_request
    payload["raw_content"] = _message_content(message)
    return payload


def is_message_authorized(message: Any, config: MilkAgentConfig) -> bool:
    channel_id = str(getattr(getattr(message, "channel", None), "id", ""))
    if config.allowed_channel_ids and channel_id not in config.allowed_channel_ids:
        return False

    if not config.allowed_role_ids:
        return True

    roles = getattr(getattr(message, "author", None), "roles", []) or []
    role_ids = {str(getattr(role, "id", "")) for role in roles}
    return bool(config.allowed_role_ids & role_ids)


def _allowed_mentions_none() -> Any:
    try:
        import discord

        return discord.AllowedMentions.none()
    except Exception:
        return None


async def send_text(channel: Any, content: str) -> None:
    await channel.send(content, allowed_mentions=_allowed_mentions_none())


async def send_discord_chunks(channel: Any, content: str) -> None:
    for chunk in split_discord_message(content):
        await send_text(channel, chunk)


class MilkAgentHttpClient:
    def __init__(self, config: MilkAgentConfig) -> None:
        self.config = config

    def _headers(self) -> dict[str, str]:
        if not self.config.token:
            return {}

        return {"Authorization": f"Bearer {self.config.token}"}

    def _url(self, path: str, params: dict[str, str] | None = None) -> str:
        url = f"{self.config.base_url}{path}"
        if not params:
            return url

        return f"{url}?{urlencode(params)}"

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            import aiohttp

            timeout = aiohttp.ClientTimeout(total=self.config.timeout_sec)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                request = session.get if method == "GET" else session.post
                kwargs: dict[str, Any] = {"headers": self._headers()}
                if method != "GET":
                    kwargs["json"] = json_payload

                async with request(self._url(path, params), **kwargs) as response:
                    if response.status != 200:
                        raise MilkAgentUnavailable(f"agent returned HTTP {response.status}")

                    data = await response.json(content_type=None)
        except MilkAgentUnavailable:
            raise
        except Exception as exc:
            raise MilkAgentUnavailable(str(exc)) from exc

        if not isinstance(data, dict) or data.get("ok") is not True:
            raise MilkAgentUnavailable("agent returned ok:false")

        return data

    async def check_health(self) -> None:
        data = await self._request_json("GET", "/health")
        if data.get("ollama_ok") is not True:
            raise MilkAgentUnavailable("ollama is not healthy")

    async def fetch_state(self, channel_id: str) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            "/state",
            params={"channel_id": channel_id},
        )

    async def chat(self, payload: dict[str, Any]) -> str:
        data = await self._request_json("POST", "/chat", json_payload=payload)
        answer = data.get("answer")

        if not isinstance(answer, str) or not answer.strip():
            raise MilkAgentUnavailable("agent returned an empty answer")

        return answer.strip()


class MilkAgentMessageHandler:
    def __init__(
        self,
        config: MilkAgentConfig,
        *,
        http_client: MilkAgentHttpClient | None = None,
    ) -> None:
        self.config = config
        self.http_client = http_client or MilkAgentHttpClient(config)
        self._semaphore = asyncio.Semaphore(1)

    async def handle_message(self, message: Any) -> bool:
        author = getattr(message, "author", None)
        if bool(getattr(author, "bot", False)):
            return False

        raw_content = _message_content(message)
        user_request = extract_user_request(raw_content, self.config.trigger_prefix)
        if user_request is None:
            return False

        if not is_message_authorized(message, self.config):
            return True

        if not user_request:
            await send_text(getattr(message, "channel"), DEFAULT_EMPTY_REQUEST_MESSAGE)
            return True

        async with self._semaphore:
            try:
                typing_context = getattr(message.channel, "typing")()
                async with typing_context:
                    answer = await self._ask_agent(message, user_request)
            except MilkAgentUnavailable:
                logger.info("milk local agent is unavailable")
                await send_text(message.channel, UNAVAILABLE_MESSAGE)
                return True
            except Exception:
                logger.exception("milk local agent request failed")
                await send_text(message.channel, UNAVAILABLE_MESSAGE)
                return True

        await send_discord_chunks(message.channel, answer)
        return True

    async def _ask_agent(self, message: Any, user_request: str) -> str:
        channel_id = str(getattr(message.channel, "id", ""))

        await self.http_client.check_health()
        state = await self.http_client.fetch_state(channel_id)
        last_processed_message_id = state.get("last_processed_message_id")
        history_payloads: list[dict[str, Any]] = []

        if last_processed_message_id:
            history_messages = await collect_messages_since_last_context(
                message,
                str(last_processed_message_id),
                self.config.max_messages_after_last_context,
                include_bot_messages=self.config.include_bot_messages_in_context,
            )
            history_payloads = [
                build_message_payload(history_message)
                for history_message in history_messages
            ]

        payload = build_agent_chat_payload(
            message,
            user_request,
            history_payloads,
        )
        return await self.http_client.chat(payload)


async def collect_messages_since_last_context(
    current_message: Any,
    last_processed_message_id: str,
    limit: int,
    *,
    include_bot_messages: bool = True,
) -> list[Any]:
    if limit <= 0:
        return []

    try:
        import discord

        after = discord.Object(id=int(last_processed_message_id))
    except Exception as exc:
        raise MilkAgentUnavailable("invalid last_processed_message_id") from exc

    messages: list[Any] = []
    async for history_message in current_message.channel.history(
        limit=limit,
        after=after,
        before=current_message,
        oldest_first=False,
    ):
        messages.append(history_message)

    selected = select_history_messages(
        list(reversed(messages)),
        current_message_id=_message_id(current_message),
        include_bot_messages=include_bot_messages,
        excluded_author_ids=_self_author_ids(current_message),
        limit=limit,
    )
    return selected


def _self_author_ids(message: Any) -> set[str]:
    guild = getattr(message, "guild", None)
    guild_me = getattr(guild, "me", None)
    author_id = str(getattr(guild_me, "id", "") or "")
    return {author_id} if author_id else set()


def build_agent_chat_payload(
    message: Any,
    user_request: str,
    history_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    guild = getattr(message, "guild", None)
    channel = getattr(message, "channel", None)

    return {
        "channel": {
            "id": str(getattr(channel, "id", "")),
            "name": str(getattr(channel, "name", "")),
        },
        "guild": {
            "id": str(getattr(guild, "id", "")) if guild is not None else "",
            "name": str(getattr(guild, "name", "")) if guild is not None else "",
        },
        "current_message": build_current_message_payload(message, user_request),
        "messages_since_last_context": history_payloads,
    }
