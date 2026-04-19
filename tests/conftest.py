import pytest
from fastapi.testclient import TestClient

from teamflow.agents.triage import TriageKind, TriageResult
from teamflow.api.app import create_app
from teamflow.core.models import Finding
from teamflow.infrastructure.repository import InMemoryTaskRepository


class StubTriage:
    def __init__(self, kind: TriageKind = "simple") -> None:
        self.kind: TriageKind = kind
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> TriageResult:
        self.calls.append(prompt)
        return TriageResult(kind=self.kind)


class StubResearch:
    def __init__(self, findings: list[Finding] | None = None) -> None:
        self.findings: list[Finding] = findings or []
        self.calls: list[str] = []

    def __call__(self, prompt: str) -> list[Finding]:
        self.calls.append(prompt)
        return list(self.findings)


class StubSynth:
    def __init__(self, report: str = "report-body") -> None:
        self.report = report
        self.calls: list[tuple[str, list[Finding]]] = []

    def __call__(self, prompt: str, findings: list[Finding]) -> str:
        self.calls.append((prompt, list(findings)))
        return self.report


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
