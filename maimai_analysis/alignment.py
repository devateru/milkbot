"""Align the first observed judgment to the first simai note group."""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from itertools import takewhile

from note_scoring import calculate_note_scores


def align_from_gain(chart, samples, detected_start):
    # Restrict matching to the early prefix before any long-note judgment can
    # move earlier or later. A partial or low-accuracy trace cannot anchor time.
    per_note = calculate_note_scores(chart.counts)['per_note']
    long_start = min((note.earliest for note in chart.notes if note.earliest != note.latest), default=float('inf'))
    events = defaultdict(float)
    for note in chart.notes:
        if note.latest >= long_start or note.latest > chart.notes[0].time + 14:
            break
        events[note.latest] += float(per_note[note.kind])
    if len(events) < 3:
        return None
    times, perfect = [], []
    total = 0
    for timestamp, value in events.items():
        total += value
        times.append(timestamp)
        perfect.append(total)
    readings = sorted((sample.time, float(sample.value)) for sample in samples if sample.mode == '+')
    first = first_change(readings)
    if first is None:
        return None
    before, after, gain = first
    min_note = min(float(weight) for weight in per_note.values())
    if not perfect[0] - min_note * 0.22 <= gain <= perfect[0] + 0.00011:
        return None
    low, high = before - times[0], after - times[0]
    if not detected_start - 5 <= (low + high) / 2 <= detected_start + 12:
        return None
    previous_time, previous_gain = readings[0]
    matched = set()
    for timestamp, gain in readings:
        if previous_gain < gain <= total + 0.00011:
            # Only identify cumulative awards within a fraction of the
            # smallest note value and with a unique matching chart milestone.
            first = bisect_left(perfect, gain - 0.00011)
            last = bisect_right(perfect, gain + min_note * 0.22)
            if last - first == 1 and timestamp - previous_time <= 0.40:
                event = times[first]
                low = max(low, previous_time - event - 0.08)
                high = min(high, timestamp - event + 0.08)
                matched.add(first)
        if gain < previous_gain or low > high:
            return None
        if gain > total + 0.00011:
            break
        previous_time, previous_gain = timestamp, gain
    if len(matched) >= 3:
        return (low + high) / 2, (high - low) / 2
    return None


def first_change(readings):
    if not readings or readings[0][1] != 0:
        return None
    for (before, _), (after, value) in zip(readings, readings[1:]):
        if value:
            return (before, after, value) if value > 0 and 0 < after - before <= 0.28 else None
    return None


def align_from_judgments(chart, readings, detected_start):
    first_time = chart.notes[0].time
    group = tuple(takewhile(lambda note: note.time == first_time, chart.notes))
    first = first_change(readings)
    if first is None or first[2] != len(group) or any(note.earliest != note.latest for note in group):
        return None
    before, after, _ = first
    origin = (before + after) / 2 - first_time
    if detected_start - 5 <= origin <= detected_start + 12:
        return origin, (after - before) / 2
    return None
