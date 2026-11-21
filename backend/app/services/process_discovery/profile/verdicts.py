"""Is this field answered, and does it count? One definition, and every view onto it (spec 13 §3.5, §3.9).

Why: the score, the step walk, the *Finish* check, the interview's phases and the screens all ask
the same two questions ("is it answered?", "does it count?"). The first is the registry's
`evaluate_field` (spec 12); the second adds provenance: a proposed value never counts. Asking them
anywhere else is how a stored value ends up counted in one place and missing in another.
What: `grade` (any address form), `field_counts`, `answer_started`, the row helpers (`cell_counts`,
`cell_skipped`, `cell_settled`, `step_is_started`, `step_is_complete`, `last_started_row`) and the step-table
numbers (`declared_step_count`, `expected_steps`, `current_step_index`).
Short step walk (approved 2026-11-20): `cell_settled` lets a Tier C proposal settle a cell for
the walk (spec 14 §3.19 W7). Must not: write anything. A row that holds only proposals is *started* (it is never trimmed) but
never *complete*. Spec 13 §3.5, §3.9; AC-13.32, AC-13.46.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..domain.field_spec import (
    COMPLETE,
    GROUP_C,
    MAX_STEPS,
    META_KEY,
    SKIPPED_KEY,
    SOURCE_AGENT,
    STEP_SPECS,
    Verdict,
    Vocabulary,
    counts,
    evaluate_field,
    has_any_answer,
    is_proposed,
    step_spec_by_leaf,
)
from .shapes import as_list, as_mapping, meta_for, process_of, resolve_key, rows_of, stored_value

P16_KEY = "process.substep_count"


def grade(profile: Mapping[str, Any], key: str, *, vocab: Vocabulary) -> Verdict:
    """The Verdict of one field or step cell, in any address form. Unknown keys grade complete.

    Unknown keys (flags, roll-ups) are not interview answers; grading them would only make noise.
    """
    address = resolve_key(key)
    if address is None:
        return COMPLETE
    return evaluate_field(address.spec, stored_value(profile, key), profile, vocab)


def field_counts(profile: Mapping[str, Any], key: str, *, vocab: Vocabulary) -> bool:
    """Complete and not a proposal: what the score, the phases and *Finish* count."""
    return counts(grade(profile, key, vocab=vocab), meta_for(profile, key))


def answer_started(profile: Mapping[str, Any], key: str) -> bool:
    """Whether anything at all has been put into the field, counted or not."""
    address = resolve_key(key)
    return address is not None and has_any_answer(address.spec, stored_value(profile, key))


def _cell_meta(row: Mapping[str, Any], leaf: str) -> Mapping[str, Any] | None:
    return as_mapping((as_mapping(row.get(META_KEY)) or {}).get(leaf))


def cell_verdict(row: Mapping[str, Any], leaf: str, *, vocab: Vocabulary) -> Verdict:
    """The Verdict of one cell of one row."""
    spec = step_spec_by_leaf(leaf)
    if spec is None:
        return COMPLETE
    return evaluate_field(spec, row.get(leaf), {}, vocab)


def cell_counts(row: Mapping[str, Any], leaf: str, *, vocab: Vocabulary) -> bool:
    """Complete and not proposed."""
    return counts(cell_verdict(row, leaf, vocab=vocab), _cell_meta(row, leaf))


def cell_proposed(row: Mapping[str, Any], leaf: str) -> bool:
    """The cell holds an answer whose meta says `proposed`."""
    spec = step_spec_by_leaf(leaf)
    meta = _cell_meta(row, leaf)
    return spec is not None and is_proposed(meta) and has_any_answer(spec, row.get(leaf))


def cell_skipped(row: Mapping[str, Any], leaf: str) -> bool:
    """The interview stopped asking for this cell: settled for the walk, missing for the score."""
    return leaf in (as_list(row.get(SKIPPED_KEY)) or [])


def step_is_started(row: Mapping[str, Any], *, vocab: Vocabulary) -> bool:
    """Any cell holds an answer that grades complete, proposed or not."""
    return any(cell_verdict(row, spec.key, vocab=vocab).is_complete for spec in STEP_SPECS)


def cell_settled(row: Mapping[str, Any], leaf: str, *, vocab: Vocabulary) -> bool:
    """The walk is done with this cell: it counts, is skipped, or is a Tier C cell holding an agent proposal.

    Short step walk (spec 14 §3.19 W7): Tier C (goal, owner, hand-over) is proposed by code and
    confirmed in bulk in the review, so a waiting proposal never holds the walk; it still adds 0 points.
    """
    if cell_counts(row, leaf, vocab=vocab) or cell_skipped(row, leaf):
        return True
    spec = step_spec_by_leaf(leaf)
    meta = _cell_meta(row, leaf) or {}
    return (
        spec is not None and spec.group == GROUP_C and cell_proposed(row, leaf) and meta.get("source") == SOURCE_AGENT
    )


def step_is_complete(row: Mapping[str, Any], *, vocab: Vocabulary) -> bool:
    """Every scored cell is settled (counts, skipped, or a Tier C proposal). S12 (weight 0) never blocks."""
    return all(cell_settled(row, spec.key, vocab=vocab) for spec in STEP_SPECS if spec.weight > 0)


def last_started_row(rows: Any, *, vocab: Vocabulary) -> int:
    """The 1-based **position** of the last started row, 0 if none (a position, not a count)."""
    items = as_list(rows) or []
    for i in range(len(items), 0, -1):
        row = as_mapping(items[i - 1])
        if row is not None and step_is_started(row, vocab=vocab):
            return i
    return 0


def declared_step_count(profile: Mapping[str, Any], *, vocab: Vocabulary) -> int:
    """P16 when it grades complete, else 0."""
    if not grade(profile, P16_KEY, vocab=vocab).is_complete:
        return 0
    value = process_of(profile).get("substep_count")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def expected_steps(profile: Mapping[str, Any], *, vocab: Vocabulary) -> int:
    """0 while P16 is not complete; else `min(MAX_STEPS, max(declared, last started))`."""
    declared = declared_step_count(profile, vocab=vocab)
    if not declared:
        return 0
    started = last_started_row(process_of(profile).get("substeps"), vocab=vocab)
    return min(MAX_STEPS, max(declared, started))


def current_step_index(profile: Mapping[str, Any], *, vocab: Vocabulary) -> int | None:
    """The 1-based index of the first incomplete row, or `None` when every row is complete."""
    for i, row in enumerate(rows_of(profile), start=1):
        if not step_is_complete(row, vocab=vocab):
            return i
    return None


VOLUME_KEY = "process.volume"
#: The step frequency assumed when the process volume is known (spec 14 §3.21 P3).
ASSUMED_FREQUENCY = "each time"


def volume_words(profile: Mapping[str, Any], *, vocab: Vocabulary) -> str | None:
    """P10 in plain words ("6 a month") when it counts, else `None` (spec 14 §3.21 P3)."""
    if not field_counts(profile, VOLUME_KEY, vocab=vocab):
        return None
    volume = as_mapping(process_of(profile).get("volume")) or {}
    count, period = volume.get("count"), str(volume.get("period") or "").strip()
    if isinstance(count, int | float) and not isinstance(count, bool) and period:
        return f"{count:g} a {period}"
    raw = str(volume.get("raw") or "").strip()
    return raw or None
