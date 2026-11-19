"""Profile builders for the profile and interview tests: the monthly cost review, built with the real writers (spec 13 §7).

Why: tests that hand-type profile dicts drift from the shape the writers produce, and a test that
passes on a shape the product never makes proves nothing. Every profile here is built through
`apply_changes`, `set_cluster` and the other producers, from registry keys (`step_cell_key`).
What: the fixed time `AT`, `context_changes`, `process_changes`, `step_changes` and
`cost_review_profile(vocab, steps=4)`, which builds the example used across specs 13 and 14.
Must not: patch or bypass a writer.
"""

from __future__ import annotations

from typing import Any

from app.services.process_discovery.domain.field_spec import Vocabulary, step_cell_key
from app.services.process_discovery.profile.mutate import apply_changes, set_cluster
from app.services.process_discovery.profile.shapes import empty_profile

AT = "2026-11-19T10:00:00+00:00"


def context_changes() -> dict[str, Any]:
    return {"department": "Finance", "user_function": "Cost controller", "region": "Europe"}


def process_changes(steps: int | None = 4) -> dict[str, Any]:
    changes: dict[str, Any] = {
        "process.name": "Monthly cost review",
        "process.trigger": "Month-end close is completed in the ledger",
        "process.end_result": "The monthly cost report",
        "process.value_at_end": "The CFO uses it to decide on budget corrections",
        "process.business_pain": "Chasing explanations takes days",
        "process.volume": {"count": 1, "period": "month"},
        "process.process_owner": {"role": "Head of Controlling"},
        "process.baseline_metric": {"value": "4", "unit": "days"},
        "process.target_metric": {"value": "2", "unit": "days"},
        "process.variation": {"same": "yes"},
        "process.sensitive_data": [{"none": True}],
    }
    if steps is not None:
        changes["process.substep_count"] = steps
    return changes


def step_changes(index: int, *, leave_out: tuple[str, ...] = ()) -> dict[str, Any]:
    cells: dict[str, Any] = {
        "name": f"Step {index}",
        "goal": f"Step {index} is done",
        "activities": ["export", "check"],
        "roles": [{"role": "Controller", "contribution": "checks"}],
        "owner": "Controller",
        "systems": ["SAP"],
        "data": {"inputs": ["actuals"], "outputs": ["report"]},
        "effort": {"duration": "2 hours", "frequency": "monthly"},
        "pain_points": ["slow"],
        "approvals": [{"none": True}],
        "exceptions": [{"none": True}],
        "handover": "by e-mail",
    }
    return {step_cell_key(index, leaf): value for leaf, value in cells.items() if leaf not in leave_out}


def cost_review_profile(
    vocab: Vocabulary, steps: int = 4, *, filled_steps: int | None = None, cluster: bool = True
) -> dict[str, Any]:
    """The monthly cost review: context, every process field, `steps` declared and `filled_steps` fully described."""
    profile = apply_changes(
        empty_profile(), {**context_changes(), **process_changes(steps)}, vocab=vocab, at=AT
    ).profile
    if cluster:
        profile = set_cluster(profile, "FIN", decided_by="proposal", vocab=vocab, at=AT)
    for index in range(1, (steps if filled_steps is None else filled_steps) + 1):
        profile = apply_changes(profile, step_changes(index), vocab=vocab, at=AT).profile
    return profile
