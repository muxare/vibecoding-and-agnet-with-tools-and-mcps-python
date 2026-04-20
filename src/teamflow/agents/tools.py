from typing import Protocol

import httpx
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str


class SearchProvider(Protocol):
    def search(self, query: str, max_results: int = 5) -> list[SearchHit]: ...


class TavilySearchProvider:
    def __init__(self, api_key: str, *, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": self._api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            },
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            SearchHit(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
            )
            for r in data.get("results", [])
        ]


_FETCH_CHAR_LIMIT = 5000


def make_tools(provider: SearchProvider) -> list[BaseTool]:
    @tool
    def web_search(query: str) -> str:
        """Search the web for pages relevant to a query.

        Use this to discover sources for a research question. Returns a numbered
        list of results with title, URL, and a short snippet. After picking a
        promising result, call web_fetch on its URL to read the full page.
        """
        hits = provider.search(query)
        if not hits:
            return "No results."
        return "\n\n".join(
            f"{i + 1}. {h.title}\n   {h.url}\n   {h.snippet}" for i, h in enumerate(hits)
        )

    @tool(extras={"cache_control": {"type": "ephemeral"}})
    def web_fetch(url: str) -> str:
        """Fetch the readable text content of a single URL.

        Use this after web_search to read a promising page in full. Returns up
        to ~5000 characters of raw response text. Only call on URLs you have
        seen in a prior web_search result.
        """
        resp = httpx.get(
            url,
            timeout=30.0,
            follow_redirects=True,
            headers={"User-Agent": "TeamFlow-Research/0.1"},
        )
        resp.raise_for_status()
        return resp.text[:_FETCH_CHAR_LIMIT]

    return [web_search, web_fetch]
