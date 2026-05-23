from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import discord
from discord import app_commands

from messages import get_message


UTAGE_CHARTS_FILE = Path("utage_charts.json")
UTAGE_PAGE_SIZE = 20
UTAGE_EMBED_COLOR = 0xD78CFF
DISCORD_FIELD_VALUE_LIMIT = 1024
DISCORD_MESSAGE_LIMIT = 2000
DISCORD_BUTTON_LABEL_LIMIT = 80

PLAYER_CHOICES = [
    app_commands.Choice(name="1명", value=1),
    app_commands.Choice(name="2명", value=2),
    app_commands.Choice(name="3명", value=3),
    app_commands.Choice(name="4명", value=4),
]

CABINET_CHOICES = [
    app_commands.Choice(name="1대", value=1),
    app_commands.Choice(name="2대", value=2),
]


class UtageDataError(RuntimeError):
    pass


def _load_utage_charts() -> list[dict[str, Any]]:
    try:
        with UTAGE_CHARTS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as exc:
        raise UtageDataError(get_message("utage.error_data_missing")) from exc
    except json.JSONDecodeError as exc:
        raise UtageDataError(get_message("utage.error_data_invalid")) from exc

    charts = data.get("charts") if isinstance(data, dict) else None
    if not isinstance(charts, list):
        raise UtageDataError(get_message("utage.error_data_invalid"))

    return [chart for chart in charts if isinstance(chart, dict)]


def _optional_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if str(item).strip()).strip()
    return str(value).strip()


def _field_value(value: Any, *, limit: int = DISCORD_FIELD_VALUE_LIMIT) -> str:
    text = _optional_text(value) or "-"
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_count(value: Any, suffix: str) -> str:
    number = _int_value(value)
    if number is None:
        return "-"
    return f"{number}{suffix}"


def _format_difficulty(chart: dict[str, Any]) -> str:
    raw_value = _optional_text(chart.get("difficulty"))
    if not raw_value:
        return "-"

    match = re.search(r"\d{1,2}\+?\??", raw_value)
    if match:
        return match.group(0)

    return raw_value.strip("【】") or "-"


def _truncate_button_label(label: str) -> str:
    label = label.strip() or "-"
    if len(label) <= DISCORD_BUTTON_LABEL_LIMIT:
        return label
    return label[: DISCORD_BUTTON_LABEL_LIMIT - 3].rstrip() + "..."


def _button_label(chart: dict[str, Any]) -> str:
    title = _field_value(chart.get("title"), limit=60)
    difficulty = _format_difficulty(chart)
    if difficulty != "-":
        return _truncate_button_label(f"{difficulty} {title}")
    return _truncate_button_label(title)


def _matches_filter(
    chart: dict[str, Any],
    *,
    recommended_players: int,
    cabinet_count: int,
) -> bool:
    return (
        _int_value(chart.get("recommended_players")) == recommended_players
        and _int_value(chart.get("cabinet_count")) == cabinet_count
    )


def _filtered_charts(recommended_players: int, cabinet_count: int) -> list[dict[str, Any]]:
    return [
        chart
        for chart in _load_utage_charts()
        if _matches_filter(
            chart,
            recommended_players=recommended_players,
            cabinet_count=cabinet_count,
        )
    ]


def build_utage_embed(chart: dict[str, Any]) -> discord.Embed:
    title = _field_value(chart.get("title"), limit=256)
    url = _optional_text(chart.get("youtube_search_url"))
    embed = discord.Embed(
        title=title,
        url=url or None,
        color=UTAGE_EMBED_COLOR,
    )
    embed.add_field(name=get_message("utage.field_artist"), value=_field_value(chart.get("artist")), inline=False)
    embed.add_field(name=get_message("utage.field_difficulty"), value=_format_difficulty(chart), inline=True)
    embed.add_field(
        name=get_message("utage.field_cabinet_count"),
        value=_format_count(chart.get("cabinet_count"), "대"),
        inline=True,
    )
    embed.add_field(
        name=get_message("utage.field_recommended_players"),
        value=_format_count(chart.get("recommended_players"), "명"),
        inline=True,
    )
    embed.add_field(name=get_message("utage.field_version"), value=_field_value(chart.get("version")), inline=True)
    embed.add_field(name=get_message("utage.field_comment"), value=_field_value(chart.get("comment")), inline=False)
    embed.add_field(
        name=get_message("utage.field_translation"),
        value=_field_value(chart.get("translation")),
        inline=False,
    )

    cover_art_url = _optional_text(chart.get("cover_art_url"))
    if cover_art_url:
        embed.set_image(url=cover_art_url)

    return embed


def _list_content(
    *,
    chart_count: int,
    recommended_players: int,
    cabinet_count: int,
    page: int,
) -> str:
    total_pages = max(1, math.ceil(chart_count / UTAGE_PAGE_SIZE))
    lines = [
        get_message(
            "utage.list_header",
            recommended_players=recommended_players,
            cabinet_count=cabinet_count,
        ),
        get_message("utage.list_count", count=chart_count),
    ]
    if total_pages > 1:
        lines.append(get_message("utage.list_page", page=page + 1, total_pages=total_pages))
    return "\n".join(lines)


async def _send_owner_only_message(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        get_message("utage.error_owner_only"),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


def _message_chunks(text: str) -> list[str]:
    if len(text) <= DISCORD_MESSAGE_LIMIT:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > DISCORD_MESSAGE_LIMIT:
        split_at = remaining.rfind("\n", 0, DISCORD_MESSAGE_LIMIT)
        if split_at <= 0:
            split_at = DISCORD_MESSAGE_LIMIT
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def _send_ephemeral_text(interaction: discord.Interaction, text: str) -> None:
    chunks = _message_chunks(text)
    await interaction.response.send_message(
        chunks[0],
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )
    for chunk in chunks[1:]:
        await interaction.followup.send(
            chunk,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class UtageChartButton(discord.ui.Button):
    def __init__(self, chart_index: int, chart: dict[str, Any], row: int) -> None:
        super().__init__(
            label=_button_label(chart),
            style=discord.ButtonStyle.secondary,
            row=row,
        )
        self.chart_index = chart_index

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, UtageListView):
            await view.select_chart(interaction, self.chart_index)


class UtagePageButton(discord.ui.Button):
    def __init__(self, *, label: str, target_page: int) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.primary, row=4)
        self.target_page = target_page

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, UtageListView):
            await view.change_page(interaction, self.target_page)


class UtageInfoButton(discord.ui.Button):
    def __init__(self, *, label: str, value: str) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.value = value

    async def callback(self, interaction: discord.Interaction) -> None:
        await _send_ephemeral_text(interaction, self.value)


class UtageBackButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label=get_message("utage.back_button"),
            style=discord.ButtonStyle.primary,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if isinstance(view, UtageDetailView):
            await view.back_to_list(interaction)


class UtageListView(discord.ui.View):
    def __init__(
        self,
        *,
        owner_id: int,
        charts: list[dict[str, Any]],
        recommended_players: int,
        cabinet_count: int,
        page: int = 0,
    ) -> None:
        super().__init__(timeout=900)
        self.owner_id = owner_id
        self.charts = charts
        self.recommended_players = recommended_players
        self.cabinet_count = cabinet_count
        self.page = min(max(page, 0), self.total_pages - 1)
        self._add_page_items()

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(len(self.charts) / UTAGE_PAGE_SIZE))

    @property
    def content(self) -> str:
        return _list_content(
            chart_count=len(self.charts),
            recommended_players=self.recommended_players,
            cabinet_count=self.cabinet_count,
            page=self.page,
        )

    async def _is_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await _send_owner_only_message(interaction)
        return False

    def _add_page_items(self) -> None:
        start = self.page * UTAGE_PAGE_SIZE
        end = start + UTAGE_PAGE_SIZE
        for position, (chart_index, chart) in enumerate(
            enumerate(self.charts[start:end], start=start)
        ):
            self.add_item(
                UtageChartButton(
                    chart_index=chart_index,
                    chart=chart,
                    row=position // 5,
                )
            )

        if self.total_pages <= 1:
            return

        if self.page > 0:
            self.add_item(
                UtagePageButton(
                    label=get_message("utage.previous_button"),
                    target_page=self.page - 1,
                )
            )
        if self.page < self.total_pages - 1:
            self.add_item(
                UtagePageButton(
                    label=get_message("utage.next_button"),
                    target_page=self.page + 1,
                )
            )

    async def select_chart(self, interaction: discord.Interaction, chart_index: int) -> None:
        if not await self._is_owner(interaction):
            return

        chart = self.charts[chart_index]
        await interaction.response.edit_message(
            content=None,
            embed=build_utage_embed(chart),
            view=UtageDetailView(
                owner_id=self.owner_id,
                charts=self.charts,
                recommended_players=self.recommended_players,
                cabinet_count=self.cabinet_count,
                page=self.page,
                chart=chart,
            ),
        )

    async def change_page(self, interaction: discord.Interaction, target_page: int) -> None:
        if not await self._is_owner(interaction):
            return

        view = UtageListView(
            owner_id=self.owner_id,
            charts=self.charts,
            recommended_players=self.recommended_players,
            cabinet_count=self.cabinet_count,
            page=target_page,
        )
        await interaction.response.edit_message(content=view.content, embed=None, view=view)


class UtageDetailView(discord.ui.View):
    def __init__(
        self,
        *,
        owner_id: int,
        charts: list[dict[str, Any]],
        recommended_players: int,
        cabinet_count: int,
        page: int,
        chart: dict[str, Any],
    ) -> None:
        super().__init__(timeout=900)
        self.owner_id = owner_id
        self.charts = charts
        self.recommended_players = recommended_players
        self.cabinet_count = cabinet_count
        self.page = page
        self.chart = chart
        self._add_detail_items()

    def _add_detail_items(self) -> None:
        hint = _optional_text(self.chart.get("hint"))
        guide = _optional_text(self.chart.get("guide"))

        if hint:
            self.add_item(UtageInfoButton(label=get_message("utage.hint_button"), value=hint))
        if guide:
            self.add_item(UtageInfoButton(label=get_message("utage.guide_button"), value=guide))
        self.add_item(UtageBackButton())

    async def back_to_list(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await _send_owner_only_message(interaction)
            return

        view = UtageListView(
            owner_id=self.owner_id,
            charts=self.charts,
            recommended_players=self.recommended_players,
            cabinet_count=self.cabinet_count,
            page=self.page,
        )
        await interaction.response.edit_message(content=view.content, embed=None, view=view)


def register_utage_command(tree: app_commands.CommandTree) -> None:
    @tree.command(
        name="우타게",
        description=get_message("slash.utage_description"),
    )
    @app_commands.rename(
        recommended_players="권장인원수",
        cabinet_count="캐비넷_수",
    )
    @app_commands.describe(
        recommended_players=get_message("utage.option_recommended_players"),
        cabinet_count=get_message("utage.option_cabinet_count"),
    )
    @app_commands.choices(
        recommended_players=PLAYER_CHOICES,
        cabinet_count=CABINET_CHOICES,
    )
    async def utage_command(
        interaction: discord.Interaction,
        recommended_players: app_commands.Choice[int],
        cabinet_count: app_commands.Choice[int],
    ) -> None:
        try:
            charts = _filtered_charts(
                recommended_players=recommended_players.value,
                cabinet_count=cabinet_count.value,
            )
        except UtageDataError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if not charts:
            await interaction.response.send_message(
                get_message(
                    "utage.error_no_matches",
                    recommended_players=recommended_players.value,
                    cabinet_count=cabinet_count.value,
                ),
                ephemeral=True,
            )
            return

        view = UtageListView(
            owner_id=interaction.user.id,
            charts=charts,
            recommended_players=recommended_players.value,
            cabinet_count=cabinet_count.value,
        )
        await interaction.response.send_message(content=view.content, view=view)
