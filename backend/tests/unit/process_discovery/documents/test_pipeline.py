"""Tests for the upload pipeline the service calls: read, fail softly, remove, list (spec 17 §3.1, §3.7, §3.12–§3.13, §3.17).

Why: these are the functions the service composes into the upload, list and delete routes. They
must turn worked example 1 into exactly its diff and report, keep a failed reading as a record
with no proposals, never call a model for a BPMN file, store only capped text, tell the expert
the right sentence, and remove a document's open proposals while keeping what was confirmed.
What: AC-17.32 to AC-17.36 and AC-17.38, with `FakeLLM` (no network).
Must not: reach Azure. Spec 17 §3.1, §3.7, §3.12, §3.13, §3.15, §3.17.
"""

from __future__ import annotations

import pytest

from app.services.process_discovery.documents.intake import DocumentNotFound, DocumentRejected
from app.services.process_discovery.documents.pipeline import (
    FAILED_MESSAGE,
    document_views,
    read_document,
    read_message,
    remove_document,
)
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.llm import (
    CallType,
    LLMBudgetExceededError,
    LLMEmptyResponseError,
    LLMInvalidOutputError,
    LLMUnavailableError,
)
from app.services.process_discovery.profile.proposals import (
    FieldProposal,
    ProposalDiff,
    StepProposal,
    apply_proposals,
    confirm_proposals,
)
from app.services.process_discovery.profile.shapes import rows_of

from .helpers import AT, STEP_NAMES, procedure_profile, procedure_reply, record, session_with

NAME = "Monthly cost review procedure.docx"


async def read(vocab, docs_config, session, data, *, name=NAME, llm=None, document_id="d1"):
    return await read_document(
        session,
        filename=name,
        data=data,
        llm=llm or FakeLLM(),
        config=docs_config,
        document_id=document_id,
        now=AT,
        vocab=vocab,
    )


async def test_ac_17_32_worked_example_1(vocab, docs_config, fixture_bytes):
    data = fixture_bytes("cost_review_procedure.docx")
    llm = FakeLLM({CallType.READ_DOCUMENT: [procedure_reply()]})
    result = await read(vocab, docs_config, session_with(procedure_profile(vocab)), data, llm=llm)
    llm.assert_all_used()
    assert result.diff.fields == (
        FieldProposal(
            "process.trigger",
            "Month-end close is completed in the ledger",
            "The review starts once month-end close is completed in the ledger",
        ),
        FieldProposal("process.end_result", "The monthly cost report", "The process ends with the monthly cost report"),
        FieldProposal(
            "process.value_at_end",
            "The CFO uses it to decide on budget corrections",
            "which the CFO uses to decide on budget corrections",
        ),
        FieldProposal(
            "process.volume",
            {"count": 1, "period": "month", "raw": "every month for 14 cost centres"},
            "It runs every month for 14 cost centres",
        ),
        FieldProposal(
            "process.process_owner",
            {"role": "Head of Controlling", "none_identified": False},
            "Owner: Head of Controlling",
        ),
    )
    assert [s.cells[0].value for s in result.diff.steps] == list(STEP_NAMES)
    assert result.diff.steps[0] == StepProposal(
        cells=(
            FieldProposal("name", "Export actuals", "Export actuals"),
            FieldProposal(
                "activities",
                ["Export actual costs per cost centre"],
                "exports actual costs per cost centre from SAP S/4HANA",
            ),
            FieldProposal(
                "roles", [{"role": "Cost controller", "contribution": ""}], "The cost controller exports actual costs"
            ),
            FieldProposal("owner", "Cost controller", "The cost controller exports actual costs"),
            FieldProposal("systems", ["SAP S/4HANA"], "from SAP S/4HANA"),
            FieldProposal(
                "data",
                {"inputs": ["Actual costs per cost centre"], "outputs": ["Review workbook"]},
                "exports actual costs per cost centre … into the review workbook",
            ),
        )
    )
    assert result.diff.step_cells == ()
    message = (
        'I read "Monthly cost review procedure.docx" and found 5 values and 5 steps for your process. '
        "Nothing counts until you confirm it."
    )
    assert result.report.model_dump(by_alias=True, exclude_none=True) == {
        "documentId": "d1",
        "kind": "docx",
        "outcome": "read",
        "reader": "model",
        "documentKind": "procedure",
        "bytes": len(data),
        "chars": result.record.chars,
        "truncated": False,
        "offered": {"fields": 7, "steps": 5, "cells": 24},
        "kept": {"fields": 5, "steps": 5, "cells": 24},
        "skipped": [
            {"key": "process.name", "reason": "confirmed"},
            {"key": "process.baseline_metric", "reason": "quote_not_found"},
            {"key": "process.substeps[2].systems", "reason": "quote_not_found", "items": 1},
        ],
        "stepList": 0,
        "message": message,
    }
    assert result.record.outcome == "read"
    assert result.record.uploaded_at == AT
    assert result.record.name == NAME


@pytest.mark.parametrize(
    "error", [LLMEmptyResponseError("empty"), LLMInvalidOutputError(["steps"]), LLMUnavailableError(503)]
)
async def test_ac_17_33_model_failure_keeps_a_failed_record(vocab, docs_config, fixture_bytes, error):
    llm = FakeLLM({CallType.READ_DOCUMENT: [error]})
    result = await read(
        vocab,
        docs_config,
        session_with(procedure_profile(vocab)),
        fixture_bytes("cost_review_notes.txt"),
        name="notes.txt",
        llm=llm,
    )
    assert result.record.outcome == "failed"
    assert result.record.text.startswith("# Cost review notes")
    assert result.diff.is_empty
    assert result.report.message == FAILED_MESSAGE
    assert FAILED_MESSAGE == (
        "I couldn't read this document just now. The interview continues without it; you can remove it and try again."
    )


async def test_ac_17_33_budget_error_is_raised(vocab, docs_config, fixture_bytes):
    llm = FakeLLM({CallType.READ_DOCUMENT: [LLMBudgetExceededError("budget")]})
    with pytest.raises(LLMBudgetExceededError):
        await read(
            vocab,
            docs_config,
            session_with(procedure_profile(vocab)),
            fixture_bytes("cost_review_notes.txt"),
            name="notes.txt",
            llm=llm,
        )


async def test_ac_17_34_bpmn_makes_no_model_call(vocab, docs_config, fixture_bytes):
    llm = FakeLLM()
    result = await read(
        vocab,
        docs_config,
        session_with(procedure_profile(vocab)),
        fixture_bytes("access_review.bpmn"),
        name="access-review.bpmn",
        llm=llm,
    )
    assert llm.calls == []
    assert result.report.reader == "bpmn"
    assert [f.key for f in result.diff.fields] == ["process.trigger", "process.end_result"]  # P04 is confirmed
    assert len(result.diff.steps) == 4
    roles = {c.key: c.value for c in result.diff.steps[0].cells}["roles"]
    assert roles == [{"role": "IT security analyst", "contribution": ""}]


async def test_ac_17_8_unsafe_bpmn_through_the_pipeline(vocab, docs_config, fixture_bytes):
    with pytest.raises(DocumentRejected) as caught:
        await read(vocab, docs_config, session_with(procedure_profile(vocab)), fixture_bytes("xxe.bpmn"), name="x.bpmn")
    assert caught.value.code == "document_unreadable"


async def test_ac_17_19_long_bpmn_gives_a_step_list(vocab, docs_config, fixture_bytes):
    result = await read(
        vocab, docs_config, session_with(procedure_profile(vocab)), fixture_bytes("long_process.bpmn"), name="long.bpmn"
    )
    assert result.diff.steps == ()
    assert [i.name for i in result.record.step_list][:2] == ["Receive request", "Check identity"]
    assert len(result.record.step_list) == 9
    assert all(i.quote == i.name for i in result.record.step_list)
    assert "It describes 9 steps; we'll group them into at most 6 main steps." in result.report.message


async def test_ac_17_35_stored_record(vocab, docs_config, fixture_bytes):
    data = fixture_bytes("long_procedure.txt")
    llm = FakeLLM({CallType.READ_DOCUMENT: [{"document_kind": "procedure"}]})
    result = await read(vocab, docs_config, session_with(procedure_profile(vocab)), data, name="long.txt", llm=llm)
    stored = result.record.model_dump(by_alias=True)
    assert "data" not in stored and "content" not in stored
    assert stored["bytes"] == len(data)
    assert len(result.record.text) == result.record.chars <= docs_config.text_budget_chars
    assert result.record.truncated is True
    assert result.record.outcome in ("read", "failed")
    assert (
        result.report.message
        == 'I read "long.txt" but found nothing new for the form. It is long, so I read only the first part.'
    )


async def test_ac_17_16_injection_upload_makes_no_call(vocab, docs_config, fixture_bytes):
    llm = FakeLLM()
    with pytest.raises(DocumentRejected) as caught:
        await read(
            vocab,
            docs_config,
            session_with(procedure_profile(vocab)),
            fixture_bytes("injection.txt"),
            name="po.txt",
            llm=llm,
        )
    assert caught.value.code == "unsafe_input"
    assert llm.calls == []


def test_ac_17_36_remove_document(vocab):
    profile = procedure_profile(vocab)
    diff = ProposalDiff(
        "d1",
        fields=(
            FieldProposal("process.trigger", "Month-end close", "month-end close"),
            FieldProposal("process.end_result", "The monthly cost report", "monthly cost report"),
            FieldProposal("process.value_at_end", "Budget corrections", "budget corrections"),
        ),
        steps=tuple(StepProposal((FieldProposal("name", n, n),)) for n in STEP_NAMES),
    )
    profile = apply_proposals(profile, diff, vocab=vocab, at=AT).profile
    profile = confirm_proposals(profile, ["process.trigger"], vocab=vocab, at=AT).profile
    session = session_with(profile, [record("d1"), record("d2")])
    new, removed = remove_document(session, "d1", vocab=vocab, now=AT)
    assert [d.id for d in new.documents] == ["d2"]
    after = new.profile.model_dump(by_alias=True)
    assert after["process"]["trigger"] == "Month-end close"
    assert after["__meta"]["process.trigger"]["status"] == "confirmed"
    assert after["__meta"]["process.trigger"]["documentId"] == "d1"
    assert after["process"]["end_result"] == "" and after["process"]["value_at_end"] == ""
    assert rows_of(after) == []
    assert removed == 7
    with pytest.raises(DocumentNotFound):
        remove_document(session, "nope", vocab=vocab, now=AT)


def test_document_views_count_pending_proposals(vocab):
    diff = ProposalDiff("d1", fields=(FieldProposal("process.trigger", "Month-end close", "month-end close"),))
    profile = apply_proposals(procedure_profile(vocab), diff, vocab=vocab, at=AT).profile
    views = document_views(session_with(profile, [record("d1"), record("d2")]))
    assert [(v.id, v.pending) for v in views] == [("d1", 1), ("d2", 0)]
    assert "text" not in views[0].model_dump(by_alias=True)


def test_ac_17_38_messages():
    base = read_message("a.docx", values=5, steps=5, truncated=False, step_list=0, case_b=False, unmatched=0)
    assert (
        base == 'I read "a.docx" and found 5 values and 5 steps for your process. Nothing counts until you confirm it.'
    )
    no_steps = read_message("a.docx", values=2, steps=0, truncated=False, step_list=0, case_b=False, unmatched=0)
    assert no_steps == 'I read "a.docx" and found 2 values for your process. Nothing counts until you confirm it.'
    nothing = read_message("a\nb.docx", values=0, steps=0, truncated=True, step_list=9, case_b=False, unmatched=0)
    assert nothing == (
        'I read "a b.docx" but found nothing new for the form. It is long, so I read only the first part. '
        "It describes 9 steps; we'll group them into at most 6 main steps."
    )
    given = read_message("a.docx", values=1, steps=0, truncated=False, step_list=0, case_b=True, unmatched=0)
    assert given.endswith("You already gave me the steps, so I kept them and only filled gaps.")
