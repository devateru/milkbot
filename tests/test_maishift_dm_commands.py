from __future__ import annotations

import unittest

from dev_commands import handle_developer_dm_command
from maishift.resync import ResyncProfileResult, ResyncResult
from maishift_dm_commands import handle_maishift_developer_dm


class FakeAuthor:
    def __init__(self, user_id: int):
        self.id = user_id


class FakeMessage:
    guild = None

    def __init__(self, content: str, user_id: int):
        self.content = content
        self.author = FakeAuthor(user_id)
        self.replies = []

    async def reply(self, *args, **kwargs):
        self.replies.append((args, kwargs))


class FakeTracker:
    def __init__(self):
        self.calls = 0

    async def manual_resync(self):
        self.calls += 1
        return ResyncResult(
            profiles=(
                ResyncProfileResult("PLAYER", True, 16000, 16100, True),
            ),
            subscriptions_before=1,
            subscriptions_after=1,
        )


class MaishiftDeveloperDmTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_developer_cannot_run_resync(self) -> None:
        message = FakeMessage("마싶동기화", 2)
        tracker = FakeTracker()
        handled = await handle_maishift_developer_dm(message, 1, tracker)
        self.assertFalse(handled)
        self.assertEqual(tracker.calls, 0)
        self.assertEqual(message.replies, [])

    async def test_developer_can_run_resync(self) -> None:
        message = FakeMessage("마싶동기화", 1)
        tracker = FakeTracker()
        handled = await handle_maishift_developer_dm(message, 1, tracker)
        self.assertTrue(handled)
        self.assertEqual(tracker.calls, 1)
        response = "\n".join(args[0] for args, _ in message.replies if args)
        self.assertIn("재동기화 완료", response)
        self.assertIn("구독 관계: 그대로 유지됨", response)
        self.assertIn("일반 채널 알림: 전송하지 않음", response)

    async def test_developer_test_uses_real_update_embed_builder(self) -> None:
        message = FakeMessage("마싶테스트", 1)
        tracker = FakeTracker()
        handled = await handle_maishift_developer_dm(message, 1, tracker)
        self.assertTrue(handled)
        self.assertEqual(tracker.calls, 0)
        embeds = message.replies[0][1]["embeds"]
        self.assertIn("[TEST]", embeds[0].title)
        fields = embeds[0].to_dict()["fields"]
        old_best = next(field["value"] for field in fields if field["name"] == "구곡 BEST")
        self.assertIn("Test Song A", old_best)
        self.assertIn("Test Song B", old_best)
        self.assertIn("Test Song C", old_best)

    async def test_non_developer_cannot_run_test_embed(self) -> None:
        message = FakeMessage("마싶테스트", 2)
        handled = await handle_maishift_developer_dm(message, 1, FakeTracker())
        self.assertFalse(handled)
        self.assertEqual(message.replies, [])

    async def test_existing_developer_commands_still_fall_through(self) -> None:
        message = FakeMessage("!m help", 1)
        tracker = FakeTracker()
        self.assertFalse(await handle_maishift_developer_dm(message, 1, tracker))
        self.assertTrue(await handle_developer_dm_command(message, None, 1))
        self.assertEqual(len(message.replies), 1)
