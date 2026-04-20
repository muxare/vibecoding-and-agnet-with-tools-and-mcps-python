from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

TaskKind = Literal["unknown", "simple", "complex"]
TaskStatus = Literal["pending", "running", "complete", "failed"]


class Finding(BaseModel):
    claim: str = Field(description="A single factual claim drawn from the sources.")
    source_url: str = Field(description="URL of the page that supports this claim.")
    confidence: float = Field(
        ge=0.0, le=1.0, description="0–1 estimate of how well sources support the claim."
    )


class HandoffEntry(BaseModel):
    source: str
    target: str
    reasoning: str
    hop: int


class Task(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    prompt: str
    status: TaskStatus = "pending"
    kind: TaskKind = "unknown"
    findings: list[Finding] = Field(default_factory=list)
    subtasks: list[str] = Field(default_factory=list)
    child_reports: list[str] = Field(default_factory=list)
    report: str = ""
    handoff_log: list[HandoffEntry] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
