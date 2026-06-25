from __future__ import annotations

import logging
import time
from typing import Any

from .config import LocalAgentConfig


logger = logging.getLogger(__name__)


class OllamaUnavailable(Exception):
    pass


class OllamaClient:
    def __init__(self, config: LocalAgentConfig) -> None:
        self.config = config

    async def health(self) -> dict[str, Any]:
        started = time.perf_counter()
        if not self.config.ollama_model:
            logger.info("ollama /api/tags skipped elapsed_ms=0.0 reason=missing_model")
            return {
                "ok": False,
                "ollama_ok": False,
                "error": "missing_ollama_model",
            }

        try:
            import aiohttp

            timeout = aiohttp.ClientTimeout(total=self.config.ollama_timeout_sec)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self.config.ollama_base_url}/api/tags") as response:
                    if response.status != 200:
                        elapsed_ms = (time.perf_counter() - started) * 1000
                        logger.info(
                            "ollama /api/tags completed elapsed_ms=%.1f status=%s",
                            elapsed_ms,
                            response.status,
                        )
                        return {
                            "ok": False,
                            "ollama_ok": False,
                            "error": f"ollama_http_{response.status}",
                        }

                    data = await response.json(content_type=None)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "ollama /api/tags failed elapsed_ms=%.1f error=%s",
                elapsed_ms,
                exc,
            )
            return {
                "ok": False,
                "ollama_ok": False,
                "error": str(exc),
            }

        model_names = {
            str(model.get("name", ""))
            for model in data.get("models", [])
            if isinstance(model, dict)
        }
        model_available = self.config.ollama_model in model_names
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "ollama /api/tags completed elapsed_ms=%.1f status=200 model_available=%s",
            elapsed_ms,
            model_available,
        )

        return {
            "ok": model_available,
            "ollama_ok": model_available,
            "model": self.config.ollama_model,
            "model_available": model_available,
        }

    async def chat(self, *, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.config.ollama_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        data = await self._post_chat(payload)
        message = data.get("message", {})
        content = message.get("content") if isinstance(message, dict) else None

        if not isinstance(content, str) or not content.strip():
            raise OllamaUnavailable("empty ollama response")

        return content.strip()

    async def summarize_context(self, channel_context_text: str) -> str:
        system_prompt = (
            "너는 Discord 채널 장기 context를 압축하는 요약기다. "
            "사실, 관계, 선호, 진행 중인 주제만 남기고 원문 로그는 보관하지 않는다."
        )
        user_prompt = (
            "다음 channel_context.txt를 사람이 읽을 수 있는 장기 context로 압축해라. "
            "중요한 정보는 유지하고 6000자 이내로 작성해라.\n\n"
            + channel_context_text
        )
        return await self.chat(system_prompt=system_prompt, user_prompt=user_prompt)

    async def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        status: int | str = "unknown"
        try:
            import aiohttp

            timeout = aiohttp.ClientTimeout(total=self.config.ollama_timeout_sec)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.config.ollama_base_url}/api/chat",
                    json=payload,
                ) as response:
                    status = response.status
                    if response.status != 200:
                        raise OllamaUnavailable(f"ollama HTTP {response.status}")

                    data = await response.json(content_type=None)
        except OllamaUnavailable:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "ollama /api/chat failed elapsed_ms=%.1f status=%s",
                elapsed_ms,
                status,
            )
            raise
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "ollama /api/chat failed elapsed_ms=%.1f status=%s error=%s",
                elapsed_ms,
                status,
                exc,
            )
            raise OllamaUnavailable(str(exc)) from exc

        elapsed_ms = (time.perf_counter() - started) * 1000
        if not isinstance(data, dict):
            logger.info(
                "ollama /api/chat failed elapsed_ms=%.1f status=%s error=invalid_response",
                elapsed_ms,
                status,
            )
            raise OllamaUnavailable("invalid ollama response")

        logger.info(
            "ollama /api/chat completed elapsed_ms=%.1f status=%s",
            elapsed_ms,
            status,
        )
        return data
