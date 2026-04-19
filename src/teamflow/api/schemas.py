from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from teamflow.core.models import Finding, HandoffEntry, TaskKind


class CreateTaskRequest(BaseModel):
    prompt: str


class TaskResponse(BaseModel):
    id: UUID
    prompt: str
    kind: TaskKind
    findings: list[Finding]
    report: str
    handoff_log: list[HandoffEntry]
    created_at: datetime


class TraceResponse(BaseModel):
    task_id: UUID
    handoff_log: list[HandoffEntry]
