from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
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

    async def fetch(self, *args, **kwargs):
        self.fetch_calls += 1
        return self.result


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, **kwargs):
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
        await tracker.poll_once()
        stored = self.repo.get_profile("shiftpsh").snapshot
        self.assertEqual(stored.last_update_datetime, before.last_update_datetime)
