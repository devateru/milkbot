rank_coefficient = {
    100.5: ["SSS+", 22.4],
    100.4999: ["SSS", 22.2],
    100.0: ["SSS", 21.6],
    99.9999: ["SS+", 21.4],
    99.5: ["SS+", 21.1],
    99.0: ["SS", 20.8],
    98.99: ["S+", 20.6],
    98.0: ["S+", 20.3],
    97.0: ["S", 20.0],
    96.99: ["AAA", 17.6],
    94.0: ["AAA", 16.8],
    90.0: ["AA", 15.2],
    80.0: ["A", 13.6],
    79.99: ["BBB", 12.8],
    75.0: ["BBB", 12.0],
    70.0: ["BB", 11.2],
    60.0: ["B", 9.6],
    50.0: ["C", 8.0],
    40.0: ["D", 6.4],
    30.0: ["D", 4.8],
    20.0: ["D", 3.2],
    10.0: ["D", 1.6],
    0.0: ["D", 0.0],
}

note_weight = {
    "tap": 1,
    "hold": 2,
    "slide": 3,
    "touch": 1,
    "break": 5
}

judgement_coefficient = {
    "perfect": 1.0,
    "great": 0.8,
    "good": 0.5,
    "miss": 0}

def rating_calc(diff: float, score: float, if_AP: bool = False):
    """* 점수가 100.5 이하일 때 AP 일 수 없음"""
    for border_index in len(rank_coefficient):
        if score >= rank_coefficient[border_index][0]:
            return border_index[0], round(diff * score * rank_coefficient[border_index][1]) + if_AP
    return -1, -1

def note_score_calc(tap: int, hold: int, slide: int, touch: int, break_: int):
    denominator = tap + hold*2 + slide*3 + touch + break_*5
    tap_score = 1 / denominator * 100
    hold_score = 2 / denominator * 100
    slide_score = 3 / denominator * 100
    touch_score = 1 / denominator * 100
    break_score = 5 / denominator + 1 / break_ * 100
    tap_total = tap * tap_score
    hold_total = hold * hold_score
    slide_total = slide * slide_score
    touch_total = touch * touch_score
    break_total = break_ * break_score
    return False # {"weight": [tap_total, hold_total, slide_total, touch_total, break_total], "tap": 