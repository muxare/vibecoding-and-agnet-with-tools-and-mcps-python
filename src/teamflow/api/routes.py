import json
import threading
from typing import Any, cast
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from teamflow.api.schemas import CreateTaskRequest, TaskResponse, TraceResponse
from teamflow.core.models import Finding, HandoffEntry, Task, TaskKind
from teamflow.infrastructure.events import EventBroker
from teamflow.infrastructure.logging import bind_task_id, clear_task_context
from teamflow.infrastructure.repository import TaskRepository

log = structlog.get_logger()

router = APIRouter(prefix="/tasks", tags=["tasks"])


def get_repository(request: Request) -> TaskRepository:
    return request.app.state.repository  # type: ignore[no-any-return]


def get_graph(request: Request) -> Any:
    return request.app.state.graph


def get_broker(request: Request) -> EventBroker:
    return request.app.state.event_broker  # type: ignore[no-any-return]


def _run_task_sync(
    task: Task, graph: Any, repo: TaskRepository, broker: EventBroker
) -> None:
    """Background worker: stream the graph and publish per-node events.

    Runs in a worker thread so it survives the request that scheduled it.
    Uses the sync `graph.stream(...)` because we are off the event loop.
    """
    bind_task_id(str(task.id))
    task.status = "running"
    repo.add(task)
    broker.publish(task.id, {"type": "status", "status": "running"})
    try:
        thread_id = str(task.id)
        for chunk in graph.stream(
            {
                "prompt": task.prompt,
                "task_id": thread_id,
                "hops": 0,
                "depth": 0,
            },
            config={"configurable": {"thread_id": thread_id}},
        ):
            for node_name, update in chunk.items():
                event = {
                    "type": "node_update",
                    "node": node_name,
                    "decision": (update or {}).get("decision"),
                    "hop": (update or {}).get("hops"),
                    "handoffs": [
                        dict(h) for h in (update or {}).get("handoff_log", []) or []
                    ],
                }
                broker.publish(task.id, event)

        final_state = graph.get_state(
            {"configurable": {"thread_id": thread_id}}
        ).values
        task.kind = cast(TaskKind, final_state.get("kind", "unknown"))
        task.findings = [
            f if isinstance(f, Finding) else Finding.model_validate(f)
            for f in final_state.get("findings", []) or []
        ]
        task.subtasks = list(final_state.get("subtasks", []) or [])
        task.child_reports = list(final_state.get("child_reports", []) or [])
        task.report = final_state.get("report", "") or ""
        task.handoff_log = [
            HandoffEntry.model_validate(dict(entry))
            for entry in final_state.get("handoff_log", []) or []
        ]
        task.status = "complete"
        repo.add(task)
        broker.publish(
            task.id,
            {"type": "status", "status": "complete", "report_length": len(task.report)},
        )
        log.info(
            "task_complete",
            kind=task.kind,
            findings=len(task.findings),
            subtasks=len(task.subtasks),
            children=len(task.child_reports),
            handoffs=len(task.handoff_log),
        )
    except Exception as exc:
        task.status = "failed"
        task.error = f"{type(exc).__name__}: {exc}"
        repo.add(task)
        broker.publish(
            task.id, {"type": "status", "status": "failed", "error": task.error}
        )
        log.exception("task_failed", error=str(exc))
    finally:
        broker.close(task.id)
        clear_task_context()


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=TaskResponse)
def create_task(
    payload: CreateTaskRequest,
    repo: TaskRepository = Depends(get_repository),
    graph: Any = Depends(get_graph),
    broker: EventBroker = Depends(get_broker),
) -> Task:
    task = Task(prompt=payload.prompt, status="pending")
    repo.add(task)
    broker.create(task.id)
    log.info("task_accepted", task_id=str(task.id), prompt_length=len(task.prompt))
    threading.Thread(
        target=_run_task_sync,
        args=(task, graph, repo, broker),
        daemon=True,
        name=f"teamflow-task-{task.id}",
    ).start()
    return task


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


@router.get("/{task_id}/events")
async def stream_events(
    task_id: UUID,
    repo: TaskRepository = Depends(get_repository),
    broker: EventBroker = Depends(get_broker),
) -> StreamingResponse:
    if repo.get(task_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    async def gen() -> Any:
        async for event in broker.subscribe(task_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
