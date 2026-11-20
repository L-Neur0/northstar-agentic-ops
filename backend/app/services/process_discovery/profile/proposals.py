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
sub-value a person gave. AC-17.52, AC-17.62 to AC-17.64.
Amendment (spec 17 §3.21, spec 13 §3.13, approved 2026-11-20): every offer is re-checked with
`conflicts.plan_offer` (C1–C8) at write time; a differing value is stored as a conflict, never
written; lists from two files merge with one source per item (`parts`); removal is per item and a
held document conflict becomes a proposal (P5, P6); ✓ closes a field's conflicts. AC-13.57,
AC-17.70 to AC-17.78.
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
from .conflicts import (
    CONFLICT,
    SAME_VALUE,
    close_conflicts,
    item_name,
    item_sources,
    merged_meta,
    open_conflicts,
    plan_offer,
    same_single,
    store_conflict,
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
    as_list,
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
class ConflictOffer:
    """A document value that differs from a stored unit (spec 17 §3.21 item 4); `sub=None` is the whole field."""

    key: str
    sub: str | None
    value: Any
    quote: str


@dataclass(frozen=True)
class ProposalDiff:
    """Everything one document proposes. `steps` and `step_cells` are never both non-empty.

    `conflicts` (spec 17 §3.21) are recorded, never proposed; `from_image` is copied onto meta, parts
    and conflict records at write time (P7).
    """

    document_id: str
    fields: tuple[FieldProposal, ...] = ()
    steps: tuple[StepProposal, ...] = ()
    step_cells: tuple[FieldProposal, ...] = ()
    conflicts: tuple[ConflictOffer, ...] = ()
    from_image: bool = False

    @property
    def is_empty(self) -> bool:
        return not (self.fields or self.steps or self.step_cells or self.conflicts)


class ProposalResult(NamedTuple):
    """The new profile, the keys written as proposals, the refused keys with a reason, the conflict keys stored."""

    profile: dict[str, Any]
    applied: list[str]
    refused: list[tuple[str, str]]
    conflicts: tuple[str, ...] = ()


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


def _propose_one(
    profile: dict[str, Any],
    proposal: FieldProposal,
    key: str,
    *,
    diff: ProposalDiff,
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
    if not diff.document_id or not proposal.quote.strip():
        return None, NO_QUOTE
    if address.step is not None and not 1 <= address.step <= max_index:
        return None, INDEX_OUT_OF_RANGE
    if _out_of_bounds(address, proposal.value):
        return None, OUT_OF_BOUNDS
    value = _proposal_value(profile, address, proposal.value, vocab=vocab)
    if value is None:
        return None, SHAPE
    plan = plan_offer(profile, address.key, value, vocab=vocab)  # C1–C8 re-checked at write time
    if plan.refusal is not None:
        return None, plan.refusal
    if plan.value is None:
        return None, CONFLICT if plan.conflicts else SAME_VALUE
    old_value = copy.deepcopy(stored_value(profile, address.key))
    old_meta = meta_for(profile, address.key)
    write_value(profile, address, plan.value)
    meta = _document_meta(diff, proposal.quote, at, replaces=plan.replaces)
    if plan.merged:
        meta = merged_meta(address.spec, plan.value, old_value, old_meta, meta)
    set_meta(profile, address, meta)
    return address.key, None


def _document_meta(diff: ProposalDiff, quote: str, at: str, *, replaces: Mapping[str, Any] | None) -> dict[str, Any]:
    meta = make_meta(
        SOURCE_DOCUMENT, "proposed", at, document_id=diff.document_id, quote=quote.strip(), replaces=replaces
    )
    if diff.from_image:
        meta["fromImage"] = True
    return meta


def _offered_unit(spec: FieldSpec, offer: ConflictOffer) -> Any:
    if offer.sub is None:
        return offer.value
    return {**empty_value(spec), offer.sub: offer.value}


def _record_conflict(
    profile: dict[str, Any], offer: ConflictOffer, *, diff: ProposalDiff, vocab: Vocabulary, at: str
) -> tuple[str | None, str | None]:
    """Re-check one conflict at write time: still a conflict → stored; the unit emptied → a proposal (AC-13.57)."""
    address = resolve_key(offer.key)
    if address is None or (address.step is not None and address.step > len(rows_of(profile))):
        return None, NOT_PROPOSABLE
    plan = plan_offer(profile, address.key, _offered_unit(address.spec, offer), vocab=vocab)
    if plan.refusal is not None and not plan.conflicts:
        return None, plan.refusal
    if plan.value is not None and not any(c.sub == offer.sub for c in plan.conflicts):
        landed, reason = _propose_one(
            profile,
            FieldProposal(address.key, plan.value, offer.quote),
            address.key,
            diff=diff,
            vocab=vocab,
            at=at,
            max_index=len(rows_of(profile)),
        )
        return None, reason if landed is None else None
    found = next((c for c in plan.conflicts if c.sub == offer.sub), None)
    if found is None:
        return None, SAME_VALUE
    stored = store_conflict(
        profile, address, found, document_id=diff.document_id, quote=offer.quote, from_image=diff.from_image, at=at
    )
    return stored, None


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
        landed, reason = _propose_one(result, proposal, key, diff=diff, vocab=vocab, at=at, max_index=max_index)
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

    conflicts: list[str] = []
    for offer in diff.conflicts:
        stored, reason = _record_conflict(result, offer, diff=diff, vocab=vocab, at=at)
        if stored is not None:
            conflicts.append(stored)
        elif reason is not None:
            refused.append((offer.key, reason))

    steps_landed = bool(leaves)
    finish_batch(result, vocab=vocab, was_closed=was_closed, steps_landed=steps_landed, leaves=set())
    return ProposalResult(result, applied, refused, tuple(conflicts))


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
    if written:  # ✓ on a field with an open conflict keeps the stored value (spec 14 §3.17 R3)
        result, _closed = close_conflicts(result, written)
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


def _without_document(spec: FieldSpec, value: Any, meta: Mapping[str, Any], document_id: str) -> tuple[Any, list[Any]]:
    """P5: the value with the removed document's items taken out, and the sources of the items that stay."""
    sources = item_sources(spec, value, meta)
    gone = [(s["sub"], s["item"]) for s in sources if s.get("documentId") == document_id]
    kept = [s for s in sources if s.get("documentId") != document_id]

    def keep(sub: str | None, items: Any) -> list[Any]:
        return [
            i
            for i in as_list(items) or []
            if not any(g[0] == sub and g[1] is not None and same_single(g[1], item_name(spec, i)) for g in gone)
        ]

    if spec.kind == "object":
        out = dict(as_mapping(value) or {})
        for sub in spec.subfields:
            if sub.kind == "list":
                out[sub.key] = keep(sub.key, out.get(sub.key))
        return out, kept
    return keep(None, value), kept


def remove_document_proposals(
    profile: Mapping[str, Any], document_id: str, *, vocab: Vocabulary, at: str
) -> ChangeResult:
    """Remove a document's open proposals, per item (spec 17 §3.21 P5, P6); values confirmed from it stay.

    A proposed value that mixes sources keeps the other sources' items; one left with nothing is
    cleared (or restored from `replaces`). The document's conflicts go; a document conflict it held
    whose proposal was cleared becomes the offering document's proposal on the now-empty unit.
    """
    normal = normalized_profile(profile)
    views = open_conflicts(normal)
    promote = [v for v in views if v.kind == "document" and v.holder_document_id == document_id]
    for view in views:
        if view.document_id == document_id or view in promote:
            normal, _closed = close_conflicts(normal, [view.conflict_key])
    keys: list[str] = []
    for key in proposed_keys(normal):
        meta = meta_for(normal, key) or {}
        address = resolve_key(key)
        parts = as_list(meta.get("parts")) or []
        if address is not None and any((as_mapping(x) or {}).get("documentId") == document_id for x in parts):
            value, kept = _without_document(address.spec, stored_value(normal, key), meta, document_id)
            if kept and has_any_answer(address.spec, value):
                write_value(normal, address, value)
                newest = kept[-1]
                new_meta = {**dict(meta), **{k: newest.get(k) for k in ("source", "documentId", "quote", "fromImage")}}
                if len({(k.get("source"), k.get("documentId")) for k in kept}) > 1:
                    new_meta["parts"] = kept
                else:
                    new_meta.pop("parts", None)
                if not new_meta.get("fromImage"):
                    new_meta.pop("fromImage", None)
                set_meta(normal, address, new_meta)
                continue
            keys.append(key)
            continue
        if meta.get("documentId") == document_id:
            keys.append(key)
    result = reject_proposals(normal, keys, vocab=vocab, at=at)
    profile_after = result.profile
    for view in promote:  # P6
        address = resolve_key(view.key)
        if address is None:
            continue
        diff = ProposalDiff(view.document_id, from_image=view.from_image)
        unit = view.offered if view.sub is None else {**empty_value(address.spec), view.sub: view.offered}
        _propose_one(
            profile_after,
            FieldProposal(view.key, unit, view.quote),
            view.key,
            diff=diff,
            vocab=vocab,
            at=at,
            max_index=len(rows_of(profile_after)),
        )
    return ChangeResult(profile_after, result.written, [], {}, result.touched_steps)


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
