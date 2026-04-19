from pathlib import Path
from typing import Literal, Protocol, cast

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, SecretStr

from teamflow.core.config import settings

TriageKind = Literal["simple", "complex"]

DEFAULT_PROMPT_VERSION = "v4"
PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts" / "triage"


class TriageResult(BaseModel):
    kind: TriageKind = Field(
        description="Whether the task is simple (single lookup) or complex (multi-step report)."
    )


class Triage(Protocol):
    def __call__(self, prompt: str) -> TriageResult: ...


def load_prompt(version: str = DEFAULT_PROMPT_VERSION) -> str:
    return (PROMPTS_DIR / f"triage.{version}.md").read_text(encoding="utf-8")


class AnthropicTriage:
    def __init__(self, *, version: str = DEFAULT_PROMPT_VERSION, model: str | None = None) -> None:
        self._system_prompt = load_prompt(version)
        self._model = model or settings.default_model
        self._classifier: object | None = None

    def _get_classifier(self) -> object:
        if self._classifier is None:
            if not settings.anthropic_api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set — add it to .env or the environment."
                )
            llm = ChatAnthropic(
                model_name=self._model,
                api_key=SecretStr(settings.anthropic_api_key),
                timeout=None,
                stop=None,
            )
            self._classifier = llm.with_structured_output(TriageResult)
        return self._classifier

    def __call__(self, prompt: str) -> TriageResult:
        classifier = self._get_classifier()
        result = classifier.invoke(  # type: ignore[attr-defined]
            [
                SystemMessage(content=self._system_prompt),
                HumanMessage(content=prompt),
            ]
        )
        return cast(TriageResult, result)
