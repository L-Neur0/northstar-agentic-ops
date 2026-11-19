"""The READ_DOCUMENT messages: what the model is asked to copy out of a document (spec 17 §3.7).

ACCEPTED FOR NOW: wording to be refined with the product owner; the structure and the rules are
what the tests hold.

Why: the model reads one business document and proposes values for the form. It must be told
exactly which fields exist (generated from the registry, never typed here), that it copies rather
than invents, that every value needs a quote copied word for word, and which fields are already
confirmed, so it spends its attention on the gaps. The document and the current form are untrusted
text and reach the model only inside fences the system message declares as data.
What: `read_document_messages(name, text, profile, vocab=..., documents=...)` → `[system, user]`.
Case A or B of §3.10 (empty step table, or steps the expert already gave) is read from the profile.
Must not: call a model, put an unfenced document or profile value into a prompt, or restate a
field list. Spec 17 §3.7; AC-17.23.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.utils.prompt_safety import fence_instruction, fence_untrusted, single_line

from ..domain.field_spec import (
    PROFILE_SPECS,
    STEP_SPECS,
    FieldSpec,
    Vocabulary,
    has_any_answer,
    object_list_shape_hints,
)
from ..interview.prompts.common import render_profile
from ..llm import ChatMessage
from ..profile.shapes import normalized_profile, rows_of, stored_value
from .filter import refusal

NAME_MAX = 120

ROLE = "You read a business document and propose values for a process form. You copy; you do not invent."
KINDS = (
    "Document kinds. Set `document_kind` to procedure, process_map, example_output or other.\n"
    "- A procedure or a process map: propose the name, the trigger, the end result, and the steps with their "
    "roles, systems, data, approvals and exceptions.\n"
    "- An example output (a report, a form, an export): infer the end result, the outputs of the last step, "
    "and the data that must exist to produce it; each still with a quote."
)
STEPS = "Steps. List the main steps in order, with the names the document uses. If it has more than 6, list them all."
STEPS_GIVEN = (
    "The form already has steps; code matches yours to them and fills only empty cells, so propose every "
    "detail the document gives for each step."
)
QUOTES = (
    "Quotes. Every value carries `quote`: words copied exactly from the document, 3–300 characters, one "
    "sentence or part of one. Never paraphrase a quote. No quote, no value: leave the field null or the list empty."
)
NEVER = (
    "Never propose: names of people (give the role instead); values the document does not state; "
    '"there are none" (leave a list empty when the document says nothing); the fields listed as already '
    "confirmed below."
)


def _field_line(spec: FieldSpec, vocab: Vocabulary) -> str:
    return f"- {spec.leaf} · {vocab.label(spec)}: {spec.rule}"


def _confirmed_keys(profile: Mapping[str, Any]) -> list[str]:
    """Fields and step cells that hold an answer a document may not touch (confirmed or a specialist's)."""
    keys = [
        s.key
        for s in PROFILE_SPECS
        if s.is_process and s.propose and has_any_answer(s, stored_value(profile, s.key)) and refusal(profile, s.key)
    ]
    for index, row in enumerate(rows_of(profile), start=1):
        for spec in STEP_SPECS:
            key = f"process.substeps[{index}].{spec.key}"
            if spec.propose and has_any_answer(spec, row.get(spec.key)) and refusal(profile, key):
                keys.append(key)
    return keys


def read_document_messages(
    name: str,
    text: str,
    profile: Mapping[str, Any],
    *,
    vocab: Vocabulary,
    documents: Sequence[Mapping[str, str]] = (),
) -> list[ChatMessage]:
    """The system message (rules, fields, the fenced current form) and the user message (the fenced document)."""
    current = normalized_profile(profile)
    steps_given = any(has_any_answer(s, row.get(s.key)) for row in rows_of(current) for s in STEP_SPECS)
    process_fields = [_field_line(s, vocab) for s in PROFILE_SPECS if s.is_process and s.propose]
    step_fields = [_field_line(s, vocab) for s in STEP_SPECS if s.propose]
    confirmed = _confirmed_keys(current)
    sections = [
        ROLE,
        fence_instruction("DOCUMENT", "The document") + " " + fence_instruction("PROFILE", "The current form"),
        "Process fields (top level of your reply):\n" + "\n".join(process_fields),
        "Fields of each step (inside `steps`):\n" + "\n".join(step_fields),
        "Row shapes in the form (in your reply every row also carries `quote`):\n"
        + "\n".join(object_list_shape_hints()),
        KINDS,
        STEPS + (" " + STEPS_GIVEN if steps_given else ""),
        QUOTES,
        NEVER,
        "Already confirmed (do not propose): " + (", ".join(confirmed) if confirmed else "(nothing yet)"),
        "The current form:\n" + fence_untrusted(render_profile(current, vocab=vocab, documents=documents), "PROFILE"),
    ]
    user = "Document: " + single_line(name, NAME_MAX) + "\n" + fence_untrusted(text, "DOCUMENT")
    return [{"role": "system", "content": "\n\n".join(sections)}, {"role": "user", "content": user}]
