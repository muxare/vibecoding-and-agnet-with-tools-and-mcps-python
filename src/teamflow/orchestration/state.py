from operator import add
from typing import Annotated, Literal, TypedDict

from teamflow.core.models import Finding


class HandoffLog(TypedDict):
    source: str
    target: str
    reasoning: str
    hop: int


class TeamFlowState(TypedDict, total=False):
    task_id: str
    prompt: str
    kind: Literal["unknown", "simple", "complex"]
    decision: str
    context_for_next: str
    findings: list[Finding]
    report: str
    hops: int
    handoff_log: Annotated[list[HandoffLog], add]
