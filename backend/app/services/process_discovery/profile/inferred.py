"""Tier C of the short step walk: goal and owner proposed by code, never asked (spec 14 §3.19 W6, W8; §3.20 O9).

Why: the evaluation showed the walk spent most of its messages on details the expert's other
answers already imply. The approved flow never asks a step's goal or owner: code proposes
them from what the expert said (what comes out of the step, the expert's own role), the panel shows them as proposals, and the expert confirms them all with one yes
in the review. A proposal counts only once confirmed (product rule 4), so the score never rests on
words the expert did not confirm.
What: `propose_tier_c` (fill-only, meta `{source: agent, status: proposed, quote}`, then the close
test and the roll-ups) and `decline_agent_proposals` (a "no" in the review: the cells are cleared
and skipped, the walk and the list confirmations are left alone).
Must not: overwrite any value or a skipped cell, call a model, read a clock (`at` is passed in),
or touch a cell outside Tier C.
Spec 14 §3.19 W6, W8; AC-14.112, AC-14.113. Amended 2026-11-21 (owner test, §3.20 O9): hand-over is
asked in the optional step question and no longer proposed (AC-14.126).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..domain.field_spec import GROUP_A, GROUP_C, SKIPPED_KEY, SOURCE_AGENT, Vocabulary, step_specs_in_group
from .mutate import close_if_complete, make_meta, rebuild_rollups, remove_meta, set_meta, write_value
from .shapes import as_list, as_mapping, empty_value, meta_for, normalized_profile, parse_step_key, resolve_key, rows_of
from .verdicts import cell_counts, cell_skipped, expected_steps

TIER_C_LEAVES: frozenset[str] = frozenset(s.key for s in step_specs_in_group(GROUP_C))


def _texts(value: Any) -> list[str]:
    return [v.strip() for v in as_list(value) or [] if isinstance(v, str) and v.strip()]


def _tier_a_settled(row: Mapping[str, Any], *, vocab: Vocabulary) -> bool:
    return all(cell_counts(row, s.key, vocab=vocab) or cell_skipped(row, s.key) for s in step_specs_in_group(GROUP_A))


def _open(row: Mapping[str, Any], leaf: str) -> bool:
    value = row.get(leaf)
    return not (isinstance(value, str) and value.strip()) and not cell_skipped(row, leaf)


def _goal(row: Mapping[str, Any]) -> tuple[str, str] | None:
    outputs = _texts((as_mapping(row.get("data")) or {}).get("outputs"))
    if outputs:
        joined = "; ".join(outputs)
        return f"{joined} ready", f"Comes out: {joined}"
    name = str(row.get("name") or "").strip()
    return (f"{name} done", name) if name else None


def _propose(profile: dict[str, Any], index: int, leaf: str, value: str, quote: str, at: str) -> None:
    address = resolve_key(f"process.substeps[{index}].{leaf}")
    if address is None:
        return
    write_value(profile, address, value)
    set_meta(profile, address, make_meta(SOURCE_AGENT, "proposed", at, quote=quote))


def _skip(row: dict[str, Any], leaf: str) -> None:
    skipped = as_list(row.get(SKIPPED_KEY)) or []
    if leaf not in skipped:
        row[SKIPPED_KEY] = [*skipped, leaf]


def propose_tier_c(profile: Mapping[str, Any], *, vocab: Vocabulary, at: str) -> dict[str, Any]:
    """Fill each empty, unskipped Tier C cell of a step whose Tier A is settled with an agent proposal (W6)."""
    result = normalized_profile(profile)
    rows = rows_of(result)
    expected = min(expected_steps(result, vocab=vocab), len(rows))
    role = str(result.get("user_function") or "").strip()
    for index in range(1, expected + 1):
        row = rows[index - 1]
        if not _tier_a_settled(row, vocab=vocab):
            continue
        if _open(row, "goal"):
            goal = _goal(row)
            if goal is not None:
                _propose(result, index, "goal", *goal, at)
            else:
                _skip(row, "goal")
        if _open(row, "owner"):
            if role:
                _propose(result, index, "owner", role, f"Your role: {role}", at)
            else:
                _skip(row, "owner")
    close_if_complete(result, vocab=vocab)
    rebuild_rollups(result)
    return result


def is_agent_proposal(profile: Mapping[str, Any], key: str) -> bool:
    """The key holds a proposal written by `propose_tier_c` (meta `source: agent`, `status: proposed`)."""
    meta = meta_for(profile, key) or {}
    return meta.get("source") == SOURCE_AGENT and meta.get("status") == "proposed"


def decline_agent_proposals(profile: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    """A "no" to agent proposals (W8): each is cleared and skipped; the walk and the list confirmations stay."""
    result = normalized_profile(profile)
    rows = rows_of(result)
    for key in keys:
        parsed = parse_step_key(key)
        address = resolve_key(key)
        if parsed is None or address is None or parsed[1] not in TIER_C_LEAVES or not 1 <= parsed[0] <= len(rows):
            continue
        if not is_agent_proposal(result, key):
            continue
        write_value(result, address, empty_value(address.spec))
        remove_meta(result, address)
        _skip(rows[parsed[0] - 1], parsed[1])
    return result
