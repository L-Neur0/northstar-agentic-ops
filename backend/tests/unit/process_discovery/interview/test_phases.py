"""Tests for the phase machine and for changes made outside a turn (spec 14 §3.3, §3.12; AC-14.30, AC-14.32).

Why: the phase decides what the guide asks about; collecting phases must never move backwards, the
tail must step back when the walk or a list reopens, and a button press must leave the session
exactly where a turn would. What: `advance_phase` rules and `after_action` after a Confirm button,
the picker, ✓/✎ on proposals and a document read.
"""

from app.models.process_discovery_schemas import Profile
from app.services.process_discovery.domain.field_spec import PHASE_ORDER, step_cell_key
from app.services.process_discovery.interview.phases import advance_phase, phase_from_state
from app.services.process_discovery.interview.turn import after_action
from app.services.process_discovery.profile.mutate import apply_changes, confirm_rollup, set_cluster
from app.services.process_discovery.profile.proposals import (
    FieldProposal,
    ProposalDiff,
    apply_proposals,
    confirm_proposals,
)
from app.services.process_discovery.profile.scoring import score
from app.services.process_discovery.profile.shapes import empty_profile

from ..profile.builders import AT, cost_review_profile
from .sessions import BOUNDARIES, NAME, profile_with, session_at

NO_COUNTERS: dict = {}


def test_collecting_phases_never_move_backwards(ctx):
    """AC-14.30."""
    for phase in PHASE_ORDER[:5]:
        assert PHASE_ORDER.index(
            advance_phase(empty_profile(), phase, NO_COUNTERS, vocab=ctx.vocab)
        ) >= PHASE_ORDER.index(phase)
    assert advance_phase(empty_profile(), "context", NO_COUNTERS, vocab=ctx.vocab) == "context"
    assert advance_phase(cost_review_profile(ctx.vocab, steps=2), "context", NO_COUNTERS, vocab=ctx.vocab) == "review"


def test_terminals_never_change(ctx):
    """AC-14.30."""
    for phase in ("finished", "no_candidate"):
        assert advance_phase(empty_profile(), phase, NO_COUNTERS, vocab=ctx.vocab) == phase


def test_the_tail_steps_back_but_never_into_a_collecting_phase(ctx):
    """AC-14.30."""
    closed = cost_review_profile(ctx.vocab, steps=2)
    confirmed = confirm_rollup(confirm_rollup(closed, "roles", vocab=ctx.vocab), "systems", vocab=ctx.vocab)
    assert advance_phase(confirmed, "review", NO_COUNTERS, vocab=ctx.vocab) == "review"
    dropped = apply_changes(confirmed, {step_cell_key(1, "roles"): ["Auditor"]}, vocab=ctx.vocab, at=AT).profile
    assert advance_phase(dropped, "review", NO_COUNTERS, vocab=ctx.vocab) == "review"  # no confirm (§3.20 O10)
    reopened = dict(confirmed)
    reopened["process"] = {**confirmed["process"], "substeps_complete": False}
    assert advance_phase(reopened, "review", NO_COUNTERS, vocab=ctx.vocab) == "steps"
    assert advance_phase(reopened, "confirm", NO_COUNTERS, vocab=ctx.vocab) == "steps"
    gap = dict(confirmed)
    gap["process"] = {**confirmed["process"], "trigger": ""}
    assert phase_from_state(gap, NO_COUNTERS, vocab=ctx.vocab) == "boundaries"
    assert advance_phase(gap, "review", NO_COUNTERS, vocab=ctx.vocab) == "review"


def test_after_action_matches_a_turn(ctx):
    """AC-14.32: Confirm buttons; a session that deferred a phase reaches review after the last confirmation."""
    profile = cost_review_profile(ctx.vocab, steps=2)
    profile["process"]["business_pain"] = ""
    counters = {"field_asks": {"process.business_pain": 3}}
    session = session_at(ctx, "confirm", profile, counters=counters)
    for target in ("roles", "systems"):
        confirmed = confirm_rollup(session.profile.model_dump(by_alias=True), target, vocab=ctx.vocab)
        session = after_action(session.model_copy(update={"profile": Profile.model_validate(confirmed)}), ctx=ctx)
    assert session.phase.value == "review"
    assert (
        session.score.filled_points == score(session.profile.model_dump(by_alias=True), vocab=ctx.vocab).filled_points
    )


def test_after_the_picker_the_proposal_is_cleared(ctx):
    """AC-14.32."""
    from app.services.process_discovery.domain.scope import keyword_placement

    profile = profile_with(ctx)
    profile["process"]["cluster"] = {"code": "", "name": "", "decided_by": ""}
    profile["__meta"].pop("process.cluster")
    session = session_at(
        ctx, "find", profile, placement={"proposal": keyword_placement("FIN"), "placed_for": "old name"}
    )
    picked = set_cluster(profile, "PRO", decided_by="picker", vocab=ctx.vocab, at=AT)
    after = after_action(session.model_copy(update={"profile": Profile.model_validate(picked)}), ctx=ctx)
    assert after.placement.proposal is None
    assert after.placement.placed_for == NAME
    assert after.phase.value == "boundaries"


def test_after_proposals_and_a_document_read(ctx):
    """AC-14.32: ✓ on a proposal and a document read recompute the score and the phase."""
    profile = profile_with(ctx, *BOUNDARIES[:3])
    session = session_at(ctx, "boundaries", profile)
    diff = ProposalDiff("d1", fields=(FieldProposal("process.business_pain", "Chasing", "chasing people"),))
    read = apply_proposals(profile, diff, vocab=ctx.vocab, at=AT).profile
    after_read = after_action(session.model_copy(update={"profile": Profile.model_validate(read)}), ctx=ctx)
    assert after_read.phase.value == "boundaries"
    assert after_read.score == session.score.model_copy(update=dict(score(read, vocab=ctx.vocab)._asdict()))
    ticked = confirm_proposals(read, ["process.business_pain"], vocab=ctx.vocab, at=AT).profile
    after_tick = after_action(after_read.model_copy(update={"profile": Profile.model_validate(ticked)}), ctx=ctx)
    assert after_tick.phase.value == "measure"
    assert after_tick.score.filled_points == after_read.score.filled_points + 1
