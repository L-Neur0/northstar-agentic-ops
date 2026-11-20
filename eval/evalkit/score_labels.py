"""Labels the product decides by code, checked by code: cluster, scope, steering, step fit and route (spec 24 §3.9).

Why: the cluster, the process-or-task verdict, the steering recommendation and each step's AI fit
and catalogue route are exact labels, so they need no judge. Checking them by code against the
persona's `expected` block keeps those scores exact and free.
What: `score_labels` reads the final `SessionOut`, the stored session (in process, for the steering
state), the ideas list and the report's step rows, and returns hits and misses. Steering names
match by normalised containment either way ("onboarding new site staff" and "onboarding").
Must not: guess when data is absent: no stored session (URL mode) makes steering `None` (n/a).
Spec 24 §3.9; AC-24.19.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from .persona import Persona
from .play import PersonaRun
from .score_fields import align_steps, normalise


class LabelScores(BaseModel):
    cluster: bool
    scope: bool | None
    steering: bool | None
    fit_hits: int = 0
    route_hits: int = 0
    routed_steps: int = 0


def names_contain(a: Any, b: Any) -> bool:
    na, nb = normalise(a), normalise(b)
    return bool(na and nb) and (na in nb or nb in na)


def _steering(persona: Persona, run: PersonaRun) -> bool | None:
    stored = run.stored
    if stored is None:
        return None
    steering = stored.get("steering") or {}
    expected = persona.expected.steering
    if expected is None:
        return steering.get("status", "off") == "off"
    names = {c.get("id"): c.get("name") for c in steering.get("candidates") or []}
    recommended = names.get(steering.get("recommendedId"))  # the stored session is dumped with its camelCase aliases
    chosen = ((run.session.get("profile") or {}).get("process") or {}).get("name")
    idea_names = [i.get("name") for i in run.ideas]
    ideas_ok = all(any(names_contain(n, got) for got in idea_names) for n in expected.ideas)
    return names_contain(recommended, expected.recommended) and names_contain(chosen, expected.chosen) and ideas_ok


def score_labels(persona: Persona, run: PersonaRun) -> LabelScores:
    session: Mapping[str, Any] = run.session
    process = (session.get("profile") or {}).get("process") or {}
    cluster = (process.get("cluster") or {}).get("code") == persona.expected.cluster
    scope_out = session.get("scope") or {}
    scope = scope_out.get("verdict") == persona.expected.scope if run.finished else None  # judged at Finish only
    rows = list(((run.report or {}).get("steps") or {}).get("rows") or [])
    captured_steps = [{"name": r.get("name")} for r in rows]
    by_number = {r.get("number"): r for r in rows}
    fit_hits = route_hits = 0
    for true_n, cap_n in align_steps(persona.truth.steps, captured_steps):
        expected = persona.expected.routes.get(true_n)
        if expected is None:
            continue
        row = by_number.get(cap_n) or {}
        fit_hits += row.get("fit") in expected.fit
        route_hits += row.get("routeId") in expected.route
    return LabelScores(
        cluster=cluster,
        scope=scope,
        steering=_steering(persona, run),
        fit_hits=fit_hits,
        route_hits=route_hits,
        routed_steps=len(persona.expected.routes) if run.report is not None else 0,  # no report: fit and route n/a
    )
