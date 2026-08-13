from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import logging
import os

from dotenv import load_dotenv

from .client import FetchStatus, MaishiftClient
from .models import snapshot_fingerprint
from .repository import MaishiftRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResyncProfileResult:
    profile_name: str
    success: bool
    before_rating: int | None
    after_rating: int | None
    changed: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ResyncResult:
    profiles: tuple[ResyncProfileResult, ...]
    subscriptions_before: int
    subscriptions_after: int

    @property
    def success_count(self) -> int:
        return sum(item.success for item in self.profiles)

    @property
    def failure_count(self) -> int:
        return len(self.profiles) - self.success_count


async def resync_subscribed_profiles(
    repository: MaishiftRepository,
    client: MaishiftClient,
) -> ResyncResult:
    profiles = repository.all_subscribed_profiles()
    subscriptions_before = repository.subscription_count()
    logger.info("maishift manual resync started: profiles=%d", len(profiles))
    results: list[ResyncProfileResult] = []
    for profile in profiles:
        before_fp = snapshot_fingerprint(profile.snapshot)
        result = await client.fetch(profile.profile_name)  # Always an unconditional GET.
        if result.status != FetchStatus.VALID_PUBLIC or result.snapshot is None:
            error = result.error or result.status.value
            repository.record_failure(profile.profile_key, retry_after=result.retry_after)
            results.append(
                ResyncProfileResult(
                    profile_name=profile.profile_name,
                    success=False,
                    before_rating=profile.snapshot.total_rating,
                    after_rating=None,
                    changed=False,
                    error=error,
                )
            )
            logger.warning("maishift manual resync failed: %s (%s)", profile.profile_name, error)
            continue
        current = result.snapshot
        after_fp = snapshot_fingerprint(current)
        repository.save_snapshot(
            current,
            etag=result.etag,
            last_modified=result.last_modified,
        )
        results.append(
            ResyncProfileResult(
                profile_name=profile.profile_name,
                success=True,
                before_rating=profile.snapshot.total_rating,
                after_rating=current.total_rating,
                changed=before_fp != after_fp,
            )
        )
        logger.info(
            "maishift manual resync profile: %s rating %d -> %d fingerprint %s -> %s",
            profile.profile_name,
            profile.snapshot.total_rating,
            current.total_rating,
            before_fp,
            after_fp,
        )
    subscriptions_after = repository.subscription_count()
    logger.info(
        "maishift manual resync completed: profiles=%d success=%d failed=%d subscriptions=%d",
        len(results),
        sum(item.success for item in results),
        sum(not item.success for item in results),
        subscriptions_after,
    )
    return ResyncResult(tuple(results), subscriptions_before, subscriptions_after)


async def _run_cli(db_path: str) -> int:
    repository = MaishiftRepository(db_path)
    client = MaishiftClient()
    try:
        result = await resync_subscribed_profiles(repository, client)
    finally:
        await client.close()
        repository.close()
    print(f"profiles={len(result.profiles)}")
    print(f"success={result.success_count}")
    print(f"failed={result.failure_count}")
    print(f"subscriptions_before={result.subscriptions_before}")
    print(f"subscriptions_after={result.subscriptions_after}")
    return 0 if result.failure_count == 0 else 1


def main() -> None:
    load_dotenv(".env")
    logging.basicConfig(
        level=os.getenv("MAISHIFT_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Silently refresh maishift baselines")
    parser.add_argument(
        "--db",
        default=os.getenv("MAISHIFT_DB_PATH", "data/maishift.sqlite3"),
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run_cli(args.db)))


if __name__ == "__main__":
    main()
