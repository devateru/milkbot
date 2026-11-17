"""Recognize the cabinet's outlined upper score glyphs on the 1P layout."""

from base64 import b64decode
from functools import lru_cache
import json
from pathlib import Path


SCORE_REGION = (244, 181, 443, 223)
SCORE_SLOTS = [(271, 185, 290, 214), (290, 185, 310, 214), (310, 185, 330, 214),
               (340, 191, 356, 213), (356, 191, 372, 213), (372, 191, 387, 213), (387, 191, 403, 213)]
COUNTER_REGION = (826, 55, 1017, 91)
COUNTER_SLOTS = [(849, 66, 863, 79), (882, 59, 897, 73), (920, 57, 932, 70),
                 (956, 60, 970, 74), (991, 64, 1006, 80)]
ZERO_GLYPHS = ('AAAAAAAAAAAAHwB8AZAGYBmAfgDgAAAAAA==', 'wAAAAAAAAAAAAAA8APgCYAmANgD4AAAAAA==',
               'AAAAAAAAAAAAAAAAAfAG4BmA5gGYB8APAA==', 'ADwAAAAAAAAAAABwA/AMwDMAzAPwAwAAAA==',
               '/wD/gD/ADwAAAAAAAAAPAHwBkATAHwA4AA==')
FIRST_SLOT_DIGITS = ('AAAAAAAAAAAADAAwAGABgAYAGAAgAAAAAA==', 'AAAAAAAAAAAADgB8AbADwA8APgDwAAAAAA==',
                     'AAAAAAAAAAAADgB8ATABwAmAPgDwAAAAAA==', 'AAAAAAAAAAAABgAcAPACwBuAfgAAAAAAAA==')
ZERO_RATING = (
    (
        '#..............................#',
        '................................',
        '...........................###..',
        '..........................####..',
        '..........................##.##.',
        '...........................#.##.',
        '...........................###..',
        '................................',
        '#...............................',
        '#...............................',
    ),
    (
        '............................####',
        '.........................##...##',
        '........................####..##',
        '........................####..##',
        '........................#.##..##',
        '........................#.##..##',
        '.........................##...##',
        '..............................##',
        '..............................##',
        '................................',
    ),
)
# Cabinet glyph samples at the original scale and resampled for the smaller 2P panel.
NAME_SYMBOLS = {
    '☆': (
        '0007600000188100555665546853368537601663048228300486683007934950',
        '1246642144555544655445556543345655433454455455544565555445544554',
        '0026410000376310334555546542256666401466465235543676565366534776',
    ),
    'Σ': (
        '9998888899954333347763110136763001267730246763108895312299988888',
        '9988888899843333458652111237752001378620347762109984222299988888',
        '7776665577865433456664211246653112366531345664216786543277755544',
        '6677666666775544446655332244664422446644335555336677553366775555',
        '8866777799664433446655221133665500336666225555228866443399887766',
    ),
}


@lru_cache(maxsize=1)
def templates():
    import numpy as np

    files = json.loads(Path(__file__).with_name('hud-templates.json').read_text(encoding='utf-8'))
    return [{digit: np.stack([np.frombuffer(b64decode(raw), dtype=np.uint8).reshape(16, 12) for raw in refs]
                            ).astype(np.float32) / 15 for digit, refs in group.items()} for group in files]


def score_digits(image):
    import cv2
    import numpy as np

    if image.shape != (42, 199):
        image = cv2.resize(image, (199, 42), interpolation=cv2.INTER_LINEAR)
    # Require both the decimal point and the percent glyph in their fixed positions.
    if (image[22:32, 86:95] > 125).mean() < 0.45 or (image[19:33, 159:173] > 125).mean() < 0.43:
        return None
    groups = templates()
    output = []
    for i, (x, y, right, bottom) in enumerate(SCORE_SLOTS):
        cell = image[y - 181:bottom - 181, x - 244:right - 244]
        feature = cv2.resize(cell, (12, 16), interpolation=cv2.INTER_AREA).astype(np.float32)
        feature = np.clip((feature - 45) / 155, 0, 1)
        if i < 2 and not output and feature.mean() < 0.16:
            continue
        ranked = sorted((float(np.min(np.mean((refs - feature) ** 2, axis=(1, 2)))), key)
                        for key, refs in groups[i >= 3].items())
        distance, digit = ranked[0]
        if distance > 0.012 or ranked[1][0] - distance < 0.005:
            return None
        output.append(digit)
    value = ''.join(output[:-4]) + '.' + ''.join(output[-4:])
    return value if float(value) <= 101 else None


@lru_cache(maxsize=1)
def counter_templates():
    import numpy as np

    def decode(encoded):
        return np.unpackbits(np.frombuffer(b64decode(encoded), dtype=np.uint8))[:196].reshape(14, 14).astype(bool)

    return [decode(encoded) for encoded in ZERO_GLYPHS], [decode(encoded) for encoded in FIRST_SLOT_DIGITS]


def early_judgments(image):
    """Use the optional five-counter strip while only CRITICAL PERFECTs are visible."""
    import cv2
    import numpy as np

    if image.shape != (36, 191):
        image = cv2.resize(image, (191, 36), interpolation=cv2.INTER_LINEAR)
    cells = [cv2.resize(image[y - 55:bottom - 55, x - 826:right - 826], (14, 14),
                        interpolation=cv2.INTER_AREA) > 115 for x, y, right, bottom in COUNTER_SLOTS]
    zeros, digits = counter_templates()
    if any(np.count_nonzero(previous != current) > 6 for previous, current in zip(zeros[1:], cells[1:])):
        return None
    ranked = sorted((np.count_nonzero(ref != cells[0]), i) for i, ref in enumerate([zeros[0], *digits]))
    distance, number = ranked[0]
    return number if distance <= 4 and ranked[1][0] - distance >= 3 else None


def guest_rating_zero(image):
    """Require a lone right-aligned zero over the full rating field."""
    import cv2
    import numpy as np

    gray = cv2.resize(image, (32, 10), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    baseline = np.median(gray[:, 3:19], axis=1)
    mask = gray > baseline[:, None] + 27
    return any(
        np.count_nonzero(mask != (np.array([list(row) for row in pattern]) == '#')) <= 10 for pattern in ZERO_RATING)


@lru_cache(maxsize=1)
def name_symbol_templates():
    import numpy as np

    return {symbol: np.array([list(ref) for ref in refs], dtype=np.float32).reshape(-1, 8, 8) / 9
            for symbol, refs in NAME_SYMBOLS.items()}


def nameplate_suffix(image):
    """Separate independently recognized suffix glyphs from the OCR prefix."""
    import cv2
    import numpy as np

    gray = cv2.resize(image, (69, 13), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    ink = np.clip((np.median(gray) - gray[1:-2]) / 150, 0, 1)
    mask = ink > .52
    edges = np.flatnonzero(np.diff(np.r_[False, mask.any(axis=0), False])).reshape(-1, 2)
    symbols = []
    for left, right in reversed(edges):
        rows = np.flatnonzero(mask[:, left:right].any(axis=1))
        if not (4 <= right - left <= 9 and 6 <= rows[-1] - rows[0] + 1 <= 9):
            break
        feature = cv2.resize(ink[rows[0]:rows[-1] + 1, left:right], (8, 8), interpolation=cv2.INTER_AREA)
        ranked = sorted((float(((refs - feature) ** 2).mean(axis=(1, 2)).min()), symbol)
                        for symbol, refs in name_symbol_templates().items())
        if ranked[0][0] > .04 or ranked[1][0] - ranked[0][0] < .04:
            break
        symbols.append(ranked[0][1])
    # Wide gaps can be intentional spaces. Leave such names to ordinary OCR.
    prefix = len(edges) - len(symbols)
    if not symbols or not prefix or np.any(edges[prefix:, 0] - edges[prefix - 1:-1, 1] > 7):
        return None
    cut = round((edges[prefix - 1, 1] + edges[prefix, 0]) * image.shape[1] / (2 * gray.shape[1]))
    return image[:, :cut], ''.join(reversed(symbols))
