from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import logging
import math
import re
from urllib.parse import parse_qs, unquote, urlparse

from lxml import html
from lxml.html import HtmlElement

from .models import MaishiftBestEntry, MaishiftSnapshot, normalize_text


logger = logging.getLogger(__name__)

PRIVATE_MARKERS = (
    "No Record Found or Profile is Private",
    "Record does not exist or is private",
    "기록이 존재하지 않거나 비공개입니다",
)


class MaishiftParseError(ValueError):
    pass


class MaishiftInvalidOrPrivateError(MaishiftParseError):
    pass


@dataclass(frozen=True, slots=True)
class _EmbeddedTrack:
    chart_id: int
    title: str
    chart_type: str
    difficulty: str
    achievement: Decimal
    grade: str
    rating: int
    image_url: str | None


@dataclass(frozen=True, slots=True)
class _RenderedCard:
    title: str
    chart_type: str
    difficulty_label: str
    achievement: Decimal
    grade: str
    rating: int
    image_url: str | None


_JS_STRING = r'"(?:\\.|[^"\\])*"'


def _decode_js_string(value: str) -> str:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise MaishiftParseError("invalid string in embedded profile data") from exc


def _field_string(source: str, name: str) -> str | None:
    match = re.search(rf"(?:^|[,{{]){re.escape(name)}:({_JS_STRING})", source)
    return _decode_js_string(match.group(1)) if match else None


def _field_int(source: str, name: str) -> int | None:
    match = re.search(rf"(?:^|[,{{]){re.escape(name)}:(-?\d+)", source)
    return int(match.group(1)) if match else None


def _balanced_object(source: str, start: int) -> str:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise MaishiftParseError("unterminated object in embedded profile data")


def _embedded_script(document: HtmlElement) -> str:
    candidates = [node.text or "" for node in document.xpath("//script")]
    script = max(candidates, key=len, default="")
    if "profile:$R[" not in script or "trackId:" not in script:
        raise MaishiftParseError("structured profile data is missing")
    return script


def _extract_profile(script: str) -> tuple[str, int, int, int | None, datetime, str]:
    match = re.search(r"profile:\$R\[\d+\]=\{", script)
    if not match:
        raise MaishiftParseError("profile object is missing")
    obj = _balanced_object(script, match.end() - 1)
    player_name = _field_string(obj, "name")
    rating = _field_int(obj, "rating")
    play_match = re.search(r"playCount:\$R\[\d+\]=\{total:(\d+),current:(\d+)\}", obj)
    created_match = re.search(r'createdAt:\$R\[\d+\]=new Date\("([^"\r\n]+)"\)', obj)
    if player_name is None or rating is None or not play_match or not created_match:
        raise MaishiftParseError("required profile fields are missing")
    timestamp_raw = created_match.group(1)
    try:
        timestamp = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MaishiftParseError("invalid machine-readable update timestamp") from exc
    return (
        normalize_text(player_name),
        rating,
        int(play_match.group(1)),
        int(play_match.group(2)),
        timestamp,
        timestamp_raw,
    )


def _visible_text(node: HtmlElement) -> str:
    return normalize_text("".join(node.xpath(".//text()[not(ancestor::style)]")))


def _section_container(document: HtmlElement, heading: str) -> HtmlElement:
    matching = [
        node for node in document.xpath("//h2")
        if normalize_text("".join(node.itertext())) == heading
    ]
    if not matching:
        raise MaishiftParseError(f"{heading} heading is missing")
    for sibling in matching[0].getparent().itersiblings():
        if sibling.tag != "div":
            continue
        cards = [child for child in sibling if child.tag == "div" and child.get("tabindex") == "0"]
        if cards or not _visible_text(sibling):
            return sibling
        break
    raise MaishiftParseError(f"{heading} card grid is missing")


def _relay_image_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.path == "/api/image-relay":
        target = parse_qs(parsed.query).get("url", [None])[0]
        return unquote(target) if target else None
    return value


def _parse_card(card: HtmlElement) -> _RenderedCard:
    direct_divs = [child for child in card if child.tag == "div"]
    if len(direct_divs) < 4:
        raise MaishiftParseError("unexpected Best 50 card structure")
    visual, rating_area, title_area, result_area = direct_divs[-4:]
    type_images = visual.xpath('.//img[@alt="DX" or @alt="STANDARD"]')
    chart_type = type_images[0].get("alt") if type_images else None
    jacket_images = visual.xpath('.//img[not(@alt)]')
    rating_spans = rating_area.xpath(".//span")
    rating_text = _visible_text(rating_spans[0]) if rating_spans else ""
    rating_match = re.fullmatch(r"\d+", rating_text)
    difficulty_nodes = rating_area.xpath("./div/div/div")
    difficulty_label = _visible_text(difficulty_nodes[-1]) if difficulty_nodes else ""
    result_spans = result_area.xpath("./span")
    achievement_text = _visible_text(result_spans[0]).removesuffix("%") if result_spans else ""
    grade = _visible_text(result_spans[1]) if len(result_spans) > 1 else ""
    try:
        achievement = Decimal(achievement_text)
    except InvalidOperation as exc:
        raise MaishiftParseError("invalid achievement in Best 50 card") from exc
    title = _visible_text(title_area)
    if not title or not chart_type or not rating_match or not difficulty_label or not grade:
        raise MaishiftParseError("required Best 50 card fields are missing")
    return _RenderedCard(
        title=title,
        chart_type=chart_type,
        difficulty_label=difficulty_label,
        achievement=achievement,
        grade=grade,
        rating=int(rating_text),
        image_url=_relay_image_url(jacket_images[0].get("src") if jacket_images else None),
    )


def _extract_embedded_track(script: str, card: _RenderedCard) -> _EmbeddedTrack | None:
    needles = ["title:" + json.dumps(card.title, ensure_ascii=False)]
    if card.image_url:
        needles.append("jacketUrl:" + json.dumps(card.image_url, ensure_ascii=False))
    positions: set[int] = set()
    for needle in needles:
        position = 0
        while True:
            found = script.find(needle, position)
            if found < 0:
                break
            positions.add(found)
            position = found + len(needle)
    for found in sorted(positions):
        start = script.rfind("{trackId:", 0, found)
        if start < 0:
            continue
        try:
            obj = _balanced_object(script, start)
        except MaishiftParseError:
            continue
        title = _field_string(obj, "title")
        chart_type = _field_string(obj, "type")
        difficulty = _field_string(obj, "difficulty")
        chart_id = _field_int(obj, "trackId")
        achievement_match = re.search(r"record:\$R\[\d+\]=\{achievement:(\d+),", obj)
        rating_match = re.search(r"(?:^|,)rating:([0-9]+(?:\.[0-9]+)?)", obj)
        grade = _field_string(obj, "rank")
        image_url = _field_string(obj, "jacketUrl")
        if None in (title, chart_type, difficulty, chart_id, grade) or not achievement_match or not rating_match:
            continue
        achievement = Decimal(achievement_match.group(1)) / Decimal(10000)
        rendered_rating = math.floor(Decimal(rating_match.group(1)))
        if (
            normalize_text(title) == card.title
            and chart_type == card.chart_type
            and achievement == card.achievement
            and rendered_rating == card.rating
            and grade == card.grade
            and (not card.image_url or image_url == card.image_url)
        ):
            return _EmbeddedTrack(
                chart_id=chart_id,
                title=normalize_text(title),
                chart_type=chart_type,
                difficulty=difficulty,
                achievement=achievement,
                grade=grade,
                rating=rendered_rating,
                image_url=image_url,
            )
    return None


def _entry_from_card(script: str, card_node: HtmlElement) -> MaishiftBestEntry:
    card = _parse_card(card_node)
    embedded = _extract_embedded_track(script, card)
    if embedded is not None:
        stable_key = f"chart:{embedded.chart_id}"
        difficulty = embedded.difficulty
        chart_id: int | None = embedded.chart_id
    else:
        logger.warning("maishift chart id fallback used: %s", card.title)
        difficulty = card.difficulty_label
        chart_id = None
        stable_key = "fallback:" + "|".join(
            (normalize_text(card.title).casefold(), card.chart_type, normalize_text(difficulty).casefold())
        )
    return MaishiftBestEntry(
        stable_key=stable_key,
        chart_id=chart_id,
        title=card.title,
        chart_type=card.chart_type,
        difficulty=difficulty,
        difficulty_label=card.difficulty_label,
        achievement=card.achievement,
        grade=card.grade,
        rating=card.rating,
        image_url=card.image_url,
    )


def _parse_section(document: HtmlElement, script: str, heading: str) -> tuple[MaishiftBestEntry, ...]:
    container = _section_container(document, heading)
    card_nodes = [
        child for child in container
        if child.tag == "div" and child.get("tabindex") == "0"
    ]
    return tuple(_entry_from_card(script, card) for card in card_nodes)


def _extract_game_version(document: HtmlElement) -> str | None:
    for node in document.xpath("//span"):
        value = " ".join(_visible_text(node).split())
        if re.search(r"\bweek\s*#\d+\b", value, flags=re.IGNORECASE):
            parts = [part.strip() for part in re.split(r"[，·]", value) if part.strip()]
            version_parts = [part for part in parts if "week #" in part.lower() or not re.search(r"\d{1,2}/\d{1,2}/\d{4}", part)]
            return " · ".join(version_parts) if version_parts else value
    return None


def _extract_last_update_raw(document: HtmlElement, fallback: str) -> str:
    for node in document.xpath("//span"):
        value = " ".join(_visible_text(node).split())
        if re.search(r"\bweek\s*#\d+\b", value, flags=re.IGNORECASE):
            first = re.split(r"[，·]", value, maxsplit=1)[0].strip()
            return first or fallback
    return fallback


def parse_maishift_profile(
    html_text: str | bytes,
    *,
    profile_key: str,
    profile_name: str,
    profile_url: str,
    checked_at: datetime | None = None,
) -> MaishiftSnapshot:
    try:
        document = html.fromstring(html_text)
    except (ValueError, TypeError) as exc:
        raise MaishiftParseError("invalid HTML") from exc
    page_text = " ".join(" ".join(document.itertext()).split())
    if any(marker.casefold() in page_text.casefold() for marker in PRIVATE_MARKERS):
        raise MaishiftInvalidOrPrivateError("profile is missing or private")
    script = _embedded_script(document)
    player_name, total_rating, play_count, secondary, update_dt, update_raw = _extract_profile(script)
    new_best = _parse_section(document, script, "New Songs")
    old_best = _parse_section(document, script, "Old Songs")
    if len(new_best) > 15 or len(old_best) > 35:
        raise MaishiftParseError("Best 50 section exceeds its maximum size")
    calculated_rating = sum(entry.rating for entry in new_best + old_best)
    if calculated_rating != total_rating:
        raise MaishiftParseError(
            f"rating integrity mismatch: profile={total_rating}, entries={calculated_rating}"
        )
    return MaishiftSnapshot(
        profile_key=profile_key,
        profile_name=normalize_text(profile_name),
        profile_url=profile_url,
        player_name=player_name,
        total_rating=total_rating,
        play_count=play_count,
        secondary_play_count=secondary,
        last_update_raw=_extract_last_update_raw(document, update_raw),
        last_update_datetime=update_dt,
        game_version=_extract_game_version(document),
        new_best=new_best,
        old_best=old_best,
        checked_at=checked_at or datetime.now(timezone.utc),
    )
