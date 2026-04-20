from langgraph.graph import END

from teamflow.core.models import Finding
from teamflow.orchestration.graph import MAX_DEPTH, build_graph
from tests.conftest import StubResearch, StubSynth, StubTriage


def _make_graph(
    *,
    kind: str = "simple",
    subtasks: list[str] | None = None,
    findings: list[Finding] | None = None,
) -> tuple[object, StubTriage, StubResearch, StubSynth]:
    triage = StubTriage(kind=kind, subtasks=subtasks)  # type: ignore[arg-type]
    research = StubResearch(findings=findings or [])
    synth = StubSynth(report="stub-report", parent_report="stub-parent-report")
    graph = build_graph(triage=triage, research=research, synth=synth)
    return graph, triage, research, synth


def test_only_synth_nodes_have_edge_to_end() -> None:
    graph, *_ = _make_graph()
    compiled = graph.get_graph()  # type: ignore[attr-defined]
    terminal_sources = {e.source for e in compiled.edges if e.target == END}
    # Phase 5: synth_node terminates the simple/flat path; synth_parent_node
    # terminates the fan-out path. No other node may reach END directly.
    assert terminal_sources == {"synth_node", "synth_parent_node"}, (
        f"only synth nodes may terminate the graph; got {terminal_sources}"
    )


def test_simple_task_traverses_triage_research_synth() -> None:
    graph, _, research, synth = _make_graph(
        kind="simple",
        findings=[Finding(claim="c", source_url="https://example.com", confidence=0.5)],
    )
    final = graph.invoke(  # type: ignore[attr-defined]
        {"prompt": "p", "task_id": "t1", "hops": 0, "depth": 0},
        config={"configurable": {"thread_id": "t1"}},
    )
    assert final["kind"] == "simple"
    assert final["report"] == "stub-report"
    assert len(research.calls) == 1
    assert len(synth.calls) == 1
    assert [h["target"] for h in final["handoff_log"]] == ["research", "synth", "END"]


def test_complex_without_subtasks_falls_through_to_research() -> None:
    graph, _, research, synth = _make_graph(kind="complex", subtasks=[])
    final = graph.invoke(  # type: ignore[attr-defined]
        {"prompt": "p", "task_id": "t2", "hops": 0, "depth": 0},
        config={"configurable": {"thread_id": "t2"}},
    )
    assert final["kind"] == "complex"
    assert research.calls == ["p"]
    assert len(synth.calls) == 1
    assert final["report"] == "stub-report"


def test_complex_with_subtasks_fans_out_via_send() -> None:
    graph, _, research, synth = _make_graph(
        kind="complex",
        subtasks=["alpha", "beta"],
        findings=[Finding(claim="c", source_url="https://example.com", confidence=0.5)],
    )
    final = graph.invoke(  # type: ignore[attr-defined]
        {"prompt": "root", "task_id": "t3", "hops": 0, "depth": 0},
        config={"configurable": {"thread_id": "t3"}},
    )
    # Each child runs the flat subgraph. With kind=complex and depth>=MAX_DEPTH,
    # children fall through to research → synth.
    assert sorted(research.calls) == ["alpha", "beta"]
    assert len(final["child_reports"]) == 2
    assert all(r == "stub-report" for r in final["child_reports"])
    assert final["report"] == "stub-parent-report"
    assert len(synth.parent_calls) == 1


def test_depth_cap_prevents_recursive_fanout() -> None:
    # If a child were ever invoked at root depth, it could try to Send again.
    # MAX_DEPTH=1 means children always run at depth>=MAX_DEPTH, so even a
    # complex-with-subtasks triage in the child path won't fan out.
    graph, _, research, _ = _make_graph(
        kind="complex", subtasks=["one", "two"]
    )
    final = graph.invoke(  # type: ignore[attr-defined]
        {"prompt": "root", "task_id": "t4", "hops": 0, "depth": 0},
        config={"configurable": {"thread_id": "t4"}},
    )
    # Exactly one research call per leaf subtask — no exponential blow-up.
    assert sorted(research.calls) == ["one", "two"]
    assert len(final["child_reports"]) == 2


def test_max_depth_is_one() -> None:
    # Sanity check on the depth-cap constant referenced by tests above.
    assert MAX_DEPTH == 1
