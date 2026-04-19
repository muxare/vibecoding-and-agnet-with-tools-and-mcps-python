# Prompt Style Guide

This guide governs every system prompt under `prompts/`. The patterns here are
the ones from the Phase 3 roadmap, written down so a new contributor can author
or revise a prompt without re-deriving them.

## File layout

```
prompts/
  <agent>/
    <agent>.v1.md
    <agent>.v2.md
    ...
```

- One folder per agent (`triage`, `research`, ...).
- One file per version. Keep old versions forever — they are the teaching
  artifact for Phase 1's lesson on prompt evolution.
- Filename is the source of truth: `triage.v4.md` is loaded as
  `load_prompt("triage", "v4")`.

## Required frontmatter

Every file begins with a YAML-style frontmatter block:

```markdown
---
name: triage
version: v5
model: claude-sonnet-4-6
description: One-sentence summary of what this version changes.
---
```

Recognised keys: `name`, `version`, `model`, `description`. Missing values fall
back to filename inference. Unknown keys are ignored — no need to guard them.

## Body conventions

1. **System framing first.** One or two sentences of role and purpose. Avoid
   "you are a helpful assistant" filler.
2. **XML-delimited input contract.** When the runtime passes data into the
   prompt, wrap each section in a tag: `<task>`, `<constraints>`, `<schema>`,
   `<examples>`. Tags survive whitespace edits and are easy to grep.
3. **Output schema, inline.** Even when `with_structured_output` enforces the
   schema at the SDK layer, repeat it in the prompt. The model reads the
   prompt; the schema in code is invisible to it.
4. **Positive examples in `<examples>`.** Two minimum, covering the boundary
   between expected outputs (one per branch).
5. **Negative examples in `<negative_examples>`.** Each one tagged with a
   `reason` attribute that names the failure mode it prevents
   (`prose around JSON`, `markdown fence`, `claim without citation`, ...).
6. **Chain-of-thought is opt-in.** When a prompt benefits from "think step by
   step", put the reasoning instructions inside a `<process>` block and tell
   the model to keep that reasoning internal — never narrate it in the reply.
7. **No trailing exhortations.** Drop "Good luck!", "Be helpful!", and similar
   noise. They are tokens that buy nothing.

## Versioning rules

- Bump the version (`v4 → v5`) for any change a reviewer would want to compare
  side-by-side. Frontmatter typo fixes can edit in place.
- Update the agent's `DEFAULT_PROMPT_VERSION` constant in the same change.
- Note the change in the file's `description` frontmatter — this is what the
  evals dashboard groups by.

## Loading prompts in code

```python
from teamflow.core.prompts import load_prompt

prompt = load_prompt("triage", "v5")
prompt.body          # the markdown body, frontmatter stripped
prompt.model         # "claude-sonnet-4-6"
prompt.description   # one-line summary
```

## Testing

- A snapshot test in `tests/test_prompts.py` asserts the rendered body of each
  default prompt is unchanged. Update the snapshot intentionally when shipping
  a real prompt change — never silently.
- For prompts that interpolate values, use `Prompt.render(**values)` and write
  a test that pins the output for a representative input.
