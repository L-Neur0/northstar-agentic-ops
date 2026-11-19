"""The frozen `raw_substeps` snapshot: what the expert said, before any machine or specialist wrote (spec 13 §3.12).

Why: the step table is the one living table: the expert's answers, then document proposals and
specialist edits layered on top. The snapshot is the before-picture, a copy taken at the last
instant the table held only the expert's own words, so the report can always say what the expert
said. "Last instant" is enforced here, not remembered at each call site.
What: `freeze_raw_substeps(raw, profile)` returns `raw` unchanged when it is non-empty (frozen once,
forever) and otherwise a deep copy of the current table (possibly `[]`, which a later call retakes).
Every non-expert writer (documents, spec 17; specialist edits, spec 21) calls it immediately before
writing. Must not: be called by the interview, mutate its inputs, or contain a word the expert did
not say. Spec 13 §3.12; AC-13.51.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .shapes import rows_of


def freeze_raw_substeps(raw: Sequence[Mapping[str, Any]], profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The session's `raw_substeps`: unchanged when already taken, else a copy of the table now."""
    if raw:
        return [dict(copy.deepcopy(dict(r))) for r in raw]
    return copy.deepcopy(rows_of(profile))
