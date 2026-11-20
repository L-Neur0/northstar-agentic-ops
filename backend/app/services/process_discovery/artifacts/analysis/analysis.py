"""The OPPORTUNITIES call and the grounding of its reply in the profile (spec 18 §3.4–3.6, §3.9).

Why: the opportunities are the heart of the report, and a model can cite a step that does not exist,
quote words nobody said, or grade a change "very high". Structured Outputs fixes the reply's shape;
nothing fixes its content, so code checks each entry on its own and drops what it cannot ground: one
bad entry never costs the others. Unlike the map, there is no fallback content: a failed call is a
failure the report shows as a note, while an empty list is a real answer.
What: `run_opportunities` (one `generate_structured` call, any `LLMError` → `OpportunitiesFailedError`,
one `assessment_call` log line); `ground_opportunities` (pure: rules O1–O9 and the stay-human
checks, counting drops by reason); `carry_reviews` (keeps specialist reviews across a re-run).
Must not: trust a step number, a type, a grade or a quote from the model; estimate hours or money;
log any text from the profile or the reply; import `artifacts/diagram`.
Spec 18 §3.4–3.6, §3.9, §4.2; AC-18.4 to AC-18.17, AC-18.39.
"""

from __future__ import annotations

import logging
import time
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Rates
from app.models.process_discovery_schemas import Grade, Opportunity, OpportunityType, StayHuman

from ...domain.field_spec import Vocabulary
from ...llm import LLM, CallType, ChatMessage, LLMError
from ...profile.shapes import as_list, as_mapping, rows_of
from ..evidence import Value, find_evidence, profile_values
from .prompts import OPPORTUNITIES_SYSTEM, opportunities_user
from .schemas import OpportunitiesOut

logger = logging.getLogger("app.assessment")

MAX_RAW_ENTRIES = 50  # O1
MAX_OPPORTUNITIES = 12  # O8
MAX_STAY_HUMAN = 6
MAX_TITLE_CHARS = 200  # O4
MAX_TEXT_CHARS = 1500  # O5, summary
MAX_REASON_CHARS = 600  # stay-human reason
_ELLIPSIS = "…"
_TYPES = {t.value for t in OpportunityType}
_GRADES = {g.value for g in Grade}
DROP_REASONS: tuple[str, ...] = ("step", "quote", "invalid", "cap")


class OpportunitiesFailedError(Exception):
    """The OPPORTUNITIES call returned nothing usable. Distinct from "returned no opportunities"."""


@dataclass(frozen=True)
class OpportunitiesResult:
    summary: str
    opportunities: list[Opportunity]
    stay_human: list[StayHuman]
    dropped: dict[str, int] = field(default_factory=lambda: dict.fromkeys(DROP_REASONS, 0))


def _clean(value: Any, limit: int) -> str:
    """One line: non-strings → "", control characters → space, whitespace collapsed, cut with "…"."""
    if not isinstance(value, str):
        return ""
    text = "".join(" " if unicodedata.category(ch).startswith("C") else ch for ch in value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + _ELLIPSIS


def _steps(raw: Any, step_count: int) -> list[int] | None:
    """Sorted, de-duplicated real step numbers; `None` when any entry is not a real step (O2)."""
    items = as_list(raw)
    if items is None:
        return None
    if not all(isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= step_count for n in items):
        return None
    return sorted(set(items))


def _opportunity(entry: Mapping[str, Any], step_count: int, values: Sequence[Value], rates: Rates) -> Opportunity | str:
    """A grounded opportunity (without its id), or the drop reason."""
    steps = _steps(entry.get("steps"), step_count)
    if steps is None:
        return "step"
    kind = entry.get("type")
    title = _clean(entry.get("title"), MAX_TITLE_CHARS)
    what_changes = _clean(entry.get("what_changes"), MAX_TEXT_CHARS)
    how = _clean(entry.get("how"), MAX_TEXT_CHARS)
    impact, feasibility = entry.get("impact"), entry.get("feasibility")
    if kind not in _TYPES or not title or not what_changes or not how or impact not in _GRADES:
        return "invalid"
    if feasibility not in _GRADES:
        return "invalid"
    hit = find_evidence(entry.get("evidence"), values)
    if hit is None:
        return "quote"
    return Opportunity(
        id="",
        title=title,
        substeps=steps,
        type=OpportunityType(kind),
        what_changes=what_changes,
        how=how,
        prepare_first=_clean(entry.get("prepare_first"), MAX_TEXT_CHARS),
        impact=Grade(impact),
        impact_reason=_clean(entry.get("impact_reason"), MAX_TEXT_CHARS),
        feasibility=Grade(feasibility),
        feasibility_reason=_clean(entry.get("feasibility_reason"), MAX_TEXT_CHARS),
        evidence=hit.quote,
        saving_share=rates.saving_share[kind],  # parked (R5): stored, read by nothing
        evidence_key=hit.key,
        evidence_source=hit.source,
    )


def _stay_human(entry: Mapping[str, Any], step_count: int, values: Sequence[Value]) -> StayHuman | str:
    steps = _steps(entry.get("steps"), step_count)
    if not steps:
        return "step"
    reason = _clean(entry.get("reason"), MAX_REASON_CHARS)
    if not reason:
        return "invalid"
    hit = find_evidence(entry.get("evidence"), values)
    if hit is None:
        return "quote"
    return StayHuman(substeps=steps, reason=reason, evidence=hit.quote, evidence_key=hit.key)


def ground_opportunities(
    reply: OpportunitiesOut | Mapping[str, Any], profile: Mapping[str, Any], rates: Rates
) -> OpportunitiesResult:
    """The reply with every entry checked against `profile` (O1–O9). Pure; never raises on bad content."""
    data = reply.model_dump() if isinstance(reply, OpportunitiesOut) else as_mapping(reply) or {}
    step_count = len(rows_of(profile))
    values = profile_values(profile)
    dropped: dict[str, int] = dict.fromkeys(DROP_REASONS, 0)

    raw = as_list(data.get("opportunities")) or []
    dropped["cap"] += max(len(raw) - MAX_RAW_ENTRIES, 0)
    kept: list[Opportunity] = []
    for entry in raw[:MAX_RAW_ENTRIES]:
        mapping = as_mapping(entry)
        result = _opportunity(mapping, step_count, values, rates) if mapping is not None else "invalid"
        if isinstance(result, str):
            dropped[result] += 1
        elif len(kept) >= MAX_OPPORTUNITIES:
            dropped["cap"] += 1
        else:
            kept.append(result.model_copy(update={"id": f"o{len(kept) + 1}"}))

    raw_stay = as_list(data.get("stay_human")) or []
    dropped["cap"] += max(len(raw_stay) - MAX_RAW_ENTRIES, 0)
    stay: list[StayHuman] = []
    for entry in raw_stay[:MAX_RAW_ENTRIES]:
        mapping = as_mapping(entry)
        result = _stay_human(mapping, step_count, values) if mapping is not None else "invalid"
        if isinstance(result, str):
            dropped[result] += 1
        elif len(stay) >= MAX_STAY_HUMAN:
            dropped["cap"] += 1
        else:
            stay.append(result)

    summary = _clean(data.get("summary"), MAX_TEXT_CHARS)
    return OpportunitiesResult(summary=summary, opportunities=kept, stay_human=stay, dropped=dropped)


def carry_reviews(old: Sequence[Opportunity], new: Sequence[Opportunity]) -> list[Opportunity]:
    """Each new opportunity takes the review of the first unused old one with the same type and steps."""
    unused = list(old)
    out: list[Opportunity] = []
    for opportunity in new:
        match = next(
            (o for o in unused if o.type == opportunity.type and sorted(o.substeps) == sorted(opportunity.substeps)),
            None,
        )
        if match is None:
            out.append(opportunity.model_copy(update={"review": "pending", "review_note": ""}))
            continue
        unused.remove(match)
        update: dict[str, Any] = {"review": match.review, "review_note": match.review_note}
        if match.review == "adjusted":
            update["saving_share"] = match.saving_share
        out.append(opportunity.model_copy(update=update))
    return out


def _log(outcome: str, started: float, *, kept: int, dropped: Mapping[str, int], error: str = "") -> None:
    """The one `assessment_call` line (§3.9): counts and codes only, never text."""
    fields: dict[str, Any] = {
        "call": CallType.OPPORTUNITIES.value,
        "outcome": outcome,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "kept": kept,
        "dropped": dict(dropped),
    }
    if error:
        fields["error"] = error
    logger.log(logging.INFO if outcome == "generated" else logging.WARNING, "assessment_call", extra=fields)


async def run_opportunities(
    profile: Mapping[str, Any],
    llm: LLM,
    rates: Rates,
    *,
    vocab: Vocabulary,
    documents: Sequence[Mapping[str, str]] = (),
) -> OpportunitiesResult:
    """One OPPORTUNITIES call, grounded. Raises `OpportunitiesFailedError` on any `LLMError`."""
    messages: list[ChatMessage] = [
        {"role": "system", "content": OPPORTUNITIES_SYSTEM},
        {"role": "user", "content": opportunities_user(profile, vocab=vocab, documents=documents)},
    ]
    started = time.monotonic()
    try:
        reply = await llm.generate_structured(OpportunitiesOut, CallType.OPPORTUNITIES, messages)
    except LLMError as error:
        _log("failed", started, kept=0, dropped=dict.fromkeys(DROP_REASONS, 0), error=type(error).__name__)
        raise OpportunitiesFailedError("The opportunities could not be generated.") from error
    result = ground_opportunities(reply, profile, rates)
    _log("generated", started, kept=len(result.opportunities), dropped=result.dropped)
    return result
