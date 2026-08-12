from __future__ import annotations

import asyncio
import colorsys
import hashlib
import io
import json
import math
import os
import random
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import discord
from discord import app_commands
from PIL import Image, ImageDraw, ImageFilter, ImageFont


MAX_GRAPHEMES = 64
MAX_COLUMNS = 12
MAX_LINES = 12
MAX_CANVAS = 1600
TILE_SIZE = 112
TILE_GAP = 8
CANVAS_PADDING = 16
COMPRESSED_SIZE = 128
MAX_OUTPUT_BYTES = 256 * 1024
MANAGED_EMOJI_PREFIX = "milktext_"
APPLICATION_EMOJI_LIMIT = 2000
EMOJI_USAGE_FILE = Path("data/application_emoji_usage.json")

BACKGROUND_COLORS: dict[str, tuple[int, int, int, int]] = {
    "transparent": (0, 0, 0, 0),
    "milk": (255, 247, 230, 255),
    "black": (24, 24, 27, 255),
    "white": (255, 255, 255, 255),
    "pink": (255, 164, 196, 255),
    "blue": (91, 156, 255, 255),
    "green": (87, 190, 132, 255),
}

FONT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "sans": (
        "fonts/NotoSansKR-Variable.ttf",
        "C:/Windows/Fonts/malgun.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ),
    "bold": (
        "fonts/NotoSansKR-Variable.ttf",
        "C:/Windows/Fonts/malgunbd.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    "serif": (
        "C:/Windows/Fonts/batang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/truetype/nanum/NanumMyeongjo.ttf",
        "fonts/NotoSansKR-Variable.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    ),
    "mono": (
        "/usr/share/fonts/truetype/nanum/NanumGothicCoding.ttf",
        "C:/Windows/Fonts/D2Coding.ttf",
        "fonts/NotoSansKR-Variable.ttf",
        "C:/Windows/Fonts/consola.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ),
}


class EmojiTextError(ValueError):
    pass


@dataclass(frozen=True)
class RenderedEmojiText:
    data: io.BytesIO
    filename: str
    grapheme_count: int


@dataclass(frozen=True)
class EmojiOutputPart:
    literal: str | None = None
    image: bytes | None = None


class ApplicationEmojiStore:
    """Persistent, name-addressed cache backed by Discord application emojis."""

    def __init__(self, client: discord.Client) -> None:
        self.client = client
        try:
            configured_limit = int(os.getenv("MILK_EMOJI_CACHE_LIMIT", "1800"))
        except ValueError:
            configured_limit = 1800
        self.cache_limit = max(16, min(1900, configured_limit))
        self._lock = asyncio.Lock()
        self._loaded = False
        self._total_count = 0
        self._managed: dict[str, discord.Emoji] = {}
        self._last_used: dict[str, float] = {}

    def _load_usage(self) -> dict[str, float]:
        try:
            data = json.loads(EMOJI_USAGE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            str(name): float(timestamp)
            for name, timestamp in data.items()
            if isinstance(name, str) and isinstance(timestamp, (int, float))
        }

    @staticmethod
    def _write_usage(data: dict[str, float]) -> None:
        EMOJI_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = EMOJI_USAGE_FILE.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(EMOJI_USAGE_FILE)

    async def _load(self) -> None:
        if self._loaded:
            return
        emojis = await self.client.fetch_application_emojis()
        self._total_count = len(emojis)
        self._managed = {
            emoji.name: emoji
            for emoji in emojis
            if emoji.name and emoji.name.startswith(MANAGED_EMOJI_PREFIX)
        }
        self._last_used = {
            name: timestamp
            for name, timestamp in self._load_usage().items()
            if name in self._managed
        }
        self._loaded = True

    async def _make_room(self) -> None:
        while (
            len(self._managed) >= self.cache_limit
            or self._total_count >= APPLICATION_EMOJI_LIMIT
        ):
            if not self._managed:
                raise EmojiTextError(
                    "애플리케이션 이모지 슬롯이 가득 찼고 정리할 글자 이모지가 없어요."
                )
            least_recent = min(
                self._managed.values(),
                key=lambda emoji: (self._last_used.get(emoji.name, 0.0), emoji.id),
            )
            await least_recent.delete()
            self._managed.pop(least_recent.name, None)
            self._last_used.pop(least_recent.name, None)
            self._total_count -= 1

    async def get_or_create(self, image: bytes) -> discord.Emoji:
        digest = hashlib.sha256(image).hexdigest()[:20]
        name = f"{MANAGED_EMOJI_PREFIX}{digest}"
        async with self._lock:
            await self._load()
            cached = self._managed.get(name)
            if cached is not None:
                self._last_used[name] = time.time()
                return cached
            await self._make_room()
            emoji = await self.client.create_application_emoji(name=name, image=image)
            self._managed[name] = emoji
            self._last_used[name] = time.time()
            self._total_count += 1
            return emoji

    async def flush_usage(self) -> None:
        async with self._lock:
            if not self._loaded:
                return
            snapshot = dict(self._last_used)
        await asyncio.to_thread(self._write_usage, snapshot)


def decode_escapes(value: str) -> str:
    """Decode common escapes without corrupting already-decoded Unicode text."""
    simple = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "b": "\b",
        "f": "\f",
        "0": "\0",
        "\\": "\\",
        '"': '"',
        "'": "'",
    }
    result: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "\\":
            result.append(value[index])
            index += 1
            continue
        if index + 1 >= len(value):
            result.append("\\")
            break
        marker = value[index + 1]
        if marker in simple:
            result.append(simple[marker])
            index += 2
            continue
        widths = {"x": 2, "u": 4, "U": 8}
        if marker in widths:
            width = widths[marker]
            digits = value[index + 2 : index + 2 + width]
            if len(digits) != width or not re.fullmatch(r"[0-9a-fA-F]+", digits):
                raise EmojiTextError(f"잘못된 이스케이프 시퀀스예요: `\\{marker}{digits}`")
            codepoint = int(digits, 16)
            if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
                raise EmojiTextError(f"유효하지 않은 유니코드 코드 포인트예요: `U+{codepoint:04X}`")
            result.append(chr(codepoint))
            index += width + 2
            continue
        # Unknown escapes remain literal, like normal chat input.
        result.extend(("\\", marker))
        index += 2
    return "".join(result)


def split_graphemes(value: str) -> list[str]:
    """Dependency-free splitter for combining marks and emoji ZWJ runs."""
    graphemes: list[str] = []
    join_next = False
    for char in value:
        codepoint = ord(char)
        is_modifier = (
            bool(unicodedata.combining(char))
            or 0xFE00 <= codepoint <= 0xFE0F
            or 0x1F3FB <= codepoint <= 0x1F3FF
            or char == "\u20e3"
        )
        if graphemes and (is_modifier or join_next or char == "\u200d"):
            graphemes[-1] += char
        else:
            graphemes.append(char)
        join_next = char == "\u200d"
    return graphemes


def _expanded_lines(value: str) -> list[list[str]]:
    value = value.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    lines: list[list[str]] = []
    for raw_line in value.split("\n"):
        graphemes = split_graphemes(raw_line)
        if not graphemes:
            lines.append([])
            continue
        lines.extend(
            graphemes[start : start + MAX_COLUMNS]
            for start in range(0, len(graphemes), MAX_COLUMNS)
        )
    return lines


def _font_path(style: str) -> str:
    for candidate in FONT_CANDIDATES.get(style, FONT_CANDIDATES["sans"]):
        if Path(candidate).is_file():
            return candidate
    raise EmojiTextError(
        "사용 가능한 폰트를 찾지 못했어요. 서버에 Noto Sans CJK 또는 나눔글꼴을 설치해주세요."
    )


def _font(style: str, size: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(_font_path(style), size=size)
    try:
        font.set_variation_by_name("Bold" if style == "bold" else "Regular")
    except (AttributeError, OSError):
        pass
    return font


def _foreground(background: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if background[3] == 0:
        return (255, 255, 255, 255)
    luminance = 0.2126 * background[0] + 0.7152 * background[1] + 0.0722 * background[2]
    return (25, 25, 28, 255) if luminance > 165 else (255, 255, 255, 255)


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
) -> None:
    left, top, right, bottom = box
    stroke_width = max(1, font.size // 22)
    stroke_fill = (0, 0, 0, 190) if fill[0] > 150 else (255, 255, 255, 180)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    x = left + (right - left - width) / 2 - bbox[0]
    y = top + (bottom - top - height) / 2 - bbox[1]
    draw.text(
        (x, y), text, font=font, fill=fill,
        stroke_width=stroke_width, stroke_fill=stroke_fill,
    )


def _normal_base(
    lines: list[list[str]],
    background: tuple[int, int, int, int],
    font_style: str,
    foreground: tuple[int, int, int, int] | None = None,
) -> Image.Image:
    columns = max(1, max((len(line) for line in lines), default=1))
    rows = max(1, len(lines))
    natural_width = CANVAS_PADDING * 2 + columns * TILE_SIZE + (columns - 1) * TILE_GAP
    natural_height = CANVAS_PADDING * 2 + rows * TILE_SIZE + (rows - 1) * TILE_GAP
    scale = min(1.0, MAX_CANVAS / natural_width, MAX_CANVAS / natural_height)
    tile = max(28, round(TILE_SIZE * scale))
    gap = max(2, round(TILE_GAP * scale))
    padding = max(4, round(CANVAS_PADDING * scale))
    width = padding * 2 + columns * tile + (columns - 1) * gap
    height = padding * 2 + rows * tile + (rows - 1) * gap
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = _font(font_style, max(16, round(tile * 0.58)))
    fill = foreground or _foreground(background)
    for row, line in enumerate(lines):
        for column, grapheme in enumerate(line):
            x = padding + column * (tile + gap)
            y = padding + row * (tile + gap)
            box = (x, y, x + tile, y + tile)
            if background[3]:
                draw.rounded_rectangle(box, radius=max(4, tile // 5), fill=background)
            if not grapheme.isspace():
                _draw_centered_text(draw, box, grapheme, font, fill)
    return image


def _fit_compressed_font(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    style: str,
    available_width: int,
    available_height: int,
) -> tuple[ImageFont.FreeTypeFont, int]:
    for size in range(112, 11, -2):
        font = _font(style, size)
        spacing = max(2, size // 7)
        boxes = [draw.textbbox((0, 0), line or " ", font=font, stroke_width=max(1, size // 24)) for line in lines]
        width = max(box[2] - box[0] for box in boxes)
        height = sum(box[3] - box[1] for box in boxes) + spacing * (len(lines) - 1)
        if width <= available_width and height <= available_height:
            return font, spacing
    return _font(style, 12), 2


def _compressed_base(
    value: str,
    background: tuple[int, int, int, int],
    font_style: str,
    foreground: tuple[int, int, int, int] | None = None,
) -> Image.Image:
    image = Image.new("RGBA", (COMPRESSED_SIZE, COMPRESSED_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = 18
    if background[3]:
        draw.rounded_rectangle(
            (2, 2, COMPRESSED_SIZE - 3, COMPRESSED_SIZE - 3),
            radius=COMPRESSED_SIZE // 5,
            fill=background,
        )
    lines = value.replace("\r", "").expandtabs(4).split("\n")
    if len(lines) == 1 and len(split_graphemes(lines[0])) > 8:
        graphemes = split_graphemes(lines[0])
        wrap_at = max(4, math.ceil(math.sqrt(len(graphemes) * 1.45)))
        lines = ["".join(graphemes[i : i + wrap_at]) for i in range(0, len(graphemes), wrap_at)]
    font, spacing = _fit_compressed_font(
        draw, lines, font_style, COMPRESSED_SIZE - margin * 2, COMPRESSED_SIZE - margin * 2,
    )
    stroke_width = max(1, font.size // 24)
    boxes = [draw.textbbox((0, 0), line or " ", font=font, stroke_width=stroke_width) for line in lines]
    heights = [box[3] - box[1] for box in boxes]
    y = (COMPRESSED_SIZE - sum(heights) - spacing * (len(lines) - 1)) / 2
    fill = foreground or _foreground(background)
    for line, box, height in zip(lines, boxes, heights):
        width = box[2] - box[0]
        x = (COMPRESSED_SIZE - width) / 2 - box[0]
        stroke_fill = (0, 0, 0, 190) if fill[0] > 150 else (255, 255, 255, 180)
        draw.text(
            (x, y - box[1]), line, font=font, fill=fill,
            stroke_width=stroke_width, stroke_fill=stroke_fill,
        )
        y += height + spacing
    return image


def _add_glow(base: Image.Image) -> Image.Image:
    alpha = base.getchannel("A")
    glow = Image.new("RGBA", base.size, (91, 214, 255, 0))
    glow.putalpha(alpha.filter(ImageFilter.GaussianBlur(max(4, min(base.size) // 35))))
    return Image.alpha_composite(glow, base)


def _fire_anchors(mask: Image.Image) -> list[tuple[int, int]]:
    pixels = mask.load()
    width, height = mask.size
    step = max(3, width // 28)
    anchors: list[tuple[int, int]] = []
    for x in range(1, width - 1, step):
        visible = [y for y in range(1, height - 1) if pixels[x, y] > 80]
        if visible:
            anchors.append((x, min(visible)))
    return anchors


def _fire_frame(background: Image.Image, glyph_mask: Image.Image, frame_index: int) -> Image.Image:
    width, height = background.size
    scale = max(0.55, min(width, height) / 128)
    rng = random.Random(81_000 + frame_index)
    anchors = _fire_anchors(glyph_mask)

    # A hot halo and charred outline keep the glyph readable even when flames overlap it.
    glow_alpha = glyph_mask.filter(ImageFilter.GaussianBlur(max(3, round(7 * scale))))
    glow = Image.new("RGBA", background.size, (255, 54, 0, 0))
    glow.putalpha(glow_alpha.point(lambda value: min(150, value)))
    frame = Image.alpha_composite(background, glow)

    outline_mask = glyph_mask.filter(ImageFilter.MaxFilter(5))
    outline = Image.new("RGBA", background.size, (70, 8, 0, 0))
    outline.putalpha(outline_mask)
    frame = Image.alpha_composite(frame, outline)

    flames = Image.new("RGBA", background.size, (0, 0, 0, 0))
    flame_draw = ImageDraw.Draw(flames)
    for anchor_index, (x, y) in enumerate(anchors):
        if (anchor_index + frame_index) % 2 and rng.random() < 0.48:
            continue
        half_width = max(2, round(scale * rng.uniform(3.0, 6.0)))
        flame_height = max(7, round(scale * rng.uniform(12.0, 30.0)))
        lean = round(scale * math.sin(frame_index * 0.9 + x * 0.16) * 5)
        tip_x = x + lean + rng.randint(-2, 2)
        root_y = min(height - 1, y + max(2, round(4 * scale)))
        flame_draw.polygon(
            [
                (x - half_width, root_y),
                (x - half_width // 2, y - flame_height // 3),
                (tip_x, max(0, y - flame_height)),
                (x + half_width // 2, y - flame_height // 3),
                (x + half_width, root_y),
            ],
            fill=(202, 20, 0, 235),
        )
        inner_height = max(4, round(flame_height * 0.62))
        inner_half = max(1, half_width // 2)
        flame_draw.polygon(
            [
                (x - inner_half, root_y),
                (x, max(0, y - inner_height)),
                (x + inner_half, root_y),
            ],
            fill=(255, 214, 35, 245),
        )
    flames = flames.filter(ImageFilter.GaussianBlur(max(1, round(scale))))
    frame = Image.alpha_composite(frame, flames)

    # Molten red/orange fill with moving yellow hot spots, inspired by burning-logo art.
    molten = Image.new("RGBA", background.size, (0, 0, 0, 0))
    molten_draw = ImageDraw.Draw(molten)
    for y in range(height):
        phase = math.sin(y * 0.22 + frame_index * 0.75)
        molten_draw.line(
            (0, y, width, y),
            fill=(255, round(70 + 38 * (phase + 1) / 2), 5, 255),
        )
    for _ in range(max(18, width // 3)):
        x = rng.randrange(width)
        y = rng.randrange(height)
        radius = rng.choice((1, 1, 2, 3))
        molten_draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=(255, rng.randint(165, 245), rng.randint(20, 75), 255),
        )
    molten.putalpha(glyph_mask)
    frame = Image.alpha_composite(frame, molten)

    # Smoke and sparks rise above the hottest top edges.
    particles = Image.new("RGBA", background.size, (0, 0, 0, 0))
    particle_draw = ImageDraw.Draw(particles)
    if anchors:
        for _ in range(max(5, len(anchors) // 2)):
            x, y = rng.choice(anchors)
            rise = round(scale * rng.uniform(9, 34))
            drift = round(scale * math.sin(frame_index * 0.6 + x) * rng.uniform(2, 8))
            if rng.random() < 0.55:
                radius = max(1, round(scale * rng.uniform(1, 3)))
                particle_draw.ellipse(
                    (x + drift - radius, y - rise - radius, x + drift + radius, y - rise + radius),
                    fill=(45, 30, 28, rng.randint(70, 145)),
                )
            else:
                particle_draw.point((x + drift, max(0, y - rise)), fill=(255, 210, 35, 255))
    particles = particles.filter(ImageFilter.GaussianBlur(max(0.4, scale * 0.55)))
    return Image.alpha_composite(frame, particles)


def _save_png(image: Image.Image) -> io.BytesIO:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


def _save_gif(frames: list[Image.Image]) -> io.BytesIO:
    def to_gif_frame(frame: Image.Image) -> Image.Image:
        # Reserve palette index 255 exclusively for transparency. Passing
        # transparency=0 after a regular adaptive conversion can accidentally
        # erase a real color and produces cyan/magenta fringes.
        alpha = frame.getchannel("A")
        flattened = Image.new("RGB", frame.size, (0, 0, 0))
        flattened.paste(frame.convert("RGB"), mask=alpha)
        paletted = flattened.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
        transparent = alpha.point(lambda value: 255 if value < 32 else 0)
        paletted.paste(255, mask=transparent)
        palette = paletted.getpalette() or [0] * 768
        palette[255 * 3 : 255 * 3 + 3] = [0, 0, 0]
        paletted.putpalette(palette)
        return paletted

    def save(items: list[Image.Image]) -> io.BytesIO:
        output = io.BytesIO()
        paletted = [to_gif_frame(frame) for frame in items]
        paletted[0].save(
            output, format="GIF", save_all=True, append_images=paletted[1:],
            duration=90, loop=0, disposal=2, optimize=False, transparency=255,
        )
        output.seek(0)
        return output
    output = save(frames)
    if output.getbuffer().nbytes <= MAX_OUTPUT_BYTES:
        return output
    resized = [
        frame.resize((max(1, frame.width // 2), max(1, frame.height // 2)), Image.Resampling.LANCZOS)
        for frame in frames
    ]
    output = save(resized)
    if output.getbuffer().nbytes > MAX_OUTPUT_BYTES:
        raise EmojiTextError("GIF가 너무 커요. 글자 수를 줄이거나 효과를 `없음`으로 바꿔주세요.")
    return output


def _prepare_render(
    text: str,
    *,
    background: str,
    font_style: str,
    effect: str,
) -> tuple[str, int, list[list[str]]]:
    decoded = decode_escapes(text)
    if not decoded:
        raise EmojiTextError("내용을 한 글자 이상 입력해주세요.")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in decoded):
        raise EmojiTextError("줄바꿈과 탭 이외의 제어 문자는 사용할 수 없어요.")
    grapheme_count = len([g for g in split_graphemes(decoded) if g not in "\n\r"])
    if grapheme_count == 0 or not any(not char.isspace() for char in decoded):
        raise EmojiTextError("공백이 아닌 글자를 한 글자 이상 입력해주세요.")
    if grapheme_count > MAX_GRAPHEMES:
        raise EmojiTextError(f"내용은 최대 {MAX_GRAPHEMES}글자까지 변환할 수 있어요.")
    if background not in BACKGROUND_COLORS:
        raise EmojiTextError("지원하지 않는 배경색이에요.")
    if font_style not in FONT_CANDIDATES:
        raise EmojiTextError("지원하지 않는 폰트예요.")
    if effect not in {"none", "glow", "rainbow", "fire"}:
        raise EmojiTextError("지원하지 않는 효과예요.")
    lines = _expanded_lines(decoded)
    if len(lines) > MAX_LINES:
        raise EmojiTextError(f"줄바꿈 후 최대 {MAX_LINES}줄까지 변환할 수 있어요.")
    return decoded, grapheme_count, lines


def render_emoji_text(
    text: str,
    *,
    background: str = "transparent",
    font_style: str = "sans",
    effect: str = "none",
    compress: bool = False,
) -> RenderedEmojiText:
    decoded, grapheme_count, lines = _prepare_render(
        text,
        background=background,
        font_style=font_style,
        effect=effect,
    )
    color = BACKGROUND_COLORS[background]

    def make_base(foreground: tuple[int, int, int, int] | None = None) -> Image.Image:
        if compress:
            return _compressed_base(decoded, color, font_style, foreground)
        return _normal_base(lines, color, font_style, foreground)

    base = make_base()
    if effect == "none":
        return RenderedEmojiText(_save_png(base), "emoji-text.png", grapheme_count)
    if effect == "glow":
        return RenderedEmojiText(_save_png(_add_glow(base)), "emoji-text-glow.png", grapheme_count)
    if effect == "rainbow":
        frames = []
        for index in range(10):
            rgb = colorsys.hsv_to_rgb(index / 10, 0.72, 1.0)
            foreground = tuple(round(channel * 255) for channel in rgb) + (255,)
            frames.append(make_base(foreground))
    else:
        transparent = (0, 0, 0, 0)
        white = (255, 255, 255, 255)
        if compress:
            fire_background = _compressed_base(" ", color, font_style)
            glyph_mask = _compressed_base(decoded, transparent, font_style, white).getchannel("A")
        else:
            blank_lines = [[" " for _grapheme in line] for line in lines]
            fire_background = _normal_base(blank_lines, color, font_style)
            glyph_mask = _normal_base(lines, transparent, font_style, white).getchannel("A")
        frames = [_fire_frame(fire_background, glyph_mask, index) for index in range(12)]
    return RenderedEmojiText(_save_gif(frames), f"emoji-text-{effect}.gif", grapheme_count)


def render_emoji_output_parts(
    text: str,
    *,
    background: str = "transparent",
    font_style: str = "sans",
    effect: str = "none",
    compress: bool = False,
) -> list[EmojiOutputPart]:
    decoded, _grapheme_count, _lines = _prepare_render(
        text,
        background=background,
        font_style=font_style,
        effect=effect,
    )
    if compress:
        rendered = render_emoji_text(
            decoded,
            background=background,
            font_style=font_style,
            effect=effect,
            compress=True,
        )
        return [EmojiOutputPart(image=rendered.data.getvalue())]

    parts: list[EmojiOutputPart] = []
    rendered_by_grapheme: dict[str, bytes] = {}
    expanded = decoded.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    for grapheme in split_graphemes(expanded):
        if grapheme == "\n":
            parts.append(EmojiOutputPart(literal="\n"))
            continue
        if grapheme.isspace():
            parts.append(EmojiOutputPart(literal=" "))
            continue
        image = rendered_by_grapheme.get(grapheme)
        if image is None:
            rendered = render_emoji_text(
                grapheme,
                background=background,
                font_style=font_style,
                effect=effect,
                compress=True,
            )
            image = rendered.data.getvalue()
            rendered_by_grapheme[grapheme] = image
        parts.append(EmojiOutputPart(image=image))
    return parts


def split_output_messages(tokens: list[str], limit: int = 1900) -> list[str]:
    messages: list[str] = []
    current = ""
    for token in tokens:
        if len(current) + len(token) > limit and current:
            messages.append(current.rstrip())
            current = ""
        current += token
    if current:
        messages.append(current.rstrip())
    return [message for message in messages if message]


BACKGROUND_CHOICES = [
    app_commands.Choice(name="투명", value="transparent"),
    app_commands.Choice(name="우유색", value="milk"),
    app_commands.Choice(name="검정", value="black"),
    app_commands.Choice(name="흰색", value="white"),
    app_commands.Choice(name="분홍", value="pink"),
    app_commands.Choice(name="파랑", value="blue"),
    app_commands.Choice(name="초록", value="green"),
]
FONT_CHOICES = [
    app_commands.Choice(name="고딕", value="sans"),
    app_commands.Choice(name="굵은 고딕", value="bold"),
    app_commands.Choice(name="명조", value="serif"),
    app_commands.Choice(name="고정폭", value="mono"),
]
EFFECT_CHOICES = [
    app_commands.Choice(name="없음", value="none"),
    app_commands.Choice(name="네온 글로우", value="glow"),
    app_commands.Choice(name="무지개 GIF", value="rainbow"),
    app_commands.Choice(name="불꽃 GIF", value="fire"),
]


def register_emoji_text_command(tree: app_commands.CommandTree) -> None:
    emoji_store = ApplicationEmojiStore(tree.client)

    @tree.command(name="글자이모지", description="문자열을 실제 앱 이모지로 변환하거나 한 개에 압축합니다.")
    @app_commands.describe(
        text=r"변환할 내용 (\n 등 이스케이프 사용 가능)",
        background="이모지 타일의 배경색",
        font="글꼴",
        effect="정적/애니메이션 효과",
        compress="내용 전체를 이모지 한 개에 압축",
    )
    @app_commands.choices(background=BACKGROUND_CHOICES, font=FONT_CHOICES, effect=EFFECT_CHOICES)
    async def emoji_text_command(
        interaction: discord.Interaction,
        text: app_commands.Range[str, 1, 256],
        background: app_commands.Choice[str] | None = None,
        font: app_commands.Choice[str] | None = None,
        effect: app_commands.Choice[str] | None = None,
        compress: bool = False,
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            parts = await asyncio.to_thread(
                render_emoji_output_parts,
                text,
                background=background.value if background else "transparent",
                font_style=font.value if font else "sans",
                effect=effect.value if effect else "none",
                compress=compress,
            )
            output_tokens: list[str] = []
            for part in parts:
                if part.literal is not None:
                    output_tokens.append(part.literal)
                elif part.image is not None:
                    emoji = await emoji_store.get_or_create(part.image)
                    output_tokens.append(str(emoji))
            messages = split_output_messages(output_tokens)
        except EmojiTextError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except discord.HTTPException as exc:
            if exc.status == 429:
                message = "Discord 이모지 생성 제한에 도달했어요. 잠시 후 다시 시도해주세요."
            else:
                message = "Discord 애플리케이션 이모지를 만들지 못했어요. 잠시 후 다시 시도해주세요."
            await interaction.followup.send(message, ephemeral=True)
            return
        except Exception:
            await interaction.followup.send(
                "글자 이모지를 만드는 중 오류가 발생했어요. 잠시 후 다시 시도해주세요.",
                ephemeral=True,
            )
            return
        finally:
            try:
                await emoji_store.flush_usage()
            except OSError:
                pass

        for index, message in enumerate(messages):
            if index == 0:
                await interaction.followup.send(content=message)
            else:
                await interaction.followup.send(content=message, wait=True)
