"""Turn whatever a model, a document or a stored session handed over into a storable value (spec 13 §3.2–§3.3).

Why: a bad change must never corrupt or wipe the profile. Every function here is a filter in front
of a write: it returns a clean value of the declared kind, or `None`, which the caller reads as
"this change adds nothing; leave the field alone". Keeping the filters apart from the writer means
the expert path (`mutate`), the document path (`proposals`) and the specialist path share one
definition of "a usable number" or "a usable row".
What: scalar coercions (`coerce_text`, `coerce_number`, `coerce_bool`, `coerce_count`), the list,
object and row filters, and the two merges the expert path uses (`merged_list` accumulates with
case-insensitive de-duplication; `merged_object` merges sub-field by sub-field with the P11
none-flag rules; `merged_rows` merges rows on their required sub-field, the none row landing only
on an empty cell). Field-specific normalisation (region spelling, P14 lower case) is `normalise`.
Must not: touch a profile, log a value, or invent a value the input did not carry.
Spec 13 §3.2–§3.3, AC-13.3 to AC-13.11.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from ..domain.field_spec import (
    MAX_STEPS,
    NONE_FLAG,
    NONE_KEY,
    FieldSpec,
    Vocabulary,
    is_none_row,
    lenient_object_rows,
    required_subfield,
)
from .shapes import as_list, as_mapping, empty_for_sub_kind


def coerce_count(value: Any) -> int:
    """A stored counter: a non-negative int, else 0 (never `None`)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def coerce_text(value: Any) -> str | None:
    """Non-blank text (trimmed); an int or float becomes its string; anything else `None`."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return None


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except (ValueError, OverflowError):
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def coerce_number(value: Any) -> int | None:
    """A non-negative whole number. Bools, `inf`, `nan`, `1e400`, text and negatives are `None`."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value >= 0 else None
    number = _finite_float(value)
    if number is None or number < 0:
        return None
    return int(number)


def raw_number(value: Any) -> float | None:
    """The number a value spells, sign kept, for bounds checks before coercion; `None` if not one."""
    return _finite_float(value)


def coerce_bool(value: Any) -> bool | None:
    """A bool, or one of `true/yes/y/1`, `false/no/n/0` in any case; anything else `None`."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().casefold()
        if text in ("true", "yes", "y", "1"):
            return True
        if text in ("false", "no", "n", "0"):
            return False
    return None


def _coerce_sub(kind: str, raw: Any) -> Any:
    if kind == "text":
        return coerce_text(raw)
    if kind == "number":
        return coerce_number(raw)
    if kind == "bool":
        return coerce_bool(raw)
    if kind == "list":
        return merged_list([], raw)
    return None


def merged_list(existing: Any, value: Any) -> list[str] | None:
    """Accumulate string items: case-insensitive de-duplication, the first spelling wins.

    A string is one item. `None` when nothing new arrives, so the caller leaves the field alone.
    """
    items = as_list(value)
    if items is None:
        if isinstance(value, str) and value.strip():
            items = [value]
        else:
            return None
    out = [v for v in (as_list(existing) or []) if isinstance(v, str)]
    seen = {v.casefold() for v in out}
    added = False
    for item in items:
        text = coerce_text(item)
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        out.append(text)
        added = True
    return out if added else None


def filtered_object(spec: FieldSpec, value: Any) -> dict[str, Any]:
    """The declared sub-fields of an object change, each coerced by its sub-kind; `{}` when none survive."""
    source = as_mapping(value)
    if source is None:
        return {}
    patch: dict[str, Any] = {}
    for sub in spec.subfields:
        if sub.key not in source:
            continue
        coerced = _coerce_sub(sub.kind, source[sub.key])
        if coerced is not None:
            patch[sub.key] = coerced
    return patch


def _is_empty(value: Any) -> bool:
    return value is None or value is False or value == "" or value == [] or value == {}


def merged_object(existing: Any, patch: Mapping[str, Any]) -> dict[str, Any]:
    """Merge an object change into the stored object, sub-field by sub-field (a later one overwrites).

    P11's none flag follows the none-row rule: a real `role` clears it (also in the same change), a
    flag-only change on an empty owner sets it, and a flag-only change on a stored role is ignored
    ("none" never erases). A blank role never reaches here (it does not coerce).
    """
    slot: dict[str, Any] = dict(as_mapping(existing) or {})
    answered = any(k != NONE_FLAG and not _is_empty(v) for k, v in patch.items())
    if not answered and patch.get(NONE_FLAG) is True:
        has_answer = any(k != NONE_FLAG and not _is_empty(v) for k, v in slot.items())
        if has_answer:
            return slot
    slot.update(patch)
    if answered and slot.get(NONE_FLAG) is True:
        slot[NONE_FLAG] = False
    return slot


def filtered_rows(
    spec: FieldSpec, value: Any, *, own_step: int | None = None, step_count: int | None = None
) -> list[dict[str, Any]] | None:
    """Clean rows of an `object_list` change, or `None` when no usable row is left.

    Lenient input (spec 12 §3.7); declared sub-fields only; a row without its required sub-field is
    dropped and a malformed entry skipped; optional sub-fields are written with their defaults. An
    exception's `loops_back_to` outside `1..step_count` (default `MAX_STEPS`) or equal to its own
    step is set to `None`; the description is kept.
    """
    candidates = lenient_object_rows(spec, value)
    if candidates is None:
        return None
    required = required_subfield(spec)
    upper = step_count or MAX_STEPS
    rows: list[dict[str, Any]] = []
    for entry in candidates:
        if is_none_row(entry):
            rows.append({NONE_KEY: True})
            continue
        if as_mapping(entry) is None:
            continue
        row = filtered_object(spec, entry)
        if required and not row.get(required):
            continue
        target = row.get("loops_back_to")
        if isinstance(target, int) and (not 1 <= target <= upper or (own_step is not None and target == own_step)):
            row.pop("loops_back_to")
        for sub in spec.subfields:
            row.setdefault(sub.key, empty_for_sub_kind(sub.kind))
        rows.append(row)
    return rows or None


def merged_rows(spec: FieldSpec, existing: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Merge clean rows into what the cell holds, keyed on the required sub-field (case-insensitive).

    A new row is appended; a row matching a stored one fills only that row's empty sub-fields; the
    none row lands only on an empty cell and never erases rows; a real row replaces a stored none
    row. `None` when nothing changes, so the write does not count as an edit.
    """
    key = required_subfield(spec)
    stored = [dict(m) for m in (as_mapping(r) for r in (as_list(existing) or [])) if m is not None]
    kept = [r for r in stored if not is_none_row(r)]
    incoming = [r for r in rows if not is_none_row(r)]
    if not incoming:
        return None if stored else [{NONE_KEY: True}]

    def marker(row: Mapping[str, Any]) -> str | None:
        value = row.get(key) if key else None
        return value.casefold() if isinstance(value, str) and value else None

    index: dict[str, dict[str, Any]] = {}
    for row in kept:
        m = marker(row)
        if m and m not in index:
            index[m] = row
    changed = len(kept) != len(stored)
    for row in incoming:
        m = marker(row)
        hit = index.get(m) if m else None
        if hit is None:
            fresh = dict(row)
            kept.append(fresh)
            if m:
                index[m] = fresh
            changed = True
            continue
        for sub_key, sub_value in row.items():
            if _is_empty(hit.get(sub_key)) and not _is_empty(sub_value):
                hit[sub_key] = sub_value
                changed = True
    return kept if changed else None


def normalise(spec: FieldSpec, value: Any, vocab: Vocabulary) -> Any:
    """Field-specific spelling on write: P03 region canonical (or as typed), P14 `same` lower-cased."""
    if spec.id == "P03" and isinstance(value, str):
        return vocab.region(value) or value
    if spec.id == "P14":
        source = as_mapping(value)
        if source is not None and isinstance(source.get("same"), str):
            return {**source, "same": str(source["same"]).strip().casefold()}
    return value
