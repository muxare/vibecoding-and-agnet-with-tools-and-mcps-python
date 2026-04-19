import pytest
from fastapi.testclient import TestClient

from teamflow.agents.triage import TriageKind, TriageResult
from teamflow.api.app import create_app
from teamflow.infrastructure.repository import InMemoryTaskRepository


class StubTriage:
    def __init__(self, kind: TriageKind = "simple") -> None:
        self.kind: TriageKind = kind
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> TriageResult:
        self.calls.append(prompt)
        return TriageResult(kind=self.kind)


@pytest.fixture
def triage() -> StubTriage:
    return StubTriage()


@pytest.fixture
def client(triage: StubTriage) -> TestClient:
    app = create_app(repository=InMemoryTaskRepository(), triage=triage)
    return TestClient(app)
