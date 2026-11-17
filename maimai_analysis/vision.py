"""ROI OCR for Game Plaza's single captured maimai player layout."""

from collections import deque
import ctypes as c
from ctypes.util import find_library
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
import json
import os
import re
import unicodedata
from zoneinfo import ZoneInfo

from .media import MediaError
from .hud import COUNTER_REGION, SCORE_REGION, early_judgments, guest_rating_zero, score_digits
from .scoring import Sample
from .tracking import Frame, identity_key


# Coordinates in a 1280x720 fit of Game Plaza's 1-player capture. The left
# panel contains the upper cabinet display. The right panel is the game feed.
REGIONS = {
    'header': (759, 61, 1088, 231),
    'profile_hint': (758, 191, 1080, 238),
    'profile_name': (890, 285, 1055, 318),
    'nameplate': (134, 83, 203, 96),
    'guest_name': (130, 82, 195, 98),
    'rating': (160, 68, 190, 78),
    'title': (201, 155, 477, 169),
    'difficulty': (195, 125, 322, 149),
    'badge': (385, 136, 430, 149),
    'track_number': (410, 90, 503, 110),
    'select_title': (855, 439, 988, 456),
    'clear': (800, 81, 1041, 152),
    'result_track': (851, 58, 995, 89),
    'round_skip': (782, 226, 1070, 420),
    'intro': (756, 126, 1103, 317),
    'upper_score': SCORE_REGION,
    'center_score': (782, 307, 1070, 400),
    'result_score': (627, 236, 1007, 307),
    'footer': (733, 444, 1112, 535),
    'clock': (1097, 696, 1276, 719),
    'judgment_strip': COUNTER_REGION,
    'playfield_dark_band': (798, 117, 1051, 155),
    'playfield_judgment_rim': (799, 91, 1051, 122),
    'upper_result': (148, 122, 428, 165),
    'single_badge': (1117, 37, 1240, 70),
    'left_badge': (44, 346, 167, 375),
    'right_badge': (1114, 346, 1237, 375),
    'camera_notice': (278, 353, 532, 551),
}
TEXT = {
    'profile': r'START\s*PLAY\s*WITH\s*THIS\s*AIME|MODE\s*SELECT',
    'credit_end': r'GAME\s*OVER|THANK\s*YOU\s*FOR\s*PLAYING|CREDIT\s*RESULT|SEE\s*YOU',
    'idle': r'PLEASE\s*TOUCH\s*BY\s*AIME|INSERT\s*COIN',
    'skip': r'TRACK\s*SKIP|SKIPPED|GIVE\s*UP',
    'result': r'TRACK\s*RESULT|(?:^|\n)\s*(?:CLEAR|FAILED)[! ]*(?:\n|$)',
    'ready': r'TRACK\s*START|GET\s*READY|MUSIC\s*SELECT|TRACK\s*SELECT',
}
DIFFICULTY = re.compile(r'\b(RE\s*[:：.]?\s*MASTER|MASTER|EXPERT|ADVANCED|BASIC)\b', re.I)
KIND = re.compile(r'\b(DX|DELUXE|STD|STANDARD|ST)\b', re.I)
PERCENT = re.compile(r'(?<![\d.+−-])([0-9]{1,3}[.][0-9]{4})\s*%(?!\d)')
CLOCK = re.compile(r'(\d{2})[./-](\d{2})[./-](\d{2})\s+(\d{2}):(\d{2}):(\d{2})')
SEOUL = ZoneInfo('Asia/Seoul')


@dataclass(frozen=True)
class Reading:
    text: str = ''
    confidence: int = 0


class TessOCR:
    """Use the libtesseract C API so each crop avoids a subprocess spawn."""

    def __init__(self, lang):
        library = os.getenv('MAIMAI_TESSERACT_LIBRARY') or find_library('tesseract')
        if not library:
            raise MediaError('libtesseract를 찾을 수 없습니다. maimai 분석 설치 문서를 확인해주세요.')
        self.library = dll = c.CDLL(library)
        pointer = c.c_void_p
        signatures = {
            'Create': (pointer,), 'Delete': (None, pointer),
            'Init3': (c.c_int, pointer, c.c_char_p, c.c_char_p),
            'SetPageSegMode': (None, pointer, c.c_int),
            'SetImage': (None, pointer, pointer, c.c_int, c.c_int, c.c_int, c.c_int),
            'GetUTF8Text': (pointer, pointer), 'MeanTextConf': (c.c_int, pointer),
            'Clear': (None, pointer),
            'SetVariable': (c.c_int, pointer, c.c_char_p, c.c_char_p),
        }
        for name, (restype, *arguments) in signatures.items():
            method = getattr(dll, 'TessBaseAPI' + name)
            method.restype, method.argtypes = restype, arguments
        dll.TessDeleteText.argtypes = [pointer]
        dll.TessDeleteText.restype = None
        self.handle = dll.TessBaseAPICreate()
        directory = os.getenv('TESSDATA_PREFIX')
        if dll.TessBaseAPIInit3(self.handle, os.fsencode(directory) if directory else None, lang.encode()):
            self.close()
            raise MediaError('Tesseract OCR 언어 데이터를 열 수 없습니다.')

    def close(self):
        if self.handle:
            self.library.TessBaseAPIDelete(self.handle)
            self.handle = None

    def read(self, img, psm, numeric=False):
        dll, api = self.library, self.handle
        height, width = img.shape
        dll.TessBaseAPISetPageSegMode(api, psm)
        dll.TessBaseAPISetVariable(api, b'tessedit_char_whitelist', b'0123456789.% ' if numeric else b'')
        dll.TessBaseAPISetImage(api, img.ctypes.data, width, height, 1, img.strides[0])
        ptr = dll.TessBaseAPIGetUTF8Text(api)
        try:
            text = c.string_at(ptr).decode('utf-8').strip() if ptr else ''
            return Reading(text, dll.TessBaseAPIMeanTextConf(api))
        finally:
            if ptr:
                dll.TessDeleteText(ptr)
            dll.TessBaseAPIClear(api)


class CliOCR:
    """Portable OCR fallback, used when libtesseract is packaged as an executable."""

    def __init__(self, lang):
        import pytesseract

        self.lang = lang
        self.engine = pytesseract
        if exe := os.getenv('MAIMAI_TESSERACT_EXE'):
            self.engine.pytesseract.tesseract_cmd = exe

    def close(self):
        pass

    def read(self, img, psm, numeric=False):
        config = f'--psm {psm}'
        if numeric:
            config += ' -c tessedit_char_whitelist=0123456789.%'
        data = self.engine.image_to_data(img, lang=self.lang, config=config, timeout=4,
                                         output_type=self.engine.Output.DICT)
        words = [(word, int(float(conf)), line) for word, conf, line in
                 zip(data['text'], data['conf'], zip(data['block_num'], data['par_num'], data['line_num'])) if word.strip()]
        if not words:
            return Reading()
        lines = []
        previous = None
        for word, _, line in words:
            if line != previous:
                lines.append([])
            lines[-1].append(word)
            previous = line
        return Reading('\n'.join(' '.join(line) for line in lines),
                       sum(conf for _, conf, _ in words) // len(words))


def percent(text):
    values = PERCENT.findall(unicodedata.normalize('NFKC', text))
    if len(values) == 1 and Decimal(values[0]) <= 101:
        return values[0]
    return None


class ScoreMode:
    def __init__(self, configured='auto'):
        self.configured = configured
        self.mode = None
        self.pending = deque(maxlen=90)

    def add(self, timestamp, value, elapsed, label=''):
        if value is None:
            return ()
        if self.mode:
            return (Sample(timestamp, self.mode, value),)
        self.pending.append((timestamp, value, elapsed))
        try:
            number = Decimal(value)
        except ArithmeticError:
            return ()
        if self.configured in {'+', '-'}:
            self.mode = self.configured
        elif re.search(r'ACHIEVEMENT\s*\(\+\)', label, re.I):
            self.mode = '+'
        elif re.search(r'ACHIEVEMENT\s*\(-\)\s*(?:②|2)', label, re.I):
            self.mode = '-'
        else:
            baselines = [Decimal(item[1]) for item in self.pending if item[2] <= 2.5]
            if baselines.count(Decimal(101)) >= 2:
                self.mode = '-'
            elif (number > 0 and elapsed <= 12 and baselines.count(Decimal(0)) >= 2 and
                  all(Decimal(left[1]) <= Decimal(right[1]) for left, right in zip(self.pending, list(self.pending)[1:]))):
                self.mode = '+'
        if not self.mode:
            return ()
        samples = tuple(Sample(time, self.mode, reading) for time, reading, _ in self.pending)
        self.pending.clear()
        return samples


def field_text(value):
    return unicodedata.normalize('NFKC', value).strip()


def cabinet_regions(seat):
    x0 = {'left': 207, 'right': 670}[seat]
    keys = ('nameplate', 'guest_name', 'rating', 'title', 'difficulty', 'badge', 'track_number',
            'upper_score', 'upper_result')
    regions = {}
    for key in keys:
        x, y, right, bottom = REGIONS[key]
        regions[key] = (round(x0 + (x - 72) * 404 / 434), round(73 + (y - 53) * 168 / 180),
                        round(x0 + (right - 72) * 404 / 434), round(73 + (bottom - 53) * 168 / 180))
    regions['camera_notice'] = (x0 + 74, 353, x0 + 328, 551)
    return regions


class Vision:
    def __init__(self, width, height, profile=None, ocr=None):
        import cv2
        import numpy as np

        self.cv2, self.np = cv2, np
        cv2.setNumThreads(1)
        self.width, self.height = width, height
        profile = profile or {}
        self.regions = {**REGIONS, **profile.get('regions', {})}
        self.hud_modes = profile.get('modes', {})
        self.origin_offset = profile.get('chart_origin_offset')
        self.origin_error = float(profile.get('origin_error', 0.10))
        lang = os.getenv('MAIMAI_OCR_LANG', 'eng+jpn+kor')
        self.ocr = ocr if ocr is not None else CliOCR(lang) if os.getenv('MAIMAI_TESSERACT_EXE') else TessOCR(lang)
        self.cache = {}
        self.reset()

    @staticmethod
    def profile():
        filename = os.getenv('MAIMAI_VISION_PROFILE')
        if filename:
            with open(filename, encoding='utf-8') as file:
                profile = json.load(file)
            for view in (profile, *profile.get('seats', {}).values()):
                for name, bounds in view.get('regions', {}).items():
                    if name not in REGIONS or len(bounds) != 4 or not (0 <= bounds[0] < bounds[2] <= 1280
                                                                        and 0 <= bounds[1] < bounds[3] <= 720):
                        raise ValueError(f'OCR 영역 {name} 좌표가 올바르지 않습니다.')
                if any(mode not in {'auto', '+', '-'} for mode in view.get('modes', {}).values()):
                    raise ValueError('OCR 점수 모드는 auto, +, - 중 하나여야 합니다.')
            return profile
        return {}

    def close(self):
        self.ocr.close()

    def reset(self):
        self.modes = {name: ScoreMode(self.hud_modes.get(name, 'auto'))
                      for name in ('upper_score', 'center_score')}
        self.play_start = None
        self.last_menu = float('-inf')
        self.last_field = float('-inf')
        self.last_name = float('-inf')
        self.first_play_frame = None
        self.play_votes = 0
        self.loss_of_play = None
        self.score_cache = {}

    def crop(self, img, key):
        x, y, x2, y2 = self.regions[key]
        return img[round(y * self.height / 720):round(y2 * self.height / 720),
                   round(x * self.width / 1280):round(x2 * self.width / 1280)]

    def read(self, img, key, psm=7, numeric=False, threshold=None, invert=False, scale=2):
        return self.read_crop(self.crop(img, key), key, psm, numeric, threshold, invert, scale)

    def read_crop(self, crop, key, psm, numeric, threshold=None, invert=False, scale=2):
        signature = (key, psm, numeric, threshold, invert, scale)
        prior = self.cache.get(signature)
        if prior is not None:
            delta = self.cv2.absdiff(prior[0], crop)
            # Score digits are small. Avoid coalescing any change on their glyphs.
            if not delta.max() or (not numeric and delta.mean() < 0.35):
                return prior[1]
        pixels = self.cv2.resize(crop, None, fx=scale, fy=scale, interpolation=self.cv2.INTER_CUBIC)
        if threshold is not None:
            flags = self.cv2.THRESH_BINARY_INV if invert else self.cv2.THRESH_BINARY
            if threshold == 0:
                flags |= self.cv2.THRESH_OTSU
            _, pixels = self.cv2.threshold(pixels, threshold, 255, flags)
        elif numeric:
            pixels = self.cv2.normalize(pixels, None, 0, 255, self.cv2.NORM_MINMAX)
        pixels = self.cv2.copyMakeBorder(pixels, 8, 8, 8, 8, self.cv2.BORDER_CONSTANT, value=255)
        result = self.ocr.read(pixels, psm, numeric)
        self.cache[signature] = (crop.copy(), result)
        return result

    def gameplay(self, img):
        """Check the dark playfield immediately below the upper judgment arc."""
        band = self.crop(img, 'playfield_dark_band')
        rim = self.crop(img, 'playfield_judgment_rim')
        baseline = self.crop(img, 'upper_score')
        left = baseline[:, :20]
        # The gameplay HUD has a fixed dark panel behind the score.
        return (band < 57).mean() > 0.53 and (rim > 170).mean() > 0.04 and (left < 75).mean() > 0.60

    def metadata(self, img, menu=False, *, cabinet_only=False):
        difficulty = (DIFFICULTY.search(self.read(img, 'difficulty', scale=3).text) or
                      DIFFICULTY.search(self.read(img, 'difficulty', threshold=145, invert=True).text))
        title = self.read(img, 'title', threshold=160, invert=True, scale=4)
        if menu and title.confidence < 70:
            title = self.read(img, 'select_title', threshold=145, invert=True, scale=3)
        badge = self.read(img, 'badge', threshold=230, scale=4).text
        kind = KIND.search(badge)
        compact_badge = ''.join(badge.split())
        if not difficulty and not cabinet_only:
            difficulty = DIFFICULTY.search(self.read(img, 'intro', 11).text)
        if difficulty:
            difficulty = re.sub(r'[^a-z]', '', difficulty[1].lower())
        kind = 'dx' if kind and kind[1].lower() in {'dx', 'deluxe'} else 'std' if kind else None
        if 'でらっくす' in compact_badge:
            kind = 'dx'
        elif 'スタンダード' in compact_badge:
            kind = 'std'
        return (field_text(title.text) if title.confidence >= 65 else None), kind, difficulty

    def score(self, img, key):
        if key == 'upper_score' and tuple(self.regions[key]) == SCORE_REGION:
            crop = self.crop(img, key)
            old = self.score_cache.get(key)
            if old is not None and not self.cv2.absdiff(old[0], crop).max():
                return old[1]
            value = score_digits(crop)
            self.score_cache[key] = crop.copy(), value
            return value
        raw = self.read(img, key, numeric=True)
        if raw.confidence >= 65 and (value := percent(raw.text)):
            return value
        alternate = self.read(img, key, numeric=True, threshold=0, invert=True)
        return percent(alternate.text) if alternate.confidence >= 65 else None

    def observations(self, img, timestamp):
        rows = []
        for key, mode in self.modes.items():
            value = self.score(img, key)
            rows.extend(mode.add(timestamp, value, timestamp - self.play_start))
        # Both displays can show independent modes. Disagreeing same-mode reads
        # remain separate so a boundary with contradictory OCR is rejected.
        return tuple(dict.fromkeys(rows))

    def track_number(self, img):
        badge = self.read(img, 'track_number', scale=4)
        track = re.search(r'TRACK\s*0?([1-5])\s*[/7.]?\s*[1-5]', field_text(badge.text).upper())
        return int(track[1]) if track else None

    def named(self, frame, img, name, track=None):
        text = field_text(name.text)
        if not re.fullmatch(r'G\s*U\s*E\s*S\s*T', text, re.I):
            guest = self.read(img, 'guest_name', psm=7, threshold=165, scale=4)
            if guest.confidence >= 80 and re.fullmatch(r'G\s*U\s*E\s*S\s*T', guest.text, re.I):
                name, text = guest, 'GUEST'
        if not text or len(text.splitlines()) != 1 or len(text) > 32:
            return replace(frame, track=track)
        rating = None
        if re.fullmatch(r'G\s*U\s*E\s*S\s*T', text, re.I):
            text = 'GUEST'
            if track == 1:
                if guest_rating_zero(self.crop(img, 'rating')):
                    rating = 0
                else:
                    reading = self.read(img, 'rating', psm=10, numeric=True, threshold=115, invert=True, scale=5)
                    if reading.confidence >= 65 and re.fullmatch(r'\d{1,5}', reading.text):
                        rating = int(reading.text)
        return replace(frame, nickname=text, confidence=name.confidence, track=track, rating=rating)

    def capture_epoch(self, img):
        raw = self.read(img, 'clock', threshold=90, scale=4)
        if match := CLOCK.search(raw.text):
            yy, month, day, hour, minute, second = map(int, match.groups())
            try:
                return datetime(2000 + yy, month, day, hour, minute, second, tzinfo=SEOUL).timestamp()
            except ValueError:
                pass
        return None

    def player_name(self, img):
        if self.crop(img, 'nameplate').mean() < 145:
            return Reading()
        plain = self.read(img, 'nameplate', psm=8, scale=4)
        readings = [plain, self.read(img, 'nameplate', threshold=210, scale=4),
                    self.read(img, 'nameplate', threshold=230, scale=4)]
        confident = [reading for reading in readings if reading.confidence >= 80 and reading.text]
        names = {identity_key(reading.text) for reading in confident}
        if len(names) != 1 or len(confident) < 2:
            return Reading()
        return max(confident, key=lambda result: result.confidence)

    @staticmethod
    def needs_name(tracker):
        return not tracker.nickname or (identity_key(tracker.nickname) == 'guest' and not tracker.guest)

    def inspect(self, image, tracker, live=False):
        timestamp = image.time
        frame = Frame(timestamp, epoch=image.epoch, gap=image.discontinuity)
        recovering = live and tracker.checking_resume(frame)
        if image.discontinuity and not recovering:
            self.reset()
        img = self.np.frombuffer(image.pixels, self.np.uint8).reshape(self.height, self.width)
        active = tracker.active is not None
        if self.gameplay(img):
            if self.play_votes == 0:
                self.first_play_frame = timestamp
            self.play_votes += 1
            if self.play_votes < 2 and not active:
                return frame
            self.loss_of_play = None
            first = self.play_start is None
            if first:
                self.play_start = self.first_play_frame
                if live and (capture := self.capture_epoch(img)) is not None:
                    frame = replace(frame, epoch=capture)
            origin = self.play_start + float(self.origin_offset) if first and self.origin_offset is not None else None
            if recovering or not active or tracker.active.chart is None:
                if timestamp - self.last_field >= 0.7:
                    self.last_field = timestamp
                    title, kind, difficulty = self.metadata(img)
                    frame = replace(frame, title=title, kind=kind, difficulty=difficulty)
                    if recovering:
                        frame = self.named(frame, img, self.player_name(img), self.track_number(img))
            if not recovering and self.needs_name(tracker) and (tracker.ready_pending or active) and (
                    timestamp - self.play_start <= 5 and timestamp - self.last_name >= 0.35):
                self.last_name = timestamp
                frame = self.named(frame, img, self.player_name(img), self.track_number(img))
            score_enabled = tracker.accepts_score(frame)
            judged = None
            if score_enabled and timestamp - self.play_start <= 12:
                judged = early_judgments(self.crop(img, 'judgment_strip'))
            return replace(frame, phase='start' if first else 'playing', origin=origin, start_time=self.play_start,
                           timing_error=self.origin_error if origin is not None else 0,
                           judged=judged, samples=self.observations(img, timestamp) if score_enabled else ())
        self.play_votes = 0
        if active and self.loss_of_play is None:
            self.loss_of_play = timestamp
        if timestamp - self.last_menu < 0.4:
            return frame
        self.last_menu = timestamp
        header = field_text(self.read(img, 'header', 11).text).upper()
        track = self.track_number(img)
        phase = next((phase for phase in ('credit_end', 'skip', 'result', 'ready')
                      if re.search(TEXT[phase], header)), 'unknown')
        if active and phase == 'unknown':
            label = self.read(img, 'clear', threshold=135, invert=True, psm=11).text.upper()
            stamp = self.read(img, 'result_track', scale=4).text.upper()
            if (re.search(r'\b(?:CLEAR|FAILED|TRACK\s*RESULT)\b', label)
                    or (self.loss_of_play is not None and timestamp - self.loss_of_play >= 0.5
                        and re.search(r'\bTRACK\s*[(O0]', stamp))):
                phase = 'result'
            elif re.search(TEXT['skip'], self.read(img, 'round_skip', psm=11).text.upper()):
                phase = 'skip'
        if active and phase in {'skip', 'result'}:
            finished_at = self.loss_of_play if self.loss_of_play is not None else timestamp
            if phase == 'skip' or timestamp - finished_at > 8:
                finished_at = timestamp
            capture = self.capture_epoch(img) if live else None
            result_epoch = capture if capture is not None else frame.epoch
            epoch = result_epoch
            if epoch is not None:
                epoch -= timestamp - finished_at
            final = self.score(img, 'result_score') if tracker.accepts_score(frame) else None
            self.reset()
            return replace(frame, phase=phase, final_score=final, end_time=finished_at, end_epoch=epoch,
                           result_epoch=result_epoch)
        if not active and phase == 'unknown':
            hint = self.read(img, 'profile_hint').text
            if re.search(TEXT['profile'], header + '\n' + hint.upper()):
                phase = 'profile'
            elif re.search(TEXT['idle'], self.read(img, 'footer', 11).text.upper()):
                phase = 'idle'
            elif track:
                phase = 'ready'
            else:
                difficulty = DIFFICULTY.search(header)
                if difficulty:
                    phase = 'ready'
        if (not active or recovering) and phase in {'ready', 'profile', 'result', 'idle', 'credit_end'}:
            self.play_start = None
            self.play_votes = 0
            self.loss_of_play = None
            self.modes = {name: ScoreMode(self.hud_modes.get(name, 'auto')) for name in self.modes}
        if phase == 'profile' and (tracker.last_phase != 'profile' or self.needs_name(tracker)):
            name = (self.read(img, 'profile_name', scale=3) if 'AIME' in hint.upper() else
                    self.player_name(img))
            frame = self.named(frame, img, name, track)
        if phase == 'ready':
            title, kind, difficulty = self.metadata(img, menu=True)
            if track and (track == 1 or self.needs_name(tracker)):
                frame = self.named(frame, img, self.player_name(img), track)
            frame = replace(frame, title=title, kind=kind, difficulty=difficulty)
        return replace(frame, phase=phase, track=track)


class CabinetVision(Vision):
    """Track one physical seat using its separate cabinet HUD in the dual layout."""

    def __init__(self, width, height, seat, ocr, profile=None):
        profile = profile or {}
        self.standard_hud = 'upper_score' not in profile.get('regions', {})
        super().__init__(width, height, {**profile, 'regions': {
            **cabinet_regions(seat), **profile.get('regions', {})}}, ocr=ocr)

    def reset(self):
        super().reset()
        self.blank_since = None

    def score(self, img, key):
        # The 2P broadcast uses the same direct upper display at a smaller scale.
        crop = self.crop(img, key)
        old = self.score_cache.get(key)
        if old is not None and not self.cv2.absdiff(old[0], crop).max():
            return old[1]
        value = score_digits(crop) if self.standard_hud else None
        if value is None:
            value = super().score(img, key)
        self.score_cache[key] = crop.copy(), value
        return value

    def hud_visible(self, img):
        panel = self.crop(img, 'upper_score')
        h, w = panel.shape
        return ((panel[h // 6:5 * h // 6, :w // 9] < 88).mean() > 0.77 and
                (panel[h // 6:5 * h // 6, -w // 10:] < 88).mean() > 0.77 and
                (panel[h // 6:5 * h // 6, w // 8:7 * w // 8] > 155).mean() > 0.055)

    def inspect(self, image, tracker, live=False):
        timestamp = image.time
        frame = Frame(timestamp, epoch=image.epoch, gap=image.discontinuity)
        recovering = live and tracker.checking_resume(frame)
        if image.discontinuity and not recovering:
            self.reset()
        img = self.np.frombuffer(image.pixels, self.np.uint8).reshape(self.height, self.width)
        active = tracker.active is not None
        if self.hud_visible(img):
            self.blank_since = self.loss_of_play = None
            first = self.play_start is None
            if first or (timestamp - self.last_field >= 0.55 and (recovering or not active or not tracker.active.chart)):
                self.last_field = timestamp
                title, kind, difficulty = self.metadata(img, cabinet_only=True)
                if first and not difficulty:
                    return frame
                frame = replace(frame, title=title, kind=kind, difficulty=difficulty)
                if recovering:
                    frame = self.named(frame, img, self.player_name(img), self.track_number(img))
            if first:
                self.play_start = timestamp
            if not recovering and (first or self.needs_name(tracker)) and (
                    timestamp - self.play_start <= 5 and timestamp - self.last_name >= 0.35):
                self.last_name = timestamp
                track = self.track_number(img)
                frame = (self.named(frame, img, self.player_name(img), track)
                         if track == 1 or self.needs_name(tracker) else replace(frame, track=track))
                if first and not active and frame.track and not tracker.ready_pending and tracker.previous is not None:
                    return replace(frame, phase='ready')
            samples = ()
            if tracker.accepts_score(frame):
                samples = self.modes['upper_score'].add(timestamp, self.score(img, 'upper_score'),
                                                         timestamp - self.play_start)
            origin = self.play_start + float(self.origin_offset) if self.origin_offset is not None else None
            return replace(frame, phase='start' if first else 'playing', start_time=self.play_start, samples=samples,
                           origin=origin, timing_error=self.origin_error if origin is not None else 0)
        if self.loss_of_play is None and active:
            self.loss_of_play = timestamp
        if timestamp - self.last_menu < 0.4:
            return frame
        self.last_menu = timestamp
        track = self.track_number(img)
        if active:
            notice = self.read(img, 'camera_notice', psm=11).text.upper()
            if re.search(TEXT['skip'], notice):
                self.reset()
                return replace(frame, phase='skip', end_time=timestamp, result_epoch=frame.epoch, end_epoch=frame.epoch)
            # Both cabinets show the judgment table in the upper display on results.
            result = self.read(img, 'upper_result', psm=11, scale=3).text.upper()
            if len(re.findall(r'\b(?:CRITICAL|PERFECT|GREAT|GOOD|MISS)\b', result)) >= 2:
                end = self.loss_of_play if self.loss_of_play is not None else timestamp
                self.reset()
                return replace(frame, phase='result', end_time=end, result_epoch=frame.epoch,
                               end_epoch=frame.epoch - (timestamp - end) if frame.epoch is not None else None)
            if timestamp - self.loss_of_play < 8 and (track is None or track == tracker.last_track):
                return frame
        if track is not None:
            if self.play_start is not None:
                self.reset()
            self.blank_since = None
            ready = replace(frame, phase='ready', track=track)
            return (self.named(ready, img, self.player_name(img), track)
                    if track == 1 or self.needs_name(tracker) else ready)
        if self.blank_since is None:
            self.blank_since = timestamp
        if timestamp - self.blank_since >= 3:
            self.play_start = None
            return replace(frame, phase='credit_end')
        return frame


class BroadcastVision:
    def __init__(self, width, height, profile=None):
        self.single = Vision(width, height, profile)
        configs = (profile or {}).get('seats', {})
        self.dual = {seat: CabinetVision(width, height, seat, self.single.ocr, configs.get(seat))
                     for seat in ('left', 'right')}
        self.layout = ()
        self.checked_at = float('-inf')

    def close(self):
        self.single.close()

    def inspect_seats(self, image, trackers, live):
        previous_layout = self.layout
        active = any(tracker.active for tracker in trackers.values())
        if image.discontinuity or image.time - self.checked_at >= (2 if active else .6):
            self.checked_at = image.time
            single = self.single
            img = single.np.frombuffer(image.pixels, single.np.uint8).reshape(single.height, single.width)
            labels = {key: single.read(img, key, threshold=220, invert=True, scale=3).text
                      for key in ('left_badge', 'right_badge', 'single_badge')}
            if (re.search(r'PLAYER\s*1', labels['left_badge'], re.I) and
                    re.search(r'PLAYER\s*2', labels['right_badge'], re.I)):
                layout = ('left', 'right')
            elif seat := re.search(r'PLAYER\s*([12])', labels['single_badge'], re.I):
                layout = ('left' if seat[1] == '1' else 'right',)
            else:
                layout = self.layout
            if layout != self.layout:
                for screen in (self.single, *self.dual.values()):
                    screen.reset()
                self.layout = layout
        if previous_layout and previous_layout != self.layout:
            image = replace(image, discontinuity=True)
        screens = self.dual if len(self.layout) == 2 else dict.fromkeys(self.layout, self.single)
        return {seat: screens[seat].inspect(image, trackers[seat], live) for seat in self.layout}
