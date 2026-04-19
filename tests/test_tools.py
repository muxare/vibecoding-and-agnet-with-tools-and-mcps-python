from teamflow.agents.tools import SearchHit, make_tools


class StubProvider:
    def __init__(self, hits: list[SearchHit]) -> None:
        self.hits = hits
        self.queries: list[str] = []

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        self.queries.append(query)
        return self.hits


def test_web_search_renders_numbered_results() -> None:
    provider = StubProvider(
        [
            SearchHit(title="A", url="https://a.test", snippet="alpha"),
            SearchHit(title="B", url="https://b.test", snippet="beta"),
        ]
    )
    web_search, _ = make_tools(provider)
    out = web_search.invoke({"query": "anything"})
    assert provider.queries == ["anything"]
    assert "1. A" in out and "https://a.test" in out
    assert "2. B" in out and "beta" in out


def test_web_search_empty() -> None:
    web_search, _ = make_tools(StubProvider([]))
    assert web_search.invoke({"query": "x"}) == "No results."


def test_tool_metadata_uses_docstrings() -> None:
    web_search, web_fetch = make_tools(StubProvider([]))
    assert web_search.name == "web_search"
    assert "Search the web" in (web_search.description or "")
    assert web_fetch.name == "web_fetch"
    assert "Fetch" in (web_fetch.description or "")
