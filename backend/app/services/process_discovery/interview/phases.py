"""Which phase the interview is in, what is still missing, and what the next question is about (spec 14 §3.3, §3.5, §3.6, §3.8).

Why: the interview has no script. The phase is recomputed from the profile and the counters every
turn, and code chooses the one ask target the guide must voice, so the model can never wander
between fields or skip one. Every loop has a counter and every counter a maximum: a process field
is deferred after 3 asks and given up after 2 more; a step cell is settled after 3; the find
posture escalates on schedule; the list confirmation changes manner after 6 turns.
What: field limits and states (`deferred_keys`, `given_up_keys`), `phase_blocks`,
`phase_from_state`, `advance_phase` (collecting phases never move backwards; the tail may step
back; terminals never change), `missing_fields`, `step_focus`, `posture`, `proposal_group`,
`steering_ask`, `next_ask`, `charge_asks` (never charges a `steer:` key) and `cell_escapes`.
Must not: write the profile, call a model, read a clock or mutate its inputs; every function
derives what it needs from the whole `counters` so no caller can forget a set.
Spec 14 §3.3, §3.5, §3.6, §3.8, §3.15 item 10; AC-14.20 to AC-14.30, AC-14.41 to AC-14.43, AC-14.65,
AC-14.73. Amendment §3.17: the `conflict` ask (after `widening`, before `proposals`), its group
(`conflict_group`), its counter (`charge_conflicts`: 2 asks, then `left`), and proposal groups that
leave out a unit under dispute (AC-14.92 to AC-14.94, AC-14.99).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from app.core.config import SteeringConfig

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
from ..profile.conflicts import ConflictView, conflicted_fields, open_conflicts
from ..profile.constants import (
    FLAG_SUBSTEPS_COMPLETE,
    NONE_ROW_LEAVES,
    ROLLUP_FLAGS,
    ROLLUP_KEYS,
    ROLLUP_TARGETS,
)
from ..profile.proposals import proposed_keys
from ..profile.shapes import as_list, as_mapping, meta_for, normalized_profile, parse_step_key, process_of, rows_of
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
from .steering import RECOMMEND_ASK_LIMIT, STEER_PREFIX, next_signals, read_steering
from .types import Ask

PROPOSAL_GROUP_MAX = 4
#: Spec 14 §3.17 (decided 2026-11-20): asks per conflict before it is left, conflicts per question.
CONFLICT_ASK_LIMIT = 2
CONFLICT_GROUP_MAX = 3
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
        "conflict_asks": _asks(source, "conflict_asks"),
        "expert_messages": coerce_count(source.get("expert_messages")),
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
    held |= conflicted_fields(p)  # §3.17 Q3: a unit under dispute is never in a proposal group
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
        if index <= len(rows) and not cell_skipped(rows[index - 1], leaf) and key not in held:
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


#: Document roles that describe one step rather than the whole process (spec 17 §3.18 item 2).
STEP_SCOPED_ROLES: frozenset[str] = frozenset({"step_output_example", "step_input_example", "step_material", "other"})


def document_group(
    profile: Mapping[str, Any],
    counters: Mapping[str, Any],
    *,
    document_id: str,
    role: str,
    target_step: int | None,
    vocab: Vocabulary,
) -> tuple[list[str], int]:
    """The proposals of one document asked right after its upload, and how many of its others wait (§3.16 item 3).

    Deferred keys are included (the expert brought the file up now); given-up and skipped ones are not.
    """
    p = normalized_profile(profile)
    held = set(given_up_keys(p, counters, vocab=vocab))
    disputed = conflicted_fields(p)
    rows = rows_of(p)
    fields: list[str] = []
    cells: dict[int, list[str]] = {}
    for key in proposed_keys(p):
        meta = meta_for(p, key) or {}
        if meta.get("documentId") != document_id or key in disputed:
            continue
        parsed = parse_step_key(key)
        if parsed is None:
            if key not in held:
                fields.append(key)
            continue
        index, leaf = parsed
        if index <= len(rows) and not cell_skipped(rows[index - 1], leaf):
            cells.setdefault(index, []).append(key)
    candidates = fields + [k for i in sorted(cells) for k in cells[i]]
    if role in STEP_SCOPED_ROLES:
        group = [*(cells.get(target_step, []) if target_step is not None else []), *fields][:PROPOSAL_GROUP_MAX]
    elif fields:
        group = fields[:PROPOSAL_GROUP_MAX]
    else:
        names = [k for i in sorted(cells) for k in cells[i] if k.endswith(".name")]
        group = names or next((cells[i] for i in sorted(cells)), [])[:PROPOSAL_GROUP_MAX]
    return group, len([k for k in candidates if k not in group])


# --- Conflict groups (§3.17 item 2) ---------------------------------------------------------------


def _step_of(view: ConflictView) -> int | None:
    parsed = parse_step_key(view.key)
    return parsed[0] if parsed is not None else None


def conflict_group(profile: Mapping[str, Any], *, document_id: str | None = None) -> list[ConflictView]:
    """The open conflicts asked together (at most 3): the first in ask order, plus those on the same
    step (or the process), from the same document, of the same kind and, for the document kind, the
    same holder."""
    views = [v for v in open_conflicts(profile, status="open") if document_id is None or v.document_id == document_id]
    if not views:
        return []
    first = views[0]
    same = [
        v
        for v in views
        if _step_of(v) == _step_of(first)
        and v.document_id == first.document_id
        and v.kind == first.kind
        and (first.kind != "document" or v.holder_document_id == first.holder_document_id)
    ]
    return same[:CONFLICT_GROUP_MAX]


# --- The ask target -------------------------------------------------------------------------------


def _cluster_mode(state: Mapping[str, Any], counters: Mapping[str, Any]) -> Literal["propose", "picker"]:
    """Propose a live proposal; the picker once it was rejected, asked twice, or asked once at the direct posture.

    A proposal never put to the expert is put once even at the direct posture: the picker is the
    guard for a proposal that did not land, and steering (§3.15) can push the name past question 6.
    """
    placement = as_mapping(state.get("placement")) or {}
    code = proposable_code(as_mapping(placement.get("proposal")))
    if not code or placement.get("rejected") is True:
        return "picker"
    asked = field_asks(counters, CLUSTER_KEY)
    if asked >= 2 or (asked >= 1 and posture(read_counters(counters)["find_turns"]) == "direct"):
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


def steering_ask(state: Mapping[str, Any], cfg: SteeringConfig, *, vocab: Vocabulary) -> Ask | None:
    """`steer` while collecting, then `recommend` (at most 2), only in `find` while P04 does not count (§3.15 item 10)."""
    profile = normalized_profile(as_mapping(state.get("profile")))
    if state.get("phase") != PHASE_FIND or field_counts(profile, NAME_KEY, vocab=vocab):
        return None
    steer = read_steering(as_mapping(state.get("steering")))
    signals = next_signals(steer, cfg)
    if signals:
        return Ask("steer", tuple(STEER_PREFIX + s for s in signals))
    if steer["status"] == "ranked" and steer["recommend_asks"] < RECOMMEND_ASK_LIMIT:
        mode = "recommend" if steer["recommended_id"] and not steer["declined"] else "pick"
        return Ask("recommend", (NAME_KEY,), mode)
    return None


def next_ask(state: Mapping[str, Any], *, vocab: Vocabulary, steering: SteeringConfig | None = None) -> Ask:
    """The one ask target of this turn, by the priority table of §3.8 (with `steer` and `recommend`, §3.15)."""
    profile = normalized_profile(as_mapping(state.get("profile")))
    phase = str(state.get("phase") or PHASE_CONTEXT)
    counters = read_counters(as_mapping(state.get("counters")))
    scope = as_mapping(state.get("scope")) or {}
    if scope.get("awaiting_widening") is True:
        return Ask("widening")
    if phase != PHASE_CONTEXT and phase not in TERMINAL_PHASES:
        disputed = conflict_group(profile)
        if disputed:
            return Ask("conflict", tuple(v.conflict_key for v in disputed))
    group = proposal_group(profile, phase, counters, vocab=vocab)
    if group:
        return Ask("proposals", tuple(group))
    steered = steering_ask(state, steering, vocab=vocab) if steering is not None else None
    if steered is not None:
        return steered
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
    if ask.kind == "conflict":
        return {"focus": [], "proposals": [], "confirm": None, "conflicts": list(ask.keys)}
    if ask.kind == "cluster":
        return {"focus": list(ask.keys), "proposals": [], "confirm": "cluster" if ask.mode == "propose" else None}
    if ask.kind == "rollups":
        first = next((t for t, k in ROLLUP_KEYS.items() if ask.keys and k == ask.keys[0]), None)
        return {"focus": list(ask.keys), "proposals": [], "confirm": first}
    if ask.kind == "widening":
        return {"focus": [], "proposals": [], "confirm": None}
    if ask.kind == "recommend":
        return {
            "focus": list(ask.keys),
            "proposals": [],
            "confirm": "recommendation" if ask.mode == "recommend" else None,
        }
    return {"focus": list(ask.keys), "proposals": [], "confirm": None}


def ask_count(ask: Ask, counters: Mapping[str, Any]) -> int:
    """How many times the ask target has been asked already (the most-asked of its keys)."""
    c = read_counters(counters)
    if ask.kind == "rollups":
        return c["confirm_turns"]
    if ask.kind == "conflict":
        return max((c["conflict_asks"].get(k, 0) for k in ask.keys), default=0)
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
        if key in rollups or key.startswith(STEER_PREFIX):
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
    out["expert_messages"] += 1  # §3.18 L1: every answered question is one expert message
    return out


def charge_conflicts(
    counters: Mapping[str, Any], keys: list[str], open_keys: set[str]
) -> tuple[dict[str, Any], list[str]]:
    """§3.17 item 5, steps 10 and 10b: one ask per asked conflict still open; those at the limit are returned."""
    out = read_counters(counters)
    left: list[str] = []
    for key in keys:
        if key not in open_keys:
            continue
        out["conflict_asks"][key] = out["conflict_asks"].get(key, 0) + 1
        if out["conflict_asks"][key] >= CONFLICT_ASK_LIMIT:
            left.append(key)
    return out, left


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
