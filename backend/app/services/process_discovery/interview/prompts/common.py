"""The welcome message and the profile-to-text renderers every model call shares (spec 14 §3.9, §3.12).

ACCEPTED FOR NOW — wording to be refined with the product owner. The wording here is a first draft of the
prompts, adapted to this product; the structure and the rules are what the tests hold, so the
wording can change after the review without touching the tests.

Why: nothing here belongs to one call. `render_profile` is the one profile-to-text renderer, used by
the guide and also by the document reader and the assessment (the layer test allows exactly that
import), so every call sees the process the same way. A value that is only a proposal is marked
`(proposed, from <document name>)` so no reader can take it for a confirmed answer; `__meta`,
`__skipped`, the flags and the parked step count never appear. The welcome message is the one
message sent without a model call.
What: `welcome_text`, `render_profile`, `step_block`, `text_value`, `field_brief`, `inline_name`.
Must not: call a model, read a clock, or put an unneutralised value into a prompt.
Spec 14 §3.9, §3.12; AC-14.56, AC-14.61, AC-14.62.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.utils.prompt_safety import neutralize, single_line

from ...domain.field_spec import (
    DERIVED_SPECS,
    PROFILE_SPECS,
    STEP_SPECS,
    FieldSpec,
    Vocabulary,
    has_any_answer,
    is_none_row,
    is_proposed,
)
from ...profile.shapes import as_list, as_mapping, meta_for, normalized_profile, process_of, rows_of
from ...profile.verdicts import P16_KEY

NONE_TEXT = "none (confirmed by the expert)"
EMPTY_TEXT = "(none)"
NAME_MAX = 120


def welcome_text(display_name: str | None, *, product_name: str, first_question: str) -> str:
    """The fixed first message (F-01.5; wording amended 2026-11-21, spec 14 §3.20 O1, AC-14.117)."""
    name = single_line(display_name or "", 40)
    greeting = f"Hi {name}!" if name else "Hi!"
    return (
        f"{greeting} I'm the {single_line(product_name, 60)}. Together we'll find a recurring workflow in your "
        "daily work that is worth transforming with AI. We'll map it step by step (it takes about 20 minutes), "
        "then assess where and how AI can help and how much transformation potential it has. You can add a "
        "document (a procedure, a process map, an example) at any time; I'll read it and you confirm what I "
        "found. Your answers describe the work, not you, and the transformation team may read this "
        f"conversation to improve the tool. To start: {first_question}"
    )


def inline_name(value: Any, fallback: str = "the process") -> str:
    """A name used inline in a prompt: one line, capped, fences defused."""
    text = single_line(value, NAME_MAX) if isinstance(value, str) and value.strip() else ""
    return text or fallback


def _sub_label(spec: FieldSpec, key: str) -> str:
    return next((s.label for s in spec.subfields if s.key == key), key.replace("_", " "))


def text_value(value: Any, spec: FieldSpec | None = None) -> str:
    """One stored value as neutralised prose: `(none)` when empty; a none row as an answer."""
    if value is None or value is False or value == "" or value == [] or value == {}:
        return EMPTY_TEXT
    if value is True:
        return "yes"
    if spec is not None and spec.id == "P05":
        cluster = as_mapping(value) or {}
        if not cluster.get("code"):
            return EMPTY_TEXT
        return f"{neutralize(cluster.get('name') or '')} ({neutralize(cluster.get('code'))})".strip()
    mapping = as_mapping(value)
    if mapping is not None:
        if is_none_row(mapping):
            return NONE_TEXT
        pairs = [
            f"{_sub_label(spec, k) if spec else k}: {text_value(v)}"
            for k, v in mapping.items()
            if text_value(v) != EMPTY_TEXT
        ]
        return "; ".join(pairs) or EMPTY_TEXT
    items = as_list(value)
    if items is not None:
        if any(is_none_row(i) for i in items):
            return NONE_TEXT
        rendered = [text_value(i, spec) for i in items]
        return ", ".join(r for r in rendered if r != EMPTY_TEXT) or EMPTY_TEXT
    return neutralize(value)


def _suffix(profile: Mapping[str, Any], key: str, spec: FieldSpec, value: Any, documents: Mapping[str, str]) -> str:
    meta = meta_for(profile, key)
    if not is_proposed(meta) or not has_any_answer(spec, value):
        return ""
    document_id = (meta or {}).get("documentId")
    name = documents.get(document_id) if isinstance(document_id, str) else None
    if (meta or {}).get("source") == "document" and name:
        return f" (proposed, from {single_line(name, NAME_MAX)})"
    return " (proposed, not yet confirmed)"


def _line(
    profile: Mapping[str, Any], spec: FieldSpec, key: str, value: Any, vocab: Vocabulary, docs: Mapping[str, str]
) -> str:
    return f"{vocab.label(spec)}: {text_value(value, spec)}{_suffix(profile, key, spec, value, docs)}"


def step_block(profile: Mapping[str, Any], *, vocab: Vocabulary, documents: Sequence[Mapping[str, str]] = ()) -> str:
    """The step table, step by step, every cell on its own line."""
    docs = {d.get("id", ""): d.get("name", "") for d in documents}
    rows = rows_of(profile)
    if not rows:
        return "(no steps described yet)"
    out: list[str] = []
    for index, row in enumerate(rows, start=1):
        out.append(f"--- STEP {index}: {text_value(row.get('name'))} ---")
        for spec in STEP_SPECS:
            if spec.key == "name":
                continue
            key = f"process.substeps[{index}].{spec.key}"
            out.append(_line(profile, spec, key, row.get(spec.key), vocab, docs))
    return "\n".join(out)


def render_profile(
    profile: Mapping[str, Any], *, vocab: Vocabulary, documents: Sequence[Mapping[str, str]] = ()
) -> str:
    """The whole profile as prose: process fields in ask order, the two roll-ups, then each step.

    `documents` = `[{id, name}]` names the documents proposals came from.
    """
    p = normalized_profile(profile)
    docs = {d.get("id", ""): d.get("name", "") for d in documents}
    proc = process_of(p)
    context = [_line(p, s, s.key, p.get(s.key), vocab, docs) for s in PROFILE_SPECS if not s.is_process]
    process_lines = [
        _line(p, s, s.key, proc.get(s.leaf), vocab, docs)
        for s in PROFILE_SPECS
        if s.is_process and s.key not in ("process.name", P16_KEY)
    ]
    process_lines.append(
        f"{vocab.label(next(s for s in PROFILE_SPECS if s.key == P16_KEY))}: {text_value(proc.get('substep_count'))}"
    )
    name_spec = next(s for s in PROFILE_SPECS if s.key == "process.name")
    name = text_value(proc.get("name")) + _suffix(p, "process.name", name_spec, proc.get("name"), docs)
    derived = [f"{d.label}: {text_value(proc.get(d.key.split('.', 1)[1]))}" for d in DERIVED_SPECS]
    return (
        "\n".join(context)
        + f"\n\n--- PROCESS: {name} ---\n"
        + "\n".join(process_lines)
        + "\n\n"
        + "\n".join(derived)
        + "\n\n--- STEPS ---\n"
        + step_block(p, vocab=vocab, documents=documents)
    )


def field_brief(spec: FieldSpec, vocab: Vocabulary, key: str | None = None) -> str:
    """One registry field for a system prompt: `- Label (key, kind, keys: a, b?)`, `ask:`, `rule:`."""
    keys = ""
    if spec.subfields:
        keys = ", keys: " + ", ".join(f"{s.key}{'' if s.required else '?'}" for s in spec.subfields)
    lines = [f"- {vocab.label(spec)} (`{key or spec.key}`, {spec.kind}{keys})"]
    question = vocab.question(spec)
    if question:
        lines.append(f"    ask: {question}")
    if spec.rule:
        lines.append(f"    rule: {spec.rule}")
    if spec.max_items:
        lines.append(f"    at most {spec.max_items} items")
    return "\n".join(lines)
