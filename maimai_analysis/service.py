"""Schedule shared video decoding, track both seats, and deliver results."""

import asyncio
from discord import HTTPException
from dataclasses import replace
import logging
import os
from threading import Event
import time

from .alignment import align_from_gain, align_from_judgments
from .capture import CAPTURE_FPS, CaptureAlignment
from .catalog import Catalog
from .delivery import Delivery
from .jobs import Job, choose_guest, play_key
from .mai_notes import MaiNotes
from .media import Decoder, MediaError
from .store import Store
from .tracking import Frame, Tracker, identity_key
from .vision import BroadcastVision, Vision
from .vod_relay import resolve_for_bot
from .youtube import Video

log = logging.getLogger(__name__)


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


def bounds(jobs, duration):
    intervals = sorted((job.start, min(job.end, duration) if job.end is not None else duration)
                       for job in jobs)
    merged = []
    for start, end in intervals:
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


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
        self.max_live = int(os.getenv('MAIMAI_MAX_LIVE', '1'))
        if (not 1 <= self.max_live <= 8 or not 2 <= self.decoder.fps <= 20 or
                not 320 <= self.decoder.width <= 1920 or not 180 <= self.decoder.height <= 1080):
            raise ValueError('maimai 디코더 해상도, FPS 또는 라이브 작업 제한이 올바르지 않습니다.')
        self.target_keys = self.store.target_keys()
        self.live_jobs = {}
        self.live = {}
        self.busy = {}
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

    async def db(self, method, *args, **kwargs):
        return await asyncio.to_thread(method, *args, **kwargs)

    @classmethod
    async def create(cls, get_index, open_dm):
        store = await asyncio.to_thread(Store, os.getenv('MAIMAI_ANALYSIS_DB', 'data/maimai-analysis.sqlite3'))
        return cls(store, get_index, open_dm)

    async def start(self):
        if self.vod_worker is None:
            self.vod_worker = asyncio.create_task(self.vod_queue(), name='maimai-vod')

    async def close(self):
        if self.stop.is_set():
            return
        self.stop.set()
        self.wake.set()
        tasks = [*self.live.values(), *self.sync_jobs]
        if self.vod_worker:
            tasks.append(self.vod_worker)
        await asyncio.gather(*tasks, return_exceptions=True)

    async def submit(self, user_id, video, live, end, chart_key, nickname, include_guest=False):
        if end is not None and end <= video.start:
            raise ValueError('종료시간은 영상 시작 시각 이후여야 합니다.')
        if nickname is not None:
            nickname = await self.db(self.store.set_nickname, user_id, nickname)
        else:
            nickname = await self.db(self.store.nickname, user_id)
        if not nickname and (live or not include_guest):
            raise ValueError('첫 분석에는 플레이어명에 게임 화면의 maimai 닉네임을 입력해주세요.')
        start = video.start if not live or video.start else None
        job = Job(user_id, video.id, live, start, end, nickname, chart_key, include_guest)
        async with self.lifecycle:
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
                try:
                    await self.delivery.waiting(job)
                except HTTPException as error:
                    raise ValueError('Discord DM을 받을 수 있도록 설정한 후 다시 시도해주세요.') from error
                self.live_jobs[video.id] = (*current, job)
                self.launch_lives()
            else:
                for existing in (*self.pending, *self.vod_jobs):
                    if ((existing.user_id, existing.video, existing.start, existing.end,
                         existing.nickname, existing.include_guest) ==
                            (user_id, video.id, start, end, nickname, include_guest)):
                        return existing
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
            if len(self.live) >= self.max_live:
                break
            if video not in self.live and video != self.vod_video:
                self.busy[video] = Event()
                self.live[video] = asyncio.create_task(self.run_live(video), name=f'maimai-live:{video}')

    def scan(self, video, source, start, end, live, get_jobs, publish, sync_chart=None, capture=None):
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
        frames = (self.decoder.live(source, start, stop=self.stop, busy=self.busy[video]) if live else
                  self.decoder.vod(source, start, end, fps=CAPTURE_FPS) if capture else
                  self.decoder.vod(source, start, end))
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
                if self.stop.is_set():
                    break
                if not live:
                    while any(event.is_set() for event in tuple(self.busy.values())) and not self.stop.is_set():
                        self.stop.wait(0.05)
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
        if self.stop.is_set():
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
            source = await self.db(self.resolve_source, Video(video, 0), True, self.decoder.height)
            start = min((job.start for job in get_jobs() if job.start is not None), default=None)
            await self.db(self.scan, video, source, start, None, True, get_jobs,
                          lambda kind, play: loop.call_soon_threadsafe(queue.put_nowait, (kind, play)))
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
                    self.busy.pop(video, None)
                    self.wake.set()
                    if not self.stop.is_set():
                        self.launch_lives()
                if not self.stop.is_set():
                    for job in finished_jobs:
                        job.error = error
                        await self.deliver(job, self.delivery.history)
                        await self.deliver(job, self.delivery.ended)

    async def vod_queue(self):
        while not self.stop.is_set():
            self.wake.clear()
            video = next((job.video for job in self.pending if job.video not in self.live), None)
            if video is None:
                await self.wake.wait()
                continue
            await self.run_vod(video)

    async def run_vod(self, video):
        plays = []
        error = None
        duration = None
        async with self.vod_lock:
            if video in self.live:
                return
            self.vod_video = video
            try:
                source = await self.db(self.resolve_source, Video(video, 0), False, self.decoder.height)
                duration = source.duration
                if not duration:
                    raise MediaError('YouTube 다시보기의 영상 길이를 확인하지 못했습니다.')
                self.vod_jobs = tuple(job for job in self.pending if job.video == video)
                self.pending = [job for job in self.pending if job.video != video]
                for start, end in bounds(self.vod_jobs, duration):
                    if self.stop.is_set():
                        break
                    await self.db(self.scan, video, source, start, end, False, lambda: self.vod_jobs,
                                  lambda kind, play: plays.append(play))
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
                    job.error = '시작 시간이 영상 길이를 벗어납니다.' if duration and job.start >= duration else error
                    for play in plays:
                        if job.matches(play):
                            await self.send_play(job, play)
                    await self.deliver(job, self.delivery.history)
        finally:
            self.vod_jobs = ()

    async def calibrate(self, video, chart_key, chart, times):
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
            if self.stop.is_set():
                raise MediaError('영상 분석이 종료 중입니다.')
            if video.id in self.live:
                raise ValueError('이미 수신 중인 라이브입니다. 첫노트시간을 입력해주세요.')
            self.vod_video = video.id
            try:
                source = await self.db(self.resolve_source, video, False, self.decoder.height)
                capture = await self.db(CaptureAlignment, self.decoder.width, self.decoder.height, chart, times)
                await self.db(self.scan, video.id, source, start, end, False, tuple,
                              lambda kind, play: plays.append(play), (chart_key, chart), capture)
            finally:
                self.vod_video = None
                if not self.stop.is_set():
                    self.launch_lives()
        origin = candidates(plays)
        if origin is None:
            origin = await self.db(capture.origin)
        if origin is None:
            raise ValueError('첫 노트 판정을 자동 확인하지 못했습니다. 첫노트시간을 입력해주세요.')
        return origin

    async def calibrate_for_interaction(self, video, chart_key, chart, times):
        task = asyncio.create_task(self.calibrate(video, chart_key, chart, times))
        self.sync_jobs.add(task)

        def completed(task):
            self.sync_jobs.discard(task)
            if not task.cancelled():
                task.exception()

        task.add_done_callback(completed)
        return await asyncio.wait_for(asyncio.shield(task), timeout=600)

    async def save_target(self, user_id, chart_key, cached, sections):
        await self.db(self.store.save_target, user_id, chart_key, cached, sections)
        self.target_keys = await self.db(self.store.target_keys)

    @staticmethod
    def describe(problem):
        if isinstance(problem, (ValueError, MediaError)):
            return str(problem)
        return '영상 입력 또는 프레임 처리에 실패했습니다.'


