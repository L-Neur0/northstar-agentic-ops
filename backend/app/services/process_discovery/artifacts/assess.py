"""The assessment run: the four model calls of *Finish* in parallel, each bounded, then the code parts (spec 20 §3.1).

Why: the report must arrive in about the time of the slowest call, not the sum of four, and one
slow or broken call must cost only its own part of the report. So OPPORTUNITIES, MAP, LABEL and
ASSESS_STEPS start together, each under its own timeout, and each degrades on its own (a failed
map still gives the linear map; a failed refresh keeps what was stored). A call whose input did
not change since the previous run is reused instead of paid for again.
What: `assess` decides which calls to run (fingerprints, `refresh`), runs them with
`asyncio.gather` over `asyncio.wait_for`, maps every result or error to the stored part and its
outcome (spec 12 values; the log keeps the richer ones such as `timeout_linear`), then runs
`compute_code_parts` (hours, readiness, blocked_by, path, recommended route), and writes one
`assessment_run` log line. `PartOutcome` is what happened to each part.
Must not: raise (any exception inside a part degrades that part), save anything (the service
saves once), read a clock (`now` is passed in), or log profile or reply text.
Spec 20 §3.1, §4; AC-20.1 to AC-20.12, AC-20.45, AC-20.49.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.core.config import Rates, ReadinessConfig, SolutionCatalogue
from app.models.process_discovery_schemas import Assessment, ProcessDiagram, StepAssessment

from ..domain.field_spec import Vocabulary
from ..llm import LLM
from .analysis.analysis import OpportunitiesFailedError, OpportunitiesResult, carry_reviews, run_opportunities
from .assessment_code import compute_code_parts
from .diagram.diagram import MapCallFailedError, linear_process_diagram, run_map
from .fingerprint import ai_input_fingerprint, map_fingerprint
from .labels.labels import LabelsFailedError, run_labels
from .step_assessment.route import inputs_hash
from .step_assessment.steps import StepAssessmentFailedError, run_step_assessment

logger = logging.getLogger("app.assessment")

PartName = Literal["opportunities", "diagram", "labels", "steps"]
PARTS: tuple[PartName, ...] = ("opportunities", "diagram", "labels", "steps")
_EXPECTED = (OpportunitiesFailedError, MapCallFailedError, LabelsFailedError, StepAssessmentFailedError)


@dataclass(frozen=True)
class PartOutcome:
    part: PartName
    outcome: str
    duration_ms: int
    reused: bool


async def _bounded(factory: Callable[[], Awaitable[Any]], timeout: float) -> tuple[Any, int]:
    """The call's result, or the exception it ended with (a timeout included), and its duration."""
    started = time.monotonic()
    try:
        result: Any = await asyncio.wait_for(factory(), timeout)
    except Exception as exc:  # degrade per part; never let one call stop the others
        result = exc
    return result, int((time.monotonic() - started) * 1000)


def _failure(exc: BaseException) -> str:
    """The log word for a failed call: `timeout`, `failed` (an expected error) or `error` (anything else)."""
    if isinstance(exc, TimeoutError):
        return "timeout"
    return "failed" if isinstance(exc, _EXPECTED) else "error"


async def assess(
    profile: Mapping[str, Any],
    previous: Assessment | None,
    llm: LLM,
    rates: Rates,
    readiness_cfg: ReadinessConfig,
    now: str,
    *,
    catalogue: SolutionCatalogue,
    vocab: Vocabulary,
    documents: Sequence[Mapping[str, str]] = (),
    refresh: bool = False,
    timeout: float = 60.0,
) -> tuple[Assessment, list[PartOutcome]]:
    """A new assessment and what happened to each part. Never raises."""
    started = time.monotonic()
    ai_hash, map_hash, steps_in = (
        ai_input_fingerprint(profile),
        map_fingerprint(profile),
        inputs_hash(profile, catalogue),
    )
    prev = previous
    was = dict(prev.outcomes) if prev is not None else {}
    ai_same = prev is not None and prev.steps_hash == ai_hash
    reuse: dict[PartName, bool] = {
        "opportunities": ai_same and was.get("opportunities") == "generated",
        "labels": ai_same and was.get("labels") == "generated",
        "steps": prev is not None and prev.step_assessment is not None
        and prev.step_assessment.inputs_hash == steps_in and was.get("steps") == "generated",
        "diagram": prev is not None and prev.diagram is not None
        and prev.diagram.steps_hash == map_hash and was.get("diagram") == "generated",
    }  # fmt: skip
    if refresh:
        reuse = dict.fromkeys(PARTS, False)

    calls: dict[PartName, Callable[[], Awaitable[Any]]] = {
        "opportunities": lambda: run_opportunities(profile, llm, rates, vocab=vocab, documents=documents),
        "diagram": lambda: run_map(profile, llm, vocab=vocab, documents=documents),
        "labels": lambda: run_labels(profile, llm, vocab=vocab, documents=documents),
        "steps": lambda: run_step_assessment(profile, llm, catalogue, vocab=vocab, documents=documents),
    }
    wanted: list[PartName] = [p for p in PARTS if not reuse[p]]
    results = await asyncio.gather(*(_bounded(calls[p], timeout) for p in wanted), return_exceptions=True)
    got: dict[PartName, tuple[Any, int]] = {}
    for part, result in zip(wanted, results, strict=True):
        got[part] = result if isinstance(result, tuple) else (result, 0)

    outcomes: dict[str, str] = {}
    logs: list[PartOutcome] = []

    def keep(part: PartName) -> None:
        if part in was:
            outcomes[part] = was[part]

    # Opportunities, stay human and the summary.
    summary = prev.summary if prev is not None else ""
    opportunities = list(prev.opportunities) if prev is not None else []
    stay_human = list(prev.stay_human) if prev is not None else []
    if "opportunities" in got:
        result, ms = got["opportunities"]
        if isinstance(result, OpportunitiesResult):
            summary, stay_human = result.summary, result.stay_human
            opportunities = carry_reviews(opportunities, result.opportunities)
            outcomes["opportunities"], word = "generated", "generated"
        elif was.get("opportunities") == "generated":
            keep("opportunities")
            word = "error" if _failure(result) == "error" else f"refresh_{_failure(result)}"
        else:
            summary, opportunities, stay_human = "", [], []
            outcomes["opportunities"], word = "failed", _failure(result)
        logs.append(PartOutcome("opportunities", word, ms, False))
    else:
        keep("opportunities")

    # The process map.
    diagram: ProcessDiagram | None = prev.diagram if prev is not None else None
    if "diagram" in got:
        result, ms = got["diagram"]
        if isinstance(result, ProcessDiagram):
            diagram = result
            outcomes["diagram"] = word = "fallback" if result.simplified else "generated"
        elif diagram is not None and was.get("diagram") == "generated":
            keep("diagram")
            word = "error" if _failure(result) == "error" else f"refresh_{_failure(result)}"
        else:
            failure = _failure(result)
            try:
                diagram = linear_process_diagram(profile)
            except Exception:  # pragma: no cover - the linear map is code; kept total for safety
                diagram = None
            outcomes["diagram"] = "fallback"
            word = "error" if failure == "error" else f"{failure}_linear"
        logs.append(PartOutcome("diagram", word, ms, False))
    else:
        keep("diagram")

    # Labels.
    labels = list(prev.labels) if prev is not None else []
    if "labels" in got:
        result, ms = got["labels"]
        if isinstance(result, tuple) and not isinstance(result, BaseException):
            labels, outcomes["labels"], word = list(result[0]), "generated", "generated"  # pyright: ignore[reportUnknownArgumentType]
        elif was.get("labels") == "generated":
            keep("labels")
            word = "error" if _failure(result) == "error" else f"refresh_{_failure(result)}"
        else:
            labels, outcomes["labels"], word = [], "failed", _failure(result)
        logs.append(PartOutcome("labels", word, ms, False))
    else:
        keep("labels")

    # The step-by-step assessment (the route is added by code below).
    step_assessment = prev.step_assessment if prev is not None else None
    if "steps" in got:
        result, ms = got["steps"]
        if isinstance(result, tuple) and not isinstance(result, BaseException):
            step_assessment = StepAssessment(
                steps=list(result[0]),  # pyright: ignore[reportUnknownArgumentType]
                inputs_hash=steps_in,
                placeholder_catalogue=catalogue.placeholder,
            )
            outcomes["steps"], word = "generated", "generated"
        elif step_assessment is not None and was.get("steps") == "generated":
            keep("steps")
            word = "error" if _failure(result) == "error" else f"refresh_{_failure(result)}"
        else:
            step_assessment, outcomes["steps"], word = None, "failed", _failure(result)
        logs.append(PartOutcome("steps", word, ms, False))
    else:
        keep("steps")

    for part in PARTS:
        if reuse[part]:
            logs.append(PartOutcome(part, "reused", 0, True))

    ratings = step_assessment.steps if step_assessment is not None else []
    value, readiness, opportunities, path, route = compute_code_parts(
        profile, opportunities, labels, ratings, outcomes, rates, readiness_cfg, catalogue,
        prev.readiness if prev is not None else None,
    )  # fmt: skip
    if step_assessment is not None:
        step_assessment = step_assessment.model_copy(update={"route": route})

    assessment = Assessment(
        summary=summary,
        opportunities=opportunities,
        stay_human=stay_human,
        diagram=diagram,
        labels=labels,
        value=value,
        readiness=readiness,
        path=path,
        step_assessment=step_assessment,
        steps_hash=ai_hash,
        generated_at=now,
        outcomes=outcomes,  # pyright: ignore[reportArgumentType]
    )
    order = {p: i for i, p in enumerate(PARTS)}
    logs.sort(key=lambda o: order[o.part])
    logger.info(
        "assessment_run",
        extra={
            "run": [o.part for o in logs if not o.reused],
            "reused": [o.part for o in logs if o.reused],
            "outcomes": {o.part: o.outcome for o in logs},
            "duration_ms": int((time.monotonic() - started) * 1000),
        },
    )
    return assessment, logs
