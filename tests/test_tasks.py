from fastapi.testclient import TestClient

from tests.conftest import StubResearch, StubTriage


def test_create_simple_task_runs_research(
    client: TestClient, triage: StubTriage, research: StubResearch
) -> None:
    triage.kind = "simple"
    create = client.post("/tasks", json={"prompt": "what is the current price of gold"})
    assert create.status_code == 201
    body = create.json()
    assert body["prompt"] == "what is the current price of gold"
    assert body["kind"] == "simple"
    assert research.calls == ["what is the current price of gold"]
    assert len(body["findings"]) == 1
    assert body["findings"][0]["source_url"] == "https://example.com/gold"

    fetch = client.get(f"/tasks/{body['id']}")
    assert fetch.status_code == 200
    assert fetch.json() == body


def test_create_complex_task_skips_research(
    client: TestClient, triage: StubTriage, research: StubResearch
) -> None:
    triage.kind = "complex"
    response = client.post("/tasks", json={"prompt": "analyze the EV market in Europe"})
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "complex"
    assert body["findings"] == []
    assert research.calls == []


def test_get_unknown_task_returns_404(client: TestClient) -> None:
    response = client.get("/tasks/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
