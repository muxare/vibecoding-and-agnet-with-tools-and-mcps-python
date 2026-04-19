from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

TaskKind = Literal["unknown", "simple", "complex"]


class Task(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    prompt: str
    kind: TaskKind = "unknown"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
