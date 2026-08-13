from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from maishift.client import FetchResult, FetchStatus
from maishift.tracker import MaishiftTracker, make_update_id
from maishift.repository import MaishiftRepository
from tests.test_maishift_repository import sample_snapshot


class FakeHttpClient:
    def __init__(self, result: FetchResult):
        self.result = result
        self.fetch_calls = 0
        self.fetch_kwargs = []

    async def fetch(self, *args, **kwargs):
        self.fetch_calls += 1
        self.fetch_kwargs.append(kwargs)
        return self.result


class FakeChannel:
    def __init__(self, *, failures: int = 0):
        self.sent = []
        self.failures = failures

    async def send(self, **kwargs):
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary Discord failure")
        self.sent.append(kwargs)


class FakeBot:
    def __init__(self, channels):
        self.channels = channels

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)

    async def fetch_channel(self, channel_id):
        return self.channels[channel_id]


class MaishiftTrackerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = MaishiftRepository(Path(self.temp.name) / "state.sqlite3")

    async def asyncTearDown(self):
        self.repo.close()
        self.temp.cleanup()

    async def test_unique_profile_fetch_fans_out_once_and_does_not_repeat(self) -> None:
        before = sample_snapshot()
        for channel_id in (10, 20):
            self.repo.add_subscription(
                before,
                guild_id=1,
                channel_id=channel_id,
                created_by=3,
                etag=None,
                last_modified=None,
                baseline_update_id=make_update_id(before),
            )
        improved = replace(before.new_best[0], rating=301)
        after = replace(
            before,
            total_rating=301,
            play_count=2,
            last_update_raw="new",
            last_update_datetime=before.last_update_datetime + timedelta(minutes=1),
            new_best=(improved,),
        )
        http = FakeHttpClient(FetchResult(FetchStatus.VALID_PUBLIC, snapshot=after))
        channels = {10: FakeChannel(), 20: FakeChannel()}
        tracker = MaishiftTracker(FakeBot(channels), self.repo, http)

        await tracker.poll_once()
        self.assertEqual(http.fetch_calls, 1)
        self.assertEqual(http.fetch_kwargs, [{}])
        self.assertEqual(len(channels[10].sent), 1)
        self.assertEqual(len(channels[20].sent), 1)
        self.assertEqual(self.repo.get_profile("shiftpsh").snapshot.total_rating, 301)

        await tracker.poll_once()
        self.assertEqual(http.fetch_calls, 2)
        self.assertEqual(len(channels[10].sent), 1)
        self.assertEqual(len(channels[20].sent), 1)

    async def test_rollback_does_not_replace_baseline(self) -> None:
        before = sample_snapshot()
        self.repo.add_subscription(
            before, guild_id=1, channel_id=10, created_by=3, etag=None, last_modified=None
        )
        rollback = replace(
            before,
            last_update_raw="older",
            last_update_datetime=before.last_update_datetime - timedelta(days=1),
        )
        tracker = MaishiftTracker(
            FakeBot({10: FakeChannel()}),
            self.repo,
            FakeHttpClient(FetchResult(FetchStatus.VALID_PUBLIC, snapshot=rollback)),
        )
        with self.assertLogs("maishift.tracker", level="WARNING"):
            await tracker.poll_once()
        stored = self.repo.get_profile("shiftpsh").snapshot
        self.assertEqual(stored.last_update_datetime, before.last_update_datetime)

    async def _track_change(self, after, *, channel=None, align_timestamp=True):
        before = sample_snapshot()
        if align_timestamp:
            before = replace(
                before,
                last_update_raw=after.last_update_raw,
                last_update_datetime=after.last_update_datetime,
                created_at=after.created_at,
                updated_at=after.updated_at,
            )
        self.repo.add_subscription(
            before,
            guild_id=1,
            channel_id=10,
            created_by=3,
            etag='"stale"',
            last_modified="stale",
        )
        target = channel or FakeChannel()
        http = FakeHttpClient(FetchResult(FetchStatus.VALID_PUBLIC, snapshot=after))
        tracker = MaishiftTracker(FakeBot({10: target}), self.repo, http)
        await tracker.poll_once()
        return tracker, http, target

    async def test_same_timestamp_achievement_only_change_notifies(self) -> None:
        before = sample_snapshot()
        improved = replace(
            before.new_best[0], achievement=Decimal("100.0200")
        )
        after = replace(before, new_best=(improved,))
        _, _, channel = await self._track_change(after)
        self.assertEqual(len(channel.sent), 1)
        field_values = "\n".join(
            field["value"] for field in channel.sent[0]["embeds"][0].to_dict()["fields"]
        )
        self.assertIn("+0.0200%", field_values)
        self.assertIn("300 → 300 (+0)", field_values)

    async def test_same_timestamp_rating_change_notifies(self) -> None:
        before = sample_snapshot()
        changed = replace(before.new_best[0], rating=301)
        after = replace(before, total_rating=301, new_best=(changed,))
        _, _, channel = await self._track_change(after)
        self.assertEqual(len(channel.sent), 1)

    async def test_same_timestamp_play_count_change_notifies(self) -> None:
        before = sample_snapshot()
        after = replace(before, play_count=5)
        _, _, channel = await self._track_change(after)
        self.assertEqual(len(channel.sent), 1)
        fields = channel.sent[0]["embeds"][0].to_dict()["fields"]
        self.assertTrue(any(field["name"] == "BEST 50" for field in fields))

    async def test_timestamp_only_change_does_not_notify(self) -> None:
        before = sample_snapshot()
        after = replace(
            before,
            last_update_raw="new timestamp",
            last_update_datetime=before.last_update_datetime + timedelta(minutes=1),
        )
        _, _, channel = await self._track_change(after, align_timestamp=False)
        self.assertEqual(channel.sent, [])
        self.assertEqual(
            self.repo.get_profile("shiftpsh").snapshot.last_update_raw,
            "new timestamp",
        )

    async def test_older_timestamp_with_valid_content_change_still_notifies(self) -> None:
        before = sample_snapshot()
        after = replace(
            before,
            play_count=2,
            last_update_raw="older but changed",
            last_update_datetime=before.last_update_datetime - timedelta(days=1),
        )
        with self.assertLogs("maishift.tracker", level="WARNING"):
            _, _, channel = await self._track_change(after, align_timestamp=False)
        self.assertEqual(len(channel.sent), 1)
        self.assertEqual(self.repo.get_profile("shiftpsh").snapshot.play_count, 2)

    async def test_update_id_changes_for_achievement_only(self) -> None:
        before = sample_snapshot()
        after = replace(
            before,
            new_best=(
                replace(before.new_best[0], achievement=Decimal("100.0001")),
            ),
        )
        self.assertNotEqual(make_update_id(before), make_update_id(after))

    async def test_failed_delivery_retries_then_stays_sent(self) -> None:
        before = sample_snapshot()
        after = replace(before, play_count=2)
        channel = FakeChannel(failures=1)
        with self.assertLogs("maishift.tracker", level="ERROR"):
            tracker, _, channel = await self._track_change(after, channel=channel)
        update_id = make_update_id(after)
        self.assertEqual(self.repo.delivery_status(update_id, 10), ("failed", 1))
        await tracker.retry_failed_deliveries(
            now=datetime.now(timezone.utc) + timedelta(minutes=5)
        )
        self.assertEqual(self.repo.delivery_status(update_id, 10), ("sent", 2))
        self.assertEqual(len(channel.sent), 1)
        await tracker.retry_failed_deliveries(
            now=datetime.now(timezone.utc) + timedelta(minutes=10)
        )
        self.assertEqual(len(channel.sent), 1)

    async def test_manual_resync_updates_baseline_without_channel_send(self) -> None:
        before = sample_snapshot()
        self.repo.add_subscription(
            before,
            guild_id=1,
            channel_id=10,
            created_by=3,
            etag='"old"',
            last_modified="old",
        )
        after = replace(
            before,
            total_rating=400,
            new_best=(replace(before.new_best[0], rating=400),),
        )
        channel = FakeChannel()
        tracker = MaishiftTracker(
            FakeBot({10: channel}),
            self.repo,
            FakeHttpClient(FetchResult(FetchStatus.VALID_PUBLIC, snapshot=after)),
        )
        result = await tracker.manual_resync()
        self.assertEqual(result.success_count, 1)
        self.assertEqual(self.repo.get_profile("shiftpsh").snapshot.total_rating, 400)
        self.assertEqual(self.repo.subscription_count(), 1)
        self.assertEqual(channel.sent, [])
