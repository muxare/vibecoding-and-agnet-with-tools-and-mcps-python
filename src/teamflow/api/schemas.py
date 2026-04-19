from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from teamflow.core.models import Finding, TaskKind


class CreateTaskRequest(BaseModel):
    prompt: str


class TaskResponse(BaseModel):
    id: UUID
    prompt: str
    kind: TaskKind
    findings: list[Finding]
    created_at: datetime
