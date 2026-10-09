"""Collect maimai titles and Namuwiki redirect aliases into a local JSON file.

Independent of milkbot. See docs/song-aliases.md for configuration and usage.
"""

import argparse
import json
import re
from pathlib import Path
import sys
import time
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup
import requests


BASE_URL = "https://namu.wiki"
LIST_DOCUMENT = "maimai 시리즈/수록곡"
ROOT = Path(__file__).resolve().parent


def document_link(href):
    parsed = urlsplit(urljoin(BASE_URL, href))
    if parsed.netloc != "namu.wiki" or not parsed.path.startswith("/w/"):
        return None
    return unquote(parsed.path[3:]), parsed.fragment


def parse_songs(html):
    """Use only the song-name column of tables headed 곡명 / 아티스트.

    Keep unlinked titles too; they simply have no wiki aliases to collect.
    Never replace the displayed title with the wiki document's name.
    """
    soup = BeautifulSoup(html, "html.parser")
    songs = {}
    for table in soup.select("table"):
        rows = [row for row in table.select("tr") if row.find_parent("table") is table]
        title_column = None
        for row in rows:
            cells = row.find_all(["td", "th"], recursive=False)
            labels = [cell.get_text("", strip=True) for cell in cells]
            if "곡명" in labels and "아티스트" in labels:
                title_column = labels.index("곡명")
                continue
            if title_column is None or len(cells) < 3 or title_column >= len(cells):
                continue
            if all(label in {"B", "A", "E", "Ex", "M", "R"} for label in labels):
                continue
            cell = cells[title_column]
            if int(cell.get("colspan", 1)) > 1:
                continue
            # Remove footnote marks without removing punctuation in song titles.
            clean = BeautifulSoup(str(cell), "html.parser")
            for note in clean.select('a[href^="#fn"], a[href^="#rfn"], sup'):
                note.decompose()
            displayed_title = clean.get_text("", strip=True)
            title = re.sub(r"\s*\((?:DX|STD)\)\s*$", "", displayed_title).rstrip()
            if not title:
                continue
            link = next((document_link(a["href"]) for a in clean.select("a[href]")
                         if document_link(a["href"])), None)
            song = {"title": title, "document": link[0] if link else None,
                    "fragment": link[1] if link else ""}
            # STD / DX versions share a title. Prefer a standalone article.
            old = songs.get(title)
            if old is None or (link and not link[1] and
                               (not old["document"] or old["fragment"] or displayed_title == title)):
                songs[title] = song
    if not songs:
        raise ValueError("수록곡 표를 찾지 못했습니다. 차단 페이지 또는 HTML 구조 변경을 확인하세요.")
    return [songs[title] for title in sorted(songs)]


def parse_backlinks(html, document):
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    flags = soup.select_one('select[name="flag"]')
    if not heading or "역링크" not in heading.get_text() or not flags or "redirect" not in flags.get_text():
        raise ValueError(f"역링크 페이지를 확인할 수 없습니다: {document}")
    aliases = set()
    entries = 0
    for item in soup.select("li"):
        text = item.get_text(" ", strip=True)
        if not text.endswith(("(link)", "(file)", "(include)", "(redirect)")):
            continue
        anchor = item.find("a", href=True)
        link = document_link(anchor["href"]) if anchor else None
        if link:
            entries += 1
            if text.endswith("(redirect)") and link[0] != document:
                aliases.add(link[0])
    if not entries and "해당 문서의 역링크가 존재하지 않습니다" not in soup.get_text():
        raise ValueError(f"역링크 목록 구조가 변경되었거나 불완전합니다: {document}")
    next_page = None
    for anchor in soup.select("a[href]"):
        if anchor.get_text(strip=True) != "다음":
            continue
        parsed = urlsplit(urljoin(BASE_URL, anchor["href"]))
        if (parsed.netloc == "namu.wiki" and
                unquote(parsed.path) == "/backlink/" + document):
            next_page = anchor["href"]
            break
    return sorted(aliases), next_page


class WikiClient:
    def __init__(self, delay):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "milkbot-song-alias-collector/1.0"
        self.delay = delay
        self.last_request = 0.0

    def get(self, path):
        url = urljoin(BASE_URL, path)
        if urlsplit(url).netloc != "namu.wiki":
            raise ValueError("나무위키 외부 URL은 수집하지 않습니다.")
        time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        response.encoding = "utf-8"
        return response.text

    def aliases(self, document):
        # A link in the song table may itself be a redirect (e.g. a Korean title).
        try:
            html = self.get("/w/" + quote(document, safe=""))
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code == 404:
                print(f"문서 없음(404): {document} — 대체어 없이 계속 수집합니다.", flush=True)
                return []
            raise
        soup = BeautifulSoup(html, "html.parser")
        heading = soup.select_one('h1 a[href]')
        link = document_link(heading["href"]) if heading else None
        if not link:
            raise ValueError(f"곡 문서 제목을 확인할 수 없습니다: {document}")
        canonical = link[0]
        aliases = {document, canonical}
        path = "/backlink/" + quote(canonical, safe="") + "?" + urlencode({"namespace": "문서", "flag": 8})
        visited = set()
        while path:
            absolute = urljoin(BASE_URL, path)
            if absolute in visited:
                raise ValueError(f"역링크 페이지 이동이 반복됩니다: {canonical}")
            visited.add(absolute)
            page_aliases, path = parse_backlinks(self.get(path), canonical)
            aliases.update(page_aliases)
        return sorted(aliases)


def write_json(path, data):
    """Replace only after writing a complete UTF-8 file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
    return content


def collect(client, cache_path, refresh=False, limit=None):
    songs = parse_songs(client.get("/w/" + quote(LIST_DOCUMENT, safe="")))
    print(f"수록곡 {len(songs)}개 발견", flush=True)
    if limit:
        songs = songs[:limit]
    cache = {}
    if cache_path.exists() and not refresh:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            raise ValueError("캐시 형식이 잘못되었습니다. --refresh로 다시 수집하세요.")
    results = []
    for index, song in enumerate(songs, 1):
        title, document = song["title"], song["document"]
        aliases = []
        # A section link can point to an album or franchise. Its redirects are
        # not aliases for the individual song, so do not import them.
        if document and not song["fragment"]:
            if document not in cache:
                cache[document] = client.aliases(document)
                write_json(cache_path, cache)
            aliases = cache[document]
        results.append({"title": title, "aliases": sorted(set(aliases) - {title})})
        print(f"[{index}/{len(songs)}] {title}: 대체어 {len(results[-1]['aliases'])}개", flush=True)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="마이마이 원제/리다이렉트 별칭을 로컬 JSON으로 저장")
    parser.add_argument("--output", type=Path, default=ROOT / "song_aliases.json")
    parser.add_argument("--cache", type=Path, default=ROOT / ".song_aliases_cache.json")
    parser.add_argument("--refresh", action="store_true", help="완료된 문서 캐시도 새로 수집")
    parser.add_argument("--delay", type=float, default=1.5, help="요청 간 최소 간격(초), 기본 1.5")
    parser.add_argument("--limit", type=int, help="시험용 수집 곡 수 (생략하면 전체 수집)")
    args = parser.parse_args(argv)
    if args.delay < 0 or (args.limit is not None and args.limit < 1):
        parser.error("--delay는 0 이상, --limit는 1 이상이어야 합니다.")
    try:
        results = collect(WikiClient(args.delay), args.cache, args.refresh, args.limit)
        write_json(args.output, results)
        print(f"로컬 저장 완료: {args.output.resolve()}")
    except (requests.RequestException, ValueError, OSError) as error:
        print(f"실패: {error}\n캐시를 이용해 재실행할 수 있습니다.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    main()
