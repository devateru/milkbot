from __future__ import annotations

import asyncio
import colorsys
import io
import math
import random
import re
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
COMPRESSED_SIZE = 256
MAX_OUTPUT_BYTES = 9_000_000

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
        "fonts/NotoSansKR-Regular.ttf",
        "C:/Windows/Fonts/malgun.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ),
    "bold": (
        "fonts/NotoSansKR-Bold.ttf",
        "C:/Windows/Fonts/malgunbd.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    "serif": (
        "C:/Windows/Fonts/batang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/truetype/nanum/NanumMyeongjo.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    ),
    "mono": (
        "C:/Windows/Fonts/consola.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicCoding.ttf",
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
    return ImageFont.truetype(_font_path(style), size=size)


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
        draw.rounded_rectangle((2, 2, 253, 253), radius=48, fill=background)
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


def _fire_frame(base: Image.Image, frame_index: int) -> Image.Image:
    flames = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(flames)
    rng = random.Random(6_500 + frame_index)
    width, height = base.size
    step = max(14, width // 28)
    baseline = height - max(5, height // 30)
    for x in range(-step, width + step, step):
        wave = math.sin((x / max(1, width)) * math.tau * 3 + frame_index * 0.8)
        flame_height = max(18, int(height * (0.09 + 0.055 * rng.random() + 0.025 * wave)))
        half = max(8, step)
        draw.polygon(
            [
                (x - half, baseline),
                (x - half // 2, baseline - flame_height // 2),
                (x + rng.randint(-half // 3, half // 3), baseline - flame_height),
                (x + half // 2, baseline - flame_height // 2),
                (x + half, baseline),
            ],
            fill=(255, 74, 20, 220),
        )
        inner_height = int(flame_height * 0.62)
        draw.ellipse(
            (x - half // 2, baseline - inner_height, x + half // 2, baseline + 2),
            fill=(255, 205, 45, 225),
        )
    flames = flames.filter(ImageFilter.GaussianBlur(max(1, min(base.size) // 180)))
    return Image.alpha_composite(base, flames)


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


def render_emoji_text(
    text: str,
    *,
    background: str = "transparent",
    font_style: str = "sans",
    effect: str = "none",
    compress: bool = False,
) -> RenderedEmojiText:
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
    color = BACKGROUND_COLORS[background]
    lines = _expanded_lines(decoded)
    if len(lines) > MAX_LINES:
        raise EmojiTextError(f"줄바꿈 후 최대 {MAX_LINES}줄까지 변환할 수 있어요.")

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
        frames = [_fire_frame(base, index) for index in range(10)]
    return RenderedEmojiText(_save_gif(frames), f"emoji-text-{effect}.gif", grapheme_count)


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
    @tree.command(name="글자이모지", description="문자열을 글자별 이모지 이미지 또는 한 개의 이모지로 만듭니다.")
    @app_commands.describe(
        text=r"변환할 내용 (\n, \t, \\, \uNNNN 사용 가능)",
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
            rendered = await asyncio.to_thread(
                render_emoji_text,
                text,
                background=background.value if background else "transparent",
                font_style=font.value if font else "sans",
                effect=effect.value if effect else "none",
                compress=compress,
            )
        except EmojiTextError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            await interaction.followup.send(
                "이모지 이미지를 만드는 중 오류가 발생했어요. 잠시 후 다시 시도해주세요.",
                ephemeral=True,
            )
            return
        file = discord.File(rendered.data, filename=rendered.filename)
        mode = "한 개로 압축" if compress else f"{rendered.grapheme_count}글자 변환"
        await interaction.followup.send(content=f"{mode} 완료!", file=file)
