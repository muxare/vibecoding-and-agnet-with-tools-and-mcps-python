# Rate Limit Fixes — Demo Instructions

Walk-through for showing A1 (prompt caching), A2 (child concurrency), and A3 (triage on Haiku) in action. Pair with `docs/rate_limit_fixes.md` for the underlying brief and `docs/rate_limiting.md` for policy context.

The demo reproduces the 2026-04-20 failure: a complex prompt that fans out to 4 children and previously hit Anthropic's 30k ITPM limit on `claude-sonnet-4-6` (tier 1).

---

## Prerequisites

- `ANTHROPIC_API_KEY` and `TAVILY_API_KEY` in `.env`
- Dependencies installed (`uv sync` or equivalent)
- A terminal with `jq` available for inspecting JSON log output

Before each section, start from a clean log. `run.log` isn't produced by the app — we create it by redirecting the server's stderr (where structlog writes JSON events) so we can `grep`/`jq` it offline:

```bash
rm -f run.log
```

Suggested demo prompt (reliably fans out to 4 children):

> "Analyze the EV market in Europe: policy drivers, major OEMs, charging infrastructure, and 2026 outlook."

---

## A1 — Prompt caching on the research agent

**What to show:** Research system prompt and tool defs are marked `cache_control: ephemeral`, so after the first ReAct turn each subsequent turn reads them from Anthropic's cache instead of re-sending.

### Where it lives

- `src/teamflow/agents/research.py` — `SystemMessage` uses the content-block form with `cache_control: {"type": "ephemeral"}` on the research prompt.

### Run the demo

```bash
uv run python main.py --port 8001 2> run.log &
curl -N -X POST localhost:8001/tasks \
  -H 'content-type: application/json' \
  -d '{"prompt": "Analyze the EV market in Europe: policy drivers, major OEMs, charging infrastructure, and 2026 outlook."}'
```

### What to verify

- Anthropic response metadata should show `cache_read_input_tokens` > 0 after the second research turn. In LangSmith, open any research LLM call past the first turn of a given child and look at the response usage payload.
- The app does not currently log `cache_read_input_tokens` via structlog, so `run.log` won't show it directly — use LangSmith (or inspect the response `usage` payload) to verify cache reads.

Expected: effective ITPM per child drops by roughly the size of the system prompt × (turns − 1).

---

## A2 — Child concurrency semaphore

**What to show:** A parent task that decomposes into 4 children now runs at most `CHILD_CONCURRENCY` (=2) children simultaneously, so ITPM bursts are bounded.

### Where it lives

- `src/teamflow/core/config.py` — `CHILD_CONCURRENCY = 2`
- `src/teamflow/orchestration/graph.py` — `asyncio.Semaphore` wraps child invocation in the fan-out node.

### Run the demo

Same request as A1. Stream the SSE response so handoff events print as they happen.

### What to verify

- In `run.log`, watch child completion timing. The fan-out node logs `child_complete` per child (`src/teamflow/orchestration/graph.py:219`) and a final `handoff` with `source="synth_parent"`:

  ```bash
  grep '"child_complete"' run.log | jq '{ts: .timestamp, task_id, depth}'
  ```

  With `CHILD_CONCURRENCY=2`, completions should cluster in two waves for a 4-child parent instead of landing nearly simultaneously.

- Wall-clock time for a 4-child task should be noticeably higher than pre-A2 (serialization cost), but no 429s.

### Tuning knob

Drop `CHILD_CONCURRENCY` to 1 if combined A1+A2+A3 still hit limits. Do not raise above 2 without measuring.

---

## A3 — Haiku system-wide

**What to show:** Every agent (triage, research, synth) runs on `claude-haiku-4-5`. This started as "Haiku for triage only" but was extended system-wide on 2026-04-20 as the accepted resolution to the Phase 5 rate-limit blocker — Haiku's ITPM headroom is large enough that the fan-out no longer bursts past the limit, so no token bucket is needed.

### Where it lives

- `src/teamflow/core/config.py` — both `default_model` and `triage_model` default to `"claude-haiku-4-5"`.
- `src/teamflow/agents/triage.py` — `AnthropicTriage` defaults its model to `settings.triage_model`.
- `src/teamflow/agents/research.py` / `synth.py` — default to `settings.default_model` (also Haiku).

### Run the demo

Fire a simple prompt first so triage is the only agent that runs:

```bash
curl -s -X POST localhost:8000/tasks \
  -H 'content-type: application/json' \
  -d '{"prompt": "What is the capital of France?"}' | tail -n 20
```

### What to verify

- LangSmith shows all three agent calls going to `claude-haiku-4-5`.
- Triage latency is subsecond — in `run.log`, the time between `task_accepted` and the `handoff` event with `source="triage"` should be under a second:

  ```bash
  grep -E '"task_accepted"|"handoff"' run.log | jq '{event, source, target, timestamp}'
  ```
- Test suite still passes:

  ```bash
  uv run pytest
  ```

### Overriding per-environment

`triage_model` is a pydantic-settings field, so it can be overridden via env var:

```bash
TRIAGE_MODEL=claude-sonnet-4-6 uv run python main.py   # back to Sonnet for comparison
```

---

## End-to-end sanity check

Run the original failing scenario with all three changes in place:

```bash
curl -N -X POST localhost:8000/tasks \
  -H 'content-type: application/json' \
  -d '{"prompt": "Analyze the EV market in Europe: policy drivers, major OEMs, charging infrastructure, and 2026 outlook."}'
```

Success criteria (updated 2026-04-20 after the Haiku-system-wide decision):

1. Task completes end-to-end without child failures, reproducibly
2. `cache_read_input_tokens` > 0 after turn 2 of any research loop
3. `uv run pytest` green
4. Logs show all agents on `claude-haiku-4-5`
5. Transient `GraphRecursionError` in a child surfaces as a `research_recursion_limit` warning, not a `child_failed` event — the child still produces findings from what it collected

Background: the original criterion "triage on Haiku, research/synth on Sonnet" is obsolete — the project moved Haiku system-wide instead of building the token-bucket limiter in `rate_limit_fixes.md`. Priority B in that doc would only become relevant if research/synth are moved back to Sonnet or `CHILD_CONCURRENCY` is raised above 1.
