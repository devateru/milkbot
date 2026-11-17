"""Evaluate safe score boundaries from explicitly identified HUD modes."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
import math

from note_scoring import calculate_note_scores
from .simai import Section, Simai, window_at

DISPLAY_UNIT = Decimal('0.0001')
# Combine judgment timing and display delay around the conservative Simai windows.
GUARD = 0.11
END_SAMPLE_WINDOW = 3.0


@dataclass(frozen=True)
class Sample:
    time: float
    mode: str
    value: str


@dataclass(frozen=True)
class Result:
    section: Section
    status: str
    loss: Decimal | None
    timestamp: int | None


def score_point(samples, chart, boundary, origin, end, guard):
    after, before = window_at(chart, boundary)
    low = origin + after + guard if math.isfinite(after) else origin + before - END_SAMPLE_WINDOW
    high = origin + before - guard if math.isfinite(before) else min(end, origin + after + END_SAMPLE_WINDOW)
    rows = [(s.time, value) for s, value in samples if low <= s.time <= high]
    if not rows:
        return None
    # OCR disagreement in an interval where the score must be constant is ambiguous.
    first = rows[0][1]
    return first if all(abs(value - first) <= DISPLAY_UNIT for _, value in rows) else None


def evaluate(chart: Simai, sections: tuple[Section, ...], samples: list[Sample],
             origin: float | None, end: float, *, skipped: bool = False,
             gaps: tuple[tuple[float, float], ...] = (), timing_error: float = 0) -> list[Result]:
    if origin is None:
        return [Result(s, 'uncertain', None, None) for s in sections]
    weights = calculate_note_scores(chart.counts)['per_note']
    values = {'+': [], '-': []}
    for sample in sorted(samples, key=lambda s: s.time):
        value = Decimal(sample.value)
        if sample.mode in values and value.is_finite() and 0 <= value <= 101:
            values[sample.mode].append((sample, value))
    guard = GUARD + timing_error
    starts = [origin + chart.notes[s.first - 1].time for s in sections]
    active = max((i for i, start in enumerate(starts) if start <= end), default=0)
    results = []
    for i, s in enumerate(sections):
        start = starts[i]
        link_time = max(0, int(start - 2))
        if skipped and i > active:
            results.append(Result(s, 'skipped', None, link_time))
            continue
        if skipped and i == active:
            loss = None
            if not any(a < end and b >= start - guard for a, b in gaps):
                observations = values['-']
                baseline = score_point(observations, chart, s.first, origin, end, guard)
                confirmed = [(point.time, value) for point, value in observations if start + guard <= point.time <= end]
                if (baseline is not None and confirmed and baseline >= confirmed[0][1] and
                        all(b <= a for (_, a), (_, b) in zip(confirmed, confirmed[1:]))):
                    loss = (baseline - confirmed[-1][1]).quantize(DISPLAY_UNIT)
            results.append(Result(s, 'skip-failed', loss, link_time))
            continue
        notes = chart.notes[s.first - 1:s.last]
        theoretical = sum((weights[n.kind] for n in notes), Fraction())
        perfect = Decimal(theoretical.numerator) / Decimal(theoretical.denominator)
        loss = None
        evaluation_end = starts[i + 1] if i + 1 < len(starts) else end
        if not any(a < evaluation_end and b > start - guard for a, b in gaps):
            for mode in ('-', '+'):
                mode_samples = values[mode]
                a = score_point(mode_samples, chart, s.first, origin, end, guard)
                b = score_point(mode_samples, chart, s.last + 1, origin, end, guard)
                if a is None or b is None:
                    continue
                interior = [v for sample, v in mode_samples if start <= sample.time < evaluation_end]
                sequence = [a, *interior, b]
                if any((right - left if mode == '+' else left - right) < -DISPLAY_UNIT
                       for left, right in zip(sequence, sequence[1:])):
                    continue
                delta = b - a
                signed_gain = delta if mode == '+' else -delta
                if not -DISPLAY_UNIT <= signed_gain <= perfect + DISPLAY_UNIT:
                    continue
                loss = (perfect - delta if mode == '+' else -delta).quantize(
                    DISPLAY_UNIT, rounding=ROUND_HALF_UP)
                loss = max(Decimal('0.0000'), loss)
                break
        limit = -Decimal(s.allowance)
        if loss is None or (loss != 0 and abs(loss - limit) <= DISPLAY_UNIT):
            status = 'uncertain'
        else:
            status = 'passed' if loss <= limit else 'failed'
        results.append(Result(s, status, loss, link_time))
    return results
