import os
import re
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone, timedelta
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, ImageOps
from yt_dlp import YoutubeDL


CHANNEL_STREAMS_URL = "https://www.youtube.com/@GAMEPLAZA_C/streams"

TARGET_STREAMS = [
    {
        "game": "maimai",
        "number": "1",
        "title": "광주 게임플라자 마이마이 디럭스 maimai DX (1번기) LIVE",
        "label": "마이마이 1번기",
        "group": "마이마이 디럭스",
    },
    {
        "game": "maimai",
        "number": "2",
        "title": "광주 게임플라자 마이마이 디럭스 maimai DX (2번기) LIVE",
        "label": "마이마이 2번기",
        "group": "마이마이 디럭스",
    },
    {
        "game": "maimai",
        "number": "3",
        "title": "광주 게임플라자 마이마이 디럭스 maimai DX (3번기) LIVE",
        "label": "마이마이 3번기",
        "group": "마이마이 디럭스",
    },
    {
        "game": "maimai",
        "number": "4",
        "title": "광주 게임플라자 마이마이 디럭스 maimai DX (4번기) LIVE",
        "label": "마이마이 4번기",
        "group": "마이마이 디럭스",
    },
    {
        "game": "maimai",
        "number": "5",
        "title": "광주 게임플라자 마이마이 디럭스 maimai DX (5번기) LIVE",
        "label": "마이마이 5번기",
        "group": "마이마이 디럭스",
    },
    {
        "game": "chunithm",
        "number": "1",
        "title": "광주 게임플라자 츄니즘 CHUNITHM (1번기) LIVE",
        "label": "츄니즘 1번기",
        "group": "츄니즘",
    },
    {
        "game": "chunithm",
        "number": "2",
        "title": "광주 게임플라자 츄니즘 CHUNITHM (2번기) LIVE",
        "label": "츄니즘 2번기",
        "group": "츄니즘",
    },
    {
        "game": "chunithm",
        "number": "3",
        "title": "광주 게임플라자 츄니즘 CHUNITHM (3번기) LIVE",
        "label": "츄니즘 3번기",
        "group": "츄니즘",
    },
]

KST = timezone(timedelta(hours=9))

CACHE_SECONDS = 45
ZERO_RESULT_CACHE_SECONDS = 10
CACHE_TIME: datetime | None = None
CACHE_ITEMS: list[dict] | None = None
CACHE_FOOTER_TEXT: str | None = None
CACHE_NO_STREAM_WARNING_NEEDED = False

LAST_GOOD_MAX_SECONDS = 120
LAST_GOOD_TIME: datetime | None = None
LAST_GOOD_ITEMS: list[dict] | None = None

RESPONSE_FOOTER_TEXT: str | None = None
NO_STREAM_WARNING_NEEDED = False
NO_STREAM_WARNING_TEXT = "감지된 라이브가 없어요. 서버 오류인 것 같다면 잠시 뒤 다시 시도해주세요."

LAST_DEBUG_ROWS: list[str] = []

TILE_W = 1280
TILE_H = 720
BORDER = 6
BANNER_H = 84
JPEG_QUALITY = 96

# Thumbnail policy:
# - keep final grid at 1280x720 per tile
# - prefer YouTube live 720p thumbnails
# - cap the number of URL attempts so loading time does not grow too much
THUMBNAIL_CANDIDATE_LIMIT = 7
THUMBNAIL_DOWNLOAD_TIMEOUT = 6
THUMBNAIL_MIN_WIDTH = 480
THUMBNAIL_MIN_HEIGHT = 270

DETAIL_CHECK_WHEN_FLAT_UNKNOWN = True
DETAIL_WORKERS = 4
DETAIL_TOTAL_TIMEOUT = 12
DETAIL_SOCKET_TIMEOUT = 6
MAX_DETAIL_CANDIDATES_PER_MACHINE = 4

global STREAM_EMPTY
STREAM_EMPTY = False

def normalize_title(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def machine_key(game: str, number: str) -> str:
    return f"{game}:{number}"


def target_title_to_key() -> dict[str, str]:
    return {
        normalize_title(target["title"]).lower(): machine_key(target["game"], target["number"])
        for target in TARGET_STREAMS
    }


def title_to_machine_key(title: str) -> str | None:
    title_norm = normalize_title(title).lower()

    exact_key = target_title_to_key().get(title_norm)
    if exact_key:
        return exact_key

    if "maimai" in title_norm or "마이마이" in title_norm:
        game = "maimai"
    elif "chunithm" in title_norm or "츄니즘" in title_norm:
        game = "chunithm"
    else:
        return None

    match = re.search(r"(\d+)\s*(?:번기|번|호기)", title_norm)
    if not match:
        return None

    return machine_key(game, match.group(1))


def get_video_id(entry: dict) -> str | None:
    video_id = entry.get("id")
    if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", str(video_id)):
        return str(video_id)

    for field in ["url", "webpage_url"]:
        url = entry.get(field)
        if not url:
            continue

        match = re.search(r"(?:v=|youtu\.be/|shorts/|live/)([A-Za-z0-9_-]{11})", str(url))
        if match:
            return match.group(1)

        if re.fullmatch(r"[A-Za-z0-9_-]{11}", str(url)):
            return str(url)

    return None


def get_video_url(entry: dict) -> str | None:
    video_id = get_video_id(entry)
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"

    url = entry.get("url")
    if url:
        if url.startswith("http"):
            return url
        return f"https://www.youtube.com/watch?v={url}"

    webpage_url = entry.get("webpage_url")
    if webpage_url:
        return webpage_url

    return None


def get_thumbnail_urls(entry: dict) -> list[str]:
    urls: list[str] = []
    video_id = get_video_id(entry)

    # Prefer high-resolution live thumbnail endpoints first.
    # These usually match the current YouTube live listing better than static maxresdefault.jpg.
    if video_id:
        urls.extend(
            [
                f"https://i.ytimg.com/vi/{video_id}/hq720_live.jpg",
                f"https://i.ytimg.com/vi/{video_id}/maxresdefault_live.jpg",
            ]
        )

    thumbnails = entry.get("thumbnails") or []
    valid_thumbnails = [
        t for t in thumbnails
        if isinstance(t, dict) and t.get("url")
    ]

    def thumbnail_score(t: dict) -> tuple[int, int]:
        url = str(t.get("url") or "").lower()
        area = (t.get("width") or 0) * (t.get("height") or 0)
        live_bonus = 2 if "live" in url else 0
        hq720_bonus = 2 if "hq720" in url else 0
        sd_bonus = 1 if "sddefault" in url else 0
        return (live_bonus + hq720_bonus + sd_bonus, area)

    valid_thumbnails.sort(key=thumbnail_score, reverse=True)
    urls.extend(t["url"] for t in valid_thumbnails)

    if entry.get("thumbnail"):
        urls.append(entry["thumbnail"])

    if video_id:
        urls.extend(
            [
                f"https://i.ytimg.com/vi/{video_id}/sddefault_live.jpg",
                f"https://i.ytimg.com/vi/{video_id}/hqdefault_live.jpg",
                f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
                f"https://i.ytimg.com/vi/{video_id}/sddefault.jpg",
                f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            ]
        )

    deduped: list[str] = []
    seen = set()

    for url in urls:
        if url and url not in seen:
            deduped.append(url)
            seen.add(url)

        if len(deduped) >= THUMBNAIL_CANDIDATE_LIMIT:
            break

    return deduped


def is_live_entry(entry: dict) -> bool:
    return entry.get("is_live") is True or entry.get("live_status") == "is_live"


def fetch_stream_entries() -> list[dict]:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "ignoreerrors": True,
        "playlistend": 50,
        "socket_timeout": 8,
        "retries": 1,
        "extractor_retries": 1,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(CHANNEL_STREAMS_URL, download=False)

    return info.get("entries", []) if info else []


def extract_video_detail(video_url: str) -> dict | None:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "noplaylist": True,
        "socket_timeout": DETAIL_SOCKET_TIMEOUT,
        "retries": 0,
        "extractor_retries": 0,
    }

    cookiefile = os.getenv("YOUTUBE_COOKIES_FILE")
    if cookiefile:
        ydl_opts["cookiefile"] = cookiefile

    try:
        with YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(video_url, download=False)
    except Exception:
        return None


def fetch_gameplaza_live_status(force_refresh: bool = False) -> list[dict]:
    global CACHE_TIME, CACHE_ITEMS, LAST_DEBUG_ROWS
    global LAST_GOOD_TIME, LAST_GOOD_ITEMS
    global CACHE_FOOTER_TEXT, RESPONSE_FOOTER_TEXT
    global CACHE_NO_STREAM_WARNING_NEEDED, NO_STREAM_WARNING_NEEDED
    global STREAM_EMPTY

    now = datetime.now(KST)

    if not force_refresh and CACHE_TIME is not None and CACHE_ITEMS is not None:
        age = (now - CACHE_TIME).total_seconds()
        cached_live_count = sum(1 for item in CACHE_ITEMS if item["is_live"])
        cache_limit = CACHE_SECONDS if cached_live_count > 0 else ZERO_RESULT_CACHE_SECONDS

        if age < cache_limit:
            RESPONSE_FOOTER_TEXT = CACHE_FOOTER_TEXT
            NO_STREAM_WARNING_NEEDED = CACHE_NO_STREAM_WARNING_NEEDED
            return CACHE_ITEMS

    RESPONSE_FOOTER_TEXT = None
    NO_STREAM_WARNING_NEEDED = False

    entries = fetch_stream_entries()

    target_keys = {
        machine_key(target["game"], target["number"]): target
        for target in TARGET_STREAMS
    }

    live_by_key: dict[str, dict] = {}
    candidates_by_key: dict[str, list[dict]] = {key: [] for key in target_keys}
    seen_candidate_urls: dict[str, set[str]] = {key: set() for key in target_keys}
    debug_rows: list[str] = [f"STREAMS_TAB_ENTRIES | {len(entries)}"]

    for entry in entries:
        if not entry:
            continue

        title = normalize_title(entry.get("title", ""))
        key = title_to_machine_key(title)
        live_status = entry.get("live_status")
        is_live = entry.get("is_live")

        debug_rows.append(
            f"ENTRY | key={key} | live_status={live_status} | is_live={is_live} | title={title[:90]}"
        )

        if key not in target_keys:
            continue

        url = get_video_url(entry)
        if not url:
            continue

        if url not in seen_candidate_urls[key] and len(candidates_by_key[key]) < MAX_DETAIL_CANDIDATES_PER_MACHINE:
            candidates_by_key[key].append(entry)
            seen_candidate_urls[key].add(url)

        if is_live_entry(entry):
            live_by_key[key] = {
                "url": url,
                "thumbnail_urls": get_thumbnail_urls(entry),
            }

    needs_detail_check = (
        DETAIL_CHECK_WHEN_FLAT_UNKNOWN
        and any(candidates_by_key[key] for key in target_keys)
        and len(live_by_key) < len([key for key in target_keys if candidates_by_key[key]])
    )

    if needs_detail_check:
        jobs: list[tuple[str, str, dict]] = []

        for key, candidates in candidates_by_key.items():
            if key in live_by_key:
                continue

            for entry in candidates:
                url = get_video_url(entry)
                if url:
                    jobs.append((key, url, entry))

        debug_rows.append(f"DETAIL_CHECK_JOBS | {len(jobs)}")

        executor = ThreadPoolExecutor(max_workers=DETAIL_WORKERS)
        future_to_job = {
            executor.submit(extract_video_detail, url): (key, url, entry)
            for key, url, entry in jobs
        }

        try:
            for future in as_completed(future_to_job, timeout=DETAIL_TOTAL_TIMEOUT):
                key, url, entry = future_to_job[future]
                detail = future.result()

                if not detail:
                    debug_rows.append(f"DETAIL | key={key} | failed | url={url}")
                    continue

                detail_title = normalize_title(detail.get("title") or entry.get("title", ""))
                detail_key = title_to_machine_key(detail_title) or key
                detail_live_status = detail.get("live_status")
                detail_is_live = detail.get("is_live")

                debug_rows.append(
                    f"DETAIL | key={detail_key} | live_status={detail_live_status} | is_live={detail_is_live} | title={detail_title[:80]}"
                )

                if detail_key not in target_keys:
                    continue

                if is_live_entry(detail):
                    live_by_key[detail_key] = {
                        "url": get_video_url(detail) or url,
                        "thumbnail_urls": get_thumbnail_urls(detail) or get_thumbnail_urls(entry),
                    }

        except FuturesTimeoutError:
            debug_rows.append(f"DETAIL_CHECK_TIMEOUT | {DETAIL_TOTAL_TIMEOUT}s")
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    results: list[dict] = []

    for target in TARGET_STREAMS:
        key = machine_key(target["game"], target["number"])
        live_item = live_by_key.get(key)

        results.append(
            {
                "label": target["label"],
                "group": target["group"],
                "is_live": live_item is not None,
                "url": live_item["url"] if live_item else None,
                "thumbnail_urls": live_item["thumbnail_urls"] if live_item else [],
            }
        )

    live_count = sum(1 for item in results if item["is_live"])
    debug_rows.append(f"FINAL_LIVE_COUNT | {live_count}/8")

    if live_count > 0:
        LAST_GOOD_TIME = now
        LAST_GOOD_ITEMS = results
        LAST_DEBUG_ROWS = debug_rows
        CACHE_TIME = now
        CACHE_ITEMS = results
        CACHE_FOOTER_TEXT = None
        CACHE_NO_STREAM_WARNING_NEEDED = False
        RESPONSE_FOOTER_TEXT = None
        NO_STREAM_WARNING_NEEDED = False
        STREAM_EMPTY = False
        return results

    if LAST_GOOD_TIME is not None and LAST_GOOD_ITEMS is not None:
        good_age = (now - LAST_GOOD_TIME).total_seconds()
        if good_age < LAST_GOOD_MAX_SECONDS:
            fallback_minutes = max(1, int(round(good_age / 60)))
            footer_text = f"*라이브가 감지되지 않아 잠깐 전의 기록을 대신 출력했어요."

            STREAM_EMPTY = True

            debug_rows.append(
                f"ZERO_LIVE_RESULT_IGNORED | keeping last good result from {int(good_age)}s ago"
            )
            LAST_DEBUG_ROWS = debug_rows
            CACHE_TIME = now
            CACHE_ITEMS = LAST_GOOD_ITEMS
            CACHE_FOOTER_TEXT = footer_text
            CACHE_NO_STREAM_WARNING_NEEDED = False
            RESPONSE_FOOTER_TEXT = footer_text
            NO_STREAM_WARNING_NEEDED = False
            return LAST_GOOD_ITEMS

    LAST_DEBUG_ROWS = debug_rows
    CACHE_TIME = now
    CACHE_ITEMS = results
    CACHE_FOOTER_TEXT = None
    CACHE_NO_STREAM_WARNING_NEEDED = True
    RESPONSE_FOOTER_TEXT = None
    NO_STREAM_WARNING_NEEDED = True

    return results


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = []

    if bold:
        candidates.extend(
            [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
                "C:/Windows/Fonts/malgunbd.ttf",
            ]
        )

    candidates.extend(
        [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/malgun.ttf",
        ]
    )

    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)

    return ImageFont.load_default()


def download_image(url: str) -> Image.Image:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )

    with urllib.request.urlopen(request, timeout=THUMBNAIL_DOWNLOAD_TIMEOUT) as response:
        data = response.read()

    image = Image.open(BytesIO(data)).convert("RGB")

    if image.width < THUMBNAIL_MIN_WIDTH or image.height < THUMBNAIL_MIN_HEIGHT:
        raise ValueError(f"thumbnail too small: {image.width}x{image.height}")

    return image


def download_first_available_image(urls: list[str]) -> Image.Image | None:
    for url in urls:
        try:
            return download_image(url)
        except Exception:
            continue

    return None


def draw_centered_multiline(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    line_spacing: int = 8,
):
    x1, y1, x2, y2 = box

    line_boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_sizes = [(b[2] - b[0], b[3] - b[1]) for b in line_boxes]
    total_height = sum(height for _, height in line_sizes) + line_spacing * (len(lines) - 1)

    cursor_y = y1 + ((y2 - y1) - total_height) // 2

    for line, bbox, (text_width, text_height) in zip(lines, line_boxes, line_sizes):
        x = x1 + ((x2 - x1) - text_width) // 2 - bbox[0]
        y = cursor_y - bbox[1]
        draw.text((x, y), line, font=font, fill=fill)
        cursor_y += text_height + line_spacing


def draw_live_label(tile: Image.Image, label: str) -> Image.Image:
    overlay = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font = load_font(38, bold=True)
    padding_x = 18
    padding_y = 12
    margin = 22

    text_bbox = draw.textbbox((0, 0), label, font=font)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]

    box_w = text_w + padding_x * 2
    box_h = text_h + padding_y * 2

    x2 = tile.width - margin
    y2 = tile.height - margin
    x1 = x2 - box_w
    y1 = y2 - box_h

    draw.rounded_rectangle((x1, y1, x2, y2), radius=12, fill=(0, 0, 0, 180))
    draw.text(
        (x1 + padding_x - text_bbox[0], y1 + padding_y - text_bbox[1]),
        label,
        font=font,
        fill=(255, 255, 255, 255),
    )

    tile_rgba = tile.convert("RGBA")
    tile_rgba.alpha_composite(overlay)
    return tile_rgba.convert("RGB")


def make_offline_tile(label: str, tile_w: int, tile_h: int) -> Image.Image:
    tile = Image.new("RGB", (tile_w, tile_h), (0, 0, 0))
    draw = ImageDraw.Draw(tile)
    font = load_font(58, bold=True)

    draw_centered_multiline(
        draw=draw,
        box=(0, 0, tile_w, tile_h),
        lines=[label, "오프라인"],
        font=font,
        fill=(255, 255, 255),
        line_spacing=22,
    )

    return tile


def make_thumbnail_tile(item: dict, tile_w: int, tile_h: int) -> Image.Image:
    label = item["label"]

    if item["is_live"]:
        image = download_first_available_image(item.get("thumbnail_urls", []))

        if image is not None:
            tile = ImageOps.fit(
                image,
                (tile_w, tile_h),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            return draw_live_label(tile, label)

        tile = Image.new("RGB", (tile_w, tile_h), (20, 20, 20))
        draw = ImageDraw.Draw(tile)
        font = load_font(54, bold=True)
        draw_centered_multiline(
            draw=draw,
            box=(0, 0, tile_w, tile_h),
            lines=[label, "라이브", "썸네일 없음"],
            font=font,
            fill=(255, 255, 255),
            line_spacing=16,
        )
        return tile

    return make_offline_tile(label, tile_w, tile_h)


def make_gameplaza_grid_image(items: list[dict]) -> BytesIO:
    cols = 4
    rows = 2
    tile_w = TILE_W
    tile_h = TILE_H
    border = BORDER
    banner_h = BANNER_H

    grid_w = cols * tile_w + (cols + 1) * border
    grid_h = rows * tile_h + (rows + 1) * border
    total_h = grid_h + banner_h

    canvas = Image.new("RGB", (grid_w, total_h), (0, 0, 0))

    for index, item in enumerate(items):
        row = index // cols
        col = index % cols
        x = border + col * (tile_w + border)
        y = border + row * (tile_h + border)
        tile = make_thumbnail_tile(item, tile_w, tile_h)
        canvas.paste(tile, (x, y))

    draw = ImageDraw.Draw(canvas)
    banner_y = grid_h
    draw.rectangle((0, banner_y, grid_w, total_h), fill=(0, 0, 0))

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    if STREAM_EMPTY:
        left_text = f"{now}*  @광주 게임플라자"
    else:
        left_text = f"{now}  @광주 게임플라자"
    right_text = "generated by @밀크봇"
    banner_font = load_font(34, bold=False)

    left_bbox = draw.textbbox((0, 0), left_text, font=banner_font)
    right_bbox = draw.textbbox((0, 0), right_text, font=banner_font)

    left_h = left_bbox[3] - left_bbox[1]
    right_w = right_bbox[2] - right_bbox[0]
    right_h = right_bbox[3] - right_bbox[1]
    margin_x = 30

    left_y = banner_y + (banner_h - left_h) // 2 - left_bbox[1]
    right_y = banner_y + (banner_h - right_h) // 2 - right_bbox[1]

    draw.text((margin_x - left_bbox[0], left_y), left_text, font=banner_font, fill=(255, 255, 255))
    draw.text(
        (grid_w - margin_x - right_w - right_bbox[0], right_y),
        right_text,
        font=banner_font,
        fill=(255, 255, 255),
    )

    output = BytesIO()
    canvas.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    output.seek(0)
    return output


def get_response_footer_text() -> str | None:
    return RESPONSE_FOOTER_TEXT


def should_send_no_stream_warning() -> bool:
    return NO_STREAM_WARNING_NEEDED


def get_no_stream_warning_text() -> str:
    return NO_STREAM_WARNING_TEXT


def get_debug_rows(limit: int | None = None) -> list[str]:
    if limit is None:
        return list(LAST_DEBUG_ROWS)

    return LAST_DEBUG_ROWS[-limit:]
