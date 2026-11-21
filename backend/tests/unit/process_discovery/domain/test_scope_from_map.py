"""Tests for refreshing the scope verdict from the mapped steps (spec 12 §3.13, M1-M5).

Why: scope was judged once, from one sentence, before any step was mapped; in evaluation run
20261121-084902 a map with 2 roles and 3 systems still ended `borderline`. Facts in the map beat a
first impression, and code decides (product rule 2).
What: `refresh_scope_from_map` turns multi_role / multi_system on from the roll-ups, never off,
re-bands with the unchanged thresholds, and marks what changed.
Must not: call a model or read the profile itself (the caller passes the roll-ups).
Covers AC-12.60.
"""

from __future__ import annotations

from app.services.process_discovery.domain import scope

FIRST = scope.build_scope_verdict(
    {
        "multi_role": False,
        "multi_system": False,
        "trigger_and_outcome": True,
        "recurring": True,
        "external_consumer": True,
        "reasoning": "One specialist does it.",
    }
)


def test_ac_12_60_map_turns_signals_on_and_rebands() -> None:
    """AC-12.60: 2 roles and 3 systems lift a borderline (F, F, T, T, T) to process, score 5."""
    assert FIRST["verdict"] == "borderline"
    out = scope.refresh_scope_from_map(
        FIRST,
        roles=["Talent acquisition specialist", "hiring manager", "  Hiring  Manager "],
        systems=["Recruiting system", "Excel", "E-mail"],
    )
    assert out["verdict"] == "process" and out["score"] == 5
    assert out["signals"]["multi_role"] and out["signals"]["multi_system"]
    assert out["refreshed"] is True
    assert out["reasoning"] == "One specialist does it. Updated from the map: 2 roles, 3 systems."
    assert FIRST["verdict"] == "borderline"  # the input is not changed


def test_ac_12_60_small_map_leaves_the_verdict_unchanged() -> None:
    """AC-12.60: 1 role and 1 system change nothing."""
    out = scope.refresh_scope_from_map(FIRST, roles=["Recruiter"], systems=["Excel", "excel"])
    assert out == FIRST


def test_ac_12_60_never_turns_a_signal_off() -> None:
    """AC-12.60 / M2: a signal already true stays true with an empty map."""
    full = scope.build_scope_verdict(dict.fromkeys(scope.SIGNAL_KEYS, True))
    assert scope.refresh_scope_from_map(full, roles=[], systems=[]) == full


def test_ac_12_60_neutral_verdict_is_refreshed_too() -> None:
    """M5: a failed CLASSIFY (score 0) is refreshed the same way."""
    out = scope.refresh_scope_from_map(scope.neutral_scope_verdict(), roles=["a", "b"], systems=["x", "y"])
    assert out["score"] == 2 and out["verdict"] == "task" and out["refreshed"] is True
