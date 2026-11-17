"""Parse numbered simai notes and derive boundaries for score sampling."""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
import re

from note_scoring import NOTE_WEIGHTS

MIN_BOUNDARY_GAP = 0.24
MAX_SECTIONS = 30
HEAD = re.compile(r'([1-8]|[ABDE][1-8]|C[12]?)([bhxf?$!@]*)')
PATH = re.compile(r'(?:[-<>^vspqzw]|pp|qq)[1-8]|V[1-8][1-8]')
DURATION = re.compile(r'\[([^\[\]]+)\]')
DIFFICULTY_NUMBER = {'basic': 2, 'advanced': 3, 'expert': 4, 'master': 5, 'remaster': 6}


@dataclass(frozen=True)
class Note:
    kind: str
    time: float
    earliest: float
    latest: float
    lane: int | None = None


@dataclass(frozen=True)
class Simai:
    notes: tuple[Note, ...]
    end: float
    first: float = 0

    @property
    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys(NOTE_WEIGHTS, 0)
        for note in self.notes:
            counts[note.kind] += 1
        return counts


@dataclass(frozen=True)
class Section:
    original: int
    first: int
    last: int
    allowance: str


def positive(value: str, *, zero: bool = False) -> Fraction:
    if not re.fullmatch(r'(?:\d+(?:\.\d*)?|\.\d+)', value):
        raise ValueError(f'지원하지 않는 simai 숫자: {value}')
    result = Fraction(value)
    if result <= 0 and not zero:
        raise ValueError('simai의 BPM, 박자와 길이는 양수여야 합니다.')
    return result


def duration(spec: str, bpm: Fraction, slide: bool = False) -> tuple[Fraction, Fraction]:
    wait = 60 / bpm if slide else Fraction(0)
    if '##' in spec:
        delay, spec = spec.split('##', 1)
        if not slide:
            raise ValueError('HOLD에는 SLIDE 대기 시간을 사용할 수 없습니다.')
        wait = positive(delay, zero=True)
        override_wait = False
    else:
        override_wait = slide
    if '#' in spec:
        tempo, spec = spec.split('#', 1)
        if tempo:
            bpm = positive(tempo)
            if override_wait:
                wait = 60 / bpm
    if ':' in spec:
        division, multiple = spec.split(':', 1)
        return wait, 240 * positive(multiple, zero=True) / bpm / positive(division)
    return wait, positive(spec, zero=True)


def parse_token(token: str, time: Fraction, bpm: Fraction) -> list[Note]:
    if re.fullmatch(r'[1-8]+', token):
        return [Note('tap', float(time), float(time), float(time), int(position)) for position in token]
    match = HEAD.match(token)
    if not match:
        raise ValueError(f'지원하지 않는 simai 노트: {token}')
    position, flags = match.groups()
    lane = int(position) if position.isdigit() else None
    tail = token[match.end():]
    start = float(time)
    if not tail or 'h' in flags:
        if tail and not DURATION.fullmatch(tail):
            raise ValueError(f'잘못된 HOLD 길이: {token}')
        if 'h' in flags:
            length = duration(tail[1:-1], bpm)[1] if tail else 240 / bpm / 1280
            return [Note('break' if 'b' in flags else 'hold', start, start, float(time + length))]
        kind = 'break' if 'b' in flags else ('tap' if position.isdigit() else 'touch')
        if '?' in flags or '!' in flags:
            raise ValueError(f'별 머리 옵션에 SLIDE 경로가 없습니다: {token}')
        return [Note(kind, start, start, start, lane)]
    if not position.isdigit():
        raise ValueError(f'SLIDE 시작 위치가 올바르지 않습니다: {token}')
    notes = [] if '?' in flags or '!' in flags else [
        Note('break' if 'b' in flags else 'tap', start, start, start, lane)]
    for branch in tail.split('*'):
        cursor = 0
        has_path = False
        wait = travel = Fraction(0)
        first_length = True
        is_break = False
        while cursor < len(branch):
            if path := PATH.match(branch, cursor):
                has_path = True
                cursor = path.end()
            elif length := DURATION.match(branch, cursor):
                if not has_path:
                    raise ValueError(f'SLIDE 판정 길이 앞에 경로가 필요합니다: {token}')
                delay, length_value = duration(length[1], bpm, slide=first_length)
                travel += length_value
                if first_length:
                    wait = delay
                first_length = has_path = False
                cursor = length.end()
                if branch[cursor:cursor + 1] == 'b':
                    is_break = True
                    cursor += 1
            else:
                raise ValueError(f'지원하지 않는 SLIDE 경로: {token}')
        if first_length or has_path:
            raise ValueError(f'SLIDE의 길이를 확인할 수 없습니다: {token}')
        notes.append(Note('break' if is_break else 'slide', start, float(time + wait),
                          float(time + wait + travel)))
    return notes


def parse_simai(source: str, difficulty: str = 'master') -> Simai:
    source = re.sub(r'\|\|[^\r\n]*', '', source)
    first = 0.0
    if fields := list(re.finditer(r'(?m)^\s*&([\w]+)\s*=', source)):
        data = {field[1]: source[field.end():fields[index + 1].start() if index + 1 < len(fields) else None].strip()
                for index, field in enumerate(fields)}
        source = data.get(f'inote_{DIFFICULTY_NUMBER[difficulty]}', '')
        first = float(data.get('first', '0'))
        if not -120 <= first <= 120:
            raise ValueError('simai의 &first 오프셋이 올바르지 않습니다.')
    compact = ''.join(source.split())
    if not compact.endswith('E'):
        raise ValueError('simai 채보 끝 표시 E를 찾을 수 없습니다.')
    time = Fraction(0)
    bpm = Fraction(0)
    divisor = Fraction(4)
    fixed = None
    notes = []
    for cell in compact[:-1].split(','):
        while directive := re.match(r'\(([^()]+)\)|\{([^{}]+)\}', cell):
            if directive[1]:
                bpm = positive(directive[1])
            elif directive[2].startswith('#'):
                fixed = positive(directive[2][1:])
            else:
                divisor = positive(directive[2])
                fixed = None
            cell = cell[directive.end():]
        if not bpm:
            raise ValueError('simai의 첫 BPM을 확인할 수 없습니다.')
        if cell:
            for tick, staggered in enumerate(cell.split('`')):
                for token in staggered.split('/'):
                    if not token:
                        raise ValueError('simai 동시치기 표기에 빈 노트가 있습니다.')
                    notes.extend(parse_token(token, time + Fraction(tick, 1000), bpm))
        time += fixed if fixed is not None else 240 / bpm / divisor
    if not notes:
        raise ValueError('채보에 노트가 없습니다.')
    if any(a.time > b.time for a, b in zip(notes, notes[1:])):
        raise ValueError('노트 시각이 역전된 채보입니다.')
    # The last cell is E and does not consume a comma.
    end = time - (fixed if fixed is not None else 240 / bpm / divisor)
    return Simai(tuple(notes), max(float(end), max(n.latest for n in notes)), first)


def note_at(chart: Simai, elapsed: float) -> tuple[int, int] | None:
    times = [note.time for note in chart.notes]
    # Frame timestamps and the chart may differ by float arithmetic at an exact hit.
    left = bisect_left(times, elapsed - 1e-8)
    if left == len(times):
        return None
    return left + 1, bisect_right(times, times[left])


def window_at(chart: Simai, first: int) -> tuple[float, float]:
    if first == 1:
        return float('-inf'), min(n.earliest for n in chart.notes)
    if first == len(chart.notes) + 1:
        return max(n.latest for n in chart.notes), float('inf')
    return (max(n.latest for n in chart.notes[:first - 1]),
            min(n.earliest for n in chart.notes[first - 1:]))


def parse_sections(text: str, chart: Simai) -> tuple[Section, ...]:
    parts = re.split(r',|\n|\s+(?=(?:\d+(?:\s*개)?|나머지)\s*:)', text)
    parts = [part.strip() for part in parts if part.strip()]
    if not 1 <= len(parts) <= MAX_SECTIONS:
        raise ValueError(f'구간을 1~{MAX_SECTIONS}개 입력해주세요.')
    total = len(chart.notes)
    # Prefix maxima let dense maps skip overlapping HOLD/SLIDE groups in one pass.
    latest = float('-inf')
    valid = [1]
    for i, (previous, current) in enumerate(zip(chart.notes, chart.notes[1:]), 2):
        latest = max(latest, previous.latest)
        if previous.time < current.time and current.time - latest >= MIN_BOUNDARY_GAP:
            valid.append(i)
    entries = []
    count_mode = bool(re.match(r'(?:\d+\s*개|나머지)\s*:', parts[0]))
    number = r'\d+\s*개|나머지' if count_mode else r'\d+'
    consumed = 0
    for part in parts:
        match = re.fullmatch(rf'({number})\s*:\s*(-?(?:\d+(?:\.\d{{1,4}})?|\.\d{{1,4}}))\s*%?', part)
        if not match:
            raise ValueError(f'한 가지 형식으로 입력해주세요. 예) 1:-0.1 또는 100개:-0.1 ({part})')
        allowance = Decimal(match[2])
        if count_mode:
            first = consumed + 1
            count = total - consumed if match[1] == '나머지' else int(match[1][:-1])
            consumed += count
            if count < 1 or consumed > total:
                raise ValueError(f'구간별 노트 수는 양수이고 합계는 {total}개 이하여야 합니다.')
        else:
            first = int(match[1])
        if not -101 <= allowance <= 0 or not 1 <= first <= total:
            raise ValueError(f'시작 노트는 1~{total}, 허용 감점률은 -101~0% 범위입니다.')
        if (not entries and first != 1) or (entries and first <= entries[-1][0]):
            raise ValueError('첫 구간은 1번에서 시작하며, 시작 번호는 중복 없이 오름차순이어야 합니다.')
        index = bisect_left(valid, first)
        if index == len(valid) or (entries and valid[index] <= entries[-1][1]):
            raise ValueError(f'{first}번 노트 이후에 중복 없이 사용할 수 있는 구간 경계가 없습니다.')
        entries.append((first, valid[index], format(allowance, '.4f')))
    if count_mode and consumed != total:
        raise ValueError(f'구간별 노트 수의 합계는 {total}개여야 합니다. 마지막 구간에 나머지를 입력할 수 있습니다.')
    return tuple(Section(original, first, entries[i + 1][1] - 1 if i + 1 < len(entries) else total, limit)
                 for i, (original, first, limit) in enumerate(entries))


def adjustment_footer(sections: tuple[Section, ...]) -> str | None:
    adjusted = [f'[구간 {i}: {s.original} → {s.first}]'
                for i, s in enumerate(sections, 1) if s.original != s.first]
    return '* 시작 노트 조정됨 ' + ' '.join(adjusted) if adjusted else None
