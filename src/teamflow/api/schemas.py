from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from teamflow.core.models import Finding, HandoffEntry, TaskKind, TaskStatus


class CreateTaskRequest(BaseModel):
    prompt: str


class TaskResponse(BaseModel):
    id: UUID
    prompt: str
    status: TaskStatus
    kind: TaskKind
    findings: list[Finding]
    subtasks: list[str]
    child_reports: list[str]
    report: str
    handoff_log: list[HandoffEntry]
    error: str | None
    created_at: datetime


class TraceResponse(BaseModel):
    task_id: UUID
    handoff_log: list[HandoffEntry]
