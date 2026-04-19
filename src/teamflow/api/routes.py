from typing import Any, cast
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from teamflow.api.schemas import CreateTaskRequest, TaskResponse, TraceResponse
from teamflow.core.models import Finding, HandoffEntry, Task, TaskKind
from teamflow.infrastructure.logging import bind_task_id, clear_task_context
from teamflow.infrastructure.repository import TaskRepository

log = structlog.get_logger()

router = APIRouter(prefix="/tasks", tags=["tasks"])


def get_repository(request: Request) -> TaskRepository:
    return request.app.state.repository  # type: ignore[no-any-return]


def get_graph(request: Request) -> Any:
    return request.app.state.graph


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskResponse)
def create_task(
    payload: CreateTaskRequest,
    repo: TaskRepository = Depends(get_repository),
    graph: Any = Depends(get_graph),
) -> Task:
    task = Task(prompt=payload.prompt)
    bind_task_id(str(task.id))
    try:
        final_state = graph.invoke(
            {"prompt": payload.prompt, "task_id": str(task.id), "hops": 0},
            config={"configurable": {"thread_id": str(task.id)}},
        )
        task.kind = cast(TaskKind, final_state.get("kind", "unknown"))
        task.findings = [
            f if isinstance(f, Finding) else Finding.model_validate(f)
            for f in final_state.get("findings", []) or []
        ]
        task.report = final_state.get("report", "") or ""
        task.handoff_log = [
            HandoffEntry.model_validate(dict(entry))
            for entry in final_state.get("handoff_log", []) or []
        ]
        repo.add(task)
        log.info(
            "task_created",
            prompt_length=len(task.prompt),
            kind=task.kind,
            findings=len(task.findings),
            hops=final_state.get("hops", 0),
            handoffs=len(task.handoff_log),
        )
        return task
    finally:
        clear_task_context()


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: UUID,
    repo: TaskRepository = Depends(get_repository),
) -> Task:
    task = repo.get(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.get("/{task_id}/trace", response_model=TraceResponse)
def get_trace(
    task_id: UUID,
    repo: TaskRepository = Depends(get_repository),
) -> TraceResponse:
    task = repo.get(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return TraceResponse(task_id=task.id, handoff_log=task.handoff_log)
