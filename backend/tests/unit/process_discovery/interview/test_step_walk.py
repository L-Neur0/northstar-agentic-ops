"""Tests for the step walk and its cell limits (spec 14 §3.5; AC-14.24 to AC-14.26).

Why: one cell the expert cannot answer must never hold the walk; the none-able cells get the none
row, the others are skipped (settled for the walk, missing for the score), and a proposal that is
never confirmed stays visible. What: example 1, a skipped goal, the hand-over rule, and a step-cell
proposal past its limit.
"""

from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.interview.phases import step_focus
from app.services.process_discovery.profile.mutate import apply_changes
from app.services.process_discovery.profile.proposals import FieldProposal, ProposalDiff, apply_proposals
from app.services.process_discovery.profile.scoring import score

from ..profile.builders import AT, step_changes
from .helpers import play
from .sessions import BOUNDARIES, MEASURE, profile_with, session_at


def walk(ctx, steps=3, leave_out=()):
    profile = profile_with(ctx, *BOUNDARIES, *MEASURE, steps=steps)
    changes = {**step_changes(1), **step_changes(2, leave_out=leave_out)}
    return apply_changes(profile, changes, vocab=ctx.vocab, at=AT).profile


async def test_example_1_approvals_get_the_none_row(ctx):
    """AC-14.24."""
    key = step_cell_key(2, "approvals")
    session = session_at(ctx, "steps", walk(ctx, leave_out=("approvals",)), last_question={"focus": [key]})
    results = await play(session, [("it depends", {})] * 3, ctx)
    final = results[-1].session
    assert final.counters.cell_asks[key] == 3
    assert final.profile.process.substeps[1].approvals[0].model_dump() == {"none": True}
    assert final.last_question.focus == [step_cell_key(3, "name")]


async def test_a_goal_asked_three_times_is_skipped_and_unscored(ctx):
    """AC-14.24."""
    key = step_cell_key(2, "goal")
    session = session_at(ctx, "steps", walk(ctx, leave_out=("goal",)), last_question={"focus": [key]})
    results = await play(session, [("hard to say", {})] * 3, ctx)
    final = results[-1].session.profile
    assert final.process.substeps[1].skipped == ["goal"]
    assert final.process.substeps[1].goal == ""
    dumped = final.model_dump(by_alias=True)
    full = apply_changes(dumped, {key: "Done"}, vocab=ctx.vocab, at=AT).profile
    assert score(full, vocab=ctx.vocab).filled_points == score(dumped, vocab=ctx.vocab).filled_points + 1


async def test_the_hand_over_is_asked_once_and_never_for_the_last_step(ctx):
    """AC-14.25."""
    profile = apply_changes(
        profile_with(ctx, *BOUNDARIES, *MEASURE, steps=2),
        step_changes(1, leave_out=("handover",)),
        vocab=ctx.vocab,
        at=AT,
    ).profile
    handover = step_cell_key(1, "handover")
    assert step_focus(profile, vocab=ctx.vocab) == handover
    session = session_at(ctx, "steps", profile, last_question={"focus": [handover]})
    results = await play(session, [("not sure", {})], ctx)
    after = results[-1].session
    assert after.profile.process.substeps[0].skipped == ["handover"]
    assert after.last_question.focus == [step_cell_key(2, "name")]
    last = apply_changes(
        profile, {handover: "mail", **step_changes(2, leave_out=("handover",))}, vocab=ctx.vocab, at=AT
    ).profile
    assert last["process"]["substeps_complete"] is True
    assert step_focus(last, vocab=ctx.vocab) is None


async def test_an_unconfirmed_step_proposal_is_skipped_and_stays_a_proposal(ctx):
    """AC-14.26."""
    profile = walk(ctx, steps=2, leave_out=("systems",))
    key = step_cell_key(2, "systems")
    profile = apply_proposals(
        profile, ProposalDiff("d1", step_cells=(FieldProposal(key, ["Excel"], "in Excel"),)), vocab=ctx.vocab, at=AT
    ).profile
    session = session_at(ctx, "steps", profile, last_question={"proposals": [key]})
    results = await play(session, [("let me check that later", {})] * 3, ctx)
    row = results[-1].session.profile.process.substeps[1]
    assert row.skipped == ["systems"]
    assert row.systems == ["Excel"]
    assert row.meta["systems"].status == "proposed"


def test_the_walk_does_not_ask_a_proposed_cell_as_a_field(ctx):
    """AC-14.26: a proposed cell is presented as a proposal, so the walk's next field is the following open cell.

    Added after a mutation check found that the "proposed" test used by the walk had no test of its own.
    """
    profile = walk(ctx, steps=2, leave_out=("systems", "data"))
    systems = step_cell_key(2, "systems")
    profile = apply_proposals(
        profile, ProposalDiff("d1", step_cells=(FieldProposal(systems, ["Excel"], "in Excel"),)), vocab=ctx.vocab, at=AT
    ).profile
    assert step_focus(profile, vocab=ctx.vocab) == step_cell_key(2, "data")
