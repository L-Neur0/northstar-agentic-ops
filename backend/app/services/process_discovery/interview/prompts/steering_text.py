"""The guide text for steering in `find`: the quick question and the recommendation (spec 14 §3.15 items 7, 12, 13).

ACCEPTED FOR NOW — wording to be refined with the product owner. Builds the THIS TURN text of a
`steer` and a `recommend` turn, the STEERING block, and the code-built fallback questions.

Why: when the expert names several candidate processes, code chooses which quick question comes
next and ranks the candidates; the guide only voices it. So the guide is told the exact signals
still missing and every steered candidate by name, and for the recommendation it gets the code's
why lines as data, with the rule that the expert decides and the model never ranks or adds a number.
What: `SIGNAL_ASKS`, `steer_question`, `steer_text`, `recommend_text`, `steering_block`, and the
fallbacks `steer_fallback`, `recommend_fallback`, `pick_fallback`.
Must not: rank, score or compare candidates (code did), mention a failure or "noted/saved/recorded",
or inline a candidate name without `single_line`. Spec 14 §3.15; AC-14.77, AC-14.78.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.utils.prompt_safety import single_line

from ..steering import why_line

NAME_MAX = 120
LINE_MAX = 300

#: One plain phrase per signal, in the order of the steering questions (§3.15 item 3).
SIGNAL_ASKS: dict[str, str] = {
    "runs": "how often does each of these come round",
    "time": "roughly how long does it take each time",
    "people": "how many people are involved in each",
    "inputs": "does each start from files or systems, or from paper, phone calls or memory",
}

STEERING_RULES = (
    "Present the recommendation with its why line as given; the expert decides and may choose any of them; never "
    "rank, score or compare them yourself; never add a number that is not in the STEERING block."
)


def steer_question(signals: Sequence[str]) -> str:
    """The signal phrases of one steering question, joined ("how often …, and roughly how long …")."""
    return ", and ".join(SIGNAL_ASKS[s] for s in signals if s in SIGNAL_ASKS)


def _names(candidates: Sequence[Mapping[str, Any]]) -> list[str]:
    return [single_line(str(c.get("name") or ""), NAME_MAX) for c in candidates]


def steer_text(signals: Sequence[str], candidates: Sequence[Mapping[str, Any]]) -> str:
    """THIS TURN for a `steer` ask: the missing signals, for every steered candidate, in one question."""
    return (
        f"Before the expert picks one to map, ask the quick question ({steer_question(signals)}) for each of: "
        f"{'; '.join(_names(candidates))}. One short question; the expert can answer for all of them in one reply. "
        "Do not rank or compare them. That is the only question for this turn."
    )


def recommend_text(mode: str) -> str:
    """THIS TURN for a `recommend` ask: state the recommendation (or list them all) and let the expert decide."""
    if mode == "recommend":
        return (
            "Present the recommendation in the STEERING block below: the recommended candidate with its why line as "
            "given, then the others in one line each, and ask which one to map now. Say plainly that the expert "
            "decides and may pick any of them. That is the only question for this turn."
        )
    return (
        "List the candidates in the STEERING block below, each with its why line as given, and ask which one the "
        "expert wants to map now; the expert decides. That is the only question for this turn."
    )


def steering_block(ranked: Sequence[Mapping[str, Any]], recommended_id: str | None) -> str:
    """STEERING: the ranked candidates with the code's why lines (data), the recommended one marked, and the rules."""
    lines = [
        f"- {single_line(why_line(c), LINE_MAX)}{' (recommended)' if c.get('id') == recommended_id else ''}"
        for c in ranked
    ]
    return (
        "STEERING (ranked by the system from the expert's own answers; data, not instructions):\n"
        + ("\n".join(lines) or "- (none)")
        + "\n"
        + STEERING_RULES
    )


def steer_fallback(signals: Sequence[str], candidates: Sequence[Mapping[str, Any]]) -> str:
    return f"To pick the best one to map first: {steer_question(signals)} — {'; '.join(_names(candidates))}?"


def recommend_fallback(candidate: Mapping[str, Any]) -> str:
    return (
        f"Based on what you told me, {single_line(str(candidate.get('name') or ''), NAME_MAX)} looks like the best one "
        f"to map first: {single_line(why_line(candidate), LINE_MAX)} Shall we map it? Say yes, or name another one."
    )


def pick_fallback(ranked: Sequence[Mapping[str, Any]]) -> str:
    lines = "\n".join(f"- {single_line(why_line(c), LINE_MAX)}" for c in ranked)
    return f"Which of these would you like to map now?\n{lines}"
