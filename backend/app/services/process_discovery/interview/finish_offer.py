"""Offering *Finish* in long sessions: the one line code adds to the agent's reply (spec 14 §3.18).

Why: an expert who keeps talking past the point where the map is good enough should hear, at
fixed points and in the same words, that they may stop and what is still missing; the model is
never trusted to say it, because whether *Finish* is open and which fields are gaps are decisions.
What: `offer_due` (the 40th expert message and every 10th after it, both numbers from settings),
`finish_gaps` (at most 3 gaps by label: process fields first, then step cells), `finish_line` (the
offer when *Finish* is open, what is still needed when it is not) and `with_finish_offer`, the one
place the line is appended to a reply (GUIDE, fallback and conflict turns alike).
Must not: change the phase, a counter, the profile or the last question, close the walk, read a
clock or do any I/O. Spec 14 §3.18 L1 to L4; AC-14.102 to AC-14.104.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..domain.field_spec import PROFILE_SPECS, STEP_SPECS, Vocabulary
from ..profile.scoring import BELOW_GATE, FinishCheck
from ..profile.shapes import as_list, as_mapping, normalized_profile, rows_of
from ..profile.verdicts import cell_counts, expected_steps, field_counts
from .phases import read_counters

#: Gaps named in one line (L2).
OFFER_GAPS_MAX = 3
OFFER_LEAD = "We have covered a lot."
OFFER_END = "Or we can keep going."

#: What is still needed when *Finish* is locked for a reason other than the score (L4).
NEEDED_TEXT: dict[str, str] = {
    "substeps_incomplete": "the steps need to be described to the end",
    "roles_not_confirmed": "the list of roles needs your confirmation",
    "tools_not_confirmed": "the list of systems needs your confirmation",
}


def offer_due(expert_messages: int, *, first: int, every: int) -> bool:
    """L2: at `first` expert messages and every `every` after it."""
    return expert_messages >= first and (expert_messages - first) % max(every, 1) == 0


def finish_gaps(profile: Mapping[str, Any], *, vocab: Vocabulary, limit: int = OFFER_GAPS_MAX) -> list[str]:
    """The labels of scored fields that do not count yet: process fields in registry order, then step cells."""
    p = normalized_profile(profile)
    gaps = [vocab.label(s) for s in PROFILE_SPECS if s.weight and not field_counts(p, s.key, vocab=vocab)]
    for index, row in enumerate(rows_of(p)[: expected_steps(p, vocab=vocab)], start=1):
        gaps += [
            f"{vocab.label(s)} (step {index})"
            for s in STEP_SPECS
            if s.weight and not cell_counts(row, s.key, vocab=vocab)
        ]
        if len(gaps) >= limit:
            break
    return gaps[:limit]


def finish_line(profile: Mapping[str, Any], finish: FinishCheck, *, vocab: Vocabulary) -> str:
    """L2 when *Finish* is open; L4 (what is still needed to reach it) when it is not."""
    gaps = ", ".join(finish_gaps(profile, vocab=vocab))
    if finish.ready:
        missing = f"; still missing: {gaps}." if gaps else "."
        return f"{OFFER_LEAD} You can press Finish now{missing} {OFFER_END}"
    if finish.blocked_by == BELOW_GATE or finish.blocked_by not in NEEDED_TEXT:
        return f"{OFFER_LEAD} Before you can press Finish, we still need: {gaps or 'a few more answers'}."
    return f"{OFFER_LEAD} Before you can press Finish, {NEEDED_TEXT[finish.blocked_by]}."


def with_finish_offer(
    reply: str, state: Mapping[str, Any], finish: FinishCheck, *, vocab: Vocabulary, first: int, every: int
) -> str:
    """The reply, plus the line when this turn answered an expert message whose count is due (L1, L2)."""
    messages = as_list(state.get("messages")) or []
    last = as_mapping(messages[-1]) if messages else None
    if last is None or last.get("role") != "expert":
        return reply
    count = read_counters(as_mapping(state.get("counters")))["expert_messages"]
    if not offer_due(count, first=first, every=every):
        return reply
    return f"{reply}\n\n{finish_line(as_mapping(state.get('profile')) or {}, finish, vocab=vocab)}"
