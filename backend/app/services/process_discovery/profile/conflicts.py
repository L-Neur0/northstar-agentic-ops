"""Conflicts between a document and a stored value, and a source per item (spec 17 §3.21, spec 13 §3.13).

Why: a document that says something different from the expert, or from another document, must not
be thrown away and must not overwrite anything (product rule 4: the expert has the last word). Code
decides, per unit (a whole field, or one sub-field of an object), whether the offer is the same
meaning, a gap to fill, a list to merge, or a real conflict to keep until the expert chooses. "Same"
is decided by code with the duration and frequency parsers of `domain/value_parse.py`, so "monthly"
and "every month" are never put to the expert as a conflict (decision 2, approved 2026-11-20).
What: `same_single` / `covered` (same meaning), `plan_offer` (rules C1–C8 for one offered value),
`item_source_parts` (P1–P4), the `__conflicts` sidecar readers and writers (`store_conflict`,
`open_conflicts`, `close_conflicts`, `mark_conflicts_left`) and `resolve_conflicts` (what a choice
writes, spec 13 §3.13 item 2).
Must not: read a clock (`at` is passed in), call a model, log a value, change the score or the
counting rule (a conflict is a sidecar), or let a document value outrank a specialist's.
Spec 17 §3.21 (C1–C8, P1–P7), spec 13 §3.13; AC-13.57 to AC-13.61, AC-17.70 to AC-17.81.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ..domain.field_spec import (
    CONFLICTS_KEY,
    PROFILE_SPECS,
    SOURCE_DOCUMENT,
    SOURCE_SPECIALIST,
    STEP_SPECS,
    FieldSpec,
    Vocabulary,
    evaluate_field,
    has_any_answer,
    is_none_row,
    is_proposed,
    required_subfield,
    step_cell_key,
)
from ..domain.value_parse import parse_duration, parse_frequency, periods_a_year
from .constants import CONFIRMED, SPECIALIST_OWNED
from .mutate import ChangeResult, finish_batch, grade_written, set_meta, write_value
from .shapes import (
    Address,
    as_dict,
    as_list,
    as_mapping,
    meta_for,
    normalized_profile,
    process_of,
    resolve_key,
    row_at,
    rows_of,
    stored_value,
)

SAME_VALUE = "same_value"
#: A refusal reason at write time: the offer differs and is (or was) recorded as a conflict, never written.
CONFLICT = "conflict"
#: Units that never conflict (spec 17 §3.21 note 2): the step name (the match key), P16 and the cluster.
NO_CONFLICT_KEYS: frozenset[str] = frozenset({"name", "process.substep_count", "process.cluster"})
LIST_MAX_DEFAULT = 20
Choice = Literal["current", "offered", "both"]
_PUNCT = re.compile(r"[^\w\s]+")


# --- Same meaning (decision 2) ------------------------------------------------------------------


def _norm(text: str) -> str:
    return " ".join(_PUNCT.sub(" ", text.casefold()).split())


def _meaning(text: str) -> tuple[Any, ...] | None:
    """The number and period of a duration, frequency or period word, or `None` when it is none of them."""
    duration = parse_duration(text)
    if duration is not None:
        return ("hours", round(duration.hours, 4))
    frequency = parse_frequency(text)
    if frequency is not None:
        return (frequency.kind, round(frequency.value, 4))
    periods = periods_a_year(text)
    return ("periodic", round(periods, 4)) if periods is not None else None


def same_single(a: Any, b: Any) -> bool:
    """Same after case, whitespace and punctuation; numbers equal; durations and frequencies by number and period."""
    if isinstance(a, str) and isinstance(b, str):
        if _norm(a) == _norm(b):
            return True
        meaning = _meaning(a)
        return meaning is not None and meaning == _meaning(b)
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return float(a) == float(b)
    if isinstance(a, str) and isinstance(b, int | float):
        return _norm(a) == _norm(str(b))
    if isinstance(b, str) and isinstance(a, int | float):
        return _norm(b) == _norm(str(a))
    return a == b


def item_name(spec: FieldSpec | None, item: Any) -> str:
    """What identifies a list item: the text, or a row's required sub-field."""
    if isinstance(item, str):
        return item
    row = as_mapping(item)
    required = required_subfield(spec) if spec is not None else None
    if row is not None and required is not None:
        return str(row.get(required) or "")
    return ""


def covered(spec: FieldSpec | None, stored: Any, offered: Any) -> bool:
    """Every offered item is the same as a stored item."""
    have = [item_name(spec, i) for i in as_list(stored) or []]
    return all(any(same_single(item_name(spec, o), h) for h in have) for o in as_list(offered) or [])


def union(spec: FieldSpec | None, stored: Any, offered: Any) -> list[Any]:
    """Stored items first, then the offered items not already present (duplicates by meaning removed)."""
    out: list[Any] = [i for i in as_list(stored) or [] if not is_none_row(i)]
    for item in as_list(offered) or []:
        if not any(same_single(item_name(spec, item), item_name(spec, o)) for o in out):
            out.append(item)
    return out


def _blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {} or value is False


def is_list_like(spec: FieldSpec, sub: str | None) -> bool:
    if sub is None:
        return spec.kind in ("list", "object_list")
    return any(s.key == sub and s.kind == "list" for s in spec.subfields)


def list_max(spec: FieldSpec) -> int:
    return spec.max_items or LIST_MAX_DEFAULT


# --- Planning one offer (C1–C8) -----------------------------------------------------------------


@dataclass(frozen=True)
class Offer:
    """One conflict found by `plan_offer`: the sub-field (or `None`), the offered unit and who holds the stored one."""

    sub: str | None
    value: Any
    kind: Literal["expert", "document"]
    holder_document_id: str | None
    list: bool


@dataclass(frozen=True)
class Plan:
    """What one offered value does at one key: a refusal, a proposal to write, conflicts, or nothing (`same_value`)."""

    refusal: str | None = None
    value: Any = None
    replaces: dict[str, Any] | None = None
    merged: bool = False
    conflicts: tuple[Offer, ...] = ()


def _leaf(address: Address) -> str:
    return address.spec.key if address.step is not None else address.key


def plan_offer(profile: Mapping[str, Any], key: str, offered: Any, *, vocab: Vocabulary | None) -> Plan:
    """Rules C1–C8 of spec 17 §3.21 for one offered (registry-shaped) value; pure.

    `vocab=None` disables filling the missing part of a partly answered object (spec 17 Q5).
    """
    address = resolve_key(key)
    if address is None:
        return Plan(refusal=CONFIRMED)
    spec = address.spec
    meta = meta_for(profile, address.key)
    if meta is not None and meta.get("source") == SOURCE_SPECIALIST:
        return Plan(refusal=SPECIALIST_OWNED)  # C7
    stored = stored_value(profile, address.key)
    answered = has_any_answer(spec, stored)
    proposed = is_proposed(meta)
    if not answered or (proposed and (meta or {}).get("source") != SOURCE_DOCUMENT):
        return Plan(value=offered)  # C1 (and P04 proposed from an idea, note 2)
    if _leaf(address) in NO_CONFLICT_KEYS:
        return Plan(value=offered) if proposed else Plan(refusal=CONFIRMED)
    holder_doc = (meta or {}).get("documentId") if (meta or {}).get("source") == SOURCE_DOCUMENT else None
    if spec.kind == "object":
        return _plan_object(
            profile, address, stored, offered, meta, proposed=proposed, holder_doc=holder_doc, vocab=vocab
        )
    if proposed:  # holder document
        if spec.kind in ("list", "object_list"):
            if covered(spec, stored, offered):
                return Plan(refusal=SAME_VALUE)  # C6
            return Plan(value=union(spec, stored, offered)[: list_max(spec)], merged=True)  # C4
        if same_single(stored, offered):
            return Plan(refusal=SAME_VALUE)
        return Plan(conflicts=(Offer(None, offered, "document", holder_doc, False),))  # C5
    if spec.kind in ("list", "object_list"):
        if any(is_none_row(i) for i in as_list(stored) or []):
            return Plan(conflicts=(Offer(None, offered, "expert", holder_doc, False),))  # C8
        if covered(spec, stored, offered):
            return Plan(refusal=SAME_VALUE)  # C2
        return Plan(conflicts=(Offer(None, offered, "expert", holder_doc, True),))  # C3
    if same_single(stored, offered):
        return Plan(refusal=SAME_VALUE)
    return Plan(conflicts=(Offer(None, offered, "expert", holder_doc, False),))


def _plan_object(
    profile: Mapping[str, Any],
    address: Address,
    stored: Any,
    offered: Any,
    meta: Mapping[str, Any] | None,
    *,
    proposed: bool,
    holder_doc: str | None,
    vocab: Vocabulary | None,
) -> Plan:
    """Per sub-field: the expert's sub-values conflict or match; the document's merge or conflict; gaps fill."""
    spec = address.spec
    current = dict(as_mapping(stored) or {})
    theirs_all = as_mapping(offered) or {}
    replaces = as_mapping((meta or {}).get("replaces")) if proposed else None
    fixed = as_mapping(replaces.get("value")) if replaces is not None else (None if proposed else current)
    fixed = fixed or {}
    none_flag = any(s.kind == "bool" and fixed.get(s.key) is True for s in spec.subfields)
    can_fill = proposed or (vocab is not None and not evaluate_field(spec, stored, profile, vocab).is_complete)
    value = copy.deepcopy(current)
    added = merged = False
    conflicts: list[Offer] = []
    for sub in spec.subfields:
        theirs = theirs_all.get(sub.key)
        if sub.kind == "bool" or _blank(theirs):
            continue
        listed = sub.kind == "list"
        mine = fixed.get(sub.key)
        if not _blank(mine) or (none_flag and not proposed):  # the expert's sub-value (C2, C3, C8)
            if none_flag and _blank(mine):
                conflicts.append(Offer(sub.key, theirs, "expert", None, False))
            elif listed and not covered(None, mine, theirs):
                conflicts.append(Offer(sub.key, theirs, "expert", holder_doc if not proposed else None, True))
            elif not listed and not same_single(mine, theirs):
                conflicts.append(Offer(sub.key, theirs, "expert", holder_doc if not proposed else None, False))
            continue
        now = current.get(sub.key)
        if _blank(now):
            if can_fill:
                value[sub.key] = theirs
                added = True
        elif listed:  # a document's list sub-value (C4, C6)
            if not covered(None, now, theirs):
                value[sub.key] = union(None, now, theirs)[: list_max(spec)]
                added = merged = True
        elif not same_single(now, theirs):  # a document's single sub-value (C5)
            conflicts.append(Offer(sub.key, theirs, "document", holder_doc, False))
    if not added:
        return Plan(refusal=None if conflicts else SAME_VALUE, conflicts=tuple(conflicts))
    if proposed:
        carried = dict(replaces) if replaces is not None else None
    else:
        carried = {"value": copy.deepcopy(stored), "meta": dict(meta) if meta else None}
    return Plan(value=value, replaces=carried, merged=merged, conflicts=tuple(conflicts))


# --- A source per item (P1–P5) ------------------------------------------------------------------


def _part(sub: str | None, item: str | None, source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sub": sub,
        "item": item,
        "source": source.get("source"),
        "documentId": source.get("documentId"),
        "quote": source.get("quote"),
        "fromImage": bool(source.get("fromImage")),
        "at": source.get("at"),
    }


def item_sources(spec: FieldSpec, value: Any, meta: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """One source per list item (P3): its part, else the field meta. Single sub-fields with a part are included."""
    meta = meta or {}
    parts = [p for p in (as_list(meta.get("parts")) or []) if as_mapping(p) is not None]

    def source_of(sub: str | None, item: str | None) -> dict[str, Any]:
        for part in parts:
            if part.get("sub") == sub and (
                (item is None and part.get("item") is None) or same_single(part.get("item"), item)
            ):
                return dict(part)
        return _part(sub, item, meta)

    out: list[dict[str, Any]] = []
    if spec.kind in ("list", "object_list"):
        out += [source_of(None, item_name(spec, i)) for i in as_list(value) or [] if not is_none_row(i)]
    elif spec.kind == "object":
        current = as_mapping(value) or {}
        for sub in spec.subfields:
            if sub.kind == "list":
                out += [source_of(sub.key, str(i)) for i in as_list(current.get(sub.key)) or []]
            elif parts and sub.kind != "bool" and not _blank(current.get(sub.key)):
                out.append(source_of(sub.key, None))
    return out


def with_parts(meta: dict[str, Any], parts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """`parts` only when the items have more than one source (P1)."""
    sources = {(p.get("source"), p.get("documentId")) for p in parts}
    if len(sources) > 1:
        meta["parts"] = [dict(p) for p in parts]
    else:
        meta.pop("parts", None)
    return meta


def merged_meta(
    spec: FieldSpec, value: Any, old_value: Any, old_meta: Mapping[str, Any] | None, new_meta: dict[str, Any]
) -> dict[str, Any]:
    """The meta of a value that merges stored items into a new writer's: parts per item (C4, P1–P3)."""
    before = item_sources(spec, old_value, old_meta)
    parts: list[dict[str, Any]] = []
    for source in item_sources(spec, value, None):
        known = next(
            (
                b
                for b in before
                if b["sub"] == source["sub"]
                and (b["item"] is None) == (source["item"] is None)
                and (b["item"] is None or same_single(b["item"], source["item"]))
            ),
            None,
        )
        parts.append(known if known is not None else _part(source["sub"], source["item"], new_meta))
    return with_parts(new_meta, parts)


# --- The sidecar --------------------------------------------------------------------------------


def _container(profile: dict[str, Any], address: Address, *, create: bool) -> dict[str, Any] | None:
    holder = profile if address.step is None else row_at(profile, address.step)
    if holder is None:
        return None
    container = as_dict(holder.get(CONFLICTS_KEY))
    if container is None and create:
        container = {}
        holder[CONFLICTS_KEY] = container
    return container


def conflict_key(address: Address, sub: str | None) -> str:
    """`<field key>` or `<field key>.<sub>`: `process.substeps[3].data.outputs` (spec 17 §3.21 item 1)."""
    return address.key if sub is None else f"{address.key}.{sub}"


def split_conflict_key(key: str) -> tuple[Address, str | None] | None:
    """The field address and sub-field of a conflict key, or `None`."""
    address = resolve_key(key)
    if address is not None:
        return address, None
    head, _, sub = key.rpartition(".")
    address = resolve_key(head) if head else None
    if address is None or not any(s.key == sub for s in address.spec.subfields):
        return None
    return address, sub


def store_conflict(
    profile: dict[str, Any], address: Address, offer: Offer, *, document_id: str, quote: str, from_image: bool, at: str
) -> str:
    """Record one conflict (CF3: replaces one on the same conflict key); returns the conflict key."""
    container = _container(profile, address, create=True)
    assert container is not None
    leaf = _leaf(address)
    records = [r for r in as_list(container.get(leaf)) or [] if (as_mapping(r) or {}).get("sub") != offer.sub]
    records.append(
        {
            "sub": offer.sub,
            "kind": offer.kind,
            "holderDocumentId": offer.holder_document_id,
            "value": copy.deepcopy(offer.value),
            "documentId": document_id,
            "quote": quote,
            "fromImage": from_image,
            "list": offer.list,
            "status": "open",
            "at": at,
        }
    )
    container[leaf] = records
    return conflict_key(address, offer.sub)


@dataclass(frozen=True)
class ConflictView:
    """One stored conflict as the interview and the panel read it; `current` is read live from the unit."""

    key: str
    sub: str | None
    conflict_key: str
    kind: str
    status: str
    list: bool
    offered: Any
    current: Any
    document_id: str
    holder_document_id: str | None
    from_image: bool
    quote: str


def _records(holder: Mapping[str, Any], leaf: str) -> list[Mapping[str, Any]]:
    container = as_mapping(holder.get(CONFLICTS_KEY)) or {}
    return [r for r in (as_mapping(x) for x in as_list(container.get(leaf)) or []) if r is not None]


def _view(profile: Mapping[str, Any], key: str, record: Mapping[str, Any]) -> ConflictView:
    sub = record.get("sub") if isinstance(record.get("sub"), str) else None
    value = stored_value(profile, key)
    current = (as_mapping(value) or {}).get(sub) if sub is not None else value
    address = resolve_key(key)
    return ConflictView(
        key=key,
        sub=sub,
        conflict_key=key if sub is None or address is None else conflict_key(address, sub),
        kind=str(record.get("kind") or "expert"),
        status=str(record.get("status") or "open"),
        list=record.get("list") is True,
        offered=record.get("value"),
        current=current,
        document_id=str(record.get("documentId") or ""),
        holder_document_id=record.get("holderDocumentId") if isinstance(record.get("holderDocumentId"), str) else None,
        from_image=record.get("fromImage") is True,
        quote=str(record.get("quote") or ""),
    )


def open_conflicts(profile: Mapping[str, Any], *, status: str | None = None) -> list[ConflictView]:
    """Every stored conflict (or those with `status`), in ask order: process fields, then step 1 S01…S12, step 2, …"""
    p = normalized_profile(profile)
    out: list[ConflictView] = []
    for spec in PROFILE_SPECS:
        out += [_view(p, spec.key, r) for r in _records(p, spec.key)]
    for index, row in enumerate(rows_of(p), start=1):
        for spec in STEP_SPECS:
            out += [_view(p, step_cell_key(index, spec.key), r) for r in _records(row, spec.key)]
    return [c for c in out if status is None or c.status == status]


def conflicted_fields(profile: Mapping[str, Any]) -> set[str]:
    """Field keys with an open conflict: left out of proposal groups (spec 14 §3.17 Q3)."""
    return {c.key for c in open_conflicts(profile, status="open")}


def _edit_records(profile: dict[str, Any], keys: Sequence[str], change: Mapping[str, Any] | None) -> list[str]:
    """Remove (`change=None`) or update the records of the given conflict keys (a field key: all of its records)."""
    done: list[str] = []
    for key in keys:
        split = split_conflict_key(key)
        if split is None:
            continue
        address, sub = split
        whole = resolve_key(key) is not None
        container = _container(profile, address, create=False)
        if container is None:
            continue
        leaf = _leaf(address)
        kept: list[Any] = []
        for record in as_list(container.get(leaf)) or []:
            hit = whole or (as_mapping(record) or {}).get("sub") == sub
            if hit:
                done.append(conflict_key(address, (as_mapping(record) or {}).get("sub")))
                if change is not None:
                    kept.append({**dict(as_mapping(record) or {}), **change})
            else:
                kept.append(record)
        if kept:
            container[leaf] = kept
        else:
            container.pop(leaf, None)
    return done


def close_conflicts(profile: Mapping[str, Any], keys: Sequence[str]) -> tuple[dict[str, Any], list[str]]:
    """Remove the conflicts of the given field or conflict keys; returns the profile and the closed conflict keys."""
    result = normalized_profile(profile)
    return result, _edit_records(result, keys, None)


def mark_conflicts_left(profile: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    """`status: left` (asked to the limit): the value is untouched, never asked again (spec 14 §3.17 item 5)."""
    result = normalized_profile(profile)
    _edit_records(result, keys, {"status": "left"})
    return result


# --- What a choice writes (spec 13 §3.13 item 2) ------------------------------------------------


def _doc_source(record: ConflictView, at: str) -> dict[str, Any]:
    return {
        "source": SOURCE_DOCUMENT,
        "documentId": record.document_id,
        "quote": record.quote,
        "fromImage": record.from_image,
        "at": at,
    }


def _resolve_one(profile: dict[str, Any], view: ConflictView, choice: Choice, at: str) -> str | None:
    address = resolve_key(view.key)
    if address is None:
        return None
    spec = address.spec
    meta = dict(meta_for(profile, address.key) or {})
    proposed = is_proposed(meta)
    stored = copy.deepcopy(stored_value(profile, address.key))
    if choice == "both" and not (view.kind == "expert" and view.list):
        choice = "current"
    if choice == "current":
        if proposed and view.sub is None:
            meta.update(status="confirmed", at=at)
            meta.pop("replaces", None)
            set_meta(profile, address, meta)
            return address.key
        return None
    if view.sub is None and choice == "offered":
        write_value(profile, address, copy.deepcopy(view.offered))
        new_meta = {**_doc_source(view, at), "status": "confirmed", "by": None}
        set_meta(profile, address, new_meta)
        return address.key
    if view.sub is None:  # both, whole list-like unit: one part per item
        value = union(spec, stored, view.offered)[: list_max(spec)]
        before = item_sources(spec, stored, meta)
        parts = [
            next((b for b in before if same_single(b["item"], item_name(spec, i))), None)
            or _part(None, item_name(spec, i), _doc_source(view, at))
            for i in value
        ]
        new_meta = {**meta, "status": "confirmed", "at": at}
        new_meta.pop("replaces", None)
        write_value(profile, address, value)
        set_meta(profile, address, with_parts(new_meta, parts))
        return address.key
    current = dict(as_mapping(stored) or {})
    if choice == "offered":
        current[view.sub] = copy.deepcopy(view.offered)
    else:
        current[view.sub] = union(None, current.get(view.sub), view.offered)[: list_max(spec)]
    write_value(profile, address, current)
    parts = [p for p in as_list(meta.get("parts")) or [] if (as_mapping(p) or {}).get("sub") != view.sub]
    if choice == "offered" and not is_list_like(spec, view.sub):
        parts.append(_part(view.sub, None, _doc_source(view, at)))
    else:
        old_items: Any = (as_mapping(stored) or {}).get(view.sub) if choice == "both" else []
        for item in as_list(current.get(view.sub)) or []:
            mine = any(same_single(item, o) for o in as_list(old_items) or [])
            parts.append(_part(view.sub, str(item), meta if mine else _doc_source(view, at)))
    new_meta = dict(meta)
    if not proposed:
        new_meta.update(status="confirmed", at=at)
    if proposed and as_mapping(meta.get("replaces")) is not None:
        replaces = copy.deepcopy(dict(as_mapping(meta.get("replaces")) or {}))
        value_before = dict(as_mapping(replaces.get("value")) or {})
        value_before[view.sub] = copy.deepcopy(current[view.sub])
        replaces["value"] = value_before
        new_meta["replaces"] = replaces
    new_meta.pop("parts", None)
    set_meta(profile, address, {**new_meta, **({"parts": parts} if parts else {})})
    return address.key


def resolve_conflicts(
    profile: Mapping[str, Any], conflict_keys: Sequence[str], choice: Choice, *, vocab: Vocabulary, at: str
) -> ChangeResult:
    """Write the expert's choice for each conflict key (current, offered, both), then close the conflicts."""
    result = normalized_profile(profile)
    was_closed = process_of(result).get("substeps_complete") is True
    wanted = set(conflict_keys)
    views = [v for v in open_conflicts(result) if v.conflict_key in wanted]
    written: list[str] = []
    leaves: set[str] = set()
    for view in views:
        landed = _resolve_one(result, view, choice, at)
        if landed is not None and landed not in written:
            written.append(landed)
            address = resolve_key(landed)
            if address is not None and address.step is not None:
                leaves.add(address.spec.key)
    _edit_records(result, [v.conflict_key for v in views], None)
    finish_batch(result, vocab=vocab, was_closed=was_closed, steps_landed=bool(leaves), leaves=leaves)
    return ChangeResult(result, written, [], grade_written(result, written, vocab=vocab), bool(leaves))
