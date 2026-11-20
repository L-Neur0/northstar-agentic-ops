"""Fingerprints of what each assessment call reads, so a call runs again only when its input changed (spec 18 §3.10).

Why: the assessment is re-run after *Finish* and after specialist edits (specs 20, 21). Re-running a
model call whose input did not change costs money and replaces reviewed results for nothing, while
skipping one whose input did change leaves the report out of date. A hash of exactly the fields a call
reads answers "did it change?" without comparing whole profiles.
What: `ai_input_fingerprint` hashes what OPPORTUNITIES, LABEL and ASSESS_STEPS read (P04, P06–P15,
the step count and every step's S01–S12); `map_fingerprint` hashes what the map is drawn from (step
names, owners, roles, systems, inputs, outputs, approver roles, exceptions; trigger, end result, owner
role). Both are SHA-256 over canonical JSON of a seeded copy, so absent and empty values hash the same.
Must not: hash `__meta`, `__skipped`, flags, roll-ups or P01–P03 and P05 (confirming a proposal or
moving a cluster must not trigger a re-run), mutate the profile, or do I/O.
Spec 18 §3.10, §4.1; AC-18.18.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from ..domain.field_spec import STEP_SPECS
from ..profile.shapes import as_list, as_mapping, normalized_profile, process_of, rows_of

_AI_PROCESS_LEAVES = (
    "name",
    "trigger",
    "end_result",
    "value_at_end",
    "business_pain",
    "volume",
    "process_owner",
    "baseline_metric",
    "target_metric",
    "variation",
    "sensitive_data",
    "substep_count",
)


def _hash(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ai_input_fingerprint(profile: Mapping[str, Any]) -> str:
    """Changes when anything OPPORTUNITIES, LABEL or ASSESS_STEPS reads changes; not with meta or flags."""
    p = normalized_profile(profile)
    proc = process_of(p)
    payload = {
        "process": {leaf: proc.get(leaf) for leaf in _AI_PROCESS_LEAVES},
        "steps": [{spec.key: row.get(spec.key) for spec in STEP_SPECS} for row in rows_of(p)],
    }
    return _hash(payload)


def _row_values(rows: Any, key: str) -> list[Any]:
    return [m.get(key) for m in (as_mapping(r) for r in as_list(rows) or []) if m is not None and key in m]


def map_fingerprint(profile: Mapping[str, Any]) -> str:
    """Changes when anything the process map is drawn from changes; not with a pain point or an effort."""
    p = normalized_profile(profile)
    proc = process_of(p)
    owner = as_mapping(proc.get("process_owner")) or {}
    steps = []
    for row in rows_of(p):
        data = as_mapping(row.get("data")) or {}
        exceptions = row.get("exceptions")
        steps.append(
            {
                "name": row.get("name"),
                "owner": row.get("owner"),
                "roles": _row_values(row.get("roles"), "role"),
                "systems": row.get("systems"),
                "inputs": data.get("inputs"),
                "outputs": data.get("outputs"),
                "approvers": _row_values(row.get("approvals"), "approver_role"),
                "exceptions": _row_values(exceptions, "description"),
                "loops": _row_values(exceptions, "loops_back_to"),
            }
        )
    payload = {
        "trigger": proc.get("trigger"),
        "end_result": proc.get("end_result"),
        "owner_role": owner.get("role"),
        "steps": steps,
    }
    return _hash(payload)
