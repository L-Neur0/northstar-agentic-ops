"""Tests for the recommended route and the catalogue fingerprint (spec 26 §3.6, §3.7).

Why: the route is an order made by code from checked ratings and step hours, so it must be exactly
the worked example's (start with steps 2 and 3, fix step 1 first, headline word for word), every
step must land in exactly one group, and the result must not change between calls.
What: `route_summary` on the §3.2 ratings and the EU hours; tie breaks, unknown hours, prerequisites,
the empty case; `catalogue_fingerprint` and `inputs_hash`; purity checks for the three pure modules.
Must not: call a model.
Covers AC-26.12 to AC-26.17.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import yaml

from app.core.config import SolutionCatalogue
from app.models.process_discovery_schemas import StepRating, StepValue, ValueResult
from app.services.process_discovery.artifacts.fingerprint import ai_input_fingerprint
from app.services.process_discovery.artifacts.step_assessment.grounding import ground_step_ratings
from app.services.process_discovery.artifacts.step_assessment.prompts import render_catalogue
from app.services.process_discovery.artifacts.step_assessment.route import (
    catalogue_fingerprint,
    inputs_hash,
    route_summary,
)
from app.services.process_discovery.artifacts.value import compute_value
from tests.fixtures.assessment.profiles import load_profile, nig_config
from tests.fixtures.assessment_19.cases import STEPS_REPLY, eu_opportunities, example_catalogue

CAT = example_catalogue()
ROOT = Path(__file__).resolve().parents[5]


def _eu():
    profile = load_profile("eu")
    ratings, _ = ground_step_ratings(STEPS_REPLY, profile, CAT)
    return ratings, compute_value(profile, eu_opportunities(), nig_config().rates)


def _rating(step: int, fit: str | None, route: str | None) -> StepRating:
    return StepRating(step=step, name=f"Step {step}", fit=fit, route_id=route)  # type: ignore[arg-type]


def _hours(*hours: float | None) -> ValueResult:
    return ValueResult(steps=[StepValue(step=i, hours_per_year=h) for i, h in enumerate(hours, 1)])


def test_ac_26_12_worked_example() -> None:
    """AC-26.12: the §3.2 groups and headline exactly."""
    summary = route_summary(*_eu(), CAT)
    assert (summary.start_with, summary.later, summary.fix_first) == ([2, 3], [5, 4], [1])
    assert (summary.stay_with_people, summary.not_routed) == ([], [])
    assert summary.headline == (
        'Start with step 2 "Consolidate into the master file" (about 96 h a year) using Custom AI app or agent '
        'built by the AI engineering team (placeholder). Fix first: step 1 "Collect site spreadsheets".'
    )


def test_ac_26_13_ties_and_unknown_hours() -> None:
    """AC-26.13: equal hours → automate before assist → step number; None last; headline without hours."""
    ratings = [_rating(1, "assist", "low-code-flow"), _rating(2, "automate", "low-code-flow"),
               _rating(3, "automate", "low-code-flow"), _rating(4, "automate", "low-code-flow")]  # fmt: skip
    summary = route_summary(ratings, _hours(50, 50, 50, None), CAT)
    assert summary.start_with + summary.later == [2, 3, 1, 4]
    unknown = route_summary(ratings, None, CAT)
    assert unknown.start_with == [2, 3]
    assert unknown.headline == 'Start with step 2 "Step 2" using Low-code workflow automation.'


def test_ac_26_14_prepare_items() -> None:
    """AC-26.14: prerequisites of the start routes, de-duplicated case-insensitively, catalogue order, ≤ 5."""
    summary = route_summary(*_eu(), CAT)
    assert summary.prepare == [
        "A written rule for each decision",
        "Connector access to the systems involved",
        "A sponsor and an implementation brief",
    ]
    nig = nig_config().solutions
    many = [_rating(1, "automate", "custom-ai-app"), _rating(2, "automate", "invoice-processing")]
    prepare = route_summary(many, _hours(10, 20), nig).prepare
    assert len(prepare) == 5
    assert prepare[:2] == ["Access to the invoice inbox or scan feed", "A contact in the team that runs the tool"]


def test_ac_26_15_groups_are_exclusive() -> None:
    """AC-26.15: no routed step → "No step has an AI route yet."; human only in stay; unrouted only in not_routed."""
    ratings = [_rating(1, "human", "stays-with-people"), _rating(2, "automate", None), _rating(3, None, None),
               _rating(4, "assist", "fix-first")]  # fmt: skip
    summary = route_summary(ratings, _hours(1, 2, 3, 4), CAT)
    assert summary.headline == 'No step has an AI route yet. Fix first: step 4 "Step 4".'
    assert (summary.stay_with_people, summary.not_routed, summary.fix_first) == ([1], [2, 3], [4])
    assert summary.start_with == summary.later == []
    groups = [*summary.start_with, *summary.later, *summary.fix_first, *summary.stay_with_people,
              *summary.not_routed]  # fmt: skip
    assert sorted(groups) == [1, 2, 3, 4]


def test_ac_26_16_catalogue_fingerprint() -> None:
    """AC-26.16: changes with an entry or the version; not with YAML key order; joined to the profile hash."""
    base = catalogue_fingerprint(CAT)
    assert catalogue_fingerprint(example_catalogue(version="test-2")) != base
    data = CAT.model_dump(mode="json")
    data["solutions"][0]["name"] = "Another name"
    assert catalogue_fingerprint(SolutionCatalogue.model_validate(data)) != base
    reordered = yaml.safe_dump(json.loads(json.dumps(CAT.model_dump(mode="json"))), sort_keys=True)
    assert catalogue_fingerprint(SolutionCatalogue.model_validate(yaml.safe_load(reordered))) == base
    profile = load_profile("eu")
    assert inputs_hash(profile, CAT) == f"{ai_input_fingerprint(profile)}:{base}"


def test_ac_26_17_pure_and_deterministic() -> None:
    """AC-26.17: same output for the same input; no I/O, clock or model import in the pure modules."""
    assert route_summary(*_eu(), CAT) == route_summary(*_eu(), CAT)
    assert render_catalogue(CAT) == render_catalogue(CAT)
    profile = load_profile("eu")
    assert ground_step_ratings(STEPS_REPLY, profile, CAT) == ground_step_ratings(STEPS_REPLY, profile, CAT)
    package = ROOT / "app/services/process_discovery/artifacts/step_assessment"
    for name in ("route.py", "grounding.py", "prompts.py"):
        tree = ast.parse((package / name).read_text(encoding="utf-8"))
        modules = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(m.endswith("llm") or m in {"os", "pathlib", "time", "datetime", "logging"} for m in modules)
