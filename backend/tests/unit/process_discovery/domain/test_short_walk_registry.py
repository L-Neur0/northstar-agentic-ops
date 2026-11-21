"""Tests for the registry side of the short step walk (spec 12 §3.4 short step walk amendment; AC-12.50 to AC-12.52).

Why: the walk groups fields by what the registry says about them; if a group, a limit or the new
rules-or-judgement field drifted from the spec, the interview would ask the wrong question or never
settle a step. What: the S13 grader, the groups and their limits, the optional target, and the
`agent` source on `FieldMeta` and the `Step` default.
Must not: restate behaviour of the interview (spec 14 §3.19 has its own tests).
"""

import pytest
from pydantic import ValidationError

from app.models.process_discovery_schemas import FieldMeta, Step
from app.services.process_discovery.domain import field_spec as fs

AT = "2026-11-20T09:14:03Z"


def spec_of(field_id: str) -> fs.FieldSpec:
    spec = fs.spec_by_id(field_id)
    assert spec is not None
    return spec


@pytest.mark.parametrize(
    ("value", "status"),
    [
        ({}, "partial"),
        ({"kind": "maybe", "evidence": "x"}, "invalid"),
        ({"kind": "mix"}, "partial"),
        ({"kind": "mix", "evidence": "mostly rules, I judge the outliers"}, "complete"),
        ({"kind": "Rules", "evidence": "always the same checks"}, "complete"),
        ({"kind": "judgement", "evidence": "I decide case by case"}, "complete"),
    ],
)
def test_rules_or_judgement_grades(nig_vocabulary, value, status):
    """AC-12.50."""
    s13 = spec_of("S13")
    assert s13.key == "decision_type"
    assert fs.evaluate_field(s13, value, {}, nig_vocabulary).status == status


def test_groups_and_their_limits():
    """AC-12.51."""
    assert spec_of("P07").group == spec_of("P08").group is not None
    assert spec_of("P14").group == spec_of("P15").group is not None
    assert spec_of("P07").group != spec_of("P14").group
    tier_a = [s.id for s in fs.step_specs_in_group(fs.GROUP_A)]
    assert tier_a == ["S03", "S04", "S06", "S07", "S09", "S13"]  # amended 2026-11-21 (AC-12.53)
    assert all(spec_of(i).max_asks == 2 for i in tier_a)
    assert [s.id for s in fs.step_specs_in_group(fs.GROUP_B)] == ["S10", "S11", "S12", "S14"]  # S14: spec 12 §3.13
    assert all(spec_of(i).max_asks == 1 for i in ("S10", "S11", "S12"))
    assert [s.id for s in fs.step_specs_in_group(fs.GROUP_EFFORT)] == ["S08"]
    assert spec_of("S08").max_asks == 2
    assert [s.id for s in fs.step_specs_in_group(fs.GROUP_C)] == ["S02", "S05"]
    assert spec_of("S12").max_asks == 1
    assert [s.id for s in fs.step_specs_in_group(fs.GROUP_NAMES)] == ["S01"]
    target = spec_of("P13")
    assert target.optional is True and target.max_asks == 1
    grouped = [s for s in (*fs.PROFILE_SPECS, *fs.STEP_SPECS) if s.group and s.group != fs.GROUP_NAMES]
    assert all(s.ask_part for s in grouped)


def test_step_points_include_rules_or_judgement():
    """AC-12.5 (amended): 12 points per step."""
    assert fs.STEP_POINTS == 12
    assert [fs.total_points_for(n) for n in (None, 0, 2, 6, 9)] == [18, 18, 42, 90, 90]


def test_agent_source_on_field_meta():
    """AC-12.52."""
    FieldMeta.model_validate({"source": "agent", "status": "proposed", "quote": "Comes out: report", "at": AT})
    FieldMeta.model_validate({"source": "agent", "status": "confirmed", "quote": "Comes out: report", "at": AT})
    with pytest.raises(ValidationError):
        FieldMeta.model_validate({"source": "agent", "status": "proposed", "at": AT})


def test_an_old_step_loads_without_rules_or_judgement():
    """AC-12.52."""
    step = Step.model_validate({"name": "Collect"})
    assert step.decision_type.kind == "" and step.decision_type.evidence == ""
