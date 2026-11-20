"""API tests for documents and proposals: upload, list, remove, confirm and reject over HTTP (spec 17 §3.1, §3.2, §3.12, §3.13; architecture §3.4).

Why: the expert reaches every document behaviour through five routes, and each must refuse with
the right code and one plain sentence, store only capped text (never bytes), turn a reading into
proposals that do not count until confirmed, keep a failed reading as a record, and save the
session once with its etag (a race is 409 and nothing is lost). These tests prove that through
the real app, the in-memory store and a scripted model.
What: worked example 1 (the procedure .docx and its scripted reply) through POST, GET, DELETE and
the confirm / reject routes; each refusal code of §3.2 (409 `document_limit`, 413
`document_too_large`, 415 `document_type`, 422 `document_unreadable`, 400 `unsafe_input`); BPMN
without a model call; a closed session; another visitor; an etag race.
Must not: patch a route, a node or a writer, or reach Azure. Covers AC-17.1 to AC-17.3, AC-17.12,
AC-17.16, AC-17.32 to AC-17.36 and AC-17.38 at the API level.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.access import owner_from_key
from app.services.process_discovery.documents.pipeline import FAILED_MESSAGE
from app.services.process_discovery.llm import CallType, LLMUnavailableError
from app.services.process_discovery.profile.scoring import score
from tests.unit.process_discovery.documents.helpers import FIXTURES, procedure_profile, procedure_reply, record

from .conftest import KEY_A, KEY_B, ApiHarness, visitor
from .test_interview_flow import SCOPE

OWNER_A = owner_from_key(KEY_A)
NAME = "Monthly cost review procedure.docx"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MESSAGE = (
    'I read "Monthly cost review procedure.docx" and found 5 values and 5 steps for your process. '
    "Nothing counts until you confirm it."
)


def _seed(api: ApiHarness, **update: Any):
    update.setdefault("profile", procedure_profile(api.service.ctx.vocab))
    return asyncio.run(api.seed(OWNER_A, **update))


def _stored(api: ApiHarness, session_id: str):
    stored = asyncio.run(api.repo.get_session(OWNER_A, session_id))
    assert stored is not None
    return stored


def _upload(api: ApiHarness, session_id: str, fixture: str, *, name: str | None = None, key: str = KEY_A):
    data = (FIXTURES / fixture).read_bytes()
    return api.client.post(
        f"/api/sessions/{session_id}/documents",
        files={"file": (name or fixture, data, "application/octet-stream")},
        headers=visitor(key),
    )


def _upload_procedure(api: ApiHarness, session_id: str):
    assert api.llm is not None
    api.llm.add(CallType.READ_DOCUMENT, procedure_reply())
    data = (FIXTURES / "cost_review_procedure.docx").read_bytes()
    return api.client.post(
        f"/api/sessions/{session_id}/documents", files={"file": (NAME, data, DOCX)}, headers=visitor()
    )


def _view(body: dict[str, Any], key: str) -> dict[str, Any]:
    return next(v for v in body["fieldViews"] if v["key"] == key)


# --- upload ---------------------------------------------------------------------------------------


def test_ac_17_32_upload_worked_example_1_returns_the_session_the_document_and_the_report(api: ApiHarness):
    seeded = _seed(api)
    response = _upload_procedure(api, seeded.id)
    assert response.status_code == 201, response.text
    body = response.json()
    report = body["report"]
    assert report["outcome"] == "read" and report["message"] == MESSAGE
    assert report["kept"] == {"fields": 5, "steps": 5, "cells": 24}
    assert report["dropped"] == 3
    assert {s["reason"] for s in report["skipped"]} == {"confirmed", "quote_not_found"}
    document = body["document"]
    assert document["name"] == NAME and document["outcome"] == "read"
    assert document["proposals"] > 0 and document["pending"] == document["proposals"]
    assert "text" not in document
    session = body["session"]
    assert session["documents"] == [document]
    trigger = _view(session, "process.trigger")
    assert trigger["source"] == "document" and trigger["documentName"] == NAME and trigger["quote"]
    filled = score(procedure_profile(api.service.ctx.vocab), vocab=api.service.ctx.vocab).filled_points
    assert session["score"]["filledPoints"] == filled  # proposals do not count
    assert trigger["status"] == "proposed"


def test_ac_17_35_the_stored_record_holds_capped_text_and_no_bytes(api: ApiHarness):
    seeded = _seed(api)
    assert _upload_procedure(api, seeded.id).status_code == 201
    stored = _stored(api, seeded.id)
    [doc] = stored.documents
    assert doc.text and len(doc.text) == doc.chars <= api.company.documents.text_budget_chars
    assert doc.outcome == "read" and doc.proposals > 0
    dumped = doc.model_dump(by_alias=True)
    assert isinstance(dumped["bytes"], int) and "data" not in dumped and "content" not in dumped


def test_ac_17_33_a_failed_reading_is_kept_with_no_proposals(api: ApiHarness):
    assert api.llm is not None
    seeded = _seed(api)
    api.llm.add(CallType.READ_DOCUMENT, LLMUnavailableError(503))
    response = _upload(api, seeded.id, "cost_review_notes.txt", name="notes.txt")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["report"]["outcome"] == "failed" and body["report"]["message"] == FAILED_MESSAGE
    assert body["document"]["proposals"] == 0
    assert _stored(api, seeded.id).documents[0].outcome == "failed"


def test_ac_17_34_a_bpmn_upload_makes_no_model_call(api: ApiHarness):
    assert api.llm is not None
    seeded = _seed(api)
    response = _upload(api, seeded.id, "access_review.bpmn")
    assert response.status_code == 201, response.text
    assert api.llm.calls == []
    body = response.json()
    assert body["report"]["reader"] == "bpmn" and body["report"]["kept"]["steps"] == 4
    assert body["session"]["profile"]["process"]["substeps"][0]["name"]


def test_ac_17_1_ac_17_69_an_eleventh_document_is_409_document_limit_and_nothing_is_stored(api: ApiHarness):
    seeded = _seed(api, documents=[record(f"d{i}") for i in range(1, 11)])
    response = _upload(api, seeded.id, "cost_review_notes.txt")
    assert response.status_code == 409
    assert response.json() == {
        "code": "document_limit",
        "message": "You can add up to 10 documents. Remove one to add another.",
    }
    stored = _stored(api, seeded.id)
    assert len(stored.documents) == 10
    assert stored.messages == seeded.messages  # AC-14.88: a refused upload adds no message


def test_ac_17_68_an_msg_file_is_415_document_type(api: ApiHarness):
    seeded = _seed(api)
    response = api.client.post(
        f"/api/sessions/{seeded.id}/documents",
        files={"file": ("late.msg", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64, "application/vnd.ms-outlook")},
        headers=visitor(),
    )
    assert response.status_code == 415
    assert response.json()["code"] == "document_type"


def test_ac_14_88_the_upload_reply_is_the_agents_question_saved_once(api: ApiHarness):
    seeded = _seed(api)
    saves: list[str] = []
    original = api.repo.replace_session

    async def counting(session):  # type: ignore[no-untyped-def]
        saves.append(session.id)
        return await original(session)

    api.repo.replace_session = counting  # type: ignore[method-assign]
    response = _upload_procedure(api, seeded.id)
    assert response.status_code == 201, response.text
    body = response.json()
    reply = body["reply"]
    assert reply["role"] == "agent"
    assert reply["text"].startswith('From "Monthly cost review procedure.docx" I\'d fill:\n- Trigger: ')
    assert reply["text"].endswith("Should I fill it like this, or is something wrong?")
    assert body["session"]["messages"][-1] == reply
    stored = _stored(api, seeded.id)
    assert stored.messages[-1].text == reply["text"]
    assert stored.last_question.proposals and stored.last_question.focus == []
    assert saves == [seeded.id]


def test_ac_14_82_a_yes_in_the_chat_confirms_the_upload_group(api: ApiHarness):
    assert api.llm is not None
    seeded = _seed(api)
    assert _upload_procedure(api, seeded.id).status_code == 201
    group = list(_stored(api, seeded.id).last_question.proposals)
    api.llm.add(CallType.EXTRACT, {})
    api.llm.add(CallType.CLASSIFY, {"scope": SCOPE})
    api.llm.add(CallType.GUIDE, "What happens next?")
    response = api.client.post(f"/api/sessions/{seeded.id}/messages", json={"text": "yes"}, headers=visitor())
    assert response.status_code == 200, response.text
    session = response.json()["session"]
    for key in group:
        assert _view(session, key)["status"] != "proposed"


def test_ac_17_2_a_file_over_the_size_limit_is_413_document_too_large(api: ApiHarness):
    seeded = _seed(api)
    size = int(api.company.documents.max_file_mb * 1_048_576) + 1
    response = api.client.post(
        f"/api/sessions/{seeded.id}/documents",
        files={"file": ("notes.txt", b"a" * size, "text/plain")},
        headers=visitor(),
    )
    assert response.status_code == 413
    assert response.json() == {"code": "document_too_large", "message": "This file is larger than 10 MB."}
    assert _stored(api, seeded.id).documents == []


def test_ac_17_3_an_unknown_type_is_415_document_type(api: ApiHarness):
    seeded = _seed(api)
    response = api.client.post(
        f"/api/sessions/{seeded.id}/documents",
        files={"file": ("tool.exe", b"MZ\x90\x00binary", "application/octet-stream")},
        headers=visitor(),
    )
    assert response.status_code == 415 and response.json()["code"] == "document_type"
    assert response.json()["message"].startswith("This file type can't be read.")


def test_ac_17_12_a_scan_is_422_document_unreadable(api: ApiHarness):
    seeded = _seed(api)
    response = _upload(api, seeded.id, "scanned.pdf")
    assert response.status_code == 422 and response.json()["code"] == "document_unreadable"
    assert _stored(api, seeded.id).documents == []


def test_ac_17_16_an_injection_is_400_unsafe_input_with_no_model_call(api: ApiHarness):
    assert api.llm is not None
    seeded = _seed(api)
    response = _upload(api, seeded.id, "injection.txt")
    assert response.status_code == 400
    assert response.json() == {
        "code": "unsafe_input",
        "message": "This document contains text that looks like instructions to the assistant, so I didn't read it.",
    }
    assert api.llm.calls == [] and _stored(api, seeded.id).documents == []


def test_upload_without_a_file_is_422_invalid_value(api: ApiHarness):
    seeded = _seed(api)
    response = api.client.post(f"/api/sessions/{seeded.id}/documents", data={"x": "1"}, headers=visitor())
    assert response.status_code == 422 and response.json()["code"] == "invalid_value"


def test_upload_on_a_closed_session_is_400_session_closed(api: ApiHarness):
    seeded = _seed(api, status="finished", phase="finished")
    response = _upload(api, seeded.id, "cost_review_notes.txt")
    assert response.status_code == 400 and response.json()["code"] == "session_closed"


def test_another_visitors_session_is_404_on_every_document_route(api: ApiHarness):
    seeded = _seed(api)
    base = f"/api/sessions/{seeded.id}"
    assert _upload(api, seeded.id, "cost_review_notes.txt", key=KEY_B).status_code == 404
    assert api.client.get(f"{base}/documents", headers=visitor(KEY_B)).status_code == 404
    assert api.client.delete(f"{base}/documents/d1", headers=visitor(KEY_B)).status_code == 404
    for action in ("confirm", "reject"):
        response = api.client.post(f"{base}/proposals/{action}", json={"keys": ["a"]}, headers=visitor(KEY_B))
        assert response.status_code == 404


def test_upload_race_is_409_conflict_and_the_other_write_survives(api: ApiHarness):
    seeded = _seed(api)
    stale_read = None

    async def capture_then_race(owner: str, session_id: str):
        nonlocal stale_read
        session = await real_get(owner, session_id)
        if stale_read is None:
            stale_read = session
            assert session is not None
            await api.repo.replace_session(session.model_copy(update={"display_name": "other tab"}))
        return stale_read

    real_get = api.repo.get_session
    api.repo.get_session = capture_then_race  # type: ignore[method-assign]
    response = _upload_procedure(api, seeded.id)
    api.repo.get_session = real_get  # type: ignore[method-assign]
    assert response.status_code == 409 and response.json()["code"] == "conflict"
    stored = _stored(api, seeded.id)
    assert stored.display_name == "other tab" and stored.documents == []


# --- list and remove ----------------------------------------------------------------------------------


def test_list_documents_shows_views_and_never_the_text(api: ApiHarness):
    seeded = _seed(api)
    uploaded = _upload_procedure(api, seeded.id).json()["document"]
    response = api.client.get(f"/api/sessions/{seeded.id}/documents", headers=visitor())
    assert response.status_code == 200
    assert response.json() == {"documents": [uploaded]}
    assert "Month-end close" not in response.text and "text" not in uploaded


def test_ac_17_36_remove_drops_open_proposals_and_keeps_confirmed_ones(api: ApiHarness):
    seeded = _seed(api)
    document = _upload_procedure(api, seeded.id).json()["document"]
    base = f"/api/sessions/{seeded.id}"
    confirmed = api.client.post(f"{base}/proposals/confirm", json={"keys": ["process.trigger"]}, headers=visitor())
    assert confirmed.status_code == 200
    response = api.client.delete(f"{base}/documents/{document['id']}", headers=visitor())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["documents"] == []
    process = body["profile"]["process"]
    assert process["trigger"] == "Month-end close is completed in the ledger"
    assert process["end_result"] in (None, "") and process["substeps"] == []
    assert _view(body, "process.trigger")["status"] == "complete"
    assert _stored(api, seeded.id).documents == []


def test_remove_an_unknown_document_is_404(api: ApiHarness):
    seeded = _seed(api)
    response = api.client.delete(f"/api/sessions/{seeded.id}/documents/nope", headers=visitor())
    assert response.status_code == 404 and response.json()["code"] == "not_found"


# --- confirm and reject -------------------------------------------------------------------------------


def test_confirm_proposals_counts_them_and_recomputes_the_score(api: ApiHarness):
    seeded = _seed(api)
    before = _upload_procedure(api, seeded.id).json()["session"]
    keys = ["process.trigger", "process.end_result"]
    response = api.client.post(f"/api/sessions/{seeded.id}/proposals/confirm", json={"keys": keys}, headers=visitor())
    assert response.status_code == 200, response.text
    body = response.json()
    assert all(_view(body, k)["status"] == "complete" for k in keys)
    assert body["score"]["filledPoints"] > before["score"]["filledPoints"]
    assert body["documents"][0]["pending"] == before["documents"][0]["pending"] - 2


def test_reject_proposals_clears_them(api: ApiHarness):
    seeded = _seed(api)
    _upload_procedure(api, seeded.id)
    response = api.client.post(
        f"/api/sessions/{seeded.id}/proposals/reject", json={"keys": ["process.trigger"]}, headers=visitor()
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["profile"]["process"]["trigger"] in (None, "")
    assert _view(body, "process.trigger")["source"] is None


def test_proposal_keys_must_not_be_empty(api: ApiHarness):
    seeded = _seed(api)
    response = api.client.post(f"/api/sessions/{seeded.id}/proposals/confirm", json={"keys": []}, headers=visitor())
    assert response.status_code == 422 and response.json()["code"] == "invalid_value"


def test_confirm_on_a_closed_session_is_400(api: ApiHarness):
    seeded = _seed(api, status="finished", phase="finished")
    response = api.client.post(
        f"/api/sessions/{seeded.id}/proposals/confirm", json={"keys": ["process.trigger"]}, headers=visitor()
    )
    assert response.status_code == 400 and response.json()["code"] == "session_closed"
