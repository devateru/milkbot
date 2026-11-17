"""Build and update private Discord reports from the current analysis run."""

import asyncio
from datetime import datetime
import logging
import time
from zoneinfo import ZoneInfo

import discord

from .catalog import DIFFICULTIES
from .scoring import evaluate
from .jobs import play_key
from .youtube import video_link

SEOUL = ZoneInfo('Asia/Seoul')
log = logging.getLogger(__name__)
STATUSES = {'passed': '목표 달성', 'failed': '목표 미달성', 'skip-failed': '목표 미달성 (중도 스킵)',
            'skipped': '해당 구간 스킵됨', 'uncertain': '분석 불확실'}


def video_clock(seconds):
    hours, rest = divmod(int(seconds), 3600)
    minute, second = divmod(rest, 60)
    return f'{hours:02d}:{minute:02d}:{second:02d}'


def chart_label(chart):
    title = discord.utils.escape_markdown(chart.title)
    parts = [title, f'[{"DX" if chart.kind == "dx" else "ST"}]', f'[{DIFFICULTIES[chart.difficulty]}]']
    if chart.constant is not None:
        parts.append(f'[{chart.constant}]')
    return ' '.join(parts)


def paginated(title, blocks):
    descriptions = ['']
    for block in blocks:
        if len(descriptions[-1]) + len(block) > 3900:
            descriptions.append('')
        descriptions[-1] += ('\n\n' if descriptions[-1] else '') + block
    return [discord.Embed(title=title[:256], description=description, color=0xDA8EB2,
                          ) for description in descriptions]


def detail_embeds(video, play, results):
    blocks = [f'[{video_clock(play.start)}]({video_link(video, play.start)})']
    if play.final_score is not None:
        blocks[0] += f' · 최종 달성률 {play.final_score}%'
    if play.status == 'skipped':
        blocks.append(f'중도 스킵 [(&t={int(play.end)})]({video_link(video, play.end)})')
    if play.status in {'interrupted', 'uncertain'}:
        blocks.append('영상 유실 또는 종료 표식 누락으로 분석 불확실')
    for i, item in enumerate(results, 1):
        section = item.section
        value = f'구간 {i} ({section.first}~{section.last}) 목표 {section.allowance}%'
        if item.loss is not None:
            value += f' → 실제 -{item.loss:.4f}%'
        value = f'**{STATUSES[item.status]}**\n{value}'
        if item.status == 'failed' and item.timestamp is not None:
            value += f'\n[해당 구간 영상 (&t={item.timestamp})]({video_link(video, item.timestamp)})'
        blocks.append(value)
    return paginated(chart_label(play.chart), blocks)


class Delivery:
    def __init__(self, store, open_dm):
        self.store = store
        self.open_dm = open_dm

    async def update(self, channel, identifier=None, **payload):
        if identifier:
            try:
                message = await channel.fetch_message(int(identifier))
                await message.edit(**payload)
                return identifier
            except discord.NotFound:
                pass
        return str((await channel.send(**payload)).id)

    async def waiting(self, job):
        channel = await self.open_dm(job.user_id)
        job.waiting = await self.update(channel, content='다음 목표곡 라이브 대기 중...')

    async def started(self, job, play):
        key = play_key(play)
        if not play.chart or key in job.started or not job.matches(play):
            return
        target = await asyncio.to_thread(self.store.target, job.user_id, play.chart.key)
        if not target or not target.sections:
            return
        channel = await self.open_dm(job.user_id)
        clock = (datetime.fromtimestamp(play.start_epoch, SEOUL).strftime('%H:%M:%S')
                 if play.start_epoch is not None else video_clock(play.start))
        job.started[key] = await self.update(channel, job.waiting,
                                             content=f'{clock} 플레이 시작 확인\n{chart_label(play.chart)}',
                                             allowed_mentions=discord.AllowedMentions.none())
        job.waiting = None

    async def finished(self, job, play):
        key = play_key(play)
        if not play.chart or key in job.reports or not job.matches(play):
            return
        target = await asyncio.to_thread(self.store.target, job.user_id, play.chart.key)
        if not target or not target.sections:
            return
        results = await asyncio.to_thread(
            evaluate, target.cached.chart, target.sections, play.samples, play.origin, play.end,
            skipped=play.status == 'skipped', gaps=tuple(play.gaps), timing_error=play.timing_error)
        channel = await self.open_dm(job.user_id)
        for i, embed in enumerate(detail_embeds(job.video, play, results)):
            previous = (job.started.get(key) or job.waiting) if not i else None
            identifier = await self.update(channel, previous, content=None, embed=embed)
            if not i:
                job.reports[key] = identifier
                if previous == job.waiting:
                    job.waiting = None
                job.started.pop(key, None)
        if job.live and play.end_epoch is not None and play.received_end is not None:
            delivered, received = time.time(), play.received_end
            captured = play.result_epoch if play.result_epoch is not None else play.end_epoch
            log.info('maimai DM video=%s timestamp=%.3f youtube_seconds=%.3f result_wait_seconds=%.3f '
                     'processing_dm_seconds=%.3f total_seconds=%.3f', job.video, play.end,
                     received - captured, captured - play.end_epoch, delivered - received, delivered - play.end_epoch)

    async def ended(self, job):
        if job.waiting:
            channel = await self.open_dm(job.user_id)
            text = f'라이브 분석 오류 · {job.error}' if job.error else '라이브 분석이 종료되었습니다.'
            await self.update(channel, job.waiting, content=text)
            job.waiting = None

    async def unconfirmed(self, job, play):
        key = play_key(play)
        channel = await self.open_dm(job.user_id)
        await self.update(channel, job.started[key], content='플레이어의 자리를 확인하지 못했습니다.')
        job.started.pop(key, None)

    async def history(self, job):
        channel = await self.open_dm(job.user_id)
        blocks = []
        for play in sorted(job.plays, key=lambda item: (item.start, item.seat)):
            label = chart_label(play.chart) if play.chart else '곡 정보 확인 불가'
            if play.final_score:
                label += f' [{play.final_score}%]'
            if play.seat in {'left', 'right'}:
                label += ' · ' + ('왼쪽' if play.seat == 'left' else '오른쪽')
            if play.guest:
                label += ' · GUEST'
            line = f'{label} ([&t={int(play.start)}]({video_link(job.video, play.start)}))'
            if play.status in {'interrupted', 'uncertain'}:
                line += ' · 종료 확인 불가'
            if detail := job.reports.get(play_key(play)):
                line += f' · [구간 결과](https://discord.com/channels/@me/{channel.id}/{detail})'
            blocks.append(line)
        if not blocks:
            blocks.append('설정에 맞는 플레이를 확인하지 못했습니다.')
        if job.error:
            blocks.append(f'일부 분석을 완료하지 못했습니다. {job.error}')
        for i, embed in enumerate(paginated('통합 플레이 기록', blocks)):
            previous = job.history[i] if i < len(job.history) else None
            identifier = await self.update(channel, previous, embed=embed)
            if previous:
                job.history[i] = identifier
            else:
                job.history.append(identifier)


