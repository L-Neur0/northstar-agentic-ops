"""Which phase the interview is in, what is still missing, and what the next question is about (spec 14 §3.3, §3.5, §3.6, §3.8).

Why: the interview has no script. The phase is recomputed from the profile and the counters every
turn, and code chooses the one ask target the guide must voice, so the model can never wander
between fields or skip one. Every loop has a counter and every counter a maximum: a process field
is deferred after 3 asks and given up after 2 more; a step cell is settled after 3; the find
posture escalates on schedule; the list confirmation changes manner after 6 turns.
What: field limits and states (`deferred_keys`, `given_up_keys`), `phase_blocks`,
`phase_from_state`, `advance_phase` (collecting phases never move backwards; the tail may step
back; terminals never change), `missing_fields`, `walk_ask`, `step_focus`, `field_group`, `posture`, `proposal_group`,
`steering_ask`, `next_ask`, `charge_asks` (never charges a `steer:` key) and `cell_escapes`.
Must not: write the profile, call a model, read a clock or mutate its inputs; every function
derives what it needs from the whole `counters` so no caller can forget a set.
Spec 14 §3.3, §3.5, §3.6, §3.8, §3.15 item 10; AC-14.20 to AC-14.30, AC-14.41 to AC-14.43, AC-14.65,
AC-14.73. Amendment §3.17: the `conflict` ask (after `widening`, before `proposals`), its group
(`conflict_group`), its counter (`charge_conflicts`: 2 asks, then `left`), and proposal groups that
leave out a unit under dispute (AC-14.92 to AC-14.94, AC-14.99). Amendment §3.19 (short step walk,
approved 2026-11-20): code groups the questions (`field_group`, `walk_ask`), an optional field is
given up at its limit, and agent proposals wait for one bulk confirmation in the review
(AC-14.105 to AC-14.113). Amendment §3.20 (owner test, 2026-11-21): no `confirm` phase, `progress`
for the bar and `suggest_now` in `find` (AC-14.118, AC-14.120, AC-14.127).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from app.core.config import SteeringConfig

from ..domain.field_spec import (
    CELL_ASK_LIMIT,
    COLLECTING_PHASES,
    FIELD_ASK_LIMIT,
    FIND_DIRECT_TURN,
    FIND_FOCUS_TURN,
    GROUP_A,
    GROUP_B,
    GROUP_EFFORT,
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
    PROGRESS_DEFAULT_STEPS,
    REVIEW_ASK_LIMIT,
    STATUS_INVALID,
    STEP_SPECS,
    FieldSpec,
    Vocabulary,
    field_applies,
    has_any_answer,
    progress_step_specs,
    specs_for_phase,
    step_cell_key,
    step_specs_in_group,
)
from ..domain.scope import proposable_code
from ..profile.coercion import coerce_count
from ..profile.conflicts import ConflictView, conflicted_fields, open_conflicts
from ..profile.constants import (
    FLAG_SUBSTEPS_COMPLETE,
    NONE_ROW_LEAVES,
    ROLLUP_KEYS,
)
from ..profile.inferred import is_agent_proposal
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
    if spec.optional:  # §3.19 W2: an optional field is given up at its limit, never deferred
        return "given_up"
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
    """The first collecting phase that blocks; else `steps` until the walk closes; else `review` (no `confirm`, §3.20 O10)."""
    p = normalized_profile(profile)
    for phase in COLLECTING_PHASES:
        if phase_blocks(p, phase, counters, vocab=vocab):
            return phase
    if process_of(p).get(FLAG_SUBSTEPS_COMPLETE) is not True:
        return PHASE_STEPS
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


def _askable(row: Mapping[str, Any], leaf: str, vocab: Vocabulary) -> bool:
    """Open and not a proposal (proposals are presented as a group, §3.8)."""
    return _cell_open(row, leaf, vocab) and not cell_proposed(row, leaf)


def walk_ask(profile: Mapping[str, Any], *, vocab: Vocabulary) -> tuple[str, ...]:
    """The cells of the next walk question (§3.19 W4); `()` when the walk has nothing left to ask.

    P16 while there is no count; else every open step name together; else, step by step, the open
    Tier A cells together, then the open Tier B cells together; else every open effort cell of all
    steps together. Tier C is never asked: code proposes it (`profile.inferred`).
    """
    p = normalized_profile(profile)
    expected = expected_steps(p, vocab=vocab)
    if expected == 0:
        return (P16_KEY,)
    rows = rows_of(p)[:expected]
    names = [step_cell_key(i, "name") for i, row in enumerate(rows, start=1) if _askable(row, "name", vocab)]
    if names:
        return tuple(names)
    for index, row in enumerate(rows, start=1):
        for group in (GROUP_A, GROUP_B):
            open_specs = [
                s for s in step_specs_in_group(group) if field_applies(s, row) and _askable(row, s.key, vocab)
            ]
            if group == GROUP_B and not _optional_worth_asking(open_specs):
                continue
            if open_specs:
                return tuple(step_cell_key(index, s.key) for s in open_specs)
    effort = [
        step_cell_key(i, s.key)
        for i, row in enumerate(rows, start=1)
        for s in step_specs_in_group(GROUP_EFFORT)
        if _askable(row, s.key, vocab)
    ]
    return tuple(effort)


def _optional_worth_asking(open_specs: list[FieldSpec]) -> bool:
    """§3.20 O8: the optional question is asked while one of its scored cells is open; hand-over alone
    (unscored) never is. §3.21 P1: an open decision criteria cell (S14, unscored but conditional) also
    keeps it open, since it only applies to a judgement or mix step."""
    return any(s.weight or s.applies_when for s in open_specs)


def step_focus(profile: Mapping[str, Any], *, vocab: Vocabulary) -> str | None:
    """The first cell of the next walk question (P16 while there is no count), or `None`."""
    keys = walk_ask(profile, vocab=vocab)
    return keys[0] if keys else None


def missing_fields(
    profile: Mapping[str, Any], phase: str, counters: Mapping[str, Any], *, vocab: Vocabulary
) -> list[str]:
    """The keys still missing for `phase`, in ask order (§3.3 table)."""
    p = normalized_profile(profile)
    if phase in COLLECTING_PHASES:
        return _blocking(p, phase, counters, vocab)
    if phase == PHASE_STEPS:
        return list(walk_ask(p, vocab=vocab))
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


# --- Progress and suggestions (spec 14 §3.20 O2, O4, amended 2026-11-21) -------------------------


def progress(profile: Mapping[str, Any], counters: Mapping[str, Any], *, vocab: Vocabulary) -> float:
    """How far along the interview path, 0–1, for the bar; `score` stays the gate's number.

    Process fields that count or are given up, plus the asked, non-optional step cells (8 per step) that
    count or are skipped, over process points + E × 8, E = P16 or 4 while it is not known.
    """
    p = normalized_profile(profile)
    done = sum(s.weight for s in PROFILE_SPECS if s.weight and _state(p, s, counters, vocab) in ("counts", "given_up"))
    steps = expected_steps(p, vocab=vocab) or PROGRESS_DEFAULT_STEPS
    specs = progress_step_specs()
    for row in rows_of(p)[:steps]:
        done += sum(s.weight for s in specs if cell_counts(row, s.key, vocab=vocab) or cell_skipped(row, s.key))
    total = sum(s.weight for s in PROFILE_SPECS) + steps * sum(s.weight for s in specs)
    return min(1.0, round(done / total, 4)) if total else 0.0


#: Find questions (1-based) on which the guide is told to suggest candidates while none was heard (§3.20 O2).
SUGGEST_MAX_TURNS = 4


def suggest_now(state: Mapping[str, Any], *, vocab: Vocabulary) -> bool:
    """Code decides WHEN the model suggests candidates (§3.20 O2): in `find`, P04 not counting, no candidate
    heard yet, on the first `SUGGEST_MAX_TURNS` find questions. The model decides WHAT to suggest."""
    profile = normalized_profile(as_mapping(state.get("profile")))
    if state.get("phase") != PHASE_FIND or field_counts(profile, NAME_KEY, vocab=vocab):
        return False
    if read_steering(as_mapping(state.get("steering")))["candidates"]:
        return False
    return read_counters(as_mapping(state.get("counters")))["find_turns"] < SUGGEST_MAX_TURNS


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
    agent: list[str] = []
    for key in proposed_keys(p):
        parsed = parse_step_key(key)
        if parsed is None:
            if key not in held:
                fields.append(key)
            continue
        index, leaf = parsed
        if index > len(rows) or cell_skipped(rows[index - 1], leaf) or key in held:
            continue
        if is_agent_proposal(p, key):  # §3.19 W8: held until the review, then confirmed in bulk
            agent.append(key)
        else:
            cells.setdefault(index, []).append(key)
    if fields:
        return fields[:PROPOSAL_GROUP_MAX]
    if agent and phase == PHASE_REVIEW:
        return agent
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


def field_group(missing: list[str]) -> tuple[str, ...]:
    """The first missing field and every other missing field of its group, in ask order (§3.19 W1)."""
    first = next((s for s in PROFILE_SPECS if s.key == missing[0]), None)
    if first is None or first.group is None:
        return (missing[0],)
    grouped = {s.key for s in PROFILE_SPECS if s.group == first.group}
    return tuple(k for k in missing if k in grouped)


def wrap_up_keys(profile: Mapping[str, Any], counters: Mapping[str, Any], *, vocab: Vocabulary) -> list[str]:
    """Given-up fields not yet offered in the wrap-up (Q4: offered once, with an easy way to settle)."""
    out: list[str] = []
    for key in given_up_keys(profile, counters, vocab=vocab):
        spec = next(s for s in PROFILE_SPECS if s.key == key)
        if spec.optional:  # §3.19 W2: an optional field is never offered again
            continue
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
            return Ask("field", field_group(missing))
    if phase == PHASE_STEPS:
        keys = walk_ask(profile, vocab=vocab)
        if keys == (P16_KEY,):
            return Ask("field", keys)
        if keys:
            return Ask("cell", keys)
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
