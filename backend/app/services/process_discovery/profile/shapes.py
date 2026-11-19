"""The profile's JSON skeleton and the seeding and reading primitives over it (spec 13 §3.1).

Why: every writer and reader in the engine works on the plain-dict form of the profile
(`Profile().model_dump(by_alias=True)`, spec 12 §3.11). If any of them had to ask "does this key
exist?", one of them would eventually forget, so the full shape is always present: an empty
profile is the whole skeleton, and a stored one is seeded back into shape before anything reads it.
What: `empty_profile`, `empty_step`, `normalized_profile` (deep-copy then seed, never rebuild, so
nothing present is lost), the address readers `value_for` / `stored_value` / `parse_step_key` /
`resolve_key`, and small typed helpers (`as_mapping`, `as_list`, `process_of`, `rows_of`,
`meta_for`) the other modules share.
Must not: grade, score or write a field; read a clock; mutate an input.
Spec 13 §3.1, AC-13.1, AC-13.2.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any, NamedTuple, cast

from ..domain.field_spec import (
    DERIVED_SPECS,
    META_KEY,
    PROFILE_SPECS,
    SKIPPED_KEY,
    STEP_SPECS,
    FieldSpec,
    resolve_address,
    step_cell_key,
)
from .constants import CONFIRMATION_FLAGS, FLAG_SUBSTEP_COUNT_REJECTED

_STEP_KEY = re.compile(r"^process\.substeps\[(\d+)\]\.([A-Za-z_][A-Za-z0-9_]*)$")


# --- Typed helpers ------------------------------------------------------------------------------


def as_mapping(value: object) -> Mapping[str, Any] | None:
    """`value` as a read-only mapping, or `None` when it is not one."""
    return cast("Mapping[str, Any]", value) if isinstance(value, Mapping) else None


def as_dict(value: object) -> dict[str, Any] | None:
    """`value` as a mutable dict, or `None` when it is not one."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def as_list(value: object) -> list[Any] | None:
    """`value` as a list, or `None` when it is not one."""
    return cast("list[Any]", value) if isinstance(value, list) else None


def as_text(value: object) -> str:
    """Trimmed text, or "" for anything that is not a string."""
    return value.strip() if isinstance(value, str) else ""


# --- Empty values -------------------------------------------------------------------------------


def empty_for_sub_kind(kind: str) -> Any:
    """The empty value of one sub-field kind (`text`, `list`, `number`, `bool`)."""
    if kind == "list":
        return []
    if kind == "number":
        return None
    if kind == "bool":
        return False
    return ""


def empty_value(spec: FieldSpec) -> Any:
    """The empty value of one field: what "cleared" means for it."""
    if spec.kind in ("list", "object_list"):
        return []
    if spec.kind == "number":
        return None
    if spec.kind == "object":
        return {sub.key: empty_for_sub_kind(sub.kind) for sub in spec.subfields}
    return ""


def empty_step() -> dict[str, Any]:
    """One empty step: every leaf at its empty value, `__meta: {}`, `__skipped: []`."""
    row: dict[str, Any] = {spec.key: empty_value(spec) for spec in STEP_SPECS}
    row[META_KEY] = {}
    row[SKIPPED_KEY] = []
    return row


def _empty_process() -> dict[str, Any]:
    proc: dict[str, Any] = {spec.leaf: empty_value(spec) for spec in PROFILE_SPECS if spec.is_process}
    proc[FLAG_SUBSTEP_COUNT_REJECTED] = None
    proc["substeps"] = []
    for derived in DERIVED_SPECS:
        proc[derived.key.split(".", 1)[1]] = []
    for flag in CONFIRMATION_FLAGS:
        proc[flag] = False
    return proc


def empty_profile() -> dict[str, Any]:
    """The JSON skeleton of an empty profile (spec 12 §3.11)."""
    profile: dict[str, Any] = {spec.key: empty_value(spec) for spec in PROFILE_SPECS if not spec.is_process}
    profile["process"] = _empty_process()
    profile[META_KEY] = {}
    return profile


# --- Seeding ------------------------------------------------------------------------------------


def _seed_object(container: dict[str, Any], spec: FieldSpec) -> None:
    slot = as_dict(container.get(spec.leaf))
    if slot is None:
        container[spec.leaf] = empty_value(spec)
        return
    for sub in spec.subfields:
        slot.setdefault(sub.key, empty_for_sub_kind(sub.kind))


def _normalized_step(row: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(copy.deepcopy(dict(row)))
    for spec in STEP_SPECS:
        if spec.key not in out:
            out[spec.key] = empty_value(spec)
        elif spec.kind == "object":
            _seed_object(out, spec)
    if as_dict(out.get(META_KEY)) is None:
        out[META_KEY] = {}
    if as_list(out.get(SKIPPED_KEY)) is None:
        out[SKIPPED_KEY] = []
    return out


def normalized_profile(profile: Mapping[str, Any] | None) -> dict[str, Any]:
    """A deep copy of `profile` with every missing key seeded; `None` gives `empty_profile()`.

    Deep-copy then seed, never rebuild from the registry: whatever is present survives. A `process`
    that is not a dict, or a `substeps` that is not a list, is replaced by its empty value.
    """
    if profile is None:
        return empty_profile()
    result: dict[str, Any] = copy.deepcopy(dict(profile))
    for spec in PROFILE_SPECS:
        if not spec.is_process:
            result.setdefault(spec.key, empty_value(spec))
    proc = as_dict(result.get("process"))
    if proc is None:
        result["process"] = _empty_process()
    else:
        for key, value in _empty_process().items():
            proc.setdefault(key, value)
        for spec in PROFILE_SPECS:
            if spec.is_process and spec.kind == "object":
                _seed_object(proc, spec)
        rows = as_list(proc.get("substeps"))
        proc["substeps"] = [_normalized_step(r) for r in (rows or []) if as_mapping(r) is not None]
        for flag in CONFIRMATION_FLAGS:
            proc[flag] = proc.get(flag) is True
    if as_dict(result.get(META_KEY)) is None:
        result[META_KEY] = {}
    return result


# --- Reading ------------------------------------------------------------------------------------


def process_of(profile: Mapping[str, Any]) -> dict[str, Any]:
    """The `process` object (a live reference on a normalised profile, `{}` otherwise)."""
    return as_dict(profile.get("process")) or {}


def rows_of(profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The step rows (live references on a normalised profile); non-dict rows are left out."""
    rows = as_list(process_of(profile).get("substeps")) or []
    return [r for r in (as_dict(x) for x in rows) if r is not None]


def parse_step_key(key: str) -> tuple[int, str] | None:
    """`"process.substeps[3].roles"` → `(3, "roles")`. The index stays 1-based (0 is returned as 0)."""
    match = _STEP_KEY.match(key)
    if not match:
        return None
    return int(match.group(1)), match.group(2)


class Address(NamedTuple):
    """A resolved key: the field, the 1-based step index (`None` for process fields), the canonical key."""

    spec: FieldSpec
    step: int | None
    key: str


def resolve_key(key: str) -> Address | None:
    """Any address form (dotted, 1-based step cell, bare process leaf) → its canonical `Address`."""
    resolved = resolve_address(key)
    if resolved is None:
        return None
    spec, index = resolved
    canonical = spec.key if index is None else step_cell_key(index, spec.key)
    return Address(spec, index, canonical)


def value_for(profile: Mapping[str, Any], key: str) -> Any:
    """A process or top-level field by registry key (`department`, `process.volume`)."""
    if key.startswith("process."):
        return process_of(profile).get(key.split(".", 1)[1])
    return profile.get(key)


def row_at(profile: Mapping[str, Any], index: int) -> dict[str, Any] | None:
    """The step row at a 1-based index, or `None` when it does not exist."""
    rows = rows_of(profile)
    return rows[index - 1] if 1 <= index <= len(rows) else None


def stored_value(profile: Mapping[str, Any], key: str) -> Any:
    """Whatever is stored at `key`, in any address form. A step that does not exist reads `None`."""
    address = resolve_key(key)
    if address is None:
        return None
    if address.step is None:
        return value_for(profile, address.spec.key)
    row = row_at(profile, address.step)
    return row.get(address.spec.key) if row is not None else None


def meta_for(profile: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    """The `__meta` entry of a field or step cell, or `None` when it has none."""
    address = resolve_key(key)
    if address is None:
        return None
    if address.step is None:
        container = as_mapping(profile.get(META_KEY)) or {}
        return as_mapping(container.get(address.spec.key))
    row = row_at(profile, address.step)
    if row is None:
        return None
    return as_mapping((as_mapping(row.get(META_KEY)) or {}).get(address.spec.key))
