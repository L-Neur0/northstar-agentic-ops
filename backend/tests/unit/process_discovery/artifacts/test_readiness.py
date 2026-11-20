"""Tests for the readiness checklist (spec 19 §3.5).

Why: the six levels are numbers made by code (product rule 3), so each threshold, each "unknown"
case and each to-prepare line is pinned, and the worked example must give the EU and NA columns
of §3.5 exactly (EU Standard low with "agree one template"; NA Standard high).
What: `compute_readiness` on the shared EU and NA fixtures with the §3.4 labels, then one test per
dimension rule, the to-prepare lines, the note carry-over and `match_application`.
Must not: call a model or build labels through LABEL (labels come from the cases module).
Covers AC-19.23 to AC-19.33 and AC-19.38 (readiness).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.models.process_discovery_schemas import (
    DecisionLabel,
    InputLabel,
    Readiness,
    ReadinessDimension,
    StepLabels,
    ValueResult,
)
from app.services.process_discovery.artifacts.readiness import DIMENSIONS, compute_readiness, match_application
from app.services.process_discovery.artifacts.value import compute_value
from tests.fixtures.assessment.profiles import load_profile, nig_config
from tests.fixtures.assessment_19.cases import eu_labels, eu_opportunities

CFG = nig_config().readiness


def _readiness(profile=None, labels=None, labels_ok=True, value=None, previous=None) -> dict[str, ReadinessDimension]:
    profile = load_profile("eu") if profile is None else profile
    value = compute_value(profile, eu_opportunities(), nig_config().rates) if value is None else value
    result = compute_readiness(profile, eu_labels() if labels is None else labels, labels_ok, value, CFG, previous)
    assert [d.key for d in result.dimensions] == list(DIMENSIONS)
    return {d.key: d for d in result.dimensions}


def _levels(dims: dict) -> dict[str, str]:
    return {k: d.level for k, d in dims.items()}


def test_ac_19_23_eu_and_na_levels() -> None:
    """AC-19.23: the EU and NA columns of the §3.5 worked example."""
    assert _levels(_readiness()) == {
        "defined": "high", "standard": "low", "data": "high", "systems": "medium", "rules": "high", "risk_size": "high",
    }  # fmt: skip
    na = _readiness(load_profile("na"))
    assert _levels(na) == {
        "defined": "high", "standard": "high", "data": "high", "systems": "medium", "rules": "high", "risk_size": "high",
    }  # fmt: skip
    assert na["standard"].reason == "Same way everywhere; exceptions in 2 of 5 steps."


def test_ac_19_23_eu_reasons_name_the_counts() -> None:
    dims = _readiness()
    assert dims["defined"].reason == "Trigger, end result and owner known; 5 of 5 steps have a goal."
    assert dims["data"].reason == "8 of 8 labelled inputs are digital."
    assert dims["systems"].reason == "2 of 3 systems have a known export or API (Outlook, SAP S/4HANA); not: Excel."
    assert dims["rules"].reason == "4 of 5 decisions are fixed rules or explainable."
    assert dims["risk_size"].reason == "About 342 hours a year and no sensitive data."
    assert dims["standard"].label == "Standard" and dims["risk_size"].label == "Risk and size"


def test_ac_19_24_eu_standard_to_prepare() -> None:
    """AC-19.24: the configured low line plus what differs today, in the expert's words."""
    assert _readiness()["standard"].to_prepare == (
        CFG.dimensions["standard"].to_prepare["low"]
        + ' What differs today: "each site sends its own spreadsheet layout".'
    )


def _with_exceptions(profile: dict, steps: set[int]) -> dict:
    for i, row in enumerate(profile["process"]["substeps"], 1):
        row["exceptions"] = [{"description": f"exception {i}"}] if i in steps else [{"none": True}]
    return profile


def test_ac_19_25_standard_rules() -> None:
    """AC-19.25: partly → medium; yes with 3 of 5 → medium; 2 of 5 → high; missing or proposed → unknown."""
    partly = load_profile("eu")
    partly["process"]["variation"] = {"same": "partly", "differences": "two sites use an old layout"}
    assert _readiness(partly)["standard"].level == "medium"
    yes = load_profile("na")
    assert _readiness(_with_exceptions(yes, {1, 2, 4}))["standard"].level == "medium"
    assert _readiness(_with_exceptions(load_profile("na"), {2, 4}))["standard"].level == "high"
    missing = load_profile("eu")
    missing["process"]["variation"] = {"same": "", "differences": ""}
    dim = _readiness(missing)["standard"]
    assert (dim.level, dim.to_prepare) == ("unknown", "")
    proposed = load_profile("eu")
    proposed["__meta"]["process.variation"] = {
        "source": "document", "status": "proposed", "documentId": "d1", "quote": "no", "at": "t"
    }  # fmt: skip
    assert _readiness(proposed)["standard"].level == "unknown"


def test_ac_19_26_defined_rules() -> None:
    """AC-19.26: owner none_identified is missing; two parts missing → low; 2 of 5 without goal → medium; 3 → low."""
    no_owner = load_profile("eu")
    no_owner["process"]["process_owner"] = {"role": "", "none_identified": True}
    dim = _readiness(no_owner)["defined"]
    assert dim.level == "medium" and "owner role" in dim.reason
    two = load_profile("eu")
    two["process"]["process_owner"] = {"role": "", "none_identified": True}
    two["process"]["trigger"] = ""
    assert _readiness(two)["defined"].level == "low"
    goals = load_profile("eu")
    for row in goals["process"]["substeps"][:2]:
        row["goal"] = ""
    dim = _readiness(goals)["defined"]
    assert (dim.level, dim.steps) == ("medium", [1, 2])
    goals["process"]["substeps"][2]["goal"] = ""
    assert _readiness(goals)["defined"].level == "low"


def _input_labels(digital: int, other: int) -> list[StepLabels]:
    inputs = [InputLabel(name=f"d{i}", format="structured") for i in range(digital)]
    inputs += [InputLabel(name=f"p{i}", format="paper") for i in range(other)]
    return [StepLabels(step=1, inputs=inputs)]


@pytest.mark.parametrize(("digital", "other", "level"), [(80, 20, "high"), (50, 50, "medium"), (49, 51, "low")])
def test_ac_19_27_data_thresholds(digital: int, other: int, level: str) -> None:
    """AC-19.27: 0.8 → high, 0.5 → medium, 0.49 → low (inclusive); paper steps concerned."""
    dim = _readiness(labels=_input_labels(digital, other))["data"]
    assert dim.level == level
    assert dim.steps == [1]


def test_ac_19_27_data_unknown_without_labelled_input() -> None:
    dim = _readiness(labels=[StepLabels(step=1)])["data"]
    assert dim.level == "unknown" and dim.to_prepare == ""
    assert "Not labelled: site cost spreadsheets" in dim.reason


def test_ac_19_28_match_application() -> None:
    """AC-19.28: alias as a whole word, exact name, unlisted system."""
    excel = match_application("Excel master file", CFG)
    assert excel is not None and excel.name == "Microsoft Excel" and excel.export_or_api is False
    sap = match_application("SAP S/4HANA", CFG)
    assert sap is not None and sap.name == "SAP S/4HANA"
    assert match_application("Our costing tool", CFG) is None
    assert match_application("Excellence portal", CFG) is None  # not a whole word


def test_ac_19_28_no_system_is_low() -> None:
    profile = load_profile("eu")
    for row in profile["process"]["substeps"]:
        row["systems"] = []
    dim = _readiness(profile)["systems"]
    assert dim.level == "low" and dim.to_prepare == CFG.dimensions["systems"].to_prepare["low"]


def _decisions(explainable: int, pure: int) -> list[StepLabels]:
    decisions = [DecisionLabel(text=f"r{i}", kind="fixed_rule") for i in range(explainable)]
    decisions += [DecisionLabel(text=f"j{i}", kind="pure_judgement") for i in range(pure)]
    return [StepLabels(step=2, decisions=decisions)]


@pytest.mark.parametrize(("rules", "pure", "level"), [(7, 3, "high"), (4, 6, "medium"), (3, 7, "low")])
def test_ac_19_29_rules_thresholds(rules: int, pure: int, level: str) -> None:
    """AC-19.29: 0.7 → high, 0.4 → medium, below → low."""
    dim = _readiness(labels=_decisions(rules, pure))["rules"]
    assert dim.level == level and dim.steps == [2]


def test_ac_19_29_no_decision_is_high() -> None:
    dim = _readiness(labels=[StepLabels(step=1)])["rules"]
    assert (dim.level, dim.reason) == ("high", "No decision was found in the steps.")


def test_ac_19_30_labels_failed() -> None:
    """AC-19.30: Data and Rules unknown, "Not rated", no line; the other four rated."""
    dims = _readiness(labels=[], labels_ok=False)
    for key in ("data", "rules"):
        assert dims[key].level == "unknown"
        assert dims[key].reason == "Not rated: the input labels could not be produced."
        assert dims[key].to_prepare == ""
    assert all(dims[k].level != "unknown" for k in ("defined", "standard", "systems", "risk_size"))


def test_ac_19_31_risk_and_size() -> None:
    """AC-19.31: 99 h → low; 342 h with a sensitive row → medium; none row → high; incomplete → unknown."""
    assert _readiness(value=ValueResult(hours_per_year=99))["risk_size"].level == "low"
    sensitive = load_profile("eu")
    sensitive["process"]["sensitive_data"] = [{"item": "personal data of employees", "detail": ""}]
    dim = _readiness(sensitive)["risk_size"]
    assert dim.level == "medium" and "personal data of employees" in dim.reason
    assert _readiness()["risk_size"].level == "high"
    assert _readiness(value=ValueResult(hours_per_year=None))["risk_size"].level == "unknown"
    big = _readiness(value=ValueResult(hours_per_year=600))["risk_size"]
    assert big.level == "high" and big.reason.endswith("— a large process.")


def test_ac_19_32_to_prepare_lines_and_no_overall_level() -> None:
    """AC-19.32: medium and low have their configured line; high and unknown have none; no overall field."""
    for dims in (_readiness(), _readiness(labels=[], labels_ok=False)):
        for d in dims.values():
            if d.level in ("medium", "low"):
                assert d.to_prepare.startswith(CFG.dimensions[d.key].to_prepare[d.level])
            else:
                assert d.to_prepare == ""
    assert set(Readiness.model_fields) == {"dimensions"}


def test_ac_19_33_specialist_note_survives() -> None:
    """AC-19.33: a note on a dimension is carried over by key."""
    first = compute_readiness(load_profile("eu"), eu_labels(), True, ValueResult(hours_per_year=342), CFG)
    noted = Readiness(
        dimensions=[d.model_copy(update={"note": "IT confirmed SAP access"}) if d.key == "systems" else d
                    for d in first.dimensions]
    )  # fmt: skip
    again = _readiness(previous=noted)
    assert again["systems"].note == "IT confirmed SAP access"
    assert again["data"].note == ""


def test_ac_19_38_readiness_is_pure() -> None:
    """AC-19.38 (readiness): no I/O import, no model call."""
    path = Path(__file__).resolve().parents[4] / "app/services/process_discovery/artifacts/readiness.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any(m.endswith("llm") or m in {"os", "pathlib", "time", "datetime"} for m in modules)
