"""Completeness and the *Finish* check: how complete is the map, and may the expert finish (spec 13 §3.9–§3.10)?

Why: the guide prompt, the API and the screen all need the same two answers, and three copies of
the rule would disagree the first time one of them changes. One function each, so they cannot.
Proposed values, skipped cells, partial and invalid answers add nothing; declaring more steps
lowers the percentage (the denominator grows), which is correct.
What: `score` (filled points over `total_points_for(expected)`), `finish_check` (the four checks in
order, plus the advisory `looks_like_task` that never blocks) and `rejected_substep_count`.
Must not: write the profile, judge a process go / no-go, or let the advisory change `ready`.
Spec 13 §3.9–§3.10; AC-13.45 to AC-13.49. Amended 2026-11-21 (owner test): a skipped optional cell
leaves the total, and *Finish* no longer waits for the roles and systems confirmations (AC-13.62, AC-13.63).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NamedTuple

from ..domain.field_spec import COMPLETENESS_GATE, PROFILE_SPECS, STEP_SPECS, Vocabulary, total_points_for
from ..domain.scope import VERDICT_BORDERLINE, VERDICT_PROCESS, VERDICT_TASK
from .coercion import coerce_number
from .constants import FLAG_SUBSTEP_COUNT_REJECTED, FLAG_SUBSTEPS_COMPLETE
from .shapes import as_mapping, normalized_profile, process_of, rows_of
from .verdicts import cell_counts, cell_skipped, expected_steps, field_counts

BELOW_GATE = "below_gate"
SUBSTEPS_INCOMPLETE = "substeps_incomplete"
ROLES_NOT_CONFIRMED = "roles_not_confirmed"
TOOLS_NOT_CONFIRMED = "tools_not_confirmed"
#: Every reason `finish_check` can give, in check order (spec 12 `FinishBlock`). The two list codes stay in
#: the wire type for old clients and are never returned (spec 13 amended 2026-11-21, owner test).
FINISH_BLOCKS: tuple[str, ...] = (BELOW_GATE, SUBSTEPS_INCOMPLETE)


class Score(NamedTuple):
    """Completeness: `value` = filled / total, rounded to 4 decimals."""

    value: float
    filled_points: int
    total_points: int


class FinishCheck(NamedTuple):
    """Whether *Finish* is open, the first reason it is not, and the advisory task note."""

    ready: bool
    blocked_by: str | None
    looks_like_task: bool


def score(profile: Mapping[str, Any], *, vocab: Vocabulary) -> Score:
    """Weights of P fields that count plus weights of cells that count in rows `1..expected`.

    A skipped optional cell (S10, S11) leaves the total: the optional question never counts against the gate.
    """
    p = normalized_profile(profile)
    filled = sum(s.weight for s in PROFILE_SPECS if s.weight and field_counts(p, s.key, vocab=vocab))
    expected = expected_steps(p, vocab=vocab)
    left_out = 0
    for row in rows_of(p)[:expected]:
        filled += sum(s.weight for s in STEP_SPECS if s.weight and cell_counts(row, s.key, vocab=vocab))
        left_out += sum(s.weight for s in STEP_SPECS if s.optional and cell_skipped(row, s.key))
    total = total_points_for(expected) - left_out
    return Score(round(filled / total, 4) if total else 0.0, filled, total)


def _looks_like_task(scope: Mapping[str, Any] | None) -> bool:
    state = as_mapping(scope) or {}
    verdict = as_mapping(state.get("verdict")) or {}
    label = verdict.get("verdict")
    if label == VERDICT_PROCESS:
        return False
    if label == VERDICT_TASK:
        return True
    asked = state.get("widening_asked", state.get("wideningAsked"))
    if label == VERDICT_BORDERLINE:
        return asked is True
    return state.get("overridden") is True


def finish_check(
    profile: Mapping[str, Any], *, vocab: Vocabulary, scope: Mapping[str, Any] | None = None
) -> FinishCheck:
    """The one *Finish* rule: score ≥ 0.80 (exactly 0.80 passes) and the walk closed."""
    p = normalized_profile(profile)
    proc = process_of(p)
    advisory = _looks_like_task(scope)
    if score(p, vocab=vocab).value < COMPLETENESS_GATE:
        return FinishCheck(False, BELOW_GATE, advisory)
    if proc.get(FLAG_SUBSTEPS_COMPLETE) is not True:
        return FinishCheck(False, SUBSTEPS_INCOMPLETE, advisory)
    return FinishCheck(True, None, advisory)


def rejected_substep_count(profile: Mapping[str, Any]) -> int | None:
    """The parked out-of-range step count, or `None` when no number was refused."""
    raw = process_of(profile).get(FLAG_SUBSTEP_COUNT_REJECTED)
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    return coerce_number(raw) if raw is not None else None
