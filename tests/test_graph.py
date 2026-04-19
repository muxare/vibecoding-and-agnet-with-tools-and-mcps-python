from langgraph.graph import END

from teamflow.core.models import Finding
from teamflow.orchestration.graph import build_graph
from tests.conftest import StubResearch, StubSynth, StubTriage


def _make_graph(
    *, kind: str = "simple", findings: list[Finding] | None = None
) -> tuple[object, StubTriage, StubResearch, StubSynth]:
    triage = StubTriage(kind=kind)  # type: ignore[arg-type]
    research = StubResearch(findings=findings or [])
    synth = StubSynth(report="stub-report")
    graph = build_graph(triage=triage, research=research, synth=synth)
    return graph, triage, research, synth


def test_only_synth_node_has_edge_to_end() -> None:
    graph, *_ = _make_graph()
    compiled = graph.get_graph()  # type: ignore[attr-defined]
    terminal_sources = {e.source for e in compiled.edges if e.target == END}
    assert terminal_sources == {"synth_node"}, (
        f"only synth_node may terminate the graph; got {terminal_sources}"
    )


def test_simple_task_traverses_triage_research_synth() -> None:
    graph, _, research, synth = _make_graph(
        kind="simple",
        findings=[
            Finding(
                claim="c", source_url="https://example.com", confidence=0.5
            )
        ],
    )
    final = graph.invoke(  # type: ignore[attr-defined]
        {"prompt": "p", "task_id": "t1", "hops": 0},
        config={"configurable": {"thread_id": "t1"}},
    )
    assert final["kind"] == "simple"
    assert final["report"] == "stub-report"
    assert len(research.calls) == 1
    assert len(synth.calls) == 1
    assert [h["target"] for h in final["handoff_log"]] == ["research", "synth", "END"]


def test_complex_task_skips_research() -> None:
    graph, _, research, synth = _make_graph(kind="complex")
    final = graph.invoke(  # type: ignore[attr-defined]
        {"prompt": "p", "task_id": "t2", "hops": 0},
        config={"configurable": {"thread_id": "t2"}},
    )
    assert final["kind"] == "complex"
    assert research.calls == []
    assert len(synth.calls) == 1
    assert [h["target"] for h in final["handoff_log"]] == ["synth", "END"]
