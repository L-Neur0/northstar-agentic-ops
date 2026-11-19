"""The document functions the service calls: read an upload, remove a document, list documents (spec 17 §3.1, §3.12–§3.14).

Why: one upload passes many stages (checks, text, reading, quotes, fill-only), and the service
should compose one call, not nine. This module runs them in order, keeps the bytes only for the
length of the call, turns a model failure into a kept record with no proposals, builds the one
sentence the expert sees, and writes exactly one `document_read` log line per attempt with counts
only. It hands a proposal diff back; the service applies it with `profile.apply_proposals`.
What: `DocumentRead`, `DocumentReport` (§3.17), `DocumentView`, `read_document`, `read_message`,
`remove_document`, `document_views`, and `FAILED_MESSAGE`.
Must not: store, cache or log the bytes, the file name, the text, a quote or a value; write the
session (the service saves it once); read a clock other than the monotonic timer for `duration_ms`.
Spec 17 §3.1, §3.7, §3.12–§3.14, §3.17, §4; AC-17.32 to AC-17.38.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from app.core.config import DocumentsConfig
from app.core.logging import correlation_id
from app.models.process_discovery_schemas import DocumentRecord, Profile, Session, WireModel
from app.utils.prompt_safety import single_line

from ..domain.field_spec import MAX_STEPS, Vocabulary
from ..llm import LLM
from ..profile.proposals import ProposalDiff, proposed_keys, remove_document_proposals
from ..profile.shapes import meta_for
from .bpmn_read import read_bpmn
from .extract import ExtractedText, extract_text
from .filter import Filtered, build_diff
from .intake import DocumentKind, DocumentNotFound, DocumentRejected, check_intake, screen
from .reader import read_with_model

logger = logging.getLogger("app.documents")

FAILED_MESSAGE = (
    "I couldn't read this document just now. The interview continues without it; you can remove it and try again."
)
NAME_MAX = 120


class Tally(WireModel):
    fields: int = 0
    steps: int = 0
    cells: int = 0


class SkipOut(WireModel):
    """A dropped proposal as reported: key and reason, never the value or the quote."""

    key: str
    reason: str
    items: int | None = None


class DocumentReport(WireModel):
    """What happened to one upload (§3.17); the service decides what goes on the wire (spec 15)."""

    document_id: str
    kind: DocumentKind
    outcome: Literal["read", "failed"]
    reader: Literal["model", "bpmn"]
    document_kind: str | None = None
    bytes: int
    chars: int
    truncated: bool
    offered: Tally
    kept: Tally
    skipped: list[SkipOut]
    step_list: int
    message: str


class DocumentView(WireModel):
    """One document as listed to the expert: never its text or its step-list quotes."""

    id: str
    name: str
    kind: DocumentKind
    bytes: int
    chars: int
    truncated: bool
    uploaded_at: str
    outcome: Literal["read", "failed"]
    proposals: int
    pending: int


@dataclass(frozen=True)
class DocumentRead:
    """The record to append, the diff to apply, and the report for the route."""

    record: DocumentRecord
    diff: ProposalDiff
    report: DocumentReport


def read_message(
    name: str, *, values: int, steps: int, truncated: bool, step_list: int, case_b: bool, unmatched: int
) -> str:
    """The sentence the expert sees after a reading (§3.12), built by code."""
    shown = single_line(name, NAME_MAX)
    if values or steps:
        found = f"{values} values" + (f" and {steps} steps" if steps else "")
        parts = [f'I read "{shown}" and found {found} for your process. Nothing counts until you confirm it.']
    else:
        parts = [f'I read "{shown}" but found nothing new for the form.']
    if truncated:
        parts.append("It is long, so I read only the first part.")
    if step_list:
        parts.append(f"It describes {step_list} steps; we'll group them into at most {MAX_STEPS} main steps.")
    if case_b:
        given = "You already gave me the steps, so I kept them and only filled gaps."
        if unmatched:
            given += f" {unmatched} of its steps didn't match yours."
        parts.append(given)
    return " ".join(parts)


def _log(level: int, event: str, **fields: Any) -> None:
    logger.log(level, event, extra={"correlationId": correlation_id.get(), **fields})


def _kept(diff: ProposalDiff) -> Tally:
    cells = sum(len(step.cells) for step in diff.steps) + len(diff.step_cells)
    return Tally(fields=len(diff.fields), steps=len(diff.steps), cells=cells)


def _dropped(filtered: Filtered | None) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for skip in filtered.skipped if filtered is not None else ():
        counts[skip.reason] += skip.items or 1
    return dict(counts)


async def read_document(
    session: Session,
    *,
    filename: str,
    data: bytes,
    llm: LLM,
    config: DocumentsConfig,
    document_id: str,
    now: str,
    vocab: Vocabulary,
) -> DocumentRead:
    """Check, extract, read and filter one upload. Raises `DocumentRejected` (nothing to store) or a budget error."""
    started = time.perf_counter()
    budget = config.text_budget_chars
    kind: str = ""
    raw: BaseModel | None = None
    reader: Literal["model", "bpmn"] = "model"
    try:
        name, kind = check_intake(session.documents, filename, data, config)
        extracted: ExtractedText
        if kind == "bpmn":
            reading = read_bpmn(data, budget)
            extracted, raw, reader = reading.text, reading.raw, "bpmn"
        else:
            extracted = extract_text(kind, data, budget)
        screen(name, extracted.text)
    except DocumentRejected as rejected:
        _log(
            logging.WARNING,
            "document_read",
            document_id="",
            kind=kind,
            outcome="rejected",
            reject_code=rejected.code,
            bytes=len(data),
            injection_patterns=rejected.patterns,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        raise

    profile = session.profile.model_dump(by_alias=True)
    if reader == "model":
        documents = [{"id": d.id, "name": d.name} for d in session.documents]
        raw = await read_with_model(llm, name, extracted.text, profile, vocab=vocab, documents=documents)

    filtered = None if raw is None else build_diff(raw, document_id=document_id, text=extracted.text, profile=profile)
    outcome: Literal["read", "failed"] = "failed" if filtered is None else "read"
    diff = ProposalDiff(document_id) if filtered is None else filtered.diff
    kept = _kept(diff)
    if filtered is None:
        offered = Tally()
        message = FAILED_MESSAGE
    else:
        offered = Tally(fields=filtered.offered_fields, steps=filtered.offered_steps, cells=filtered.offered_cells)
        message = read_message(
            name,
            values=kept.fields + len(diff.step_cells),
            steps=kept.steps,
            truncated=extracted.truncated,
            step_list=len(filtered.step_list),
            case_b=filtered.steps_given and filtered.offered_steps > 0,
            unmatched=filtered.unmatched,
        )

    record = DocumentRecord(
        id=document_id,
        name=name,
        kind=kind,
        bytes=len(data),
        chars=extracted.chars,
        truncated=extracted.truncated,
        text=extracted.text,
        uploaded_at=now,
        outcome=outcome,
        step_list=list(filtered.step_list) if filtered is not None else [],
    )
    report = DocumentReport(
        document_id=document_id,
        kind=kind,
        outcome=outcome,
        reader=reader,
        document_kind=getattr(raw, "document_kind", None),
        bytes=len(data),
        chars=extracted.chars,
        truncated=extracted.truncated,
        offered=offered,
        kept=kept,
        skipped=[SkipOut(key=s.key, reason=s.reason, items=s.items or None) for s in filtered.skipped]
        if filtered is not None
        else [],
        step_list=len(record.step_list),
        message=message,
    )
    _log(
        logging.INFO if outcome == "read" else logging.WARNING,
        "document_read",
        document_id=document_id,
        kind=kind,
        outcome=outcome,
        bytes=len(data),
        chars=extracted.chars,
        truncated=extracted.truncated,
        reader=reader,
        offered_fields=offered.fields,
        offered_steps=offered.steps,
        offered_cells=offered.cells,
        kept_fields=kept.fields,
        kept_steps=kept.steps,
        kept_cells=kept.cells,
        dropped=_dropped(filtered),
        step_list=len(record.step_list),
        injection_patterns=0,
        duration_ms=round((time.perf_counter() - started) * 1000),
    )
    return DocumentRead(record, diff, report)


def remove_document(session: Session, document_id: str, *, vocab: Vocabulary, now: str) -> tuple[Session, int]:
    """Drop the record and its open proposals; values confirmed from it stay (§3.13). Returns `(session, removed)`."""
    if not any(d.id == document_id for d in session.documents):
        raise DocumentNotFound(document_id)
    result = remove_document_proposals(session.profile.model_dump(by_alias=True), document_id, vocab=vocab, at=now)
    updated = session.model_copy(
        update={
            "documents": [d for d in session.documents if d.id != document_id],
            "profile": Profile.model_validate(result.profile),
        }
    )
    _log(logging.INFO, "document_removed", document_id=document_id, proposals_removed=len(result.written))
    return updated, len(result.written)


def document_views(session: Session) -> list[DocumentView]:
    """Every document with the number of its values still waiting for the expert's confirmation."""
    profile = session.profile.model_dump(by_alias=True)
    pending = Counter((meta_for(profile, key) or {}).get("documentId") for key in proposed_keys(profile))
    return [
        DocumentView(
            id=d.id,
            name=d.name,
            kind=d.kind,
            bytes=d.bytes,
            chars=d.chars,
            truncated=d.truncated,
            uploaded_at=d.uploaded_at,
            outcome=d.outcome,
            proposals=d.proposals,
            pending=pending.get(d.id, 0),
        )
        for d in session.documents
    ]
