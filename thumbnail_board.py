from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont, ImageOps

from youtube_live import MachineStatus


COLS = 4
ROWS = 2
TILE_W = 1280
TILE_H = 720
BORDER = 6
BANNER_H = 84
JPEG_QUALITY = 96

GRID_W = COLS * TILE_W + (COLS + 1) * BORDER
GRID_H = ROWS * TILE_H + (ROWS + 1) * BORDER
IMG_W = GRID_W
IMG_H = GRID_H + BANNER_H

THUMBNAIL_DOWNLOAD_TIMEOUT = 6
THUMBNAIL_MIN_W = 480
THUMBNAIL_MIN_H = 270


def _font_candidates(bold: bool) -> tuple[Path, ...]:
    regular = (
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        Path("C:/Windows/Fonts/malgun.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    bold_paths = (
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
        Path("C:/Windows/Fonts/malgunbd.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    )

    return bold_paths + regular if bold else regular + bold_paths


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _font_candidates(bold):
        if path.exists():
            return ImageFont.truetype(str(path), size=size)

    return ImageFont.load_default()


def _thumbnail_urls(status: MachineStatus) -> list[str]:
    urls = []

    if status.video_id:
        urls.extend(
            [
                f"https://i.ytimg.com/vi/{status.video_id}/hq720_live.jpg",
                f"https://i.ytimg.com/vi/{status.video_id}/maxresdefault_live.jpg",
            ]
        )

    if status.thumbnail_url:
        urls.append(status.thumbnail_url)

    if status.video_id:
        urls.extend(
            [
                f"https://i.ytimg.com/vi/{status.video_id}/sddefault_live.jpg",
                f"https://i.ytimg.com/vi/{status.video_id}/hqdefault_live.jpg",
                f"https://i.ytimg.com/vi/{status.video_id}/maxresdefault.jpg",
                f"https://i.ytimg.com/vi/{status.video_id}/sddefault.jpg",
                f"https://i.ytimg.com/vi/{status.video_id}/hqdefault.jpg",
            ]
        )

    deduped = []
    seen = set()
    for url in urls:
        if url and url not in seen:
            deduped.append(url)
            seen.add(url)

    return deduped


def _download_image(url: str) -> Image.Image:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )

    with urlopen(request, timeout=THUMBNAIL_DOWNLOAD_TIMEOUT) as response:
        image = Image.open(BytesIO(response.read())).convert("RGB")

    if image.width < THUMBNAIL_MIN_W or image.height < THUMBNAIL_MIN_H:
        raise ValueError(f"thumbnail too small: {image.width}x{image.height}")

    return image


def _download_first_available_image(urls: list[str]) -> Image.Image | None:
    for url in urls:
        try:
            return _download_image(url)
        except (OSError, ValueError, URLError):
            continue

    return None


def _draw_centered_multiline(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    lines: list[
        tuple[str, ImageFont.FreeTypeFont | ImageFont.ImageFont, tuple[int, int, int]]
    ],
    line_spacing: int,
) -> None:
    x1, y1, x2, y2 = box
    line_boxes = [draw.textbbox((0, 0), line, font=font) for line, font, _fill in lines]
    line_sizes = [(bbox[2] - bbox[0], bbox[3] - bbox[1]) for bbox in line_boxes]
    total_h = sum(height for _width, height in line_sizes) + line_spacing * (len(lines) - 1)
    cursor_y = y1 + ((y2 - y1) - total_h) // 2

    for (line, font, fill), bbox, (text_w, text_h) in zip(lines, line_boxes, line_sizes):
        x = x1 + ((x2 - x1) - text_w) // 2 - bbox[0]
        y = cursor_y - bbox[1]
        draw.text((x, y), line, font=font, fill=fill)
        cursor_y += text_h + line_spacing


def _format_minutes_since(value: datetime | None, now: datetime) -> str | None:
    if value is None:
        return None

    minutes = max(0, int((now - value.astimezone(timezone.utc)).total_seconds() // 60))
    if minutes < 60:
        return f"{minutes}분 전 종료"

    hours = minutes // 60
    rest = minutes % 60
    if hours < 24 and rest:
        return f"{hours}시간 {rest}분 전 종료"
    if hours < 24:
        return f"{hours}시간 전 종료"

    days = hours // 24
    return f"{days}일 전 종료"


def _draw_live_label(tile: Image.Image, label: str) -> Image.Image:
    overlay = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _load_font(38, bold=True)
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


def _make_offline_tile(status: MachineStatus, now: datetime) -> Image.Image:
    tile = Image.new("RGB", (TILE_W, TILE_H), (0, 0, 0))
    draw = ImageDraw.Draw(tile)
    main_font = _load_font(58, bold=True)
    meta_font = _load_font(38)
    lines = [
        (status.label, main_font, (255, 255, 255)),
        ("오프라인", main_font, (255, 255, 255)),
    ]
    last_ended_text = _format_minutes_since(status.last_ended_at, now)

    if last_ended_text:
        lines.append((last_ended_text, meta_font, (210, 210, 210)))

    _draw_centered_multiline(
        draw=draw,
        box=(0, 0, TILE_W, TILE_H),
        lines=lines,
        line_spacing=22,
    )
    return tile


def _make_thumbnail_tile(status: MachineStatus, now: datetime) -> Image.Image:
    if status.is_live:
        image = _download_first_available_image(_thumbnail_urls(status))
        if image is not None:
            tile = ImageOps.fit(
                image,
                (TILE_W, TILE_H),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            return _draw_live_label(tile, status.label)

        tile = Image.new("RGB", (TILE_W, TILE_H), (20, 20, 20))
        draw = ImageDraw.Draw(tile)
        font = _load_font(54, bold=True)
        _draw_centered_multiline(
            draw=draw,
            box=(0, 0, TILE_W, TILE_H),
            lines=[
                (status.label, font, (255, 255, 255)),
                ("라이브", font, (255, 255, 255)),
                ("썸네일 없음", font, (255, 255, 255)),
            ],
            line_spacing=16,
        )
        return tile

    return _make_offline_tile(status, now)


def build_gameplaza_thumbnail_board(
    statuses: list[MachineStatus],
    timestamp: str,
    now: datetime | None = None,
) -> BytesIO:
    now = now or datetime.now(timezone.utc)
    canvas = Image.new("RGB", (IMG_W, IMG_H), (0, 0, 0))

    for index, status in enumerate(statuses[: COLS * ROWS]):
        row = index // COLS
        col = index % COLS
        x = BORDER + col * (TILE_W + BORDER)
        y = BORDER + row * (TILE_H + BORDER)
        tile = _make_thumbnail_tile(status, now)
        canvas.paste(tile, (x, y))

    draw = ImageDraw.Draw(canvas)
    banner_y = GRID_H
    draw.rectangle((0, banner_y, IMG_W, IMG_H), fill=(0, 0, 0))
    left_text = f"{timestamp} KST  @광주 게임플라자"
    right_text = "generated by @밀크봇"
    font = _load_font(34)
    left_bbox = draw.textbbox((0, 0), left_text, font=font)
    right_bbox = draw.textbbox((0, 0), right_text, font=font)
    left_h = left_bbox[3] - left_bbox[1]
    right_w = right_bbox[2] - right_bbox[0]
    right_h = right_bbox[3] - right_bbox[1]
    margin_x = 30
    left_y = banner_y + (BANNER_H - left_h) // 2 - left_bbox[1]
    right_y = banner_y + (BANNER_H - right_h) // 2 - right_bbox[1]

    draw.text(
        (margin_x - left_bbox[0], left_y),
        left_text,
        font=font,
        fill=(255, 255, 255),
    )
    draw.text(
        (IMG_W - margin_x - right_w - right_bbox[0], right_y),
        right_text,
        font=font,
        fill=(255, 255, 255),
    )

    output = BytesIO()
    canvas.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    output.seek(0)
    return output
