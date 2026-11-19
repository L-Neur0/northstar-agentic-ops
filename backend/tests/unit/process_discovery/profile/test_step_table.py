"""Tests for the step table: index bounds, padding, the step count, resize, close and skipped cells (spec 13 §3.5).

Why: the table is where content was lost in the past (a count deleting described steps, a gap
cutting off content, a loop that could not close). What: AC-13.12 to AC-13.16, AC-13.27 to
AC-13.29 and AC-13.32, built with the real writers.
"""

import copy

from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.profile.mutate import apply_changes, assume_substep_count, mark_cells_skipped
from app.services.process_discovery.profile.proposals import FieldProposal, ProposalDiff, apply_proposals
from app.services.process_discovery.profile.scoring import score
from app.services.process_discovery.profile.shapes import empty_profile
from app.services.process_discovery.profile.verdicts import (
    expected_steps,
    grade,
    step_is_complete,
)

from .builders import AT, cost_review_profile, step_changes


def write(vocab, profile, changes):
    return apply_changes(profile, changes, vocab=vocab, at=AT)


def test_step_writes_are_one_based_and_bounded(vocab):
    """AC-13.12."""
    r = write(vocab, empty_profile(), {step_cell_key(1, "name"): "Export"})
    assert r.profile["process"]["substeps"][0]["name"] == "Export"
    four = write(vocab, empty_profile(), {"process.substep_count": 4}).profile
    assert write(vocab, four, {step_cell_key(5, "name"): "x"}).refused == [
        (step_cell_key(5, "name"), "index_out_of_range")
    ]
    assert write(vocab, empty_profile(), {step_cell_key(6, "name"): "x"}).refused == []
    assert write(vocab, empty_profile(), {step_cell_key(7, "name"): "x"}).refused == [
        (step_cell_key(7, "name"), "index_out_of_range")
    ]
    assert write(vocab, empty_profile(), {step_cell_key(0, "name"): "x"}).refused[0][1] == "index_out_of_range"


def test_a_gapped_table_pads_scores_and_keeps_the_far_step(vocab):
    """AC-13.13."""
    r = write(vocab, empty_profile(), step_changes(3))
    rows = r.profile["process"]["substeps"]
    assert len(rows) == 3 and rows[0]["name"] == "" and rows[2]["name"] == "Step 3"
    profile = cost_review_profile(vocab, steps=3, filled_steps=0)
    profile = write(vocab, profile, step_changes(3)).profile
    assert expected_steps(profile, vocab=vocab) == 3
    assert score(profile, vocab=vocab).total_points == 18 + 33
    profile = write(vocab, profile, {**step_changes(1), **step_changes(2)}).profile
    assert profile["process"]["substeps_complete"] is True
    assert profile["process"]["substeps"][2]["name"] == "Step 3"


def test_an_out_of_range_count_is_parked(vocab):
    """AC-13.14 (example 3)."""
    for bad in (0, 1, 7, 8, 13):
        r = write(vocab, empty_profile(), {"process.substep_count": bad})
        assert r.profile["process"]["substep_count"] is None
        assert r.profile["process"]["substep_count_rejected"] == bad
    parked = write(vocab, empty_profile(), {"process.substep_count": 13}).profile
    assert grade(parked, "process.substep_count", vocab=vocab).status == "invalid"
    assert score(parked, vocab=vocab).filled_points == 0
    fixed = write(vocab, parked, {"process.substep_count": 5}).profile
    assert fixed["process"]["substep_count"] == 5
    assert fixed["process"]["substep_count_rejected"] is None
    assert len(fixed["process"]["substeps"]) == 5


def test_resize(vocab):
    """AC-13.15."""
    five = write(vocab, empty_profile(), {"process.substep_count": 5}).profile
    assert len(five["process"]["substeps"]) == 5
    three = write(vocab, five, {"process.substep_count": 3}).profile
    assert len(three["process"]["substeps"]) == 3
    content = write(vocab, three, {step_cell_key(3, "name"): "Review"}).profile
    lowered = write(vocab, content, {"process.substep_count": 2}).profile
    assert lowered["process"]["substep_count"] == 3
    assert len(lowered["process"]["substeps"]) == 3
    stored = empty_profile()
    stored["process"]["substep_count"] = 1
    lifted = write(vocab, stored, {"process.trigger": "x"}).profile
    assert lifted["process"]["substep_count"] == 2
    six = write(vocab, empty_profile(), {"process.substep_count": 6, step_cell_key(6, "name"): "x"}).profile
    assert len(six["process"]["substeps"]) == 6


def test_closing_trims_the_count_to_what_was_described(vocab):
    """AC-13.16."""
    profile = cost_review_profile(vocab, steps=6, filled_steps=4)
    rows_5_6 = {
        **{step_cell_key(i, s): v for i in (5, 6) for s, v in (("roles", [{"none": True}]),)},
    }
    profile = write(vocab, profile, rows_5_6).profile
    skip = [
        step_cell_key(i, leaf)
        for i in (5, 6)
        for leaf in (
            "name",
            "goal",
            "activities",
            "owner",
            "systems",
            "data",
            "effort",
            "pain_points",
            "approvals",
            "exceptions",
        )
    ]
    closed = mark_cells_skipped(profile, skip, vocab=vocab)
    assert closed["process"]["substeps_complete"] is True
    assert closed["process"]["substep_count"] == 6  # rows 5 and 6 are started (roles: none)

    four = cost_review_profile(vocab, steps=6, filled_steps=4)
    skip_all = [
        step_cell_key(i, s)
        for i in (5, 6)
        for s in (
            "name",
            "goal",
            "activities",
            "roles",
            "owner",
            "systems",
            "data",
            "effort",
            "pain_points",
            "approvals",
            "exceptions",
        )
    ]
    trimmed = mark_cells_skipped(four, skip_all, vocab=vocab)
    assert trimmed["process"]["substeps_complete"] is True
    assert trimmed["process"]["substep_count"] == 4
    assert len(trimmed["process"]["substeps"]) == 4

    one = write(vocab, empty_profile(), {"process.substep_count": 2, **step_changes(1)}).profile
    skip_two = [
        step_cell_key(2, s)
        for s in (
            "name",
            "goal",
            "activities",
            "roles",
            "owner",
            "systems",
            "data",
            "effort",
            "pain_points",
            "approvals",
            "exceptions",
        )
    ]
    floor = mark_cells_skipped(one, skip_two, vocab=vocab)
    assert floor["process"]["substeps_complete"] is True
    assert floor["process"]["substep_count"] == 2


def test_skipped_cells_are_settled_but_unscored(vocab):
    """AC-13.27."""
    profile = cost_review_profile(vocab, steps=2, filled_steps=1)
    profile = write(vocab, profile, step_changes(2, leave_out=("goal",))).profile
    before = copy.deepcopy(profile)
    skipped = mark_cells_skipped(
        profile,
        [step_cell_key(2, "goal"), step_cell_key(2, "name"), step_cell_key(9, "goal"), step_cell_key(1, "bogus")],
        vocab=vocab,
    )
    assert profile == before
    row = skipped["process"]["substeps"][1]
    assert row["__skipped"] == ["goal"]
    assert row["goal"] == ""
    assert score(skipped, vocab=vocab).filled_points == score(profile, vocab=vocab).filled_points
    assert skipped["process"]["substeps_complete"] is True


def test_a_later_answer_lifts_the_skip(vocab):
    """AC-13.28."""
    profile = cost_review_profile(vocab, steps=2, filled_steps=1)
    profile = write(vocab, profile, step_changes(2, leave_out=("goal",))).profile
    skipped = mark_cells_skipped(profile, [step_cell_key(2, "goal")], vocab=vocab)
    answered = write(vocab, skipped, {step_cell_key(2, "goal"): "Done"}).profile
    assert answered["process"]["substeps"][1]["__skipped"] == []
    assert answered["process"]["substeps_complete"] is True


def test_assume_substep_count(vocab):
    """AC-13.29."""
    three = write(vocab, empty_profile(), {step_cell_key(3, "name"): "Review", "process.substep_count": 13}).profile
    before = copy.deepcopy(three)
    assumed = assume_substep_count(three, vocab=vocab, at=AT)
    assert three == before
    assert assumed["process"]["substep_count"] == 3
    assert assumed["process"]["substep_count_rejected"] is None
    assert assume_substep_count(empty_profile(), vocab=vocab, at=AT)["process"]["substep_count"] == 2
    counted = write(vocab, empty_profile(), {"process.substep_count": 5}).profile
    assert assume_substep_count(counted, vocab=vocab, at=AT) == counted


def test_row_completeness_ignores_s12_and_honours_proposals_and_skips(vocab):
    """AC-13.32."""
    full = write(vocab, empty_profile(), step_changes(1, leave_out=("handover",))).profile
    assert step_is_complete(full["process"]["substeps"][0], vocab=vocab)
    open_goal = write(
        vocab, empty_profile(), {"process.substep_count": 2, **step_changes(1, leave_out=("goal",))}
    ).profile
    diff = ProposalDiff("d1", step_cells=(FieldProposal(step_cell_key(1, "goal"), "Done", "it is done"),))
    proposed = apply_proposals(open_goal, diff, vocab=vocab, at=AT).profile
    assert not step_is_complete(proposed["process"]["substeps"][0], vocab=vocab)
    skipped = mark_cells_skipped(proposed, [step_cell_key(1, "goal")], vocab=vocab)
    assert step_is_complete(skipped["process"]["substeps"][0], vocab=vocab)
