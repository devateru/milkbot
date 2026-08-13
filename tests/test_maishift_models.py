from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
import unittest

from maishift.models import MaishiftSnapshot, snapshot_fingerprint
from tests.test_maishift_repository import sample_snapshot


class MaishiftSnapshotModelTests(unittest.TestCase):
    def test_old_json_without_created_or_updated_at_remains_readable(self) -> None:
        snapshot = sample_snapshot()
        data = snapshot.to_dict()
        data.pop("created_at")
        data.pop("updated_at")
        restored = MaishiftSnapshot.from_json(json.dumps(data))
        self.assertEqual(restored.created_at, restored.last_update_datetime)
        self.assertIsNone(restored.updated_at)

    def test_fingerprint_ignores_timestamp_and_http_independent_metadata(self) -> None:
        snapshot = sample_snapshot()
        timestamp_only = replace(
            snapshot,
            last_update_raw="later",
            last_update_datetime=snapshot.last_update_datetime + timedelta(minutes=1),
            checked_at=snapshot.checked_at + timedelta(minutes=1),
        )
        self.assertEqual(
            snapshot_fingerprint(snapshot),
            snapshot_fingerprint(timestamp_only),
        )

    def test_fingerprint_changes_for_achievement_and_order(self) -> None:
        snapshot = sample_snapshot()
        achievement = replace(
            snapshot,
            new_best=(
                replace(snapshot.new_best[0], achievement=Decimal("100.0001")),
            ),
        )
        self.assertNotEqual(
            snapshot_fingerprint(snapshot),
            snapshot_fingerprint(achievement),
        )
        second = replace(
            snapshot.new_best[0],
            stable_key="chart:2",
            chart_id=2,
            title="두 번째 곡",
        )
        ordered = replace(snapshot, new_best=(snapshot.new_best[0], second))
        reversed_order = replace(snapshot, new_best=(second, snapshot.new_best[0]))
        self.assertNotEqual(
            snapshot_fingerprint(ordered),
            snapshot_fingerprint(reversed_order),
        )
