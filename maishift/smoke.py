from __future__ import annotations

import argparse
import asyncio

from .client import FetchStatus, MaishiftClient
from .models import snapshot_fingerprint


async def _run(profile_name: str) -> int:
    client = MaishiftClient()
    try:
        result = await client.fetch(profile_name)
    finally:
        await client.close()
    if result.status != FetchStatus.VALID_PUBLIC or result.snapshot is None:
        print(f"FAILED status={result.status.value} error={result.error}")
        return 1
    snapshot = result.snapshot
    print(f"profile={snapshot.profile_name}")
    print(f"player={snapshot.player_name}")
    print(f"rating={snapshot.total_rating}")
    print(f"play_count={snapshot.play_count}")
    print(f"secondary_play_count={snapshot.secondary_play_count}")
    print(f"created_at={snapshot.created_at.isoformat() if snapshot.created_at else None}")
    print(f"updated_at={snapshot.updated_at.isoformat() if snapshot.updated_at else None}")
    print(f"source_last_update={snapshot.source_last_update}")
    print(f"game_version={snapshot.game_version}")
    print(f"new_best={len(snapshot.new_best)}")
    print(f"old_best={len(snapshot.old_best)}")
    new_rating = sum(entry.rating for entry in snapshot.new_best)
    old_rating = sum(entry.rating for entry in snapshot.old_best)
    print(f"new_rating_sum={new_rating}")
    print(f"old_rating_sum={old_rating}")
    print(f"rating_sum={new_rating + old_rating}")
    print(f"fingerprint={snapshot_fingerprint(snapshot)}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only live maishift parser smoke test")
    parser.add_argument("profile", nargs="?", default="shiftpsh")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.profile)))


if __name__ == "__main__":
    main()
