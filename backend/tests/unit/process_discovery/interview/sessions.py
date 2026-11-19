"""Session builders for the interview tests: the monthly cost review at a given point of the interview (spec 14 §7).

Why: many interview tests start mid-interview (in `measure`, at the step count, in the walk); building
those sessions with the real writers keeps them in a shape the product actually produces.
What: `profile_until(vocab, phase)` and `session_at(ctx, phase, profile, **parts)`, with the name's
scope and placement already current so no CLASSIFY call is needed. Must not: bypass a writer.
"""

from __future__ import annotations

from typing import Any

from app.models.process_discovery_schemas import Profile, Session
from app.services.process_discovery.interview.types import InterviewContext
from app.services.process_discovery.profile.mutate import apply_changes, set_cluster
from app.services.process_discovery.profile.shapes import empty_profile

from ..profile.builders import AT, context_changes, process_changes
from .helpers import new_session

NAME = "Monthly cost review"
BOUNDARIES = ("process.trigger", "process.end_result", "process.value_at_end", "process.business_pain")
MEASURE = (
    "process.volume",
    "process.process_owner",
    "process.baseline_metric",
    "process.target_metric",
    "process.variation",
    "process.sensitive_data",
)


def profile_with(ctx: InterviewContext, *keys: str, steps: int | None = None) -> dict[str, Any]:
    """Context, the name, the cluster, and the listed process fields (values from the cost review)."""
    values = process_changes(steps)
    changes = {**context_changes(), "process.name": NAME, **{k: values[k] for k in keys}}
    if steps is not None:
        changes["process.substep_count"] = steps
    profile = apply_changes(empty_profile(), changes, vocab=ctx.vocab, at=AT).profile
    return set_cluster(profile, "FIN", decided_by="proposal", vocab=ctx.vocab, at=AT)


def session_at(ctx: InterviewContext, phase: str, profile: dict[str, Any], **parts: Any) -> Session:
    """A session in `phase` holding `profile`, with scope and placement current for the name."""
    return new_session(
        ctx,
        phase=phase,
        profile=Profile.model_validate(profile),
        scope=parts.pop("scope", {"verdict": None, "scoped_for": NAME}),
        placement=parts.pop("placement", {"proposal": None, "placed_for": NAME}),
        **parts,
    )
