import os
import runpy
import unittest
from unittest.mock import AsyncMock, Mock, patch

from song_lookup import SongLookup


class SongCommandTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # Register commands locally; never connect to Discord or read secrets.
        with patch.dict(os.environ, {'DISCORD_TOKEN': 'test', 'BOT_DEVELOPER_ID': '1'}), \
                patch('discord.Client.run'), patch('dotenv.load_dotenv'):
            cls.namespace = runpy.run_path('bot.py', run_name='bot_test')
        cls.command = cls.namespace['tree'].get_command('곡검색')

    def setUp(self):
        self.index = SongLookup([{
            'title': 'Magical Flavor', 'artist': 'Artist', 'imageName': 'cover.png',
            'sheets': [{'type': 'dx', 'difficulty': 'master',
                        'internalLevelValue': 13.2, 'regions': {'intl': True}}],
        }], [])
        self.command.callback.__globals__['_song_lookup'] = self.index

    def test_command_options(self):
        song, difficulty = self.command.parameters
        self.assertEqual(song.display_name, '곡')
        self.assertTrue(song.autocomplete)
        self.assertEqual(difficulty.display_name, '난이도')
        self.assertEqual(len(difficulty.choices), 5)

    async def test_search_sends_embed_without_reroll_and_explains_fallback(self):
        interaction = Mock()
        interaction.response.send_message = AsyncMock()
        option = self.index.autocomplete('magical')[0]
        await self.command.callback(interaction, option['value'], 'remaster')
        payload = interaction.response.send_message.call_args.kwargs
        self.assertEqual([button.label for button in payload['view'].children], ['노트 배점'])
        embed = payload['embed']
        self.assertIn('Magical Flavor', embed.title)
        self.assertEqual(embed.fields[0].name, 'MASTER 13.2')
        self.assertTrue(embed.fields[0].value)
        self.assertIn('Re:MASTER', embed.footer.text)

    async def test_note_button_displays_selected_sheet_and_missing_data_message(self):
        chart = {'title': 'Song', 'artist': 'Artist', 'imageName': 'cover.png'}
        sheet = {'type': 'dx', 'difficulty': 'master', 'internalLevelValue': 13.2,
                 'noteCounts': {'tap': 995, 'hold': 0, 'slide': 0, 'touch': 0, 'break': 1}}
        view = self.namespace['SongResultView'](user_id=1, current_chart=chart, current_p1_sheet=sheet)
        interaction = Mock()
        interaction.response.send_message = AsyncMock()
        await view.note_scores.callback(interaction)
        payload = interaction.response.send_message.call_args.kwargs
        self.assertTrue(payload['ephemeral'])
        embed = payload['embeds'][0]
        self.assertIn('[DX]', embed.description)
        self.assertIn('MASTER 13.2', embed.description)
        self.assertIn('5개 이하', embed.fields[2].value)
        self.assertEqual(embed.thumbnail.url, self.namespace['COVER_BASE_URL'] + 'cover.png')
        self.assertLessEqual(len(embed), 6000)
        sheet.pop('noteCounts')
        await view.note_scores.callback(interaction)
        payload = interaction.response.send_message.call_args.kwargs
        self.assertEqual(payload['embeds'], [])
        self.assertIn('노트 수 데이터', payload['content'])

    async def test_reroll_updates_note_button_and_two_player_charts(self):
        first = {'title': 'Before', 'artist': 'A', 'imageName': 'before.png'}
        second = {'title': 'After', 'artist': 'A', 'imageName': 'after.png'}
        sheet = {'type': 'std', 'difficulty': 'master', 'internalLevelValue': 13.0,
                 'noteCounts': {'tap': 100, 'hold': 0, 'slide': 0, 'touch': None, 'break': 1}}
        p2 = {**sheet, 'difficulty': 'expert'}
        view = self.namespace['RandomSongResultView'](user_id=1, results=[second],
                    current_chart=first, current_p1_sheet=sheet, current_p2_sheet=None)
        self.assertIn('노트 배점', [b.label for b in view.children])
        self.assertEqual([b.label for b in view.children], ['노트 배점', '다시 뽑기'])
        interaction = Mock()
        interaction.response.edit_message = AsyncMock()
        interaction.response.send_message = AsyncMock()
        with patch.dict(self.namespace['make_song_embed'].__globals__,
                        {'choose_chart': Mock(return_value=(second, sheet, p2))}):
            await view.reroll.callback(interaction)
        await view.note_scores.callback(interaction)
        embeds = interaction.response.send_message.call_args.kwargs['embeds']
        self.assertEqual(len(embeds), 2)
        self.assertTrue(all('After' in e.title for e in embeds))
        self.assertIn('1P', embeds[0].description)
        self.assertIn('2P', embeds[1].description)
        self.assertIn('EXPERT', embeds[1].description)

    def test_note_score_layout_is_compact_and_converts_break_losses_to_taps(self):
        chart = {'title': 'Song', 'artist': 'x0o0x_', 'imageName': 'cover.png'}
        sheet = {'type': 'dx', 'difficulty': 'master', 'internalLevelValue': 12.8,
                 'noteCounts': {'tap': 382, 'hold': 38, 'slide': 135, 'touch': 44, 'break': 6, 'total': 605}}
        embed = self.namespace['make_note_score_embed'](chart, sheet)
        self.assertEqual(len(embed.fields), 4)
        self.assertEqual(embed.fields[1].name, '1개당 배점')
        self.assertIn('TAP / TOUCH = 1 TAP = 0.1067%', embed.fields[1].value)
        self.assertIn('BREAK = 5 + **1.56** TAP = **0.7003%**', embed.fields[1].value)
        self.assertNotIn('MISS', embed.fields[2].value)
        self.assertIn('PERFECT (±2F): −0.0417% = 0.4 TAP', embed.fields[3].value)
        self.assertIn('PERFECT (±3F): −0.0833%', embed.fields[3].value)
        self.assertIn('GREAT = −0.2 TAP', embed.footer.text)

    def test_shared_song_embed_keeps_design_and_shows_constants_below_selection(self):
        chart = {'title': 'Song', 'artist': 'A', 'imageName': 'cover.png',
                 'sheets': [{'type': 'dx', 'difficulty': 'basic', 'internalLevelValue': 5.0},
                            {'type': 'dx', 'difficulty': 'master', 'internalLevelValue': 14.6},
                            {'type': 'std', 'difficulty': 'master', 'internalLevelValue': 14.3}]}
        selected = chart['sheets'][1]
        embed = self.namespace['make_song_embed'](chart, selected, None)
        self.assertEqual(embed.description, 'A')
        self.assertEqual(embed.fields[0].name, 'MASTER 14.6')
        self.assertEqual(embed.fields[0].value, '[DX] 5.0 / 14.6\n[ST] 14.3')
        self.assertEqual(embed.thumbnail.url, self.namespace['COVER_BASE_URL'] + 'cover.png')

    async def test_manual_text_is_rejected_instead_of_random_selection(self):
        interaction = Mock()
        interaction.response.send_message = AsyncMock()
        await self.command.callback(interaction, 'Magical Flavor')
        payload = interaction.response.send_message.call_args.kwargs
        self.assertTrue(payload['ephemeral'])
        self.assertNotIn('embed', payload)


if __name__ == '__main__':
    unittest.main()
