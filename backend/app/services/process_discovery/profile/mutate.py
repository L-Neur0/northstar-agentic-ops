"""The writer of the profile: expert changes, code-set values and specialist edits (spec 13 §3.4–§3.8).

Why: one rule above all: a bad change can never corrupt or wipe the profile. So unknown keys,
wrong shapes and empty values are dropped (and reported), a specialist's value outranks a later
model write, a proposal is replaced rather than accumulated onto, and the step table is only ever
trimmed where nothing was said. `apply_changes` reads top to bottom in the order the writes must
happen: per key (address, writability, ownership, proposal, index, kind, step count, meta, un-skip),
then invalidation, resize, the close test, the roll-ups, and only then the Verdicts, graded last
because completeness is not always local (P13 reads P12's unit; the resize may drop a row).
What: `ChangeResult`, `UnknownClusterError`, `allowed_changes` / `unknown_change_keys` (the EXTRACT
whitelist and its shape report), `apply_changes`, `mark_cells_skipped`, `assume_substep_count`,
`set_cluster`, `confirm_rollup`, `set_field`, and the shared batch steps (`finish_batch`,
`resize_steps`, `close_if_complete`, `rebuild_rollups`, `make_meta`) the proposal writer reuses.
Must not: read a clock (`at` is passed in), mutate an input, log a value (keys, reasons and value
types only), or let a model write the cluster, a flag, a roll-up or a sidecar.
Spec 13 §3.4–§3.8; AC-13.4 to AC-13.31. Amendment §3.13 item 3: a landed write closes the field's
conflicts (`conflicts_closed`, AC-13.60); `__conflicts` is a sidecar no change may write.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, NamedTuple

from ..domain.field_spec import (
    CONFLICTS_KEY,
    MAX_STEPS,
    META_KEY,
    MIN_STEPS,
    PROFILE_SPECS,
    SKIPPED_KEY,
    SOURCE_EXPERT,
    SOURCE_SPECIALIST,
    STEP_SPECS,
    Verdict,
    Vocabulary,
    extract_keys,
    is_proposed,
    recompute_derived,
    specialist_keys,
    step_key_template,
    step_spec_by_leaf,
)
from .coercion import (
    coerce_number,
    coerce_text,
    filtered_object,
    filtered_rows,
    merged_list,
    merged_object,
    merged_rows,
    normalise,
)
from .constants import (
    CONFIRMATION_FLAGS,
    FLAG_ROLES_CONFIRMED,
    FLAG_SUBSTEP_COUNT_REJECTED,
    FLAG_SUBSTEPS_COMPLETE,
    FLAG_TOOLS_CONFIRMED,
    INDEX_OUT_OF_RANGE,
    NOT_WRITABLE,
    ROLLUP_FLAGS,
    ROLLUP_KEYS,
    ROLLUP_TARGETS,
    SHAPE,
    SPECIALIST_OWNED,
    UNKNOWN_KEY,
)
from .shapes import (
    Address,
    as_dict,
    as_list,
    as_mapping,
    empty_step,
    empty_value,
    meta_for,
    normalized_profile,
    parse_step_key,
    process_of,
    resolve_key,
    rows_of,
)
from .verdicts import (
    P16_KEY,
    cell_counts,
    expected_steps,
    field_counts,
    grade,
    last_started_row,
    step_is_complete,
    step_is_started,
)

logger = logging.getLogger("app.profile")

BASE_KEYS: tuple[str, ...] = tuple(s.key for s in PROFILE_SPECS if not s.is_process)
#: Keys on `process` that no change may write: flags, the parked count, roll-ups, sidecars.
_CODE_OWNED_LEAVES: frozenset[str] = frozenset(
    {
        *CONFIRMATION_FLAGS,
        FLAG_SUBSTEP_COUNT_REJECTED,
        "all_roles",
        "all_tools",
        "substeps",
        META_KEY,
        SKIPPED_KEY,
        CONFLICTS_KEY,
    }
)
_SIDECARS: frozenset[str] = frozenset({META_KEY, SKIPPED_KEY, CONFLICTS_KEY})


class ChangeResult(NamedTuple):
    """What one batch of writes did: the new profile and an account of every key."""

    profile: dict[str, Any]
    written: list[str]
    refused: list[tuple[str, str]]
    verdicts: dict[str, Verdict]
    touched_steps: bool
    #: Conflict keys closed because a person wrote the field (spec 13 §3.13 item 3, `own_words`).
    conflicts_closed: tuple[str, ...] = ()


class UnknownClusterError(ValueError):
    """`set_cluster` was given a code the company taxonomy does not declare."""

    def __init__(self, code: str) -> None:
        super().__init__(f"unknown cluster code {code!r}")
        self.code = code


def make_meta(
    source: str,
    status: str,
    at: str,
    *,
    document_id: str | None = None,
    quote: str | None = None,
    by: str | None = None,
    replaces: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One `__meta` entry, keyed as stored (`documentId`); `replaces` only on a proposal over a partial answer."""
    meta: dict[str, Any] = {"source": source, "status": status, "documentId": document_id, "quote": quote, "by": by}
    meta["at"] = at
    if replaces is not None:
        meta["replaces"] = dict(replaces)
    return meta


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return value == [] or value == {}


def log_refusal(key: str, reason: str, value: Any) -> None:
    """One warning per refused non-empty value: key, reason and value type, never the value."""
    if _blank(value):
        return
    shown = key if resolve_key(key) is not None or key in BASE_KEYS else "(unrecognised key)"
    logger.warning("profile_write_refused", extra={"key": shown, "reason": reason, "value_type": type(value).__name__})


# --- Whitelist ------------------------------------------------------------------------------------


def _allowed_process_leaves() -> set[str]:
    return {k.split(".", 1)[1] for k in extract_keys() if k.startswith("process.") and "[" not in k}


def allowed_changes(changes: Any) -> dict[str, Any]:
    """Only the keys EXTRACT may write (`extract_keys()`), plus the lenient nested `{"process": {...}}` form."""
    source = as_mapping(changes)
    if source is None:
        return {}
    allowed = set(extract_keys())
    process_leaves = _allowed_process_leaves()
    step_leaves = {s.key for s in STEP_SPECS if s.extract}
    out: dict[str, Any] = {}
    for key, value in source.items():
        if not isinstance(key, str):  # pyright: ignore[reportUnnecessaryIsInstance]
            continue
        parsed = parse_step_key(key)
        if parsed is not None:
            if parsed[1] in step_leaves and step_key_template(parsed[1]) in allowed:
                out[key] = value
            continue
        if key == "process":
            nested = as_mapping(value)
            if nested is not None:
                kept = {k: v for k, v in nested.items() if k in process_leaves}
                if kept:
                    out[key] = kept
            continue
        if key in allowed:
            out[key] = value
    return out


def unknown_change_keys(changes: Any) -> list[str]:
    """Keys whose *shape* no writer accepts (a misrouted `"volume"` at top level), for the turn log."""
    source = as_mapping(changes)
    if source is None:
        return []
    unknown: list[str] = []
    for key in source:
        if key in BASE_KEYS or parse_step_key(key) is not None or key == "process" or key.startswith("process."):
            continue
        unknown.append(key)
    return unknown


# --- Batch steps shared with proposals ------------------------------------------------------------


def _set_meta(profile: dict[str, Any], address: Address, meta: dict[str, Any]) -> None:
    if address.step is None:
        container = as_dict(profile.get(META_KEY))
        if container is None:
            container = {}
            profile[META_KEY] = container
        container[address.spec.key] = meta
        return
    row = rows_of(profile)[address.step - 1]
    container = as_dict(row.get(META_KEY))
    if container is None:
        container = {}
        row[META_KEY] = container
    container[address.spec.key] = meta


def remove_meta(profile: dict[str, Any], address: Address) -> None:
    """Drop one field's or cell's `__meta` entry."""
    if address.step is None:
        (as_dict(profile.get(META_KEY)) or {}).pop(address.spec.key, None)
        return
    rows = rows_of(profile)
    if address.step <= len(rows):
        (as_dict(rows[address.step - 1].get(META_KEY)) or {}).pop(address.spec.key, None)


def set_meta(profile: dict[str, Any], address: Address, meta: dict[str, Any]) -> None:
    """Write one field's or cell's `__meta` entry (the row must exist)."""
    _set_meta(profile, address, meta)


def unskip(row: dict[str, Any], leaf: str) -> None:
    """Remove `leaf` from the row's `__skipped`."""
    skipped = as_list(row.get(SKIPPED_KEY))
    if skipped is not None and leaf in skipped:
        row[SKIPPED_KEY] = [k for k in skipped if k != leaf]


def write_value(profile: dict[str, Any], address: Address, value: Any) -> None:
    """Store `value` at `address`, padding the step table up to the row (1-based)."""
    proc = process_of(profile)
    if address.step is None:
        if address.spec.is_process:
            proc[address.spec.leaf] = value
        else:
            profile[address.spec.key] = value
        return
    rows = as_list(proc.get("substeps"))
    if rows is None:
        rows = []
        proc["substeps"] = rows
    while len(rows) < address.step:
        rows.append(empty_step())
    row = rows_of(profile)[address.step - 1]
    row[address.spec.key] = value
    unskip(row, address.spec.key)


def _clamp(value: int) -> int:
    return min(max(value, MIN_STEPS), MAX_STEPS)


def resize_steps(profile: dict[str, Any], *, vocab: Vocabulary) -> None:
    """Reconcile the table with P16: raise P16 rather than delete content; grow; drop trailing empty rows."""
    proc = process_of(profile)
    rows = as_list(proc.get("substeps"))
    if rows is None:
        rows = []
        proc["substeps"] = rows
    started = last_started_row(rows, vocab=vocab)
    declared = coerce_number(proc.get("substep_count")) or 0
    if declared:
        declared = _clamp(max(declared, started))
        proc["substep_count"] = declared
    target = min(MAX_STEPS, max(declared, started))
    while len(rows) < target:
        rows.append(empty_step())
    while len(rows) > target:
        last = as_mapping(rows[-1])
        if last is not None and step_is_started(last, vocab=vocab):
            break
        rows.pop()


def close_if_complete(profile: dict[str, Any], *, vocab: Vocabulary) -> None:
    """Close the walk when rows `1..expected` are complete; trim P16 to the last started row (≥ 2)."""
    expected = expected_steps(profile, vocab=vocab)
    rows = rows_of(profile)
    if expected <= 0 or len(rows) < expected:
        return
    if not all(step_is_complete(r, vocab=vocab) for r in rows[:expected]):
        return
    _close_and_trim(profile, vocab=vocab)


def _close_and_trim(profile: dict[str, Any], *, vocab: Vocabulary) -> None:
    """Raise `substeps_complete` and lower P16 to the last started row (never below 2), dropping later rows.

    The only path that lowers the count: an expert who said six and described four has a four-step
    process. Trimming is by the last started position, never by a count of started rows, so a gap
    in the table never deletes a described step.
    """
    proc = process_of(profile)
    proc[FLAG_SUBSTEPS_COMPLETE] = True
    started = last_started_row(rows_of(profile), vocab=vocab)
    if started:
        keep = _clamp(started)
        proc["substep_count"] = keep
        table = as_list(proc.get("substeps"))
        if table is not None:
            del table[keep:]


def close_steps(profile: Mapping[str, Any], *, vocab: Vocabulary) -> dict[str, Any]:
    """ "No further steps": close the walk on the expert's request and trim the count (AC-13.55, AC-13.56).

    Returns a new profile; the roll-ups are rebuilt because trimmed rows may have held roles or systems.
    """
    result = normalized_profile(profile)
    _close_and_trim(result, vocab=vocab)
    rebuild_rollups(result)
    return result


def rebuild_rollups(profile: dict[str, Any]) -> None:
    """Rebuild `all_roles` / `all_tools` from scratch; a list that changed loses its confirmation."""
    proc = process_of(profile)
    for key, values in recompute_derived(profile).items():
        leaf = key.split(".", 1)[1]
        if proc.get(leaf) != values:
            proc[leaf] = values
            for target, rollup_key in ROLLUP_KEYS.items():
                if rollup_key == key:
                    proc[ROLLUP_FLAGS[target]] = False


def reopen(profile: dict[str, Any]) -> None:
    """A step edit on a closed walk reopens it and drops both list confirmations."""
    proc = process_of(profile)
    for flag in CONFIRMATION_FLAGS:
        proc[flag] = False


def finish_batch(
    profile: dict[str, Any],
    *,
    vocab: Vocabulary,
    was_closed: bool,
    steps_landed: bool,
    leaves: set[str],
) -> None:
    """The steps after every batch, in order: invalidate, resize, close test, roll-ups."""
    proc = process_of(profile)
    if steps_landed and was_closed:
        reopen(profile)
    if "roles" in leaves:
        proc[FLAG_ROLES_CONFIRMED] = False
    if "systems" in leaves:
        proc[FLAG_TOOLS_CONFIRMED] = False
    resize_steps(profile, vocab=vocab)
    close_if_complete(profile, vocab=vocab)
    rebuild_rollups(profile)


def grade_written(profile: Mapping[str, Any], written: Sequence[str], *, vocab: Vocabulary) -> dict[str, Verdict]:
    """The Verdict of every written key, after the whole batch; keys whose row was dropped are left out."""
    rows = rows_of(profile)
    out: dict[str, Verdict] = {}
    for key in written:
        address = resolve_key(key)
        if address is None or (address.step is not None and address.step > len(rows)):
            continue
        out[key] = grade(profile, key, vocab=vocab)
    return out


def step_upper_bound(profile: Mapping[str, Any]) -> int:
    """The highest step index a write may address: `min(P16, 6)` when P16 is set, else 6."""
    declared = coerce_number(process_of(profile).get("substep_count")) or 0
    return min(declared, MAX_STEPS) if declared else MAX_STEPS


# --- Expert changes -------------------------------------------------------------------------------


def _flatten(changes: Mapping[str, Any]) -> Iterator[tuple[Any, Any]]:
    for key, value in changes.items():
        nested = as_mapping(value) if key == "process" else None
        if nested is not None:
            for leaf, sub in nested.items():
                yield f"process.{leaf}", sub
        else:
            yield key, value


def _address(key: Any) -> Address | str:
    """The address of an incoming key, or the refusal reason."""
    if not isinstance(key, str):
        return UNKNOWN_KEY
    if key in _SIDECARS:
        return NOT_WRITABLE
    if key.startswith("process.") and key.split(".", 1)[1] in _CODE_OWNED_LEAVES:
        return NOT_WRITABLE
    parsed = parse_step_key(key)
    if parsed is not None and parsed[1] in _SIDECARS:
        return NOT_WRITABLE
    if parsed is not None and parsed[0] < 1 and step_spec_by_leaf(parsed[1]) is not None:
        return INDEX_OUT_OF_RANGE
    address = resolve_key(key)
    if address is None:
        return UNKNOWN_KEY
    if address.step is None and key != address.spec.key:
        return UNKNOWN_KEY  # a bare leaf ("volume") is not an accepted form
    return address


def _new_value(
    profile: dict[str, Any], address: Address, base: Any, value: Any, *, vocab: Vocabulary, replace: bool
) -> tuple[Any, str | None]:
    """The value to store (or `None` for "no change") and a refusal reason, by kind (§3.3)."""
    spec = address.spec
    if spec.kind == "text":
        text = coerce_text(value)
        if text is None:
            return None, SHAPE
        return normalise(spec, text, vocab), None
    if spec.kind == "list":
        if as_list(value) is None and not isinstance(value, str):
            return None, SHAPE
        return merged_list([] if replace else base, value), None
    if spec.kind == "number":
        number = coerce_number(value)
        return (number, None) if number is not None else (None, SHAPE)
    if spec.kind == "object":
        patch = filtered_object(spec, normalise(spec, value, vocab))
        if not patch:
            return None, SHAPE
        return merged_object(empty_value(spec) if replace else base, patch), None
    rows = filtered_rows(
        spec,
        value,
        own_step=address.step,
        step_count=step_upper_bound(profile) if address.step is not None else None,
    )
    if rows is None:
        return None, SHAPE
    if replace:
        real = [r for r in rows if "none" not in r]
        return (real or rows[:1]), None
    return merged_rows(spec, base, rows), None


def _current(profile: Mapping[str, Any], address: Address) -> Any:
    if address.step is None:
        if address.spec.is_process:
            return process_of(profile).get(address.spec.leaf)
        return profile.get(address.spec.key)
    rows = rows_of(profile)
    return rows[address.step - 1].get(address.spec.key) if address.step <= len(rows) else empty_value(address.spec)


def _write_one(
    profile: dict[str, Any],
    key: Any,
    value: Any,
    *,
    vocab: Vocabulary,
    meta: dict[str, Any],
    specialist: bool,
) -> tuple[str | None, str | None]:
    """Apply one change. Returns `(canonical key written, None)`, `(None, reason)` or `(None, None)` (no change)."""
    address = _address(key)
    if isinstance(address, str):
        return None, address
    spec = address.spec
    if specialist:
        if step_key_template(spec.key) not in specialist_keys() and spec.key not in specialist_keys():
            return None, NOT_WRITABLE
    elif not spec.extract:
        return None, NOT_WRITABLE
    if address.step is not None and not 1 <= address.step <= step_upper_bound(profile):
        return None, INDEX_OUT_OF_RANGE
    meta_now = meta_for(profile, address.key)
    if not specialist and meta_now is not None and meta_now.get("source") == SOURCE_SPECIALIST:
        return None, SPECIALIST_OWNED
    if _blank(value):
        return None, None
    proposed = is_proposed(meta_now)
    current = _current(profile, address)
    # A proposal is cleared first; one that completed a partial answer gives back what the person gave (spec 17 Q5).
    replaced = as_mapping((meta_now or {}).get("replaces")) if proposed else None
    base = (replaced.get("value") if replaced else empty_value(spec)) if proposed else current
    new, reason = _new_value(profile, address, base, value, vocab=vocab, replace=specialist)
    if reason is not None:
        return None, reason
    if spec.key == P16_KEY and isinstance(new, int):
        proc = process_of(profile)
        if not MIN_STEPS <= new <= MAX_STEPS:
            proc[FLAG_SUBSTEP_COUNT_REJECTED] = new
            return None, None
        proc[FLAG_SUBSTEP_COUNT_REJECTED] = None
    if new is None or (new == current and not proposed and not specialist):
        return None, None
    write_value(profile, address, new)
    set_meta(profile, address, meta)
    return address.key, None


def _apply_batch(
    profile: Mapping[str, Any] | None,
    changes: Any,
    *,
    vocab: Vocabulary,
    meta: dict[str, Any],
    specialist: bool,
) -> ChangeResult:
    result = normalized_profile(profile)
    source = as_mapping(changes)
    if source is None:
        return ChangeResult(result, [], [], {}, False)
    was_closed = process_of(result).get(FLAG_SUBSTEPS_COMPLETE) is True
    written: list[str] = []
    refused: list[tuple[str, str]] = []
    leaves: set[str] = set()
    steps_landed = False
    for key, value in _flatten(source):
        landed, reason = _write_one(result, key, value, vocab=vocab, meta=dict(meta), specialist=specialist)
        if reason is not None:
            shown = key if isinstance(key, str) else repr(key)
            refused.append((shown, reason))
            log_refusal(shown, reason, value)
            continue
        if landed is None:
            continue
        written.append(landed)
        parsed = parse_step_key(landed)
        if parsed is not None:
            steps_landed = True
            leaves.add(parsed[1])
    closed = close_written_conflicts(result, written)
    finish_batch(result, vocab=vocab, was_closed=was_closed, steps_landed=steps_landed, leaves=leaves)
    return ChangeResult(result, written, refused, grade_written(result, written, vocab=vocab), steps_landed, closed)


def close_written_conflicts(profile: dict[str, Any], written: Sequence[str]) -> tuple[str, ...]:
    """A person's write on a field closes that field's conflicts (spec 13 §3.13 item 3); returns their keys."""
    closed: list[str] = []
    for key in written:
        address = resolve_key(key)
        if address is None:
            continue
        holder = profile if address.step is None else rows_of(profile)[address.step - 1]
        container = as_dict(holder.get(CONFLICTS_KEY)) or {}
        leaf = address.spec.key
        for record in as_list(container.pop(leaf, None)) or []:
            sub = (as_mapping(record) or {}).get("sub")
            closed.append(address.key if not isinstance(sub, str) else f"{address.key}.{sub}")
    return tuple(closed)


def apply_changes(
    profile: Mapping[str, Any] | None, changes: Mapping[str, Any], *, vocab: Vocabulary, at: str
) -> ChangeResult:
    """Apply the expert's changes (EXTRACT output, already whitelisted) in the order of §3.4."""
    return _apply_batch(profile, changes, vocab=vocab, meta=make_meta(SOURCE_EXPERT, "confirmed", at), specialist=False)


# --- Settling the walk ----------------------------------------------------------------------------


def mark_cells_skipped(profile: Mapping[str, Any], keys: Sequence[str], *, vocab: Vocabulary) -> dict[str, Any]:
    """Settle these step cells for the walk (missing for the score); then the close test and roll-ups."""
    result = normalized_profile(profile)
    rows = rows_of(result)
    for key in keys:
        parsed = parse_step_key(key)
        if parsed is None or step_spec_by_leaf(parsed[1]) is None or not 1 <= parsed[0] <= len(rows):
            continue
        row = rows[parsed[0] - 1]
        leaf = parsed[1]
        if cell_counts(row, leaf, vocab=vocab):
            continue
        skipped = as_list(row.get(SKIPPED_KEY)) or []
        if leaf not in skipped:
            row[SKIPPED_KEY] = [*skipped, leaf]
    close_if_complete(result, vocab=vocab)
    rebuild_rollups(result)
    return result


def assume_substep_count(profile: Mapping[str, Any], *, vocab: Vocabulary, at: str) -> dict[str, Any]:
    """Settle a deferred P16 from the table: the last started row, at least 2 and at most 6. Fill-only."""
    result = normalized_profile(profile)
    if field_counts(result, P16_KEY, vocab=vocab):
        return result
    proc = process_of(result)
    proc["substep_count"] = _clamp(last_started_row(proc.get("substeps"), vocab=vocab))
    proc[FLAG_SUBSTEP_COUNT_REJECTED] = None
    address = resolve_key(P16_KEY)
    if address is not None:
        set_meta(result, address, make_meta(SOURCE_EXPERT, "confirmed", at))
    resize_steps(result, vocab=vocab)
    rebuild_rollups(result)
    return result


# --- Code-set values ------------------------------------------------------------------------------

DECIDED_BY: tuple[str, ...] = ("proposal", "named", "picker", "specialist")


def set_cluster(
    profile: Mapping[str, Any],
    code: str,
    *,
    decided_by: str,
    vocab: Vocabulary,
    at: str,
    by: str | None = None,
) -> dict[str, Any]:
    """The only writer of P05: `{code, name, decided_by}` from the company taxonomy."""
    if decided_by not in DECIDED_BY:
        raise ValueError(f"decided_by must be one of {DECIDED_BY}")
    cluster = vocab.taxonomy.by_code(code)
    if cluster is None:
        raise UnknownClusterError(code)
    result = normalized_profile(profile)
    process_of(result)["cluster"] = {"code": cluster.code, "name": cluster.name, "decided_by": decided_by}
    address = resolve_key("process.cluster")
    if address is not None:
        if decided_by == "specialist":
            meta = make_meta(SOURCE_SPECIALIST, "confirmed", at, by=by or "specialist")
        else:
            meta = make_meta(SOURCE_EXPERT, "confirmed", at)
        set_meta(result, address, meta)
    return result


def confirm_rollup(profile: Mapping[str, Any], target: str, *, vocab: Vocabulary) -> dict[str, Any]:
    """Raise `roles_confirmed` or `tools_confirmed`; the roll-ups are rebuilt first, so what is confirmed is what is shown."""
    if target not in ROLLUP_TARGETS:
        raise ValueError(f"unknown confirmation target {target!r}; expected one of {ROLLUP_TARGETS}")
    result = normalized_profile(profile)
    rebuild_rollups(result)
    process_of(result)[ROLLUP_FLAGS[target]] = True
    return result


def set_field(profile: Mapping[str, Any], key: str, value: Any, *, by: str, vocab: Vocabulary, at: str) -> ChangeResult:
    """A specialist edit: the value replaces the stored one (no merge); meta specialist/confirmed."""
    address = resolve_key(key)
    if address is not None and address.spec.id == "P05":
        source = as_mapping(value)
        code = source.get("code") if source is not None else value
        try:
            result = set_cluster(profile, str(code or ""), decided_by="specialist", vocab=vocab, at=at, by=by)
        except UnknownClusterError:
            log_refusal(key, SHAPE, value)
            return ChangeResult(normalized_profile(profile), [], [(key, SHAPE)], {}, False)
        return ChangeResult(result, [address.key], [], grade_written(result, [address.key], vocab=vocab), False)
    return _apply_batch(
        profile, {key: value}, vocab=vocab, meta=make_meta(SOURCE_SPECIALIST, "confirmed", at, by=by), specialist=True
    )
