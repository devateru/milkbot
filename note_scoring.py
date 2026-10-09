"""maimai DX achievement scoring (also applies to STD charts in DX).

100% weighted base score plus 1% BREAK bonus. See docs/note-scores.md.
Fractions keep rank boundary calculations exact before display rounding.
"""

from fractions import Fraction


NOTE_WEIGHTS = {'tap': 1, 'hold': 2, 'slide': 3, 'touch': 1, 'break': 5}
RANKS = {'SSS+': Fraction('100.5'), 'SSS': Fraction(100), 'SS+': Fraction('99.5'),
         'SS': Fraction(99), 'S+': Fraction(98), 'S': Fraction(97)}


def calculate_note_scores(note_counts):
    if not isinstance(note_counts, dict):
        raise ValueError('이 채보의 노트 수 데이터가 없습니다.')
    counts = {}
    for type_ in NOTE_WEIGHTS:
        value = note_counts.get(type_)
        if type_ == 'touch' and value is None:
            value = 0  # STD data has null TOUCH counts.
        if type(value) is not int or value < 0:
            raise ValueError(f'{type_.upper()} 노트 수 데이터가 없거나 올바르지 않습니다.')
        counts[type_] = value
    total = sum(counts.values())
    if not total:
        raise ValueError('노트 수가 0인 채보는 배점을 계산할 수 없습니다.')
    if note_counts.get('total') is not None and note_counts['total'] != total:
        raise ValueError('총 노트 수와 유형별 노트 수 합계가 일치하지 않습니다.')
    weighted_total = sum(counts[k] * weight for k, weight in NOTE_WEIGHTS.items())
    tap_score = Fraction(100, weighted_total)
    bonus = Fraction(1, counts['break']) if counts['break'] else Fraction(0)
    per_note = {k: weight * tap_score for k, weight in NOTE_WEIGHTS.items()}
    per_note['break'] += bonus
    maximum = Fraction(101 if counts['break'] else 100)
    miss_limits = {rank: min(counts['tap'], (maximum - threshold) // tap_score)
                   if maximum >= threshold else None for rank, threshold in RANKS.items()}
    losses = {k: {'perfect': Fraction(0), 'great': weight * tap_score / 5,
                  'good': weight * tap_score / 2, 'miss': weight * tap_score}
              for k, weight in NOTE_WEIGHTS.items() if k != 'break'}
    break_losses = {
        'critical_perfect': Fraction(0),
        'perfect_2550': bonus / 4,
        'perfect_2500': bonus / 2,
        'great_2000': tap_score + bonus * Fraction(3, 5),
        'great_1500': 2 * tap_score + bonus * Fraction(3, 5),
        'great_1250': Fraction(5, 2) * tap_score + bonus * Fraction(3, 5),
        'good': 3 * tap_score + bonus * Fraction(7, 10),
        'miss': 5 * tap_score + bonus,
    }
    return {'counts': counts, 'total': total, 'weighted_total': weighted_total,
            'per_note': per_note, 'break_bonus': bonus, 'maximum': maximum,
            'miss_limits': miss_limits, 'losses': losses, 'break_losses': break_losses}
