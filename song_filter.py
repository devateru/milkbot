from dataclasses import dataclass, field

import discord


# =========================================================
# 필터 기본값
# =========================================================

CATEGORY_OPTIONS = [
    ("팝/애니", "POPS＆アニメ"),
    ("보카로", "niconico＆ボーカロイド"),
    ("동방", "東方Project"),
    ("버라이어티", "ゲーム＆バラエティ"),
    ("마이마이", "maimai"),
    ("게키츄", "オンゲキ＆CHUNITHM"),
]

ALL_CATEGORIES = {
    value for _, value in CATEGORY_OPTIONS
}


TYPE_OPTIONS = [
    ("DX", "dx"),
    ("STD", "std"),
]

DEFAULT_TYPES = {
    "dx",
    "std",
}


DIFFICULTY_OPTIONS = [
    ("BAS", "basic"),
    ("ADV", "advanced"),
    ("EXP", "expert"),
    ("MAS", "master"),
    ("Re:MAS", "remaster"),
]

DEFAULT_DIFFICULTIES = {
    "master",
    "remaster",
}


# UTAGE는 일반 장르와 별도 카테고리로 처리
UTAGE_CATEGORY = "宴会場"


# =========================================================
# 버전
# 실제 data.json 값과 다르면 여기만 수정
# =========================================================

OLD_VERSIONS = [
    "maimai",
    "maimai PLUS",
    "GreeN",
    "GreeN PLUS",
    "ORANGE",
    "ORANGE PLUS",
    "PiNK",
    "PiNK PLUS",
    "MURASAKi",
    "MURASAKi PLUS",
    "MiLK",
    "MiLK PLUS",
    "FiNALE",
]

NEW_VERSIONS = [
    "maimaiでらっくす",
    "maimaiでらっくす PLUS",
    "Splash",
    "Splash PLUS",
    "UNiVERSE",
    "UNiVERSE PLUS",
    "FESTiVAL",
    "FESTiVAL PLUS",
    "BUDDiES",
    "BUDDiES PLUS",
    "PRiSM",
    "PRiSM PLUS",
    "CiRCLE",
    "CiRCLE PLUS",
]

ALL_VERSIONS = set(
    OLD_VERSIONS + NEW_VERSIONS
)


# NEW = 현재 레이팅 신곡
RATING_NEW_VERSIONS = {
    "CiRCLE",
    "CiRCLE PLUS",
}

# OLD = NEW 이외
RATING_OLD_VERSIONS = (
    ALL_VERSIONS - RATING_NEW_VERSIONS
)


# =========================================================
# 필터 상태
# =========================================================

@dataclass
class FilterState:

    # 카테고리 기본 전체 ON
    categories: set[str] = field(
        default_factory=lambda: ALL_CATEGORIES.copy()
    )

    # DX / STD 기본 전체 ON
    types: set[str] = field(
        default_factory=lambda: DEFAULT_TYPES.copy()
    )

    # 기본 MAS / Re:MAS ON
    difficulties: set[str] = field(
        default_factory=lambda: DEFAULT_DIFFICULTIES.copy()
    )

    # UTAGE 기본 OFF
    utage: bool = False

    # 버전 기본 전체 ON
    versions: set[str] = field(
        default_factory=lambda: ALL_VERSIONS.copy()
    )

    # 1P 난이도
    diff_min: float = 1.0
    diff_max: float = 15.0

    # 2P 난이도 종류
    p2_difficulties: set[str] = field(
        default_factory=set
    )

    # 2P 범위
    p2_diff_min: float = 1.0
    p2_diff_max: float = 15.0

    # 사용자가 2P 범위를 직접 건드렸는지
    # 기본값 1~15 때문에 자동으로 P2 검색이 켜지는 것을 방지
    p2_range_touched: bool = False


# =========================================================
# 난이도 입력 Modal
# =========================================================

class DifficultyModal(discord.ui.Modal):

    def __init__(
        self,
        filter_view,
        target: str,
        title: str,
        current: float,
    ):
        super().__init__(
            title=title
        )

        self.filter_view = filter_view
        self.target = target

        self.input = discord.ui.TextInput(
            label=title,
            placeholder="예: 13.7",
            default=f"{current:.1f}",
            required=True,
            max_length=4,
        )

        self.add_item(
            self.input
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        try:
            value = float(
                self.input.value
            )

        except ValueError:
            await interaction.response.send_message(
                "난이도는 숫자로 입력해주세요.",
                ephemeral=True,
            )
            return

        if not 1.0 <= value <= 15.0:
            await interaction.response.send_message(
                "난이도는 1.0 ~ 15.0 사이로 입력해주세요.",
                ephemeral=True,
            )
            return

        # 0.1 단위만 허용
        if abs(value * 10 - round(value * 10)) > 1e-9:
            await interaction.response.send_message(
                "난이도는 0.1 단위로 입력해주세요.",
                ephemeral=True,
            )
            return

        value = round(
            value,
            1
        )

        state = self.filter_view.state

        # 최소/최대 관계 검사
        if (
            self.target == "diff_min"
            and value > state.diff_max
        ):
            await interaction.response.send_message(
                "최소 난이도가 최대 난이도보다 높을 수 없습니다.",
                ephemeral=True,
            )
            return

        if (
            self.target == "diff_max"
            and value < state.diff_min
        ):
            await interaction.response.send_message(
                "최대 난이도가 최소 난이도보다 낮을 수 없습니다.",
                ephemeral=True,
            )
            return

        if (
            self.target == "p2_diff_min"
            and value > state.p2_diff_max
        ):
            await interaction.response.send_message(
                "2P 최소 난이도가 최대 난이도보다 높을 수 없습니다.",
                ephemeral=True,
            )
            return

        if (
            self.target == "p2_diff_max"
            and value < state.p2_diff_min
        ):
            await interaction.response.send_message(
                "2P 최대 난이도가 최소 난이도보다 낮을 수 없습니다.",
                ephemeral=True,
            )
            return

        setattr(
            state,
            self.target,
            value
        )

        # 2P 범위를 직접 수정했다면
        # difficulty 선택이 없어도 2P 필터 사용
        if self.target in {
            "p2_diff_min",
            "p2_diff_max",
        }:
            state.p2_range_touched = True

        self.filter_view.render()

        await interaction.response.edit_message(
            content=self.filter_view.page_text(),
            view=self.filter_view,
        )


# =========================================================
# 난이도 입력 버튼
# =========================================================

class DifficultyInputButton(discord.ui.Button):

    def __init__(
        self,
        *,
        target: str,
        label: str,
        value: float,
        row: int,
    ):
        super().__init__(
            label=f"{label}: {value:.1f}",
            style=discord.ButtonStyle.secondary,
            row=row,
        )

        self.target = target
        self.modal_title = label

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        view = self.view

        current = getattr(
            view.state,
            self.target
        )

        await interaction.response.send_modal(
            DifficultyModal(
                filter_view=view,
                target=self.target,
                title=self.modal_title,
                current=current,
            )
        )


# =========================================================
# 카테고리 / 채보 토글 버튼
# =========================================================

class FilterToggleButton(discord.ui.Button):

    def __init__(
        self,
        *,
        label: str,
        key: str,
        group: str,
        active: bool,
        row: int,
    ):
        super().__init__(
            label=label,
            style=(
                discord.ButtonStyle.success
                if active
                else discord.ButtonStyle.secondary
            ),
            row=row,
        )

        self.key = key
        self.group = group

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        view = self.view

        view.toggle_filter(
            self.group,
            self.key,
        )

        view.render()

        await interaction.response.edit_message(
            content=view.page_text(),
            view=view,
        )


# =========================================================
# 버전 그룹 버튼
# =========================================================

class VersionButton(discord.ui.Button):

    def __init__(
        self,
        *,
        label: str,
        group: set[str],
        selected: set[str],
        row: int = 0,
    ):
        active = (
            group <= selected
        )

        super().__init__(
            label=label,
            style=(
                discord.ButtonStyle.success
                if active
                else discord.ButtonStyle.secondary
            ),
            row=row,
        )

        self.version_group = group

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        view = self.view
        group = self.version_group

        # 그룹이 전부 켜져 있으면 → 전부 OFF
        if group <= view.state.versions:
            view.state.versions -= group

        # 하나라도 꺼져 있으면 → 그룹 전체 ON
        else:
            view.state.versions |= group

        view.render()

        await interaction.response.edit_message(
            content=view.page_text(),
            view=view,
        )


# =========================================================
# 버전 멀티선택
# =========================================================

class VersionSelect(discord.ui.Select):

    def __init__(
        self,
        *,
        versions: list[str],
        selected: set[str],
        placeholder: str,
        row: int,
    ):
        self.version_group = set(
            versions
        )

        options = [
            discord.SelectOption(
                label=version,
                value=version,
                default=version in selected,
            )
            for version in versions
        ]

        super().__init__(
            placeholder=placeholder,
            options=options,
            min_values=0,
            max_values=len(options),
            row=row,
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        view = self.view

        # 이 Select가 담당하는 버전만 다시 설정
        view.state.versions -= (
            self.version_group
        )

        view.state.versions.update(
            self.values
        )

        view.render()

        await interaction.response.edit_message(
            content=view.page_text(),
            view=view,
        )


# =========================================================
# 2P 난이도 멀티선택
# =========================================================

class P2DifficultySelect(discord.ui.Select):

    def __init__(
        self,
        selected: set[str]
    ):
        options = [
            discord.SelectOption(
                label=label,
                value=value,
                default=value in selected,
            )
            for label, value in DIFFICULTY_OPTIONS
        ]

        super().__init__(
            placeholder="2P 난이도 선택 · 기본 미사용",
            options=options,
            min_values=0,
            max_values=len(options),
            row=1,
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        view = self.view

        view.state.p2_difficulties = set(
            self.values
        )

        view.render()

        await interaction.response.edit_message(
            content=view.page_text(),
            view=view,
        )


# =========================================================
# 페이지 이동 버튼
# =========================================================

class PageButton(discord.ui.Button):

    def __init__(
        self,
        label: str,
        target_page: int,
    ):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            row=4,
        )

        self.target_page = target_page

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        view = self.view

        view.page = self.target_page
        view.render()

        await interaction.response.edit_message(
            content=view.page_text(),
            view=view,
        )


# =========================================================
# 초기화 버튼
# =========================================================

class ResetButton(discord.ui.Button):

    def __init__(self):
        super().__init__(
            label="초기화",
            style=discord.ButtonStyle.danger,
            row=4,
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        view = self.view

        view.state = FilterState()

        view.render()

        await interaction.response.edit_message(
            content=view.page_text(),
            view=view,
        )


# =========================================================
# 프리셋 버튼
# =========================================================

class PresetButton(discord.ui.Button):

    def __init__(self):
        super().__init__(
            label="프리셋 저장 [WIP]",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            row=4,
        )


# =========================================================
# 제출 버튼
# =========================================================

class SubmitButton(discord.ui.Button):

    def __init__(self):
        super().__init__(
            label="입력",
            style=discord.ButtonStyle.primary,
            row=4,
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):
        view = self.view

        await view.submit(
            interaction
        )


# =========================================================
# 메인 필터 View
# =========================================================

class SongFilterView(discord.ui.View):

    def __init__(
        self,
        user_id: int
    ):
        super().__init__(
            timeout=300
        )

        self.user_id = user_id

        # 0: 카테고리/채보
        # 1: 버전
        # 2: 난이도/2P
        self.page = 0

        self.state = FilterState()

        # 최종 반환값
        self.result = None

        self.render()


    # -----------------------------------------------------
    # 명령어 실행자만 사용 가능
    # -----------------------------------------------------

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:

        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "이 필터는 명령어를 실행한 사람만 변경할 수 있습니다.",
                ephemeral=True,
            )

            return False

        return True


    # -----------------------------------------------------
    # 페이지 안내
    # -----------------------------------------------------

    def page_text(self) -> str:

        if self.page == 0:
            return (
                "**곡 필터 · 1/3**\n"
                "카테고리 / 채보 유형\n"
                "초록색 = 활성화"
            )

        if self.page == 1:
            return (
                "**곡 필터 · 2/3**\n"
                "버전\n"
                "초록색 = 해당 그룹 전체 활성화"
            )

        p2_text = (
            ", ".join(
                value
                for value in self.state.p2_difficulties
            )
            if self.state.p2_difficulties
            else "미사용"
        )

        return (
            "**곡 필터 · 3/3**\n"
            f"난이도 상수: "
            f"{self.state.diff_min:.1f} ~ "
            f"{self.state.diff_max:.1f}\n"
            f"2P 난이도: {p2_text}\n"
            f"2P 상수: "
            f"{self.state.p2_diff_min:.1f} ~ "
            f"{self.state.p2_diff_max:.1f}"
        )


    # -----------------------------------------------------
    # UTAGE → 일반 기본 상태
    # -----------------------------------------------------

    def leave_utage_default(self):

        self.state.utage = False

        self.state.categories = (
            ALL_CATEGORIES.copy()
        )

        self.state.types = (
            DEFAULT_TYPES.copy()
        )

        self.state.difficulties = (
            DEFAULT_DIFFICULTIES.copy()
        )


    # -----------------------------------------------------
    # 카테고리 / 채보 토글 처리
    # -----------------------------------------------------

    def toggle_filter(
        self,
        group: str,
        key: str,
    ):

        # =================================================
        # 일반 카테고리
        # =================================================

        if group == "category":

            # UTAGE 상태에서 일반 카테고리를 누르면
            # UTAGE 해제
            if self.state.utage:

                self.state.utage = False

                self.state.categories = {
                    key
                }

                self.state.types = (
                    DEFAULT_TYPES.copy()
                )

                self.state.difficulties = (
                    DEFAULT_DIFFICULTIES.copy()
                )

                return

            if key in self.state.categories:
                self.state.categories.remove(
                    key
                )

            else:
                self.state.categories.add(
                    key
                )

            return


        # =================================================
        # UTAGE
        # =================================================

        if group == "utage":

            # UTAGE를 다시 누르면 기본 상태로 복귀
            if self.state.utage:
                self.leave_utage_default()
                return

            self.state.utage = True

            # 일반 카테고리 전부 OFF
            self.state.categories.clear()

            # 일반 채보 유형 전부 OFF
            self.state.types.clear()
            self.state.difficulties.clear()

            # UTAGE에서는 2P 설정 초기화
            self.state.p2_difficulties.clear()

            self.state.p2_diff_min = 1.0
            self.state.p2_diff_max = 15.0
            self.state.p2_range_touched = False

            return


        # =================================================
        # DX / STD
        # =================================================

        if group == "type":

            # UTAGE 상태에서 DX/STD를 누르면
            # 일반 모드로 복귀
            if self.state.utage:

                self.state.utage = False

                self.state.categories = (
                    ALL_CATEGORIES.copy()
                )

                self.state.types = {
                    key
                }

                self.state.difficulties = (
                    DEFAULT_DIFFICULTIES.copy()
                )

                return

            if key in self.state.types:

                # DX 또는 STD 하나만 남았는데
                # 그것을 끄려고 하면 반대쪽을 켬
                if len(self.state.types) == 1:

                    other = (
                        "std"
                        if key == "dx"
                        else "dx"
                    )

                    self.state.types = {
                        other
                    }

                else:
                    self.state.types.remove(
                        key
                    )

            else:
                self.state.types.add(
                    key
                )

            return


        # =================================================
        # BAS / ADV / EXP / MAS / Re:MAS
        # =================================================

        if group == "difficulty":

            # 일반 난이도를 누르면 UTAGE 해제
            if self.state.utage:

                self.state.utage = False

                self.state.categories = (
                    ALL_CATEGORIES.copy()
                )

                self.state.types = (
                    DEFAULT_TYPES.copy()
                )

                self.state.difficulties = {
                    key
                }

                return

            if key in self.state.difficulties:
                self.state.difficulties.remove(
                    key
                )

            else:
                self.state.difficulties.add(
                    key
                )


    # -----------------------------------------------------
    # 화면 다시 생성
    # -----------------------------------------------------

    def render(self):

        self.clear_items()

        if self.page == 0:
            self.render_basic()

        elif self.page == 1:
            self.render_version()

        else:
            self.render_difficulty()


    # -----------------------------------------------------
    # 공통 하단
    # -----------------------------------------------------

    def add_footer(
        self,
        *,
        previous=None,
        next_=None,
    ):

        if previous is not None:
            self.add_item(
                PageButton(
                    "◀ 이전",
                    previous,
                )
            )

        if next_ is not None:
            self.add_item(
                PageButton(
                    "다음 ▶",
                    next_,
                )
            )

        self.add_item(
            SubmitButton()
        )

        self.add_item(
            PresetButton()
        )

        self.add_item(
            ResetButton()
        )


    # -----------------------------------------------------
    # 1페이지
    # -----------------------------------------------------

    def render_basic(self):

        # 카테고리
        for i, (label, key) in enumerate(
            CATEGORY_OPTIONS
        ):

            self.add_item(
                FilterToggleButton(
                    label=label,
                    key=key,
                    group="category",
                    active=(
                        key in self.state.categories
                    ),
                    row=(
                        0
                        if i < 5
                        else 1
                    ),
                )
            )


        # DX
        self.add_item(
            FilterToggleButton(
                label="DX",
                key="dx",
                group="type",
                active=(
                    "dx" in self.state.types
                ),
                row=2,
            )
        )

        # STD
        self.add_item(
            FilterToggleButton(
                label="STD",
                key="std",
                group="type",
                active=(
                    "std" in self.state.types
                ),
                row=2,
            )
        )


        # BAS / ADV / EXP
        for label, key in DIFFICULTY_OPTIONS[:3]:

            self.add_item(
                FilterToggleButton(
                    label=label,
                    key=key,
                    group="difficulty",
                    active=(
                        key
                        in self.state.difficulties
                    ),
                    row=2,
                )
            )


        # MAS / Re:MAS
        for label, key in DIFFICULTY_OPTIONS[3:]:

            self.add_item(
                FilterToggleButton(
                    label=label,
                    key=key,
                    group="difficulty",
                    active=(
                        key
                        in self.state.difficulties
                    ),
                    row=3,
                )
            )


        # UTAGE
        self.add_item(
            FilterToggleButton(
                label="UTAGE",
                key="utage",
                group="utage",
                active=self.state.utage,
                row=3,
            )
        )

        self.add_footer(
            next_=1
        )


    # -----------------------------------------------------
    # 2페이지
    # -----------------------------------------------------

    def render_version(self):

        self.add_item(
            VersionButton(
                label="NEW",
                group=RATING_NEW_VERSIONS,
                selected=self.state.versions,
            )
        )

        self.add_item(
            VersionButton(
                label="OLD",
                group=RATING_OLD_VERSIONS,
                selected=self.state.versions,
            )
        )

        self.add_item(
            VersionButton(
                label="구버전 전체",
                group=set(OLD_VERSIONS),
                selected=self.state.versions,
            )
        )

        self.add_item(
            VersionButton(
                label="신버전 전체",
                group=set(NEW_VERSIONS),
                selected=self.state.versions,
            )
        )


        self.add_item(
            VersionSelect(
                versions=OLD_VERSIONS,
                selected=self.state.versions,
                placeholder="구버전 멀티 선택",
                row=1,
            )
        )

        self.add_item(
            VersionSelect(
                versions=NEW_VERSIONS,
                selected=self.state.versions,
                placeholder="신버전 멀티 선택",
                row=2,
            )
        )

        self.add_footer(
            previous=0,
            next_=2,
        )


    # -----------------------------------------------------
    # 3페이지
    # -----------------------------------------------------

    def render_difficulty(self):

        # 1P 최소
        self.add_item(
            DifficultyInputButton(
                target="diff_min",
                label="최소 난이도",
                value=self.state.diff_min,
                row=0,
            )
        )

        # 1P 최대
        self.add_item(
            DifficultyInputButton(
                target="diff_max",
                label="최대 난이도",
                value=self.state.diff_max,
                row=0,
            )
        )


        # 2P 난이도 종류
        self.add_item(
            P2DifficultySelect(
                self.state.p2_difficulties
            )
        )


        # 2P 최소
        self.add_item(
            DifficultyInputButton(
                target="p2_diff_min",
                label="2P 최소 난이도",
                value=self.state.p2_diff_min,
                row=2,
            )
        )

        # 2P 최대
        self.add_item(
            DifficultyInputButton(
                target="p2_diff_max",
                label="2P 최대 난이도",
                value=self.state.p2_diff_max,
                row=2,
            )
        )

        self.add_footer(
            previous=1
        )


    # -----------------------------------------------------
    # 최종 반환값 생성
    # -----------------------------------------------------

    def build_result(self) -> dict:

        state = self.state


        # =================================================
        # UTAGE
        # =================================================

        if state.utage:

            category = [
                UTAGE_CATEGORY
            ]

            # UTAGE는 category 자체로 거르므로
            # sheet type은 제한하지 않음
            type_ = None
            difficulty = None


        # =================================================
        # 일반 채보
        # =================================================

        else:

            category = list(
                state.categories
            )

            type_ = list(
                state.types
            )

            difficulty = list(
                state.difficulties
            )


        # =================================================
        # 2P
        # =================================================

        use_p2 = (
            bool(state.p2_difficulties)
            or state.p2_range_touched
        )

        if use_p2:

            p2_difficulty = (
                list(state.p2_difficulties)
                if state.p2_difficulties
                else None
            )

            p2_diff_min = (
                state.p2_diff_min
            )

            p2_diff_max = (
                state.p2_diff_max
            )

        else:

            p2_difficulty = None
            p2_diff_min = None
            p2_diff_max = None


        # search_chart(**result)로
        # 그대로 넣을 수 있는 구조
        return {
            "category": category,
            "version": list(
                state.versions
            ),
            "type_": type_,
            "difficulty": difficulty,
            "diff_min": state.diff_min,
            "diff_max": state.diff_max,
            "p2_difficulty": p2_difficulty,
            "p2_diff_min": p2_diff_min,
            "p2_diff_max": p2_diff_max,
            "region": "intl",
        }


    # -----------------------------------------------------
    # 제출
    # -----------------------------------------------------

    async def submit(
        self,
        interaction: discord.Interaction
    ):

        # 일반 모드 유효성 검사
        if not self.state.utage:

            if not self.state.categories:

                await interaction.response.send_message(
                    "카테고리를 하나 이상 선택해주세요.",
                    ephemeral=True,
                )

                return

            if not self.state.difficulties:

                await interaction.response.send_message(
                    "채보 난이도를 하나 이상 선택해주세요.",
                    ephemeral=True,
                )

                return


        if not self.state.versions:

            await interaction.response.send_message(
                "버전을 하나 이상 선택해주세요.",
                ephemeral=True,
            )

            return


        # 최종 검색 인자 저장
        self.result = self.build_result()

        # get_song_filters()의 view.wait() 종료
        self.stop()

        # 필터 UI 제거
        await interaction.response.edit_message(
            content="곡을 검색하고 있습니다.",
            view=None,
        )


# =========================================================
# bot.py에서 호출할 함수
# =========================================================

async def get_song_filters(
    interaction: discord.Interaction
) -> dict | None:
    """
    Discord 필터 UI를 표시하고,
    사용자가 [입력]을 누르면 search_chart()에
    바로 전달 가능한 dict를 반환.

    timeout 발생 시 None 반환.
    """

    view = SongFilterView(
        user_id=interaction.user.id
    )

    await interaction.response.send_message(
        content=view.page_text(),
        view=view,
    )

    # 사용자가 [입력]을 누르거나
    # View timeout까지 기다림
    timed_out = await view.wait()

    if timed_out:
        return None

    return view.result