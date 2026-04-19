from pathlib import Path
from typing import Any, Protocol, cast

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import BaseModel, SecretStr

from teamflow.agents.tools import SearchProvider, make_tools
from teamflow.core.config import settings
from teamflow.core.models import Finding

log = structlog.get_logger()

DEFAULT_PROMPT_VERSION = "v1"
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts" / "research"


class ResearchAgent(Protocol):
    def __call__(self, prompt: str) -> list[Finding]: ...


class _Findings(BaseModel):
    findings: list[Finding]


def _load_prompt(version: str) -> str:
    raw = (PROMPTS_DIR / f"research.{version}.md").read_text(encoding="utf-8")
    if raw.startswith("---"):
        _, _, body = raw.split("---", 2)
        return body.strip()
    return raw.strip()


_EXTRACTOR_SYSTEM = (
    "Extract a structured list of findings from the assistant's research notes. "
    "Each finding must have a single concrete claim, a source_url that appears "
    "in the notes, and a confidence between 0 and 1. If the notes contain no "
    "supportable claims, return an empty list."
)


class LangGraphResearchAgent:
    """Explicit two-node tool-using agent.

    Mirrors the §Agents pattern from workflows-agents.mdx: an `llm_call` node
    that may emit tool calls, a `tool_node` that executes them, and a
    `should_continue` conditional edge that loops or terminates.
    """

    def __init__(
        self,
        *,
        provider: SearchProvider,
        model: str | None = None,
        prompt_version: str = DEFAULT_PROMPT_VERSION,
        max_iterations: int | None = None,
        llm: Any | None = None,
        extractor: Runnable[Any, Any] | None = None,
    ) -> None:
        self._provider = provider
        self._model = model or settings.default_model
        self._system_prompt = _load_prompt(prompt_version)
        self._max_iterations = max_iterations or settings.research_max_iterations
        self._tools: list[BaseTool] = make_tools(provider)
        self._tools_by_name: dict[str, BaseTool] = {t.name: t for t in self._tools}
        self._graph: Any = None
        self._llm_override: Any | None = llm
        self._extractor: Runnable[Any, Any] | None = extractor

    def _llm(self) -> Any:
        if self._llm_override is not None:
            return self._llm_override
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set — add it to .env or the environment."
            )
        return ChatAnthropic(
            model_name=self._model,
            api_key=SecretStr(settings.anthropic_api_key),
            timeout=None,
            stop=None,
        )

    def _build(self) -> Any:
        if self._graph is not None:
            return self._graph

        llm_with_tools = self._llm().bind_tools(self._tools)
        system = SystemMessage(content=self._system_prompt)

        def llm_call(state: MessagesState) -> dict[str, Any]:
            response = llm_with_tools.invoke([system, *state["messages"]])
            return {"messages": [response]}

        def tool_node(state: MessagesState) -> dict[str, Any]:
            last = state["messages"][-1]
            results: list[ToolMessage] = []
            for call in getattr(last, "tool_calls", []) or []:
                tool_obj = self._tools_by_name.get(call["name"])
                if tool_obj is None:
                    observation = f"Unknown tool: {call['name']}"
                else:
                    try:
                        observation = str(tool_obj.invoke(call["args"]))
                    except Exception as exc:  # tool errors flow back to the model
                        observation = f"Tool error from {call['name']}: {exc}"
                log.info(
                    "tool_call",
                    tool=call["name"],
                    args=call.get("args"),
                    result_chars=len(observation),
                )
                results.append(ToolMessage(content=observation, tool_call_id=call["id"]))
            return {"messages": results}

        def should_continue(state: MessagesState) -> str:
            last = state["messages"][-1]
            if getattr(last, "tool_calls", None):
                return "tool_node"
            return END

        builder = StateGraph(MessagesState)
        builder.add_node("llm_call", llm_call)
        builder.add_node("tool_node", tool_node)
        builder.add_edge(START, "llm_call")
        builder.add_conditional_edges(
            "llm_call", should_continue, {"tool_node": "tool_node", END: END}
        )
        builder.add_edge("tool_node", "llm_call")
        self._graph = builder.compile()
        return self._graph

    def _get_extractor(self) -> Runnable[Any, Any]:
        if self._extractor is None:
            self._extractor = self._llm().with_structured_output(_Findings)
        return self._extractor

    def __call__(self, prompt: str) -> list[Finding]:
        graph = self._build()
        # recursion_limit caps llm_call ↔ tool_node round trips.
        recursion_limit = max(4, self._max_iterations * 2 + 1)
        result = graph.invoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"recursion_limit": recursion_limit},
        )
        final = result["messages"][-1]
        notes = getattr(final, "content", "") or ""
        if not notes:
            return []
        extracted = self._get_extractor().invoke(
            [
                SystemMessage(content=_EXTRACTOR_SYSTEM),
                HumanMessage(content=str(notes)),
            ]
        )
        return cast(_Findings, extracted).findings
