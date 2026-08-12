from __future__ import annotations

import unittest

from PIL import Image

from emoji_text import (
    EmojiTextError,
    decode_escapes,
    render_emoji_text,
    split_graphemes,
)


class DecodeEscapesTests(unittest.TestCase):
    def test_decodes_common_and_unicode_escapes_without_corrupting_korean(self) -> None:
        self.assertEqual(
            decode_escapes(r"우유\nA\t\uD55C\x21\\"),
            "우유\nA\t한!\\",
        )

    def test_unknown_escape_remains_literal(self) -> None:
        self.assertEqual(decode_escapes(r"a\qb"), r"a\qb")

    def test_invalid_unicode_escape_is_rejected(self) -> None:
        with self.assertRaises(EmojiTextError):
            decode_escapes(r"\u12no")


class GraphemeTests(unittest.TestCase):
    def test_keeps_combining_and_zwj_sequences_together(self) -> None:
        self.assertEqual(split_graphemes("e\u0301👩‍💻"), ["e\u0301", "👩‍💻"])


class RenderEmojiTextTests(unittest.TestCase):
    def test_renders_individual_tiles_as_png(self) -> None:
        rendered = render_emoji_text("밀크", background="milk", font_style="sans")
        self.assertEqual(rendered.filename, "emoji-text.png")
        self.assertEqual(rendered.grapheme_count, 2)
        with Image.open(rendered.data) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreater(image.width, image.height)

    def test_compresses_full_content_into_square(self) -> None:
        rendered = render_emoji_text(r"MILK\nBOT", background="black", compress=True)
        with Image.open(rendered.data) as image:
            self.assertEqual(image.size, (256, 256))

    def test_renders_fire_as_animated_gif(self) -> None:
        rendered = render_emoji_text("HOT", background="black", effect="fire", compress=True)
        self.assertEqual(rendered.filename, "emoji-text-fire.gif")
        with Image.open(rendered.data) as image:
            self.assertEqual(image.format, "GIF")
            self.assertGreater(image.n_frames, 1)

    def test_rejects_too_many_characters(self) -> None:
        with self.assertRaises(EmojiTextError):
            render_emoji_text("a" * 65)

    def test_rejects_blank_and_excessive_lines(self) -> None:
        with self.assertRaises(EmojiTextError):
            render_emoji_text(r"\n\t")
        with self.assertRaises(EmojiTextError):
            render_emoji_text("x\n" * 12 + "x")


if __name__ == "__main__":
    unittest.main()
