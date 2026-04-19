from typing import Any, Literal

import structlog
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from teamflow.agents.research import ResearchAgent
from teamflow.agents.synth import Synth
from teamflow.agents.triage import Triage
from teamflow.orchestration.state import HandoffLog, TeamFlowState

log = structlog.get_logger()

MAX_HOPS = 6


def _kind_to_decision(kind: str) -> tuple[str, str]:
    """Map a triage kind to a next_agent + human-readable reasoning.

    Simple tasks go through research before synth. Complex tasks skip
    research in Phase 4 — decomposition lands in Phase 5 via the Send API.
    """
    if kind == "simple":
        return "research", "Single-lookup task — route to research for citations."
    if kind == "complex":
        return (
            "synth",
            "Multi-step task — decomposition arrives in Phase 5; "
            "routing to synth for a best-effort report.",
        )
    return "synth", "Unknown kind — terminating via synth."


def build_graph(
    *,
    triage: Triage,
    research: ResearchAgent,
    synth: Synth,
    checkpointer: Any | None = None,
) -> Any:
    """Assemble the Phase 4 routing graph.

    Three top-level nodes — triage, research, synth — connected by two
    conditional edges whose routers read `state["decision"]`. Only
    `synth_node` has an edge to `END`.
    """

    def triage_node(state: TeamFlowState) -> dict[str, Any]:
        result = triage(state["prompt"])
        decision, reasoning = _kind_to_decision(result.kind)
        hop = state.get("hops", 0) + 1
        log.info("handoff", source="triage", target=decision, hop=hop)
        return {
            "kind": result.kind,
            "decision": decision,
            "context_for_next": reasoning,
            "hops": hop,
            "handoff_log": [
                HandoffLog(source="triage", target=decision, reasoning=reasoning, hop=hop)
            ],
        }

    def research_node(state: TeamFlowState) -> dict[str, Any]:
        findings = research(state["prompt"])
        hop = state.get("hops", 0) + 1
        reasoning = f"Research complete with {len(findings)} finding(s) — hand off to synth."
        log.info("handoff", source="research", target="synth", hop=hop, findings=len(findings))
        return {
            "findings": findings,
            "decision": "synth",
            "context_for_next": reasoning,
            "hops": hop,
            "handoff_log": [
                HandoffLog(source="research", target="synth", reasoning=reasoning, hop=hop)
            ],
        }

    def synth_node(state: TeamFlowState) -> dict[str, Any]:
        report = synth(state["prompt"], list(state.get("findings", [])))
        hop = state.get("hops", 0) + 1
        log.info("handoff", source="synth", target="END", hop=hop)
        return {
            "report": report,
            "hops": hop,
            "handoff_log": [
                HandoffLog(source="synth", target="END", reasoning="Report written.", hop=hop)
            ],
        }

    def route_from_triage(state: TeamFlowState) -> Literal["research_node", "synth_node"]:
        if state.get("hops", 0) >= MAX_HOPS:
            return "synth_node"
        return "research_node" if state.get("decision") == "research" else "synth_node"

    def route_from_research(state: TeamFlowState) -> Literal["synth_node", "triage_node"]:
        if state.get("hops", 0) >= MAX_HOPS:
            return "synth_node"
        return "triage_node" if state.get("decision") == "triage" else "synth_node"

    builder = StateGraph(TeamFlowState)
    builder.add_node("triage_node", triage_node)
    builder.add_node("research_node", research_node)
    builder.add_node("synth_node", synth_node)
    builder.add_edge(START, "triage_node")
    builder.add_conditional_edges(
        "triage_node",
        route_from_triage,
        {"research_node": "research_node", "synth_node": "synth_node"},
    )
    builder.add_conditional_edges(
        "research_node",
        route_from_research,
        {"synth_node": "synth_node", "triage_node": "triage_node"},
    )
    builder.add_edge("synth_node", END)

    return builder.compile(checkpointer=checkpointer or MemorySaver())


__all__ = ["MAX_HOPS", "build_graph"]
