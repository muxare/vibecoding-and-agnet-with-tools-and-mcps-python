# Phase 1 — First Agent

**Concept introduced:** Prompt engineering — basics

The simplest useful thing an LLM can do in this system is classify a task. No
tools, no handoffs, no orchestration — just prompt in, structured answer out.
This phase replaces the placeholder `kind = "unknown"` from Phase 0 with the
first real LLM call, using the `with_structured_output` pattern from
`workflows-agents.mdx` §LLMs and augmentations.

---

## What's done

### Triage agent

- `src/teamflow/agents/triage.py`:
  - `TriageResult` Pydantic model — single field `kind: Literal["simple", "complex"]`.
  - `Triage` protocol — a callable `(prompt: str) -> TriageResult`. Lets the
    API depend on behavior, not a concrete class (same pattern as
    `TaskRepository`).
  - `AnthropicTriage` — default implementation. Wraps `ChatAnthropic` with
    `.with_structured_output(TriageResult)`. The Anthropic client is built
    lazily on first call so importing the app without `ANTHROPIC_API_KEY` set
    does not explode.
  - `load_prompt(version)` — reads a prompt body from `prompts/triage/triage.<version>.md`.

### Prompt versions (kept as teaching artifacts)

All live under `prompts/triage/` and are never deleted — each version shows one
more prompt-engineering lever applied on top of the last:

- `triage.v1.md` — one sentence: *"Is this simple or complex?"*. Messy baseline.
- `triage.v2.md` — adds role framing: *"You classify research tasks."*
- `triage.v3.md` — adds definitions of simple vs complex, an explicit JSON
  schema, and a "do not return prose" negative instruction.
- `triage.v4.md` — adds two few-shot examples (gold price → simple, EV market
  analysis → complex). This is the default version the API uses.

### Wiring into the API

- `src/teamflow/api/app.py` — `create_app(repository=..., triage=...)` now
  accepts an injectable `Triage` alongside the repository. Defaults to
  `AnthropicTriage()`.
- `src/teamflow/api/routes.py` — `POST /tasks` invokes `triage(prompt)` before
  storing the task, and writes `decision.kind` onto `task.kind`. The
  `task_created` log line now carries the classification.
- No LangGraph yet. The call is a plain Python function invoked from the
  request handler — the shape of the app is unchanged from Phase 0.

### Tests

- `tests/conftest.py` — `StubTriage` fixture implements the `Triage` protocol
  with a canned `kind` and a `.calls` list. The `client` fixture wires it into
  `create_app` so no test hits the real Anthropic API.
- `tests/test_tasks.py`:
  - `test_create_and_get_task` — asserts `kind == "simple"` and that triage was
    called with the submitted prompt.
  - `test_create_task_classifies_complex` — flips the stub to "complex" and
    asserts the stored task reflects it.
  - `test_get_unknown_task_returns_404` — unchanged from Phase 0.
- `tests/test_triage.py`:
  - Parametrised check that all four prompt files load non-empty.
  - Snapshot-ish check that `v4` actually contains the few-shot examples.

---

## How to demo

### 1. Install deps and run the tests

```bash
uv sync
uv run pytest
```

Expected: `8 passed`. Tests run offline — the stub triage has no Anthropic
dependency.

### 2. Run lint + type checks (optional)

```bash
uv run ruff check src tests
uv run mypy
```

### 3. Start the server (requires `ANTHROPIC_API_KEY`)

```bash
cp .env.example .env   # then edit .env and set ANTHROPIC_API_KEY=sk-ant-...
uv run python main.py
```

### 4. Hit the endpoint with a simple task

```bash
curl -s -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt":"what is the current price of gold"}'
```

Expected response:

```json
{
  "id": "…",
  "prompt": "what is the current price of gold",
  "kind": "simple",
  "created_at": "…"
}
```

### 5. Hit it with a complex task

```bash
curl -s -X POST http://127.0.0.1:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt":"analyze the EV market in Europe, including key players, regulation, and five-year outlook"}'
```

Expected: `"kind": "complex"`.

### 6. Show the v1 → v4 prompt evolution

Open `prompts/triage/triage.v1.md` through `triage.v4.md` side by side. To see
the difference in practice, temporarily change the default in
`src/teamflow/agents/triage.py`:

```python
DEFAULT_PROMPT_VERSION = "v1"   # then "v2", "v3", "v4"
```

Restart the server and submit a borderline prompt such as
*"compare the iPhone 15 and iPhone 16 cameras"*. The `kind` classification gets
more stable as the version climbs — same model, same input, cost of the change
was a few lines of Markdown.

### 7. Observe the structured log

The `task_created` line now carries the classification:

```json
{"task_id": "…", "prompt_length": 72, "kind": "complex", "event": "task_created", "level": "info", "timestamp": "…"}
```

---

## Reflection

> Every prompt version cost us nothing to write, but each one made the system
> more reliable. Before reaching for fine-tuning or a bigger model, exhaust
> this lever first.
>
> The Phase 0 API contract did not change. `POST /tasks` still accepts a
> prompt and returns a task. What changed is what happens inside one function
> — exactly the slot we left open for intelligence to land in.

---

## Not done (carried forward)

- Prompts are plain Markdown without YAML frontmatter. Phase 3 introduces
  frontmatter (`name`, `version`, `model`, `description`) and a proper
  `load_prompt(name, version)` helper.
- No retries, no timeouts, no token/cost accounting on the LLM call. Budget
  enforcement lands in later phases.
- Triage is synchronous and blocks the request. That is fine at Phase 1 — the
  async worker arrives in Phase 5.
