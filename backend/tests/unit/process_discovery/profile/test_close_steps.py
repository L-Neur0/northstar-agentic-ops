"""Closing the step walk on request: "No further steps" (spec 13 §3.5, spec 23 AC-23.51; AC-13.55, AC-13.56).

Why: an expert who declared six steps and described four has a four-step process; the button must
close the walk and lower the count to what was really described, or the score would stay out of
six and Finish would never open. What: `close_steps` raises `substeps_complete`, trims the count
to the last started row (never below 2), drops the empty rows after it, and rebuilds the roll-ups.
It never deletes a described step and never touches the confirmations of the lists.
"""

from app.services.process_discovery.profile.mutate import apply_changes, close_steps
from app.services.process_discovery.profile.shapes import normalized_profile

from .builders import AT, context_changes, cost_review_profile, process_changes, step_changes


def test_closing_trims_the_count_to_the_last_started_step(vocab):
    """AC-13.55: declared 6, described 4 → closed with 4 steps, rows 5-6 removed."""
    profile = cost_review_profile(vocab, steps=6, filled_steps=4)
    closed = close_steps(profile, vocab=vocab)
    proc = closed["process"]
    assert proc["substeps_complete"] is True
    assert proc["substep_count"] == 4
    assert len(proc["substeps"]) == 4
    assert profile["process"]["substep_count"] == 6  # input not mutated


def test_closing_never_goes_below_two_steps(vocab):
    """AC-13.56: one described step still leaves a count of 2."""
    profile = cost_review_profile(vocab, steps=4, filled_steps=1)
    closed = close_steps(profile, vocab=vocab)
    assert closed["process"]["substep_count"] == 2
    assert closed["process"]["substeps_complete"] is True


def test_closing_keeps_a_partly_described_step(vocab):
    """AC-13.55: a started but incomplete row counts as started and is kept."""
    profile = cost_review_profile(vocab, steps=5, filled_steps=3)
    profile = apply_changes(
        profile, step_changes(4, leave_out=("goal", "systems", "effort")), vocab=vocab, at=AT
    ).profile
    closed = close_steps(profile, vocab=vocab)
    assert closed["process"]["substep_count"] == 4
    assert closed["process"]["substeps"][3]["name"]


def test_closing_an_empty_table_only_raises_the_flag(vocab):
    """With no started row there is nothing to trim; the count is left as it is."""
    profile = apply_changes(
        normalized_profile(None), {**context_changes(), **process_changes(3)}, vocab=vocab, at=AT
    ).profile
    closed = close_steps(profile, vocab=vocab)
    assert closed["process"]["substeps_complete"] is True
    assert closed["process"]["substep_count"] == profile["process"]["substep_count"]
