"""Tests for completeness and the *Finish* check (spec 13 §3.9–§3.10; AC-13.45 to AC-13.49).

Why: the guide, the API and the screen read the same two answers; the numbers must be exactly the
ones in the spec tables. What: the §3.9 table, the 0.80 gate, the order of the blocking reasons and
the advisory `looks_like_task` table.
"""

import pytest

from app.services.process_discovery.domain.field_spec import STEP_SPECS, step_cell_key
from app.services.process_discovery.profile.mutate import apply_changes, confirm_rollup, mark_cells_skipped
from app.services.process_discovery.profile.scoring import FINISH_BLOCKS, finish_check, score
from app.services.process_discovery.profile.shapes import empty_profile
from app.services.process_discovery.profile.verdicts import expected_steps

from .builders import AT, context_changes, cost_review_profile, step_changes

SCORED = [s.key for s in STEP_SPECS if s.weight]


def write(vocab, profile, changes):
    return apply_changes(profile, changes, vocab=vocab, at=AT).profile


def test_the_score_table(vocab):
    """AC-13.45."""
    assert tuple(score(empty_profile(), vocab=vocab)) == (0.0, 0, 18)
    assert tuple(score(write(vocab, empty_profile(), context_changes()), vocab=vocab)) == (0.1667, 3, 18)
    assert tuple(score(cost_review_profile(vocab, steps=4, filled_steps=0), vocab=vocab)) == (0.2903, 18, 62)
    partial = cost_review_profile(vocab, steps=4, filled_steps=3)
    six_cells = {
        step_cell_key(4, leaf): v
        for leaf, v in (
            ("name", "Send"),
            ("goal", "Sent"),
            ("owner", "Clerk"),
            ("systems", ["Mail"]),
            ("pain_points", ["slow"]),
            ("activities", ["send"]),
        )
    }
    partial = write(vocab, partial, six_cells)
    assert tuple(score(partial, vocab=vocab)) == (0.9194, 57, 62)
    six = cost_review_profile(vocab, steps=6, filled_steps=4)
    six = write(
        vocab,
        six,
        {
            step_cell_key(5, leaf): v
            for leaf, v in (
                ("name", "Five"),
                ("goal", "G"),
                ("owner", "O"),
                ("systems", ["S"]),
                ("pain_points", ["p"]),
                ("activities", ["a"]),
            )
        },
    )
    assert tuple(score(six, vocab=vocab)) == (0.8095, 68, 84)


def test_double_weights_and_zero_for_non_counting_values(vocab):
    """AC-13.45: P12 and P13 weigh 2; partial and invalid add 0."""
    base = write(vocab, empty_profile(), {"process.baseline_metric": {"value": "4", "unit": "days"}})
    assert score(base, vocab=vocab).filled_points == 2
    invalid = write(vocab, base, {"process.target_metric": {"value": "2", "unit": "hours"}})
    assert score(invalid, vocab=vocab).filled_points == 2
    partial = write(vocab, empty_profile(), {"process.volume": {"count": 3}})
    assert score(partial, vocab=vocab).filled_points == 0


def test_expected_steps(vocab):
    """AC-13.46."""
    rows = write(vocab, empty_profile(), step_changes(2))
    assert expected_steps(rows, vocab=vocab) == 0
    assert expected_steps(write(vocab, rows, {"process.substep_count": 3}), vocab=vocab) == 3


def finished(vocab, steps, skip_cells):
    profile = cost_review_profile(vocab, steps=steps)
    keys = [step_cell_key(i, leaf) for i in range(1, steps + 1) for leaf in SCORED][:skip_cells]
    blanked = profile
    for key in keys:
        idx = int(key.split("[")[1].split("]")[0]) - 1
        leaf = key.rsplit(".", 1)[1]
        blanked["process"]["substeps"][idx][leaf] = (
            []
            if isinstance(blanked["process"]["substeps"][idx][leaf], list)
            else (
                {k: ([] if isinstance(v, list) else "") for k, v in blanked["process"]["substeps"][idx][leaf].items()}
                if isinstance(blanked["process"]["substeps"][idx][leaf], dict)
                else ""
            )
        )
    blanked = mark_cells_skipped(blanked, keys, vocab=vocab)
    return confirm_rollup(confirm_rollup(blanked, "roles", vocab=vocab), "systems", vocab=vocab)


def test_the_gate(vocab):
    """AC-13.47."""
    ready = finished(vocab, 4, 12)
    assert score(ready, vocab=vocab)[1:] == (50, 62)
    assert finish_check(ready, vocab=vocab) == (True, None, False)
    below = finished(vocab, 4, 13)
    assert score(below, vocab=vocab)[1:] == (49, 62)
    assert finish_check(below, vocab=vocab).blocked_by == "below_gate"
    exact = finished(vocab, 2, 8)
    assert score(exact, vocab=vocab).value == 0.8
    assert finish_check(exact, vocab=vocab).ready


def test_blocking_reasons_in_order(vocab):
    """AC-13.48."""
    ready = finished(vocab, 4, 0)
    assert finish_check(ready, vocab=vocab).ready
    seen = []
    for flag in ("substeps_complete", "roles_confirmed", "tools_confirmed"):
        ready["process"][flag] = False
        seen.append(finish_check(ready, vocab=vocab).blocked_by)
        ready["process"][flag] = True
    assert seen == list(FINISH_BLOCKS[1:])
    low = cost_review_profile(vocab, steps=4, filled_steps=1)
    assert finish_check(low, vocab=vocab).blocked_by == "below_gate"


def verdict(label):
    return {"verdict": label, "score": 3, "signals": {}, "reasoning": ""}


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ({"verdict": verdict("process"), "overridden": True}, False),
        ({"verdict": verdict("task")}, True),
        ({"verdict": verdict("borderline"), "widening_asked": True}, True),
        ({"verdict": verdict("borderline"), "widening_asked": False}, False),
        ({"verdict": None, "overridden": True}, True),
        ({"verdict": None}, False),
        (None, False),
    ],
)
def test_looks_like_task_never_blocks(vocab, scope, expected):
    """AC-13.49."""
    ready = finished(vocab, 4, 0)
    check = finish_check(ready, vocab=vocab, scope=scope)
    assert check.looks_like_task is expected
    assert (check.ready, check.blocked_by) == (True, None)
