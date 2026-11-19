"""Which phase the interview is in, what is still missing, and what the next question is about (spec 14 §3.3, §3.5, §3.6, §3.8).

Why: the interview has no script. The phase is recomputed from the profile and the counters every
turn, and code chooses the one ask target the guide must voice, so the model can never wander
between fields or skip one. Every loop has a counter and every counter a maximum: a process field
is deferred after 3 asks and given up after 2 more; a step cell is settled after 3; the find
posture escalates on schedule; the list confirmation changes manner after 6 turns.
What: field limits and states (`deferred_keys`, `given_up_keys`), `phase_blocks`,
`phase_from_state`, `advance_phase` (collecting phases never move backwards; the tail may step
back; terminals never change), `missing_fields`, `step_focus`, `posture`, `proposal_group`,
`next_ask`, `charge_asks` and `cell_escapes`.
Must not: write the profile, call a model, read a clock or mutate its inputs; every function
derives what it needs from the whole `counters` so no caller can forget a set.
Spec 14 §3.3, §3.5, §3.6, §3.8; AC-14.20 to AC-14.30, AC-14.41 to AC-14.43.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from ..domain.field_spec import (
    CELL_ASK_LIMIT,
    COLLECTING_PHASES,
    CONFIRM_TURN_LIMIT,
    FIELD_ASK_LIMIT,
    FIND_DIRECT_TURN,
    FIND_FOCUS_TURN,
    NONE_KEY,
    PHASE_CONFIRM,
    PHASE_CONTEXT,
    PHASE_FIND,
    PHASE_FINISHED,
    PHASE_NO_CANDIDATE,
    PHASE_ORDER,
    PHASE_REVIEW,
    PHASE_STEPS,
    PROFILE_SPECS,
    REVIEW_ASK_LIMIT,
    STATUS_INVALID,
    STEP_SPECS,
    FieldSpec,
    Vocabulary,
    has_any_answer,
    specs_for_phase,
    step_cell_key,
)
from ..domain.scope import proposable_code
from ..profile.coercion import coerce_count
from ..profile.constants import (
    FLAG_SUBSTEPS_COMPLETE,
    NONE_ROW_LEAVES,
    ROLLUP_FLAGS,
    ROLLUP_KEYS,
    ROLLUP_TARGETS,
)
from ..profile.proposals import proposed_keys
from ..profile.shapes import as_list, as_mapping, normalized_profile, parse_step_key, process_of, rows_of
from ..profile.verdicts import (
    P16_KEY,
    cell_counts,
    cell_proposed,
    cell_skipped,
    current_step_index,
    expected_steps,
    field_counts,
    grade,
)
from .types import Ask

PROPOSAL_GROUP_MAX = 4
#: Q4 (spec 14): a given-up field is offered once more in the wrap-up with an easy way to settle it.
WRAP_UP_ASKS = 1
TERMINAL_PHASES: tuple[str, ...] = (PHASE_FINISHED, PHASE_NO_CANDIDATE)
_TAIL: tuple[str, ...] = (PHASE_STEPS, PHASE_CONFIRM, PHASE_REVIEW)
CLUSTER_KEY = "process.cluster"
NAME_KEY = "process.name"

Posture = Literal["open", "narrowed", "direct"]


# --- Counters -------------------------------------------------------------------------------------


def _asks(counters: Mapping[str, Any], name: str) -> dict[str, int]:
    raw = as_mapping(counters.get(name)) or {}
    return {str(k): coerce_count(v) for k, v in raw.items()}


def read_counters(counters: Mapping[str, Any] | None) -> dict[str, Any]:
    """A clean copy of the counters: every stored value that is not a non-negative int reads as 0."""
    source = counters or {}
    return {
        "field_asks": _asks(source, "field_asks"),
        "cell_asks": _asks(source, "cell_asks"),
        "find_turns": coerce_count(source.get("find_turns")),
        "widening_count": coerce_count(source.get("widening_count")),
        "confirm_turns": coerce_count(source.get("confirm_turns")),
    }


def field_limit(spec: FieldSpec) -> int:
    """The spec's own `max_asks`, else `FIELD_ASK_LIMIT` (3)."""
    return spec.max_asks or FIELD_ASK_LIMIT


def cell_limit(spec: FieldSpec) -> int:
    """The leaf's own `max_asks` (S12: 1), else `CELL_ASK_LIMIT` (3)."""
    return spec.max_asks or CELL_ASK_LIMIT


def field_asks(counters: Mapping[str, Any], key: str) -> int:
    return read_counters(counters)["field_asks"].get(key, 0)


def cell_asks(counters: Mapping[str, Any], key: str) -> int:
    return read_counters(counters)["cell_asks"].get(key, 0)


def _state(profile: Mapping[str, Any], spec: FieldSpec, counters: Mapping[str, Any], vocab: Vocabulary) -> str:
    if field_counts(profile, spec.key, vocab=vocab):
        return "counts"
    asks = field_asks(counters, spec.key)
    limit = field_limit(spec)
    if asks < limit:
        return "open"
    if asks < limit + REVIEW_ASK_LIMIT:
        return "deferred"
    return "given_up"


def deferred_keys(profile: Mapping[str, Any], counters: Mapping[str, Any], *, vocab: Vocabulary) -> list[str]:
    """Process fields asked their limit without counting, not yet given up (asked again in review)."""
    return [s.key for s in PROFILE_SPECS if _state(profile, s, counters, vocab) == "deferred"]


def given_up_keys(profile: Mapping[str, Any], counters: Mapping[str, Any], *, vocab: Vocabulary) -> list[str]:
    """Process fields asked limit + 2 times without counting: never asked again; they lower the score."""
    return [s.key for s in PROFILE_SPECS if _state(profile, s, counters, vocab) == "given_up"]


def _blocking(profile: Mapping[str, Any], phase: str, counters: Mapping[str, Any], vocab: Vocabulary) -> list[str]:
    out: list[str] = []
    for spec in specs_for_phase(phase):
        state = _state(profile, spec, counters, vocab)
        if state == "open" or (state == "deferred" and grade(profile, spec.key, vocab=vocab).status == STATUS_INVALID):
            out.append(spec.key)
    return out


def phase_blocks(profile: Mapping[str, Any], phase: str, counters: Mapping[str, Any], *, vocab: Vocabulary) -> bool:
    """A collecting phase holds while a field is open, or deferred with an invalid answer ("13 steps")."""
    return bool(_blocking(profile, phase, counters, vocab))


def phase_from_state(profile: Mapping[str, Any], counters: Mapping[str, Any], *, vocab: Vocabulary) -> str:
    """The first collecting phase that blocks; else `steps` until the walk closes; else `confirm`; else `review`."""
    p = normalized_profile(profile)
    for phase in COLLECTING_PHASES:
        if phase_blocks(p, phase, counters, vocab=vocab):
            return phase
    proc = process_of(p)
    if proc.get(FLAG_SUBSTEPS_COMPLETE) is not True:
        return PHASE_STEPS
    if not all(proc.get(ROLLUP_FLAGS[t]) is True for t in ROLLUP_TARGETS):
        return PHASE_CONFIRM
    return PHASE_REVIEW


def advance_phase(profile: Mapping[str, Any], current: str, counters: Mapping[str, Any], *, vocab: Vocabulary) -> str:
    """Move forward; the tail (`steps`, `confirm`, `review`) may step back; terminals never change."""
    if current in TERMINAL_PHASES:
        return current
    computed = phase_from_state(profile, counters, vocab=vocab)
    if current in (PHASE_CONFIRM, PHASE_REVIEW) and computed in _TAIL:
        return computed
    current_index = PHASE_ORDER.index(current) if current in PHASE_ORDER else 0
    return PHASE_ORDER[max(current_index, PHASE_ORDER.index(computed))]


# --- The step walk --------------------------------------------------------------------------------


def _cell_open(row: Mapping[str, Any], leaf: str, vocab: Vocabulary) -> bool:
    return not cell_counts(row, leaf, vocab=vocab) and not cell_skipped(row, leaf)


def _walk_leaves(index: int, expected: int) -> list[FieldSpec]:
    """S01→S12; the last step's hand-over is never asked (there is no next step)."""
    return [s for s in STEP_SPECS if not (s.key == "handover" and index >= expected)]


def step_focus(profile: Mapping[str, Any], *, vocab: Vocabulary) -> str | None:
    """The one cell to ask next: P16 while there is no count; else the first open, unproposed cell; else `None`."""
    p = normalized_profile(profile)
    expected = expected_steps(p, vocab=vocab)
    if expected == 0:
        return P16_KEY
    rows = rows_of(p)
    for index in range(1, min(expected, len(rows)) + 1):
        row = rows[index - 1]
        for spec in _walk_leaves(index, expected):
            if _cell_open(row, spec.key, vocab) and not cell_proposed(row, spec.key):
                return step_cell_key(index, spec.key)
    return None


def _focus_step(profile: Mapping[str, Any], vocab: Vocabulary) -> int | None:
    focus = step_focus(profile, vocab=vocab)
    parsed = parse_step_key(focus) if focus else None
    if parsed is not None:
        return parsed[0]
    return current_step_index(profile, vocab=vocab)


def missing_fields(
    profile: Mapping[str, Any], phase: str, counters: Mapping[str, Any], *, vocab: Vocabulary
) -> list[str]:
    """The keys still missing for `phase`, in ask order (§3.3 table)."""
    p = normalized_profile(profile)
    if phase in COLLECTING_PHASES:
        return _blocking(p, phase, counters, vocab)
    if phase == PHASE_STEPS:
        if expected_steps(p, vocab=vocab) == 0:
            return [P16_KEY]
        index = _focus_step(p, vocab)
        rows = rows_of(p)
        if index is None or index > len(rows):
            return []
        expected = expected_steps(p, vocab=vocab)
        return [
            step_cell_key(index, s.key)
            for s in _walk_leaves(index, expected)
            if _cell_open(rows[index - 1], s.key, vocab)
        ]
    if phase == PHASE_CONFIRM:
        proc = process_of(p)
        return [ROLLUP_KEYS[t] for t in ROLLUP_TARGETS if proc.get(ROLLUP_FLAGS[t]) is not True]
    if phase == PHASE_REVIEW:
        return [s.key for s in PROFILE_SPECS if _state(p, s, counters, vocab) not in ("counts", "given_up")]
    return []


def posture(find_turns: int) -> Posture:
    """The find posture for question `find_turns + 1`: 1–3 open, 4–5 narrowed, 6+ direct."""
    question = coerce_count(find_turns) + 1
    if question < FIND_FOCUS_TURN:
        return "open"
    if question < FIND_DIRECT_TURN:
        return "narrowed"
    return "direct"


# --- Proposal groups ------------------------------------------------------------------------------


def proposal_group(
    profile: Mapping[str, Any], phase: str, counters: Mapping[str, Any], *, vocab: Vocabulary
) -> list[str]:
    """The proposals presented together this turn (§3.8): process fields (≤ 4), all step names, the focus step, the first step."""
    if phase == PHASE_CONTEXT or phase in TERMINAL_PHASES:
        return []
    p = normalized_profile(profile)
    held = set(given_up_keys(p, counters, vocab=vocab))
    if phase != PHASE_REVIEW:
        held |= set(deferred_keys(p, counters, vocab=vocab))
    rows = rows_of(p)
    fields: list[str] = []
    cells: dict[int, list[str]] = {}
    for key in proposed_keys(p):
        parsed = parse_step_key(key)
        if parsed is None:
            if key not in held:
                fields.append(key)
            continue
        index, leaf = parsed
        if index <= len(rows) and not cell_skipped(rows[index - 1], leaf):
            cells.setdefault(index, []).append(key)
    if fields:
        return fields[:PROPOSAL_GROUP_MAX]
    names = [k for keys in cells.values() for k in keys if k.endswith(".name")]
    if names:
        return names
    focus = current_step_index(p, vocab=vocab)
    if focus is not None and cells.get(focus):
        return cells[focus]
    return next((cells[i] for i in sorted(cells)), [])


# --- The ask target -------------------------------------------------------------------------------


def _cluster_mode(state: Mapping[str, Any], counters: Mapping[str, Any]) -> Literal["propose", "picker"]:
    placement = as_mapping(state.get("placement")) or {}
    code = proposable_code(as_mapping(placement.get("proposal")))
    if not code or placement.get("rejected") is True:
        return "picker"
    if posture(read_counters(counters)["find_turns"]) == "direct" or field_asks(counters, CLUSTER_KEY) >= 2:
        return "picker"
    return "propose"


def wrap_up_keys(profile: Mapping[str, Any], counters: Mapping[str, Any], *, vocab: Vocabulary) -> list[str]:
    """Given-up fields not yet offered in the wrap-up (Q4: offered once, with an easy way to settle)."""
    out: list[str] = []
    for key in given_up_keys(profile, counters, vocab=vocab):
        spec = next(s for s in PROFILE_SPECS if s.key == key)
        if field_asks(counters, key) < field_limit(spec) + REVIEW_ASK_LIMIT + WRAP_UP_ASKS:
            out.append(key)
    return out


def next_ask(state: Mapping[str, Any], *, vocab: Vocabulary) -> Ask:
    """The one ask target of this turn, by the priority table of §3.8."""
    profile = normalized_profile(as_mapping(state.get("profile")))
    phase = str(state.get("phase") or PHASE_CONTEXT)
    counters = read_counters(as_mapping(state.get("counters")))
    scope = as_mapping(state.get("scope")) or {}
    if scope.get("awaiting_widening") is True:
        return Ask("widening")
    group = proposal_group(profile, phase, counters, vocab=vocab)
    if group:
        return Ask("proposals", tuple(group))
    missing = missing_fields(profile, phase, counters, vocab=vocab)
    if phase in COLLECTING_PHASES or phase == PHASE_REVIEW:
        if missing and missing[0] == CLUSTER_KEY:
            return Ask("cluster", (CLUSTER_KEY,), _cluster_mode(state, counters))
        if missing:
            return Ask("field", (missing[0],))
    if phase == PHASE_STEPS:
        focus = step_focus(profile, vocab=vocab)
        if focus == P16_KEY:
            return Ask("field", (P16_KEY,))
        if focus is not None:
            return Ask("cell", (focus,))
    if phase == PHASE_CONFIRM and missing:
        keys = missing if counters["confirm_turns"] >= CONFIRM_TURN_LIMIT else missing[:1]
        return Ask("rollups", tuple(keys))
    return Ask("wrap_up", tuple(wrap_up_keys(profile, counters, vocab=vocab)))


def last_question_for(ask: Ask) -> dict[str, Any]:
    """The `LastQuestion` (spec 12) that records an ask target, so the next turn can read the reply."""
    if ask.kind == "proposals":
        return {"focus": [], "proposals": list(ask.keys), "confirm": None}
    if ask.kind == "cluster":
        return {"focus": list(ask.keys), "proposals": [], "confirm": "cluster" if ask.mode == "propose" else None}
    if ask.kind == "rollups":
        first = next((t for t, k in ROLLUP_KEYS.items() if ask.keys and k == ask.keys[0]), None)
        return {"focus": list(ask.keys), "proposals": [], "confirm": first}
    if ask.kind == "widening":
        return {"focus": [], "proposals": [], "confirm": None}
    return {"focus": list(ask.keys), "proposals": [], "confirm": None}


def ask_count(ask: Ask, counters: Mapping[str, Any]) -> int:
    """How many times the ask target has been asked already (the most-asked of its keys)."""
    c = read_counters(counters)
    if ask.kind == "rollups":
        return c["confirm_turns"]
    counts = [c["cell_asks"].get(k, 0) if parse_step_key(k) else c["field_asks"].get(k, 0) for k in ask.keys]
    return max(counts, default=0)


# --- Charging and the cell limits -----------------------------------------------------------------


def charge_asks(
    counters: Mapping[str, Any] | None,
    last_question: Mapping[str, Any] | None,
    prior_phase: str,
    *,
    find_turns_before: int,
) -> dict[str, Any]:
    """Charge one ask to every key the answered question was about (§3.6); never mutates its input."""
    out = read_counters(counters)
    question = last_question or {}
    keys = [
        k
        for k in (as_list(question.get("focus")) or []) + (as_list(question.get("proposals")) or [])
        if isinstance(k, str)
    ]
    rollups = set(ROLLUP_KEYS.values())
    for key in dict.fromkeys(keys):
        if key in rollups:
            continue
        if parse_step_key(key) is not None:
            out["cell_asks"][key] = out["cell_asks"].get(key, 0) + 1
            continue
        if key == NAME_KEY and prior_phase == PHASE_FIND and posture(find_turns_before) != "direct":
            continue
        out["field_asks"][key] = out["field_asks"].get(key, 0) + 1
    if prior_phase == PHASE_FIND:
        out["find_turns"] += 1
    if prior_phase == PHASE_CONFIRM:
        out["confirm_turns"] += 1
    return out


def cell_escapes(
    profile: Mapping[str, Any], counters: Mapping[str, Any], *, vocab: Vocabulary
) -> tuple[dict[str, Any], list[str]]:
    """Step cells asked past their limit: none-row changes for empty S04/S10/S11, skip keys for the rest."""
    p = normalized_profile(profile)
    asks = read_counters(counters)["cell_asks"]
    changes: dict[str, Any] = {}
    skips: list[str] = []
    for index, row in enumerate(rows_of(p), start=1):
        for spec in STEP_SPECS:
            key = step_cell_key(index, spec.key)
            if asks.get(key, 0) < cell_limit(spec) or not _cell_open(row, spec.key, vocab):
                continue
            if spec.key in NONE_ROW_LEAVES and not has_any_answer(spec, row.get(spec.key)):
                changes[key] = [{NONE_KEY: True}]
            else:
                skips.append(key)
    return changes, skips
