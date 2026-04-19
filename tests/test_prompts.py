import pytest

from teamflow.core.prompts import Prompt, load_prompt


@pytest.mark.parametrize(
    ("name", "version"),
    [
        ("triage", "v1"),
        ("triage", "v2"),
        ("triage", "v3"),
        ("triage", "v4"),
        ("triage", "v5"),
        ("research", "v1"),
        ("research", "v2"),
        ("synth", "v1"),
    ],
)
def test_prompt_loads_with_frontmatter(name: str, version: str) -> None:
    prompt = load_prompt(name, version)
    assert prompt.name == name
    assert prompt.version == version
    assert prompt.model == "claude-sonnet-4-6"
    assert prompt.description, "description frontmatter is required"
    assert prompt.body.strip(), "body must be non-empty"
    assert not prompt.body.lstrip().startswith("---"), "frontmatter must be stripped"


def test_triage_v5_has_xml_contract_and_negative_examples() -> None:
    body = load_prompt("triage", "v5").body
    for tag in ("<task>", "<schema>", "<constraints>", "<examples>", "<negative_examples>"):
        assert tag in body, f"v5 must include {tag}"


def test_research_v2_has_chain_of_thought_block() -> None:
    body = load_prompt("research", "v2").body
    assert "<process>" in body
    assert "step by step" in body.lower()
    assert "<negative_examples>" in body


def test_render_substitutes_double_brace_placeholders() -> None:
    prompt = Prompt(
        name="t",
        version="v0",
        model=None,
        description=None,
        body="Hello, {{who}}! Code: {{code}}.",
    )
    assert prompt.render(who="world", code="42") == "Hello, world! Code: 42."


def test_triage_v5_body_snapshot() -> None:
    """Pinned snapshot of the current default triage prompt body.

    Update intentionally when shipping a real prompt change — never silently.
    """
    body = load_prompt("triage", "v5").body
    assert body.startswith("You classify research tasks for a research queue.")
    assert body.rstrip().endswith("</negative_examples>")
    # Stable identifying fragments — cheap regression detector.
    assert "When in doubt between simple and complex, prefer `complex`" in body
    assert '{"kind": "simple"}' in body
    assert '{"kind": "complex"}' in body
