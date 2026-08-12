from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
import asyncio
import logging
from urllib.parse import quote

import aiohttp

from .models import MaishiftSnapshot, normalize_text
from .parser import (
    MaishiftInvalidOrPrivateError,
    MaishiftParseError,
    parse_maishift_profile,
)


logger = logging.getLogger(__name__)


class FetchStatus(str, Enum):
    VALID_PUBLIC = "VALID_PUBLIC"
    INVALID_OR_PRIVATE = "INVALID_OR_PRIVATE"
    TEMPORARY_ERROR = "TEMPORARY_ERROR"
    NOT_MODIFIED = "NOT_MODIFIED"


@dataclass(frozen=True, slots=True)
class FetchResult:
    status: FetchStatus
    snapshot: MaishiftSnapshot | None = None
    etag: str | None = None
    last_modified: str | None = None
    retry_after: float | None = None
    error: str | None = None


def normalize_profile_key(profile_name: str) -> str:
    return normalize_text(profile_name).casefold()


def profile_urls(profile_name: str) -> tuple[str, str]:
    encoded = quote(normalize_text(profile_name), safe="")
    return (
        f"https://maimai.shiftpsh.com/en/profile/{encoded}/home",
        f"https://maimai.shiftpsh.com/profile/{encoded}/home",
    )


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            return None
        return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())


class MaishiftClient:
    def __init__(self, *, timeout: float = 10.0, concurrency: int = 5) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._semaphore = asyncio.Semaphore(concurrency)
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                headers={"User-Agent": "MilkBot maishift tracker"},
            )

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def fetch(
        self,
        profile_name: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchResult:
        await self.start()
        assert self._session is not None
        internal_url, public_url = profile_urls(profile_name)
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        try:
            async with self._semaphore:
                async with self._session.get(internal_url, headers=headers, allow_redirects=True) as response:
                    response_etag = response.headers.get("ETag")
                    response_modified = response.headers.get("Last-Modified")
                    if response.status == 304:
                        return FetchResult(
                            FetchStatus.NOT_MODIFIED,
                            etag=response_etag or etag,
                            last_modified=response_modified or last_modified,
                        )
                    if response.status == 429:
                        return FetchResult(
                            FetchStatus.TEMPORARY_ERROR,
                            retry_after=_retry_after_seconds(response.headers.get("Retry-After")),
                            error="HTTP 429",
                        )
                    if response.status >= 500:
                        return FetchResult(FetchStatus.TEMPORARY_ERROR, error=f"HTTP {response.status}")
                    if response.status >= 400:
                        return FetchResult(FetchStatus.INVALID_OR_PRIVATE, error=f"HTTP {response.status}")
                    body = await response.read()
            try:
                snapshot = parse_maishift_profile(
                    body,
                    profile_key=normalize_profile_key(profile_name),
                    profile_name=profile_name,
                    profile_url=public_url,
                )
            except MaishiftInvalidOrPrivateError as exc:
                return FetchResult(FetchStatus.INVALID_OR_PRIVATE, error=str(exc))
            except MaishiftParseError as exc:
                logger.error("maishift parser failed: %s", profile_name, exc_info=True)
                return FetchResult(FetchStatus.TEMPORARY_ERROR, error=str(exc))
            return FetchResult(
                FetchStatus.VALID_PUBLIC,
                snapshot=snapshot,
                etag=response_etag,
                last_modified=response_modified,
            )
        except (aiohttp.ClientError, TimeoutError) as exc:
            return FetchResult(FetchStatus.TEMPORARY_ERROR, error=type(exc).__name__)
