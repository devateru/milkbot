import asyncio
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from dataclasses import dataclass, field
from urllib.parse import quote

import discord
from discord import app_commands
from dotenv import load_dotenv

from thumbnail_board import build_gameplaza_thumbnail_board
from youtube_live import (
    MachineStatus,
    YouTubeLiveError,
    get_gameplaza_machine_statuses,
)
from song_search import search_chart, choose_chart
from song_lookup import load_song_lookup
from note_scoring import calculate_note_scores, NOTE_WEIGHTS, RANKS
from song_filter import get_song_filters

load_dotenv(".env")

TOKEN = os.getenv("DISCORD_TOKEN")
BOT_DEVELOPER_ID = os.getenv("BOT_DEVELOPER_ID")
GAMEPLAZA_YOUTUBE_URL = os.getenv(
    "GAMEPLAZA_YOUTUBE_URL",
    "https://www.youtube.com/@GAMEPLAZA_C/streams",
)

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set in .env")
if not BOT_DEVELOPER_ID:
    raise RuntimeError("BOT_DEVELOPER_ID is not set in .env")

BOT_DEVELOPER_ID = int(BOT_DEVELOPER_ID)


intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
_synced = False
_update_dm_sent = False
_song_lookup = None
_song_lookup_task = None


async def refresh_song_lookup() -> None:
    global _song_lookup
    try:
        _song_lookup = await asyncio.to_thread(load_song_lookup)
    except Exception:
        logging.getLogger(__name__).exception("곡 검색 데이터를 불러오지 못했습니다.")


async def keep_song_lookup_updated() -> None:
    while not client.is_closed():
        await asyncio.sleep(3600 if _song_lookup is not None else 60)
        await refresh_song_lookup()


# ---------------------------------------------------------------------------
# 새 슬래시 명령어를 추가하는 곳
# ---------------------------------------------------------------------------
# 명령어는 모두 전역 Application Command로 등록하고,
# allowed_installs / allowed_contexts로 설치 방식과 실행 위치를 구분합니다.
#
# [1] 서버 설치(Guild Install) 전용
#
# @tree.command(name="서버명령어", description="서버에서만 사용하는 명령어입니다.")
# @app_commands.allowed_installs(guilds=True, users=False)
# @app_commands.allowed_contexts(
#     guilds=True,
#     dms=False,
#     private_channels=False,
# )
# async def guild_only_command(interaction: discord.Interaction) -> None:
#     await interaction.response.send_message("서버 전용 명령어")
#
#
# [2] 사용자 설치(User Install) 전용
# 사용자가 밀크봇을 자기 계정에 설치한 뒤, 봇이 들어가 있지 않은 서버나
# DM/GDM 등에서도 사용할 개인용 명령어에 사용합니다.
#
# @tree.command(name="개인명령어", description="개인 앱으로 사용하는 명령어입니다.")
# @app_commands.allowed_installs(guilds=False, users=True)
# @app_commands.allowed_contexts(
#     guilds=True,
#     dms=True,
#     private_channels=True,
# )
# async def user_only_command(interaction: discord.Interaction) -> None:
#     await interaction.response.send_message("사용자 설치 전용 명령어")
#
#
# [3] 서버 설치 + 사용자 설치 모두 허용
# 조회/계산처럼 서버 권한이 필요 없는 명령어에 적합합니다.
#
# @tree.command(name="공용명령어", description="어디서나 사용할 수 있는 명령어입니다.")
# @app_commands.allowed_installs(guilds=True, users=True)
# @app_commands.allowed_contexts(
#     guilds=True,
#     dms=True,
#     private_channels=True,
# )
# async def shared_command(interaction: discord.Interaction) -> None:
#     await interaction.response.send_message("공용 명령어")
#
#
# name은 Discord에 표시할 명령어 이름, description은 명령어 설명입니다.
# 사용자가 입력할 옵션은 함수 매개변수로 추가할 수 있습니다.
# 처리 시간이 길면 interaction.response.defer() 후
# interaction.followup.send(...)로 결과를 전송하세요.
#
# 명령어를 추가한 뒤 봇을 재시작하면 on_ready()의 tree.sync()가
# Discord의 전역 Application Command 목록을 동기화합니다.

# @tree.command(name="임베드테스트", description="곡 선택 임베드 테스트용")
# @app_commands.allowed_installs(guilds=True, users=True)
# @app_commands.allowed_contexts(
#     guilds=True,
#     dms=True,
#     private_channels=True,
# )
# async def foo(interaction: discord.Interaction) -> None:
#     song_title = "INTJINTPENTJENTPINFJENFJINFPENFPISTJISFJESTJESFJESTPISTPISFPESFP"
#     song_title = song_title if len(song_title) <= 100 else song_title[:100] + "..."
#     song_type = "\u2060".join([
#     "<:dx1:1546757257478410260>",
#     "<:dx2:1546757259025977384>",
#     "<:dx3:1546757260594778173>",
#     "<:dx4:1546757261999738921>",
# ])
#     song_artist = "3markets[]"
#     song_link = r"https://arcade-songs.zetaraku.dev/maimai/song/?id=INTJINTPENTJENTPINFJENFJINFPENFPISTJISFJESTJESFJESTPISTPISFPESFP"
#     song_cover = r"https://dp4p6x0xfi5o9.cloudfront.net/maimai/img/cover/f13031c7d0390a23079c0b0344a272caa9dbb965d74a4d7edddcc9ae9bfee985.png"
#     embed_color = 0x9e45e2
#     diff_1p = "MASTER"
#     const_1p = 13.3
#     diff_2p = False
#     const_2p = -1

#     if diff_2p:
#         chart_1p = f"[1P] {diff_1p} {const_1p}"
#         chart_2p = f"[2P] {diff_2p} {const_2p}"
#     else:
#         chart_1p = f"{diff_1p} {const_1p}"
#         chart_2p = ""
    
#     embed = discord.Embed(
#         title=f"{song_title} {song_type}",
#         description=song_artist,
#         url=song_link,
#         color=embed_color,
#     )
#     embed.set_thumbnail(url=song_cover)
#     embed.add_field(name=chart_1p, value=chart_2p)
#     view = discord.ui.View()

#     view.add_item(
#     discord.ui.Button(
#         label="자세히 보기 [WIP]",
#         style=discord.ButtonStyle.secondary,
#         custom_id="detail",
#         )
#     )

#     view.add_item(
#         discord.ui.Button(
#             label="다시 뽑기",
#             style=discord.ButtonStyle.secondary,
#             custom_id="reroll",
#         )
#     )

#     await interaction.response.send_message(embed=embed, view=view)

# 해당 코드는 분량 이슈로 gpt 랑 함께 작성

import asyncio
from urllib.parse import quote

import discord
from discord import app_commands

# 파일명에 맞게 수정
from song_filter import get_song_filters
from song_search import search_chart, choose_chart


# =========================================================
# 랜덤선곡 표시 설정
# =========================================================

COVER_BASE_URL = (
    "https://dp4p6x0xfi5o9.cloudfront.net/"
    "maimai/img/cover/"
)

SONG_PAGE_BASE_URL = (
    "https://arcade-songs.zetaraku.dev/"
    "maimai/song/?id="
)

WORD_JOINER = "\u2060"


# ---------------------------------------------------------
# 난이도 이름 / 임베드 색
# ---------------------------------------------------------

DIFFICULTY_INFO = {
    "basic": {
        "name": "BASIC",
        "color": 0x22BB5B,
    },
    "advanced": {
        "name": "ADVANCED",
        "color": 0xFB9C2D,
    },
    "expert": {
        "name": "EXPERT",
        "color": 0xF64861,
    },
    "master": {
        "name": "MASTER",
        "color": 0x9E45E2,
    },
    "remaster": {
        "name": "Re:MASTER",
        "color": 0xBA67F8,
    },
}


# ---------------------------------------------------------
# DX / STD 아이콘
# WORD JOINER를 사이에 넣어서 중간 줄바꿈 방지
# ---------------------------------------------------------

DX_EMOJIS = [
    "<:dx1:1546757257478410260>",
    "<:dx2:1546757259025977384>",
    "<:dx3:1546757260594778173>",
    "<:dx4:1546757261999738921>",
]

STD_EMOJIS = [
    "<:st1:1547465912507048027>",
    "<:st2:1547465914113466438>",
    "<:st3:1547465915581337630>",
    "<:st4:1547465916982231050>",
]

DX_ICON = WORD_JOINER.join(DX_EMOJIS)
STD_ICON = WORD_JOINER.join(STD_EMOJIS)


# ---------------------------------------------------------
# False Amber 전용 아이콘
# ---------------------------------------------------------

FALSE_AMBER_EMOJIS = [
    "<a:falseamber1:1547465948909404271>",
    "<a:falseamber2:1547465951341969428>",
    "<a:falseamber3:1547465954147958784>",
    # "<a:falseamber4:1547465956098580530>",
    # "<a:falseamber5:1547465957809586176>",
    # "<a:falseamber6:1547465959600820224>",
]

# 괄호 시작부터 끝까지 줄바꿈 방지
FALSE_AMBER_GROUP = WORD_JOINER.join(
    [
        "(",
        *FALSE_AMBER_EMOJIS,
        ")",
    ]
)


# =========================================================
# 제목 표시용
# =========================================================

def get_display_title(song_title: str) -> str:
    """
    False Amber로 시작하는 긴 제목은
    전용 표시 이름으로 교체.
    """

    if song_title.startswith("False Amber"):
        return (
            f"False Amber "
            f"{FALSE_AMBER_GROUP}"
        )

    return song_title


# =========================================================
# DX / STD 표시
# =========================================================

def get_type_icon(sheet_type: str) -> str:

    if sheet_type == "dx":
        return DX_ICON

    if sheet_type == "std":
        return STD_ICON

    # UTAGE 등 기타 타입
    return sheet_type.upper()


# =========================================================
# 채보 표시 문자열
# =========================================================

def format_chart(sheet: dict) -> str:

    difficulty_key = sheet["difficulty"]

    difficulty_name = (
        DIFFICULTY_INFO
        .get(
            difficulty_key,
            {
                "name": difficulty_key.upper()
            }
        )
        ["name"]
    )

    internal_level = sheet.get(
        "internalLevelValue"
    )

    if internal_level is None:
        return difficulty_name

    return (
        f"{difficulty_name} "
        f"{internal_level:.1f}"
    )


# =========================================================
# 임베드 생성
# =========================================================

def make_random_song_embed(
    chart: dict,
    p1_sheet: dict,
    p2_sheet: dict | None,
) -> discord.Embed:

    # -----------------------------------------------------
    # 원래 곡 제목
    # URL 생성에는 이 값을 그대로 사용
    # -----------------------------------------------------

    original_title = chart["title"]

    # -----------------------------------------------------
    # Discord 표시용 제목
    # False Amber만 특수 처리
    # -----------------------------------------------------

    display_title = get_display_title(
        original_title
    )

    # -----------------------------------------------------
    # DX / STD 아이콘
    # -----------------------------------------------------

    song_type = get_type_icon(
        p1_sheet["type"]
    )

    # -----------------------------------------------------
    # 아티스트
    # -----------------------------------------------------

    song_artist = chart["artist"]

    # -----------------------------------------------------
    # 곡 상세 링크
    # -----------------------------------------------------

    song_link = (
        SONG_PAGE_BASE_URL
        + quote(
            original_title,
            safe=""
        )
    )

    # -----------------------------------------------------
    # 재킷
    # base URL + JSON imageName
    # -----------------------------------------------------

    song_cover = (
        COVER_BASE_URL
        + chart["imageName"]
    )

    # -----------------------------------------------------
    # 임베드 색
    # 1P로 선택된 채보 난이도 기준
    # -----------------------------------------------------

    difficulty_key = (
        p1_sheet["difficulty"]
    )

    embed_color = (
        DIFFICULTY_INFO
        .get(
            difficulty_key,
            {
                # UTAGE 등 색이 지정되지 않은 타입 fallback
                "color": 0x9E45E2
            }
        )
        ["color"]
    )

    # -----------------------------------------------------
    # 채보 표시
    # -----------------------------------------------------

    if p2_sheet is not None:

        chart_1p = (
            f"[1P] "
            f"{format_chart(p1_sheet)}"
        )

        chart_2p = (
            f"[2P] "
            f"{format_chart(p2_sheet)}"
        )

    else:

        chart_1p = format_chart(
            p1_sheet
        )

        # Discord Embed field value는
        # 완전한 빈 문자열 대신 zero-width space 사용
        chart_2p = "\u200b"

    # -----------------------------------------------------
    # Embed
    # -----------------------------------------------------

    embed = discord.Embed(
        title=(
            f"{display_title} "
            f"{song_type}"
        ),
        description=song_artist,
        url=song_link,
        color=embed_color,
    )

    embed.set_thumbnail(
        url=song_cover
    )

    embed.add_field(
        name=chart_1p,
        value=chart_2p,
        inline=False,
    )

    return embed


# =========================================================
# 현재 선택 식별
# 다시 뽑기에서 직전 결과 반복 방지용
# =========================================================

def get_selection_key(
    chart: dict,
    p1_sheet: dict,
    p2_sheet: dict | None,
):

    p1_key = (
        p1_sheet.get("type"),
        p1_sheet.get("difficulty"),
        p1_sheet.get("internalLevelValue"),
    )

    if p2_sheet is not None:

        p2_key = (
            p2_sheet.get("type"),
            p2_sheet.get("difficulty"),
            p2_sheet.get("internalLevelValue"),
        )

    else:
        p2_key = None

    return (
        chart["title"],
        p1_key,
        p2_key,
    )


# =========================================================
# 결과 버튼 View
# =========================================================

def make_note_score_embed(chart: dict, sheet: dict, player: str = "") -> discord.Embed:
    stats = calculate_note_scores(sheet.get("noteCounts"))
    title = get_display_title(chart['title'])
    embed = discord.Embed(
        title=f"{title[:240]} · 노트 배점",
        description=(f"{player + ' · ' if player else ''}"
                     f"[{'DX' if sheet['type'] == 'dx' else 'ST' if sheet['type'] == 'std' else sheet['type'].upper()}] "
                     f"**{format_chart(sheet)}**\n{chart['artist']}"),
        color=DIFFICULTY_INFO.get(sheet['difficulty'], {'color': 0x9E45E2})['color'],
        url=SONG_PAGE_BASE_URL + quote(chart['title'], safe=""),
    )
    embed.set_thumbnail(url=COVER_BASE_URL + chart['imageName'])
    counts = stats['counts']
    embed.add_field(name=f"노트 수 · 총 {stats['total']:,}개",
                    value=' · '.join(f"**{k.upper()}** {counts[k]:,}" for k in NOTE_WEIGHTS), inline=False)
    lines = []
    for k, weight in NOTE_WEIGHTS.items():
        if k == 'break' and not counts[k]:
            lines.append('**BREAK** 0개 · 해당 없음')
            continue
        base = f"{weight} TAP"
        if k == 'break':
            base += f" + 보너스 {float(stats['break_bonus']):.5f}%"
        line = f"**{k.upper()}** {base} = **{float(stats['per_note'][k]):.5f}%**"
        if k == 'break':
            equivalent = stats['per_note'][k] / stats['per_note']['tap']
            line += f" (총 {float(equivalent):.2f} TAP 상당)"
        lines.append(line)
    embed.add_field(name=f"1개당 배점 · 만점 {float(stats['maximum']):.4f}%",
                    value='\n'.join(lines), inline=False)
    ranks = []
    for rank, threshold in RANKS.items():
        limit = stats['miss_limits'][rank]
        allowance = f"TAP **{limit}개 이하 MISS**" if limit is not None else '도달 불가'
        ranks.append(f"**{rank}** {float(threshold):g}% · {allowance}")
    embed.add_field(name="랭크별 TAP MISS 허용 수",
                    value='\n'.join(ranks) + '\n나머지 노트는 최고 판정, BREAK 보너스 만점 기준입니다.', inline=False)
    normal = []
    for k, losses in stats['losses'].items():
        if counts[k]:
            normal.append(f"{k.upper()}: GREAT −{float(losses['great']):.5f}% · "
                          f"GOOD −{float(losses['good']):.5f}% · MISS −{float(losses['miss']):.5f}%")
    embed.add_field(name="일반 노트 · 판정 1개당 감소율",
                    value=('PERFECT/CRITICAL PERFECT: 감점 없음\n'
                           'GREAT: 80% 획득 / 20% 감점 · GOOD: 50% 획득 / 50% 감점\n'
                           'MISS: 0% 획득 / 100% 감점\n' + '\n'.join(normal)), inline=False)
    if counts['break']:
        labels = {'critical_perfect': 'CRITICAL PERFECT', 'perfect_2550': 'PERFECT (2550)',
                  'perfect_2500': 'PERFECT (2500)', 'great_2000': 'GREAT (2000)',
                  'great_1500': 'GREAT (1500)', 'great_1250': 'GREAT (1250)', 'good': 'GOOD', 'miss': 'MISS'}
        embed.add_field(name="BREAK · 판정 1개당 감소율 (보너스 포함)",
                        value='\n'.join(f"{labels[k]}: −{float(loss):.5f}%"
                                        for k, loss in stats['break_losses'].items()), inline=False)
    embed.set_footer(text="현재 maimai DX 달성률 기준(ST 채보 포함) · %는 달성률 퍼센트포인트 · 표시값만 반올림")
    return embed


class SongResultView(discord.ui.View):
    def __init__(self, *, user_id: int, current_chart: dict,
                 current_p1_sheet: dict, current_p2_sheet: dict | None = None):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.current_chart = current_chart
        self.current_p1_sheet = current_p1_sheet
        self.current_p2_sheet = current_p2_sheet

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("명령어를 실행한 사람만 사용할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="노트 배점", style=discord.ButtonStyle.secondary)
    async def note_scores(self, interaction: discord.Interaction, button: discord.ui.Button):
        embeds, errors = [], []
        sheets = [("1P" if self.current_p2_sheet is not None else "", self.current_p1_sheet)]
        if self.current_p2_sheet is not None:
            sheets.append(("2P", self.current_p2_sheet))
        for player, sheet in sheets:
            try:
                embeds.append(make_note_score_embed(self.current_chart, sheet, player))
            except ValueError as error:
                errors.append(f"{player + ': ' if player else ''}{error}")
        await interaction.response.send_message(content='\n'.join(errors) or None,
                                                embeds=embeds, ephemeral=True)


class RandomSongResultView(SongResultView):

    def __init__(
        self,
        *,
        user_id: int,
        results: list[dict],
        current_chart: dict,
        current_p1_sheet: dict,
        current_p2_sheet: dict | None,
    ):

        super().__init__(user_id=user_id, current_chart=current_chart,
                         current_p1_sheet=current_p1_sheet, current_p2_sheet=current_p2_sheet)

        self.user_id = user_id

        # 최초 필터로 검색된 전체 후보군.
        # 다시 뽑을 때 search_chart()를 다시 실행하지 않고
        # 이 후보군 안에서만 선택함.
        self.results = results

        self.current_key = get_selection_key(
            current_chart,
            current_p1_sheet,
            current_p2_sheet,
        )


    # -----------------------------------------------------
    # 명령어 실행자만 버튼 사용 가능
    # -----------------------------------------------------

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:

        if interaction.user.id != self.user_id:

            await interaction.response.send_message(
                "랜덤선곡을 실행한 사람만 사용할 수 있습니다.",
                ephemeral=True,
            )

            return False

        return True


    # -----------------------------------------------------
    # 자세히 보기
    # -----------------------------------------------------

    @discord.ui.button(
        label="자세히 보기 [WIP]",
        style=discord.ButtonStyle.secondary,
    )
    async def detail(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        await interaction.response.send_message(
            "자세히 보기 기능은 아직 준비 중입니다.",
            ephemeral=True,
        )


    # -----------------------------------------------------
    # 다시 뽑기
    # -----------------------------------------------------

    @discord.ui.button(
        label="다시 뽑기",
        style=discord.ButtonStyle.secondary,
    )
    async def reroll(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        # 같은 필터 검색 결과에서 다시 선택
        chart, p1_sheet, p2_sheet = (
            choose_chart(
                self.results
            )
        )

        new_key = get_selection_key(
            chart,
            p1_sheet,
            p2_sheet,
        )

        # 가능하면 바로 직전에 나온 것과
        # 동일한 곡 + 동일 채보 조합은 피함.
        #
        # 후보가 사실상 하나뿐인 경우를 대비해
        # 무한루프 대신 최대 10회만 재시도.
        for _ in range(10):

            if new_key != self.current_key:
                break

            chart, p1_sheet, p2_sheet = (
                choose_chart(
                    self.results
                )
            )

            new_key = get_selection_key(
                chart,
                p1_sheet,
                p2_sheet,
            )

        self.current_key = new_key
        self.current_chart = chart
        self.current_p1_sheet = p1_sheet
        self.current_p2_sheet = p2_sheet

        embed = make_random_song_embed(
            chart,
            p1_sheet,
            p2_sheet,
        )

        # 새 메시지를 보내지 않고
        # 기존 곡 임베드를 그대로 수정
        await interaction.response.edit_message(
            embed=embed,
            view=self,
        )


# =========================================================
# /랜덤선곡
# =========================================================

@tree.command(
    name="랜덤선곡",
    description="밀크봇의 마이마이곡 랜덤픽"
)
@app_commands.allowed_installs(
    guilds=True,
    users=True
)
@app_commands.allowed_contexts(
    guilds=True,
    dms=True,
    private_channels=True,
)
async def randsong(
    interaction: discord.Interaction
) -> None:

    # =====================================================
    # 1. 필터 UI
    # =====================================================

    filters = await get_song_filters(
        interaction
    )

    # 필터 View timeout
    if filters is None:

        try:
            await interaction.edit_original_response(
                content="랜덤선곡 필터 입력 시간이 만료되었습니다.",
                embed=None,
                view=None,
            )

        except discord.NotFound:
            pass

        return


    # =====================================================
    # 2. 선택한 필터로 곡 검색
    # =====================================================
    #
    # search_chart() 내부에서 requests.get()을 사용하므로
    # Discord 봇 event loop를 막지 않도록 thread에서 실행.
    #
    # filters는 get_song_filters()가 반환한
    # search_chart(**filters)용 dict.
    # =====================================================

    try:

        results = await asyncio.to_thread(
            search_chart,
            **filters,
        )

    except Exception as e:

        print(
            f"[랜덤선곡] search_chart 오류: {e}"
        )

        await interaction.edit_original_response(
            content="곡 데이터를 검색하는 중 오류가 발생했습니다.",
            embed=None,
            view=None,
        )

        return


    # =====================================================
    # 3. 검색 결과 없음
    # =====================================================

    if not results:

        await interaction.edit_original_response(
            content="조건에 맞는 곡이 없습니다.",
            embed=None,
            view=None,
        )

        return


    # =====================================================
    # 4. 최초 랜덤 선곡
    # =====================================================

    chart, p1_sheet, p2_sheet = (
        choose_chart(
            results
        )
    )


    # =====================================================
    # 5. 곡 임베드 생성
    # =====================================================

    embed = make_random_song_embed(
        chart,
        p1_sheet,
        p2_sheet,
    )


    # =====================================================
    # 6. 결과 View
    #
    # 필터 결과 results 자체를 View에 저장.
    # 따라서 다시 뽑기는 무조건 같은 필터 후보군에서 실행.
    # =====================================================

    view = RandomSongResultView(
        user_id=interaction.user.id,
        results=results,
        current_chart=chart,
        current_p1_sheet=p1_sheet,
        current_p2_sheet=p2_sheet,
    )


    # =====================================================
    # 7. 필터 메시지를 곡 결과로 교체
    # =====================================================
    #
    # get_song_filters()가 이미 최초 interaction에
    # 응답했기 때문에 response.send_message()를 다시 쓰면 안 됨.
    # =====================================================

    await interaction.edit_original_response(
        content=None,
        embed=embed,
        view=view,
    )

# async def randsong(interaction: discord.Interaction) -> None:
#     song_title = "INTJINTPENTJENTPINFJENFJINFPENFPISTJISFJESTJESFJESTPISTPISFPESFP"
#     song_title = song_title if len(song_title) <= 100 else song_title[:100] + "..."
#     song_type = "\u2060".join([
#     "<:dx1:1546757257478410260>",
#     "<:dx2:1546757259025977384>",
#     "<:dx3:1546757260594778173>",
#     "<:dx4:1546757261999738921>",
# ])
#     song_artist = "3markets[]"
#     song_link = r"https://arcade-songs.zetaraku.dev/maimai/song/?id=INTJINTPENTJENTPINFJENFJINFPENFPISTJISFJESTJESFJESTPISTPISFPESFP"
#     song_cover = r"https://dp4p6x0xfi5o9.cloudfront.net/maimai/img/cover/f13031c7d0390a23079c0b0344a272caa9dbb965d74a4d7edddcc9ae9bfee985.png"
#     embed_color = 0x9e45e2
#     diff_1p = "MASTER"
#     const_1p = 13.3
#     diff_2p = False
#     const_2p = -1

#     if diff_2p:
#         chart_1p = f"[1P] {diff_1p} {const_1p}"
#         chart_2p = f"[2P] {diff_2p} {const_2p}"
#     else:
#         chart_1p = f"{diff_1p} {const_1p}"
#         chart_2p = ""
    
#     embed = discord.Embed(
#         title=f"{song_title} {song_type}",
#         description=song_artist,
#         url=song_link,
#         color=embed_color,
#     )
#     embed.set_thumbnail(url=song_cover)
#     embed.add_field(name=chart_1p, value=chart_2p)
#     view = discord.ui.View()

#     view.add_item(
#     discord.ui.Button(
#         label="자세히 보기 [WIP]",
#         style=discord.ButtonStyle.secondary,
#         custom_id="detail",
#         )
#     )

#     view.add_item(
#         discord.ui.Button(
#             label="다시 뽑기",
#             style=discord.ButtonStyle.secondary,
#             custom_id="reroll",
#         )
#     )

#     await interaction.response.send_message(embed=embed, view=view)



@tree.command(name="곡검색", description="곡명이나 대체어로 마이마이 곡을 검색합니다.")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.rename(song="곡", difficulty="난이도")
@app_commands.describe(song="곡명/대체어를 입력하고 DX 또는 ST 채보를 선택하세요.",
                       difficulty="기본 MASTER, Re:MASTER가 없으면 MASTER로 표시합니다.")
@app_commands.choices(difficulty=[
    app_commands.Choice(name="BASIC", value="basic"),
    app_commands.Choice(name="ADVANCED", value="advanced"),
    app_commands.Choice(name="EXPERT", value="expert"),
    app_commands.Choice(name="MASTER", value="master"),
    app_commands.Choice(name="Re:MASTER", value="remaster"),
])
async def find_song(interaction: discord.Interaction, song: str, difficulty: str = "master") -> None:
    index = _song_lookup
    if index is None:
        await interaction.response.send_message("곡 검색 데이터를 준비 중입니다. 잠시 후 다시 시도해주세요.", ephemeral=True)
        return
    try:
        chart, sheet, fallback = index.select(song, difficulty)
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return
    embed = make_random_song_embed(chart, sheet, None)
    if fallback:
        embed.set_footer(text="선택한 채보에 Re:MASTER가 없어 MASTER를 표시합니다.")
    view = SongResultView(user_id=interaction.user.id, current_chart=chart, current_p1_sheet=sheet)
    await interaction.response.send_message(embed=embed, view=view)


@find_song.autocomplete("song")
async def autocomplete_song(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    if _song_lookup is None:
        return []
    return [app_commands.Choice(name=option['name'], value=option['value'])
            for option in _song_lookup.autocomplete(current)]


@tree.command(name="겜플라이브", description="게임플라자 라이브 상태를 확인합니다.")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(
    guilds=True,
    dms=True,
    private_channels=True,
)
async def gameplaza_live(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)

    try:
        statuses = await asyncio.to_thread(get_gameplaza_machine_statuses)
    except YouTubeLiveError:
        await interaction.followup.send(
            "유튜브 라이브 상태를 확인하지 못했습니다. 잠시 후 다시 시도해주세요.\n"
            f"{GAMEPLAZA_YOUTUBE_URL}"
        )
        return

    checked_at = datetime.now(ZoneInfo("Asia/Seoul"))
    timestamp = checked_at.strftime("%Y-%m-%d %H:%M:%S")
    thumbnail_board = await asyncio.to_thread(
        build_gameplaza_thumbnail_board,
        statuses,
        timestamp,
    )
    file = discord.File(thumbnail_board, filename="gameplaza_live.jpg")
    embed = build_gameplaza_live_embed(statuses, checked_at)

    await interaction.followup.send(embed=embed, file=file)


def _format_status(status: MachineStatus) -> str:
    if not status.is_live or status.live_url is None:
        return "[---]"

    return f"[{status.number}번기]({status.live_url})"


def build_gameplaza_live_embed(
    statuses: list[MachineStatus],
    checked_at: datetime,
) -> discord.Embed:
    live_count = sum(1 for status in statuses if status.is_live)
    embed = discord.Embed(
        title="게임플라자 라이브 상태",
        description=(
            f"[@GAMEPLAZA_C/streams]({GAMEPLAZA_YOUTUBE_URL})\n"
            f"확인 시각: {checked_at.strftime('%Y-%m-%d %H:%M KST')}\n"
            f"라이브: {live_count}/8"
        ),
    )
    embed.add_field(
        name="마이마이 디럭스",
        value=" / ".join(_format_status(status) for status in statuses[:5]),
        inline=False,
    )
    embed.add_field(
        name="츄니즘",
        value=" / ".join(_format_status(status) for status in statuses[5:]),
        inline=False,
    )
    embed.set_image(url="attachment://gameplaza_live.jpg")
    return embed


def get_current_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "log", "-1", "--oneline"],
            text=True,
            timeout=3,
        ).strip()
    except Exception:
        return "커밋 정보를 확인하지 못했습니다."


async def notify_developer_update() -> None:
    try:
        user = client.get_user(BOT_DEVELOPER_ID) or await client.fetch_user(
            BOT_DEVELOPER_ID
        )
        commit = await asyncio.to_thread(get_current_commit)
        await user.send(f"밀크봇 업데이트 완료!\n`{commit}`")
    except Exception:
        # DM 차단, 잘못된 사용자 ID 등의 문제로 봇 자체가 종료되지는 않게 합니다.
        return


@client.event
async def on_ready() -> None:
    global _synced, _update_dm_sent, _song_lookup_task

    if _song_lookup_task is None or _song_lookup_task.done():
        await refresh_song_lookup()
        _song_lookup_task = asyncio.create_task(keep_song_lookup_updated())

    if not _synced:
        await tree.sync()
        for guild in client.guilds:
            await tree.sync(guild=guild)
        _synced = True

    if not _update_dm_sent:
        await notify_developer_update()
        _update_dm_sent = True

    print(f"Logged in as {client.user}")


client.run(TOKEN)
