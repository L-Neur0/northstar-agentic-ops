"""The recommended route: which steps to start with, with which kind of solution, what to fix first (spec 26 §3.6).

Why: the step ratings say what AI could do in each step; the expert and the specialists also need
to know where to begin. That order is a decision, so code makes it (product rule 3), from facts
already checked: each step's fit and route (grounded against the profile and the catalogue) and its
hours a year (spec 19). The headline is one code template, so no sentence in it is the model's.
What: `route_summary` puts every step in exactly one group (start with, later, fix first, stays with
people, not routed), orders the routed steps by hours, collects the prerequisites to prepare and
writes the headline; `catalogue_fingerprint` hashes the catalogue so a changed catalogue re-runs
ASSESS_STEPS; `inputs_hash` joins it to the profile fingerprint.
Must not: call a model, read a clock, do I/O, use money (parked, refinement R5), or name a tool
that is not in the catalogue (names come from configuration only).
Spec 26 §3.6, §3.7, §4.1; AC-26.12 to AC-26.17.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.config import SolutionCatalogue
from app.models.process_discovery_schemas import RouteSummary, StepRating, ValueResult

from ..fingerprint import ai_input_fingerprint
from ..value import num

ROUTE_START_MAX = 2
PREPARE_MAX = 5
NOT_ROUTED_CATEGORIES = frozenset({"fix_first", "none"})


def catalogue_fingerprint(catalogue: SolutionCatalogue) -> str:
    """SHA-256 of the catalogue's canonical JSON (sorted keys): changes with any entry or the version."""
    text = json.dumps(catalogue.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def inputs_hash(profile: Mapping[str, Any], catalogue: SolutionCatalogue) -> str:
    """`StepAssessment.inputs_hash`: what ASSESS_STEPS reads from the profile, and the catalogue."""
    return f"{ai_input_fingerprint(profile)}:{catalogue_fingerprint(catalogue)}"


def _step_list(steps: Sequence[int], names: Mapping[int, str]) -> str:
    return ", ".join(f'step {k} "{names.get(k, "")}"' for k in steps)


def route_summary(
    ratings: Sequence[StepRating], value: ValueResult | None, catalogue: SolutionCatalogue
) -> RouteSummary:
    """Every step in one group, the routed steps ordered by hours, the prerequisites and the headline."""
    hours: dict[int, float | None] = {s.step: s.hours_per_year for s in value.steps} if value is not None else {}
    names = {r.step: r.name for r in ratings}
    routed: list[StepRating] = []
    fix_first: list[int] = []
    stay: list[int] = []
    not_routed: list[int] = []
    for rating in sorted(ratings, key=lambda r: r.step):
        solution = catalogue.get(rating.route_id) if rating.route_id else None
        if rating.fit == "human":
            stay.append(rating.step)
        elif rating.fit is None or solution is None:
            not_routed.append(rating.step)
        elif solution.category == "fix_first":
            fix_first.append(rating.step)
        elif solution.category in NOT_ROUTED_CATEGORIES:
            not_routed.append(rating.step)
        else:
            routed.append(rating)

    def order(r: StepRating) -> tuple[int, float, int, int]:
        h = hours.get(r.step)
        return (h is None, -(h or 0.0), 0 if r.fit == "automate" else 1, r.step)

    routed.sort(key=order)
    start, later = routed[:ROUTE_START_MAX], routed[ROUTE_START_MAX:]

    used = {r.route_id for r in start}
    prepare: list[str] = []
    for solution in catalogue.solutions:
        if solution.id not in used:
            continue
        for item in solution.prerequisites:
            if item.casefold() not in {p.casefold() for p in prepare} and len(prepare) < PREPARE_MAX:
                prepare.append(item)

    if start:
        first = start[0]
        solution = catalogue.get(first.route_id or "")
        h = hours.get(first.step)
        about = f" (about {num(h)} h a year)" if h is not None else ""
        headline = f'Start with step {first.step} "{first.name}"{about} using {solution.name if solution else ""}.'
    else:
        headline = "No step has an AI route yet."
    if fix_first:
        headline += f" Fix first: {_step_list(fix_first, names)}."
    return RouteSummary(
        headline=headline,
        start_with=[r.step for r in start],
        later=[r.step for r in later],
        fix_first=fix_first,
        stay_with_people=stay,
        not_routed=not_routed,
        prepare=prepare,
    )
