from __future__ import annotations

import io
import unittest

from PIL import Image

from emoji_text import (
    EmojiTextError,
    ApplicationEmojiStore,
    decode_escapes,
    render_emoji_text,
    render_emoji_output_parts,
    split_output_messages,
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
            self.assertEqual(image.size, (128, 128))

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

    def test_each_visible_grapheme_becomes_a_separate_emoji_image(self) -> None:
        parts = render_emoji_output_parts(r"AB\nA", background="white")
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[2].literal, "\n")
        self.assertEqual(parts[0].image, parts[3].image)
        for part in (parts[0], parts[1], parts[3]):
            self.assertIsNotNone(part.image)
            with Image.open(io.BytesIO(part.image)) as image:
                self.assertEqual(image.size, (128, 128))

    def test_compressed_output_is_exactly_one_emoji_image(self) -> None:
        parts = render_emoji_output_parts("MILK", compress=True)
        self.assertEqual(len(parts), 1)
        self.assertIsNotNone(parts[0].image)

    def test_splits_long_emoji_markup_without_breaking_tokens(self) -> None:
        self.assertEqual(split_output_messages(["123", "456", "789"], limit=6), ["123456", "789"])


class FakeEmoji:
    def __init__(self, name: str, emoji_id: int) -> None:
        self.name = name
        self.id = emoji_id
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True

    def __str__(self) -> str:
        return f"<:{self.name}:{self.id}>"


class FakeClient:
    def __init__(self) -> None:
        self.created: list[FakeEmoji] = []

    async def create_application_emoji(self, *, name: str, image: bytes) -> FakeEmoji:
        emoji = FakeEmoji(name, 100 + len(self.created))
        self.created.append(emoji)
        return emoji


class ApplicationEmojiStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_images_and_evicts_least_recently_used(self) -> None:
        client = FakeClient()
        store = ApplicationEmojiStore(client)  # type: ignore[arg-type]
        old = FakeEmoji("milktext_old", 1)
        recent = FakeEmoji("milktext_recent", 2)
        store.cache_limit = 2
        store._loaded = True
        store._total_count = 2
        store._managed = {old.name: old, recent.name: recent}
        store._last_used = {old.name: 10.0, recent.name: 20.0}

        created = await store.get_or_create(b"new image")
        reused = await store.get_or_create(b"new image")

        self.assertTrue(old.deleted)
        self.assertFalse(recent.deleted)
        self.assertIs(created, reused)
        self.assertEqual(len(client.created), 1)


if __name__ == "__main__":
    unittest.main()
