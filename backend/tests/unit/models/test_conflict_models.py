"""Tests for the storage contract of conflicts and per-item sources (spec 12 §3.6 amendment, approved 2026-11-20).

Why: a stored session must load before and after the amendment, so the new keys (`parts`,
`fromImage`, `__conflicts`, `conflictAsks`, `lastQuestion.conflicts`) need defaults, round-trip in
camelCase, and stay out of the dump when empty; and the sidecar must never reach a model prompt.
What: AC-12.48 and AC-12.49 on `Profile`, `Session` and the EXTRACT profile view.
Must not: touch the store. Spec 12 §3.6 (amendment).
"""

from __future__ import annotations

from app.models.process_discovery_schemas import Counters, LastQuestion, Profile, Session
from app.services.process_discovery.interview.prompts.extractor import extract_view

RECORD = {
    "sub": "outputs",
    "kind": "expert",
    "holderDocumentId": None,
    "value": ["Site report"],
    "documentId": "d2",
    "quote": "Site | Cost",
    "fromImage": False,
    "list": True,
    "status": "open",
    "at": "2026-11-20T10:00:00Z",
}
META = {
    "source": "document",
    "status": "proposed",
    "documentId": "d1",
    "quote": "Ledger",
    "by": None,
    "at": "t",
    "fromImage": True,
    "parts": [
        {
            "sub": None,
            "item": "Ledger",
            "source": "document",
            "documentId": "d1",
            "quote": "Ledger",
            "fromImage": True,
            "at": "t",
        }
    ],
}


def test_ac_12_48_profile_holds_parts_and_conflicts():
    data = {
        "process": {"substeps": [{"name": "Review", "__conflicts": {"data": [RECORD]}, "__meta": {"systems": META}}]},
        "__conflicts": {"process.trigger": [{**RECORD, "sub": None, "list": False}]},
    }
    dumped = Profile.model_validate(data).model_dump(by_alias=True)
    assert dumped["process"]["substeps"][0]["__conflicts"]["data"] == [RECORD]
    assert dumped["process"]["substeps"][0]["__meta"]["systems"] == META
    old = Profile.model_validate({"process": {"substeps": [{"name": "Review"}]}}).model_dump(by_alias=True)
    assert "__conflicts" not in old and "__conflicts" not in old["process"]["substeps"][0]
    assert "__conflicts" not in str(extract_view(dumped))


def test_ac_12_49_session_counters_and_last_question():
    session = Session(
        owner_id="o",
        created_at="t",
        updated_at="t",
        counters=Counters(conflict_asks={"process.trigger": 1}),
        last_question=LastQuestion(conflicts=["process.trigger"]),
    )
    dumped = session.model_dump(by_alias=True)
    assert dumped["counters"]["conflictAsks"] == {"process.trigger": 1}
    assert dumped["lastQuestion"]["conflicts"] == ["process.trigger"]
    assert Session.model_validate(dumped).counters.conflict_asks == {"process.trigger": 1}
    fresh = Session(owner_id="o", created_at="t", updated_at="t")
    assert (fresh.counters.conflict_asks, fresh.last_question.conflicts) == ({}, [])
