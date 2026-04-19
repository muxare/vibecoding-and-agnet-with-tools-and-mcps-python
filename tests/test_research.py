from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from teamflow.agents.research import LangGraphResearchAgent, _Findings
from teamflow.agents.tools import SearchHit
from teamflow.core.models import Finding


class StubProvider:
    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        return [SearchHit(title="Gold spot", url="https://example.com/gold", snippet="$2300/oz")]


class FakeChatLLM:
    """Plays back a scripted sequence of AIMessages.

    `bind_tools` is a no-op — the tool schema is irrelevant to playback.
    """

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self.calls: list[Any] = []

    def bind_tools(self, _tools: Any) -> "FakeChatLLM":
        return self

    def invoke(self, messages: Any, *_args: Any, **_kwargs: Any) -> AIMessage:
        self.calls.append(messages)
        if not self._responses:
            return AIMessage(content="done")
        return self._responses.pop(0)


def _stub_extractor(findings: list[Finding]) -> Any:
    return RunnableLambda(lambda _msgs: _Findings(findings=findings))


def test_agent_runs_tool_loop_and_extracts_findings() -> None:
    scripted = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "web_search",
                    "args": {"query": "gold price"},
                    "id": "call_1",
                    "type": "tool_call",
                }
            ],
        ),
        AIMessage(content="Gold was $2300/oz on 2025-01-01 (https://example.com/gold)."),
    ]
    fake_llm = FakeChatLLM(scripted)
    findings = [
        Finding(
            claim="Gold spot price was $2300/oz on 2025-01-01.",
            source_url="https://example.com/gold",
            confidence=0.85,
        )
    ]
    agent = LangGraphResearchAgent(
        provider=StubProvider(),
        llm=fake_llm,
        extractor=_stub_extractor(findings),
    )

    result = agent("price of gold")

    assert result == findings
    # Two LLM invocations: initial call, then post-tool follow-up.
    assert len(fake_llm.calls) == 2


def test_agent_short_circuits_when_no_tool_calls() -> None:
    fake_llm = FakeChatLLM([AIMessage(content="I cannot help.")])
    agent = LangGraphResearchAgent(
        provider=StubProvider(),
        llm=fake_llm,
        extractor=_stub_extractor([]),
    )
    assert agent("anything") == []
    assert len(fake_llm.calls) == 1
