from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import json
import unicodedata
from typing import Any


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFC", value.strip())


@dataclass(frozen=True, slots=True)
class MaishiftBestEntry:
    stable_key: str
    chart_id: int | None
    title: str
    chart_type: str
    difficulty: str
    difficulty_label: str
    achievement: Decimal
    grade: str
    rating: int
    image_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stable_key": self.stable_key,
            "chart_id": self.chart_id,
            "title": self.title,
            "chart_type": self.chart_type,
            "difficulty": self.difficulty,
            "difficulty_label": self.difficulty_label,
            "achievement": str(self.achievement),
            "grade": self.grade,
            "rating": self.rating,
            "image_url": self.image_url,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MaishiftBestEntry":
        return cls(
            stable_key=str(data["stable_key"]),
            chart_id=int(data["chart_id"]) if data.get("chart_id") is not None else None,
            title=str(data["title"]),
            chart_type=str(data["chart_type"]),
            difficulty=str(data["difficulty"]),
            difficulty_label=str(data["difficulty_label"]),
            achievement=Decimal(str(data["achievement"])),
            grade=str(data["grade"]),
            rating=int(data["rating"]),
            image_url=str(data["image_url"]) if data.get("image_url") else None,
        )


@dataclass(frozen=True, slots=True)
class MaishiftSnapshot:
    profile_key: str
    profile_name: str
    profile_url: str
    player_name: str
    total_rating: int
    play_count: int
    secondary_play_count: int | None
    last_update_raw: str
    last_update_datetime: datetime | None
    game_version: str | None
    new_best: tuple[MaishiftBestEntry, ...]
    old_best: tuple[MaishiftBestEntry, ...]
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def source_last_update(self) -> str:
        if self.last_update_datetime is not None:
            return self.last_update_datetime.isoformat()
        return self.last_update_raw

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_key": self.profile_key,
            "profile_name": self.profile_name,
            "profile_url": self.profile_url,
            "player_name": self.player_name,
            "total_rating": self.total_rating,
            "play_count": self.play_count,
            "secondary_play_count": self.secondary_play_count,
            "last_update_raw": self.last_update_raw,
            "last_update_datetime": (
                self.last_update_datetime.isoformat()
                if self.last_update_datetime is not None
                else None
            ),
            "game_version": self.game_version,
            "new_best": [entry.to_dict() for entry in self.new_best],
            "old_best": [entry.to_dict() for entry in self.old_best],
            "checked_at": self.checked_at.isoformat(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MaishiftSnapshot":
        last_update = data.get("last_update_datetime")
        checked_at = data.get("checked_at")
        return cls(
            profile_key=str(data["profile_key"]),
            profile_name=str(data["profile_name"]),
            profile_url=str(data["profile_url"]),
            player_name=str(data["player_name"]),
            total_rating=int(data["total_rating"]),
            play_count=int(data["play_count"]),
            secondary_play_count=(
                int(data["secondary_play_count"])
                if data.get("secondary_play_count") is not None
                else None
            ),
            last_update_raw=str(data["last_update_raw"]),
            last_update_datetime=datetime.fromisoformat(str(last_update)) if last_update else None,
            game_version=str(data["game_version"]) if data.get("game_version") else None,
            new_best=tuple(MaishiftBestEntry.from_dict(item) for item in data["new_best"]),
            old_best=tuple(MaishiftBestEntry.from_dict(item) for item in data["old_best"]),
            checked_at=datetime.fromisoformat(str(checked_at)) if checked_at else datetime.now(timezone.utc),
        )

    @classmethod
    def from_json(cls, value: str) -> "MaishiftSnapshot":
        return cls.from_dict(json.loads(value))
