# Phase 4 — LangGraph Routing

**Concept:** Agents as nodes in a `StateGraph`; handoffs as `add_conditional_edges` driven by a structured-output decision.

## What shipped

### State & orchestration

- `src/teamflow/orchestration/state.py` — `TeamFlowState` TypedDict with `prompt`, `kind`, `decision`, `context_for_next`, `findings`, `report`, `hops`, and `handoff_log: Annotated[list[HandoffLog], add]` (reducer lets nodes append without clobbering).
- `src/teamflow/orchestration/graph.py` — `build_graph(triage, research, synth, checkpointer=None)` assembles three nodes:
  - `triage_node` — calls the triage callable, maps `kind → decision` (`simple → research`, `complex → synth`), appends a handoff entry.
  - `research_node` — invokes the Phase 2 research agent, writes findings + `decision="synth"`.
  - `synth_node` — writes the final report. The only node with an edge to `END`.
- Routers: `route_from_triage`, `route_from_research`. Both honour `MAX_HOPS = 6` by forcing `synth_node`.
- `MemorySaver` checkpointer wired by default.

### Agent

- `src/teamflow/agents/synth.py` — `Synth` protocol + `AnthropicSynth` implementation.
- `prompts/synth/synth.v1.md` — cited-report prompt following the style guide (XML input contract, positive/negative examples).

### API

- `POST /tasks` now invokes the compiled graph; `Task` gains `report` and `handoff_log`.
- `GET /tasks/{id}/trace` returns the ordered handoff log for a task.

### Tests (30 passing)

- `tests/test_graph.py::test_only_synth_node_has_edge_to_end` — terminal-edge discipline asserted on the compiled graph.
- Simple vs. complex routing traces asserted at both the graph and HTTP layers.

## Rules of the road honoured

- Only `synth_node` terminates the graph (enforced by test).
- All cross-node state lives in `TeamFlowState`. No side channels.
- `MAX_HOPS` enforced inside every router.
- Every transition appends to `handoff_log` via the `add` reducer.

## How to demo

Prereqs: `ANTHROPIC_API_KEY` (triage + synth) and `TAVILY_API_KEY` (research) in `.env`.

### 1. Run the tests — prove the topology

```bash
uv run pytest -x
```

The `test_only_synth_node_has_edge_to_end` test is the headline assertion: the framework's edges, not our code, enforce that only synth can terminate.

### 2. Start the API

```bash
uv run uvicorn teamflow.api.app:app --reload
```

### 3. Simple task → triage → research → synth

```bash
curl -s -X POST http://localhost:8000/tasks \
  -H 'content-type: application/json' \
  -d '{"prompt": "what is the current price of gold"}' | jq
```

Expected in the response:

- `kind == "simple"`
- non-empty `findings` with citations
- a prose `report` grounded in the findings
- `handoff_log` targets: `["research", "synth", "END"]`

### 4. Complex task → triage → synth (research skipped until Phase 5)

```bash
curl -s -X POST http://localhost:8000/tasks \
  -H 'content-type: application/json' \
  -d '{"prompt": "analyze the EV market in Europe"}' | jq
```

Expected:

- `kind == "complex"`
- `findings == []`
- `handoff_log` targets: `["synth", "END"]`

### 5. Inspect the trace

```bash
TASK_ID=<paste id from step 3>
curl -s http://localhost:8000/tasks/$TASK_ID/trace | jq
```

Shows the ordered `(source, target, reasoning, hop)` log — the pedagogical payoff of Phase 4. Same endpoint for any task.

### 6. Talking points while demoing

- Point at `orchestration/graph.py`: the router functions are ~3 lines each. LangGraph owns dispatch, state merge, and checkpointing.
- Contrast with Phase 2: in both cases a *structured model output drives something*. Phase 2 pointed that output at the world (tools); Phase 4 points it at the graph (next node).
- Flip `triage.kind` in a stub (or change the prompt) — same graph, different traversal, zero routing code touched.

## Deferred to later phases

- Complex-task decomposition via `Send` — Phase 5.
- Durable checkpointer (Postgres) — Phase 5/9.
- Skill-driven synth output — Phase 6.
- LangSmith trace links + eval gates — Phase 8.
