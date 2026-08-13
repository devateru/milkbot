from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import discord
from discord import app_commands

from maishift.client import MaishiftClient
from maishift.repository import MaishiftRepository
from maishift_commands import build_maishift_rating_embed, register_maishift_commands
from tests.test_maishift_repository import sample_snapshot


class MaishiftCommandTests(unittest.TestCase):
    def test_all_slash_commands_are_registered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = MaishiftRepository(Path(directory) / "state.sqlite3")
            bot = discord.Client(intents=discord.Intents.none())
            tree = app_commands.CommandTree(bot)
            try:
                register_maishift_commands(tree, repository, MaishiftClient())
                names = {command.name for command in tree.get_commands()}
                self.assertTrue(
                    {
                        "마이시프트추적",
                        "마이시프트추적해제",
                        "마이시프트추적목록",
                        "마이시프트레이팅",
                    }.issubset(names)
                )
            finally:
                repository.close()

    def test_rating_embed_contains_section_sums_and_kst_time(self) -> None:
        snapshot = sample_snapshot()
        embed = build_maishift_rating_embed(snapshot).to_dict()
        fields = {field["name"]: field["value"] for field in embed["fields"]}
        self.assertEqual(fields["레이팅"], "**300**")
        self.assertEqual(fields["신곡 레이팅"], "300 / 1곡")
        self.assertEqual(fields["구곡 레이팅"], "0 / 0곡")
        self.assertIn("게임 버전", fields)

    def test_rating_embed_rejects_integrity_mismatch(self) -> None:
        snapshot = sample_snapshot()
        object.__setattr__(snapshot, "total_rating", 999)
        with self.assertRaises(ValueError):
            build_maishift_rating_embed(snapshot)
