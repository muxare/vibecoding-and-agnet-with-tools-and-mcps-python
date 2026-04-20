from typing import Any
from uuid import uuid4

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from teamflow.agents.research import ResearchAgent
from teamflow.agents.synth import Synth
from teamflow.agents.triage import Triage
from teamflow.orchestration.state import HandoffLog, TeamFlowState

log = structlog.get_logger()

MAX_HOPS = 6
# Depth cap on Send-based decomposition. depth=0 is the root; children are
# dispatched at depth=1. With MAX_DEPTH=1, only the root may fan out — child
# graphs run as flat triage→research→synth chains. Two levels total.
MAX_DEPTH = 1


def _build_triage_node(triage: Triage) -> Any:
    def triage_node(state: TeamFlowState) -> dict[str, Any]:
        result = triage(state["prompt"])
        depth = state.get("depth", 0)
        hop = state.get("hops", 0) + 1

        # Honour the depth cap: deeper-than-root tasks are never decomposed,
        # they fall through to a flat research → synth chain.
        if depth >= MAX_DEPTH or not result.subtasks:
            if result.kind == "simple":
                decision, reasoning = (
                    "research",
                    "Single-lookup task — route to research for citations.",
                )
            else:
                decision, reasoning = (
                    "research",
                    f"Complex task without decomposition (depth={depth}) — "
                    "route to research as best-effort.",
                )
            log.info("handoff", source="triage", target=decision, hop=hop, depth=depth)
            return {
                "kind": result.kind,
                "subtasks": [],
                "decision": decision,
                "context_for_next": reasoning,
                "hops": hop,
                "handoff_log": [
                    HandoffLog(
                        source="triage", target=decision, reasoning=reasoning, hop=hop
                    )
                ],
            }

        # Complex with subtasks at root depth → fan out via Send.
        decision = "split"
        reasoning = f"Decomposed into {len(result.subtasks)} subtask(s) for parallel research."
        log.info(
            "handoff",
            source="triage",
            target="child_worker",
            hop=hop,
            depth=depth,
            subtasks=len(result.subtasks),
        )
        return {
            "kind": result.kind,
            "subtasks": list(result.subtasks),
            "decision": decision,
            "context_for_next": reasoning,
            "hops": hop,
            "handoff_log": [
                HandoffLog(
                    source="triage",
                    target="child_worker",
                    reasoning=reasoning,
                    hop=hop,
                )
            ],
        }

    return triage_node


def _build_research_node(research: ResearchAgent) -> Any:
    def research_node(state: TeamFlowState) -> dict[str, Any]:
        findings = research(state["prompt"])
        hop = state.get("hops", 0) + 1
        reasoning = f"Research complete with {len(findings)} finding(s) — hand off to synth."
        log.info(
            "handoff", source="research", target="synth", hop=hop, findings=len(findings)
        )
        return {
            "findings": findings,
            "decision": "synth",
            "context_for_next": reasoning,
            "hops": hop,
            "handoff_log": [
                HandoffLog(
                    source="research", target="synth", reasoning=reasoning, hop=hop
                )
            ],
        }

    return research_node


def _build_synth_node(synth: Synth) -> Any:
    def synth_node(state: TeamFlowState) -> dict[str, Any]:
        report = synth(state["prompt"], list(state.get("findings", [])))
        hop = state.get("hops", 0) + 1
        log.info("handoff", source="synth", target="END", hop=hop)
        return {
            "report": report,
            "hops": hop,
            "handoff_log": [
                HandoffLog(
                    source="synth", target="END", reasoning="Report written.", hop=hop
                )
            ],
        }

    return synth_node


def _route_from_research(state: TeamFlowState) -> str:
    if state.get("hops", 0) >= MAX_HOPS:
        return "synth_node"
    return "triage_node" if state.get("decision") == "triage" else "synth_node"


def _build_child_subgraph(
    *,
    triage: Triage,
    research: ResearchAgent,
    synth: Synth,
) -> Any:
    """A flat triage → research/synth → END graph used per subtask.

    Children invoke this with depth >= MAX_DEPTH so the shared triage node
    won't try to fan out further (which it couldn't anyway — this graph has
    no `child_worker`).
    """
    builder = StateGraph(TeamFlowState)
    builder.add_node("triage_node", _build_triage_node(triage))
    builder.add_node("research_node", _build_research_node(research))
    builder.add_node("synth_node", _build_synth_node(synth))
    builder.add_edge(START, "triage_node")

    def route_from_child_triage(state: TeamFlowState) -> str:
        if state.get("hops", 0) >= MAX_HOPS:
            return "synth_node"
        return "research_node" if state.get("decision") == "research" else "synth_node"

    builder.add_conditional_edges(
        "triage_node",
        route_from_child_triage,
        {"research_node": "research_node", "synth_node": "synth_node"},
    )
    builder.add_conditional_edges(
        "research_node",
        _route_from_research,
        {"synth_node": "synth_node", "triage_node": "triage_node"},
    )
    builder.add_edge("synth_node", END)
    return builder.compile(checkpointer=MemorySaver())


def build_graph(
    *,
    triage: Triage,
    research: ResearchAgent,
    synth: Synth,
    checkpointer: Any | None = None,
) -> Any:
    """Assemble the Phase 5 graph.

    Adds Send-based fan-out to the Phase 4 routing graph. When triage emits
    `subtasks`, a conditional edge dispatches one `child_worker` per
    subtask via the `Send` API. Each child runs the flat Phase 4 subgraph
    on its prompt and returns a report into `child_reports` via the `add`
    reducer. A `synth_parent_node` then rolls those reports into a single
    final report.
    """
    child_graph = _build_child_subgraph(triage=triage, research=research, synth=synth)

    triage_node = _build_triage_node(triage)
    research_node = _build_research_node(research)
    synth_node = _build_synth_node(synth)

    def child_worker_node(state: TeamFlowState) -> dict[str, Any]:
        """Run the child subgraph on one Send-dispatched subtask."""
        prompt = state.get("prompt", "")
        task_id = state.get("task_id") or uuid4().hex
        depth = state.get("depth", MAX_DEPTH)
        substate: dict[str, Any] = {
            "prompt": prompt,
            "task_id": task_id,
            "hops": 0,
            "depth": depth,
        }
        try:
            final = child_graph.invoke(
                substate,
                config={"configurable": {"thread_id": task_id}},
            )
            report = final.get("report") or "(empty child report)"
            log.info("child_complete", task_id=task_id, depth=depth, length=len(report))
        except Exception as exc:  # partial-failure policy: keep going
            report = f"[child failed for prompt {prompt!r}: {type(exc).__name__}: {exc}]"
            log.warning("child_failed", task_id=task_id, error=str(exc))
        return {
            "child_reports": [report],
            "handoff_log": [
                HandoffLog(
                    source="child_worker",
                    target="synth_parent",
                    reasoning=f"Child finished for: {prompt[:80]}",
                    hop=1,
                )
            ],
        }

    def synth_parent_node(state: TeamFlowState) -> dict[str, Any]:
        reports = list(state.get("child_reports", []))
        report = synth.synthesize_parent(state["prompt"], reports)
        hop = state.get("hops", 0) + 1
        log.info("handoff", source="synth_parent", target="END", hop=hop, children=len(reports))
        return {
            "report": report,
            "hops": hop,
            "handoff_log": [
                HandoffLog(
                    source="synth_parent",
                    target="END",
                    reasoning=f"Synthesised {len(reports)} child report(s).",
                    hop=hop,
                )
            ],
        }

    def route_from_triage(state: TeamFlowState) -> Any:
        if state.get("hops", 0) >= MAX_HOPS:
            return "synth_node"
        decision = state.get("decision")
        subtasks = state.get("subtasks") or []
        depth = state.get("depth", 0)
        if decision == "split" and subtasks and depth < MAX_DEPTH:
            task_id = state.get("task_id") or uuid4().hex
            return [
                Send(
                    "child_worker",
                    {
                        "prompt": s,
                        "task_id": f"{task_id}:{i}",
                        "hops": 0,
                        "depth": depth + 1,
                    },
                )
                for i, s in enumerate(subtasks)
            ]
        if decision == "research":
            return "research_node"
        return "synth_node"

    builder = StateGraph(TeamFlowState)
    builder.add_node("triage_node", triage_node)
    builder.add_node("research_node", research_node)
    builder.add_node("synth_node", synth_node)
    builder.add_node("child_worker", child_worker_node)
    builder.add_node("synth_parent_node", synth_parent_node)
    builder.add_edge(START, "triage_node")
    builder.add_conditional_edges(
        "triage_node",
        route_from_triage,
        ["research_node", "synth_node", "child_worker"],
    )
    builder.add_conditional_edges(
        "research_node",
        _route_from_research,
        {"synth_node": "synth_node", "triage_node": "triage_node"},
    )
    builder.add_edge("synth_node", END)
    builder.add_edge("child_worker", "synth_parent_node")
    builder.add_edge("synth_parent_node", END)

    return builder.compile(checkpointer=checkpointer or MemorySaver())


__all__ = ["MAX_DEPTH", "MAX_HOPS", "build_graph"]
