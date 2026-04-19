from fastapi import FastAPI

from teamflow.agents.triage import AnthropicTriage, Triage
from teamflow.api.routes import router as tasks_router
from teamflow.infrastructure.logging import configure_logging
from teamflow.infrastructure.repository import InMemoryTaskRepository, TaskRepository


def create_app(
    repository: TaskRepository | None = None,
    triage: Triage | None = None,
) -> FastAPI:
    configure_logging()
    app = FastAPI(title="TeamFlow", version="0.1.0")
    app.state.repository = repository or InMemoryTaskRepository()
    app.state.triage = triage or AnthropicTriage()
    app.include_router(tasks_router)
    return app


app = create_app()
