"""The code-only parts of the assessment, recomputed together with no model call (spec 19 §3.7).

Why: hours, readiness, the opportunities' blocking dimensions, the suggested path and the recommended
route are all made by code from the profile and the checked model outputs. They depend on each other
(readiness needs the hours, the path needs readiness, the route needs the hours), so they are always
rebuilt together and in this order: at *Finish* (spec 20) and after any specialist change (spec 21).
What: `compute_code_parts` runs value → readiness → blocked_by → path → route summary and returns
all five; the label outcome decides whether Data and Rules can be rated; specialist notes on
readiness dimensions are carried over from `previous_readiness`.
Must not: call a model, read a clock, do I/O, or change an opportunity other than its `blocked_by`.
Spec 19 §3.7, §4.2; spec 26 §5; AC-19.43.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.core.config import Rates, ReadinessConfig, SolutionCatalogue
from app.models.process_discovery_schemas import (
    Opportunity,
    Path,
    Readiness,
    RouteSummary,
    StepLabels,
    StepRating,
    ValueResult,
)

from .path import blocked_by, compute_path
from .readiness import compute_readiness
from .step_assessment.route import route_summary
from .value import compute_value


def compute_code_parts(
    profile: Mapping[str, Any],
    opportunities: Sequence[Opportunity],
    labels: Sequence[StepLabels],
    step_ratings: Sequence[StepRating],
    outcomes: Mapping[str, str],
    rates: Rates,
    readiness_cfg: ReadinessConfig,
    catalogue: SolutionCatalogue,
    previous_readiness: Readiness | None,
) -> tuple[ValueResult, Readiness, list[Opportunity], Path, RouteSummary | None]:
    """Value, readiness, opportunities with `blocked_by`, path and route (None when there are no ratings)."""
    value = compute_value(profile, opportunities, rates)
    labels_ok = outcomes.get("labels") == "generated"
    readiness = compute_readiness(profile, labels, labels_ok, value, readiness_cfg, previous_readiness)
    blocked = [o.model_copy(update={"blocked_by": blocked_by(o, readiness)}) for o in opportunities]
    path = compute_path(blocked, value, readiness)
    route = route_summary(step_ratings, value, catalogue) if step_ratings else None
    return value, readiness, blocked, path, route
