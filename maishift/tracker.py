from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime

import discord

from .client import FetchStatus, MaishiftClient
from .diff import diff_snapshots
from .embeds import build_maishift_update_embeds
from .models import MaishiftSnapshot, snapshot_fingerprint
from .repository import MaishiftRepository, ProfileRecord, Subscription
from .resync import ResyncResult, resync_subscribed_profiles


logger = logging.getLogger(__name__)


def make_update_id(snapshot: MaishiftSnapshot) -> str:
    material = f"{snapshot.profile_key}:{snapshot_fingerprint(snapshot)}"
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
        self._sync_lock = asyncio.Lock()

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
        async with self._sync_lock:
            await self.retry_failed_deliveries()
            profiles = self.repository.tracked_profiles()
            if not profiles:
                return
            await asyncio.gather(*(self._poll_profile(profile) for profile in profiles))

    async def manual_resync(self) -> ResyncResult:
        async with self._sync_lock:
            return await resync_subscribed_profiles(self.repository, self.http_client)

    async def _poll_profile(self, profile: ProfileRecord) -> None:
        try:
            logger.debug("maishift poll profile: %s", profile.profile_name)
            # Accuracy takes priority over conditional request optimization.
            result = await self.http_client.fetch(profile.profile_name)
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
            previous_fp = snapshot_fingerprint(previous)
            current_fp = snapshot_fingerprint(current)
            if current_fp == previous_fp:
                # Persist newer timestamp metadata without generating a meaningless
                # rating +0 notification.
                if (
                    previous.last_update_datetime is None
                    or current.last_update_datetime is None
                    or current.last_update_datetime >= previous.last_update_datetime
                ):
                    self.repository.save_snapshot(
                        current, etag=result.etag, last_modified=result.last_modified
                    )
                else:
                    logger.warning(
                        "maishift timestamp rollback with unchanged content: %s",
                        profile.profile_name,
                    )
                    self.repository.record_checked(
                        profile.profile_key,
                        etag=result.etag,
                        last_modified=result.last_modified,
                    )
                logger.debug("maishift content unchanged: %s", profile.profile_name)
                return
            if (
                previous.last_update_datetime is not None
                and current.last_update_datetime is not None
                and current.last_update_datetime < previous.last_update_datetime
            ):
                logger.warning(
                    "maishift timestamp rollback with valid content change: %s %s -> %s",
                    profile.profile_name,
                    previous.source_last_update,
                    current.source_last_update,
                )
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
            payload_json = json.dumps(
                [embed.to_dict() for embed in embeds],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            subscriptions = self.repository.subscriptions_for_profile(profile.profile_key)
            await asyncio.gather(
                *(
                    self._deliver(
                        subscription,
                        update_id,
                        embeds,
                        payload_json=payload_json,
                    )
                    for subscription in subscriptions
                )
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
        *,
        payload_json: str,
        retry_now: datetime | None = None,
    ) -> None:
        if not self.repository.claim_delivery(
            update_id,
            subscription.channel_id,
            subscription.profile_key,
            payload_json=payload_json,
            now=retry_now,
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
            self.repository.finish_delivery(
                update_id, subscription.channel_id, "channel_missing", error="Discord NotFound"
            )
            logger.warning("removed maishift subscriptions for missing channel: %d", subscription.channel_id)
        except discord.Forbidden:
            self.repository.finish_delivery(
                update_id, subscription.channel_id, "forbidden", error="Discord Forbidden"
            )
            logger.warning("maishift delivery forbidden: channel=%d", subscription.channel_id)
        except Exception as exc:
            self.repository.finish_delivery(
                update_id,
                subscription.channel_id,
                "failed",
                error=f"{type(exc).__name__}: {exc}"[:1000],
            )
            logger.exception("maishift delivery failed: channel=%d", subscription.channel_id)
        else:
            self.repository.finish_delivery(update_id, subscription.channel_id, "sent")
            logger.info(
                "maishift delivery sent: profile=%s channel=%d",
                subscription.profile_key,
                subscription.channel_id,
            )

    async def retry_failed_deliveries(self, *, now: datetime | None = None) -> None:
        records = self.repository.retryable_deliveries(now=now)
        for record in records:
            subscriptions = {
                item.channel_id: item
                for item in self.repository.subscriptions_for_profile(record.profile_key)
            }
            subscription = subscriptions.get(record.channel_id)
            if subscription is None:
                continue
            try:
                data = json.loads(record.payload_json)
                embeds = [discord.Embed.from_dict(item) for item in data]
            except (TypeError, ValueError, json.JSONDecodeError):
                logger.exception(
                    "maishift delivery payload invalid: update=%s channel=%d",
                    record.update_id,
                    record.channel_id,
                )
                continue
            await self._deliver(
                subscription,
                record.update_id,
                embeds,
                payload_json=record.payload_json,
                retry_now=now,
            )
