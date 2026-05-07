import asyncio
import os
import re
import unicodedata
import urllib.request
from datetime import datetime, timezone, timedelta
from io import BytesIO

import discord
from discord import app_commands
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont, ImageOps
from yt_dlp import YoutubeDL


load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in .env")


CHANNEL_STREAMS_URL = "https://www.youtube.com/@GAMEPLAZA_C/streams"

TARGET_STREAMS = [
    {"game": "maimai", "number": "1", "label": "마이마이 1번기", "group": "마이마이 디럭스"},
    {"game": "maimai", "number": "2", "label": "마이마이 2번기", "group": "마이마이 디럭스"},
    {"game": "maimai", "number": "3", "label": "마이마이 3번기", "group": "마이마이 디럭스"},
    {"game": "maimai", "number": "4", "label": "마이마이 4번기", "group": "마이마이 디럭스"},
    {"game": "maimai", "number": "5", "label": "마이마이 5번기", "group": "마이마이 디럭스"},
    {"game": "chunithm", "number": "1", "label": "츄니즘 1번기", "group": "츄니즘"},
    {"game": "chunithm", "number": "2", "label": "츄니즘 2번기", "group": "츄니즘"},
    {"game": "chunithm", "number": "3", "label": "츄니즘 3번기", "group": "츄니즘"},
]

KST = timezone(timedelta(hours=9))

CACHE_SECONDS = 45
CACHE_TIME: datetime | None = None
CACHE_ITEMS: list[dict] | None = None
LAST_DEBUG_ROWS: list[str] = []


def normalize_title(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def machine_key(game: str, number: str) -> str:
    return f"{game}:{number}"


def title_to_machine_key(title: str) -> str | None:
    """
    기존 exact title matching 대신, flat entry 제목에서 게임명과 기기 번호만 뽑아 매칭합니다.
    예: '광주 게임플라자 마이마이 디럭스 maimai DX (1번기) LIVE' -> 'maimai:1'
    """
    title_norm = normalize_title(title).lower()

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


def get_video_url(entry: dict) -> str | None:
    video_id = entry.get("id")
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


def get_thumbnail_url(entry: dict) -> str | None:
    thumbnails = entry.get("thumbnails") or []

    valid_thumbnails = [
        t for t in thumbnails
        if isinstance(t, dict) and t.get("url")
    ]

    if valid_thumbnails:
        best = max(
            valid_thumbnails,
            key=lambda t: (t.get("width") or 0) * (t.get("height") or 0),
        )
        return best["url"]

    if entry.get("thumbnail"):
        return entry["thumbnail"]

    video_id = entry.get("id")
    if video_id:
        return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

    return None


def is_live_entry(entry: dict) -> bool:
    live_status = entry.get("live_status")
    is_live = entry.get("is_live")

    if is_live is True:
        return True

    if live_status == "is_live":
        return True

    return False


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


def fetch_gameplaza_live_status(force_refresh: bool = False) -> list[dict]:
    """
    빠른 버전입니다.
    /streams flat 목록만 조회하고, 제목 exact match 대신 machine key로 매칭합니다.
    ytsearch 또는 영상별 상세 조회는 하지 않습니다.
    """
    global CACHE_TIME, CACHE_ITEMS, LAST_DEBUG_ROWS

    now = datetime.now(KST)

    if not force_refresh and CACHE_TIME is not None and CACHE_ITEMS is not None:
        age = (now - CACHE_TIME).total_seconds()
        if age < CACHE_SECONDS:
            return CACHE_ITEMS

    entries = fetch_stream_entries()

    target_keys = {
        machine_key(target["game"], target["number"]): target
        for target in TARGET_STREAMS
    }

    live_by_key: dict[str, dict] = {}
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

        if not is_live_entry(entry):
            continue

        url = get_video_url(entry)
        if not url:
            continue

        live_by_key[key] = {
            "url": url,
            "thumbnail": get_thumbnail_url(entry),
        }

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
                "thumbnail": live_item["thumbnail"] if live_item else None,
            }
        )

    live_count = sum(1 for item in results if item["is_live"])
    debug_rows.append(f"FINAL_LIVE_COUNT | {live_count}/8")

    LAST_DEBUG_ROWS = debug_rows
    CACHE_TIME = now
    CACHE_ITEMS = results

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
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urllib.request.urlopen(request, timeout=8) as response:
        data = response.read()

    return Image.open(BytesIO(data)).convert("RGB")


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
    line_heights = [b[3] - b[1] for b in line_boxes]
    total_height = sum(line_heights) + line_spacing * (len(lines) - 1)

    y = y1 + ((y2 - y1) - total_height) // 2

    for line, bbox in zip(lines, line_boxes):
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = x1 + ((x2 - x1) - text_width) // 2
        draw.text((x, y), line, font=font, fill=fill)
        y += text_height + line_spacing


def draw_live_label(tile: Image.Image, label: str) -> Image.Image:
    overlay = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font = load_font(24, bold=True)
    padding_x = 12
    padding_y = 8
    margin = 14

    text_bbox = draw.textbbox((0, 0), label, font=font)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]

    box_w = text_w + padding_x * 2
    box_h = text_h + padding_y * 2

    x2 = tile.width - margin
    y2 = tile.height - margin
    x1 = x2 - box_w
    y1 = y2 - box_h

    draw.rounded_rectangle((x1, y1, x2, y2), radius=8, fill=(0, 0, 0, 180))
    draw.text((x1 + padding_x, y1 + padding_y - 2), label, font=font, fill=(255, 255, 255, 255))

    tile_rgba = tile.convert("RGBA")
    tile_rgba.alpha_composite(overlay)
    return tile_rgba.convert("RGB")


def make_offline_tile(label: str, tile_w: int, tile_h: int) -> Image.Image:
    tile = Image.new("RGB", (tile_w, tile_h), (0, 0, 0))
    draw = ImageDraw.Draw(tile)
    font = load_font(36, bold=True)

    draw_centered_multiline(
        draw=draw,
        box=(0, 0, tile_w, tile_h),
        lines=[label, "오프라인"],
        font=font,
        fill=(255, 255, 255),
        line_spacing=14,
    )

    return tile


def make_thumbnail_tile(item: dict, tile_w: int, tile_h: int) -> Image.Image:
    label = item["label"]

    if item["is_live"] and item["thumbnail"]:
        try:
            image = download_image(item["thumbnail"])
            tile = ImageOps.fit(
                image,
                (tile_w, tile_h),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            return draw_live_label(tile, label)
        except Exception:
            pass

    if item["is_live"]:
        tile = Image.new("RGB", (tile_w, tile_h), (20, 20, 20))
        draw = ImageDraw.Draw(tile)
        font = load_font(34, bold=True)
        draw_centered_multiline(
            draw=draw,
            box=(0, 0, tile_w, tile_h),
            lines=[label, "라이브", "썸네일 없음"],
            font=font,
            fill=(255, 255, 255),
            line_spacing=10,
        )
        return tile

    return make_offline_tile(label, tile_w, tile_h)


def make_gameplaza_grid_image(items: list[dict]) -> BytesIO:
    cols = 4
    rows = 2

    tile_w = 640
    tile_h = 360

    border = 4
    banner_h = 72

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
    left_text = f"{now}  @광주 게임플라자"
    right_text = "generated by @밀크봇"

    banner_font = load_font(26, bold=False)

    left_bbox = draw.textbbox((0, 0), left_text, font=banner_font)
    right_bbox = draw.textbbox((0, 0), right_text, font=banner_font)

    left_h = left_bbox[3] - left_bbox[1]
    right_w = right_bbox[2] - right_bbox[0]
    right_h = right_bbox[3] - right_bbox[1]

    margin_x = 22

    left_y = banner_y + (banner_h - left_h) // 2 - 2
    right_y = banner_y + (banner_h - right_h) // 2 - 2

    draw.text((margin_x, left_y), left_text, font=banner_font, fill=(255, 255, 255))
    draw.text((grid_w - margin_x - right_w, right_y), right_text, font=banner_font, fill=(255, 255, 255))

    output = BytesIO()
    canvas.save(output, format="JPEG", quality=92, optimize=True)
    output.seek(0)

    return output


intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@client.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {client.user}")


@tree.command(name="ping", description="밀크봇 부르기")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("pong")


@tree.command(name="겜플라이브디버그", description="게임플라자 /streams 빠른 조회 디버그 정보를 확인합니다.")
async def gameplaza_debug(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)

    try:
        items = await asyncio.to_thread(fetch_gameplaza_live_status, True)
    except Exception as e:
        await interaction.followup.send(f"디버그 실패:\n```{type(e).__name__}: {e}```", ephemeral=True)
        return

    status_lines = [
        f"{item['label']}: {'LIVE' if item['is_live'] else 'OFFLINE'} | {item['url'] or '-'}"
        for item in items
    ]

    debug_text = "\n".join(status_lines + ["", "--- RAW ENTRIES ---"] + LAST_DEBUG_ROWS[-35:])

    if len(debug_text) > 1900:
        debug_text = debug_text[:1900] + "\n... truncated"

    await interaction.followup.send(f"```text\n{debug_text}\n```", ephemeral=True)


@tree.command(name="겜플라이브", description="밀크봇한테 겜플 츄마이 라이브 현황 확인시키기")
async def gameplaza_live(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    try:
        items = await asyncio.to_thread(fetch_gameplaza_live_status)
        image_buffer = await asyncio.to_thread(make_gameplaza_grid_image, items)
    except Exception as e:
        embed = discord.Embed(
            title="게임플라자 라이브 상태 확인 실패",
            description=f"처리 중 오류가 발생했습니다.\n\n```{type(e).__name__}: {e}```",
            color=discord.Color.red(),
        )
        await interaction.followup.send(embed=embed)
        return

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")
    live_count = sum(1 for item in items if item["is_live"])

    embed = discord.Embed(
        title="게임플라자 라이브 상태",
        description=(
            f"[채널 스트림 목록]({CHANNEL_STREAMS_URL})\n"
            f"확인 시각: `{now}`\n"
            f"라이브: `{live_count}/8`"
        ),
        color=discord.Color.blue(),
    )

    def format_machine_link(item: dict) -> str:
        match = re.search(r"(\d+)번기", item["label"])
        machine_name = f"{match.group(1)}번기" if match else item["label"]

        if item["is_live"] and item["url"]:
            return f"[{machine_name}]({item['url']})"

        return "[----]"

    maimai_items = [item for item in items if item["group"] == "마이마이 디럭스"]
    chunithm_items = [item for item in items if item["group"] == "츄니즘"]

    embed.add_field(
        name="마이마이 디럭스",
        value=" / ".join(format_machine_link(item) for item in maimai_items),
        inline=False,
    )

    embed.add_field(
        name="츄니즘",
        value=" / ".join(format_machine_link(item) for item in chunithm_items),
        inline=False,
    )

    file = discord.File(fp=image_buffer, filename="gameplaza_live_grid.jpg")
    embed.set_image(url="attachment://gameplaza_live_grid.jpg")
    embed.set_footer(text="YouTube /streams 목록 기준")

    await interaction.followup.send(embed=embed, file=file)


client.run(TOKEN)
