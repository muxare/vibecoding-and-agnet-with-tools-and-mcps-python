# Rate Limiting & Budgets — Policy

Durable reference for how TeamFlow handles rate limits, token pressure, and concurrency. This is policy, not a task list. For active tuning work, see scoped work orders like `rate_limit_fixes.md`.

---

## Why this matters

TeamFlow is an agent system on Anthropic + Tavily. A single user task can fan out to 20-40 LLM calls and 10+ search calls across triage, research, and synth agents, with multipliers from child decomposition and ReAct loops. This is not a typical API workload. Rate-limit pressure is a first-class concern and must be designed for, not patched around.

## The three pressure points

Anthropic enforces limits on three axes simultaneously; any one can fail a task:

- **Requests per minute (RPM)**
- **Input tokens per minute (ITPM)** — almost always the first to hit for agent systems, because ReAct loops re-send history
- **Output tokens per minute (OTPM)** — rarely the bottleneck for us

Tavily has its own per-minute limits on the paid tiers. Documented in their dashboard.

Find current Anthropic limits at `console.anthropic.com/settings/limits`. They differ per model (Haiku > Sonnet > Opus) and per tier (1 through 4, based on spend history).

---

## Config — single source of truth

All limiting-related constants live in `src/teamflow/config/limits.py`. No magic numbers elsewhere. Every constant has a comment explaining why it has its current value; future tuning passes update both.

```python
# Anthropic tier — check at console.anthropic.com/settings/limits
ANTHROPIC_TIER = 1                 # update when tier changes

# Concurrency — the biggest lever
WORKER_CONCURRENCY = 4             # max simultaneous graph runs (root tasks)
CHILD_CONCURRENCY = 2              # max simultaneous child tasks within one parent

# Agent budgets
MAX_HOPS = 6                       # graph transitions per task
MAX_RESEARCH_ITERATIONS = 8        # ReAct loop iterations in research agent
WEB_FETCH_MAX_TOKENS = 4000        # per-fetch result cap

# Caching
ENABLE_PROMPT_CACHE = True         # cache system prompts and tool defs
TAVILY_CACHE_TTL_SECONDS = 3600    # query result cache

# Resilience
MAX_RETRIES = 5                    # per LLM call; SDK handles exponential backoff
```

Rate limiter RPS values and summarization thresholds are also here when those features are enabled.

---

## The core techniques

Listed roughly in order of bang-for-buck. Not all are implemented at all times — see "when to reach for each" below.

### Concurrency control

The single most effective defense. Rate limits are per-minute; worker concurrency is per-second. A single semaphore capping in-flight graph runs prevents the multiplier effect from spiraling.

Two layers:

- `WORKER_CONCURRENCY` caps root-task parallelism at the queue level
- `CHILD_CONCURRENCY` caps fan-out parallelism within a single parent

Both are in `orchestration/worker.py` and whatever node dispatches children. Start conservative; loosen only when observability shows headroom.

### Model tiering

Match model to task difficulty:

- **Haiku** — triage, skill selection, summarization. Classification-shaped work.
- **Sonnet** — research, synthesis. Reasoning-shaped work where quality matters.
- **Opus** — not currently used. Reach for it only if evals show Sonnet can't handle synth quality.

Separate models also use separate rate-limit buckets, which gives natural headroom when one bucket is under pressure.

Models are instantiated once per agent in a single location — never inline. This makes swapping cheap and consistent.

### Prompt caching

Anthropic's ephemeral cache cuts effective input tokens substantially for anything stable across calls. Cache:

- System prompts (research, synth, any agent with a prompt > ~1024 tokens)
- Tool definitions (they're constant per agent)
- Skill content once skills are loaded into synth

Use the content-block form with `cache_control: {"type": "ephemeral"}`. Verify via `cache_read_input_tokens` in response metadata.

Don't cache anything that varies per call: user prompts, accumulated findings, chat history.

### Per-agent rate limiters

Client-side limiter via `langchain_core.rate_limiters.InMemoryRateLimiter`, attached to `ChatAnthropic` constructors. Smooths bursts before they hit 429s.

One limiter per *model*, not per agent — research and synth share a Sonnet limiter because they compete for the same bucket; triage gets its own Haiku limiter.

Caveats:
- Limits requests only, not tokens
- Per-process — multi-worker deployments need a shared (Redis-based) limiter
- Not a substitute for concurrency control; it's complementary

### Tool output truncation

`web_fetch` results are truncated to `WEB_FETCH_MAX_TOKENS` before entering agent context. `web_search` results already come back bounded but should be inspected if Tavily config changes.

Truncation happens at tool-call injection time, not inside the tool function itself, so we can vary truncation per tool or iteration if needed.

**Do not truncate below 4000 tokens without evals.** Aggressive truncation loses citations and degrades research quality invisibly.

### Summarization of ReAct history

When a research loop exceeds ~5 messages, the middle of the history is compressed using Haiku while recent turns stay verbatim. This is the quality-preserving alternative to dropping old messages.

Invariants the summarizer prompt must enforce:
- All source URLs preserved verbatim
- All factual claims preserved verbatim
- All tool call arguments preserved verbatim
- Only the model's reasoning prose between actions may be dropped

Summarization is opt-in per agent — it's overhead if context isn't actually large. Enable via a config flag, measure the win.

### Hard iteration caps

Every ReAct loop has a hard cap enforced in its conditional edge, not relying on prompts alone. `MAX_RESEARCH_ITERATIONS` counts tool-call rounds; when exceeded, the loop exits with whatever findings exist.

This is task-semantic (counts rounds of work), not framework-semantic (like LangGraph's generic `recursion_limit`). Prefer the task-semantic cap.

### Graceful degradation on 429

Wrap model calls in the research node with `try/except anthropic.RateLimitError`. On catch, return a `Command` that hands off to synth with `status="partial"` in state. Synth's prompt acknowledges partial findings honestly.

Partial reports beat failed tasks. The UX cost of "some research incomplete" is lower than "task failed, try again."

### Result caching (Tavily)

Hash `(query, date_bucket=today)` → cached result with `TAVILY_CACHE_TTL_SECONDS` TTL. Same child tasks searching "market size" multiple times should not pay Tavily multiple times.

In-memory LRU is fine for single-worker; Redis when multi-worker. Behind a `SearchProvider` protocol so the cache is transparent to agents.

---

## When to reach for each technique

Some techniques are always on. Others are added when observability shows pressure. Rough order of "when do I need this":

| Always on                        | Add when ITPM pressure appears   | Add when still pressured       |
| -------------------------------- | -------------------------------- | ------------------------------ |
| Concurrency caps                 | Prompt caching                   | Summarization hook             |
| Model tiering                    | Per-agent rate limiters          | Lower concurrency further      |
| Tool output truncation (4k)      | Tavily result caching            | Graceful 429 degradation       |
| Hard iteration caps              |                                  | Tier upgrade                   |
| SDK retry (`max_retries=5`)      |                                  |                                |

The always-on column should be in place from Phase 2 onward. The middle column typically gets added once real research tasks start hitting ITPM. The right column is for when you've tried the others and still see 429s.

## What not to build (yet)

These come up naturally but are the wrong tool for rate-limit problems as experienced:

- **Redis-backed distributed limiters.** Only meaningful with multi-worker deployments. Single-worker for now; note the limitation in deployment docs.
- **Token-per-minute client-side limiter.** Truncation + caching + iteration caps cover this at our scale. Building a TPM limiter adds complexity without a clear win until we have real multi-worker load.
- **Per-user quotas.** No auth layer yet. Revisit when one exists.
- **Retrieval/storage for context compression.** That's a cross-task knowledge reuse feature, not a rate-limit mitigation. See the Phase 10 discussion if we build it at all.
- **Aggressive tool output truncation.** Below 4000 tokens, we lose citations. Don't.

## Resilience baseline

Rely on the SDK's retry behavior for transient failures:

```python
llm = ChatAnthropic(
    model="claude-sonnet-4-6",
    max_retries=MAX_RETRIES,
    # SDK honors retry-after on 429; exponential backoff otherwise
)
```

Do not wrap with custom retry logic. It shadows the SDK's backoff and typically makes things worse.

Log all 429s, limiter waits, retries, and partial-mode degradations to structlog with `task_id`, `agent`, `reason`, `wait_ms`. LangSmith shows the LLM-side detail; structlog shows the orchestration-side signals that LangSmith can't see.

---

## Tuning protocol

Never change limit constants based on intuition. Tune based on signals:

**If you see 429s in logs:**

- Identify which model and which agent
- Lower the relevant RPS limiter by 20%, or lower `CHILD_CONCURRENCY` by 1
- If the issue is ITPM not RPM, prompt caching is often the right fix before touching limiters

**If you see limiter waits > 1s at p95 without 429s:**

- Safe to raise the limiter's RPS modestly
- May indicate the limiter is over-conservative relative to actual tier

**If tail latency is bad but 429s are zero:**

- Concurrency is likely the bottleneck, not rate limits
- Lower `WORKER_CONCURRENCY` or `CHILD_CONCURRENCY`

**If research agent ITPM grows over a task's lifetime:**

- History is the culprit; enable summarization hook for that agent
- Do not enable globally — summarization has cost; only pay it where it wins

**If Tavily hits its limit:**

- Result caching first, then per-process rate limit, then upgrade plan

## Tier upgrades

The tier listed in `ANTHROPIC_TIER` is checked manually, not auto-detected. Anthropic auto-upgrades based on spend history but with some lag. If approaching limits regularly, request an upgrade directly rather than waiting.

Update `ANTHROPIC_TIER` in config when it changes, and revisit the per-model RPS values — higher tiers usually permit more headroom in all limiters.

## Observability requirements

Rate-limit work is uninterpretable without these signals:

- Every limiter wait, retry, cache hit/miss, and budget trip logged via structlog (`agent`, `reason`, `wait_ms`, `task_id`)
- Per-task token usage visible in LangSmith (free if LangSmith is wired)
- Per-task handoff count and research iteration count emitted in structlog summaries at task completion
- 429 errors logged at `warning` level, never silently swallowed by retry logic

---

## Relationship to other docs

- **`CLAUDE.md`** — points here for rate-limit questions
- **`rate_limit_fixes.md`** (if present) — active work order for a specific tuning pass. Its lasting lessons get folded back into this doc when the work lands, then it's archived.
- **Phase docs** (`docs/phases/PHASE_N.md`) — may reference specific constants or techniques from here