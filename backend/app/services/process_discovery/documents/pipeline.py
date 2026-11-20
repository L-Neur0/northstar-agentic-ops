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
Spec 17 §3.1, §3.7, §3.12–§3.14, §3.17, §4; AC-17.32 to AC-17.38. Amendment §3.18–§3.19: the
reading context goes to the reader and the filter; images are prepared (`image.py`), read by one
call, stored as their transcription only, and screened after the call (I1, I2); the report and the
log line gain the role, the target step and `from_image`; the extra sentences are returned apart so
the interview's chat question can reuse them. AC-17.47 to AC-17.61. Amendment §3.21: the report,
the sentence and the log line count the conflicts a reading recorded (never a value); removing a
document removes its items and conflicts only (P5, P6). AC-17.70, AC-17.77, AC-17.79.
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
from .context import ReadingContext
from .extract import ExtractedText, clean_and_cap, extract_text
from .filter import NO_TARGET_STEP, Filtered, build_diff, has_contact_data
from .image import PreparedImage, prepare_image
from .intake import DocumentKind, DocumentNotFound, DocumentRejected, check_intake, screen
from .reader import read_image_with_model, read_with_model
from .schema import STEP_SCOPED

logger = logging.getLogger("app.documents")

FAILED_MESSAGE = (
    "I couldn't read this document just now. The interview continues without it; you can remove it and try again."
)
NAME_MAX = 120
IMAGE_KINDS = frozenset({"png", "jpeg"})
NO_TARGET_ROWS = (
    "It looks like it belongs to one of your steps, but I couldn't tell which one, so I didn't fill anything "
    "for a step."
)
NO_TARGET_EMPTY = (
    "It looks like it belongs to one step; we haven't listed the steps yet, so I used only what fits the whole process."
)
IMAGE_EMPTY = 'I looked at "{name}" but couldn\'t read enough in it to fill anything.'
REMOVED = "[removed]"


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
    document_role: str | None = None
    target_step: int | None = None
    target_source: str = "none"
    from_image: bool = False
    bytes: int
    chars: int
    truncated: bool
    offered: Tally
    kept: Tally
    skipped: list[SkipOut]
    step_list: int
    message: str
    #: Conflicts recorded by this reading (spec 17 §3.21 item 6).
    conflicts: int = 0


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
    """The record to append, the diff to apply, the report for the route, and what the chat question needs."""

    record: DocumentRecord
    diff: ProposalDiff
    report: DocumentReport
    role: str = "whole_process"
    target_step: int | None = None
    from_image: bool = False
    extras: tuple[str, ...] = ()


def read_extras(*, truncated: bool, step_list: int, case_b: bool, unmatched: int, no_target: str | None) -> list[str]:
    """The sentences added after the main one (§3.12, §3.18 item 10), each its own string."""
    parts: list[str] = []
    if truncated:
        parts.append("It is long, so I read only the first part.")
    if step_list:
        parts.append(f"It describes {step_list} steps; we'll group them into at most {MAX_STEPS} main steps.")
    if case_b:
        given = "You already gave me the steps, so I kept them and only filled gaps."
        if unmatched:
            given += f" {unmatched} of its steps didn't match yours."
        parts.append(given)
    if no_target:
        parts.append(no_target)
    return parts


def read_message(
    name: str,
    *,
    values: int,
    steps: int,
    truncated: bool,
    step_list: int,
    case_b: bool,
    unmatched: int,
    no_target: str | None = None,
    image: bool = False,
    conflicts: int = 0,
) -> str:
    """The sentence the expert sees after a reading (§3.12, §3.21 item 6), built by code."""
    shown = single_line(name, NAME_MAX)
    verb = "looked at" if image else "read"
    places = f"{conflicts} place{'' if conflicts == 1 else 's'}"
    if values or steps:
        found = f"{values} value{'' if values == 1 else 's'}" + (f" and {steps} steps" if steps else "")
        parts = [f'I {verb} "{shown}" and found {found} for your process. Nothing counts until you confirm it.']
        if conflicts:
            parts.append(f"It also differs from what I have in {places}.")
    elif conflicts:
        parts = [f'I {verb} "{shown}". It differs from what I have in {places}; I\'ll ask you which to keep.']
    else:
        parts = [f'I {verb} "{shown}" but found nothing new for the form.']
    parts += read_extras(
        truncated=truncated, step_list=step_list, case_b=case_b, unmatched=unmatched, no_target=no_target
    )
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
    context: ReadingContext | None = None,
) -> DocumentRead:
    """Check, extract, read and filter one upload. Raises `DocumentRejected` (nothing to store) or a budget error."""
    started = time.perf_counter()
    budget = config.text_budget_chars
    kind: str = ""
    raw: BaseModel | None = None
    reader: Literal["model", "bpmn"] = "model"
    image: PreparedImage | None = None
    extracted = ExtractedText("", 0, False)
    profile = session.profile.model_dump(by_alias=True)
    documents = [{"id": d.id, "name": d.name} for d in session.documents]

    def rejected_line(rejected: DocumentRejected) -> None:
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

    try:
        name, kind = check_intake(session.documents, filename, data, config)
        if kind in IMAGE_KINDS:
            image = prepare_image(data, kind, config)
            screen(name, "")
        elif kind == "bpmn":
            reading = read_bpmn(data, budget)
            extracted, raw, reader = reading.text, reading.raw, "bpmn"
            screen(name, extracted.text)
        else:
            extracted = extract_text(kind, data, budget)
            screen(name, extracted.text)
    except DocumentRejected as rejected:
        rejected_line(rejected)
        raise

    empty_image = False
    if image is not None:
        raw = await read_image_with_model(llm, name, image, profile, vocab=vocab, documents=documents, context=context)
        if raw is not None:
            try:
                extracted, empty_image = _image_text(raw, budget)
                screen(name, extracted.text)  # I1: the model saw the image before code could screen it
            except DocumentRejected as rejected:
                rejected_line(rejected)
                raise
    elif reader == "model":
        raw = await read_with_model(
            llm, name, extracted.text, profile, vocab=vocab, documents=documents, context=context
        )

    from_image = image is not None
    filtered = (
        None
        if raw is None
        else build_diff(
            raw,
            document_id=document_id,
            text=extracted.text,
            profile=profile,
            vocab=vocab,
            context=context,
            name=name,
            from_image=from_image,
        )
    )
    if filtered is not None and empty_image:
        filtered = Filtered(ProposalDiff(document_id), (), (), role=filtered.role)
    outcome: Literal["read", "failed"] = "failed" if filtered is None else "read"
    diff = ProposalDiff(document_id) if filtered is None else filtered.diff
    kept = _kept(diff)
    extras: list[str] = []
    if filtered is None:
        offered = Tally()
        message = FAILED_MESSAGE
    elif empty_image:
        offered = Tally()
        message = IMAGE_EMPTY.format(name=single_line(name, NAME_MAX))
    else:
        offered = Tally(fields=filtered.offered_fields, steps=filtered.offered_steps, cells=filtered.offered_cells)
        no_target = None
        if filtered.role in STEP_SCOPED and any(s.reason == NO_TARGET_STEP for s in filtered.skipped):
            no_target = NO_TARGET_ROWS if session.profile.process.substeps else NO_TARGET_EMPTY
        facts = {
            "truncated": extracted.truncated,
            "step_list": len(filtered.step_list),
            "case_b": filtered.steps_given and filtered.offered_steps > 0 and filtered.role not in STEP_SCOPED,
            "unmatched": filtered.unmatched,
            "no_target": no_target,
        }
        extras = read_extras(**facts)
        message = read_message(
            name,
            values=kept.fields + len(diff.step_cells),
            steps=kept.steps,
            image=from_image,
            conflicts=len(diff.conflicts),
            **facts,
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
        document_role=filtered.role if filtered is not None else None,
        target_step=filtered.target_step if filtered is not None else None,
        target_source=filtered.target_source if filtered is not None else "none",
        from_image=from_image,
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
        conflicts=len(diff.conflicts),
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
        conflicts=len(diff.conflicts),
        dropped=_dropped(filtered),
        step_list=len(record.step_list),
        injection_patterns=0,
        document_role=report.document_role,
        target_source=report.target_source,
        from_image=from_image,
        **({"width": image.width, "height": image.height} if image is not None else {}),
        duration_ms=round((time.perf_counter() - started) * 1000),
    )
    return DocumentRead(
        record,
        diff,
        report,
        role=report.document_role or "whole_process",
        target_step=report.target_step,
        from_image=from_image,
        extras=tuple(extras),
    )


def _image_text(raw: BaseModel, budget: int) -> tuple[ExtractedText, bool]:
    """§3.19 item 6: `Image: <summary>` + `Visible text:` + the transcription, capped; contact data in the summary removed (I2).

    Returns the stored text and whether the model saw nothing to read (both parts empty).
    """
    summary = " ".join(str(getattr(raw, "image_summary", "") or "").split())
    visible = str(getattr(raw, "visible_text", "") or "").strip()
    if has_contact_data(summary):
        summary = " ".join(REMOVED if has_contact_data(word) else word for word in summary.split())
    if not summary and not visible:
        return ExtractedText("", 0, False), True
    return clean_and_cap(f"Image: {summary}\nVisible text:\n{visible}", budget), False


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
