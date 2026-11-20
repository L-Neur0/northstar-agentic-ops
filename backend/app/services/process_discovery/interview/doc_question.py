"""The agent's question right after an upload, built by code with no model call (spec 14 §3.16).

Why: after an upload the expert should not have to hunt for the proposals in the panel or type
anything to get going. The agent's very next message names the file, says exactly what it would
fill, and asks plainly whether that is right; the expert answers in the chat like any other
question, and the existing reply reading (`read_proposal_reply`) confirms, rejects or leaves the
group, because the question stores the group in `last_question.proposals`. Building it in code
means exact names and values, no second wait after the reading, and wording a test can hold.
What: `DocumentQuestion` and `document_question(...)`: the group (`phases.document_group`), the
message of §3.16 item 4 (process field, step cell, S07 one line per list, the step names, the
"(from an image)" mark, the "there is more" line, the extra sentences) and the `LastQuestion`;
for a reading with nothing to ask or a failed one, the report sentence plus "Let's carry on where
we left off." with the last question kept.
Must not: call a model, read a clock, import `documents` (the service passes plain values), or
say "noted", "saved" or "recorded". Spec 14 §3.16; AC-14.81, AC-14.83 to AC-14.86.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.models.process_discovery_schemas import LastQuestion, Session
from app.utils.prompt_safety import single_line

from ..profile.shapes import normalized_profile, resolve_key, rows_of, stored_value
from .phases import document_group
from .prompts.common import text_value
from .types import InterviewContext

NAME_MAX = 120
VALUE_MAX = 200
CARRY_ON = "Let's carry on where we left off."
CLOSING = "Should I fill it like this, or is something wrong?"
IMAGE_MARK = " (from an image)"


@dataclass(frozen=True)
class DocumentQuestion:
    """The agent's message, the question to store (`None` = keep the session's), the keys asked and the rest."""

    text: str
    last_question: LastQuestion | None
    keys: tuple[str, ...]
    remaining: int


def _value(value: Any, spec: Any = None) -> str:
    text = single_line(text_value(value, spec), 10_000)
    return text if len(text) <= VALUE_MAX else text[: VALUE_MAX - 1].rstrip() + "…"


def _lines(profile: dict[str, Any], keys: Sequence[str], ctx: InterviewContext) -> list[str]:
    rows = rows_of(profile)
    names = [k for k in keys if k.endswith(".name") and "substeps[" in k]
    out: list[str] = []
    if names and len(names) == len(keys):
        steps = " · ".join(f"{resolve_key(k).step} {_value(stored_value(profile, k))}" for k in names)  # pyright: ignore[reportOptionalMemberAccess]
        return [f"The steps: {steps}"]
    for key in keys:
        address = resolve_key(key)
        if address is None:
            continue
        spec = address.spec
        value = stored_value(profile, key)
        if address.step is None:
            out.append(f"{ctx.vocab.label(spec)}: {_value(value, spec)}")
            continue
        row = rows[address.step - 1] if address.step <= len(rows) else {}
        lead = f'Step {address.step} "{single_line(str(row.get("name") or ""), NAME_MAX)}" – '
        if spec.kind == "object" and any(s.kind == "list" for s in spec.subfields):
            for sub in spec.subfields:
                items = (value or {}).get(sub.key) if isinstance(value, dict) else None
                if items:
                    label = (sub.label or sub.key.replace("_", " ")).capitalize()
                    out.append(f"{lead}{label}: {_value('; '.join(str(i) for i in items))}")
            continue
        out.append(f"{lead}{ctx.vocab.label(spec)}: {_value(value, spec)}")
    return out


def document_question(
    session: Session,
    *,
    document_id: str,
    name: str,
    from_image: bool,
    role: str,
    target_step: int | None,
    outcome: Literal["read", "failed"],
    extras: Sequence[str],
    report_sentence: str,
    ctx: InterviewContext,
) -> DocumentQuestion:
    """The agent's question after an upload (§3.16 items 2–5); `session` already holds the applied proposals."""
    profile = normalized_profile(session.profile.model_dump(mode="json", by_alias=True))
    keys: list[str] = []
    remaining = 0
    if outcome == "read":
        keys, remaining = document_group(
            profile,
            session.counters.model_dump(mode="json"),
            document_id=document_id,
            role=role,
            target_step=target_step,
            vocab=ctx.vocab,
        )
    if not keys:
        return DocumentQuestion(f"{report_sentence} {CARRY_ON}", None, (), 0)
    mark = IMAGE_MARK if from_image else ""
    parts = [f'From "{single_line(name, NAME_MAX)}" I\'d fill:']
    parts += [f"- {line}{mark}" for line in _lines(profile, keys, ctx)]
    if remaining:
        parts.append(f"There is more in it ({remaining} other values); I'll ask about those next.")
    if extras:
        parts.append(" ".join(extras))
    parts.append(CLOSING)
    return DocumentQuestion("\n".join(parts), LastQuestion(focus=[], proposals=list(keys)), tuple(keys), remaining)
