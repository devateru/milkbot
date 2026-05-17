import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"


class YouTubeLiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class YouTubeLiveVideo:
    video_id: str
    title: str
    channel_title: str
    description: str
    thumbnail_url: str | None
    actual_start_time: datetime | None
    concurrent_viewers: str | None

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


_cached_channel_id: str | None = None


def _request_youtube(path: str, params: dict[str, object]) -> dict[str, Any]:
    api_key = os.getenv("YOUTUBE_API_KEY")

    if not api_key:
        raise YouTubeLiveError("YOUTUBE_API_KEY is not set in .env")

    query = urlencode({**params, "key": api_key})
    url = f"{YOUTUBE_API_BASE_URL}/{path}?{query}"

    try:
        with urlopen(url, timeout=10) as response:
            import json

            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise YouTubeLiveError(f"YouTube API returned HTTP {exc.code}") from exc
    except (OSError, URLError) as exc:
        raise YouTubeLiveError("Could not reach YouTube API") from exc


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _best_thumbnail(snippet: dict[str, Any]) -> str | None:
    thumbnails = snippet.get("thumbnails")

    if not isinstance(thumbnails, dict):
        return None

    for key in ("maxres", "standard", "high", "medium", "default"):
        thumbnail = thumbnails.get(key)
        if isinstance(thumbnail, dict) and isinstance(thumbnail.get("url"), str):
            return thumbnail["url"]

    return None


def _get_channel_id() -> str:
    global _cached_channel_id

    if _cached_channel_id:
        return _cached_channel_id

    configured_channel_id = os.getenv("GAMEPLAZA_YOUTUBE_CHANNEL_ID")
    if configured_channel_id:
        _cached_channel_id = configured_channel_id
        return configured_channel_id

    handle = os.getenv("GAMEPLAZA_YOUTUBE_HANDLE", "@GAMEPLAZA_C")
    data = _request_youtube(
        "channels",
        {
            "part": "id",
            "forHandle": handle,
        },
    )
    items = data.get("items", [])

    if not items:
        raise YouTubeLiveError(f"Could not find YouTube channel for {handle}")

    channel_id = items[0].get("id")
    if not isinstance(channel_id, str):
        raise YouTubeLiveError(f"YouTube channel response for {handle} had no id")

    _cached_channel_id = channel_id
    return channel_id


def get_gameplaza_live_video() -> YouTubeLiveVideo | None:
    channel_id = _get_channel_id()
    search_data = _request_youtube(
        "search",
        {
            "part": "snippet",
            "channelId": channel_id,
            "eventType": "live",
            "maxResults": 1,
            "type": "video",
        },
    )
    search_items = search_data.get("items", [])

    if not search_items:
        return None

    video_id = search_items[0].get("id", {}).get("videoId")
    if not isinstance(video_id, str):
        raise YouTubeLiveError("YouTube search response had no video id")

    videos_data = _request_youtube(
        "videos",
        {
            "part": "snippet,liveStreamingDetails",
            "id": video_id,
        },
    )
    video_items = videos_data.get("items", [])

    if not video_items:
        raise YouTubeLiveError(f"YouTube video response had no item for {video_id}")

    video = video_items[0]
    snippet = video.get("snippet", {})
    live_details = video.get("liveStreamingDetails", {})

    if not isinstance(snippet, dict):
        snippet = {}

    if not isinstance(live_details, dict):
        live_details = {}

    return YouTubeLiveVideo(
        video_id=video_id,
        title=str(snippet.get("title", "게임플라자 라이브")),
        channel_title=str(snippet.get("channelTitle", "GAMEPLAZA")),
        description=str(snippet.get("description", "")),
        thumbnail_url=_best_thumbnail(snippet),
        actual_start_time=_parse_datetime(live_details.get("actualStartTime")),
        concurrent_viewers=live_details.get("concurrentViewers"),
    )
