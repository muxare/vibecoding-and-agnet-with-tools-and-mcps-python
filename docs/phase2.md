# Phase 2 — First External Tool

**Concept introduced:** Tools & function calling.

## Why

Triage in Phase 1 was pure reasoning. Phase 2 gives the model two actual
capabilities — searching the web and fetching a page — and lets it decide
when to use them. The tool-calling loop is built **explicitly** as a
`StateGraph(MessagesState)` so the mechanism is visible before LangGraph
shortcuts hide it later.

## What was built

### `src/teamflow/agents/tools.py`

- `SearchHit` Pydantic model.
- `SearchProvider` Protocol (`search(query, max_results) -> list[SearchHit]`).
- `TavilySearchProvider` — single httpx call to `api.tavily.com/search`.
- `make_tools(provider)` factory returning two `@tool` functions:
  - `web_search(query)` — numbered list of title/URL/snippet results.
  - `web_fetch(url)` — first ~5000 chars of a URL's response body.
- Docstrings are written as prompts; the docstring change in the demo below
  changes behaviour with zero code change.

### `src/teamflow/agents/research.py`

`LangGraphResearchAgent` is the explicit two-node agent from
`workflows-agents.mdx §Agents`:

- `llm_call` node — invokes `llm.bind_tools(tools)` with the system prompt
  and the running message list; returns whatever the model produces (text or
  tool calls).
- `tool_node` — executes every `tool_call` on the last `AIMessage`,
  appending one `ToolMessage` per call. Tool errors are caught and fed back
  to the model as text so the loop can recover.
- `should_continue` — conditional edge: route to `tool_node` if the last
  message has tool calls, otherwise `END`.
- `recursion_limit = max_iterations * 2 + 1` caps the loop.
- After the loop, a separate `llm.with_structured_output(_Findings)` call
  extracts a list of `Finding(claim, source_url, confidence)` records from
  the final assistant message.

The constructor accepts an `llm=` and `extractor=` for tests; production
defaults to `ChatAnthropic(model=settings.default_model)`.

### `src/teamflow/core/models.py`

- New `Finding` model.
- `Task.findings: list[Finding]` (default `[]`).

### `src/teamflow/api/`

- `app.py` — wires `app.state.research`. Production uses `_LazyResearch`,
  which defers the `TAVILY_API_KEY` check until the first call so the app
  can boot without the key set.
- `routes.py` — `POST /tasks` calls `research(prompt)` when triage returns
  `simple`; complex tasks skip research (Phase 5 will fan them out).
- `schemas.py` — `TaskResponse.findings` exposed in the API.

### `prompts/research/research.v1.md`

System prompt for the research agent. Tells the model to alternate
`web_search` / `web_fetch`, prefer primary sources, and stop when it can
answer. Loaded by `_load_prompt("v1")`.

### Tests

13 pass (`uv run pytest`):

- `tests/test_tools.py` — tool rendering, empty-results path, docstring →
  description wiring.
- `tests/test_research.py` — scripted `FakeChatLLM` plays back an
  AIMessage with a `web_search` tool call, then a final answer; asserts
  the loop runs the tool, calls the LLM twice, and the extractor returns
  findings. A second test exercises the no-tool-call short-circuit.
- `tests/test_tasks.py` — `POST /tasks` with `kind=simple` populates
  `findings`; `kind=complex` does not invoke research.

`ruff check` and `mypy --strict` are clean.

## How to demo

### 1. Set keys

Add to `.env`:

```dotenv
ANTHROPIC_API_KEY=sk-ant-...
TAVILY_API_KEY=tvly-...
```

A free Tavily key from <https://tavily.com> works for the demo.

### 2. Boot the API

```bash
uv run uvicorn teamflow.api.app:app --reload
```

### 3. Submit a simple task and watch the loop

```bash
curl -s -X POST http://localhost:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "what is the current price of gold"}' | jq
```

Expected response shape:

```json
{
  "id": "…",
  "prompt": "what is the current price of gold",
  "kind": "simple",
  "findings": [
    {
      "claim": "Gold spot was $X/oz on …",
      "source_url": "https://…",
      "confidence": 0.8
    }
  ],
  "created_at": "…"
}
```

In the server log you'll see one `tool_call` line per LLM tool invocation
(`tool=web_search`, `tool=web_fetch`, with `args` and `result_chars`).
That's the loop in action: model → tool → model → tool → final answer →
structured extraction.

### 4. Confirm complex tasks skip research (until Phase 5)

```bash
curl -s -X POST http://localhost:8000/tasks \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "analyze the EV market in Europe"}' | jq
```

`kind` is `complex` and `findings` is `[]`.

### 5. The "docstring is a prompt" demo

In `src/teamflow/agents/tools.py`, change the `web_search` docstring's
first line from:

```text
Search the web for pages relevant to a query.
```

to:

```text
Search ONLY academic papers and primary research sources.
```

Restart the server and rerun step 3 with a question like
`"why is the sky blue"`. The model now scopes its queries differently —
no Python changed, only the docstring the model reads.

### 6. Fetch a stored task

```bash
curl -s http://localhost:8000/tasks/<id> | jq
```

Same body, retrieved from the in-memory repository.

## Reflection

The tool docstring is a prompt. We just wrote instructions for a stranger.
A vague docstring produces vague tool use. In Phase 4 we'll use the same
"structured model output drives behaviour" idea for control flow —
conditional edges between agent nodes — instead of the world.
