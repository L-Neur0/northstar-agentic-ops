"""Tests for the shared profile renderer (spec 14 §3.9; AC-14.61, AC-14.62).

Why: every model call sees the profile through `render_profile`; a proposal rendered like an answer
would be taken for one, and internals in the text would leak meta data into prompts.
What: the proposal suffixes and the absence of internals, on a profile holding all of them.
"""

from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.interview.prompts.common import render_profile
from app.services.process_discovery.profile.mutate import apply_changes, mark_cells_skipped
from app.services.process_discovery.profile.proposals import (
    FieldProposal,
    ProposalDiff,
    apply_proposals,
    confirm_proposals,
    propose_from_idea,
)
from app.services.process_discovery.profile.shapes import empty_profile

from ..profile.builders import AT

DOCS = [{"id": "d1", "name": "Cost review procedure.docx"}]


def test_proposals_are_marked(ctx):
    """AC-14.61."""
    diff = ProposalDiff(
        "d1", fields=(FieldProposal("process.trigger", "Month-end close", "starts at month-end close"),)
    )
    proposed = apply_proposals(empty_profile(), diff, vocab=ctx.vocab, at=AT).profile
    assert "Trigger: Month-end close (proposed, from Cost review procedure.docx)" in render_profile(
        proposed, vocab=ctx.vocab, documents=DOCS
    )
    confirmed = confirm_proposals(proposed, ["process.trigger"], vocab=ctx.vocab, at=AT).profile
    text = render_profile(confirmed, vocab=ctx.vocab, documents=DOCS)
    assert "Trigger: Month-end close\n" in text and "proposed" not in text
    idea = propose_from_idea(empty_profile(), "Monthly cost review", "the review", at=AT)
    assert "Monthly cost review (proposed, not yet confirmed)" in render_profile(idea, vocab=ctx.vocab)


def test_no_internals_reach_the_text(ctx):
    """AC-14.62."""
    p = apply_changes(
        empty_profile(),
        {"process.substep_count": 13, step_cell_key(1, "roles"): [{"none": True}]},
        vocab=ctx.vocab,
        at=AT,
    ).profile
    p = mark_cells_skipped(p, [step_cell_key(1, "goal")], vocab=ctx.vocab)
    p = apply_proposals(
        p, ProposalDiff("d1", fields=(FieldProposal("process.trigger", "T", "t"),)), vocab=ctx.vocab, at=AT
    ).profile
    p["process"]["roles_confirmed"] = True
    text = render_profile(p, vocab=ctx.vocab, documents=DOCS)
    for internal in (
        "__meta",
        "__skipped",
        "documentId",
        "substep_count_rejected",
        "substeps_complete",
        "roles_confirmed",
        "tools_confirmed",
    ):
        assert internal not in text
    assert "Roles involved: none (confirmed by the expert)" in text
