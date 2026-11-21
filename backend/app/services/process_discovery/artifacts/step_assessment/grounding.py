"""Checks every step rating the model returns against the profile and the solution catalogue (spec 26 §3.5).

Why: the model's reply has the right shape (strict schema) but none of its content is trusted. It
may rate a step that does not exist, quote words the expert never said (or said about another
step), or pick a route that is not one of the company's tools or does not serve the step's fit.
Code checks each entry on its own: a bad entry is dropped and counted, never fatal, and a bad route
only loses the route, not the rating.
What: `ground_step_ratings` applies rules A1–A10 and returns one `StepRating` per step 1..N in order
(a step without a kept entry is *not assessed*) plus the drop counts by reason.
Must not: call a model, read a clock, do I/O, trust a step name from the model, or keep a route id
that is not in the catalogue (product rule 8: company tools come from configuration).
Spec 26 §3.5, §4.1; AC-26.4 to AC-26.10, AC-26.17. Spec 27 §3.2: signals grounded in that step's words
(a dropped signal counts as false), and `raw_motivations`; AC-27.2.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any

from app.core.config import SolutionCatalogue
from app.models.process_discovery_schemas import StepRating

from ...profile.shapes import as_list, as_mapping, rows_of
from ..evidence import find_evidence, profile_values, restrict_to_step, restrict_to_step_or_process
from .schemas import AssessStepsOut

MAX_RAW_ENTRIES = 50  # A1
MAX_REASON_CHARS = 600  # A4
MAX_ROUTE_REASON_CHARS = 400  # A8
FITS = ("automate", "assist", "human")
SIGNAL_NAMES = frozenset(
    ("reads_unstructured", "compares_to_criteria", "finds_patterns", "drafts_text", "must_be_exact", "fixed_rules")
)
MOTIVATION_KEYS = {"q1": "fit_motivation", "q2": "assistant_motivation", "q3": "worth_motivation"}
DROP_REASONS: tuple[str, ...] = ("step", "quote", "invalid", "cap", "route", "signal")
_ELLIPSIS = "…"


def clean_text(value: Any, limit: int) -> str:
    """One paragraph: non-strings → "", control characters → space, whitespace collapsed, cut with "…"."""
    if not isinstance(value, str):
        return ""
    text = "".join(" " if unicodedata.category(ch).startswith("C") else ch for ch in value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + _ELLIPSIS


def ground_step_ratings(
    reply: AssessStepsOut | Mapping[str, Any], profile: Mapping[str, Any], catalogue: SolutionCatalogue
) -> tuple[list[StepRating], dict[str, int]]:
    """One rating per step 1..N (unassessed steps have `fit = None`) and the drop counts. Pure."""
    data = reply.model_dump() if isinstance(reply, AssessStepsOut) else as_mapping(reply) or {}
    rows = rows_of(profile)
    names = [str(row.get("name") or "").strip() for row in rows]
    values = profile_values(profile)
    dropped = dict.fromkeys(DROP_REASONS, 0)
    raw = as_list(data.get("steps")) or []
    dropped["cap"] = max(len(raw) - MAX_RAW_ENTRIES, 0)
    kept: dict[int, StepRating] = {}
    seen: set[int] = set()

    for item in raw[:MAX_RAW_ENTRIES]:
        entry = as_mapping(item)
        if entry is None:
            dropped["invalid"] += 1
            continue
        step = entry.get("step")
        if not isinstance(step, int) or isinstance(step, bool) or not 1 <= step <= len(rows) or step in seen:
            dropped["step"] += 1
            continue
        seen.add(step)
        fit = entry.get("fit")
        reason = clean_text(entry.get("reason"), MAX_REASON_CHARS)
        if fit not in FITS or not reason:
            dropped["invalid"] += 1
            continue
        hit = find_evidence(entry.get("evidence"), restrict_to_step_or_process(values, step))
        if hit is None:
            dropped["quote"] += 1
            continue
        route = entry.get("route")
        route_id = route.strip() if isinstance(route, str) else ""
        solution = catalogue.get(route_id) if route_id else None
        if route_id and (solution is None or fit not in solution.fits):
            dropped["route"] += 1
            solution = None
        signals: dict[str, bool] = {}
        signal_evidence: dict[str, str] = {}
        for raw_signal in as_list(entry.get("signals")) or []:  # spec 27 §3.2: only that step's words
            sig = as_mapping(raw_signal) or {}
            name = sig.get("name")
            quote = find_evidence(sig.get("evidence"), restrict_to_step(values, step))
            if name not in SIGNAL_NAMES or quote is None:
                dropped["signal"] += 1
                continue
            signals[str(name)], signal_evidence[str(name)] = True, quote.quote
        kept[step] = StepRating(
            step=step,
            name=names[step - 1],
            fit=fit,
            reason=reason,
            evidence=hit.quote,
            evidence_key=hit.key,
            evidence_source=hit.source,
            route_id=solution.id if solution is not None else None,
            route_reason=clean_text(entry.get("route_reason"), MAX_ROUTE_REASON_CHARS) if solution else "",
            signals=signals,
            signal_evidence=signal_evidence,
        )

    ratings = [kept.get(k) or StepRating(step=k, name=names[k - 1]) for k in range(1, len(rows) + 1)]
    return ratings, dropped


def raw_motivations(reply: AssessStepsOut | Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    """The three motivations as (text, quote), unchecked: `questions.answer_questions` keeps a motivation
    only when its quote is the expert's words (spec 27 §3.2)."""
    data = reply.model_dump() if isinstance(reply, AssessStepsOut) else as_mapping(reply) or {}
    out: dict[str, tuple[str, str]] = {}
    for key, field in MOTIVATION_KEYS.items():
        item = as_mapping(data.get(field)) or {}
        text, quote = clean_text(item.get("text"), 400), clean_text(item.get("evidence"), 400)
        if text and quote:
            out[key] = (text, quote)
    return out
