from fractions import Fraction
import unittest

from note_scoring import calculate_note_scores


class NoteScoringTests(unittest.TestCase):
    def test_full_score_and_break_bonus(self):
        score = calculate_note_scores({'tap': 100, 'hold': 10, 'slide': 10, 'touch': None, 'break': 5, 'total': 125})
        self.assertEqual(score['weighted_total'], 175)
        self.assertEqual(score['maximum'], 101)
        self.assertEqual(score['per_note']['tap'], Fraction(100, 175))
        self.assertEqual(score['per_note']['break'], Fraction(500, 175) + Fraction(1, 5))
        self.assertEqual(sum(score['counts'][k] * v for k, v in score['per_note'].items()), 101)

    def test_rank_boundary_is_exact_and_limited_to_actual_taps(self):
        score = calculate_note_scores({'tap': 995, 'hold': 0, 'slide': 0, 'touch': 0, 'break': 1})
        # Weighted total 1000: one missed tap costs exactly 0.1 percentage point.
        self.assertEqual(score['miss_limits']['SSS+'], 5)
        self.assertEqual(score['miss_limits']['SSS'], 10)
        self.assertEqual(score['miss_limits']['S'], 40)
        score = calculate_note_scores({'tap': 1, 'hold': 1000, 'slide': 0, 'touch': 0, 'break': 1})
        self.assertEqual(score['miss_limits']['S'], 1)

    def test_no_break_chart_and_no_tap_chart(self):
        score = calculate_note_scores({'tap': 100, 'hold': 0, 'slide': 0, 'touch': None, 'break': 0})
        self.assertEqual(score['maximum'], 100)
        self.assertIsNone(score['miss_limits']['SSS+'])
        self.assertEqual(score['miss_limits']['S'], 3)
        score = calculate_note_scores({'tap': 0, 'hold': 1, 'slide': 0, 'touch': 0, 'break': 1})
        self.assertEqual(score['miss_limits']['SSS+'], 0)

    def test_judgement_losses_include_break_bonus(self):
        score = calculate_note_scores({'tap': 100, 'hold': 0, 'slide': 0, 'touch': 0, 'break': 1})
        tap = score['per_note']['tap']
        self.assertEqual(score['losses']['tap']['great'], tap / 5)
        self.assertEqual(score['losses']['hold']['good'], tap)
        self.assertEqual(score['break_losses']['perfect_2550'], Fraction(1, 4))
        self.assertEqual(score['break_losses']['perfect_2500'], Fraction(1, 2))
        self.assertEqual(score['break_losses']['great_2000'], tap + Fraction(3, 5))
        self.assertEqual(score['break_losses']['good'], 3 * tap + Fraction(7, 10))
        self.assertEqual(score['break_losses']['miss'], score['per_note']['break'])

    def test_missing_or_inconsistent_counts_are_rejected(self):
        for counts in [None, {}, {'tap': -1, 'hold': 0, 'slide': 0, 'break': 1},
                       {'tap': 1, 'hold': 0, 'slide': 0, 'break': 1, 'total': 99},
                       {'tap': 0, 'hold': 0, 'slide': 0, 'break': 0}]:
            with self.subTest(counts=counts), self.assertRaises(ValueError):
                calculate_note_scores(counts)


if __name__ == '__main__':
    unittest.main()
