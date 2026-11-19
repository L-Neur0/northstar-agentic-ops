"""Tests for the turn graph and how many model calls a turn costs (spec 14 §3.1; AC-14.1, AC-14.2).

Why: the fixed order (EXTRACT → CLASSIFY only when needed → GUIDE) is the backbone of every turn,
and the call count is the cost. What: the compiled graph's nodes and edges, and the calls a
`FakeLLM` records for the three cases of AC-14.2.
"""

from langgraph.graph.state import CompiledStateGraph

from app.models.process_discovery_schemas import Profile
from app.services.process_discovery.interview.graph import build_graph, route_after_extract, route_from_start
from app.services.process_discovery.llm import CallType

from ..profile.builders import AT, cost_review_profile
from .helpers import fake, new_session, turn

SCOPE_PROCESS = {
    "scope": {
        "multi_role": True,
        "multi_system": True,
        "trigger_and_outcome": True,
        "recurring": True,
        "external_consumer": True,
        "reasoning": "several roles",
    }
}


def test_the_graph_shape(ctx):
    """AC-14.1."""
    graph = build_graph(fake(), ctx)
    assert isinstance(graph, CompiledStateGraph)
    drawn = graph.get_graph()
    assert {"extract", "classify", "guide"} <= set(drawn.nodes)
    edges = {(e.source, e.target) for e in drawn.edges}
    assert ("__start__", "extract") in edges
    assert ("classify", "guide") in edges
    assert ("guide", "__end__") in edges
    assert route_from_start({}) == "converse"
    assert route_after_extract({"profile": {}}, vocab=ctx.vocab) == "guide"


def current_session(ctx):
    profile = cost_review_profile(ctx.vocab, steps=2, filled_steps=0)
    return new_session(
        ctx,
        phase="steps",
        profile=Profile.model_validate(profile),
        scope={"verdict": None, "scoped_for": "Monthly cost review"},
        placement={"proposal": None, "placed_for": "Monthly cost review"},
    )


async def test_a_current_session_costs_two_calls(ctx):
    """AC-14.2."""
    llm = fake(EXTRACT=[{}], GUIDE=["Q?"])
    await turn(current_session(ctx), "hello", llm, ctx)
    assert [c.call_type for c in llm.calls] == [CallType.EXTRACT, CallType.GUIDE]


async def test_a_new_name_costs_three_calls(ctx):
    """AC-14.2."""
    session = new_session(ctx, phase="find")
    llm = fake(
        EXTRACT=[{"process.name": "Quarterly access review"}],
        CLASSIFY=[
            {
                **SCOPE_PROCESS,
                "placement": {
                    "code": "IT",
                    "confidence": 0.9,
                    "rationale": "r",
                    "runner_up": None,
                    "runner_up_confidence": None,
                },
            }
        ],
        GUIDE=["Q?"],
    )
    result = await turn(session, "the quarterly access review", llm, ctx)
    assert [c.call_type for c in llm.calls] == [CallType.EXTRACT, CallType.CLASSIFY, CallType.GUIDE]
    assert result.session.placement.placed_for == "Quarterly access review"


async def test_a_keyword_hit_with_a_current_scope_makes_no_classify_call(ctx):
    """AC-14.2."""
    session = new_session(ctx, phase="find", scope={"verdict": None, "scoped_for": "Monthly cost review"})
    llm = fake(EXTRACT=[{"process.name": "Monthly cost review"}], GUIDE=["Q?"])
    result = await turn(session, "the monthly cost review", llm, ctx)
    assert [c.call_type for c in llm.calls] == [CallType.EXTRACT, CallType.GUIDE]
    assert result.session.placement.proposal is not None
    assert result.session.placement.proposal.code == "FIN"
    assert result.session.placement.proposal.source == "keyword"
    assert AT
