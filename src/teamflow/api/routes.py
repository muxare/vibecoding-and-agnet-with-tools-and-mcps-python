from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from teamflow.agents.triage import Triage
from teamflow.api.schemas import CreateTaskRequest, TaskResponse
from teamflow.core.models import Task
from teamflow.infrastructure.logging import bind_task_id, clear_task_context
from teamflow.infrastructure.repository import TaskRepository

log = structlog.get_logger()

router = APIRouter(prefix="/tasks", tags=["tasks"])


def get_repository(request: Request) -> TaskRepository:
    return request.app.state.repository  # type: ignore[no-any-return]


def get_triage(request: Request) -> Triage:
    return request.app.state.triage  # type: ignore[no-any-return]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskResponse)
def create_task(
    payload: CreateTaskRequest,
    repo: TaskRepository = Depends(get_repository),
    triage: Triage = Depends(get_triage),
) -> Task:
    task = Task(prompt=payload.prompt)
    bind_task_id(str(task.id))
    try:
        decision = triage(payload.prompt)
        task.kind = decision.kind
        repo.add(task)
        log.info("task_created", prompt_length=len(task.prompt), kind=task.kind)
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
