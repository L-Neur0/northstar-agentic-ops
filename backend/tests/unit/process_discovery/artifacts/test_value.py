"""Tests for hours a year per step, in total and per opportunity (spec 19 §3.2, hours only).

Why: the report's hours must be exactly the worked example's (342 h for the EU cost review), must
show their formula, and must say "incomplete" with the field to fix instead of guessing. While the
value method is parked (R5) no money, rate or saving share may appear anywhere.
What: `compute_value` on the shared EU fixture with o1–o4, with an unreadable effort, an unreadable
volume, a per-run versus a periodic step, the formula text, determinism and the parked fields.
Must not: test the parser's grammar (that is `domain/test_value_parse.py`) or call a model.
Covers AC-19.6, AC-19.10 to AC-19.12, AC-19.15, AC-19.16, AC-19.38 (value), AC-19.39, AC-19.40;
AC-19.7, 19.8, 19.9, 19.13, 19.14 are parked (R5) and skipped with that reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.models.process_discovery_schemas import Opportunity
from app.services.process_discovery.artifacts.value import compute_value
from tests.fixtures.assessment.profiles import load_profile, nig_config
from tests.fixtures.assessment_19.cases import eu_opportunities

PARKED_REASON = "parked until the value method is decided (refinement R5)"


def _value(profile=None, opportunities=None):
    return compute_value(
        load_profile("eu") if profile is None else profile,
        eu_opportunities() if opportunities is None else opportunities,
        nig_config().rates,
    )


def _set_effort(profile, step: int, **effort: str):
    profile["process"]["substeps"][step - 1]["effort"].update(effort)
    return profile


def test_ac_19_6_eu_hours() -> None:
    """AC-19.6: 342 h; steps 72, 96, 72, 30, 72; o1 168, o2 72, o3 30, o4 72; parked fields None."""
    value = _value()
    assert value.complete and value.missing == []
    assert value.hours_per_year == 342
    assert value.runs_per_year == 12
    assert [s.hours_per_year for s in value.steps] == [72, 96, 72, 30, 72]
    assert [s.name for s in value.steps][1] == "Consolidate into the master file"
    assert {o.id: o.step_hours for o in value.opportunities} == {"o1": 168, "o2": 72, "o3": 30, "o4": 72}
    assert (value.cost_today, value.hours_freed, value.value_conservative, value.value_expected) == (None,) * 4


def test_ac_19_10_periodic_ignores_volume_per_run_uses_it() -> None:
    """AC-19.10: "10 times a month" = 120 runs whatever the volume; "each time" = the process runs."""
    profile = load_profile("eu")
    profile["process"]["volume"] = {"count": 2, "period": "week", "raw": ""}
    value = _value(profile)
    assert value.steps[3].runs_per_year == 120
    assert value.steps[1].runs_per_year == 100  # each time × 2 a week × 50 weeks
    assert value.steps[1].hours_per_year == 800


def test_ac_19_11_unreadable_duration() -> None:
    """AC-19.11: step 4 "a while" → incomplete, totals None, the field to fix and a quoting problem."""
    value = _value(_set_effort(load_profile("eu"), 4, duration="a while"))
    assert value.complete is False
    assert value.hours_per_year is None
    assert value.missing == ["process.substeps[4].effort"]
    assert value.problems == ['Effort of step 4 ("a while") could not be read as a duration.']
    assert value.steps[3].problem == value.problems[0]
    assert [s.hours_per_year for s in value.steps] == [72, 96, 72, None, 72]
    assert {o.id: o.step_hours for o in value.opportunities}["o3"] is None
    assert {o.id: o.step_hours for o in value.opportunities}["o1"] == 168


def test_ac_19_11_unreadable_frequency_is_named() -> None:
    value = _value(_set_effort(load_profile("eu"), 3, frequency="when needed"))
    assert value.missing == ["process.substeps[3].effort"]
    assert "could not be read as a frequency" in value.problems[0]


def test_ac_19_12_unreadable_volume() -> None:
    """AC-19.12: a per-run step with an unreadable volume names `process.volume`; periodic-only is complete."""
    profile = load_profile("eu")
    profile["process"]["volume"] = {"count": None, "period": "", "raw": "it depends"}
    value = _value(profile)
    assert "process.volume" in value.missing
    assert value.steps[1].hours_per_year is None and value.runs_per_year is None
    _set_effort(profile, 2, frequency="monthly")
    assert _value(profile).complete is True


def test_ac_19_12_proposed_volume_is_not_used() -> None:
    profile = load_profile("eu")
    profile["__meta"]["process.volume"] = {
        "source": "document", "status": "proposed", "documentId": "d1", "quote": "monthly", "at": "t"
    }  # fmt: skip
    assert "process.volume" in _value(profile).missing


def test_ac_19_15_formula_lines() -> None:
    """AC-19.15: every number has a formula; step 4's line is exact."""
    value = _value()
    assert (
        'Step 4 Chase explanations: 0.25 h ("15 minutes") × 120 runs a year ("10 times a month") = 30 h'
        in value.formulas
    )
    assert any(f.startswith("Step 2 Consolidate into the master file: 8 h") for f in value.formulas)
    assert "Hours a year: 72 + 96 + 72 + 30 + 72 = 342 h" in value.formulas
    assert "Opportunity o1 (steps 1, 2): 72 + 96 = 168 h" in value.formulas
    assert any(f.startswith("Process runs a year:") for f in value.formulas)
    assert len([f for f in value.formulas if f.startswith("Step ")]) == 5


def test_ac_19_4_midpoint_assumption_listed() -> None:
    """AC-19.4 (value half): a range read anywhere adds the midpoint assumption."""
    assert len(_value().assumptions) == 1
    value = _value(_set_effort(load_profile("eu"), 1, duration="5-7 hours"))
    assert value.steps[0].hours_per_year == 72
    assert any("midpoint" in a for a in value.assumptions)


def test_ac_19_16_deterministic() -> None:
    """AC-19.16: the same inputs give the same result."""
    assert _value() == _value()


def test_ac_19_39_parked_fields_and_wording() -> None:
    """AC-19.39: every parked field is None and no line mentions money, rate, realisation or share."""
    value = _value()
    for step in value.steps:
        assert (step.rate, step.share, step.hours_freed, step.value_conservative, step.value_expected) == (None,) * 5
    for opp in value.opportunities:
        assert (opp.hours_freed, opp.value_conservative, opp.value_expected) == (None,) * 3
    for line in value.formulas + value.assumptions:
        lowered = line.casefold()
        assert not any(w in lowered for w in ("€", "$", "eur", "rate", "realisation", "saving share"))


def test_ac_19_40_opportunity_step_hours() -> None:
    """AC-19.40: steps de-duplicated; whole process = 342; a step without hours → None."""

    def opp(substeps: list[int]) -> Opportunity:
        return Opportunity.model_validate(
            {"id": "x", "title": "t", "substeps": substeps, "type": "workflow", "impact": "low", "feasibility": "low"}
        )

    assert _value(opportunities=[opp([1, 1, 2])]).opportunities[0].step_hours == 168
    assert _value(opportunities=[opp([])]).opportunities[0].step_hours == 342
    broken = _set_effort(load_profile("eu"), 2, duration="a while")
    assert _value(broken, [opp([2, 3])]).opportunities[0].step_hours is None


def test_ac_19_38_value_is_pure() -> None:
    """AC-19.38 (value): imports nothing that does I/O and makes no model call."""
    path = Path(__file__).resolve().parents[4] / "app/services/process_discovery/artifacts/value.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any(m.endswith("llm") or m in {"os", "pathlib", "time", "datetime"} for m in modules)


@pytest.mark.skip(reason=f"AC-19.7: {PARKED_REASON}")
def test_ac_19_7_hours_freed_add_up() -> None: ...


@pytest.mark.skip(reason=f"AC-19.8: {PARKED_REASON}")
def test_ac_19_8_combined_share_cap() -> None: ...


@pytest.mark.skip(reason=f"AC-19.9: {PARKED_REASON}")
def test_ac_19_9_rejected_and_whole_process_shares() -> None: ...


@pytest.mark.skip(reason=f"AC-19.13: {PARKED_REASON}")
def test_ac_19_13_no_opportunities_value_zero() -> None: ...


@pytest.mark.skip(reason=f"AC-19.14: {PARKED_REASON}")
def test_ac_19_14_role_group_rates() -> None: ...
