weight_note = {"tap": 1, "hold": 2, "slide": 3, "touch": 1, "_break": 5}
weight_judge = {""}

def note_weight_calc(tap: int, hold: int, slide: int, touch: int, _break: int):
    total_cost = tap * weight_note["tap"] + hold * weight_note["hold"] + slide * weight_note["slide"] + touch * weight_note["touch"] + _break * weight_note["_break"]
    