from __future__ import annotations

import asyncio
import hashlib
import logging

import discord

from .client import FetchStatus, MaishiftClient
from .diff import diff_snapshots
from .embeds import build_maishift_update_embeds
from .models import MaishiftSnapshot
from .repository import MaishiftRepository, ProfileRecord, Subscription


logger = logging.getLogger(__name__)


def make_update_id(snapshot: MaishiftSnapshot) -> str:
    material = "\0".join(
        (
            snapshot.profile_key,
            snapshot.source_last_update,
            str(snapshot.total_rating),
            str(snapshot.play_count),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class MaishiftTracker:
    def __init__(
        self,
        bot: discord.Client,
        repository: MaishiftRepository,
        http_client: MaishiftClient,
        *,
        interval: float = 60.0,
    ) -> None:
        self.bot = bot
        self.repository = repository
        self.http_client = http_client
        self.interval = interval
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        await self.http_client.start()
        self._stopping.clear()
        self._task = asyncio.create_task(self._run(), name="maishift-tracker")
        logger.info(
            "maishift tracker started: %d unique profiles",
            len(self.repository.tracked_profiles()),
        )

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.http_client.close()

    async def _run(self) -> None:
        try:
            while not self._stopping.is_set():
                try:
                    await self.poll_once()
                except Exception:
                    logger.exception("maishift polling iteration failed")
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=self.interval)
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise

    async def poll_once(self) -> None:
        profiles = self.repository.tracked_profiles()
        if not profiles:
            return
        await asyncio.gather(*(self._poll_profile(profile) for profile in profiles))

    async def _poll_profile(self, profile: ProfileRecord) -> None:
        try:
            result = await self.http_client.fetch(
                profile.profile_name,
                etag=profile.etag,
                last_modified=profile.last_modified,
            )
            if result.status == FetchStatus.NOT_MODIFIED:
                self.repository.record_checked(
                    profile.profile_key, etag=result.etag, last_modified=result.last_modified
                )
                return
            if result.status != FetchStatus.VALID_PUBLIC or result.snapshot is None:
                self.repository.record_failure(profile.profile_key, retry_after=result.retry_after)
                if result.error == "HTTP 429":
                    logger.warning("maishift request rate limited: %s", profile.profile_name)
                else:
                    logger.warning(
                        "maishift profile check failed: %s (%s)",
                        profile.profile_name,
                        result.error or result.status.value,
                    )
                return
            current = result.snapshot
            previous = profile.snapshot
            if current.source_last_update == previous.source_last_update:
                self.repository.record_checked(
                    profile.profile_key, etag=result.etag, last_modified=result.last_modified
                )
                return
            if (
                previous.last_update_datetime is not None
                and current.last_update_datetime is not None
                and current.last_update_datetime < previous.last_update_datetime
            ):
                logger.warning("maishift snapshot rollback detected: %s", profile.profile_name)
                self.repository.record_rollback(profile.profile_key, current)
                return
            diff = diff_snapshots(previous, current)
            if (
                diff.new_section.rating_delta + diff.old_section.rating_delta
                != diff.total_rating_delta
            ):
                logger.warning(
                    "maishift rating invariant mismatch: %s sections=%+d total=%+d",
                    profile.profile_name,
                    diff.new_section.rating_delta + diff.old_section.rating_delta,
                    diff.total_rating_delta,
                )
            logger.info(
                "maishift update detected: %s rating %d -> %d",
                profile.profile_name,
                previous.total_rating,
                current.total_rating,
            )
            update_id = make_update_id(current)
            embeds = build_maishift_update_embeds(diff, current)
            subscriptions = self.repository.subscriptions_for_profile(profile.profile_key)
            await asyncio.gather(
                *(self._deliver(subscription, update_id, embeds) for subscription in subscriptions)
            )
            self.repository.save_snapshot(
                current, etag=result.etag, last_modified=result.last_modified
            )
        except Exception:
            logger.exception("maishift profile polling failed: %s", profile.profile_name)
            self.repository.record_failure(profile.profile_key)

    async def _deliver(
        self,
        subscription: Subscription,
        update_id: str,
        embeds: list[discord.Embed],
    ) -> None:
        if not self.repository.claim_delivery(
            update_id, subscription.channel_id, subscription.profile_key
        ):
            return
        try:
            channel = self.bot.get_channel(subscription.channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(subscription.channel_id)
            if not hasattr(channel, "send"):
                raise TypeError("tracked channel is not messageable")
            await channel.send(embeds=embeds, allowed_mentions=discord.AllowedMentions.none())
        except discord.NotFound:
            self.repository.remove_channel(subscription.channel_id)
            self.repository.finish_delivery(update_id, subscription.channel_id, "channel_missing")
            logger.warning("removed maishift subscriptions for missing channel: %d", subscription.channel_id)
        except discord.Forbidden:
            self.repository.finish_delivery(update_id, subscription.channel_id, "forbidden")
            logger.warning("maishift delivery forbidden: channel=%d", subscription.channel_id)
        except Exception:
            self.repository.finish_delivery(update_id, subscription.channel_id, "failed")
            logger.exception("maishift delivery failed: channel=%d", subscription.channel_id)
        else:
            self.repository.finish_delivery(update_id, subscription.channel_id, "sent")
