"""Schedule shared video decoding, track both seats, and deliver results."""

import asyncio
from contextlib import closing
from discord import HTTPException
from dataclasses import dataclass, field, replace
import logging
import os
from threading import Event
import time
from requests import RequestException

from .alignment import align_from_gain, align_from_judgments
from .capture import CAPTURE_FPS, CaptureAlignment
from .catalog import Catalog
from .delivery import Delivery
from .jobs import Job, choose_guest, play_key
from .mai_notes import MaiNotes
from .media import Decoder, DVRRangeError, MediaError
from .store import Store
from .tracking import Frame, Tracker, identity_key, identity_name
from .vision import BroadcastVision, Vision
from .vod_relay import resolve_for_bot
from .youtube import Video

log = logging.getLogger(__name__)
STOPPED = '새 요청으로 분석을 중단했습니다.'
CALIBRATION_TIMEOUT = 600


@dataclass(eq=False)
class AnalysisRun:
    owner: int
    kind: str
    video: str
    window: tuple
    cancel: Event = field(default_factory=Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    shareable: bool = False


class AnalysisBusy(ValueError):
    def __init__(self, run):
        super().__init__('다른 영상 분석이 진행 중입니다.')
        self.run = run


def resource_usage():
    import psutil

    proc = psutil.Process()
    cpu, rss = 0.0, 0
    for process in [proc, *proc.children(recursive=True)]:
        try:
            times = process.cpu_times()
            cpu += times.user + times.system
            rss += process.memory_info().rss
        except psutil.NoSuchProcess:
            continue
    if os.name == 'posix':
        import resource

        children = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu += children.ru_utime + children.ru_stime
    return cpu, rss / 1024 ** 2


class AnalysisService:
    def __init__(self, store, get_index, open_dm, decoder=None, make_vision=None, resolve_source=resolve_for_bot):
        self.store = store
        self.notes = MaiNotes(store)
        self.delivery = Delivery(store, open_dm)
        self.get_index = get_index
        self.decoder = decoder or Decoder(height=int(os.getenv('MAIMAI_HEIGHT', '720')),
                                          width=int(os.getenv('MAIMAI_WIDTH', '1280')),
                                          fps=int(os.getenv('MAIMAI_FPS', '8')))
        self.make_vision = make_vision or (lambda: BroadcastVision(
            self.decoder.width, self.decoder.height, Vision.profile()))
        self.resolve_source = resolve_source
        if (not 2 <= self.decoder.fps <= 20 or
                not 320 <= self.decoder.width <= 1920 or not 180 <= self.decoder.height <= 1080):
            raise ValueError('maimai 디코더 해상도, FPS 또는 라이브 작업 제한이 올바르지 않습니다.')
        self.target_keys = self.store.target_keys()
        self.live_jobs = {}
        self.live = {}
        self.cursors = {}
        self.pending = []
        self.vod_jobs = ()
        self.vod_video = None
        self.vod_lock = asyncio.Lock()
        self.lifecycle = asyncio.Lock()
        self.wake = asyncio.Event()
        self.stop = Event()
        self.vod_worker = None
        self.sync_jobs = set()
        self.current = None

    async def db(self, method, *args, **kwargs):
        return await asyncio.to_thread(method, *args, **kwargs)

    @classmethod
    async def create(cls, get_index, open_dm):
        store = await asyncio.to_thread(Store, os.getenv('MAIMAI_ANALYSIS_DB', 'data/maimai-analysis.sqlite3'))
        return cls(store, get_index, open_dm)

    async def start(self):
        if self.vod_worker is None:
            self.vod_worker = asyncio.create_task(self.vod_queue(), name='maimai-vod')
            log.info('maimai analysis ready fps=%s omp_thread_limit=%s', self.decoder.fps,
                     os.getenv('OMP_THREAD_LIMIT', 'default'))

    async def close(self):
        if self.stop.is_set():
            return
        self.stop.set()
        if self.current:
            self.current.cancel.set()
        self.wake.set()
        tasks = [*self.live.values(), *self.sync_jobs]
        if self.vod_worker:
            tasks.append(self.vod_worker)
        await asyncio.gather(*tasks, return_exceptions=True)

    async def reserve(self, user_id, kind, video, window, replace_run):
        while True:
            async with self.lifecycle:
                if self.stop.is_set():
                    raise MediaError('영상 분석이 종료 중입니다.')
                run = self.current
                if run is None:
                    self.current = AnalysisRun(user_id, kind, video, window)
                    return self.current, True
                if run is not replace_run:
                    if (run.shareable and not run.cancel.is_set() and (run.kind, run.video, run.window) ==
                            (kind, video, window)):
                        return run, False
                    if run.owner != user_id:
                        raise ValueError('현재 작업은 분석을 요청한 사람만 중단할 수 있습니다.')
                    raise AnalysisBusy(run)
                if run.owner != user_id:
                    raise ValueError('현재 작업은 분석을 요청한 사람만 중단할 수 있습니다.')
                run.cancel.set()
            await run.done.wait()
            replace_run = None

    def release(self, run):
        if run is not None:
            if self.current is run:
                self.current = None
            run.done.set()

    async def submit(self, user_id, video, live, end, chart_key, nickname, include_guest=False, *, replace_run=None):
        if end is not None and end <= video.start:
            raise ValueError('종료시간은 영상 시작 시각 이후여야 합니다.')
        start = video.start if not live or video.start else None
        run, created = await self.reserve(user_id, 'live' if live else 'vod', video.id, (start, end), replace_run)
        try:
            job = await self.register_job(run, user_id, video, live, start, end, chart_key, nickname, include_guest)
            run.shareable = True
            return job
        except (Exception, asyncio.CancelledError):
            if created:
                self.release(run)
            raise

    async def register_job(self, run, user_id, video, live, start, end, chart_key, nickname, include_guest):
        provided = nickname is not None
        nickname = identity_name(nickname) if provided else await self.db(self.store.nickname, user_id)
        if not provided and not nickname and (live or not include_guest):
            raise ValueError('첫 분석에는 플레이어명에 게임 화면의 maimai 닉네임을 입력해주세요.')
        job = Job(user_id, video.id, live, start, end, nickname, chart_key, include_guest)
        async with self.lifecycle:
            if self.current is not run or run.cancel.is_set():
                raise ValueError('진행 중인 작업이 바뀌었습니다. 명령을 다시 실행해주세요.')
            if live:
                current = self.live_jobs.get(video.id, ())
                for existing in current:
                    if existing.user_id == user_id:
                        if (existing.start, existing.chart_key, identity_key(existing.nickname)) != (
                                start, chart_key, identity_key(nickname)):
                            raise ValueError('이 방송을 이미 분석 중입니다. 게스트 포함 여부는 /라이브분석-게스트토글에서 바꿀 수 있습니다.')
                        return existing
                if start is not None and self.cursors.get(video.id, 0) > start:
                    raise ValueError('이 시각은 이미 분석 중인 라이브의 현재 수신 지점보다 이전입니다.')
            else:
                for existing in (*self.pending, *self.vod_jobs):
                    if ((existing.user_id, existing.video, existing.start, existing.end,
                         existing.nickname, existing.include_guest) ==
                            (user_id, video.id, start, end, nickname, include_guest)):
                        return existing
                if self.vod_jobs:
                    if run.owner == user_id:
                        raise AnalysisBusy(run)
                    raise ValueError('이미 프레임을 읽고 있어 이 다시보기 분석에 참가할 수 없습니다.')
            if provided:
                await self.db(self.store.set_nickname, user_id, nickname)
            if live:
                try:
                    await self.delivery.waiting(job)
                except HTTPException as error:
                    raise ValueError('Discord DM을 받을 수 있도록 설정한 후 다시 시도해주세요.') from error
                self.live_jobs[video.id] = (*current, job)
                self.launch_lives()
            else:
                self.pending.append(job)
                self.wake.set()
        return job

    async def toggle_guest(self, user_id, video=None):
        async with self.lifecycle:
            jobs = [job for key, jobs in self.live_jobs.items() if video is None or key == video
                    for job in jobs if job.user_id == user_id]
            if not jobs:
                raise ValueError('먼저 /라이브분석으로 방송을 등록해주세요.')
            if len(jobs) != 1:
                raise ValueError('분석 중인 방송이 여러 개입니다. 라이브링크를 지정해주세요.')
            job = jobs[0]
            job.include_guest = not job.include_guest
            return job.include_guest

    def launch_lives(self):
        for video in self.live_jobs:
            if self.live or (self.current and self.current.kind != 'live'):
                break
            if video not in self.live and video != self.vod_video:
                self.live[video] = asyncio.create_task(self.run_live(video), name=f'maimai-live:{video}')

    def live_frames(self, video, source, start, stop):
        last = None
        attempts = 0
        while not stop.is_set():
            try:
                if source is None:
                    source = self.resolve_source(Video(video, 0), True, self.decoder.height)
                with closing(self.decoder.live(source, start, stop=stop)) as frames:
                    for image in frames:
                        if stop.is_set():
                            return
                        if last is not None and image.time <= last:
                            continue
                        if attempts and last is not None and image.time - last > max(.35, 2 / self.decoder.fps):
                            image = replace(image, discontinuity=True)
                        last, attempts = image.time, 0
                        yield image
                return
            except (MediaError, RequestException, TimeoutError) as problem:
                if stop.is_set():
                    return
                if attempts >= 2 or (isinstance(problem, DVRRangeError) and last is None):
                    raise
                attempts += 1
                start = None if isinstance(problem, DVRRangeError) else last if last is not None else start
                source = None
                log.warning('maimai live reconnect video=%s from=%s attempt=%d', video, start, attempts)
                stop.wait(1)

    def scan(self, video, source, start, end, live, get_jobs, publish, sync_chart=None, capture=None, *, cancel=None):
        stop = cancel if cancel is not None else self.stop
        index = self.get_index()
        if index is None:
            raise MediaError('곡 검색 데이터를 준비 중입니다. 잠시 후 다시 시도해주세요.')
        catalog = Catalog(index)

        def targeted(play):
            if sync_chart:
                return play.chart.key == sync_chart[0]
            return any(job.matches(play) and (job.user_id, play.chart.key) in self.target_keys for job in get_jobs())

        trackers = {seat: Tracker(catalog.resolve, targeted, seat=seat) for seat in ('left', 'right')}
        vision = self.make_vision()
        frames = (self.live_frames(video, source, start, stop) if live else
                  self.decoder.vod(source, start, end, fps=CAPTURE_FPS, stop=stop) if capture else
                  self.decoder.vod(source, start, end, stop=stop))
        invitations = {}
        announced = set()
        last = first = None
        started_at = measured_at = time.monotonic()
        cpu, _ = resource_usage()
        count = 0
        track_at = start

        def finish(play, received):
            play.received_end = received
            if play.chart and (play.judgments or play.samples):
                chart = sync_chart[1] if sync_chart and play.chart.key == sync_chart[0] else None
                if not sync_chart:
                    for job in get_jobs():
                        if job.matches(play) and (job.user_id, play.chart.key) in self.target_keys:
                            target = self.store.target(job.user_id, play.chart.key)
                            if target and target.sections:
                                chart = target.cached.chart
                                break
                if chart:
                    alignment = (align_from_judgments(chart, play.judgments, play.start) or
                                 align_from_gain(chart, play.samples, play.start))
                    if alignment:
                        play.origin, play.timing_error = alignment
            publish('finish', play)
            invitations.pop(play.seat, None)
            announced.discard(play.seat)

        try:
            for image in frames:
                received = time.time()
                if stop.is_set():
                    break
                last = image.time
                first = last if first is None else first
                count += 1
                if live:
                    self.cursors[video] = last
                if capture:
                    capture.feed(image)
                    if not image.discontinuity and last + .001 < track_at:
                        continue
                    track_at = last + 1 / self.decoder.fps
                readings = vision.inspect_seats(image, trackers, live)
                for seat, tracker in trackers.items():
                    frame = readings.get(seat)
                    if frame is None and tracker.previous is None:
                        continue
                    if frame is None:
                        frame = Frame(last, 'credit_end')
                    started, completed = tracker.feed(frame)
                    if completed:
                        finish(completed, received)
                    if started:
                        invitations[seat] = tuple(job for job in get_jobs() if job.include_guest)
                players = [tracker.active for tracker in trackers.values() if tracker.active]
                identities = [identity_key(player.nickname) for player in players if player.nickname]
                if len(identities) == 2 and identities[0] == identities[1]:
                    for play in players:
                        play.identity_ambiguous = True
                for play in players:
                    if play.guest:
                        # Established players in the other seat are considered even before their song card appears.
                        others = [replace(play, nickname=trackers[seat].nickname, guest=False) for seat in readings
                                  if seat != play.seat and trackers[seat].active is None]
                        play.guest_user = choose_guest(play, players + others, invitations.get(play.seat, ()))
                    if (live and play.chart and play.seat not in announced and
                            any(job.matches(play) for job in get_jobs())):
                        announced.add(play.seat)
                        publish('start', replace(play, samples=[], judgments=[]))
                now = time.monotonic()
                if now - measured_at >= 30:
                    new_cpu, rss = resource_usage()
                    log.info('maimai resources video=%s live=%d position=%.3f frames=%d cpu_pct=%.1f rss_mib=%.1f',
                             video, live, last, count, 100 * max(0, new_cpu - cpu) / (now - measured_at), rss)
                    measured_at, cpu = now, new_cpu
        finally:
            frames.close()
            vision.close()
            if last is not None and not self.stop.is_set():
                for tracker in trackers.values():
                    if play := tracker.finish(last, 'interrupted'):
                        finish(play, None)
        if stop.is_set():
            return
        if last is None:
            raise MediaError('분석 범위 안에서 영상 프레임을 찾지 못했습니다.')
        log.info('maimai decode video=%s live=%d frames=%d video_seconds=%.3f elapsed_seconds=%.3f',
                 video, live, count, last - first, time.monotonic() - started_at)
        if not live and end is not None and last < min(end, source.duration or end) - 0.75:
            raise MediaError('요청한 범위의 끝까지 영상 프레임을 읽지 못했습니다.')

    async def deliver(self, job, method, *args):
        try:
            await method(job, *args)
        except HTTPException:
            log.warning('maimai Discord DM failed video=%s', job.video, exc_info=True)

    async def send_play(self, job, play):
        await self.deliver(job, self.delivery.finished, play)
        job.plays.append(replace(play, samples=[], judgments=[], gaps=[]))

    async def run_live(self, video):
        run = self.current
        cancel = run.cancel if run else self.stop
        queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        finished_jobs = None

        def get_jobs():
            return self.live_jobs.get(video, ()) if finished_jobs is None else finished_jobs

        async def consume():
            while (event := await queue.get()) is not None:
                kind, play = event
                for job in get_jobs():
                    if not job.matches(play):
                        if kind == 'finish' and play_key(play) in job.started:
                            await self.deliver(job, self.delivery.unconfirmed, play)
                        continue
                    if kind == 'start':
                        await self.deliver(job, self.delivery.started, play)
                    else:
                        await self.send_play(job, play)
                        await self.deliver(job, self.delivery.history)

        consumer = asyncio.create_task(consume())
        error = None
        try:
            start = min((job.start for job in get_jobs() if job.start is not None), default=None)
            await self.db(self.scan, video, None, start, None, True, get_jobs,
                          lambda kind, play: loop.call_soon_threadsafe(queue.put_nowait, (kind, play)), cancel=cancel)
        except Exception as problem:
            error = self.describe(problem)
            log.warning('maimai live failed video=%s error=%s', video, error)
        finally:
            async with self.lifecycle:
                finished_jobs = self.live_jobs.pop(video, ())
                self.cursors.pop(video, None)
            await queue.put(None)
            try:
                await consumer
            finally:
                async with self.lifecycle:
                    self.live.pop(video, None)
                    self.wake.set()
                    if not self.stop.is_set():
                        self.launch_lives()
                try:
                    if not self.stop.is_set():
                        for job in finished_jobs:
                            job.error = STOPPED if cancel.is_set() else error
                            await self.deliver(job, self.delivery.history)
                            await self.deliver(job, self.delivery.ended)
                finally:
                    self.release(run)

    async def vod_queue(self):
        while not self.stop.is_set():
            self.wake.clear()
            video = next((job.video for job in self.pending if job.video not in self.live), None)
            if video is None:
                await self.wake.wait()
                continue
            await self.run_vod(video)

    async def run_vod(self, video):
        run = self.current
        cancel = run.cancel if run else self.stop
        plays = []
        error = None
        duration = None
        async with self.vod_lock:
            if video in self.live:
                return
            self.vod_video = video
            try:
                if cancel.is_set():
                    raise MediaError(STOPPED)
                source = await self.db(self.resolve_source, Video(video, 0), False, self.decoder.height)
                duration = source.duration
                if not duration:
                    raise MediaError('YouTube 다시보기의 영상 길이를 확인하지 못했습니다.')
                self.vod_jobs = tuple(job for job in self.pending if job.video == video)
                self.pending = [job for job in self.pending if job.video != video]
                if self.vod_jobs and not cancel.is_set():
                    requested = self.vod_jobs[0]
                    end = min(requested.end, duration) if requested.end is not None else duration
                    if requested.start < end:
                        await self.db(self.scan, video, source, requested.start, end, False, lambda: self.vod_jobs,
                                      lambda kind, play: plays.append(play), cancel=cancel)
            except Exception as problem:
                error = self.describe(problem)
                log.warning('maimai VOD failed video=%s error=%s', video, error)
            finally:
                if not self.vod_jobs:
                    self.vod_jobs = tuple(job for job in self.pending if job.video == video)
                    self.pending = [job for job in self.pending if job.video != video]
                self.vod_video = None
                if not self.stop.is_set():
                    self.launch_lives()
        try:
            if not self.stop.is_set():
                for job in self.vod_jobs:
                    job.error = STOPPED if cancel.is_set() else (
                        '시작 시간이 영상 길이를 벗어납니다.' if duration and job.start >= duration else error)
                    for play in plays:
                        if job.matches(play):
                            await self.send_play(job, play)
                    await self.deliver(job, self.delivery.history)
        finally:
            self.vod_jobs = ()
            self.release(run)

    async def calibrate(self, video, chart_key, chart, times, *, cancel=None):
        first, last = min(times), max(times)

        def candidates(plays):
            origins = sorted(play.origin for play in plays if play.chart and play.chart.key == chart_key and
                             play.origin is not None and play.start <= first + 0.25 and play.end >= last - 0.25)
            # Both seats can share a chart and song clock.
            return origins[0] if origins and origins[-1] - origins[0] <= 0.15 else None

        if video.id in self.live:
            origin = candidates(play for job in self.live_jobs.get(video.id, ()) for play in job.plays)
            if origin is not None:
                return origin
            raise ValueError('수신 중인 라이브에서 일치 구간을 동기화하지 못했습니다. 첫노트시간을 입력해주세요.')
        start = max(0, first - chart.end - 30)
        end = last + 12
        plays = []
        async with self.vod_lock:
            if self.stop.is_set() or (cancel and cancel.is_set()):
                raise MediaError('영상 분석이 종료 중입니다.')
            if video.id in self.live:
                raise ValueError('이미 수신 중인 라이브입니다. 첫노트시간을 입력해주세요.')
            self.vod_video = video.id
            try:
                source = await self.db(self.resolve_source, video, False, self.decoder.height)
                if cancel and cancel.is_set():
                    raise MediaError(STOPPED)
                capture = await self.db(CaptureAlignment, self.decoder.width, self.decoder.height, chart, times)
                await self.db(self.scan, video.id, source, start, end, False, tuple,
                              lambda kind, play: plays.append(play), (chart_key, chart), capture, cancel=cancel)
            finally:
                self.vod_video = None
                if not self.stop.is_set():
                    self.launch_lives()
        if cancel and cancel.is_set():
            raise MediaError(STOPPED)
        origin = candidates(plays)
        if origin is None:
            origin = await self.db(capture.origin)
        if origin is None:
            raise ValueError('첫 노트 판정을 자동 확인하지 못했습니다. 첫노트시간을 입력해주세요.')
        return origin

    async def calibrate_for_interaction(self, video, chart_key, chart, times, *, user_id, replace_run=None):
        if replace_run is None and video.id in self.live:
            return await self.calibrate(video, chart_key, chart, times)
        run, _ = await self.reserve(user_id, 'sync', video.id, (), replace_run)
        task = asyncio.create_task(self.calibrate(video, chart_key, chart, times, cancel=run.cancel))
        self.sync_jobs.add(task)

        def completed(task):
            self.sync_jobs.discard(task)
            if not task.cancelled():
                task.exception()
            self.release(run)

        task.add_done_callback(completed)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=CALIBRATION_TIMEOUT)
        except (TimeoutError, asyncio.CancelledError):
            run.cancel.set()
            raise

    async def save_target(self, user_id, chart_key, cached, sections):
        await self.db(self.store.save_target, user_id, chart_key, cached, sections)
        self.target_keys = await self.db(self.store.target_keys)

    @staticmethod
    def describe(problem):
        if isinstance(problem, (ValueError, MediaError)):
            return str(problem)
        return '영상 입력 또는 프레임 처리에 실패했습니다.'


