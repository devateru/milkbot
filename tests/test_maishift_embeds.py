from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
import unittest

from maishift.diff import diff_snapshots
from maishift.embeds import INDENT, build_maishift_update_embeds
from maishift.sample import build_maishift_test_embeds
from tests.test_maishift_diff import entry, snapshot


def _with_display(entry_value, *, chart_type="DX", level="14.1"):
    return replace(
        entry_value,
        chart_type=chart_type,
        difficulty_label=level,
    )


def _field_value(embed, name: str) -> str:
    fields = embed.to_dict()["fields"]
    return next(field["value"] for field in fields if field["name"] == name)


def _embed_text(embed) -> str:
    return json.dumps(embed.to_dict(), ensure_ascii=False)


class MaishiftEmbedTests(unittest.TestCase):
    def test_single_out_and_in_are_rendered_as_one_replacement(self) -> None:
        removed = _with_display(
            entry("chart:1", "Neon Kingdom", 310, "100.5674"), level="13.8"
        )
        added = _with_display(
            entry("chart:2", "Don't Fight The Music", 317, "100.5384")
        )
        before = snapshot(old=[removed])
        after = snapshot(old=[added])

        value = _field_value(
            build_maishift_update_embeds(diff_snapshots(before, after), after)[0],
            "구곡 BEST",
        )

        self.assertIn(f"{INDENT}[310] **Neon Kingdom** (DX, 13.8) 100.5674%", value)
        self.assertNotIn("   [310]", value)
        self.assertIn(
            "→ [317] **Don't Fight The Music** (DX, 14.1) 100.5384% **(+7)**",
            value,
        )
        self.assertTrue(
            any(line.startswith("→ [317]") for line in value.splitlines())
        )
        self.assertIn("섹션 레이팅 변화: **+7**", value)
        self.assertNotIn("IN **Don't Fight The Music**", value)
        self.assertNotIn("OUT **Neon Kingdom**", value)

    def test_same_chart_update_is_compact_and_hides_grade(self) -> None:
        before_entry = _with_display(
            entry("chart:1", "Don't Fight The Music", 307, "99.1384", "SS+")
        )
        after_entry = replace(
            before_entry,
            rating=317,
            achievement=before_entry.achievement + Decimal("1.4000"),
            grade="SSS+",
        )
        before = snapshot(old=[before_entry])
        after = snapshot(old=[after_entry])

        value = _field_value(
            build_maishift_update_embeds(diff_snapshots(before, after), after)[0],
            "구곡 BEST",
        )

        self.assertIn(
            "[307 → 317] **Don't Fight The Music** (DX, 14.1) · Rating +10",
            value,
        )
        self.assertIn("99.1384% → 100.5384% (+1.4000%)", value)
        self.assertNotIn("SS+ → SSS+", value)

    def test_replacement_delta_supports_zero_and_negative_values(self) -> None:
        for added_rating, expected in ((310, "+0"), (307, "-3")):
            with self.subTest(added_rating=added_rating):
                removed = _with_display(entry("chart:1", "Removed", 310))
                added = _with_display(entry("chart:2", "Added", added_rating))
                before = snapshot(old=[removed])
                after = snapshot(old=[added])
                value = _field_value(
                    build_maishift_update_embeds(
                        diff_snapshots(before, after), after
                    )[0],
                    "구곡 BEST",
                )
                self.assertIn(f"**({expected})**", value)

    def test_achievement_only_change_keeps_rating_zero_visible(self) -> None:
        before_entry = _with_display(
            entry("chart:1", "Achievement Only", 317, "100.5000")
        )
        after_entry = replace(
            before_entry,
            achievement=before_entry.achievement + Decimal("0.0200"),
        )
        before = snapshot(new=[before_entry])
        after = snapshot(new=[after_entry])

        value = _field_value(
            build_maishift_update_embeds(diff_snapshots(before, after), after)[0],
            "신곡 BEST",
        )
        self.assertIn("[317 → 317]", value)
        self.assertIn("Rating +0", value)
        self.assertIn("+0.0200%", value)

    def test_rating_only_change_says_achievement_is_unchanged(self) -> None:
        before_entry = _with_display(entry("chart:1", "Constant Change", 317, "100.5384"))
        after_entry = replace(before_entry, rating=320)
        before = snapshot(old=[before_entry])
        after = snapshot(old=[after_entry])

        value = _field_value(
            build_maishift_update_embeds(diff_snapshots(before, after), after)[0],
            "구곡 BEST",
        )
        self.assertIn("[317 → 320]", value)
        self.assertIn("Rating +3", value)
        self.assertIn("100.5384% 유지", value)

    def test_multiple_out_and_in_are_not_arbitrarily_paired(self) -> None:
        removed = [
            _with_display(entry("chart:1", "OUT A", 310, "100.5674"), level="13.8"),
            _with_display(entry("chart:2", "OUT B", 308, "100.4123"), level="13.7+"),
        ]
        added = [
            _with_display(entry("chart:3", "IN A", 317, "100.5384")),
            _with_display(
                entry("chart:4", "IN B", 315, "100.6123"),
                chart_type="STANDARD",
                level="14.0",
            ),
        ]
        before = snapshot(new=removed)
        after = snapshot(new=added)

        value = _field_value(
            build_maishift_update_embeds(diff_snapshots(before, after), after)[0],
            "신곡 BEST",
        )
        self.assertIn("OUT [310] **OUT A**", value)
        self.assertIn("OUT [308] **OUT B**", value)
        self.assertIn("IN  [317] **IN A**", value)
        self.assertIn("IN  [315] **IN B** (STANDARD, 14.0)", value)
        self.assertNotIn("→ [", value)
        self.assertLess(value.index("OUT ["), value.index("IN  ["))

    def test_version_field_and_total_rating_footer_are_not_rendered(self) -> None:
        before = snapshot(new=[entry("chart:1", "Song", 320)], version="week #2")
        after = snapshot(new=[entry("chart:1", "Song", 320)], version="week #3")
        embed = build_maishift_update_embeds(diff_snapshots(before, after), after)[0]
        data = embed.to_dict()
        text = _embed_text(embed)
        self.assertNotIn("게임 버전/레이팅 환경 변경", text)
        self.assertNotIn("총 레이팅 변화", text)
        self.assertNotIn("footer", data)

    def test_play_only_embed_and_discord_limits(self) -> None:
        before = snapshot(new=[entry("chart:1", "AiAe", 320)])
        after = replace(
            before,
            play_count=14,
            last_update_raw="8/12/2026, 2:31:00 PM",
            last_update_datetime=before.last_update_datetime + timedelta(minutes=1),
        )
        embed = build_maishift_update_embeds(diff_snapshots(before, after), after)[0]
        data = embed.to_dict()
        self.assertIn("🎮", data["title"])
        self.assertTrue(any(field["name"] == "BEST 50" for field in data["fields"]))
        self.assertLessEqual(len(data["title"]), 256)
        self.assertLessEqual(len(data.get("description", "")), 4096)
        self.assertLessEqual(len(data["fields"]), 25)
        self.assertTrue(all(len(field["value"]) <= 1024 for field in data["fields"]))

    def test_long_section_value_is_truncated_to_discord_limit(self) -> None:
        removed = [
            _with_display(entry(f"chart:{index}", "긴 곡명" * 100, 300 + index))
            for index in range(1, 5)
        ]
        added = [
            _with_display(entry(f"chart:{index}", "새로운 긴 곡명" * 100, 310 + index))
            for index in range(5, 9)
        ]
        before = snapshot(old=removed)
        after = snapshot(old=added)
        value = _field_value(
            build_maishift_update_embeds(diff_snapshots(before, after), after)[0],
            "구곡 BEST",
        )
        self.assertLessEqual(len(value), 1024)

    def test_developer_sample_covers_update_and_replacement(self) -> None:
        embed = build_maishift_test_embeds()[0]
        value = _field_value(embed, "구곡 BEST")
        self.assertIn("[TEST]", embed.title)
        self.assertIn("[307 → 317] **Test Song A**", value)
        self.assertIn("99.1384% → 100.5384% (+1.4000%)", value)
        self.assertIn(f"{INDENT}[310] **Test Song B** (DX, 13.8) 100.5674%", value)
        self.assertNotIn("   [310]", value)
        self.assertIn("→ [317] **Test Song C** (DX, 14.1) 100.5384% **(+7)**", value)
        self.assertNotIn("SS+ → SSS+", value)
