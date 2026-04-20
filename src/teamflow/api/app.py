from typing import Any

from fastapi import FastAPI

from teamflow.agents.research import LangGraphResearchAgent, ResearchAgent
from teamflow.agents.synth import AnthropicSynth, Synth
from teamflow.agents.tools import TavilySearchProvider
from teamflow.agents.triage import AnthropicTriage, Triage
from teamflow.api.routes import router as tasks_router
from teamflow.core.config import settings
from teamflow.infrastructure.events import EventBroker
from teamflow.infrastructure.logging import configure_logging
from teamflow.infrastructure.repository import InMemoryTaskRepository, TaskRepository
from teamflow.orchestration.graph import build_graph


class _LazyResearch:
    """Defers TAVILY_API_KEY/Anthropic checks until the first request."""

    def __init__(self) -> None:
        self._agent: ResearchAgent | None = None

    def _build(self) -> ResearchAgent:
        if not settings.tavily_api_key:
            raise RuntimeError(
                "TAVILY_API_KEY is not set — add it to .env or pass a research agent explicitly."
            )
        provider = TavilySearchProvider(settings.tavily_api_key)
        return LangGraphResearchAgent(provider=provider)

    def __call__(self, prompt: str) -> list:  # type: ignore[type-arg]
        if self._agent is None:
            self._agent = self._build()
        return self._agent(prompt)


def create_app(
    repository: TaskRepository | None = None,
    triage: Triage | None = None,
    research: ResearchAgent | None = None,
    synth: Synth | None = None,
    graph: Any | None = None,
) -> FastAPI:
    configure_logging()
    app = FastAPI(title="TeamFlow", version="0.1.0")
    app.state.repository = repository or InMemoryTaskRepository()
    resolved_triage = triage or AnthropicTriage()
    resolved_research = research or _LazyResearch()
    resolved_synth = synth or AnthropicSynth()
    app.state.triage = resolved_triage
    app.state.research = resolved_research
    app.state.synth = resolved_synth
    app.state.graph = graph or build_graph(
        triage=resolved_triage,
        research=resolved_research,
        synth=resolved_synth,
    )
    app.state.event_broker = EventBroker()
    app.include_router(tasks_router)
    return app


app = create_app()
