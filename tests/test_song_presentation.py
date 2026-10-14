import unittest
from unittest.mock import patch

from song_presentation import enrich_song_catalog, format_song_constants
from song_search import search_chart


def sheet(type_, difficulty, constant, **extra):
    return dict(type=type_, difficulty=difficulty, internalLevelValue=constant,
                regions={'intl': True}, **extra)


class SongPresentationTests(unittest.TestCase):
    def test_current_type_first_and_fixed_difficulty_order(self):
        chart = {'sheets': [sheet('std', 'master', 14.3), sheet('dx', 'master', 14.6),
                           sheet('dx', 'expert', 12.7), sheet('dx', 'basic', 5),
                           sheet('dx', 'advanced', 7), sheet('std', 'basic', 4)]}
        self.assertEqual(format_song_constants(chart, 'dx'), '[DX] 5.0 / 7.0 / 12.7 / 14.6\n[ST] 4.0 / 14.3')
        self.assertTrue(format_song_constants(chart, 'std').startswith('[ST]'))
        self.assertNotIn('|', format_song_constants(chart, 'dx'))

    def test_separate_utage_and_buddy_entries_are_joined(self):
        songs = [{'title': 'Song', 'sheets': [sheet('dx', 'master', 13.8)]},
                 {'title': '[X]Song', 'comment': '', 'sheets': [sheet('utage', '【X】', 13.6, level='13+?')]},
                 {'title': '[協]Song', 'comment': '【🤝バディ】test',
                  'sheets': [sheet('utage', '【協】', 14, level='14?')]}]
        enriched = enrich_song_catalog(songs)
        self.assertEqual(format_song_constants(enriched[0], 'dx'), '[DX] 13.8\n[X] 13+\n[協] 14 🤝')
        self.assertEqual(len(songs[0]['sheets']), 1)
        self.assertNotIn('all_sheets', songs[0])

    def test_region_overrides_and_unavailable_charts(self):
        chart = {'sheets': [sheet('dx', 'master', 14.2,
                                 regionOverrides={'intl': {'internalLevelValue': 13.9}}),
                           dict(type='std', difficulty='master', internalLevelValue=15,
                                regions={'intl': False})]}
        self.assertEqual(format_song_constants(chart, 'dx'), '[DX] 13.9')

    def test_random_filter_keeps_all_chart_metadata(self):
        song = dict(category='maimai', title='Song', artist='A', bpm=120, imageName='cover.png',
                    version='V', isLocked=False, comment=None,
                    sheets=[sheet('dx', 'basic', 5), sheet('dx', 'master', 14), sheet('std', 'master', 13)])
        with patch('song_search.get_data', return_value=([song], None)):
            result = search_chart(type_=['dx'], difficulty=['master'])[0]
        self.assertEqual(len(result['sheets']), 1)
        self.assertEqual(format_song_constants(result, 'dx'), '[DX] 5.0 / 14.0\n[ST] 13.0')

    def test_random_selected_constant_matches_international_summary(self):
        song = dict(category='maimai', title='Song', artist='A', bpm=120, imageName='cover.png',
                    version='V', isLocked=False, comment=None,
                    sheets=[sheet('dx', 'master', 14.2,
                                  regionOverrides={'intl': {'internalLevelValue': 13.9}})])
        with patch('song_search.get_data', return_value=([song], None)):
            result = search_chart(difficulty=['master'], diff_max=14)[0]
        self.assertEqual(result['sheets'][0]['internalLevelValue'], 13.9)
        self.assertEqual(format_song_constants(result, 'dx'), '[DX] 13.9')


if __name__ == '__main__':
    unittest.main()
