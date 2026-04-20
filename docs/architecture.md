# TeamFlow Architecture

TeamFlow is a multi-agent research system built on **FastAPI** and **LangGraph**. A client submits a prompt; the system triages it, optionally decomposes it into parallel subtasks, runs a tool-using research agent per subtask, and synthesises a final report. Progress is streamed back over SSE.

## System architecture

The runtime is a single FastAPI app. Requests land in `api/routes.py`, tasks are stored in an in-memory `TaskRepository`, and execution happens in a background thread that drives the LangGraph orchestrator. An `EventBroker` fans per-node updates out to SSE subscribers.

```mermaid
flowchart LR
    Client[Client]

    subgraph API["FastAPI (api/)"]
        Routes[routes.py<br/>POST /tasks<br/>GET /tasks/:id<br/>GET /tasks/:id/events]
        Repo[(InMemoryTaskRepository)]
        Broker[EventBroker<br/>SSE fan-out]
    end

    subgraph Orchestration["Orchestration (orchestration/)"]
        Graph[LangGraph<br/>build_graph]
        State[TeamFlowState<br/>TypedDict]
    end

    subgraph Agents["Agents (agents/)"]
        Triage[Triage<br/>AnthropicTriage]
        Research[ResearchAgent<br/>LangGraphResearchAgent]
        Synth[Synth<br/>AnthropicSynth]
        Tools[web_search / web_fetch]
    end

    subgraph External["External"]
        Anthropic[Anthropic API<br/>Claude Haiku]
        Tavily[Tavily Search]
        Web[HTTP fetch]
    end

    Client -->|POST prompt| Routes
    Client <-->|SSE| Routes
    Routes --> Repo
    Routes --> Broker
    Routes -->|thread| Graph
    Graph <--> State
    Graph --> Triage
    Graph --> Research
    Graph --> Synth
    Research --> Tools
    Triage --> Anthropic
    Research --> Anthropic
    Synth --> Anthropic
    Tools --> Tavily
    Tools --> Web
    Graph -.->|node updates| Broker
```

## Agent graph

`build_graph` (`orchestration/graph.py`) assembles the top-level LangGraph. `triage_node` either routes a simple task straight to `research_node`, or — for a complex task at `depth=0` — fans out one `child_worker` per subtask using `Send`. Each child runs a flat triage → research → synth subgraph. Child reports are reduced into `child_reports` and rolled up by `synth_parent_node`.

```mermaid
flowchart TD
    START([START]) --> Triage[triage_node]

    Triage -->|decision=research<br/>or simple| Research[research_node]
    Triage -->|decision=synth<br/>hops >= MAX_HOPS| Synth[synth_node]
    Triage -->|decision=split<br/>+ subtasks<br/>+ depth &lt; MAX_DEPTH| Fanout{{Send per subtask}}

    Fanout --> CW1[child_worker #1]
    Fanout --> CW2[child_worker #2]
    Fanout --> CWN[child_worker #N]

    subgraph ChildGraph["Child subgraph (per Send)"]
        CStart([START]) --> CTriage[triage_node]
        CTriage --> CResearch[research_node]
        CTriage --> CSynth[synth_node]
        CResearch --> CSynth
        CSynth --> CEnd([END])
    end

    CW1 -.invoke.-> ChildGraph
    CW2 -.invoke.-> ChildGraph
    CWN -.invoke.-> ChildGraph

    CW1 --> SynthParent[synth_parent_node]
    CW2 --> SynthParent
    CWN --> SynthParent

    Research -->|route_from_research| Synth
    Research -.->|decision=triage<br/>& hops &lt; MAX_HOPS| Triage

    Synth --> END1([END])
    SynthParent --> END2([END])
```

Notes:
- `MAX_DEPTH = 1`: only the root may fan out; children are flat.
- `MAX_HOPS = 6`: a global circuit breaker that forces early synthesis.
- `CHILD_CONCURRENCY`: a `threading.Semaphore` caps parallel child subgraphs, since `graph.stream` runs Sends in a thread pool.
- Inside `research_node`, `LangGraphResearchAgent` runs its own inner graph: `llm_call ↔ tool_node` (see `agents/research.py`).

## Example execution flow

A complex query like *"Compare the positioning of Anthropic, OpenAI, and Google DeepMind in 2026."* Triage decomposes it into three subtasks, each runs its own research/synth pipeline in parallel, and results are rolled up.

```mermaid
sequenceDiagram
    autonumber
    actor U as Client
    participant R as routes.py
    participant B as EventBroker
    participant G as Root graph
    participant T as triage_node
    participant CW as child_worker (xN)
    participant CG as Child subgraph
    participant RA as ResearchAgent
    participant Tv as Tavily / web
    participant SP as synth_parent_node

    U->>R: POST /tasks {prompt}
    R->>R: thread: _run_task_sync
    R-->>U: 202 {task_id}
    U->>R: GET /tasks/:id/events (SSE)
    R->>B: subscribe

    R->>G: graph.stream(prompt, depth=0)
    G->>T: triage_node
    T->>T: classify: complex + 3 subtasks
    T-->>B: node_update(decision=split)

    par Subtask A
        G->>CW: Send(prompt=A, depth=1)
        CW->>CG: invoke child
        CG->>RA: research_node
        loop tool loop
            RA->>Tv: web_search / web_fetch
            Tv-->>RA: hits / page text
        end
        RA-->>CG: findings
        CG->>CG: synth_node → child report A
        CG-->>CW: report A
    and Subtask B
        G->>CW: Send(prompt=B, depth=1)
        CW->>CG: invoke child
        CG-->>CW: report B
    and Subtask C
        G->>CW: Send(prompt=C, depth=1)
        CW->>CG: invoke child
        CG-->>CW: report C
    end

    CW-->>G: child_reports += [A, B, C]
    G->>SP: synth_parent_node
    SP->>SP: synthesize_parent(reports)
    SP-->>B: node_update(synth_parent → END)
    G-->>R: final state

    R->>R: persist Task (report, findings, handoff_log)
    R-->>B: status=complete
    B-->>U: SSE status=complete
    U->>R: GET /tasks/:id
    R-->>U: {report, findings, handoff_log}
```

## Key files

- `api/app.py`, `api/routes.py` — FastAPI wiring, task thread, SSE endpoint.
- `orchestration/graph.py` — root graph + child subgraph + `Send` fan-out.
- `orchestration/state.py` — `TeamFlowState` with `add`-reduced `child_reports` and `handoff_log`.
- `agents/triage.py`, `agents/research.py`, `agents/synth.py` — the three agent roles.
- `agents/tools.py` — `web_search` and `web_fetch` tools bound to the research LLM.
- `infrastructure/events.py` — per-task pub/sub for SSE.
