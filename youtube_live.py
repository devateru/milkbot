import os
import re
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
    actual_end_time: datetime | None
    concurrent_viewers: str | None

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass(frozen=True)
class MachineStatus:
    key: str
    kind: str
    number: int
    label: str
    is_live: bool
    thumbnail_url: str | None
    live_url: str | None
    last_ended_at: datetime | None


_cached_channel_id: str | None = None

DISPLAY_NAME = {
    "maimai": "마이마이",
    "chunithm": "츄니즘",
}

MACHINE_LAYOUT = (
    ("maimai", 1),
    ("maimai", 2),
    ("maimai", 3),
    ("maimai", 4),
    ("maimai", 5),
    ("chunithm", 1),
    ("chunithm", 2),
    ("chunithm", 3),
)


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


def _parse_slot_key(title: str) -> str | None:
    normalized = title.casefold()

    game_key: str | None = None
    game_position: int | None = None

    for keyword in ("maimai", "마이마이", "mai"):
        position = normalized.find(keyword)
        if position >= 0 and (game_position is None or position < game_position):
            game_key = "maimai"
            game_position = position

    for keyword in ("chunithm", "츄니즘", "chu"):
        position = normalized.find(keyword)
        if position >= 0 and (game_position is None or position < game_position):
            game_key = "chunithm"
            game_position = position

    if game_key is None or game_position is None:
        return None

    title_after_game_name = normalized[game_position:]
    machine_match = re.search(
        r"([1-8])\s*(?:번기|号机|台|cab|cabinet)?",
        title_after_game_name,
    )

    if not machine_match:
        return None

    machine_number = machine_match.group(1)

    if game_key == "maimai":
        return f"maimai_{machine_number}"

    if game_key == "chunithm":
        return f"chunithm_{machine_number}"

    return None


def _machine_key(kind: str, number: int) -> str:
    return f"{kind}_{number}"


def _machine_label(kind: str, number: int) -> str:
    return f"{DISPLAY_NAME[kind]} {number}번기"


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


def _build_live_video(video_id: str, video: dict[str, Any]) -> YouTubeLiveVideo:
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
        actual_end_time=_parse_datetime(live_details.get("actualEndTime")),
        concurrent_viewers=live_details.get("concurrentViewers"),
    )


def _fetch_videos_by_event(event_type: str, max_results: int = 25) -> list[YouTubeLiveVideo]:
    channel_id = _get_channel_id()
    search_data = _request_youtube(
        "search",
        {
            "part": "snippet",
            "channelId": channel_id,
            "eventType": event_type,
            "maxResults": max_results,
            "order": "date",
            "type": "video",
        },
    )
    search_items = search_data.get("items", [])

    if not search_items:
        return []

    video_ids = [
        item.get("id", {}).get("videoId")
        for item in search_items
        if isinstance(item.get("id", {}).get("videoId"), str)
    ]

    if not video_ids:
        raise YouTubeLiveError("YouTube search response had no video ids")

    videos_data = _request_youtube(
        "videos",
        {
            "part": "snippet,liveStreamingDetails",
            "id": ",".join(video_ids),
        },
    )
    video_items = videos_data.get("items", [])

    if not video_items:
        raise YouTubeLiveError("YouTube video response had no items")

    videos_by_id = {item.get("id"): item for item in video_items}
    live_videos = []

    for video_id in video_ids:
        video = videos_by_id.get(video_id)
        if isinstance(video, dict):
            live_videos.append(_build_live_video(video_id, video))

    return live_videos


def get_gameplaza_live_videos(max_results: int = 25) -> list[YouTubeLiveVideo]:
    return _fetch_videos_by_event("live", max_results=max_results)


def get_gameplaza_completed_videos(max_results: int = 50) -> list[YouTubeLiveVideo]:
    return _fetch_videos_by_event("completed", max_results=max_results)


def get_gameplaza_machine_statuses() -> list[MachineStatus]:
    live_videos = get_gameplaza_live_videos()
    completed_videos = get_gameplaza_completed_videos()
    videos_by_slot: dict[str, YouTubeLiveVideo] = {}
    completed_by_slot: dict[str, YouTubeLiveVideo] = {}

    for video in live_videos:
        slot_key = _parse_slot_key(video.title)
        if slot_key:
            videos_by_slot[slot_key] = video

    for video in completed_videos:
        slot_key = _parse_slot_key(video.title)
        if slot_key and slot_key not in completed_by_slot:
            completed_by_slot[slot_key] = video

    statuses = []

    for kind, number in MACHINE_LAYOUT:
        slot_key = _machine_key(kind, number)
        live_video = videos_by_slot.get(slot_key)
        completed_video = completed_by_slot.get(slot_key)

        statuses.append(
            MachineStatus(
                key=slot_key,
                kind=kind,
                number=number,
                label=_machine_label(kind, number),
                is_live=live_video is not None,
                thumbnail_url=live_video.thumbnail_url if live_video else None,
                live_url=live_video.url if live_video else None,
                last_ended_at=completed_video.actual_end_time if completed_video else None,
            )
        )

    return statuses


def get_gameplaza_live_slots() -> list[MachineStatus]:
    return get_gameplaza_machine_statuses()


def get_gameplaza_live_video() -> YouTubeLiveVideo | None:
    live_videos = get_gameplaza_live_videos(max_results=1)
    return live_videos[0] if live_videos else None
