"""One state machine per video with conservative credit and track ownership."""

from dataclasses import dataclass, field
import unicodedata

from .scoring import Sample

# A much longer jump can hide an entire transition, even with matching HUD text.
MAX_RESUME_GAP = 20
RESUME_CHECK_SECONDS = 2


def identity_name(name: str) -> str:
    return unicodedata.normalize('NFKC', name).strip()


def identity_key(name: str | None) -> str | None:
    return identity_name(name).casefold() if name else None


@dataclass(frozen=True)
class Chart:
    key: str
    title: str
    kind: str
    difficulty: str
    constant: str | None


@dataclass(frozen=True)
class Frame:
    time: float
    phase: str = 'unknown'
    nickname: str | None = None
    confidence: float = 0
    title: str | None = None
    kind: str | None = None
    difficulty: str | None = None
    origin: float | None = None
    samples: tuple[Sample, ...] = ()
    gap: bool = False
    final_score: str | None = None
    track: int | None = None
    epoch: float | None = None
    timing_error: float = 0
    start_time: float | None = None
    end_time: float | None = None
    end_epoch: float | None = None
    judged: int | None = None
    result_epoch: float | None = None
    rating: int | None = None


@dataclass
class Play:
    chart: Chart | None
    nickname: str | None
    confidence: float
    start: float
    end: float | None = None
    origin: float | None = None
    status: str = 'playing'
    samples: list[Sample] = field(default_factory=list)
    gaps: list[tuple[float, float]] = field(default_factory=list)
    final_score: str | None = None
    end_epoch: float | None = None
    timing_error: float = 0
    start_epoch: float | None = None
    received_end: float | None = None
    judgments: list[tuple[float, int]] = field(default_factory=list)
    result_epoch: float | None = None
    seat: str = 'single'
    guest: bool = False
    guest_user: int | None = None
    identity_ambiguous: bool = False


class Tracker:
    def __init__(self, resolve, targeted, seat='single'):
        self.resolve = resolve
        self.targeted = targeted
        self.seat = seat
        self.nickname = None
        self.confidence = 0
        self.candidate = None
        self.ready = None
        self.active = None
        self.previous = None
        self.last_track = None
        self.last_phase = None
        self.ready_pending = False
        self.waiting_since = None
        self.resume_until = None
        self.guest = False
        self.guest_evidence = False

    def reset_identity(self):
        self.nickname = self.candidate = None
        self.confidence = 0
        self.last_track = None
        self.guest = self.guest_evidence = False

    def accepts_score(self, frame: Frame) -> bool:
        play = self.active
        return bool(play and play.chart and self.targeted(play))

    def has_gap(self, frame):
        return frame.gap or (self.previous is not None and frame.time - self.previous > 1.25)

    def checking_resume(self, frame):
        return self.active is not None and (self.resume_until is not None or self.has_gap(frame))

    def finish(self, time, status, epoch=None, score=None):
        play, self.active = self.active, None
        if play:
            if self.resume_until is not None:
                time = play.gaps[-1][0]
            play.end, play.status, play.end_epoch = max(play.start, time), status, epoch
            play.final_score = score
        self.resume_until = None
        return play

    def feed(self, frame: Frame, *, live=False) -> tuple[Play | None, Play | None]:
        complete = start = None
        gap = self.has_gap(frame)
        if live and self.checking_resume(frame):
            play = self.active
            if self.resume_until is None:
                self.resume_until = frame.time + RESUME_CHECK_SECONDS
                play.gaps.append((self.previous if self.previous is not None else play.start, frame.time))
            before, _ = play.gaps[-1]
            play.gaps[-1] = (before, frame.time)
            playing = frame.phase in {'start', 'playing'}
            chart = self.resolve(frame) if playing else None
            name = identity_key(frame.nickname) if frame.confidence >= 80 else None
            prior_name = identity_key(play.nickname)
            same_name = name is not None and name == prior_name and name != 'guest'
            tracks_known = frame.track is not None and self.last_track is not None
            conflict = ((chart and chart != play.chart) or (name and prior_name and name != prior_name) or
                        (tracks_known and frame.track != self.last_track))
            plausible = not conflict and frame.time - before <= MAX_RESUME_GAP
            if plausible and chart and (same_name or tracks_known):
                self.resume_until = None
                gap = False
            elif plausible and (playing or frame.phase == 'unknown') and frame.time < self.resume_until:
                self.previous = frame.time
                return None, None
            else:
                complete = self.finish(frame.time, 'interrupted')
                gap = True
        if gap:
            if self.active:
                before = self.previous if self.previous is not None else self.active.start
                self.active.gaps.append((before, frame.time))
                complete = self.finish(before, 'interrupted')
            self.reset_identity()
            self.ready = None
            self.ready_pending = False
        self.previous = frame.time

        if frame.phase in {'credit_end', 'idle'} or (
                frame.track == 1 and self.last_track is not None and self.last_track > 1):
            complete = self.finish(frame.time, 'interrupted', frame.epoch) or complete
            self.ready = None
            self.ready_pending = False
            self.reset_identity()
        if frame.track is not None:
            self.last_track = frame.track

        if frame.phase == 'profile' and self.last_phase != 'profile':
            self.reset_identity()
        confirming_active = (self.active and (not self.active.nickname or
                             (identity_key(self.active.nickname) == 'guest' and not self.active.guest)) and
                             frame.phase in {'start', 'playing'} and
                             frame.time - self.active.start <= 5)
        if frame.nickname and frame.confidence >= 80 and (not self.active or confirming_active or frame.phase == 'profile'):
            name = identity_name(frame.nickname)
            if self.nickname is not None and identity_key(name) != identity_key(self.nickname):
                self.reset_identity()
            if identity_key(name) == 'guest' and frame.rating == 0 and frame.track == 1:
                self.guest_evidence = True
            if self.candidate and identity_key(self.candidate[0]) == identity_key(name):
                if frame.time > self.candidate[2]:
                    self.nickname, self.confidence = name, min(frame.confidence, self.candidate[1])
                    self.guest = identity_key(name) == 'guest' and self.guest_evidence
                    if confirming_active:
                        self.active.nickname, self.active.confidence = self.nickname, self.confidence
                        self.active.guest = self.guest
            else:
                self.candidate = (name, frame.confidence, frame.time)
                if identity_key(name) != 'guest':
                    self.guest_evidence = False
        elif frame.phase == 'profile' and not frame.nickname:
            self.candidate = None

        if frame.phase == 'ready':
            complete = self.finish(frame.time, 'interrupted', frame.epoch) or complete
            if not self.ready_pending:
                self.ready = None
            self.ready_pending = True
            self.waiting_since = frame.time
            candidate = self.resolve(frame)
            if candidate:
                self.ready = candidate
        elif frame.phase in {'start', 'playing'}:
            if self.active is None and self.ready_pending:
                start_time = frame.start_time if frame.start_time is not None else frame.time
                epoch = frame.epoch - (frame.time - start_time) if frame.epoch is not None else None
                self.active = start = Play(self.resolve(frame) or self.ready, self.nickname, self.confidence,
                                           start_time, start_epoch=epoch, seat=self.seat, guest=self.guest)
                self.ready = None
                self.ready_pending = False
            if self.active:
                self.active.chart = self.active.chart or self.resolve(frame)
                if frame.origin is not None and self.active.origin is None and not self.active.gaps:
                    self.active.origin, self.active.timing_error = frame.origin, frame.timing_error
                if self.accepts_score(frame):
                    self.active.samples.extend(frame.samples)
                    if frame.judged is not None:
                        self.active.judgments.append((frame.time, frame.judged))
        elif frame.phase in {'result', 'skip'}:
            if self.accepts_score(frame):
                self.active.samples.extend(frame.samples)
            complete = self.finish(frame.end_time if frame.end_time is not None else frame.time,
                                   'skipped' if frame.phase == 'skip' else 'finished',
                                   frame.end_epoch if frame.end_epoch is not None else frame.epoch,
                                   frame.final_score) or complete
            if complete and complete.status in {'finished', 'skipped'}:
                complete.result_epoch = frame.result_epoch
            self.ready = None
            self.ready_pending = False
            self.waiting_since = frame.time
        if self.active is None and self.waiting_since is not None and frame.time - self.waiting_since > 120:
            self.reset_identity()
            self.ready = None
            self.ready_pending = False
            self.waiting_since = None
        if frame.phase != 'unknown':
            self.last_phase = frame.phase
        return start, complete
