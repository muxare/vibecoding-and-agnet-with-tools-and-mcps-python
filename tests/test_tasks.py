from fastapi.testclient import TestClient

from tests.conftest import StubResearch, StubSynth, StubTriage


def test_simple_task_routes_triage_research_synth(
    client: TestClient,
    triage: StubTriage,
    research: StubResearch,
    synth: StubSynth,
) -> None:
    triage.kind = "simple"
    create = client.post("/tasks", json={"prompt": "what is the current price of gold"})
    assert create.status_code == 201
    body = create.json()
    assert body["prompt"] == "what is the current price of gold"
    assert body["kind"] == "simple"
    assert research.calls == ["what is the current price of gold"]
    assert len(synth.calls) == 1
    assert body["report"] == "report-body"
    assert len(body["findings"]) == 1
    assert body["findings"][0]["source_url"] == "https://example.com/gold"

    targets = [entry["target"] for entry in body["handoff_log"]]
    assert targets == ["research", "synth", "END"]

    fetch = client.get(f"/tasks/{body['id']}")
    assert fetch.status_code == 200
    assert fetch.json() == body


def test_complex_task_skips_research(
    client: TestClient,
    triage: StubTriage,
    research: StubResearch,
    synth: StubSynth,
) -> None:
    triage.kind = "complex"
    response = client.post("/tasks", json={"prompt": "analyze the EV market in Europe"})
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "complex"
    assert body["findings"] == []
    assert research.calls == []
    assert len(synth.calls) == 1
    targets = [entry["target"] for entry in body["handoff_log"]]
    assert targets == ["synth", "END"]


def test_trace_endpoint_returns_handoff_log(
    client: TestClient, triage: StubTriage
) -> None:
    triage.kind = "simple"
    create = client.post("/tasks", json={"prompt": "what is the current price of gold"})
    task_id = create.json()["id"]

    trace = client.get(f"/tasks/{task_id}/trace")
    assert trace.status_code == 200
    body = trace.json()
    assert body["task_id"] == task_id
    assert [e["target"] for e in body["handoff_log"]] == ["research", "synth", "END"]
    assert [e["source"] for e in body["handoff_log"]] == ["triage", "research", "synth"]


def test_get_unknown_task_returns_404(client: TestClient) -> None:
    response = client.get("/tasks/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_trace_for_unknown_task_returns_404(client: TestClient) -> None:
    response = client.get("/tasks/00000000-0000-0000-0000-000000000000/trace")
    assert response.status_code == 404
