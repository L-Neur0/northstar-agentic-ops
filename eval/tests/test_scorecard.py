"""The scorecard: schema, Markdown from JSON, targets with deltas, the `latest` rule, exit codes (spec 24 §3.11; AC-24.23 to AC-24.25).

Why: the scorecard is what a person reads after a change; it must be the same facts as the JSON,
show every target with ✓ / ✗ / n/a and its delta, and fail the run for the right reasons only.
What: hand-built `PersonaScore` values through `build_scorecard` and `render_markdown`.
Must not: call a model.
"""

from __future__ import annotations

from typing import Any

from eval.evalkit.calibrate import Calibration
from eval.evalkit.score_behaviour import BehaviourScores
from eval.evalkit.score_efficiency import CurvePoint, EfficiencyScores
from eval.evalkit.score_labels import LabelScores
from eval.evalkit.scorecard import PersonaScore, Scorecard, build_scorecard, render_markdown, should_replace_latest

PASSING = Calibration(pairs=30, agreed=30, agreement=1.0, passed=True)


def persona_score(**changes: Any) -> PersonaScore:
    data: dict[str, Any] = {
        "id": "p01-cooperative",
        "version": 1,
        "kind": "cooperative",
        "status": "finished",
        "quality": 61 / 71,
        "quality_code": 0.5,
        "correct": 61,
        "total": 71,
        "labels": LabelScores(cluster=True, scope=True, steering=True, fit_hits=4, route_hits=4, routed_steps=5),
        "behaviour": BehaviourScores(turn_median_s=5.0, turn_max_s=20.0, finish_s=12.0),
        "efficiency": EfficiencyScores(
            messages=28, messages_to_finish=28, message_target=30, failed=False, efficiency=2.18, wasted=1
        ),
        "curve": [CurvePoint(n=n, quality=n / 28, score=n / 28, phase="steps") for n in range(1, 29)],
    }
    data.update(changes)
    return PersonaScore(**data)


def test_ac_24_23_the_json_validates_and_the_markdown_comes_from_it():
    card = build_scorecard("20261120-120000", [persona_score()], PASSING, None, mode="in-process")
    again = Scorecard.model_validate_json(card.model_dump_json())
    assert again == card and card.passed
    text = render_markdown(again)
    assert "PASS" in text and "86% (61/71)" in text and "2.18" in text
    assert "▁" in text and "█" in text and "28 (Finish): 100%" in text
    row = next(r for r in card.targets if r.name == "report quality")
    assert (row.value, row.target, row.status) == ("86%", "≥ 85%", "✓")
    assert next(r for r in card.targets if r.name == "turn time median (s)").status == "✓"


def test_ac_24_23_deltas_against_latest_and_new_versions():
    before = build_scorecard("a", [persona_score(quality=0.80, correct=57)], PASSING, None)
    now = build_scorecard("b", [persona_score()], PASSING, before)
    assert now.deltas["p01-cooperative"]["quality"] == "+6 pt"
    assert next(r for r in now.targets if r.name == "wasted turns").delta == "+0"
    newer = build_scorecard("c", [persona_score(version=2)], PASSING, before)
    assert newer.deltas["p01-cooperative"]["quality"] == "new"
    assert "new" in render_markdown(newer)


def test_ac_24_23_missing_data_is_n_a_and_does_not_fail():
    score = persona_score(behaviour=BehaviourScores())
    card = build_scorecard("r", [score], PASSING, None)
    row = next(r for r in card.targets if r.name == "turn time median (s)")
    assert row.status == "n/a" and card.passed


def test_ac_24_25_a_missed_target_fails_and_names_it():
    card = build_scorecard("r", [persona_score(quality=0.5, correct=35)], PASSING, None)
    assert not card.passed and any("report quality" in r for r in card.reasons)


def test_a_plateau_is_a_flag_not_a_failure():
    eff = EfficiencyScores(messages=28, messages_to_finish=28, message_target=30, failed=False, efficiency=2.0,
                           wasted=0, plateaus=[[3, 4, 5, 6, 7]])  # fmt: skip
    card = build_scorecard("r", [persona_score(efficiency=eff)], PASSING, None)
    assert card.passed and next(r for r in card.targets if r.name == "plateaus").status == "flag"


def test_ac_24_24_only_a_full_in_process_run_replaces_latest():
    assert should_replace_latest(quick=False, url=None, filtered=False)
    assert not should_replace_latest(quick=True, url=None, filtered=False)
    assert not should_replace_latest(quick=False, url="https://x", filtered=False)
    assert not should_replace_latest(quick=False, url=None, filtered=True)
