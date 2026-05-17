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
    concurrent_viewers: str | None

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass(frozen=True)
class GameplazaLiveSlot:
    key: str
    label: str
    video: YouTubeLiveVideo | None


_cached_channel_id: str | None = None

GAMEPLAZA_LIVE_SLOTS = (
    ("maimai_1", "마이마이 1번기"),
    ("maimai_2", "마이마이 2번기"),
    ("maimai_3", "마이마이 3번기"),
    ("maimai_4", "마이마이 4번기"),
    ("maimai_5", "마이마이 5번기"),
    ("chunithm_1", "츄니즘 1번기"),
    ("chunithm_2", "츄니즘 2번기"),
    ("chunithm_3", "츄니즘 3번기"),
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
        concurrent_viewers=live_details.get("concurrentViewers"),
    )


def get_gameplaza_live_videos(max_results: int = 8) -> list[YouTubeLiveVideo]:
    channel_id = _get_channel_id()
    search_data = _request_youtube(
        "search",
        {
            "part": "snippet",
            "channelId": channel_id,
            "eventType": "live",
            "maxResults": max_results,
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


def get_gameplaza_live_slots(max_results: int = 8) -> list[GameplazaLiveSlot]:
    videos = get_gameplaza_live_videos(max_results=max_results)
    videos_by_slot: dict[str, YouTubeLiveVideo] = {}
    unassigned_videos = []

    for video in videos:
        slot_key = _parse_slot_key(video.title)
        if slot_key in dict(GAMEPLAZA_LIVE_SLOTS):
            videos_by_slot[slot_key] = video
        else:
            unassigned_videos.append(video)

    for slot_key, _label in GAMEPLAZA_LIVE_SLOTS:
        if not unassigned_videos:
            break
        if slot_key not in videos_by_slot:
            videos_by_slot[slot_key] = unassigned_videos.pop(0)

    return [
        GameplazaLiveSlot(
            key=slot_key,
            label=label,
            video=videos_by_slot.get(slot_key),
        )
        for slot_key, label in GAMEPLAZA_LIVE_SLOTS
    ]


def get_gameplaza_live_video() -> YouTubeLiveVideo | None:
    live_videos = get_gameplaza_live_videos(max_results=1)
    return live_videos[0] if live_videos else None
