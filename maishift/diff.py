from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import MaishiftBestEntry, MaishiftSnapshot


@dataclass(frozen=True, slots=True)
class EntryChange:
    old: MaishiftBestEntry
    new: MaishiftBestEntry
    section: str
    achievement_delta: Decimal
    rating_delta: int

    @property
    def rating_only(self) -> bool:
        return self.old.achievement == self.new.achievement and self.old.rating != self.new.rating


@dataclass(frozen=True, slots=True)
class SectionMigration:
    entry: MaishiftBestEntry
    from_section: str
    to_section: str


@dataclass(frozen=True, slots=True)
class SectionDiff:
    name: str
    rating_before: int
    rating_after: int
    added: tuple[MaishiftBestEntry, ...]
    removed: tuple[MaishiftBestEntry, ...]
    changes: tuple[EntryChange, ...]

    @property
    def rating_delta(self) -> int:
        return self.rating_after - self.rating_before


@dataclass(frozen=True, slots=True)
class MaishiftDiff:
    total_rating_before: int
    total_rating_after: int
    play_count_before: int
    play_count_after: int
    new_section: SectionDiff
    old_section: SectionDiff
    section_migrations: tuple[SectionMigration, ...]
    metadata_changes: tuple[tuple[str, str | None, str | None], ...]

    @property
    def total_rating_delta(self) -> int:
        return self.total_rating_after - self.total_rating_before

    @property
    def play_count_delta(self) -> int:
        return self.play_count_after - self.play_count_before

    @property
    def b50_changed(self) -> bool:
        return bool(
            self.new_section.added
            or self.new_section.removed
            or self.new_section.changes
            or self.old_section.added
            or self.old_section.removed
            or self.old_section.changes
            or self.section_migrations
        )

    @property
    def has_changes(self) -> bool:
        return bool(
            self.total_rating_delta
            or self.play_count_delta
            or self.b50_changed
            or self.metadata_changes
        )


def _entry_changed(old: MaishiftBestEntry, new: MaishiftBestEntry) -> bool:
    return (
        old.achievement != new.achievement
        or old.rating != new.rating
        or old.grade != new.grade
    )


def diff_snapshots(old: MaishiftSnapshot, new: MaishiftSnapshot) -> MaishiftDiff:
    old_sections = {"new": old.new_best, "old": old.old_best}
    new_sections = {"new": new.new_best, "old": new.old_best}
    old_location = {
        entry.stable_key: section
        for section, entries in old_sections.items()
        for entry in entries
    }
    new_location = {
        entry.stable_key: section
        for section, entries in new_sections.items()
        for entry in entries
    }
    old_all = {
        entry.stable_key: entry
        for entries in old_sections.values()
        for entry in entries
    }
    new_all = {
        entry.stable_key: entry
        for entries in new_sections.values()
        for entry in entries
    }
    migration_keys = {
        key for key in old_all.keys() & new_all.keys()
        if old_location[key] != new_location[key]
    }
    migrations = tuple(
        SectionMigration(
            entry=new_all[key],
            from_section=old_location[key],
            to_section=new_location[key],
        )
        for key in sorted(migration_keys)
    )

    section_diffs: dict[str, SectionDiff] = {}
    for section in ("new", "old"):
        old_map = {entry.stable_key: entry for entry in old_sections[section]}
        new_map = {entry.stable_key: entry for entry in new_sections[section]}
        added_keys = new_map.keys() - old_map.keys() - migration_keys
        removed_keys = old_map.keys() - new_map.keys() - migration_keys
        common_changes = [
            EntryChange(
                old=old_map[key],
                new=new_map[key],
                section=section,
                achievement_delta=new_map[key].achievement - old_map[key].achievement,
                rating_delta=new_map[key].rating - old_map[key].rating,
            )
            for key in sorted(old_map.keys() & new_map.keys())
            if _entry_changed(old_map[key], new_map[key])
        ]
        migration_changes = [
            EntryChange(
                old=old_all[key],
                new=new_all[key],
                section=section,
                achievement_delta=new_all[key].achievement - old_all[key].achievement,
                rating_delta=new_all[key].rating - old_all[key].rating,
            )
            for key in sorted(migration_keys)
            if new_location[key] == section and _entry_changed(old_all[key], new_all[key])
        ]
        changes = tuple(common_changes + migration_changes)
        section_diffs[section] = SectionDiff(
            name=section,
            rating_before=sum(entry.rating for entry in old_sections[section]),
            rating_after=sum(entry.rating for entry in new_sections[section]),
            added=tuple(new_map[key] for key in sorted(added_keys)),
            removed=tuple(old_map[key] for key in sorted(removed_keys)),
            changes=changes,
        )

    metadata_changes: list[tuple[str, str | None, str | None]] = []
    if old.game_version != new.game_version:
        metadata_changes.append(("game_version", old.game_version, new.game_version))
    if old.player_name != new.player_name:
        metadata_changes.append(("player_name", old.player_name, new.player_name))
    if old.secondary_play_count != new.secondary_play_count:
        metadata_changes.append(
            (
                "secondary_play_count",
                str(old.secondary_play_count) if old.secondary_play_count is not None else None,
                str(new.secondary_play_count) if new.secondary_play_count is not None else None,
            )
        )
    return MaishiftDiff(
        total_rating_before=old.total_rating,
        total_rating_after=new.total_rating,
        play_count_before=old.play_count,
        play_count_after=new.play_count,
        new_section=section_diffs["new"],
        old_section=section_diffs["old"],
        section_migrations=migrations,
        metadata_changes=tuple(metadata_changes),
    )
