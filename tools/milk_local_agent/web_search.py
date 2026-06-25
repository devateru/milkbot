from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .config import LocalAgentConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchResult:
    title: str
    snippet: str
    link: str


class SearchProvider:
    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        return []


class DisabledSearchProvider(SearchProvider):
    pass


class GoogleCustomSearchProvider(SearchProvider):
    def __init__(self, api_key: str, engine_id: str) -> None:
        self.api_key = api_key
        self.engine_id = engine_id

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params={
                        "key": self.api_key,
                        "cx": self.engine_id,
                        "q": query,
                        "num": min(limit, 5),
                    },
                ) as response:
                    if response.status != 200:
                        logger.warning("google custom search returned HTTP %s", response.status)
                        return []
                    data = await response.json(content_type=None)
        except Exception:
            logger.exception("google custom search failed")
            return []

        return _google_items_to_results(data.get("items", []), limit)


class SerpApiSearchProvider(SearchProvider):
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://serpapi.com/search.json",
                    params={"api_key": self.api_key, "q": query, "num": min(limit, 5)},
                ) as response:
                    if response.status != 200:
                        logger.warning("serpapi returned HTTP %s", response.status)
                        return []
                    data = await response.json(content_type=None)
        except Exception:
            logger.exception("serpapi search failed")
            return []

        organic = data.get("organic_results", [])
        return [
            SearchResult(
                title=str(item.get("title", "")),
                snippet=str(item.get("snippet", "")),
                link=str(item.get("link", "")),
            )
            for item in organic[:limit]
            if isinstance(item, dict)
        ]


class TavilySearchProvider(SearchProvider):
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "max_results": min(limit, 5),
                    },
                ) as response:
                    if response.status != 200:
                        logger.warning("tavily returned HTTP %s", response.status)
                        return []
                    data = await response.json(content_type=None)
        except Exception:
            logger.exception("tavily search failed")
            return []

        results = data.get("results", [])
        return [
            SearchResult(
                title=str(item.get("title", "")),
                snippet=str(item.get("content", "")),
                link=str(item.get("url", "")),
            )
            for item in results[:limit]
            if isinstance(item, dict)
        ]


def build_search_provider(config: LocalAgentConfig) -> SearchProvider:
    provider = config.web_search_provider.strip().casefold()

    if not config.web_search_enabled or provider == "disabled":
        return DisabledSearchProvider()

    if provider == "google_custom_search":
        if config.google_search_api_key and config.google_search_engine_id:
            return GoogleCustomSearchProvider(
                config.google_search_api_key,
                config.google_search_engine_id,
            )
        logger.warning("google custom search is enabled but API key or engine ID is missing")
        return DisabledSearchProvider()

    if provider == "serpapi":
        if config.serpapi_api_key:
            return SerpApiSearchProvider(config.serpapi_api_key)
        logger.warning("serpapi is enabled but API key is missing")
        return DisabledSearchProvider()

    if provider == "tavily":
        if config.tavily_api_key:
            return TavilySearchProvider(config.tavily_api_key)
        logger.warning("tavily is enabled but API key is missing")
        return DisabledSearchProvider()

    logger.warning("unknown web search provider: %s", config.web_search_provider)
    return DisabledSearchProvider()


def _google_items_to_results(items: Any, limit: int) -> list[SearchResult]:
    if not isinstance(items, list):
        return []

    return [
        SearchResult(
            title=str(item.get("title", "")),
            snippet=str(item.get("snippet", "")),
            link=str(item.get("link", "")),
        )
        for item in items[:limit]
        if isinstance(item, dict)
    ]


def format_search_results(results: list[SearchResult]) -> str:
    if not results:
        return ""

    lines = []
    for index, result in enumerate(results[:5], start=1):
        lines.append(
            f"{index}. {result.title}\n"
            f"   {result.snippet}\n"
            f"   {result.link}"
        )

    return "\n".join(lines)
