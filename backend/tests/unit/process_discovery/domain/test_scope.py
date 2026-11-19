"""Tests for the process-or-task rubric and the placement arithmetic (spec 12 §3.9).

Why: the model only reports five yes/no signals and a cluster with a confidence; code decides the
verdict and whether a cluster may be proposed (product rule 2). The arithmetic must hold whatever
the model returned, so it is tested without one.
What: every signal combination, literal-true parsing, the neutral verdict, the calibration rows,
the confidence and margin thresholds, and which codes may be put to the expert. Implements
AC-12.33 to AC-12.37.
"""

from itertools import product

import pytest

from app.services.process_discovery.domain import scope
from app.services.process_discovery.domain.taxonomy import UNKNOWN_CODE

KEYS = ("multi_role", "multi_system", "trigger_and_outcome", "recurring", "external_consumer")


def test_signals_are_the_five_in_rubric_order():
    """§3.9: five signals, each with a test and one plain question."""
    assert scope.SIGNAL_KEYS == KEYS
    assert tuple(k for k, _ in scope.SIGNALS) == KEYS
    assert all(test.strip() for _, test in scope.SIGNALS)
    assert set(scope.SIGNAL_QUESTIONS) == set(KEYS)
    assert scope.SIGNAL_QUESTIONS["external_consumer"] == "Who is waiting on the result once you are done?"


# --- AC-12.33 ----------------------------------------------------------------------------------


def expected_band(combo: tuple[bool, ...]) -> str:
    score = sum(combo)
    if score >= 4:
        return "process" if combo[4] else "borderline"
    return "borderline" if score == 3 else "task"


@pytest.mark.parametrize("combo", list(product([False, True], repeat=5)))
def test_every_combination_bands_as_documented(combo):
    """AC-12.33: all 32 combinations."""
    verdict = scope.build_scope_verdict(dict(zip(KEYS, combo, strict=True)))
    assert verdict["score"] == sum(combo)
    assert verdict["verdict"] == expected_band(combo)


def test_external_consumer_is_a_cap():
    """AC-12.33: four signals without `external_consumer` stay borderline."""
    assert scope.verdict_for(4, False) == "borderline"
    assert scope.verdict_for(4, True) == "process"
    assert scope.verdict_for(3, True) == "borderline"
    assert scope.verdict_for(2, True) == "task"


# --- AC-12.34 ----------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["true", "True", 1, 1.0, "yes", None, {}, [], "false"])
def test_only_a_literal_true_counts(value):
    """AC-12.34."""
    assert scope.normalise_signals({"multi_role": value})["multi_role"] is False
    assert scope.score_scope({"multi_role": value}) == 0


def test_normalise_signals_returns_exactly_the_five_keys():
    """AC-12.34."""
    out = scope.normalise_signals({"multi_role": True, "extra": True})
    assert tuple(out) == KEYS
    assert out["multi_role"] is True
    assert scope.normalise_signals("garbage") == dict.fromkeys(KEYS, False)


def test_neutral_scope_verdict():
    """AC-12.34: borderline, score 0, five false signals."""
    assert scope.neutral_scope_verdict() == {
        "verdict": "borderline",
        "score": 0,
        "signals": dict.fromkeys(KEYS, False),
        "reasoning": "",
    }


def test_reasoning_is_carried_and_failed_signals_are_named():
    """§3.9 rules 3–4."""
    verdict = scope.build_scope_verdict({"multi_role": True, "recurring": True, "reasoning": "  two people  "})
    assert verdict["reasoning"] == "two people"
    assert scope.failed_signals(verdict) == ("multi_system", "trigger_and_outcome", "external_consumer")
    assert scope.failed_signals({}) == KEYS


# --- AC-12.35 ----------------------------------------------------------------------------------


@pytest.mark.parametrize("row", scope.CALIBRATION, ids=lambda r: r[0])
def test_calibration_rows_score_to_their_verdict(row):
    """AC-12.35: the scorer agrees with every calibration example."""
    _, signals, verdict = row
    assert scope.build_scope_verdict(signals)["verdict"] == verdict


def test_calibration_has_the_documented_rows():
    """AC-12.35: the eight rows of §3.9, including the one-off migration."""
    assert len(scope.CALIBRATION) == 8
    rows = {d: (s, v) for d, s, v in scope.CALIBRATION}
    assert rows["I file my weekly timesheet"][1] == "task"
    assert rows["The monthly cost review"][1] == "process"
    signals, verdict = rows["We migrated the CRM last year"]
    built = scope.build_scope_verdict(signals)
    assert verdict == "process" and scope.is_one_off(built)
    assert not scope.is_one_off(scope.build_scope_verdict(rows["The monthly cost review"][0]))


# --- AC-12.36 ----------------------------------------------------------------------------------


def raw(code="FIN", confidence=0.9, runner_up=None, runner_up_confidence=None, **extra):
    data = {"code": code, "confidence": confidence, "rationale": " fits "}
    if runner_up is not None:
        data["runner_up"] = runner_up
    if runner_up_confidence is not None:
        data["runner_up_confidence"] = runner_up_confidence
    return data | extra


def test_low_confidence_falls_back_to_unknown(taxonomy):
    """AC-12.36: 0.55 → UNKNOWN, confidence 0, the raw number kept."""
    placement = scope.build_placement(raw(confidence=0.55), taxonomy)
    assert (placement["code"], placement["confidence"], placement["raw_confidence"]) == (UNKNOWN_CODE, 0.0, 0.55)
    assert placement["ambiguous"] is False
    survived = scope.build_placement(raw(confidence=0.60), taxonomy)
    assert (survived["code"], survived["confidence"]) == ("FIN", 0.60)
    assert survived["source"] == "model" and survived["rationale"] == "fits"


@pytest.mark.parametrize(
    ("top", "second", "ambiguous"),
    [(0.74, 0.60, True), (0.75, 0.60, False), (0.70, 0.55, False), (0.70, 0.56, True)],
)
def test_margin_is_strict(taxonomy, top, second, ambiguous):
    """AC-12.36: margin 0.14 → ambiguous, 0.15 → not (float noise ignored)."""
    placement = scope.build_placement(raw(confidence=top, runner_up="PRO", runner_up_confidence=second), taxonomy)
    assert placement["ambiguous"] is ambiguous


def test_no_runner_up_is_not_ambiguous(taxonomy):
    """AC-12.36: an absent runner-up has confidence 0."""
    placement = scope.build_placement(raw(confidence=0.7, runner_up_confidence=0.69), taxonomy)
    assert placement["runner_up"] == UNKNOWN_CODE
    assert placement["runner_up_confidence"] == 0.0
    assert placement["ambiguous"] is False


@pytest.mark.parametrize("code", ["Finance", "XYZ", None, 3, ""])
def test_unknown_codes(taxonomy, code):
    """AC-12.36: names, unknown and non-string codes are UNKNOWN."""
    assert scope.build_placement(raw(code=code), taxonomy)["code"] == UNKNOWN_CODE


def test_codes_are_normalised(taxonomy):
    """A lower-case code is still the code."""
    assert scope.build_placement(raw(code=" fin "), taxonomy)["code"] == "FIN"


@pytest.mark.parametrize(("value", "expected"), [(1.7, 1.0), (-0.2, 0.0), ("0.9", 0.0), (True, 0.0), (None, 0.0)])
def test_confidence_is_clamped(taxonomy, value, expected):
    """§3.9: clamped to [0, 1]; non-numbers and bools are 0."""
    assert scope.build_placement(raw(confidence=value), taxonomy)["raw_confidence"] == expected


@pytest.mark.parametrize("kwargs", [{"min_confidence": 1.2}, {"min_confidence": -0.1}, {"min_margin": 60}])
def test_thresholds_outside_the_unit_interval_raise(taxonomy, kwargs):
    """AC-12.36: never clamped."""
    with pytest.raises(ValueError):
        scope.build_placement(raw(), taxonomy, **kwargs)


def test_thresholds_can_be_passed_in(taxonomy):
    """Q3: spec 14 may pass settings values."""
    assert scope.build_placement(raw(confidence=0.65), taxonomy, min_confidence=0.7)["code"] == UNKNOWN_CODE


@pytest.mark.parametrize("garbage", [None, "nope", 3, []])
def test_unparseable_placement_is_unknown(taxonomy, garbage):
    """§3.9: the shape is always complete."""
    placement = scope.build_placement(garbage, taxonomy)
    assert placement["code"] == UNKNOWN_CODE
    assert set(placement) == set(scope.unknown_placement())


# --- AC-12.37 ----------------------------------------------------------------------------------


def test_keyword_placement():
    """AC-12.37: certain, no runner-up, marked as keyword."""
    placement = scope.keyword_placement("FIN")
    assert placement["confidence"] == 1.0
    assert placement["runner_up"] == UNKNOWN_CODE and placement["runner_up_confidence"] == 0.0
    assert placement["source"] == "keyword" and placement["ambiguous"] is False
    assert scope.proposable_code(placement) == "FIN"
    assert set(placement) == set(scope.unknown_placement())


@pytest.mark.parametrize(
    "placement",
    [None, {}, "FIN", 7, {"code": UNKNOWN_CODE}, {"code": "FIN", "ambiguous": True}, {"code": 3}],
)
def test_nothing_dubious_is_proposable(placement):
    """AC-12.37."""
    assert scope.proposable_code(placement) == ""


def test_a_clear_placement_is_proposable(taxonomy):
    """AC-12.37 (positive case)."""
    placement = scope.build_placement(raw(confidence=0.9, runner_up="PRO", runner_up_confidence=0.3), taxonomy)
    assert scope.proposable_code(placement) == "FIN"


@pytest.fixture
def taxonomy(nig_config):
    return nig_config.taxonomy
