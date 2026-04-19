from fastapi.testclient import TestClient

from tests.conftest import StubTriage


def test_create_and_get_task(client: TestClient, triage: StubTriage) -> None:
    triage.kind = "simple"
    create = client.post("/tasks", json={"prompt": "what is the current price of gold"})
    assert create.status_code == 201
    body = create.json()
    assert body["prompt"] == "what is the current price of gold"
    assert body["kind"] == "simple"
    assert triage.calls == ["what is the current price of gold"]
    task_id = body["id"]

    fetch = client.get(f"/tasks/{task_id}")
    assert fetch.status_code == 200
    assert fetch.json() == body


def test_create_task_classifies_complex(client: TestClient, triage: StubTriage) -> None:
    triage.kind = "complex"
    response = client.post("/tasks", json={"prompt": "analyze the EV market in Europe"})
    assert response.status_code == 201
    assert response.json()["kind"] == "complex"


def test_get_unknown_task_returns_404(client: TestClient) -> None:
    response = client.get("/tasks/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
