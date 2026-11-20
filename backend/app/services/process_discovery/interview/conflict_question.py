"""The conflict question, built by code with no model call (spec 14 §3.17 item 3).

Why: when a document says something different from the expert, or from another document, the
expert decides (product rule 4), and the question must show both values exactly as stored, name
both sources, and offer only the choices that make sense ("both" only for lists that still fit).
A model rewording it could drop a value or soften the choice, so code writes it, and the reply is
read by code too (`replies.read_conflict_reply`).
What: `conflict_question(profile, group, *, vocab, names)` → the message of §3.17 item 3 for one
group (one conflict: three lines; two or three: a header, one line each and the close), and
`both_offered(profile, group)`.
Must not: call a model, read a clock, import `documents`, or say "noted", "saved" or "recorded".
Spec 14 §3.17 items 2–3; AC-14.91, AC-14.94, AC-14.95.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.utils.prompt_safety import single_line

from ..domain.field_spec import Vocabulary
from ..profile.conflicts import ConflictView, list_max, union
from ..profile.shapes import as_list, normalized_profile, parse_step_key, resolve_key, rows_of
from .prompts.common import text_value

NAME_MAX = 120
VALUE_MAX = 200
IMAGE_MARK = " (from an image)"
CLOSE_BOTH = "Which should I keep: yours, the document's, both, or tell me in your words?"
CLOSE_EXPERT = "Which should I keep: yours or the document's, or tell me in your words?"
CLOSE_DOCUMENT = "Which is right, or how would you put it?"


def _value(value: Any) -> str:
    items = as_list(value)
    text = "; ".join(text_value(i) for i in items) if items is not None else text_value(value)
    text = single_line(text, 10_000)
    return text if len(text) <= VALUE_MAX else text[: VALUE_MAX - 1].rstrip() + "…"


def _name(names: Mapping[str, str], document_id: str | None) -> str:
    return single_line(names.get(document_id or "", "a removed document"), NAME_MAX)


def _label(view: ConflictView, vocab: Vocabulary) -> str:
    """`<Label>` plus `, <sub label>` (S07: `Inputs` / `Outputs`; others: the key with `_` as a space)."""
    address = resolve_key(view.key)
    if address is None:
        return view.key
    label = vocab.label(address.spec)
    if view.sub is None:
        return label
    lists = any(s.kind == "list" for s in address.spec.subfields)
    sub = view.sub.replace("_", " ")
    return f"{label}, {sub.capitalize() if lists else sub}"


def _step(profile: Mapping[str, Any], view: ConflictView) -> tuple[int, str] | None:
    parsed = parse_step_key(view.key)
    if parsed is None:
        return None
    rows = rows_of(profile)
    name = str(rows[parsed[0] - 1].get("name") or "") if parsed[0] <= len(rows) else ""
    return parsed[0], single_line(name, NAME_MAX)


def both_offered(profile: Mapping[str, Any], group: Sequence[ConflictView]) -> bool:
    """ "both" is offered only for an expert-kind group whose units are all list-like and whose union fits."""
    if not group or any(v.kind != "expert" or not v.list for v in group):
        return False
    for view in group:
        address = resolve_key(view.key)
        if address is None:
            return False
        spec = address.spec
        if len(union(spec if view.sub is None else None, view.current, view.offered)) > list_max(spec):
            return False
    return True


def _holder(view: ConflictView, names: Mapping[str, str]) -> str:
    if view.kind == "document":
        return f'"{_name(names, view.holder_document_id)}" says "{_value(view.current)}";'
    if view.holder_document_id:
        return f'You confirmed "{_value(view.current)}" from "{_name(names, view.holder_document_id)}".'
    return f'You said "{_value(view.current)}".'


def conflict_question(
    profile: Mapping[str, Any], group: Sequence[ConflictView], *, vocab: Vocabulary, names: Mapping[str, str]
) -> str:
    """The message of §3.17 item 3 for one conflict group (1–3 conflicts, same place, document and kind)."""
    p = normalized_profile(profile)
    first = group[0]
    offered = f'"{_name(names, first.document_id)}"' + (IMAGE_MARK if first.from_image else "")
    if first.kind == "document":
        close = CLOSE_DOCUMENT
    else:
        close = CLOSE_BOTH if both_offered(p, group) else CLOSE_EXPERT
    step = _step(p, first)
    if len(group) == 1:
        place = _label(first, vocab)
        if step is not None:
            place = f'step {step[0]} "{step[1]}" – {place}'
        line = f'{_holder(first, names)} {offered} says "{_value(first.offered)}".'
        return "\n".join([f"About {place}:", line, close])
    where = f'step {step[0]} "{step[1]}"' if step is not None else "the process"
    if first.kind == "document":
        head = f'About {where}, "{_name(names, first.holder_document_id)}" and {offered} differ:'
    else:
        head = f"About {where}, {offered} differs from what you told me:"
    lines = [head]
    for view in group:
        if view.kind == "document":
            holder = f'"{_name(names, view.holder_document_id)}" says "{_value(view.current)}"'
            lines.append(f'- {_label(view, vocab)}: {holder}; {offered} says "{_value(view.offered)}".')
        else:
            lines.append(
                f'- {_label(view, vocab)}: you said "{_value(view.current)}"; the document says "{_value(view.offered)}".'
            )
    return "\n".join([*lines, close])
