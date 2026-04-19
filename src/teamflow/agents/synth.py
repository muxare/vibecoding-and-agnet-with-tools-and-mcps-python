from typing import Any, Protocol, cast

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import SecretStr

from teamflow.core.config import settings
from teamflow.core.models import Finding
from teamflow.core.prompts import load_prompt

DEFAULT_PROMPT_VERSION = "v1"


class Synth(Protocol):
    def __call__(self, prompt: str, findings: list[Finding]) -> str: ...


def _format_findings(findings: list[Finding]) -> str:
    if not findings:
        return "(no findings)"
    lines = []
    for i, f in enumerate(findings, start=1):
        lines.append(
            f"{i}. claim={f.claim!r} source_url={f.source_url} "
            f"confidence={f.confidence:.2f}"
        )
    return "\n".join(lines)


class AnthropicSynth:
    def __init__(
        self,
        *,
        version: str = DEFAULT_PROMPT_VERSION,
        model: str | None = None,
        llm: Any | None = None,
    ) -> None:
        self._system_prompt = load_prompt("synth", version).body
        self._model = model or settings.default_model
        self._llm_override: Any | None = llm
        self._llm: Any | None = None

    def _get_llm(self) -> Any:
        if self._llm_override is not None:
            return self._llm_override
        if self._llm is None:
            if not settings.anthropic_api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set — add it to .env or the environment."
                )
            self._llm = ChatAnthropic(
                model_name=self._model,
                api_key=SecretStr(settings.anthropic_api_key),
                timeout=None,
                stop=None,
            )
        return self._llm

    def __call__(self, prompt: str, findings: list[Finding]) -> str:
        user = (
            f"<task>\n{prompt}\n</task>\n\n"
            f"<findings>\n{_format_findings(findings)}\n</findings>"
        )
        response = self._get_llm().invoke(
            [
                SystemMessage(content=self._system_prompt),
                HumanMessage(content=user),
            ]
        )
        return cast(str, getattr(response, "content", "") or "")
