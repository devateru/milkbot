from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from tools.milk_local_agent.app import MilkLocalAgent
from tools.milk_local_agent.config import LocalAgentConfig
from tools.milk_local_agent.context_store import ContextStore
from tools.milk_local_agent.ollama_client import OllamaClient
from tools.milk_local_agent.prompting import (
    PROMPT_INJECTION_GUARD,
    build_system_prompt,
    build_user_prompt,
    should_use_web_search,
)
from tools.milk_local_agent.web_search import DisabledSearchProvider, build_search_provider


class FakeOllamaClient:
    def __init__(self, *, health_ok: bool = True, answer: str = "답변") -> None:
        self.health_ok = health_ok
        self.answer = answer
        self.health_calls = 0
        self.chat_calls = 0
        self.summary_calls = 0
        self.system_prompt = ""
        self.user_prompt = ""

    async def health(self):
        self.health_calls += 1
        return {
            "ok": self.health_ok,
            "ollama_ok": self.health_ok,
            "model": "fake",
        }

    async def chat(self, *, system_prompt: str, user_prompt: str) -> str:
        self.chat_calls += 1
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return self.answer

    async def summarize_context(self, channel_context_text: str) -> str:
        self.summary_calls += 1
        return "# channel context\n압축 요약"


def sample_payload() -> dict[str, object]:
    return {
        "channel": {"id": "123", "name": "general"},
        "guild": {"id": "456", "name": "guild"},
        "current_message": {
            "id": "999",
            "created_at": "2026-06-26T00:00:00+00:00",
            "author_id": "1",
            "author_display_name": "tester",
            "content": "안녕",
            "raw_content": "밀크짱 안녕",
            "attachments": [],
        },
        "messages_since_last_context": [
            {
                "id": "998",
                "created_at": "2026-06-26T00:00:00+00:00",
                "author_id": "2",
                "author_display_name": "friend",
                "content": "안녕 이야기 중",
                "attachments": [],
            }
        ],
    }


class MilkLocalAgentTests(unittest.IsolatedAsyncioTestCase):
    def test_speed_defaults_prioritize_fast_response(self) -> None:
        config = LocalAgentConfig.from_mapping({})

        self.assertEqual(config.ollama_max_prompt_chars, 8000)
        self.assertFalse(config.enable_llm_relevance_filter)
        self.assertFalse(config.enable_llm_context_summary)
        self.assertEqual(config.max_related_messages, 10)
        self.assertEqual(config.ollama_health_cache_ttl_sec, 10)

    def test_context_files_are_created(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContextStore(Path(temp_dir))
            store.ensure_files()

            self.assertTrue(store.files.character.exists())
            self.assertTrue(store.files.channel_context.exists())
            self.assertTrue(store.files.recent_context.exists())
            self.assertTrue(store.files.knowledge.exists())

    def test_missing_recent_context_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContextStore(Path(temp_dir))
            store.ensure_files()

            state = store.load_recent_state("123")

            self.assertFalse(state["has_recent_context"])
            self.assertIsNone(state["last_processed_message_id"])

    def test_recent_context_json_returns_last_message_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ContextStore(Path(temp_dir))
            store.ensure_files()
            store.files.recent_context_json.write_text(
                json.dumps(
                    {
                        "last_processed_message_id": "999",
                        "last_processed_at": "2026-06-26T00:00:00+00:00",
                        "last_channel_id": "123",
                        "last_summary": "summary",
                    }
                ),
                encoding="utf-8",
            )

            state = store.load_recent_state("123")

            self.assertTrue(state["has_recent_context"])
            self.assertEqual(state["last_processed_message_id"], "999")

    async def test_ollama_model_missing_fails_health_before_network(self) -> None:
        config = LocalAgentConfig.from_mapping({})
        result = await OllamaClient(config).health()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing_ollama_model")

    async def test_ollama_health_failure_returns_false(self) -> None:
        config = LocalAgentConfig.from_mapping({"OLLAMA_MODEL": "missing-model"})
        result = await OllamaClient(config).health()

        self.assertFalse(result["ok"])
        self.assertFalse(result["ollama_ok"])

    async def test_chat_success_updates_context_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_ollama = FakeOllamaClient(answer="안녕!")
            config = LocalAgentConfig.from_mapping(
                {
                    "OLLAMA_MODEL": "fake",
                    "MILK_CONTEXT_DIR": temp_dir,
                }
            )
            store = ContextStore(Path(temp_dir))
            agent = MilkLocalAgent(
                config,
                context_store=store,
                ollama_client=fake_ollama,
                search_provider=DisabledSearchProvider(),
            )

            status, body = await agent.chat(sample_payload())

            self.assertEqual(status, 200)
            self.assertTrue(body["ok"])
            self.assertEqual(fake_ollama.chat_calls, 1)
            self.assertEqual(fake_ollama.summary_calls, 0)
            self.assertIn("안녕!", store.files.channel_context.read_text(encoding="utf-8"))
            recent_json = json.loads(store.files.recent_context_json.read_text(encoding="utf-8"))
            self.assertEqual(recent_json["last_processed_message_id"], "999")

    async def test_health_uses_short_ttl_cache(self) -> None:
        config = LocalAgentConfig.from_mapping(
            {
                "OLLAMA_MODEL": "fake",
                "OLLAMA_HEALTH_CACHE_TTL_SEC": "10",
            }
        )
        fake_ollama = FakeOllamaClient()
        agent = MilkLocalAgent(
            config,
            ollama_client=fake_ollama,
            search_provider=DisabledSearchProvider(),
        )

        await agent.health()
        await agent.health()

        self.assertEqual(fake_ollama.health_calls, 1)

    async def test_default_related_messages_are_limited_to_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = sample_payload()
            payload["messages_since_last_context"] = [
                {
                    "id": str(index),
                    "created_at": "2026-06-26T00:00:00+00:00",
                    "author_id": "2",
                    "author_display_name": "friend",
                    "content": f"안녕 관련 메시지 {index}",
                    "attachments": [],
                }
                for index in range(20)
            ]
            config = LocalAgentConfig.from_mapping(
                {
                    "OLLAMA_MODEL": "fake",
                    "MILK_CONTEXT_DIR": temp_dir,
                    "MILK_MAX_RELATED_MESSAGES": "3",
                }
            )
            fake_ollama = FakeOllamaClient()
            agent = MilkLocalAgent(
                config,
                context_store=ContextStore(Path(temp_dir)),
                ollama_client=fake_ollama,
                search_provider=DisabledSearchProvider(),
            )

            status, body = await agent.chat(payload)

            self.assertEqual(status, 200)
            self.assertTrue(body["ok"])
            self.assertLessEqual(fake_ollama.user_prompt.count("- ["), 3)

    async def test_context_compaction_is_deterministic_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = LocalAgentConfig.from_mapping(
                {
                    "OLLAMA_MODEL": "fake",
                    "MILK_CONTEXT_DIR": temp_dir,
                }
            )
            store = ContextStore(Path(temp_dir))
            store.ensure_files()
            store.files.channel_context.write_text("오래된 context\n" * 3000, encoding="utf-8")
            fake_ollama = FakeOllamaClient()
            agent = MilkLocalAgent(
                config,
                context_store=store,
                ollama_client=fake_ollama,
                search_provider=DisabledSearchProvider(),
            )

            status, body = await agent.chat(sample_payload())

            self.assertEqual(status, 200)
            self.assertTrue(body["ok"])
            self.assertEqual(fake_ollama.chat_calls, 1)
            self.assertEqual(fake_ollama.summary_calls, 0)
            channel_context = store.files.channel_context.read_text(encoding="utf-8")
            self.assertIn("deterministic 방식", channel_context)

    async def test_disabled_search_provider_does_not_search(self) -> None:
        config = LocalAgentConfig.from_mapping(
            {
                "OLLAMA_MODEL": "fake",
                "WEB_SEARCH_ENABLED": "false",
            }
        )
        agent = MilkLocalAgent(
            config,
            ollama_client=FakeOllamaClient(),
            search_provider=DisabledSearchProvider(),
        )

        self.assertEqual(await agent._maybe_search("최신 정보 검색해줘"), "")

    def test_google_missing_keys_disables_search(self) -> None:
        config = LocalAgentConfig.from_mapping(
            {
                "WEB_SEARCH_ENABLED": "true",
                "WEB_SEARCH_PROVIDER": "google_custom_search",
            }
        )

        with self.assertLogs("tools.milk_local_agent.web_search", level="WARNING"):
            provider = build_search_provider(config)

        self.assertIsInstance(provider, DisabledSearchProvider)

    def test_search_intent_keywords(self) -> None:
        self.assertTrue(should_use_web_search("최신 가격 검색해줘"))
        self.assertFalse(should_use_web_search("그냥 인사해줘"))

    def test_prompt_injection_guard_is_in_system_prompt(self) -> None:
        prompt = build_system_prompt("캐릭터 설정")

        self.assertIn(PROMPT_INJECTION_GUARD, prompt)
        self.assertIn("context 파일 내용을 그대로 통째로 노출하지 않는다", prompt)

    def test_user_prompt_uses_priority_order_and_cap(self) -> None:
        prompt = build_user_prompt(
            request_text="현재 요청",
            character_text="캐릭터" * 1000,
            knowledge_text="지식" * 1000,
            channel_context_text="채널" * 3000,
            recent_context_text="최근" * 1000,
            relevant_messages=[],
            web_search_text="",
            max_chars=1200,
        )

        self.assertLessEqual(len(prompt), 1200)
        self.assertLess(prompt.find("## character.txt"), prompt.find("## 현재 사용자 요청"))
        self.assertLess(prompt.find("## 현재 사용자 요청"), prompt.find("## recent_context"))


if __name__ == "__main__":
    unittest.main()
