from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from milk_agent_client import (
    DEFAULT_EMPTY_REQUEST_MESSAGE,
    UNAVAILABLE_MESSAGE,
    MilkAgentConfig,
    MilkAgentMessageHandler,
    MilkAgentUnavailable,
    extract_user_request,
    select_history_messages,
    split_discord_message,
)


class FakeTyping:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeChannel:
    def __init__(self) -> None:
        self.id = 123
        self.name = "general"
        self.sent: list[tuple[str, dict[str, object]]] = []
        self.history_called = False

    def typing(self) -> FakeTyping:
        return FakeTyping()

    async def send(self, content: str, **kwargs: object) -> None:
        self.sent.append((content, kwargs))

    def history(self, **_kwargs: object):
        self.history_called = True
        raise AssertionError("history should not be called")


class FakeHttpClient:
    def __init__(
        self,
        *,
        health_ok: bool = True,
        state: dict[str, object] | None = None,
        answer: str = "ok",
    ) -> None:
        self.health_ok = health_ok
        self.state = state or {"ok": True, "has_recent_context": False}
        self.answer = answer
        self.payload: dict[str, object] | None = None

    async def check_health(self) -> None:
        if not self.health_ok:
            raise MilkAgentUnavailable("down")

    async def fetch_state(self, channel_id: str) -> dict[str, object]:
        self.fetched_channel_id = channel_id
        return self.state

    async def chat(self, payload: dict[str, object]) -> str:
        self.payload = payload
        return self.answer


def fake_message(
    content: str,
    *,
    message_id: int = 999,
    bot: bool = False,
    channel: FakeChannel | None = None,
) -> SimpleNamespace:
    channel = channel or FakeChannel()
    return SimpleNamespace(
        id=message_id,
        content=content,
        created_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
        author=SimpleNamespace(
            id=456,
            display_name="tester",
            name="tester",
            bot=bot,
            roles=[],
        ),
        channel=channel,
        guild=SimpleNamespace(id=789, name="guild"),
        attachments=[],
    )


class MilkAgentClientTests(unittest.IsolatedAsyncioTestCase):
    def test_prefix_detection(self) -> None:
        self.assertEqual(extract_user_request("밀크짱 안녕", "밀크짱"), "안녕")
        self.assertEqual(extract_user_request("밀크짱", "밀크짱"), "")

    def test_middle_prefix_is_ignored(self) -> None:
        self.assertIsNone(extract_user_request("야 밀크짱 안녕", "밀크짱"))

    async def test_bot_message_is_ignored(self) -> None:
        channel = FakeChannel()
        handler = MilkAgentMessageHandler(
            MilkAgentConfig(),
            http_client=FakeHttpClient(),
        )
        handled = await handler.handle_message(
            fake_message("밀크짱 안녕", bot=True, channel=channel),
        )

        self.assertFalse(handled)
        self.assertEqual(channel.sent, [])

    async def test_empty_request_asks_short_question(self) -> None:
        channel = FakeChannel()
        handler = MilkAgentMessageHandler(
            MilkAgentConfig(),
            http_client=FakeHttpClient(),
        )
        handled = await handler.handle_message(fake_message("밀크짱", channel=channel))

        self.assertTrue(handled)
        self.assertEqual(channel.sent[0][0], DEFAULT_EMPTY_REQUEST_MESSAGE)

    async def test_health_failure_returns_exact_unavailable_message(self) -> None:
        channel = FakeChannel()
        handler = MilkAgentMessageHandler(
            MilkAgentConfig(),
            http_client=FakeHttpClient(health_ok=False),
        )
        handled = await handler.handle_message(fake_message("밀크짱 안녕", channel=channel))

        self.assertTrue(handled)
        self.assertEqual(channel.sent[0][0], UNAVAILABLE_MESSAGE)
        self.assertIn("allowed_mentions", channel.sent[0][1])

    async def test_state_without_recent_context_uses_zero_history_messages(self) -> None:
        channel = FakeChannel()
        client = FakeHttpClient(state={"ok": True, "has_recent_context": False})
        handler = MilkAgentMessageHandler(MilkAgentConfig(), http_client=client)

        handled = await handler.handle_message(fake_message("밀크짱 안녕", channel=channel))

        self.assertTrue(handled)
        self.assertFalse(channel.history_called)
        self.assertIsNotNone(client.payload)
        self.assertEqual(client.payload["messages_since_last_context"], [])

    async def test_state_with_last_message_collects_history(self) -> None:
        channel = FakeChannel()
        client = FakeHttpClient(
            state={
                "ok": True,
                "has_recent_context": True,
                "last_processed_message_id": "10",
            }
        )
        handler = MilkAgentMessageHandler(MilkAgentConfig(), http_client=client)
        historical = fake_message("이전 대화", message_id=11)

        async def fake_collect(_message, last_processed_message_id: str, limit: int):
            self.assertEqual(last_processed_message_id, "10")
            self.assertEqual(limit, 100)
            return [historical]

        with patch("milk_agent_client.collect_messages_since_last_context", fake_collect):
            handled = await handler.handle_message(fake_message("밀크짱 이어서", channel=channel))

        self.assertTrue(handled)
        self.assertEqual(
            client.payload["messages_since_last_context"][0]["content"],
            "이전 대화",
        )

    def test_history_message_limit(self) -> None:
        messages = [fake_message(f"m{i}", message_id=i) for i in range(150)]
        selected = select_history_messages(messages, limit=100)

        self.assertEqual(len(selected), 100)
        self.assertEqual(selected[0].content, "m50")
        self.assertEqual(selected[-1].content, "m149")

    def test_chunking_uses_1900_characters(self) -> None:
        chunks = split_discord_message("a" * 4000)

        self.assertEqual([len(chunk) for chunk in chunks], [1900, 1900, 200])

    async def test_allowed_mentions_argument_is_set(self) -> None:
        channel = FakeChannel()
        handler = MilkAgentMessageHandler(
            MilkAgentConfig(),
            http_client=FakeHttpClient(answer="hello"),
        )
        await handler.handle_message(fake_message("밀크짱 안녕", channel=channel))

        self.assertIn("allowed_mentions", channel.sent[0][1])


if __name__ == "__main__":
    unittest.main()
