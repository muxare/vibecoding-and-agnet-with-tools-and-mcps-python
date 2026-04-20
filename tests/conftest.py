import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from teamflow.agents.triage import TriageKind, TriageResult
from teamflow.api.app import create_app
from teamflow.core.models import Finding
from teamflow.infrastructure.repository import InMemoryTaskRepository


class StubTriage:
    def __init__(
        self,
        kind: TriageKind = "simple",
        subtasks: list[str] | None = None,
    ) -> None:
        self.kind: TriageKind = kind
        self.subtasks: list[str] = list(subtasks or [])
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> TriageResult:
        self.calls.append(prompt)
        return TriageResult(kind=self.kind, subtasks=list(self.subtasks))


class StubResearch:
    def __init__(self, findings: list[Finding] | None = None) -> None:
        self.findings: list[Finding] = findings or []
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> list[Finding]:
        self.calls.append(prompt)
        return list(self.findings)


class StubSynth:
    def __init__(
        self, report: str = "report-body", parent_report: str = "parent-report"
    ) -> None:
        self.report = report
        self.parent_report = parent_report
        self.calls: list[tuple[str, list[Finding]]] = []
        self.parent_calls: list[tuple[str, list[str]]] = []

    def __call__(self, prompt: str, findings: list[Finding]) -> str:
        self.calls.append((prompt, list(findings)))
        return self.report

    def synthesize_parent(self, prompt: str, child_reports: list[str]) -> str:
        self.parent_calls.append((prompt, list(child_reports)))
        return self.parent_report


@pytest.fixture
def triage() -> StubTriage:
    return StubTriage()


@pytest.fixture
def research() -> StubResearch:
    return StubResearch(
        findings=[
            Finding(
                claim="Gold spot price was $2,300/oz on 2025-01-01.",
                source_url="https://example.com/gold",
                confidence=0.8,
            )
        ]
    )


@pytest.fixture
def synth() -> StubSynth:
    return StubSynth()


@pytest.fixture
def client(triage: StubTriage, research: StubResearch, synth: StubSynth) -> TestClient:
    app = create_app(
        repository=InMemoryTaskRepository(),
        triage=triage,
        research=research,
        synth=synth,
    )
    return TestClient(app)


def wait_for_status(
    client: TestClient,
    task_id: str,
    status: str = "complete",
    *,
    timeout: float = 5.0,
    interval: float = 0.02,
) -> dict[str, Any]:
    """Poll GET /tasks/{id} until status is reached or timeout."""
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/tasks/{task_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last.get("status") == status:
            return last
        if last.get("status") == "failed" and status != "failed":
            raise AssertionError(
                f"task {task_id} failed while waiting for {status}: {last.get('error')}"
            )
        time.sleep(interval)
    raise AssertionError(
        f"timed out waiting for task {task_id} to reach status={status}; last={last}"
    )
