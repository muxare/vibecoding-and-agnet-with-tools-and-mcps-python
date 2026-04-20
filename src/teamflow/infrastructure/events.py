"""In-memory pub/sub for per-task graph events.

Phase 5 introduces background graph execution and an SSE endpoint that
streams progress to clients. This broker is the simplest possible
fan-out: each task has a list of buffered events plus a threading.Event
that flips whenever a new event lands. Subscribers loop, replaying the
buffer from their last index and waiting on the flag.

This means a subscriber that connects mid-run still sees the full history,
and one that connects after completion still gets every event. Good enough
for a single-process pedagogical build; swap for Redis/NATS in production.

Threading rather than asyncio because the runner executes the graph in a
background thread (FastAPI's request loop does not outlive the request,
so an asyncio.create_task background worker is unreliable under
TestClient). Subscribers bridge into asyncio via asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID


class _TaskChannel:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.flag = threading.Event()
        self.lock = threading.Lock()
        self.closed = False


class EventBroker:
    def __init__(self) -> None:
        self._channels: dict[UUID, _TaskChannel] = {}
        self._channels_lock = threading.Lock()

    def _channel(self, task_id: UUID) -> _TaskChannel:
        with self._channels_lock:
            if task_id not in self._channels:
                self._channels[task_id] = _TaskChannel()
            return self._channels[task_id]

    def create(self, task_id: UUID) -> None:
        self._channel(task_id)

    def publish(self, task_id: UUID, event: dict[str, Any]) -> None:
        channel = self._channel(task_id)
        with channel.lock:
            channel.events.append(event)
            channel.flag.set()

    def close(self, task_id: UUID) -> None:
        channel = self._channel(task_id)
        with channel.lock:
            channel.closed = True
            channel.flag.set()

    def snapshot(self, task_id: UUID) -> list[dict[str, Any]]:
        channel = self._channel(task_id)
        with channel.lock:
            return list(channel.events)

    async def subscribe(self, task_id: UUID) -> AsyncIterator[dict[str, Any]]:
        channel = self._channel(task_id)
        index = 0
        while True:
            with channel.lock:
                pending = channel.events[index:]
                index = len(channel.events)
                closed = channel.closed
            for event in pending:
                yield event
            if closed:
                return
            # Wait for the next publish on a worker thread so we don't block
            # the event loop. Time out so a stuck producer can't pin us forever.
            await asyncio.to_thread(channel.flag.wait, 1.0)
            with channel.lock:
                channel.flag.clear()
