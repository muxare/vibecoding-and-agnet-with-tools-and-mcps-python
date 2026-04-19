from typing import Protocol
from uuid import UUID

from teamflow.core.models import Task


class TaskRepository(Protocol):
    def add(self, task: Task) -> None: ...
    def get(self, task_id: UUID) -> Task | None: ...


class InMemoryTaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[UUID, Task] = {}

    def add(self, task: Task) -> None:
        self._tasks[task.id] = task

    def get(self, task_id: UUID) -> Task | None:
        return self._tasks.get(task_id)
