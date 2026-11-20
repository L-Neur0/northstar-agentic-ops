"""Document proposals: the hand-over types and the fill-only writer for machine-found values (specs 13 §3.6, 17 §3.11).

Why: a value read from an uploaded document (or, for P04 only, an idea's name) is only a proposal
until the expert confirms it. It is stored like any value, but its meta says `status: proposed`,
and it never counts (score, row completeness, *Finish*). The rules are the fill-only rules for
machine-found data: a proposal may fill a gap, never overrule a person. The document reader
(spec 17) and the profile writer are built by different workstreams, so the shared types are
declared here exactly as both specs state, and `documents/` imports them downward.
What: the frozen dataclasses `FieldProposal`, `StepProposal`, `ProposalDiff` and the result type
`ProposalResult` (unchanged contract), and `apply_proposals`, `confirm_proposals`,
`reject_proposals`, `remove_document_proposals`, `propose_from_idea`, `proposed_keys`.
Must not: count a proposed value toward completeness, let a proposal overwrite a value the expert
or a specialist gave, add rows to a table that already has content, set P16 from a document, or
log a value. Spec 13 §3.6; AC-13.33 to AC-13.44.
Amendment (spec 17 Q5/Q7, decided 2026-11-20): a partly answered object field (volume with a count
and no period; step data with inputs and no outputs) may take a WHOLE-field proposal: the person's
sub-values unchanged plus the document's missing ones, with meta `replaces` = the previous value and
meta; a no restores them exactly and a yes confirms the whole field. A document never changes a
sub-value a person gave (`fill_target`, `merge_offered`). AC-17.52, AC-17.62 to AC-17.65.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

from ..domain.field_spec import (
    MAX_STEPS,
    MIN_STEPS,
    PROFILE_SPECS,
    SOURCE_DOCUMENT,
    SOURCE_EXPERT,
    SOURCE_SPECIALIST,
    STEP_SPECS,
    FieldSpec,
    Vocabulary,
    evaluate_field,
    has_any_answer,
    is_proposed,
    proposal_keys,
    step_cell_key,
    step_key_template,
)
from .coercion import (
    coerce_number,
    coerce_text,
    filtered_object,
    filtered_rows,
    merged_list,
    normalise,
    raw_number,
)
from .constants import (
    CONFIRMED,
    FLAG_SUBSTEPS_COMPLETE,
    INDEX_OUT_OF_RANGE,
    NO_QUOTE,
    NOT_PROPOSABLE,
    NUMBER_BOUNDS_PROPOSAL,
    OUT_OF_BOUNDS,
    SHAPE,
    SPECIALIST_OWNED,
    TABLE_NOT_EMPTY,
)
from .mutate import (
    ChangeResult,
    close_if_complete,
    finish_batch,
    grade_written,
    log_refusal,
    make_meta,
    rebuild_rollups,
    remove_meta,
    reopen,
    resize_steps,
    set_meta,
    write_value,
)
from .shapes import (
    Address,
    as_dict,
    as_mapping,
    empty_value,
    meta_for,
    normalized_profile,
    process_of,
    resolve_key,
    rows_of,
    stored_value,
)
from .verdicts import P16_KEY, cell_counts, last_started_row


@dataclass(frozen=True)
class FieldProposal:
    """One proposed value with its verified quote.

    `key`: a registry key for a process field ("process.trigger"); a 1-based step cell key in
    `ProposalDiff.step_cells` ("process.substeps[2].data"); the bare leaf inside `StepProposal`.
    """

    key: str
    value: Any
    quote: str


@dataclass(frozen=True)
class StepProposal:
    """One new step row proposed into an empty step table; `cells[0]` is always the name."""

    cells: tuple[FieldProposal, ...]


@dataclass(frozen=True)
class ProposalDiff:
    """Everything one document proposes. `steps` and `step_cells` are never both non-empty."""

    document_id: str
    fields: tuple[FieldProposal, ...] = ()
    steps: tuple[StepProposal, ...] = ()
    step_cells: tuple[FieldProposal, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.fields or self.steps or self.step_cells)


class ProposalResult(NamedTuple):
    """The new profile, the keys written as proposals, and the refused keys with a reason."""

    profile: dict[str, Any]
    applied: list[str]
    refused: list[tuple[str, str]]


# --- Applying ----------------------------------------------------------------------------------------


def _out_of_bounds(address: Address, value: Any) -> bool:
    """A number (field or object sub-field) outside 0..1,000,000 is a parse artefact."""
    low, high = NUMBER_BOUNDS_PROPOSAL
    numbers: list[Any] = []
    if address.spec.kind == "number":
        numbers.append(value)
    elif address.spec.kind == "object":
        source = as_mapping(value) or {}
        numbers += [source.get(s.key) for s in address.spec.subfields if s.kind == "number" and s.key in source]
    for raw in numbers:
        if raw is None:
            continue
        number = raw_number(raw)
        if number is not None and not low <= number <= high:
            return True
    return False


def _proposal_value(profile: Mapping[str, Any], address: Address, value: Any, *, vocab: Vocabulary) -> Any:
    """The value coerced by kind and written whole (the target is empty or a proposal); `None` if unusable."""
    spec = address.spec
    if spec.kind == "text":
        text = coerce_text(value)
        return normalise(spec, text, vocab) if text is not None else None
    if spec.kind == "list":
        return merged_list([], value)
    if spec.kind == "number":
        return coerce_number(value)
    if spec.kind == "object":
        patch = filtered_object(spec, normalise(spec, value, vocab))
        if not patch:
            return None
        return {**empty_value(spec), **patch}
    upper = coerce_number(process_of(profile).get("substep_count")) or MAX_STEPS
    rows = filtered_rows(spec, value, own_step=address.step, step_count=upper)
    real = [r for r in (rows or []) if "none" not in r]
    return real or None


@dataclass(frozen=True)
class FillTarget:
    """What a proposal may do at one key: refused, or free with the person's sub-values `fixed`.

    `fixed`: sub-values a person gave that no proposal may change (a partly answered field).
    `current`: the stored value when the target is itself a proposal (S07 lists are merged into it).
    `replaces`: what the new meta's `replaces` holds (`{"value", "meta"}`), carried over from an older proposal.
    """

    refusal: str | None = None
    fixed: Any = None
    current: Any = None
    replaces: dict[str, Any] | None = None


def fill_target(profile: Mapping[str, Any], key: str, *, vocab: Vocabulary | None) -> FillTarget:
    """The fill-only rules (§3.6 rules 3–5) plus partial answers (spec 17 Q5); `vocab=None` means no partial fill."""
    address = resolve_key(key)
    if address is None:
        return FillTarget(refusal=NOT_PROPOSABLE)
    meta = meta_for(profile, address.key)
    if meta is not None and meta.get("source") == SOURCE_SPECIALIST:
        return FillTarget(refusal=SPECIALIST_OWNED)
    value = stored_value(profile, address.key)
    answered = has_any_answer(address.spec, value)
    if is_proposed(meta):
        replaces = as_mapping((meta or {}).get("replaces"))
        return FillTarget(
            fixed=replaces.get("value") if replaces else None,
            current=value if answered else None,
            replaces=dict(replaces) if replaces else None,
        )
    if not answered:
        return FillTarget()
    if (
        address.spec.kind == "object"
        and vocab is not None
        and not evaluate_field(address.spec, value, profile, vocab).is_complete
    ):
        return FillTarget(fixed=value, replaces={"value": copy.deepcopy(value), "meta": dict(meta) if meta else None})
    return FillTarget(refusal=CONFIRMED)


def _blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {} or value is False


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()
    return a == b


def _union(first: Any, second: Any) -> list[str]:
    out: list[str] = []
    for item in [*(_strings(first)), *(_strings(second))]:
        if not any(_same(item, seen) for seen in out):
            out.append(item)
    return out


def _strings(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []  # pyright: ignore[reportUnknownVariableType]


def merge_offered(spec: FieldSpec, offered: Any, target: FillTarget) -> tuple[Any, int]:
    """The whole value to propose and the number of offered sub-values that contradict a person's.

    Non-object kinds pass through. For an object: S07 lists are merged into a stored proposal (spec 17
    D7); every `fixed` sub-value is kept as the person gave it, and a differing offered one is counted
    as a conflict. `None` when the proposal adds nothing to what the person gave.
    """
    if spec.kind != "object":
        return offered, 0
    value: dict[str, Any] = dict(as_mapping(offered) or {})
    current = as_mapping(target.current)
    if current is not None:
        for sub in spec.subfields:
            if sub.kind == "list":
                value[sub.key] = _union(current.get(sub.key), value.get(sub.key))
    fixed = as_mapping(target.fixed)
    if fixed is None:
        return value, 0
    conflicts = 0
    added = False
    for sub in spec.subfields:
        mine = fixed.get(sub.key)
        theirs = value.get(sub.key)
        if sub.kind == "bool":
            value[sub.key] = mine if mine is not None else theirs
        elif sub.kind == "list":
            if _strings(mine):
                conflicts += sum(1 for t in _strings(theirs) if not any(_same(t, m) for m in _strings(mine)))
                value[sub.key] = list(_strings(mine))
            else:
                added = added or bool(_strings(theirs))
        elif not _blank(mine):
            if not _blank(theirs) and not _same(mine, theirs):
                conflicts += 1
            value[sub.key] = mine
        else:
            added = added or not _blank(theirs)
    return (value if added else None), conflicts


def _propose_one(
    profile: dict[str, Any],
    proposal: FieldProposal,
    key: str,
    *,
    document_id: str,
    vocab: Vocabulary,
    at: str,
    max_index: int,
) -> tuple[str | None, str | None]:
    address = resolve_key(key)
    template = step_key_template(address.spec.key) if address is not None and address.step is not None else None
    if address is None or (template or address.spec.key) not in proposal_keys():
        return None, NOT_PROPOSABLE
    if address.step is None and key != address.spec.key:
        return None, NOT_PROPOSABLE
    if not document_id or not proposal.quote.strip():
        return None, NO_QUOTE
    if address.step is not None and not 1 <= address.step <= max_index:
        return None, INDEX_OUT_OF_RANGE
    target = fill_target(profile, address.key, vocab=vocab)
    if target.refusal is not None:
        return None, target.refusal
    if _out_of_bounds(address, proposal.value):
        return None, OUT_OF_BOUNDS
    value = _proposal_value(profile, address, proposal.value, vocab=vocab)
    if value is None:
        return None, SHAPE
    value, _conflicts = merge_offered(address.spec, value, target)
    if value is None:
        return None, CONFIRMED
    write_value(profile, address, value)
    meta = make_meta(
        SOURCE_DOCUMENT,
        "proposed",
        at,
        document_id=document_id,
        quote=proposal.quote.strip(),
        replaces=target.replaces,
    )
    set_meta(profile, address, meta)
    return address.key, None


def apply_proposals(profile: Mapping[str, Any], diff: ProposalDiff, *, vocab: Vocabulary, at: str) -> ProposalResult:
    """Write the diff as proposals, fill-only (spec 13 §3.6). The score does not move."""
    result = normalized_profile(profile)
    proc = process_of(result)
    was_closed = proc.get(FLAG_SUBSTEPS_COMPLETE) is True
    table_empty = last_started_row(proc.get("substeps"), vocab=vocab) == 0
    declared = coerce_number(proc.get("substep_count")) or 0
    applied: list[str] = []
    refused: list[tuple[str, str]] = []
    leaves: set[str] = set()

    def take(proposal: FieldProposal, key: str, max_index: int) -> None:
        landed, reason = _propose_one(
            result, proposal, key, document_id=diff.document_id, vocab=vocab, at=at, max_index=max_index
        )
        if reason is not None:
            refused.append((key, reason))
            log_refusal(key, reason, proposal.value)
        elif landed is not None:
            applied.append(landed)
            address = resolve_key(landed)
            if address is not None and address.step is not None:
                leaves.add(address.spec.key)

    for proposal in diff.fields:
        take(proposal, proposal.key, MAX_STEPS)

    new_rows_bound = min(declared, MAX_STEPS) if declared else MAX_STEPS
    for position, step in enumerate(diff.steps, start=1):
        for cell in step.cells:
            key = step_cell_key(position, cell.key)
            if not table_empty:
                refused.append((key, TABLE_NOT_EMPTY))
                log_refusal(key, TABLE_NOT_EMPTY, cell.value)
                continue
            take(cell, key, new_rows_bound)

    existing_rows = len(rows_of(result))
    for proposal in diff.step_cells:
        take(proposal, proposal.key, existing_rows)

    steps_landed = bool(leaves)
    finish_batch(result, vocab=vocab, was_closed=was_closed, steps_landed=steps_landed, leaves=set())
    return ProposalResult(result, applied, refused)


# --- Confirming and rejecting --------------------------------------------------------------------


def _proposed_addresses(profile: Mapping[str, Any], keys: Sequence[str]) -> list[Address]:
    out: list[Address] = []
    seen: set[str] = set()
    for key in keys:
        address = resolve_key(key)
        if address is None or address.key in seen:
            continue
        if is_proposed(meta_for(profile, address.key)):
            seen.add(address.key)
            out.append(address)
    return out


def confirm_proposals(profile: Mapping[str, Any], keys: Sequence[str], *, vocab: Vocabulary, at: str) -> ChangeResult:
    """Confirm the proposed keys (value unchanged; source, document id and quote kept); P16 follows the steps."""
    result = normalized_profile(profile)
    written: list[str] = []
    for address in _proposed_addresses(result, keys):
        meta = dict(meta_for(result, address.key) or {})
        meta.update(status="confirmed", at=at)
        meta.pop("replaces", None)
        set_meta(result, address, meta)
        written.append(address.key)
    rows = rows_of(result)
    if (
        written
        and process_of(result).get("substep_count") is None
        and MIN_STEPS <= len(rows) <= MAX_STEPS
        and all(cell_counts(r, "name", vocab=vocab) for r in rows)
    ):
        process_of(result)["substep_count"] = len(rows)
        process_of(result)["substep_count_rejected"] = None
        address = resolve_key(P16_KEY)
        if address is not None:
            set_meta(result, address, make_meta(SOURCE_EXPERT, "confirmed", at))
            written.append(P16_KEY)
    close_if_complete(result, vocab=vocab)
    rebuild_rollups(result)
    touched = any(resolve_key(k) is not None and "substeps[" in k for k in written)
    return ChangeResult(result, written, [], grade_written(result, written, vocab=vocab), touched)


def reject_proposals(profile: Mapping[str, Any], keys: Sequence[str], *, vocab: Vocabulary, at: str) -> ChangeResult:
    """Clear each proposed key to its empty value and drop its meta; trailing empty rows go; roll-ups follow."""
    result = normalized_profile(profile)
    was_closed = process_of(result).get(FLAG_SUBSTEPS_COMPLETE) is True
    written: list[str] = []
    for address in _proposed_addresses(result, keys):
        if address.step is not None and address.step > len(rows_of(result)):
            continue
        replaced = as_mapping((meta_for(result, address.key) or {}).get("replaces"))
        if replaced is not None:  # a proposal over a partial answer: restore exactly what was there (AC-17.64)
            write_value(result, address, copy.deepcopy(replaced.get("value")))
            previous = as_mapping(replaced.get("meta"))
            if previous is not None:
                set_meta(result, address, dict(previous))
            else:
                remove_meta(result, address)
        else:
            write_value(result, address, empty_value(address.spec))
            remove_meta(result, address)
        written.append(address.key)
    steps = any("substeps[" in k for k in written)
    if steps and was_closed:
        reopen(result)
    resize_steps(result, vocab=vocab)
    close_if_complete(result, vocab=vocab)
    rebuild_rollups(result)
    return ChangeResult(result, written, [], {}, steps)


def remove_document_proposals(
    profile: Mapping[str, Any], document_id: str, *, vocab: Vocabulary, at: str
) -> ChangeResult:
    """Reject every unconfirmed proposal from `document_id`; values confirmed from it stay."""
    normal = normalized_profile(profile)
    keys = [k for k in proposed_keys(normal) if (meta_for(normal, k) or {}).get("documentId") == document_id]
    return reject_proposals(normal, keys, vocab=vocab, at=at)


def propose_from_idea(profile: Mapping[str, Any], name: str, words: str, *, at: str) -> dict[str, Any]:
    """A session started from an idea: P04 gets the name as `{source: expert, status: proposed, quote: words}`."""
    result = normalized_profile(profile)
    text = coerce_text(name)
    address = resolve_key("process.name")
    if text is None or address is None or has_any_answer(address.spec, process_of(result).get("name")):
        return result
    write_value(result, address, text)
    set_meta(result, address, make_meta(SOURCE_EXPERT, "proposed", at, quote=(coerce_text(words) or text)))
    return result


def proposed_keys(profile: Mapping[str, Any]) -> list[str]:
    """Every proposed field, canonical keys, in ask order: process fields, then step 1 S01…S12, step 2, …"""
    out: list[str] = []
    for spec in PROFILE_SPECS:
        meta = meta_for(profile, spec.key)
        if is_proposed(meta) and has_any_answer(spec, stored_value(profile, spec.key)):
            out.append(spec.key)
    for index, row in enumerate(rows_of(profile), start=1):
        metas = as_dict(row.get("__meta")) or {}
        for spec in STEP_SPECS:
            if is_proposed(as_mapping(metas.get(spec.key))) and has_any_answer(spec, row.get(spec.key)):
                out.append(step_cell_key(index, spec.key))
    return out
