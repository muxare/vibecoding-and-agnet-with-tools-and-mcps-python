from fastapi.testclient import TestClient

from tests.conftest import StubResearch, StubSynth, StubTriage, wait_for_status


def test_simple_task_routes_triage_research_synth(
    client: TestClient,
    triage: StubTriage,
    research: StubResearch,
    synth: StubSynth,
) -> None:
    triage.kind = "simple"
    create = client.post("/tasks", json={"prompt": "what is the current price of gold"})
    assert create.status_code == 202
    accepted = create.json()
    assert accepted["status"] in {"pending", "running", "complete"}
    body = wait_for_status(client, accepted["id"])
    assert body["prompt"] == "what is the current price of gold"
    assert body["kind"] == "simple"
    assert research.calls == ["what is the current price of gold"]
    assert len(synth.calls) == 1
    assert body["report"] == "report-body"
    assert len(body["findings"]) == 1
    assert body["findings"][0]["source_url"] == "https://example.com/gold"

    targets = [entry["target"] for entry in body["handoff_log"]]
    assert targets == ["research", "synth", "END"]


def test_complex_task_with_subtasks_fans_out(
    client: TestClient,
    triage: StubTriage,
    research: StubResearch,
    synth: StubSynth,
) -> None:
    triage.kind = "complex"
    triage.subtasks = ["sub one", "sub two", "sub three"]
    response = client.post("/tasks", json={"prompt": "analyze the EV market in Europe"})
    assert response.status_code == 202
    body = wait_for_status(client, response.json()["id"])
    assert body["kind"] == "complex"
    assert body["subtasks"] == ["sub one", "sub two", "sub three"]
    # Each child runs the flat subgraph (depth=MAX_DEPTH so no further splits).
    # With kind=complex and no subtasks at depth>=MAX_DEPTH, child triage routes
    # to research → synth, so research is called once per child.
    assert sorted(research.calls) == sorted(["sub one", "sub two", "sub three"])
    assert len(body["child_reports"]) == 3
    assert body["report"] == "parent-report"
    assert len(synth.parent_calls) == 1
    parent_targets = [entry["target"] for entry in body["handoff_log"]]
    assert "child_worker" in parent_targets
    assert parent_targets[-1] == "END"


def test_complex_task_without_subtasks_falls_back_to_research(
    client: TestClient,
    triage: StubTriage,
    research: StubResearch,
    synth: StubSynth,
) -> None:
    triage.kind = "complex"
    triage.subtasks = []
    response = client.post("/tasks", json={"prompt": "analyze EV market"})
    body = wait_for_status(client, response.json()["id"])
    assert body["kind"] == "complex"
    assert research.calls == ["analyze EV market"]
    assert body["report"] == "report-body"
    targets = [entry["target"] for entry in body["handoff_log"]]
    assert targets == ["research", "synth", "END"]


def test_trace_endpoint_returns_handoff_log(
    client: TestClient, triage: StubTriage
) -> None:
    triage.kind = "simple"
    create = client.post("/tasks", json={"prompt": "what is the current price of gold"})
    task_id = create.json()["id"]
    wait_for_status(client, task_id)

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


def test_events_endpoint_streams_progress(
    client: TestClient, triage: StubTriage
) -> None:
    triage.kind = "simple"
    create = client.post("/tasks", json={"prompt": "p"})
    task_id = create.json()["id"]
    # Wait for completion first; broker buffers all events so subscribers
    # connecting late still get the full history.
    wait_for_status(client, task_id)

    with client.stream("GET", f"/tasks/{task_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        chunks: list[str] = []
        for line in response.iter_lines():
            if line.startswith("data: "):
                chunks.append(line[len("data: ") :])

    assert any('"status": "running"' in c for c in chunks)
    assert any('"status": "complete"' in c for c in chunks)
    assert any('"node": "triage_node"' in c for c in chunks)


def test_events_for_unknown_task_returns_404(client: TestClient) -> None:
    response = client.get("/tasks/00000000-0000-0000-0000-000000000000/events")
    assert response.status_code == 404
