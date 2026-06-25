from __future__ import annotations

import asyncio
import logging
from typing import Any

from .config import LocalAgentConfig
from .context_store import ContextStore, build_channel_context_entry
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

    def is_authorized(self, authorization_header: str | None) -> bool:
        if not self.config.token:
            return True

        return authorization_header == f"Bearer {self.config.token}"

    async def health(self) -> tuple[int, dict[str, Any]]:
        async with self.ollama_semaphore:
            result = await self.ollama_client.health()
        status = 200 if result.get("ok") is True else 503
        return status, result

    async def state(self, channel_id: str) -> dict[str, Any]:
        self.context_store.ensure_files()
        return self.context_store.load_recent_state(channel_id)

    async def chat(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        health_status, health_body = await self.health()
        if health_status != 200:
            return 503, {
                "ok": False,
                "error": health_body.get("error", "ollama_unavailable"),
            }

        context = self.context_store.load_context()
        current_message = payload.get("current_message", {})
        request_text = str(current_message.get("content") or "").strip()
        if not request_text:
            return 400, {"ok": False, "error": "empty_request"}

        messages = payload.get("messages_since_last_context", [])
        if not isinstance(messages, list):
            messages = []

        relevant_messages = select_relevant_messages(request_text, messages)
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

        try:
            async with self.ollama_semaphore:
                answer = await self.ollama_client.chat(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
        except OllamaUnavailable:
            logger.exception("ollama chat failed")
            return 503, {"ok": False, "error": "ollama_unavailable"}

        try:
            await self._update_context(payload, answer, relevant_messages)
            updated_context = True
        except Exception:
            logger.exception("context update failed")
            updated_context = False

        return 200, {
            "ok": True,
            "answer": answer,
            "updated_context": updated_context,
        }

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
    ) -> None:
        async with self.context_lock:
            context = self.context_store.load_context()
            entry = build_channel_context_entry(payload, answer, relevant_messages)
            next_channel_context = context["channel_context"].rstrip() + "\n" + entry + "\n"

            if len(next_channel_context) > MAX_CHANNEL_CONTEXT_CHARS:
                try:
                    async with self.ollama_semaphore:
                        next_channel_context = await self.ollama_client.summarize_context(
                            next_channel_context,
                        )
                except Exception:
                    logger.exception("channel context compression failed")
                    next_channel_context = (
                        "# channel context\n"
                        "이전 context가 길어져 최근 요약 일부만 유지합니다.\n\n"
                        + next_channel_context[-MAX_CHANNEL_CONTEXT_CHARS:]
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

    def unauthorized_response() -> web.Response:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

    def is_request_authorized(request: web.Request) -> bool:
        if agent.is_authorized(request.headers.get("Authorization")):
            return True

        return False

    async def health_handler(request: web.Request) -> web.Response:
        if not is_request_authorized(request):
            return unauthorized_response()

        status, body = await agent.health()
        return web.json_response(body, status=status)

    async def state_handler(request: web.Request) -> web.Response:
        if not is_request_authorized(request):
            return unauthorized_response()

        channel_id = request.query.get("channel_id", "").strip()
        if not channel_id:
            return web.json_response(
                {"ok": False, "error": "missing_channel_id"},
                status=400,
            )

        return web.json_response(await agent.state(channel_id))

    async def chat_handler(request: web.Request) -> web.Response:
        if not is_request_authorized(request):
            return unauthorized_response()

        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)

        if not isinstance(payload, dict):
            return web.json_response({"ok": False, "error": "invalid_payload"}, status=400)

        status, body = await agent.chat(payload)
        return web.json_response(body, status=status)

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
