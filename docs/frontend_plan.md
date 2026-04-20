# TeamFlow React Frontend — Vibe-coding Plan

## Context
The TeamFlow FastAPI service exposes a small but rich API (task creation, polling, handoff trace, SSE event stream) that currently has no UI. You want to vibe-code a React + TypeScript dashboard locally (Vite + Cursor/Claude) against the backend running on `http://127.0.0.1:8000`, styled with Tailwind + shadcn/ui, and built up in incremental slices rather than one big drop.

Goal: a dashboard that lets you submit prompts, watch the agent graph run live, and inspect past tasks — shaped to be a good demo for the "vibe coding with agents + tools + MCPs" talk.

## API surface (reference)
Source of truth: `src/teamflow/api/routes.py`, `src/teamflow/api/schemas.py`, `src/teamflow/core/models.py`.

- `POST /tasks` → 202, body `{ prompt }` → `TaskResponse`
- `GET  /tasks/{id}` → `TaskResponse` (full state)
- `GET  /tasks/{id}/trace` → `{ task_id, handoff_log: HandoffEntry[] }`
- `GET  /tasks/{id}/events` → SSE, JSON payloads of shape
  - `{ type: "status", status: "running"|"complete"|"failed", ... }`
  - `{ type: "node_update", node, decision, hop, handoffs }`

`TaskResponse` fields: `id, prompt, status, kind, findings[], subtasks[], child_reports[], report, handoff_log[], error, created_at`.

No auth. No CORS configured — **this must be fixed first** or the browser will block everything.

## Prerequisite: enable CORS on the backend
One tiny backend change in `src/teamflow/api/app.py` (inside `create_app()`):

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite default
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Gate it behind a settings flag if you prefer (`settings.cors_origins`), but for local vibecoding the hardcoded Vite origin is fine.

Alternative: set `server.proxy` in `vite.config.ts` to forward `/api` → `http://127.0.0.1:8000` and skip the CORS change. Pick one.

## Note on separate folder
Developing the frontend in a separate folder (or separate git repo) doesn't change anything technical — the browser still talks to `http://127.0.0.1:8000` over HTTP, so CORS/proxy setup is identical. The only practical differences:

- **Types can't be imported from Python.** Hand-mirror `src/types/api.ts` from `schemas.py`, or generate an OpenAPI spec from FastAPI (`/openapi.json`) and run `openapi-typescript` in the frontend repo.
- **Two terminals, two git repos.** Add a one-line README in the frontend repo pointing at this backend and the required `.env` vars.
- **`.env` for the frontend:** put `VITE_API_BASE_URL=http://127.0.0.1:8000` so the base URL is swappable (useful if you later point at a tunnel or deployed backend).

## Frontend stack
- **Vite** React + TypeScript template (`npm create vite@latest teamflow-ui -- --template react-ts`)
- **Tailwind v4** + **shadcn/ui** (LLMs know it well, lots of ready components)
- **TanStack Query** for task polling + cache
- **React Router** for `/`, `/tasks/:id`
- Native `EventSource` for SSE (no extra dep)
- Types hand-mirrored from `schemas.py` in `src/types/api.ts` (small surface, not worth OpenAPI codegen yet)

Directory shape:

```
teamflow-ui/
  src/
    api/client.ts        # fetch wrappers
    api/events.ts        # EventSource hook
    types/api.ts         # TaskResponse, HandoffEntry, etc.
    hooks/useTask.ts     # TanStack Query hooks
    pages/Dashboard.tsx
    pages/TaskDetail.tsx
    components/...       # shadcn/ui + custom
```

## Incremental slices
Each slice is a demo-able checkpoint. Stop, eyeball it in the browser, then move on.

### Slice 1 — Scaffold & connect
- Create Vite app, install Tailwind + shadcn/ui, init shadcn.
- Add `src/types/api.ts` mirroring `TaskResponse`, `Finding`, `HandoffEntry`, `TaskStatus`, `TaskKind`.
- Add `src/api/client.ts` with `createTask`, `getTask`, `getTrace` (typed `fetch`).
- Smoke test: a button on `/` that POSTs a hardcoded prompt and logs the response.

### Slice 2 — Submit + live stream (the hero view)
- Dashboard page: prompt `Textarea`, submit `Button`, status `Badge`.
- On submit → `createTask` → navigate to `/tasks/:id`.
- Task detail page opens `EventSource` on `/tasks/{id}/events`, renders a live event log (node, hop, decision) as shadcn `Card`s streaming in.
- When `status: "complete"` arrives, fetch full task and render `report` (markdown via `react-markdown`).

### Slice 3 — Task list
- Persist created task ids to `localStorage` (no backend list endpoint exists).
- Dashboard shows a `Table` of recent tasks, each row fetched via TanStack Query (`getTask`) with polling disabled once terminal.
- Click row → detail page.

### Slice 4 — Trace visualization
- On detail page, add a "Trace" tab showing the handoff log.
- Simple version: ordered list of `source → target` with reasoning.
- Snazzy version: render as a graph with `reactflow`, nodes = agents, edges = handoffs, hop number on edge.

### Slice 5 — Findings & subtasks polish
- Findings table (claim, source_url as link, confidence bar).
- Subtasks + child_reports as collapsible sections.
- Error state when `status: "failed"` — show `error` field prominently.

### Slice 6 (stretch) — UX niceties
- Toast on task completion.
- Copy-report button.
- Filter task list by status.
- Dark mode (shadcn freebie).

## Critical files to touch
Backend (one-time):
- `src/teamflow/api/app.py` — add CORS middleware.

Frontend (separate repo/folder — location doesn't matter, it talks to the backend over HTTP):
- `teamflow-ui/src/types/api.ts`
- `teamflow-ui/src/api/client.ts`
- `teamflow-ui/src/api/events.ts`
- `teamflow-ui/src/pages/Dashboard.tsx`
- `teamflow-ui/src/pages/TaskDetail.tsx`

## Verification per slice
- Slice 1: `curl` + browser devtools network tab shows 202 from `/tasks`.
- Slice 2: submit "What is LangGraph?" → events stream in < 2s, final report renders. Cross-check against `python main.py` terminal logs and `GET /tasks/{id}/trace`.
- Slice 3: reload page → previously submitted tasks still listed.
- Slice 4: handoff count in UI matches `len(handoff_log)` from `GET /tasks/{id}/trace`.
- Slice 5: trigger failure by unsetting `ANTHROPIC_API_KEY` → UI shows error state.

## Vibe-coding tips
- Keep `src/types/api.ts` open in the editor — paste it into the prompt when asking Claude/Cursor to generate a component, so it gets the field names right the first time.
- When a slice gets hairy, ask the agent to scaffold the component *without* data first, then wire the hook in a second pass. Fewer places to be wrong.
- Run `python main.py` in one terminal, `npm run dev` in another, and use the browser as the feedback loop — no unit tests needed for a demo UI.
