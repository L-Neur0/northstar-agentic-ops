"""The two classification gates and the widening state machine (spec 14 §3.1, §3.4; product F-06, F-07).

Why: CLASSIFY answers two separate questions about the named process, "is it a process or one
person's task?" (scope) and "which cluster?" (placement). An answer can pass one and fail the
other, so they are gated separately, and both are keyed on the process name: a new name
invalidates both verdicts, an unchanged name means the work is done and must not be paid for
twice. A first-pass `borderline` or `task` earns one widening question; two per session at most,
across renames (one is a clarification, a third is an interrogation).
What: `current_name` (P04 only when it counts), `needs_scope`, `needs_placement`,
`needs_classification`, `classification_subject` (the name, plus the widening question and the
expert's answer on a widening pass) and `apply_scope_verdict`.
Must not: call a model, write the profile or mutate its inputs.
Spec 14 §3.1, §3.4; AC-14.33 to AC-14.36. Amended 2026-11-21 (owner test, §3.20 O3): no widening
question for recurring work (AC-14.119).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..domain.field_spec import WIDENING_LIMIT, Vocabulary, recompute_derived
from ..domain.scope import RECURRING, VERDICT_BORDERLINE, VERDICT_TASK, refresh_scope_from_map
from ..profile.coercion import coerce_count
from ..profile.shapes import as_mapping, as_text, process_of, rows_of
from ..profile.verdicts import field_counts
from .replies import last_agent_message, last_expert_message


def current_name(profile: Mapping[str, Any] | None, *, vocab: Vocabulary) -> str:
    """The process name both verdicts are keyed on: P04 only when it counts (a proposal is not a name yet)."""
    if profile is None or not field_counts(profile, "process.name", vocab=vocab):
        return ""
    return as_text(process_of(profile).get("name"))


def _profile(state: Mapping[str, Any]) -> Mapping[str, Any]:
    return as_mapping(state.get("profile")) or {}


def needs_scope(state: Mapping[str, Any], *, vocab: Vocabulary) -> bool:
    """A counting name whose scope was not judged for it, or an outstanding widening question."""
    name = current_name(_profile(state), vocab=vocab)
    if not name:
        return False
    scope = as_mapping(state.get("scope")) or {}
    if scope.get("awaiting_widening") is True:
        return True
    return as_text(scope.get("scoped_for")) != name


def needs_placement(state: Mapping[str, Any], *, vocab: Vocabulary) -> bool:
    """A counting name with no cluster yet and no placement attempted for it. A counting P05 ends this for good."""
    profile = _profile(state)
    name = current_name(profile, vocab=vocab)
    if not name or field_counts(profile, "process.cluster", vocab=vocab):
        return False
    placement = as_mapping(state.get("placement")) or {}
    return as_text(placement.get("placed_for")) != name


def needs_classification(state: Mapping[str, Any], *, vocab: Vocabulary) -> bool:
    """The graph gate: does CLASSIFY have anything to do this turn?"""
    return needs_scope(state, vocab=vocab) or needs_placement(state, vocab=vocab)


def classification_subject(state: Mapping[str, Any], *, vocab: Vocabulary) -> str:
    """What CLASSIFY judges: the name; on a widening pass also the widening question and the expert's answer."""
    name = current_name(_profile(state), vocab=vocab)
    scope = as_mapping(state.get("scope")) or {}
    if not name or scope.get("awaiting_widening") is not True:
        return name
    answer = last_expert_message(state)
    if not answer:
        return name
    asked = last_agent_message(state)
    if asked:
        return f"{name}\n\nWidening question asked: {asked}\n\nFollow-up answer: {answer}"
    return f"{name}\n\nFollow-up answer: {answer}"


def apply_scope_verdict(
    scope: Mapping[str, Any], counters: Mapping[str, Any], verdict: Mapping[str, Any], name: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fold a fresh verdict into the widening machine; returns new `(scope, counters)`.

    First pass `borderline` or `task` with `widening_count < 2` arms one widening question and bumps
    the count, unless the work recurs: recurring individual work is a valid candidate (§3.20 O3). The second pass is terminal: the flag clears, `widening_asked` is recorded, and a
    second-pass `task` sets the sticky `overridden`.
    """
    second_pass = scope.get("awaiting_widening") is True
    new_scope: dict[str, Any] = {
        **dict(scope),
        "verdict": dict(verdict),
        "scoped_for": name,
        "awaiting_widening": False,
        "widening_asked": second_pass,
    }
    new_counters: dict[str, Any] = dict(counters)
    count = coerce_count(counters.get("widening_count"))
    new_counters["widening_count"] = count
    label = verdict.get("verdict")
    if second_pass:
        if label == VERDICT_TASK:
            new_scope["overridden"] = True
        return new_scope, new_counters
    recurring = (as_mapping(verdict.get("signals")) or {}).get(RECURRING) is True
    if label in (VERDICT_BORDERLINE, VERDICT_TASK) and not recurring and count < WIDENING_LIMIT:
        new_scope["awaiting_widening"] = True
        new_counters["widening_count"] = count + 1
    return new_scope, new_counters


def refresh_scope(scope: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    """The stored scope with its verdict refreshed from the mapped steps (spec 12 §3.13, spec 14 §3.21 P6).

    Roles are every step's S04 roles and S05 owner; systems every step's S06. The map only turns
    `multi_role` / `multi_system` on; the widening flags are never touched, so no question is re-armed.
    """
    verdict = as_mapping(scope.get("verdict"))
    if verdict is None:
        return dict(scope)
    rolled = recompute_derived(profile)
    owners = [str(r.get("owner") or "") for r in rows_of(profile)]
    roles = [*rolled.get("process.all_roles", []), *owners]
    refreshed = refresh_scope_from_map(verdict, roles=roles, systems=rolled.get("process.all_tools", []))
    return {**dict(scope), "verdict": refreshed}
