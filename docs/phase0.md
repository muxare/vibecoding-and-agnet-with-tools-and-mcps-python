# Phase 0 — Foundation

**Concept introduced:** Project shape (no AI yet)

Before wiring up an LLM, we need somewhere for it to live. This phase gives us a bare-bones API and a mental model of the codebase so every later AI concept drops into a familiar slot. The shape of the app will not change after this — only what happens inside a handful of functions.

---

## What's done

### Project layout (src layout)

```
src/teamflow/
├── api/              # FastAPI app factory, routes, request/response schemas
│   ├── app.py
│   ├── routes.py
│   └── schemas.py
├── core/             # Domain models and settings
│   ├── config.py
│   └── models.py
├── agents/           # (empty — Phases 1, 2, 4)
├── orchestration/    # (empty — Phases 4, 5)
└── infrastructure/   # Repository protocol + logging config
    ├── logging.py
    └── repository.py
tests/
├── conftest.py
└── test_tasks.py
main.py               # uvicorn entrypoint
```

### Tooling

- `pyproject.toml` — hatchling build, src-layout package, deps pinned:
  - Runtime: `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `python-dotenv`, `structlog`, `langgraph`, `langchain`, `langchain-anthropic`
  - Dev (`[dependency-groups].dev`): `pytest`, `httpx`, `ruff`, `mypy`
- `ruff` configured (line-length 100, rule set E/F/I/B/UP/N, `fastapi.Depends` allowlisted for B008)
- `mypy` configured (`strict = true`, scoped to `src` and `tests`)
- `pytest` configured (`testpaths=["tests"]`, `pythonpath=["src"]`)
- `.env.example` with `ANTHROPIC_API_KEY`, `DEFAULT_MODEL=claude-sonnet-4-6`, `LOG_LEVEL`
- `.gitignore` extended for `.env` and tool caches

### Domain model

- `Task` (`src/teamflow/core/models.py`): `id: UUID`, `prompt: str`, `kind: Literal["unknown","simple","complex"] = "unknown"`, `created_at: datetime` (UTC).
- `Settings` (`src/teamflow/core/config.py`): reads `.env`, default model pinned to `claude-sonnet-4-6` (matching `workflows-agents.mdx`).

### Persistence

- `TaskRepository` Protocol + `InMemoryTaskRepository` in `src/teamflow/infrastructure/repository.py`. The API depends on the protocol, not the implementation — swapping in Postgres later is a one-line change.

### Logging

- `configure_logging()` sets up `structlog` with JSON output.
- `bind_task_id(task_id)` / `clear_task_context()` push the task id into the contextvars bundle so every log line inside a request carries it automatically.

### API

- `POST /tasks` — accepts `{ "prompt": "..." }`, stores a `Task`, returns `201` with `{id, prompt, kind, created_at}`.
- `GET /tasks/{task_id}` — returns the stored task, or `404` if unknown.
- App is built by a factory (`create_app(repository=...)`) so tests can inject an isolated repo.

### Tests

- `tests/test_tasks.py`:
  - `test_create_and_get_task` — POST then GET round-trips the same body.
  - `test_get_unknown_task_returns_404` — missing id returns 404.

---

## How to demo

### 1. Install deps

```bash
uv sync
```

### 2. Run the tests

```bash
uv run pytest
```

Expected: `2 passed`.

### 3. Run the lint + type checks (optional)

```bash
uv run ruff check src tests
uv run mypy
```

### 4. Start the server

```bash
uv run python main.py
```

The server listens on `http://127.0.0.1:8000`. FastAPI's auto-generated docs are at `http://127.0.0.1:8000/docs`.

### 5. Hit the endpoints

In another shell:

```bash
# Create a task
curl -s -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt":"what is the current price of gold"}'
```

Response (example):

```json
{
  "id": "ff2a5dda-1363-4400-acfe-b9585cecccb8",
  "prompt": "what is the current price of gold",
  "kind": "unknown",
  "created_at": "2026-04-19T12:25:19.384254Z"
}
```

```bash
# Fetch it back
curl -s http://127.0.0.1:8000/tasks/ff2a5dda-1363-4400-acfe-b9585cecccb8
```

Same body, plus a `404` if you make up an id:

```bash
curl -i http://127.0.0.1:8000/tasks/00000000-0000-0000-0000-000000000000
```

### 6. Observe the structured logs

Watch the server's stdout while hitting `POST /tasks` — you get one JSON line per request with a bound `task_id`, ready for a log aggregator:

```json
{"task_id": "ff2a5dda-...", "prompt_length": 33, "event": "task_created", "level": "info", "timestamp": "2026-04-19T12:25:19.384254Z"}
```

---

## Reflection

> Notice there is no intelligence here yet. Everything that follows is added at specific, named places in this skeleton. The shape of the app does not change — only what happens inside one function. Phase 1 replaces `kind = "unknown"` with the first LLM call.

---

## Not done (carried forward)

- GitHub Actions CI workflow file — tooling is configured but no `.github/workflows/ci.yml` committed yet.
