from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from PIL import Image, ImageDraw, ImageFont, ImageOps

from youtube_live import GameplazaLiveSlot


BOARD_COLUMNS = 4
BOARD_ROWS = 2
CELL_SIZE = (512, 288)
BOARD_SIZE = (BOARD_COLUMNS * CELL_SIZE[0], BOARD_ROWS * CELL_SIZE[1])


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_candidates = (
        Path("C:/Windows/Fonts/malgunbd.ttf"),
        Path("C:/Windows/Fonts/malgun.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
        Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    )

    for path in font_candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)

    return ImageFont.load_default()


def _text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def _fit_thumbnail(image: Image.Image) -> Image.Image:
    return ImageOps.fit(
        image.convert("RGB"),
        CELL_SIZE,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def _download_thumbnail(url: str) -> Image.Image | None:
    try:
        with urlopen(url, timeout=10) as response:
            return Image.open(BytesIO(response.read()))
    except (OSError, URLError):
        return None


def _draw_text_with_shadow(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    anchor: str,
) -> None:
    x, y = position
    draw.text((x + 2, y + 2), text, fill=(0, 0, 0), font=font, anchor=anchor)
    draw.text(position, text, fill=(255, 255, 255), font=font, anchor=anchor)


def _draw_offline_cell(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    label_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    offline_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    draw.rectangle((x, y, x + CELL_SIZE[0], y + CELL_SIZE[1]), fill=(0, 0, 0))
    center_x = x + CELL_SIZE[0] // 2
    center_y = y + CELL_SIZE[1] // 2
    _draw_text_with_shadow(draw, (center_x, center_y - 18), label, label_font, "mm")
    _draw_text_with_shadow(draw, (center_x, center_y + 28), "오프라인", offline_font, "mm")


def _draw_corner_label(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    text_width, text_height = _text_size(draw, label, font)
    horizontal_padding = 18
    vertical_padding = 8
    box_width = min(CELL_SIZE[0], text_width + horizontal_padding * 2)
    box_height = text_height + vertical_padding * 2
    left = x + CELL_SIZE[0] - box_width
    top = y + CELL_SIZE[1] - box_height

    draw.rectangle(
        (left, top, x + CELL_SIZE[0], y + CELL_SIZE[1]),
        fill=(0, 0, 0),
    )
    _draw_text_with_shadow(
        draw,
        (x + CELL_SIZE[0] - horizontal_padding, top + box_height // 2),
        label,
        font,
        "rm",
    )


def build_gameplaza_thumbnail_board(slots: list[GameplazaLiveSlot]) -> BytesIO:
    board = Image.new("RGB", BOARD_SIZE, (0, 0, 0))
    draw = ImageDraw.Draw(board)
    label_font = _load_font(30)
    offline_font = _load_font(28)
    corner_font = _load_font(24)

    for index, slot in enumerate(slots[: BOARD_COLUMNS * BOARD_ROWS]):
        x = (index % BOARD_COLUMNS) * CELL_SIZE[0]
        y = (index // BOARD_COLUMNS) * CELL_SIZE[1]

        thumbnail = None
        if slot.video and slot.video.thumbnail_url:
            thumbnail = _download_thumbnail(slot.video.thumbnail_url)

        if thumbnail:
            board.paste(_fit_thumbnail(thumbnail), (x, y))
            _draw_corner_label(draw, x, y, slot.label, corner_font)
        else:
            _draw_offline_cell(draw, x, y, slot.label, label_font, offline_font)

    buffer = BytesIO()
    board.save(buffer, format="PNG", optimize=True)
    buffer.seek(0)
    return buffer
