"""Profile vocabulary: flags, roll-up targets, proposal bounds and refusal reasons (spec 13 §4).

Why: the writers, the scoring and the interview all name the same flags and the same refusal
reasons, and a reason spelled two ways is a log nobody can count. Every name is declared once
here; anything that can be derived from the field registry (`domain.field_spec`) is derived there
and only re-exported, never restated.
What: the three confirmation flags and the parked step count, the roll-up targets and their keys,
the bounds for numbers read from documents, and the `Refusal` reasons a write can be refused with.
Must not: compute, write a profile, or import anything but the registry.
Spec 13 §4; used by AC-13.12 to AC-13.38.
"""

from __future__ import annotations

from typing import Literal

from ..domain.field_spec import (
    META_KEY,
    REJECTED_COUNT_KEY,
    SKIPPED_KEY,
)

FLAG_SUBSTEPS_COMPLETE = "substeps_complete"
FLAG_ROLES_CONFIRMED = "roles_confirmed"
FLAG_TOOLS_CONFIRMED = "tools_confirmed"
FLAG_SUBSTEP_COUNT_REJECTED = REJECTED_COUNT_KEY
#: The three flags a person (or the close test) raises; never scored, never written by a model.
CONFIRMATION_FLAGS: tuple[str, ...] = (FLAG_SUBSTEPS_COMPLETE, FLAG_ROLES_CONFIRMED, FLAG_TOOLS_CONFIRMED)

#: `LastQuestion.confirm` values for the two lists (spec 12), in ask order: roles before systems.
ROLLUP_TARGETS: tuple[str, ...] = ("roles", "systems")
ROLLUP_KEYS: dict[str, str] = {"roles": "process.all_roles", "systems": "process.all_tools"}
ROLLUP_FLAGS: dict[str, str] = {"roles": FLAG_ROLES_CONFIRMED, "systems": FLAG_TOOLS_CONFIRMED}
#: The step leaf that feeds each roll-up: a write to it resets that list's confirmation.
ROLLUP_SOURCE_LEAF: dict[str, str] = {"roles": "roles", "systems": "systems"}

#: A number read from a document outside these bounds is a parse artefact, not a fact.
NUMBER_BOUNDS_PROPOSAL: tuple[int, int] = (0, 1_000_000)

#: The none-able leaves a step-cell limit settles with the none row (spec 14 §3.5).
NONE_ROW_LEAVES: tuple[str, ...] = ("roles", "approvals", "exceptions")

Refusal = Literal[
    "unknown_key",
    "not_writable",
    "specialist_owned",
    "index_out_of_range",
    "shape",
    "not_proposable",
    "no_quote",
    "confirmed",
    "table_not_empty",
    "out_of_bounds",
]
UNKNOWN_KEY: Refusal = "unknown_key"
NOT_WRITABLE: Refusal = "not_writable"
SPECIALIST_OWNED: Refusal = "specialist_owned"
INDEX_OUT_OF_RANGE: Refusal = "index_out_of_range"
SHAPE: Refusal = "shape"
NOT_PROPOSABLE: Refusal = "not_proposable"
NO_QUOTE: Refusal = "no_quote"
CONFIRMED: Refusal = "confirmed"
TABLE_NOT_EMPTY: Refusal = "table_not_empty"
OUT_OF_BOUNDS: Refusal = "out_of_bounds"

__all__ = [
    "CONFIRMATION_FLAGS",
    "FLAG_ROLES_CONFIRMED",
    "FLAG_SUBSTEPS_COMPLETE",
    "FLAG_SUBSTEP_COUNT_REJECTED",
    "FLAG_TOOLS_CONFIRMED",
    "META_KEY",
    "NONE_ROW_LEAVES",
    "NUMBER_BOUNDS_PROPOSAL",
    "ROLLUP_FLAGS",
    "ROLLUP_KEYS",
    "ROLLUP_SOURCE_LEAF",
    "ROLLUP_TARGETS",
    "Refusal",
    "SKIPPED_KEY",
]
