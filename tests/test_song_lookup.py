import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from song_lookup import SongLookup, load_song_lookup


def sheet(type_, difficulty='master', **kwargs):
    return dict(type=type_, difficulty=difficulty, regions={'intl': True}, **kwargs)


class SongLookupTests(unittest.TestCase):
    def test_alias_title_can_differ_from_catalog_title(self):
        index = SongLookup([{'title': 'トルコ行進曲 - オワタ＼(^o^)／', 'sheets': [sheet('std')]}], [
            {'title': 'トルコ行進 - オワタ＼(^o^)／',
             'aliases': ['トルコ行進曲 - オワタ＼(^o^)／', '터키 행진곡']},
        ])
        self.assertEqual(index.autocomplete('터키 행진곡')[0]['name'], '[ST] トルコ行進曲 - オワタ＼(^o^)／')

    def test_aliases_do_not_leak_to_distinct_remix(self):
        index = SongLookup([{'title': title, 'sheets': [sheet('std')]}
                            for title in ['Original', 'Original (Remix)']], [
            {'title': 'Original', 'aliases': ['약칭', 'Original (Remix)']},
        ])
        self.assertEqual([o['name'] for o in index.autocomplete('약칭')], ['[ST] Original'])

    def test_local_json_changes_are_reloaded_without_fetching_song_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'aliases.json'
            path.write_text('[]', encoding='utf-8')
            with patch('song_lookup.get_data', return_value=(self.songs, None)) as get_data:
                index = load_song_lookup(path)
                self.assertFalse(index.autocomplete('새로운별칭'))
                path.write_text(json.dumps([{'title': 'Magical Flavor', 'aliases': ['새로운별칭']}]), encoding='utf-8')
                self.assertEqual(len(index.autocomplete('새로운별칭')), 2)
                get_data.assert_called_once()

    def setUp(self):
        self.songs = [
            {'title': 'Magical Flavor', 'songId': 'magical',
             'sheets': [sheet('dx'), sheet('std'), sheet('std', 'remaster')]},
            {'title': '星★', 'songId': 'star', 'sheets': [sheet('dx')]},
            {'title': 'Only Standard', 'songId': 'standard', 'sheets': [sheet('std')]},
        ]
        self.index = SongLookup(self.songs, [
            {'title': 'Magical Flavor', 'aliases': ['매지컬 플레이버']},
            {'title': '星★', 'aliases': ['별노래', 'ほし']},
        ])

    def test_autocomplete_lists_types_once_not_difficulties(self):
        options = self.index.autocomplete('MAGICAL-fl')
        self.assertEqual([o['name'] for o in options],
                         ['[DX] Magical Flavor', '[ST] Magical Flavor'])
        self.assertNotEqual(options[0]['value'], options[1]['value'])
        self.assertEqual([o['name'] for o in self.index.autocomplete('only standard')],
                         ['[ST] Only Standard'])

    def test_alias_partial_initials_and_kana(self):
        for query in ['매지컬', 'ㅁㅈㅋ', '매 지 컬', 'ｍａｇｉｃａｌ', 'magicl flavor']:
            self.assertEqual(len(self.index.autocomplete(query)), 2, query)
        self.assertEqual(self.index.autocomplete('ホシ')[0]['name'], '[DX] 星★')
        self.assertEqual(self.index.autocomplete('별노')[0]['name'], '[DX] 星★')

    def test_remaster_fallback_stays_on_selected_type(self):
        dx, st = self.index.autocomplete('Magical Flavor')
        song, selected, fallback = self.index.select(dx['value'], 'remaster')
        self.assertEqual(selected['type'], 'dx')
        self.assertEqual(selected['difficulty'], 'master')
        self.assertTrue(fallback)
        _, selected, fallback = self.index.select(st['value'], 'remaster')
        self.assertEqual(selected['difficulty'], 'remaster')
        self.assertFalse(fallback)

    def test_invalid_selection_and_missing_difficulty(self):
        with self.assertRaises(ValueError):
            self.index.select('Magical Flavor', 'master')
        with self.assertRaises(ValueError):
            self.index.select(self.index.autocomplete('Magical')[0]['value'], 'expert')

    def test_region_overrides_and_unavailable_charts(self):
        index = SongLookup([{'title': 'Song', 'sheets': [
            sheet('dx', internalLevelValue=13.5, regionOverrides={'intl': {'internalLevelValue': 13.2}}),
            dict(type='std', difficulty='master', regions={'intl': False}),
            sheet('utage'),
        ]}], [])
        options = index.autocomplete('Song')
        self.assertEqual(len(options), 1)
        self.assertEqual(index.select(options[0]['value'])[1]['internalLevelValue'], 13.2)

    def test_discord_limits_and_long_titles_roundtrip(self):
        index = SongLookup([{'title': 'あ' * 150 + str(i), 'sheets': [sheet('dx')]} for i in range(30)], [])
        options = index.autocomplete('')
        self.assertEqual(len(options), 25)
        self.assertTrue(all(len(o['name']) <= 100 and len(o['value']) <= 100 for o in options))
        self.assertGreater(len(index.select(options[0]['value'])[0]['title']), 100)


if __name__ == '__main__':
    unittest.main()
