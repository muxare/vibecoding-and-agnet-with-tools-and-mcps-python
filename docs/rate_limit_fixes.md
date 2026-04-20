# Rate Limit Fixes — Implementation Brief

Active work order, scoped to the specific rate-limit failure observed on 2026-04-20. Not general policy — see `docs/rate_limiting.md` for that.

---

## What's happening

During a complex task with 4-child fan-out, we hit Anthropic's 30,000 input-tokens-per-minute limit on `claude-sonnet-4-6` (tier 1). Children launched in parallel, each spun up a ReAct loop that grew context on every turn, and the combined burst exceeded ITPM within ~40 seconds. Two children failed; the rest stalled in retry backoff.

The root causes, in order of contribution:

1. All four children run in parallel — no concurrency cap
2. Every LLM call re-sends the full system prompt (no prompt caching)
3. All three agents use Sonnet, including trivial triage calls
4. ReAct message history grows unbounded per research iteration

## Priority A — Do these first, in order

These are zero-quality-loss changes. Implement all three, then stop and measure before continuing.

### A1. Turn on prompt caching for the research agent's system message and tools

**Why:** Research agent's system prompt is ~1-2k tokens and gets re-sent on every ReAct turn (6+ turns × 4 children = ~25 redundant copies per task). Caching it cuts effective ITPM significantly with zero behavior change.

**Where:** Wherever the research agent's system message is constructed. If building the ReAct loop by hand, this is the function that assembles messages before each model call.

**What to do:** Mark the system message content with `cache_control: {"type": "ephemeral"}`. Use the content-block form, not the plain string form:

```python
from langchain_core.messages import SystemMessage

SystemMessage(content=[{
    "type": "text",
    "text": load_prompt("research.v3"),
    "cache_control": {"type": "ephemeral"},
}])
```

Also cache tool definitions if `langchain-anthropic`'s current API supports it — check their docs for the parameter name (it has shifted recently, so don't trust training data). Tool defs are another 1-2k tokens of stable content.

**Verify:** In Anthropic API response metadata, `cache_read_input_tokens` should be non-zero after the second turn of any research loop.

### A2. Serialize child execution with a semaphore

**Why:** Parallel fan-out is the single biggest multiplier on our ITPM consumption. Serializing costs wall-clock time, not quality.

**Where:** Wherever the parent graph fans out children via Send. Likely `orchestration/graph.py` or similar.

**What to do:** Wrap child invocation in an `asyncio.Semaphore(2)`. Start at 2; drop to 1 if A1-A3 together still hit limits.

```python
CHILD_CONCURRENCY = 2
child_semaphore = asyncio.Semaphore(CHILD_CONCURRENCY)

async def run_child(child_state):
    async with child_semaphore:
        return await child_graph.ainvoke(child_state)
```

Constant goes in `config/limits.py` alongside the existing `WORKER_CONCURRENCY`.

**Verify:** In the log, child `handoff` events for a single parent task should no longer appear within the same second.

### A3. Model tiering — Haiku for triage

**Why:** Triage is classification only. Haiku is ~5x cheaper, faster, and on a separate ITPM bucket. Same quality for this task.

**Where:** Wherever the triage LLM is instantiated.

**What to do:** Change triage's model to `claude-haiku-4-5`. Keep research and synth on Sonnet.

```python
triage_llm = ChatAnthropic(model="claude-haiku-4-5", ...)
research_llm = ChatAnthropic(model="claude-sonnet-4-6", ...)
synth_llm = ChatAnthropic(model="claude-sonnet-4-6", ...)
```

If synth has a skill-selection sub-call (for Phase 6), put that on Haiku too.

**Verify:** Tests still pass. Triage latency in logs should drop noticeably.

---

## Checkpoint — stop here and measure

Run the failing scenario from the logs: a complex prompt that fan-outs to 4 children ("analyze the EV market in Europe" or similar). Observe:

1. Does the task complete without 429s?
2. If 429s still occur, how many and at what stage?
3. Does Anthropic's response metadata show cache reads after turn 2?

**If the task now completes reliably:** stop. Commit the changes. Don't do Priority B.

**If 429s still occur but less frequently:** proceed to Priority B, but only the items that target the remaining failure mode.

**If 429s occur just as often:** something is wrong with the implementation of A1-A3. Check cache_control placement and semaphore wrapping before continuing.

---

## Priority B — Only if still hitting limits after Priority A

These are quality-preserving but more involved. Do them surgically, not all at once.

### B1. Summarization hook in the research ReAct loop

**Why:** Each ReAct iteration keeps all prior tool outputs in history. Fetches at 5000 chars add up fast. Summarizing the middle of the history (keeping recent turns verbatim) compresses context without losing fidelity.

**Where:** Inside the research agent's model-call node, before invoking the LLM. This is easier with a hand-rolled ReAct loop than with `create_react_agent`.

**What to do:** Add a `compress_messages_if_needed` function that summarizes messages older than the last 4, using Haiku. Critical rules for the summarizer prompt:

- Preserve all source URLs verbatim
- Preserve all factual claims verbatim
- Preserve all tool call arguments
- Drop only the model's reasoning prose between actions

```python
def compress_messages_if_needed(messages):
    if len(messages) <= 5:
        return messages
    # Guard: never split a tool_call / tool_result pair.
    # Keep first message + last 4, summarize the middle.
    ...
```

Log before/after token counts as a `structlog` event so we can measure the impact.

**Don't:** Compress when the most recent message is a `ToolMessage` waiting for the next model turn. The model needs the tool result adjacent to the tool call that produced it.

### B2. Tighten research agent's appetite

**Why:** Current research loops do 5-7 searches per simple task. That's thorough but expensive. A better-prompted agent plans first, searches less.

**Where:** Two places — the research prompt file and the hard iteration cap in the ReAct loop's conditional edge.

**What to do:**

Rewrite the research prompt to include:
> Plan your research BEFORE searching. Identify the 2-3 most specific queries that would resolve the question. Only expand if the initial results are insufficient. Never run parallel exploratory searches hoping something will stick.

Add a hard cap in the `should_continue` function that counts AIMessage turns with tool_calls and returns `"done"` once `MAX_RESEARCH_ITERATIONS` is hit (start at 8). This is task-semantic, unlike LangGraph's generic `recursion_limit`.

Keep the old prompt file alongside the new one (per the "never delete prompt versions" rule).

### B3. Per-process rate limiter for Sonnet

**Why:** Smooths bursts against ITPM. Doesn't raise the ceiling but prevents slamming into it.

**Where:** Wherever the Sonnet-using LLMs are instantiated.

**What to do:** Add a `langchain_core.rate_limiters.InMemoryRateLimiter` shared by research and synth (they're both on Sonnet, both compete for the same ITPM bucket).

```python
sonnet_limiter = InMemoryRateLimiter(
    requests_per_second=1.5,
    check_every_n_seconds=0.1,
    max_bucket_size=3,
)

research_llm = ChatAnthropic(model="claude-sonnet-4-6", rate_limiter=sonnet_limiter, ...)
synth_llm = ChatAnthropic(model="claude-sonnet-4-6", rate_limiter=sonnet_limiter, ...)
```

Tune downward if still hitting 429s.

### B4. Graceful degradation on rate-limit error

**Why:** A partial report beats a failed task. Right now a 429 propagates up and kills the child entirely.

**Where:** The research model-call node.

**What to do:** Wrap the LLM invocation in a try/except for `anthropic.RateLimitError`. On catch, return a `Command(goto=...)` that hands off to synth with whatever findings have been collected, tagged as `status="partial"` in state.

```python
try:
    response = research_llm_with_tools.invoke(messages)
    return {"messages": [response]}
except anthropic.RateLimitError:
    return Command(
        goto="handoff_to_synth",
        update={"status": "partial", "reason": "rate_limit"},
    )
```

Synth's prompt should be updated to note when findings are partial so the report reflects the limitation honestly.

---

## Don't do any of these

While you're in the rate-limiting area, you may notice things that look like they want fixing. They do not. Leave them alone for this work:

- **Do not truncate `web_fetch` output below 5000 chars.** That's already our policy. Aggressive truncation loses citations.
- **Do not build a retrieval/storage layer.** That's for cross-task knowledge reuse, not within-task burstiness. Different problem.
- **Do not rewrite the agent architecture.** The handoff pattern and graph structure are fine.
- **Do not remove the `LANGGRAPH_STRICT_MSGPACK` deserialization warnings.** That's a separate issue (register Pydantic models with LangGraph's msgpack allowlist); track it in its own todo, not here.
- **Do not change `MAX_HOPS`, `WORKER_CONCURRENCY`, or other existing limits in `config/limits.py`** except for adding `CHILD_CONCURRENCY` from A2 and the summarizer threshold if B1 is needed.
- **Do not "improve" prompts you happen to be editing.** Only the research prompt (B2) should change wording, and only with a new version file.

## Stopping criteria

This work is done when:

1. A 4-child complex task completes without 429s, reproducibly
2. Cache reads appear in response metadata after turn 2
3. Test suite still passes
4. LangSmith/logs show triage on Haiku, research/synth on Sonnet

Archive or merge this brief into `docs/rate_limiting.md` once complete.