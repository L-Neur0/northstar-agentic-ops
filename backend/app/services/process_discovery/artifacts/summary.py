"""The summary that opens the report (spec 27 §3.5).

Why: the first thing a reader sees must tell the whole story in a few plain sentences: what was
mapped, how well AI fits, where to start, whether a dedicated solution suits it, the expert's own
target, how many hours go into it and what to prepare. Every number and level comes from code
(product rule 3), so the summary is fixed templates over facts already checked, never model text.
What: `build_summary` returns the sentences in order; each is left out when its data is missing.
Must not: call a model, read a clock, give a yes / no or go / no-go, or invent a number (the
"from-to" uses only the expert's own target, P13). Spec 27 §3.5; AC-27.7.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.core.config import SolutionCatalogue
from app.models.process_discovery_schemas import Questions, RouteSummary, StepRating, ValueResult

from ..domain.field_spec import Vocabulary, same_unit
from ..profile.shapes import as_mapping, process_of, rows_of
from ..profile.verdicts import field_counts, volume_words
from .questions import LEVEL_WORDS

FIT_WORDS = {"strong": "strong", "partial": "partial", "weak": "weak: rules or a script would do most of it"}
SIZE_WORDS = {"strong": "a large process", "partial": "a moderate process", "weak": "a small process"}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _metric(value: Any) -> str:
    m = as_mapping(value) or {}
    return " ".join(p for p in (_text(m.get("value")), _text(m.get("unit"))) if p) or _text(m.get("qualitative"))


def _start_with(questions: Questions | None, ratings: Sequence[StepRating], catalogue: SolutionCatalogue | None) -> str:
    """Sentence 3 (as built, 2026-11-21): the strong-fit steps and their routes, where AI fits best;
    the route headline (ordered by hours) is the fallback."""
    if questions is None or catalogue is None:
        return ""
    by_step = {r.step: r for r in ratings}
    groups: dict[str, list[int]] = {}
    for fit in questions.steps:
        rating = by_step.get(fit.step)
        solution = catalogue.get(rating.route_id) if rating is not None and rating.route_id else None
        if fit.level == "strong" and solution is not None:
            groups.setdefault(solution.name, []).append(fit.step)
    parts = [
        f"{'step' if len(n) == 1 else 'steps'} {_and([str(x) for x in n])} using {name}" for name, n in groups.items()
    ]
    return f"Suggested route: start with {_and(parts)}." if parts else ""


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def build_summary(
    profile: Mapping[str, Any],
    questions: Questions | None,
    route: RouteSummary | None,
    value: ValueResult | None,
    *,
    vocab: Vocabulary,
    ratings: Sequence[StepRating] | None = None,
    catalogue: SolutionCatalogue | None = None,
) -> list[str]:
    """The §3.5 sentences, in order."""
    process = process_of(profile)
    name = _text(process.get("name")) or "this process"
    department = _text(profile.get("department"))
    cluster = vocab.taxonomy.by_code(_text((as_mapping(process.get("cluster")) or {}).get("code")))
    where = f" in {department}" + (f" ({cluster.name})" if cluster else "") if department else ""
    parts = [f"{len(rows_of(profile))} steps"]
    runs = volume_words(profile, vocab=vocab)
    if runs:
        parts.append(f"about {runs}")
    today = _metric(process.get("baseline_metric"))
    if today:
        parts.append(f"{today} each time today")
    out = [f"We mapped {name}{where}: {', '.join(parts)}."]
    if questions is not None and questions.q1.level != "not_rated":
        reasons = " ".join(questions.q1.reasons)
        out.append(f"AI fit: {FIT_WORDS[questions.q1.level]}. {reasons}".strip())
    start = _start_with(questions, ratings or [], catalogue)
    if start:
        out.append(start)
    elif route is not None and route.headline:
        out.append(route.headline)
    if questions is not None and questions.q2.level != "not_rated":
        reasons = sorted(questions.q2.reasons, key=len)
        out.append(f"{LEVEL_WORDS['q2'][questions.q2.level]}: {' '.join(reasons)}".strip())
    target = as_mapping(process.get("target_metric")) or {}
    base = as_mapping(process.get("baseline_metric")) or {}
    if (
        field_counts(profile, "process.target_metric", vocab=vocab)
        and _text(target.get("unit"))
        and same_unit(_text(target.get("unit")), _text(base.get("unit")))
        and today
    ):
        out.append(f"The expert's target is {_metric(target)} instead of {today}.")
    if value is not None and value.hours_per_year is not None:
        size = SIZE_WORDS.get(questions.q3.level, "") if questions is not None else ""
        out.append(
            f"About {value.hours_per_year:,.0f} hours a year go into this process today"
            + (f": {size}." if size else ".")
        )
    if questions is not None and questions.prepare:
        out.append(f"Before starting: {questions.prepare[0]}")
    return out
