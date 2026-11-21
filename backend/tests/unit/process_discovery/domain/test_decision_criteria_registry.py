"""Tests for S14 decision criteria in the registry and the storage model (spec 12 §3.13).

Why: evaluation run 20261121-084902 showed the interview never asked what a judgement step is
based on, yet that decides whether AI can help. S14 holds it; it must only apply to judgement or
mix steps, and it must never change the score or the *Finish* gate (weight 0, optional).
What: the registry entry, `field_applies`, the cell verdicts, the storage model, and that points,
score and gate are the same with or without S14.
Must not: restate other fields of the registry.
Covers AC-12.56 to AC-12.59.
"""

from __future__ import annotations

import copy
import dataclasses
from pathlib import Path

import pytest

from app.core.config import load_company_config
from app.models.process_discovery_schemas import Step
from app.services.process_discovery.domain import field_spec as fs
from app.services.process_discovery.domain.field_spec import (
    STEP_POINTS,
    Vocabulary,
    evaluate_field,
    extract_keys,
    field_applies,
)
from app.services.process_discovery.profile.scoring import finish_check, score
from tests.fixtures.assessment.profiles import load_profile

NIG = Path(__file__).resolve().parents[5] / "config" / "nig"
CONFIG = load_company_config(NIG)
VOCAB = Vocabulary(taxonomy=CONFIG.taxonomy, regions=CONFIG.organisation.regions, wording=CONFIG.wording)
_S14 = fs.spec_by_id("S14")
assert _S14 is not None
S14: fs.FieldSpec = _S14


def test_ac_12_56_s14_in_the_registry():
    """AC-12.56: the attributes of spec 12 §3.13; S14 is extractable; Step stores it."""
    assert (S14.key, S14.label, S14.kind) == ("decision_criteria", "Decision criteria", "object")
    assert [(sf.key, sf.required) for sf in S14.subfields] == [
        ("basis", True),
        ("set_by", False),
        ("written", False),
        ("varies", False),
    ]
    assert (S14.weight, S14.group, S14.max_asks, S14.optional) == (0, fs.GROUP_B, 1, True)
    assert S14.applies_when == "decision_judgement"
    assert S14.ask_part == "what the decision is based on, who sets the criteria and whether they are written down"
    assert S14.extract and S14.propose
    assert "process.substeps[i].decision_criteria" in extract_keys()
    assert Step.model_validate({"decision_criteria": {"basis": "x", "written": "no"}}).decision_criteria.basis == "x"


def test_ac_12_56_unknown_applies_when_is_refused():
    """AC-12.56: an `applies_when` other than `decision_judgement` or None fails the registry check."""
    bad = dataclasses.replace(S14, applies_when="sometimes")
    with pytest.raises(ValueError, match="applies_when"):
        fs.check_registry((*fs.PROFILE_SPECS, *fs.STEP_SPECS, bad))


@pytest.mark.parametrize(
    ("kind", "applies"), [("judgement", True), ("mix", True), ("rules", False), ("", False), (None, False)]
)
def test_ac_12_57_field_applies(kind, applies):
    """AC-12.57: S14 applies only to a judgement or mix step; every other field always applies."""
    row = {} if kind is None else {"decision_type": {"kind": kind, "evidence": "x"}}
    assert field_applies(S14, row) is applies
    systems = fs.step_spec_by_leaf("systems")
    assert systems is not None and field_applies(systems, row) is True


def test_ac_12_58_verdicts():
    """AC-12.58: basis completes it; a `written` other than yes / partly / no is invalid; empty is empty."""
    ok = evaluate_field(S14, {"basis": "the hiring manager's must-haves", "written": "no"}, {}, VOCAB)
    assert ok.status == fs.STATUS_COMPLETE
    bad = evaluate_field(S14, {"basis": "x", "written": "maybe"}, {}, VOCAB)
    assert bad.status == fs.STATUS_INVALID and "written" in bad.reason
    assert evaluate_field(S14, {}, {}, VOCAB).status == fs.STATUS_PARTIAL


def test_ac_12_59_points_score_and_gate_unchanged():
    """AC-12.59: S14 carries no points; the fixture's score and gate are the same with it."""
    assert STEP_POINTS == 12
    profile = load_profile("eu")
    with_criteria = copy.deepcopy(profile)  # written directly: an edit through apply_changes reopens the walk
    with_criteria["process"]["substeps"][2]["decision_criteria"] = {"basis": "the variance threshold", "written": "yes"}
    assert score(with_criteria, vocab=VOCAB) == score(profile, vocab=VOCAB)
    assert finish_check(with_criteria, vocab=VOCAB).ready == finish_check(profile, vocab=VOCAB).ready
