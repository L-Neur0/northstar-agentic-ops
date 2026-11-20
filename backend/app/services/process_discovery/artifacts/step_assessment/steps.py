"""The ASSESS_STEPS call: one model call that rates every step and picks a route from the catalogue (spec 26 §3.3).

Why: the step-by-step assessment comes from one model call whose content is trusted for nothing.
Structured Outputs fixes the shape; grounding checks the steps, quotes and route ids. A failed call
is a failure the report shows as a note (there is no fallback content), and it never blocks the
other parts of the assessment.
What: `run_step_assessment` builds the messages (rules + catalogue, fenced profile), makes one
`generate_structured` call, turns any `LLMError` into `StepAssessmentFailedError`, grounds the reply
and writes one `assessment_call` log line with counts only. `ground_step_ratings` is re-exported
from the pure `grounding` module.
Must not: log any text from the profile or the reply, fall back to invented ratings, or import
`analysis/`, `diagram/` or `labels/` (they are peers, each removable on its own).
Spec 26 §3.3, §3.8, §4.1; AC-26.3, AC-26.11, AC-26.18.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.config import SolutionCatalogue
from app.models.process_discovery_schemas import StepRating

from ...domain.field_spec import Vocabulary
from ...llm import LLM, CallType, ChatMessage, LLMError
from .grounding import DROP_REASONS, ground_step_ratings
from .prompts import assess_steps_system, assess_steps_user
from .schemas import AssessStepsOut

__all__ = ["StepAssessmentFailedError", "ground_step_ratings", "run_step_assessment"]

logger = logging.getLogger("app.assessment")


class StepAssessmentFailedError(Exception):
    """The ASSESS_STEPS call returned nothing usable; no ratings are stored."""


def _log(
    outcome: str, started: float, catalogue: SolutionCatalogue, *, kept: int, dropped: Mapping[str, int],
    error: str = "",
) -> None:  # fmt: skip
    """The one `assessment_call` line (§3.8): counts and codes only, never text."""
    fields: dict[str, Any] = {
        "call": CallType.ASSESS_STEPS.value,
        "outcome": outcome,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "kept": kept,
        "dropped": dict(dropped),
        "placeholder_catalogue": catalogue.placeholder,
    }
    if error:
        fields["error"] = error
    logger.log(logging.INFO if outcome == "generated" else logging.WARNING, "assessment_call", extra=fields)


async def run_step_assessment(
    profile: Mapping[str, Any],
    llm: LLM,
    catalogue: SolutionCatalogue,
    *,
    vocab: Vocabulary,
    documents: Sequence[Mapping[str, str]] = (),
) -> tuple[list[StepRating], dict[str, int]]:
    """One ASSESS_STEPS call, grounded. Raises `StepAssessmentFailedError` on any `LLMError`."""
    messages: list[ChatMessage] = [
        {"role": "system", "content": assess_steps_system(catalogue)},
        {"role": "user", "content": assess_steps_user(profile, vocab=vocab, documents=documents)},
    ]
    started = time.monotonic()
    try:
        reply = await llm.generate_structured(AssessStepsOut, CallType.ASSESS_STEPS, messages)
    except LLMError as error:
        _log("failed", started, catalogue, kept=0, dropped=dict.fromkeys(DROP_REASONS, 0), error=type(error).__name__)
        raise StepAssessmentFailedError("The step assessment could not be generated.") from error
    ratings, dropped = ground_step_ratings(reply, profile, catalogue)
    _log("generated", started, catalogue, kept=sum(r.fit is not None for r in ratings), dropped=dropped)
    return ratings, dropped
