"""Where the interview is when a file arrives: the reading context (spec 17 §3.18 item 1).

Why: the expert may upload any file at any moment, a procedure at the start or, in the middle of
step 3, "here is the report the sites send back". A reader that does not know where the interview
is reads every file as a procedure and proposes the wrong things. This module gathers, from the
session alone, what the reader needs to place a file: the phase, the step in focus, what was
last asked, the last two messages and the step names.
What: `ReadingContext` (frozen) and `reading_context(session, vocab=...)`. The step in focus is the
row of the first step cell key in `last_question.focus`, then `.proposals`; messages are one line
and at most 1,000 characters.
Must not: read a clock, call a model, write the session, or decide anything (code decides the
target step in `filter.resolve_target`). AC-17.45.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.process_discovery_schemas import MessageRole, Session
from app.utils.prompt_safety import single_line

from ..domain.field_spec import Vocabulary
from ..profile.shapes import resolve_key, rows_of

MESSAGE_MAX = 1_000
ASKED_MAX = 4


@dataclass(frozen=True)
class ReadingContext:
    """What the reader is told about the interview; `focus_step` is 1-based or `None`."""

    phase: str = ""
    focus_step: int | None = None
    asked: tuple[str, ...] = ()
    last_agent: str = ""
    last_expert: str = ""
    step_names: tuple[str, ...] = ()


def _last(session: Session, role: MessageRole) -> str:
    text = next((m.text for m in reversed(session.messages) if m.role == role), "")
    return single_line(text, len(text) + 1)[:MESSAGE_MAX]


def reading_context(session: Session, *, vocab: Vocabulary) -> ReadingContext:
    """The context for one reading, from the session as it is before the upload."""
    question = session.last_question
    keys = [*question.focus, *question.proposals]
    focus_step: int | None = None
    asked: list[str] = []
    for key in keys:
        address = resolve_key(key)
        if address is None:
            continue
        if address.step is not None and focus_step is None:
            focus_step = address.step
        if len(asked) < ASKED_MAX:
            label = vocab.label(address.spec)
            asked.append(f"{label} (step {address.step})" if address.step is not None else label)
    rows = rows_of(session.profile.model_dump(mode="json", by_alias=True))
    names = tuple(str(row.get("name") or "").strip() for row in rows)
    return ReadingContext(
        phase=session.phase.value,
        focus_step=focus_step,
        asked=tuple(asked),
        last_agent=_last(session, MessageRole.AGENT),
        last_expert=_last(session, MessageRole.EXPERT),
        step_names=names,
    )
