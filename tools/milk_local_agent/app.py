from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .config import LocalAgentConfig
from .context_store import (
    ContextStore,
    build_channel_context_entry,
    compact_channel_context_deterministically,
)
from .ollama_client import OllamaClient, OllamaUnavailable
from .prompting import (
    build_system_prompt,
    build_user_prompt,
    select_relevant_messages,
    should_use_web_search,
)
from .web_search import (
    DisabledSearchProvider,
    SearchProvider,
    build_search_provider,
    format_search_results,
)


MAX_CHANNEL_CONTEXT_CHARS = 24000
logger = logging.getLogger(__name__)


class MilkLocalAgent:
    def __init__(
        self,
        config: LocalAgentConfig,
        *,
        context_store: ContextStore | None = None,
        ollama_client: OllamaClient | None = None,
        search_provider: SearchProvider | None = None,
    ) -> None:
        self.config = config
        self.context_store = context_store or ContextStore(config.context_dir)
        self.ollama_client = ollama_client or OllamaClient(config)
        self.search_provider = search_provider or build_search_provider(config)
        self.ollama_semaphore = asyncio.Semaphore(config.ollama_max_concurrency)
        self.context_lock = asyncio.Lock()
        self._health_cache: tuple[float, int, dict[str, Any]] | None = None

    def is_authorized(self, authorization_header: str | None) -> bool:
        if not self.config.token:
            return True

        return authorization_header == f"Bearer {self.config.token}"

    async def health(self) -> tuple[int, dict[str, Any]]:
        started = time.perf_counter()
        cached = self._get_cached_health()
        if cached is not None:
            status, body = cached
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "milk local agent health completed elapsed_ms=%.1f status=%s cache_hit=true",
                elapsed_ms,
                status,
            )
            return status, body

        async with self.ollama_semaphore:
            result = await self.ollama_client.health()
        status = 200 if result.get("ok") is True else 503
        self._health_cache = (time.monotonic(), status, dict(result))
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "milk local agent health completed elapsed_ms=%.1f status=%s cache_hit=false",
            elapsed_ms,
            status,
        )
        return status, result

    def _get_cached_health(self) -> tuple[int, dict[str, Any]] | None:
        if self.config.ollama_health_cache_ttl_sec <= 0 or self._health_cache is None:
            return None

        cached_at, status, body = self._health_cache
        age = time.monotonic() - cached_at
        if age > self.config.ollama_health_cache_ttl_sec:
            return None

        cached_body = dict(body)
        cached_body["health_cache_hit"] = True
        return status, cached_body

    async def state(self, channel_id: str) -> dict[str, Any]:
        started = time.perf_counter()
        self.context_store.ensure_files()
        result = self.context_store.load_recent_state(channel_id)
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "milk local agent state completed elapsed_ms=%.1f channel_id=%s has_recent_context=%s",
            elapsed_ms,
            channel_id,
            result.get("has_recent_context"),
        )
        return result

    async def chat(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        started = time.perf_counter()
        status = 500
        ollama_call_counter = {"api_chat": 0}
        messages_received = 0
        relevant_count = 0
        prompt_chars = 0
        system_prompt_chars = 0
        updated_context = False

        health_status, health_body = await self.health()
        if health_status != 200:
            status = 503
            body = {
                "ok": False,
                "error": health_body.get("error", "ollama_unavailable"),
            }
            self._log_chat_complete(
                started,
                status=status,
                ollama_chat_calls=ollama_call_counter["api_chat"],
                messages_received=messages_received,
                relevant_count=relevant_count,
                prompt_chars=prompt_chars,
                system_prompt_chars=system_prompt_chars,
                updated_context=updated_context,
            )
            return status, body

        context = self.context_store.load_context()
        current_message = payload.get("current_message", {})
        request_text = str(current_message.get("content") or "").strip()
        if not request_text:
            status = 400
            body = {"ok": False, "error": "empty_request"}
            self._log_chat_complete(
                started,
                status=status,
                ollama_chat_calls=ollama_call_counter["api_chat"],
                messages_received=messages_received,
                relevant_count=relevant_count,
                prompt_chars=prompt_chars,
                system_prompt_chars=system_prompt_chars,
                updated_context=updated_context,
            )
            return status, body

        messages = payload.get("messages_since_last_context", [])
        if not isinstance(messages, list):
            messages = []
        messages_received = len(messages)

        if self.config.enable_llm_relevance_filter:
            logger.info(
                "MILK_ENABLE_LLM_RELEVANCE_FILTER=true requested; using heuristic relevance filter to avoid extra default LLM calls"
            )
        relevant_messages = select_relevant_messages(
            request_text,
            messages,
            max_messages=self.config.max_related_messages,
        )
        relevant_count = len(relevant_messages)
        web_search_text = await self._maybe_search(request_text)
        system_prompt = build_system_prompt(context["character"])
        user_prompt = build_user_prompt(
            request_text=request_text,
            character_text=context["character"],
            knowledge_text=context["knowledge"],
            channel_context_text=context["channel_context"],
            recent_context_text=context["recent_context"],
            relevant_messages=relevant_messages,
            web_search_text=web_search_text,
            max_chars=self.config.ollama_max_prompt_chars,
        )
        prompt_chars = len(user_prompt)
        system_prompt_chars = len(system_prompt)

        try:
            async with self.ollama_semaphore:
                ollama_call_counter["api_chat"] += 1
                answer = await self.ollama_client.chat(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
        except OllamaUnavailable:
            logger.exception("ollama chat failed")
            status = 503
            body = {"ok": False, "error": "ollama_unavailable"}
            self._log_chat_complete(
                started,
                status=status,
                ollama_chat_calls=ollama_call_counter["api_chat"],
                messages_received=messages_received,
                relevant_count=relevant_count,
                prompt_chars=prompt_chars,
                system_prompt_chars=system_prompt_chars,
                updated_context=updated_context,
            )
            return status, body

        try:
            await self._update_context(
                payload,
                answer,
                relevant_messages,
                ollama_chat_calls_ref=ollama_call_counter,
            )
            updated_context = True
        except Exception:
            logger.exception("context update failed")
            updated_context = False

        status = 200
        body = {
            "ok": True,
            "answer": answer,
            "updated_context": updated_context,
        }
        self._log_chat_complete(
            started,
            status=status,
            ollama_chat_calls=ollama_call_counter["api_chat"],
            messages_received=messages_received,
            relevant_count=relevant_count,
            prompt_chars=prompt_chars,
            system_prompt_chars=system_prompt_chars,
            updated_context=updated_context,
        )
        return status, body

    def _log_chat_complete(
        self,
        started: float,
        *,
        status: int,
        ollama_chat_calls: int,
        messages_received: int,
        relevant_count: int,
        prompt_chars: int,
        system_prompt_chars: int,
        updated_context: bool,
    ) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "milk local agent chat completed elapsed_ms=%.1f status=%s ollama_chat_calls=%s messages_received=%s relevant_messages=%s user_prompt_chars=%s system_prompt_chars=%s updated_context=%s",
            elapsed_ms,
            status,
            ollama_chat_calls,
            messages_received,
            relevant_count,
            prompt_chars,
            system_prompt_chars,
            updated_context,
        )

    async def _maybe_search(self, request_text: str) -> str:
        if not should_use_web_search(request_text):
            return ""

        if isinstance(self.search_provider, DisabledSearchProvider):
            if self.config.web_search_enabled:
                return "검색 후보로 판단했지만 검색 provider/API key가 설정되지 않아 검색하지 못했습니다."
            return ""

        try:
            results = await self.search_provider.search(request_text, limit=5)
        except Exception:
            logger.exception("web search failed")
            return "검색을 시도했지만 실패했습니다."

        return format_search_results(results)

    async def _update_context(
        self,
        payload: dict[str, Any],
        answer: str,
        relevant_messages: list[dict[str, Any]],
        ollama_chat_calls_ref: dict[str, int] | None = None,
    ) -> None:
        async with self.context_lock:
            context = self.context_store.load_context()
            entry = build_channel_context_entry(payload, answer, relevant_messages)
            next_channel_context = context["channel_context"].rstrip() + "\n" + entry + "\n"

            if len(next_channel_context) > MAX_CHANNEL_CONTEXT_CHARS:
                if self.config.enable_llm_context_summary:
                    try:
                        async with self.ollama_semaphore:
                            if ollama_chat_calls_ref is not None:
                                ollama_chat_calls_ref["api_chat"] += 1
                            next_channel_context = await self.ollama_client.summarize_context(
                                next_channel_context,
                            )
                    except Exception:
                        logger.exception("channel context compression failed")
                        next_channel_context = compact_channel_context_deterministically(
                            next_channel_context,
                            max_chars=MAX_CHANNEL_CONTEXT_CHARS,
                        )
                else:
                    logger.info(
                        "channel context compacted deterministically without extra Ollama call"
                    )
                    next_channel_context = compact_channel_context_deterministically(
                        next_channel_context,
                        max_chars=MAX_CHANNEL_CONTEXT_CHARS,
                    )

            self.context_store.save_successful_chat(
                payload,
                answer,
                relevant_messages,
                channel_context_text=next_channel_context,
            )


def create_app(config: LocalAgentConfig | None = None) -> Any:
    from aiohttp import web

    logging.basicConfig(level=logging.INFO)
    agent = MilkLocalAgent(config or LocalAgentConfig.from_env())

    def log_endpoint(path: str, started: float, status: int) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "milk local agent endpoint completed path=%s elapsed_ms=%.1f status=%s",
            path,
            elapsed_ms,
            status,
        )

    def unauthorized_response() -> web.Response:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

    def is_request_authorized(request: web.Request) -> bool:
        if agent.is_authorized(request.headers.get("Authorization")):
            return True

        return False

    async def health_handler(request: web.Request) -> web.Response:
        started = time.perf_counter()
        if not is_request_authorized(request):
            response = unauthorized_response()
            log_endpoint("/health", started, response.status)
            return response

        status, body = await agent.health()
        response = web.json_response(body, status=status)
        log_endpoint("/health", started, response.status)
        return response

    async def state_handler(request: web.Request) -> web.Response:
        started = time.perf_counter()
        if not is_request_authorized(request):
            response = unauthorized_response()
            log_endpoint("/state", started, response.status)
            return response

        channel_id = request.query.get("channel_id", "").strip()
        if not channel_id:
            response = web.json_response(
                {"ok": False, "error": "missing_channel_id"},
                status=400,
            )
            log_endpoint("/state", started, response.status)
            return response

        response = web.json_response(await agent.state(channel_id))
        log_endpoint("/state", started, response.status)
        return response

    async def chat_handler(request: web.Request) -> web.Response:
        started = time.perf_counter()
        if not is_request_authorized(request):
            response = unauthorized_response()
            log_endpoint("/chat", started, response.status)
            return response

        try:
            payload = await request.json()
        except Exception:
            response = web.json_response({"ok": False, "error": "invalid_json"}, status=400)
            log_endpoint("/chat", started, response.status)
            return response

        if not isinstance(payload, dict):
            response = web.json_response({"ok": False, "error": "invalid_payload"}, status=400)
            log_endpoint("/chat", started, response.status)
            return response

        status, body = await agent.chat(payload)
        response = web.json_response(body, status=status)
        log_endpoint("/chat", started, response.status)
        return response

    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/state", state_handler)
    app.router.add_post("/chat", chat_handler)
    return app


def main() -> None:
    from aiohttp import web

    config = LocalAgentConfig.from_env()
    app = create_app(config)
    web.run_app(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
