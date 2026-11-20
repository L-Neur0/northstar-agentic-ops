"""Tests for the suggested path (spec 19 §3.6) and the code-only recompute (spec 19 §3.7).

Why: the path is an order made by code, so it must be fully deterministic and match the worked
example: in Europe the template comes first and blocks reading the site files (Standard low); in
North America (Standard high) the same opportunity is just a bigger change.
What: `blocked_by` and `compute_path` on the shared EU and NA fixtures with o1–o4, the tie
breaks, a rejected opportunity, an incomplete value; `compute_code_parts` with and without ratings.
Must not: call a model.
Covers AC-19.34 to AC-19.36, AC-19.38 (path), AC-19.41, AC-19.43.
"""

from __future__ import annotations

import ast
from pathlib import Path as FilePath

from app.models.process_discovery_schemas import (
    Opportunity,
    Readiness,
    ReadinessDimension,
    StepRating,
    ValueResult,
)
from app.services.process_discovery.artifacts.assessment_code import compute_code_parts
from app.services.process_discovery.artifacts.path import blocked_by, compute_path
from app.services.process_discovery.artifacts.readiness import compute_readiness
from app.services.process_discovery.artifacts.step_assessment.route import route_summary
from app.services.process_discovery.artifacts.value import compute_value
from tests.fixtures.assessment.profiles import load_profile, nig_config
from tests.fixtures.assessment_19.cases import STEPS_REPLY, eu_labels, eu_opportunities, example_catalogue


def _parts(variant: str = "eu", opportunities: list[Opportunity] | None = None):
    profile = load_profile(variant)  # type: ignore[arg-type]
    opps = eu_opportunities() if opportunities is None else opportunities
    value = compute_value(profile, opps, nig_config().rates)
    readiness = compute_readiness(profile, eu_labels(), True, value, nig_config().readiness)
    return opps, value, readiness


def test_ac_19_34_blocked_by() -> None:
    """AC-19.34: EU o1 (document_ai, steps 1–2) → standard; o3 (workflow) → none; medium never blocks."""
    opps, _, readiness = _parts()
    by_id = {o.id: o for o in opps}
    assert blocked_by(by_id["o1"], readiness) == ["standard"]
    assert blocked_by(by_id["o3"], readiness) == []
    medium = Readiness(dimensions=[ReadinessDimension(key="standard", level="medium", steps=[1, 2])])
    assert blocked_by(by_id["o1"], medium) == []


def test_ac_19_34_whole_process_opportunity_overlaps_any_concerned_step() -> None:
    opp = Opportunity.model_validate(
        {"id": "x", "title": "t", "type": "ai_agent", "impact": "low", "feasibility": "low", "substeps": []}
    )
    low_rules = Readiness(dimensions=[ReadinessDimension(key="rules", level="low", steps=[5])])
    assert blocked_by(opp, low_rules) == ["rules"]
    no_steps = Readiness(dimensions=[ReadinessDimension(key="rules", level="low", steps=[])])
    assert blocked_by(opp, no_steps) == []


def test_ac_19_35_eu_and_na_paths() -> None:
    """AC-19.35: EU = [o4, o1] / [o2, o3] / [] with prepare items [standard]; NA = [] / [o2, o3] / [o1]."""
    path = compute_path(*_parts())
    assert (path.prepare_first, path.quick_wins, path.bigger_changes) == (["o4", "o1"], ["o2", "o3"], [])
    assert path.prepare_items == ["standard"]
    na = compute_path(*_parts("na", [o for o in eu_opportunities() if o.id != "o4"]))  # no standardise in NA
    assert (na.prepare_first, na.quick_wins, na.bigger_changes, na.prepare_items) == ([], ["o2", "o3"], ["o1"], [])


def _opp(id: str, impact: str, feasibility: str, substeps: list[int]) -> Opportunity:
    return Opportunity.model_validate(
        {"id": id, "title": id, "type": "workflow", "impact": impact, "feasibility": feasibility, "substeps": substeps}
    )


def test_ac_19_36_ties_and_rejected() -> None:
    """AC-19.36: equal hours → impact → feasibility → model order; rejected in no group."""
    opps = [
        _opp("a", "low", "high", [1]),  # 72 h
        _opp("b", "high", "high", [3]),  # 72 h, higher impact
        _opp("c", "high", "high", [5]),  # 72 h, same as b, later in model order
        _opp("d", "high", "high", [2]).model_copy(update={"review": "rejected"}),
    ]
    path = compute_path(*_parts(opportunities=opps))
    assert path.quick_wins == ["b", "c", "a"]
    assert "d" not in path.quick_wins + path.bigger_changes + path.prepare_first


def test_ac_19_36_incomplete_value_orders_without_hours() -> None:
    """AC-19.36: an opportunity without step hours makes its group order by impact, feasibility, model order."""
    opps = [_opp("small", "high", "high", [4]), _opp("big", "low", "high", [2])]
    _, _, readiness = _parts(opportunities=opps)
    value = ValueResult.model_validate(
        {"opportunities": [{"id": "small", "stepHours": None}, {"id": "big", "stepHours": 96}]}
    )
    assert compute_path(opps, value, readiness).quick_wins == ["small", "big"]


def test_ac_19_41_step_hours_order_the_group() -> None:
    """AC-19.41: EU quick wins are o2 (72 h) before o3 (30 h); hours beat impact."""
    opps = [_opp("small", "high", "high", [4]), _opp("big", "low", "high", [2])]
    assert compute_path(*_parts(opportunities=opps)).quick_wins == ["big", "small"]
    value = _parts()[1]
    assert {o.id: o.step_hours for o in value.opportunities if o.id in ("o2", "o3")} == {"o2": 72, "o3": 30}


def test_ac_19_43_compute_code_parts() -> None:
    """AC-19.43: with ratings, the route summary of spec 26 from the same hours; without, None."""
    from app.services.process_discovery.artifacts.step_assessment.grounding import ground_step_ratings

    profile = load_profile("eu")
    catalogue = example_catalogue()
    ratings, _ = ground_step_ratings(STEPS_REPLY, profile, catalogue)
    config = nig_config()
    value, readiness, opps, path, route = compute_code_parts(
        profile, eu_opportunities(), eu_labels(), ratings, {"labels": "generated"}, config.rates,
        config.readiness, catalogue, None,
    )  # fmt: skip
    assert value.hours_per_year == 342
    assert path.prepare_first == ["o4", "o1"]
    assert {o.id: o.blocked_by for o in opps}["o1"] == ["standard"]
    assert route == route_summary(ratings, value, catalogue)
    assert route is not None and route.start_with == [2, 3]
    none = compute_code_parts(
        profile, eu_opportunities(), [], [], {"labels": "failed"}, config.rates, config.readiness, catalogue, readiness
    )
    assert none[4] is None
    assert {d.key: d.level for d in none[1].dimensions}["data"] == "unknown"
    assert isinstance(ratings[0], StepRating)


def test_ac_19_38_path_is_pure() -> None:
    """AC-19.38 (path): no I/O import, no model call."""
    root = FilePath(__file__).resolve().parents[4] / "app/services/process_discovery/artifacts"
    for name in ("path.py", "assessment_code.py"):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        modules = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not any(m.endswith("llm") or m in {"os", "pathlib", "time", "datetime"} for m in modules)
