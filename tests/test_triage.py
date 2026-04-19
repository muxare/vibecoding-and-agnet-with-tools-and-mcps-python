import pytest

from teamflow.agents.triage import load_prompt


@pytest.mark.parametrize("version", ["v1", "v2", "v3", "v4"])
def test_load_prompt_versions_exist(version: str) -> None:
    body = load_prompt(version)
    assert body.strip(), f"prompt {version} should be non-empty"


def test_v4_contains_few_shot_examples() -> None:
    body = load_prompt("v4")
    assert "Examples" in body
    assert "simple" in body
    assert "complex" in body
