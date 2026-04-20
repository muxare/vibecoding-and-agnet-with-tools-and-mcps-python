# Phase 5 — The Queue: Decomposition & Synthesis

**Concept:** Recursive task breakdown via the LangGraph `Send` API, plus
background execution and live event streaming over SSE.

## Why

Phase 4 handled simple tasks end-to-end through a triage → research → synth
graph. Complex tasks need **decomposition**: triage splits them into
independently researchable subtasks, each child runs through its own flat
graph in parallel, and a parent synthesizer rolls the child reports up
into a single final report.

This phase introduces the **Orchestrator-worker** pattern from
`workflows-agents.mdx` (specifically *Creating workers in LangGraph*), where
`Send` dynamically dispatches one worker node per subtask, and an
`Annotated[list, operator.add]` reducer merges their outputs.

## What was built

### Subtask decomposition in triage

- `TriageResult` (`src/teamflow/agents/triage.py`) gained a
  `subtasks: list[str]` field — empty for `simple`, 2–4 entries for `complex`.
- New prompt `prompts/triage/triage.v6.md` teaches the model to decompose
  with explicit positive and negative examples. v5 is preserved as a
  teaching artifact.
- `DEFAULT_PROMPT_VERSION` bumped to `v6`.

### State schema with parallel-safe reducer

`src/teamflow/orchestration/state.py` adds three fields to `TeamFlowState`:

- `subtasks: list[str]` — what triage decomposed into.
- `depth: int` — how deep we are in the Send tree (0 = root).
- `child_reports: Annotated[list[str], add]` — the same reducer pattern as
  `completed_sections` in `workflows-agents.mdx`, so parallel workers
  append without clobbering each other.

### Send-based fan-out and depth cap

`src/teamflow/orchestration/graph.py`:

- `MAX_DEPTH = 1` — root may decompose; children always run flat. With
  this cap there are at most two levels of agents in flight.
- `route_from_triage(state)` returns either:
  - a list of `Send("child_worker", substate)` objects when triage decided
    to split and we're at root depth, or
  - a node name (`"research_node"` or `"synth_node"`) for the simple path.
- `child_worker_node` invokes a *separate* compiled subgraph
  (`_build_child_subgraph`) that contains only triage/research/synth — no
  `child_worker` of its own, so further fan-out is structurally
  impossible. Depth is also bumped on dispatch as belt-and-braces.
- **Partial-failure policy**: a child exception is caught and turned into
  a `[child failed: ...]` sentinel inserted into `child_reports`. The
  parent synth proceeds with whatever children completed.

### Parent synthesizer

- `Synth` protocol gained `synthesize_parent(prompt, child_reports) -> str`.
- New prompt `prompts/synth.parent/synth.parent.v1.md` instructs the model
  to preserve every child citation, surface disagreements, and end with a
  unified Sources list.
- `synth_parent_node` runs after all `Send` workers complete (LangGraph
  waits for fan-out by default), and is the only terminal node on the
  fan-out path.

### Background execution & SSE streaming

- `Task` model (`src/teamflow/core/models.py`) gained
  `status: Literal["pending", "running", "complete", "failed"]`,
  `subtasks`, `child_reports`, and `error` fields.
- `POST /tasks` now returns **202 Accepted** immediately with a `pending`
  task and runs the graph in a daemon thread. Threading rather than
  `asyncio.create_task` because FastAPI's per-request event loop does not
  outlive the request — background asyncio tasks would be cancelled.
- New `EventBroker` (`src/teamflow/infrastructure/events.py`) — a
  thread-safe per-task buffer of events with a `threading.Event` flag.
  Subscribers get the full history on connect (so late subscribers don't
  miss the start) and get woken on each new publish.
- New endpoint **`GET /tasks/{id}/events`** streams events as
  `text/event-stream`. Each event is a JSON blob: status transitions and
  per-node updates including the handoff log entries that node produced.

### Topology

```
START → triage_node ──┬─→ research_node → synth_node → END           (simple path)
                      │
                      ├─→ synth_node → END                             (best-effort path)
                      │
                      └─→ [Send("child_worker", subtask) × N]
                              │
                              child_worker  (each runs flat subgraph)
                              │
                              ▼
                          synth_parent_node → END                      (fan-out path)
```

## How to demo

### 1. Show the simple path (Phase 4 still works)

```bash
curl -s -X POST http://localhost:8000/tasks \
  -H 'content-type: application/json' \
  -d '{"prompt":"what is the current price of gold"}'
# → 202 with status="pending"
```

Poll `GET /tasks/{id}` — status moves `pending → running → complete`. The
handoff log shows `triage → research → synth → END`. Same shape as Phase 4,
just async now.

### 2. Show the fan-out path (the Phase 5 headline)

```bash
curl -s -X POST http://localhost:8000/tasks \
  -H 'content-type: application/json' \
  -d '{"prompt":"analyze the EV market in Europe, including key players, regulation, and five-year outlook"}'
```

Then **immediately**:

```bash
curl -N http://localhost:8000/tasks/{id}/events
```

Watch the SSE stream:

- `{"type": "status", "status": "running"}`
- `{"type": "node_update", "node": "triage_node", "decision": "split", ...}`
  with a handoff entry pointing at `child_worker`.
- Several `{"type": "node_update", "node": "child_worker", ...}` events,
  one per subtask, arriving as each child completes.
- `{"type": "node_update", "node": "synth_parent_node", ...}` once all
  children are in.
- `{"type": "status", "status": "complete", "report_length": ...}`.

Then `GET /tasks/{id}` — the body now includes:

- `kind: "complex"`,
- `subtasks: [...]` — exactly what triage decomposed into,
- `child_reports: [...]` — one full report per subtask,
- `report` — the parent synthesis citing all child sources,
- `handoff_log` — every transition, including one `child_worker` entry
  per child.

### 3. Show the depth cap

The cap is structural — children can't fan out because their subgraph has
no `child_worker` node, and they're dispatched at `depth=MAX_DEPTH`. This
is verified by `tests/test_graph.py::test_depth_cap_prevents_recursive_fanout`:
even when the triage stub keeps returning subtasks, exactly one
`research` call happens per leaf subtask — no exponential blow-up.

### 4. Show partial-failure handling

Wire a `StubResearch` (or real research agent) that raises on one of the
subtasks. The corresponding child report becomes `[child failed: ...]`
and the parent synth still produces a final report from the surviving
children. The task ends in `status: "complete"`, not `"failed"` — failure
of an individual child does not fail the whole task.

### 5. Visualize the graph

```python
from teamflow.orchestration.graph import build_graph
# ... build with stubs ...
graph.get_graph().draw_mermaid_png()
```

Two terminal nodes are now visible: `synth_node` for the flat path and
`synth_parent_node` for the fan-out path. The terminal-edge test
(`tests/test_graph.py::test_only_synth_nodes_have_edge_to_end`) enforces
that no other node may reach `END` directly.

## Reflection

> The "queue" in TeamFlow turned out to be partly the LangGraph runtime
> itself. `Send` + the `add` reducer + a background worker thread give us
> durable parallel execution with almost no custom code. We did *not*
> write a job scheduler, a result aggregator, or a fan-in barrier —
> LangGraph waits for all `Send`s to complete before the next edge fires.
>
> What we *did* write: the state schema, the node functions, the depth
> cap, and the SSE plumbing that makes the graph's progress legible to a
> human. The framework owns mechanism; we own meaning.
