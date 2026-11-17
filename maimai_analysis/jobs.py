"""Per-command state kept only while this process is analyzing a video."""

from dataclasses import dataclass, field

from .tracking import Play, identity_key


@dataclass(eq=False)
class Job:
    user_id: int
    video: str
    live: bool
    start: float | None
    end: float | None
    nickname: str | None
    chart_key: str | None
    include_guest: bool = False
    error: str | None = None
    waiting: str | None = None
    started: dict[tuple[str, float], str] = field(default_factory=dict)
    reports: dict[tuple[str, float], str] = field(default_factory=dict)
    history: list[str] = field(default_factory=list)
    plays: list[Play] = field(default_factory=list)

    def in_range(self, play):
        return ((self.chart_key is None or (play.chart and self.chart_key == play.chart.key)) and
                (self.start is None or self.start <= play.start) and (self.end is None or play.start < self.end))

    def matches(self, play):
        if play.identity_ambiguous or not self.in_range(play):
            return False
        if identity_key(play.nickname) == 'guest':
            return play.guest and play.guest_user == self.user_id and (self.live or self.include_guest)
        return bool(play.nickname and identity_key(self.nickname) == identity_key(play.nickname))


def play_key(play):
    return play.seat, play.start


def choose_guest(guest, players, initial_jobs):
    """Return one opting-in user only when the visible seats allow attribution."""
    if not guest.guest or sum(identity_key(player.nickname) == 'guest' for player in players) != 1:
        return None
    if any(player is not guest and not player.nickname for player in players):
        return None
    named = {identity_key(player.nickname) for player in players if player is not guest}
    users = {job.user_id for job in initial_jobs if job.in_range(guest) and identity_key(job.nickname) not in named}
    return next(iter(users)) if len(users) == 1 else None
