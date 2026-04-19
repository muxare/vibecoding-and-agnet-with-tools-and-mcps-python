# Phase 3 — Structured Prompts

**Concept introduced:** Prompt engineering — advanced patterns

## Why

Phase 2 gave us a tool-using research agent. The next leverage point is the
prompts themselves: with real tools wired in, prompt edits now produce visible
downstream effects on cost, latency, and answer quality. Phase 3 builds the
infrastructure that makes prompt iteration tractable — versioned files,
frontmatter metadata, XML-delimited contracts, chain-of-thought triggers,
explicit negative examples, and a snapshot test that catches silent
regressions.

## What changed

### New shared loader

- `src/teamflow/core/prompts.py` — `load_prompt(name, version)` returns a
  `Prompt` dataclass:

  ```python
  prompt = load_prompt("triage", "v5")
  prompt.body          # markdown body, frontmatter stripped
  prompt.model         # "claude-sonnet-4-6"
  prompt.description   # one-line summary
  prompt.render(**values)  # interpolates {{name}} placeholders
  ```

- Both agents now go through this loader. The ad-hoc per-agent file readers
  were deleted.

### Frontmatter on every prompt

All `prompts/triage/triage.v{1..4}.md` were backfilled with YAML frontmatter
(`name`, `version`, `model`, `description`). `prompts/research/research.v1.md`
already had it. The frontmatter is the contract the loader and any future
evals dashboard groups by.

### New default prompt versions

- `prompts/triage/triage.v5.md` — XML-delimited contract with `<definitions>`,
  `<schema>`, `<constraints>`, `<examples>`, and `<negative_examples>` (each
  `<bad>` tagged with the failure mode it prevents: `prose around JSON`,
  `markdown fence`, `extra fields`). `DEFAULT_PROMPT_VERSION` in
  `src/teamflow/agents/triage.py` is now `v5`.
- `prompts/research/research.v2.md` — adds a `<process>` block with a
  three-step "think step by step" plan (kept internal), an XML `<workflow>`
  and `<rules>` split, and a `<negative_examples>` section covering
  uncited claims, fabricated URLs, and hedged non-answers.
  `DEFAULT_PROMPT_VERSION` in `src/teamflow/agents/research.py` is now `v2`.

### Style guide

`docs/prompts/README.md` documents the rules a contributor needs to author
or revise a prompt: file layout, required frontmatter, body conventions,
versioning rules, and the testing expectation.

### Tests

`tests/test_prompts.py` adds:

- Frontmatter coverage for every prompt (`name`, `version`, `model`,
  `description`, body non-empty, frontmatter stripped).
- Structural assertions on `triage.v5` (all five XML tags present) and
  `research.v2` ("step by step" + `<process>` + `<negative_examples>`).
- A `Prompt.render` placeholder test.
- A pinned snapshot of the `triage.v5` body — the silent-regression catcher
  the roadmap calls for.

`uv run pytest -q` reports **24 passed**. `ruff check` and `mypy` are clean.

## Demo

### 1. Show the prompt evolution side-by-side

The teaching artifact lives in `prompts/triage/`. Each version isolates one
prompt-engineering lever. Walk through them in a viewer:

```bash
ls prompts/triage/
# triage.v1.md  triage.v2.md  triage.v3.md  triage.v4.md  triage.v5.md
```

- `v1` — bare instruction. Unreliable.
- `v2` — adds role framing.
- `v3` — adds explicit task definitions and an inline JSON schema.
- `v4` — adds two few-shot examples.
- `v5` — XML-delimited contract + negative examples (this phase's addition).

### 2. Inspect the loader output

```bash
uv run python -c "
from teamflow.core.prompts import load_prompt
p = load_prompt('triage', 'v5')
print('name:', p.name)
print('version:', p.version)
print('model:', p.model)
print('description:', p.description)
print('---')
print(p.body[:300], '...')
"
```

You should see metadata parsed out of the frontmatter and the body returned
without the `---` block.

### 3. Run a real triage call against v4 and v5

With `ANTHROPIC_API_KEY` set, exercise both versions to feel the difference:

```bash
uv run python -c "
from teamflow.agents.triage import AnthropicTriage
for v in ('v4', 'v5'):
    t = AnthropicTriage(version=v)
    for prompt in [
        'what is the current price of gold',
        'compare the developer experience of Next.js, Remix, and SvelteKit for a small team',
        'should we migrate our analytics stack',  # ambiguous
    ]:
        print(v, '->', t(prompt).kind, '|', prompt)
"
```

The interesting row is the ambiguous one. v5's "when in doubt, prefer
complex" rule pushes the borderline case toward `complex`; v4 was silent on
the tie-breaker.

### 4. Run the research agent on the new prompt

```bash
uv run python -c "
from teamflow.agents.research import LangGraphResearchAgent
from teamflow.agents.tools import TavilySearchProvider  # or your provider
agent = LangGraphResearchAgent(provider=TavilySearchProvider(), prompt_version='v2')
for f in agent('what is the current price of gold'):
    print(f.confidence, f.source_url, '-', f.claim)
"
```

The `<negative_examples>` block should suppress uncited claims; every
`Finding` returned must carry a real `source_url` from a tool result.

### 5. Show the snapshot test catching a regression

Demonstrate the safety net by editing `prompts/triage/triage.v5.md` (e.g.,
remove the "when in doubt" sentence) and running:

```bash
uv run pytest tests/test_prompts.py -q
```

`test_triage_v5_body_snapshot` fails. Revert the edit, rerun — green. The
lesson: prompt changes are now first-class diffs, not silent drift.

### 6. Confirm the suite is healthy

```bash
uv run pytest -q          # 24 passed
uv run ruff check src tests
uv run mypy src tests
```

## Reflection

> "Structure beats cleverness. Once we had frontmatter, XML tags, and a
> snapshot test, the prompts stopped being prose-we-hope-works and started
> being artifacts-we-can-version. Every Phase 3 lever — role framing, schema
> in the prompt, few-shot, XML delimiters, chain-of-thought, negative
> examples — costs nothing to add and pays compounding interest at every
> later phase that loads a prompt."

## What's next

Phase 4 introduces LangGraph routing — the moment the two-agent pipeline
becomes a `StateGraph` with conditional edges. Each node will load its
system prompt through the same `load_prompt` helper added here, and the
prompt style guide will govern those prompts too.
