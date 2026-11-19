"""Tests for the ask target and proposal groups (spec 14 §3.8; AC-14.41 to AC-14.43).

Why: code chooses the one thing each question is about, and `last_question` must record exactly
that, or the next reply cannot be read. What: the priority table, the THIS TURN line against the
stored `last_question`, and the proposal groups.
"""

from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.domain.scope import keyword_placement
from app.services.process_discovery.interview.phases import next_ask, proposal_group
from app.services.process_discovery.llm import CallType
from app.services.process_discovery.profile.proposals import FieldProposal, ProposalDiff, StepProposal, apply_proposals
from app.services.process_discovery.profile.shapes import empty_profile

from ..profile.builders import AT, cost_review_profile
from .helpers import fake, turn
from .sessions import BOUNDARIES, MEASURE, profile_with, session_at


def ask(ctx, profile, phase, **parts):
    return next_ask({"profile": profile, "phase": phase, **parts}, vocab=ctx.vocab)


def test_the_priority_table(ctx):
    """AC-14.42."""
    base = profile_with(ctx)
    assert ask(ctx, base, "boundaries", scope={"awaiting_widening": True}).kind == "widening"
    proposed = apply_proposals(
        base, ProposalDiff("d1", fields=(FieldProposal("process.trigger", "T", "t"),)), vocab=ctx.vocab, at=AT
    ).profile
    assert ask(ctx, proposed, "boundaries") == ("proposals", ("process.trigger",), None)
    no_cluster = profile_with(ctx)
    no_cluster["process"]["cluster"] = {"code": "", "name": "", "decided_by": ""}
    del no_cluster["__meta"]["process.cluster"]
    placed = {"proposal": keyword_placement("FIN"), "placed_for": "Monthly cost review"}
    assert ask(ctx, no_cluster, "find", placement=placed) == ("cluster", ("process.cluster",), "propose")
    assert (
        ask(ctx, no_cluster, "find", placement=placed, counters={"field_asks": {"process.cluster": 2}}).mode == "picker"
    )
    assert ask(ctx, no_cluster, "find", placement=placed, counters={"find_turns": 5}).mode == "picker"
    assert ask(ctx, no_cluster, "find").mode == "picker"
    assert ask(ctx, base, "boundaries") == ("field", ("process.trigger",), None)
    walking = profile_with(ctx, *BOUNDARIES, *MEASURE, steps=2)
    assert ask(ctx, walking, "steps") == ("cell", (step_cell_key(1, "name"),), None)
    closed = cost_review_profile(ctx.vocab, steps=2)
    assert ask(ctx, closed, "confirm") == ("rollups", ("process.all_roles",), None)
    assert ask(ctx, closed, "confirm", counters={"confirm_turns": 6}).keys == ("process.all_roles", "process.all_tools")
    closed["process"]["roles_confirmed"] = closed["process"]["tools_confirmed"] = True
    assert ask(ctx, closed, "review").kind == "wrap_up"
    context_proposal = apply_proposals(
        empty_profile(),
        ProposalDiff("d1", fields=(FieldProposal("process.trigger", "T", "t"),)),
        vocab=ctx.vocab,
        at=AT,
    ).profile
    assert ask(ctx, context_proposal, "context") == ("field", ("department",), None)


async def test_this_turn_names_the_target_and_last_question_records_it(ctx):
    """AC-14.41."""
    session = session_at(ctx, "boundaries", profile_with(ctx, "process.trigger"))
    llm = fake(EXTRACT=[{}], GUIDE=["Q?"])
    result = await turn(session, "hm", llm, ctx)
    system = llm.calls_of(CallType.GUIDE)[0].messages[0]["content"]
    this_turn = system.split("THIS TURN:\n", 1)[1].split("\n\n", 1)[0]
    assert "`process.end_result`" in this_turn
    assert this_turn.count("`process.") == 1
    assert result.session.last_question.focus == ["process.end_result"]


def test_proposal_groups(ctx):
    """AC-14.43."""
    six = ProposalDiff(
        "d1",
        fields=tuple(
            FieldProposal(k, "x", "q")
            for k in ("process.trigger", "process.end_result", "process.value_at_end", "process.business_pain")
        )
        + (
            FieldProposal("process.volume", {"count": 1, "period": "month"}, "q"),
            FieldProposal("process.process_owner", {"role": "Head"}, "q"),
        ),
    )
    base = profile_with(ctx)
    p = apply_proposals(base, six, vocab=ctx.vocab, at=AT).profile
    assert proposal_group(p, "boundaries", {}, vocab=ctx.vocab) == [
        "process.trigger",
        "process.end_result",
        "process.value_at_end",
        "process.business_pain",
    ]
    deferred = {"field_asks": {"process.trigger": 3}}
    assert "process.trigger" not in proposal_group(p, "boundaries", deferred, vocab=ctx.vocab)
    assert "process.trigger" in proposal_group(p, "review", deferred, vocab=ctx.vocab)
    assert "process.trigger" not in proposal_group(p, "review", {"field_asks": {"process.trigger": 5}}, vocab=ctx.vocab)
    steps = ProposalDiff("d1", steps=tuple(StepProposal((FieldProposal("name", f"S{i}", f"S{i}"),)) for i in range(5)))
    q = apply_proposals(profile_with(ctx, *BOUNDARIES, *MEASURE), steps, vocab=ctx.vocab, at=AT).profile
    assert proposal_group(q, "step_count", {}, vocab=ctx.vocab) == [step_cell_key(i, "name") for i in range(1, 6)]
    from app.services.process_discovery.profile.mutate import mark_cells_skipped

    skipped = mark_cells_skipped(q, [step_cell_key(1, "name")], vocab=ctx.vocab)
    assert step_cell_key(1, "name") not in proposal_group(skipped, "steps", {}, vocab=ctx.vocab)
