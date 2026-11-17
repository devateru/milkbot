"""Discord commands for goals, note lookup, and video analysis."""

import asyncio
import logging
import re

import discord
from discord import app_commands

from .catalog import DIFFICULTIES, chart_record
from .delivery import video_clock
from .service import AnalysisService
from .simai import adjustment_footer, note_at, parse_sections
from .youtube import parse_time, parse_video, video_link


log = logging.getLogger(__name__)
CHOICES = [app_commands.Choice(name=name, value=key) for key, name in DIFFICULTIES.items()]


def parse_times(text):
    values = [parse_time(token) for token in re.split(r'[,\s]+', text.strip()) if token]
    if not 1 <= len(values) <= 25:
        raise ValueError('타임스탬프를 1~25개 입력해주세요.')
    return values


def goals_embed(make_song_embed, song, sheet, cached, sections, fallback=False):
    embed = make_song_embed(song, sheet, None)
    embed.remove_footer()
    embed.add_field(name=f'확인한 채보 · 전체 {len(cached.chart.notes)}노트', value=cached.url, inline=False)
    if fallback:
        embed.add_field(name='난이도', value='Re:MASTER 채보가 없어 MASTER를 선택했습니다.', inline=False)
    if not sections:
        embed.add_field(name='설정한 목표', value='구간목표 옵션이나 구간 편집에서 허용 감점률을 입력해주세요.', inline=False)
    for start in range(0, len(sections), 12):
        embed.add_field(name='설정한 목표' if start == 0 else '설정한 목표 (계속)', inline=False,
                        value='\n'.join(f'구간 {i} · 노트 {s.first}~{s.last} : {s.allowance}%'
                                        for i, s in enumerate(sections[start:start + 12], start + 1)))
    if footer := adjustment_footer(sections):
        embed.set_footer(text=footer)
    return embed


class ChartModal(discord.ui.Modal, title='채보 변경'):
    link = discord.ui.TextInput(label='mai-notes 채보 링크', required=True, max_length=255)

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.link.default = view.cached.url

    async def on_submit(self, interaction):
        view = self.view
        await interaction.response.defer()
        try:
            cached = await view.service.db(view.service.notes.load, self.link.value, view.chart, view.song, view.sheet)
        except ValueError as problem:
            await interaction.followup.send(str(problem), ephemeral=True)
            return
        text = ', '.join(f'{s.original}:{s.allowance}' for s in view.sections)
        sections = ()
        if text:
            try:
                sections = parse_sections(text, cached.chart)
            except ValueError as problem:
                await interaction.followup.send(f'새 채보에서 구간을 다시 입력해주세요. {problem}', ephemeral=True)
        view.cached, view.sections = cached, sections
        await interaction.edit_original_response(embed=view.embed(), view=view)


class SectionsModal(discord.ui.Modal, title='구간 편집'):
    segments = discord.ui.TextInput(label='시작 번호 또는 노트 수와 허용 감점률',
                                    placeholder='100개:-0.1, 나머지:-0.05 또는 1:-0.1, 101:-0.05',
                                    style=discord.TextStyle.paragraph, max_length=1500)

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.segments.default = ', '.join(f'{s.original}:{s.allowance}' for s in view.sections)

    async def on_submit(self, interaction):
        try:
            self.view.sections = parse_sections(self.segments.value, self.view.cached.chart)
        except ValueError as problem:
            await interaction.response.send_message(str(problem), ephemeral=True)
            return
        await interaction.response.edit_message(embed=self.view.embed(), view=self.view)


class GoalView(discord.ui.View):
    def __init__(self, user_id, service, make_song_embed, chart, song, sheet, cached, sections=(), fallback=False):
        super().__init__(timeout=900)
        self.user_id = user_id
        self.service = service
        self.make_song_embed = make_song_embed
        self.chart = chart
        self.song = song
        self.sheet = sheet
        self.cached = cached
        self.sections = sections
        self.fallback = fallback

    def embed(self):
        return goals_embed(self.make_song_embed, self.song, self.sheet, self.cached, self.sections, self.fallback)

    async def interaction_check(self, interaction):
        if self.user_id == interaction.user.id:
            return True
        await interaction.response.send_message('명령을 실행한 사용자만 사용할 수 있습니다.', ephemeral=True)
        return False

    @discord.ui.button(label='채보 변경', style=discord.ButtonStyle.secondary)
    async def change_chart(self, interaction, _button):
        await interaction.response.send_modal(ChartModal(self))

    @discord.ui.button(label='구간 편집', style=discord.ButtonStyle.primary)
    async def edit_sections(self, interaction, _button):
        await interaction.response.send_modal(SectionsModal(self))

    @discord.ui.button(label='저장', style=discord.ButtonStyle.success)
    async def save(self, interaction, _button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.service.save_target(self.user_id, self.chart.key, self.cached, self.sections)
        text = ('목표를 저장했습니다.' if self.sections else
                '채보 링크를 저장했습니다. /구간확인에서 시작 노트를 찾을 수 있습니다.')
        await interaction.followup.send(text, ephemeral=True)


def register_analysis(tree, get_service, get_index, autocomplete_song, make_song_embed):
    def select(song, difficulty):
        index = get_index()
        if index is None:
            raise ValueError('곡 검색 데이터를 준비 중입니다. 잠시 후 다시 시도해주세요.')
        record, sheet, fallback = index.select(song, difficulty)
        return chart_record(song, record, sheet), record, sheet, fallback

    async def reply_error(interaction, problem):
        if not isinstance(problem, (ValueError, RuntimeError)):
            log.exception('maimai analysis command failed')
        await interaction.followup.send(AnalysisService.describe(problem), ephemeral=True)

    async def load_chart(app, user, chart, record, sheet, link=None):
        previous = await app.db(app.store.target, user, chart.key)
        if link is None:
            link = previous.cached.url if previous else await app.db(app.notes.find_link, chart, record)
        return await app.db(app.notes.load, link, chart, record, sheet), previous

    @tree.command(name='목표설정', description='mai-notes 채보에 구간별 달성률 목표를 저장합니다.')
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.rename(song='곡', difficulty='난이도', chart_link='채보링크', goals='구간목표')
    @app_commands.choices(difficulty=CHOICES)
    @app_commands.describe(chart_link='생략하면 저장된 링크 또는 mai-notes의 곡·채보 목록에서 찾습니다.',
                           goals='예) 100개:-0.1, 나머지:-0.05 또는 1:-0.1, 101:-0.05. 입력하면 즉시 저장합니다.')
    async def set_target(interaction: discord.Interaction, song: str, chart_link: str | None = None,
                         difficulty: str = 'master', goals: str | None = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            chart, record, sheet, fallback = select(song, difficulty)
            app = await get_service()
            cached, previous = await load_chart(app, interaction.user.id, chart, record, sheet, chart_link)
            if goals is not None:
                sections = parse_sections(goals, cached.chart)
                await app.save_target(interaction.user.id, chart.key, cached, sections)
            else:
                sections = previous.sections if previous and previous.cached.url == cached.url else ()
            view = GoalView(interaction.user.id, app, make_song_embed, chart, record, sheet, cached, sections, fallback)
            await interaction.followup.send(content='목표를 저장했습니다.' if goals is not None else None,
                                            embed=view.embed(), view=view, ephemeral=True)
        except Exception as problem:
            await reply_error(interaction, problem)

    @tree.command(name='구간확인', description='영상의 여러 시각에서 simai 노트 번호를 찾습니다.')
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.rename(song='곡', difficulty='난이도', video_link_='영상링크',
                         timestamps='타임스탬프', first_note='첫노트시간')
    @app_commands.choices(difficulty=CHOICES)
    @app_commands.describe(first_note='자동 동기화 실패 시 첫 노트가 판정선에 도달한 영상 시각을 입력하세요.',
                           timestamps='초 또는 HH:MM:SS, 쉼표나 공백으로 구분')
    async def check_sections(interaction: discord.Interaction, song: str, video_link_: str, timestamps: str,
                             difficulty: str = 'master', first_note: str | None = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            chart, record, sheet, _ = select(song, difficulty)
            video, times = parse_video(video_link_), parse_times(timestamps)
            app = await get_service()
            cached, _ = await load_chart(app, interaction.user.id, chart, record, sheet)
            simai = cached.chart
            if first_note is not None:
                origin = parse_time(first_note) - simai.notes[0].time
            else:
                origin = await app.calibrate_for_interaction(video, chart.key, simai, times)
            lines = []
            for timestamp in times:
                notes = note_at(simai, timestamp - origin)
                if notes:
                    a, b = notes
                    label = f'{a}번' if a == b else f'{a}~{b}번'
                else:
                    label = '이후 노트 없음'
                lines.append(f'[{video_clock(timestamp)}]({video_link(video.id, timestamp)})'
                             f' · 첫 노트 기준 {timestamp - origin - simai.notes[0].time:.3f}초 · {label}')
            embed = discord.Embed(title=f'{chart.title} 구간 확인', description='\n'.join(lines), color=0xDA8EB2)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send('자동 동기화 시간이 초과되었습니다. 첫노트시간을 입력해주세요.', ephemeral=True)
        except Exception as problem:
            await reply_error(interaction, problem)

    async def submit(interaction, url, live, player, *, song=None, difficulty='master', closing=None,
                     include_guest=False):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            if get_index() is None:
                raise ValueError('곡 검색 데이터를 준비 중입니다. 잠시 후 다시 시도해주세요.')
            video = parse_video(url)
            chart = select(song, difficulty)[0] if song is not None else None
            app = await get_service()
            await app.submit(interaction.user.id, video, live, parse_time(closing) if closing is not None else None,
                             chart.key if chart else None, player, include_guest)
            text = ('라이브 분석을 등록했습니다. DM에서 대기 상태를 확인해주세요.' if live else
                    '다시보기 분석을 대기열에 등록했습니다. 완료되면 DM으로 결과를 보냅니다.')
            await interaction.followup.send(text, ephemeral=True)
        except Exception as problem:
            await reply_error(interaction, problem)

    @tree.command(name='영상분석', description='YouTube 다시보기를 분석하고 확인된 플레이를 DM으로 보냅니다.')
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.rename(video_url='영상링크', ends_at='종료시간', player='플레이어명', include_guest='게스트허용')
    @app_commands.describe(include_guest='첫 판에 이름 GUEST와 레이팅 0이 확인된 플레이를 포함합니다.')
    async def analyze_video(interaction: discord.Interaction, video_url: str, ends_at: str | None = None,
                            player: str | None = None, include_guest: bool = False):
        await submit(interaction, video_url, False, player, closing=ends_at, include_guest=include_guest)

    @tree.command(name='라이브분석', description='YouTube 라이브의 maimai 플레이를 추적합니다.')
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.rename(video_url='라이브링크', song='곡', difficulty='난이도', player='플레이어명')
    @app_commands.choices(difficulty=CHOICES)
    async def analyze_live(interaction: discord.Interaction, video_url: str, song: str | None = None,
                           difficulty: str = 'master', player: str | None = None):
        await submit(interaction, video_url, True, player, song=song, difficulty=difficulty)

    @tree.command(name='라이브분석-게스트토글', description='진행 중인 라이브의 다음 판부터 게스트 포함 여부를 바꿉니다.')
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.rename(video_url='라이브링크')
    @app_commands.describe(video_url='여러 방송을 분석하고 있다면 변경할 라이브 링크를 지정하세요.')
    async def toggle_guest(interaction: discord.Interaction, video_url: str | None = None):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            app = await get_service()
            enabled = await app.toggle_guest(interaction.user.id, parse_video(video_url).id if video_url else None)
            state = '포함합니다' if enabled else '제외합니다'
            await interaction.followup.send(f'다음 판부터 게스트 플레이를 {state}.', ephemeral=True)
        except Exception as problem:
            await reply_error(interaction, problem)

    for command in (set_target, check_sections, analyze_live):
        command.autocomplete('song')(autocomplete_song)
