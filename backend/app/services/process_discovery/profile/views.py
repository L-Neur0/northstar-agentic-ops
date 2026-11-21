"""Field views for the screens: one status per field and per step cell, computed once (spec 13 §3.11).

Why: the live panel and the review screen must show the same status the interview acts on. If the
client computed "complete" or "deferred" itself, it would drift from the registry and the
counters; so the status, reason, source, quote and ask count of every field are built here.
What: `field_views` returns one plain dict per process field and per cell of every step row, with
the keys of the `FieldView` wire model (spec 12), so the service can validate it directly.
Must not: import the API models (the layer rule), write anything, or expose `__meta` internals
beyond source, quote and document name. Spec 13 §3.11; AC-13.50. Amendment §3.13 item 5: a view
also says whether the field came from an image, whether it has an open or left conflict, and, for a
value that mixes sources, the source and file of each item (AC-17.76).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..domain.field_spec import (
    FIELD_ASK_LIMIT,
    PROFILE_SPECS,
    REVIEW_ASK_LIMIT,
    STEP_SPECS,
    FieldSpec,
    Vocabulary,
    field_applies,
    field_status,
    has_any_answer,
    step_cell_key,
)
from .coercion import coerce_count
from .conflicts import ConflictView, item_sources, open_conflicts
from .shapes import as_mapping, meta_for, normalized_profile, rows_of, stored_value
from .verdicts import cell_skipped, grade


def _asks(counters: Mapping[str, Any], name: str, key: str) -> int:
    return coerce_count((as_mapping(counters.get(name)) or {}).get(key))


def _view(
    profile: Mapping[str, Any],
    spec: FieldSpec,
    key: str,
    *,
    vocab: Vocabulary,
    asks: int,
    skipped: bool,
    documents: Mapping[str, str],
    is_process: bool,
    conflicts: Sequence[ConflictView] = (),
) -> dict[str, Any]:
    verdict = grade(profile, key, vocab=vocab)
    meta = meta_for(profile, key)
    answered = has_any_answer(spec, stored_value(profile, key))
    status = field_status(verdict, meta, answered=answered, skipped=skipped)
    if is_process and status in ("empty", "invalid", "partial"):
        limit = spec.max_asks or FIELD_ASK_LIMIT
        if asks >= limit + REVIEW_ASK_LIMIT or (spec.optional and asks >= limit):  # optional: spec 14 §3.19 W2
            status = "given_up"
        elif asks >= limit:
            status = "deferred"
    meta = meta or {}
    document_id = meta.get("documentId")
    items = [
        {
            "sub": part["sub"],
            "item": part["item"],
            "source": part.get("source"),
            "document_name": documents.get(str(part.get("documentId"))) if part.get("documentId") else None,
            "from_image": bool(part.get("fromImage")),
        }
        for part in (item_sources(spec, stored_value(profile, key), meta) if meta.get("parts") else [])
    ]
    states = {c.status for c in conflicts if c.key == key}
    return {
        "key": key,
        "id": spec.id,
        "label": vocab.label(spec),
        "phase": spec.phase,
        "status": status,
        "reason": "" if verdict.is_complete else verdict.reason,
        "missing": [] if verdict.is_complete else list(verdict.missing),
        "source": meta.get("source"),
        "quote": meta.get("quote") if meta.get("source") is not None else None,
        "document_name": documents.get(document_id) if isinstance(document_id, str) else None,
        "asks": asks,
        "from_image": bool(meta.get("fromImage")),
        "conflict": "open" if "open" in states else "left" if "left" in states else None,
        "items": items,
    }


def field_views(
    profile: Mapping[str, Any],
    *,
    counters: Mapping[str, Any],
    vocab: Vocabulary,
    documents: Sequence[Mapping[str, str]] = (),
) -> list[dict[str, Any]]:
    """One view per process field (ask order), then per cell of every step row (S01–S12)."""
    p = normalized_profile(profile)
    names = {d.get("id", ""): d.get("name", "") for d in documents}
    conflicts = open_conflicts(p)
    views = [
        _view(
            p,
            spec,
            spec.key,
            vocab=vocab,
            asks=_asks(counters, "field_asks", spec.key),
            skipped=False,
            documents=names,
            is_process=True,
            conflicts=conflicts,
        )
        for spec in PROFILE_SPECS
    ]
    for index, row in enumerate(rows_of(p), start=1):
        for spec in STEP_SPECS:
            if not field_applies(spec, row):
                continue  # spec 12 §3.13: S14 is shown only for a judgement or mix step
            key = step_cell_key(index, spec.key)
            views.append(
                _view(
                    p,
                    spec,
                    key,
                    vocab=vocab,
                    asks=_asks(counters, "cell_asks", key),
                    skipped=cell_skipped(row, spec.key),
                    documents=names,
                    is_process=False,
                    conflicts=conflicts,
                )
            )
    return views
