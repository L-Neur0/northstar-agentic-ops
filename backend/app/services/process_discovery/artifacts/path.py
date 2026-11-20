"""The suggested path: which opportunities to prepare first, which are quick wins, which are bigger changes (spec 19 §3.6).

Why: a list of opportunities does not say where to start, and the order must not be the model's
opinion (product rule 3). Code orders them from facts already checked: the low readiness
dimensions that block an opportunity's type in its steps (a missing template blocks reading the
site files, but not a reminder workflow), its feasibility, the hours of the steps it covers, its
impact. Medium never blocks, and nothing here is a go / no-go: it only orders.
What: `BLOCKS` (which types each low dimension blocks), `blocked_by` (the dimensions blocking one
opportunity) and `compute_path` (three groups, fully deterministic order, the prepare items).
Must not: call a model, read a clock, change an opportunity, or use money while the value method is
parked (refinement R5: hours freed are not computed, so step hours order the groups).
Spec 19 §3.6, §4.2; AC-19.34 to AC-19.36, AC-19.38, AC-19.41.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models.process_discovery_schemas import Opportunity, OpportunityType, Path, Readiness, ValueResult

_ALL_TYPES = frozenset(t.value for t in OpportunityType)
BLOCKS: dict[str, frozenset[str]] = {
    "defined": _ALL_TYPES - {"eliminate", "standardise"},
    "standard": frozenset({"integration", "document_ai", "ai_agent", "rpa"}),
    "data": frozenset({"integration", "ai_agent", "rpa"}),
    "systems": frozenset({"integration", "ai_agent", "rpa"}),
    "rules": frozenset({"ai_agent", "workflow"}),
    "risk_size": frozenset(),
}
GRADE_ORDER = {"high": 0, "medium": 1, "low": 2}


def blocked_by(opportunity: Opportunity, readiness: Readiness) -> list[str]:
    """Low dimensions that block this opportunity's type and concern one of its steps (`[]` = all steps)."""
    out: list[str] = []
    for dim in readiness.dimensions:
        if dim.level != "low" or opportunity.type.value not in BLOCKS.get(dim.key, frozenset()):
            continue
        overlaps = bool(dim.steps) if not opportunity.substeps else bool(set(dim.steps) & set(opportunity.substeps))
        if overlaps:
            out.append(dim.key)
    return out


def _ordered(group: list[tuple[int, Opportunity]], hours: dict[str, float | None]) -> list[str]:
    """Step hours high first (only when every member has hours), then impact, feasibility, model order."""
    use_hours = all(hours.get(o.id) is not None for _, o in group)

    def key(item: tuple[int, Opportunity]) -> tuple[float, int, int, int]:
        position, opp = item
        h = -(hours.get(opp.id) or 0.0) if use_hours else 0.0
        return h, GRADE_ORDER[opp.impact.value], GRADE_ORDER[opp.feasibility.value], position

    return [o.id for _, o in sorted(group, key=key)]


def compute_path(opportunities: Sequence[Opportunity], value: ValueResult, readiness: Readiness) -> Path:
    """The three groups (rejected opportunities left out) and the low dimensions to prepare."""
    hours = {o.id: o.step_hours for o in value.opportunities}
    kept = [(i, o) for i, o in enumerate(opportunities) if o.review != "rejected"]
    standardise = [(i, o) for i, o in kept if o.type == OpportunityType.STANDARDISE]
    blocked = [(i, o) for i, o in kept if o.type != OpportunityType.STANDARDISE and blocked_by(o, readiness)]
    first = {o.id for _, o in standardise + blocked}
    rest = [(i, o) for i, o in kept if o.id not in first]
    return Path(
        prepare_first=_ordered(standardise, hours) + _ordered(blocked, hours),
        quick_wins=_ordered([(i, o) for i, o in rest if o.feasibility.value == "high"], hours),
        bigger_changes=_ordered([(i, o) for i, o in rest if o.feasibility.value != "high"], hours),
        prepare_items=[d.key for d in readiness.dimensions if d.level == "low"],
    )
