from __future__ import annotations

from typing import Any

from .config import LocalAgentConfig


class OllamaUnavailable(Exception):
    pass


class OllamaClient:
    def __init__(self, config: LocalAgentConfig) -> None:
        self.config = config

    async def health(self) -> dict[str, Any]:
        if not self.config.ollama_model:
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
                        return {
                            "ok": False,
                            "ollama_ok": False,
                            "error": f"ollama_http_{response.status}",
                        }

                    data = await response.json(content_type=None)
        except Exception as exc:
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
        try:
            import aiohttp

            timeout = aiohttp.ClientTimeout(total=self.config.ollama_timeout_sec)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.config.ollama_base_url}/api/chat",
                    json=payload,
                ) as response:
                    if response.status != 200:
                        raise OllamaUnavailable(f"ollama HTTP {response.status}")

                    data = await response.json(content_type=None)
        except OllamaUnavailable:
            raise
        except Exception as exc:
            raise OllamaUnavailable(str(exc)) from exc

        if not isinstance(data, dict):
            raise OllamaUnavailable("invalid ollama response")

        return data
