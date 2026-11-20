"""Efficiency: report quality weighed against the expert messages it took (spec 24 §3.9a).

Why: the product owner wants short interviews, never endless chats. A session that gets every
field right in 58 messages is not a success, and one that stops gaining after message 20 should
show where it stalled. So quality is always shown beside the number of messages, and the series of
snapshots shows which messages changed nothing (wasted turns) and where progress stopped (plateaus).
What: `score_efficiency` (messages to *Finish*, the hard cap verdict, efficiency = correct fields ÷
messages, wasted turns, plateaus), `progress_curve` (report quality and product score after every
expert message, scored with the same field scorer, so a value judged before is not judged again)
and `sparkline` (one character per message, `▁` to `█`).
Must not: count uploads, *Finish*, snapshots or button presses as messages; count a confirmation
answer ("yes", "no", "mine", a code-answered cluster reply) as wasted.
Spec 24 §3.9a; AC-24.31 to AC-24.36.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel, Field

from .persona import HARD_CAP, Persona
from .play import Snapshot
from .score_fields import JudgeLike, score_fields

MESSAGE_TARGET = {"cooperative": 30, "difficult": 40}
WASTED_TARGET = 3
PLATEAU_LENGTH = 5
CONFIRM_MAX_WORDS = 6
BARS = "▁▂▃▄▅▆▇█"


class EfficiencyScores(BaseModel):
    messages: int
    messages_to_finish: int | None
    message_target: int
    failed: bool
    efficiency: float | None
    wasted: int
    wasted_at: list[int] = Field(default_factory=list)
    plateaus: list[list[int]] = Field(default_factory=list)


class CurvePoint(BaseModel):
    n: int
    quality: float
    score: float
    phase: str


def word_set(phrases: Iterable[str]) -> frozenset[str]:
    """Every word of the yes / no / conflict phrases of `language.yaml`."""
    return frozenset(w for p in phrases for w in re.findall(r"[a-z']+", p.lower()))


def is_confirmation(text: str, words: frozenset[str]) -> bool:
    tokens = re.findall(r"[a-z']+", text.lower())
    return 0 < len(tokens) <= CONFIRM_MAX_WORDS and all(t in words for t in tokens)


def _state(snap: Snapshot) -> tuple[Any, ...]:
    statuses = sorted((str(v.get("key")), str(v.get("status"))) for v in snap.fieldViews)
    return (snap.profile, statuses, snap.phase)


def score_efficiency(
    persona: Persona,
    snapshots: Sequence[Snapshot],
    correct_at_finish: int | None,
    words: frozenset[str],
    *,
    messages_to_finish: int | None,
    expert_texts: Sequence[str] = (),
    code_replies: Sequence[int] = (),
) -> EfficiencyScores:
    """Messages, the hard-cap verdict, efficiency, wasted turns and plateaus from a snapshot series."""
    failed = messages_to_finish is None or messages_to_finish > HARD_CAP
    messages = max((s.n for s in snapshots), default=0)
    wasted: list[int] = []
    plateaus: list[list[int]] = []
    streak: list[int] = []
    for previous, snap in zip(snapshots, snapshots[1:], strict=False):
        if snap.event != "message":
            continue
        text = expert_texts[snap.n - 1] if 0 < snap.n <= len(expert_texts) else ""
        confirmation = snap.n in code_replies or is_confirmation(text, words)
        if _state(snap) == _state(previous) and not confirmation:
            wasted.append(snap.n)
        if snap.score > previous.score + 1e-9:
            streak = []
        else:
            streak.append(snap.n)
            if len(streak) == PLATEAU_LENGTH:
                plateaus.append(streak)
                streak = []
    efficiency = None
    if not failed and correct_at_finish is not None and messages_to_finish:
        efficiency = round(correct_at_finish / messages_to_finish, 2)
    return EfficiencyScores(
        messages=messages,
        messages_to_finish=None if failed else messages_to_finish,
        message_target=MESSAGE_TARGET[persona.kind],
        failed=failed,
        efficiency=efficiency,
        wasted=len(wasted),
        wasted_at=wasted,
        plateaus=plateaus,
    )


async def progress_curve(persona: Persona, snapshots: Sequence[Snapshot], judge: JudgeLike) -> list[CurvePoint]:
    """Report quality and product score after every expert message (AC-24.36)."""
    points: list[CurvePoint] = []
    for snap in snapshots:
        if snap.event != "message":
            continue
        scores = await score_fields(persona, snap.profile, judge)
        points.append(CurvePoint(n=snap.n, quality=round(scores.quality, 4), score=snap.score, phase=snap.phase))
    return points


def sparkline(values: Sequence[float]) -> str:
    """One bar per value, scaled 0-100 %."""
    return "".join(BARS[min(len(BARS) - 1, max(0, round(v * (len(BARS) - 1))))] for v in values)
