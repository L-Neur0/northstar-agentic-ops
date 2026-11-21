"""Unit tests for the workspace session list: rows, filters and counts (spec 21 §3.2; AC-21.2 to AC-21.7).

Why: the list is the specialist's entry to every session, so its counts must match what the
interview itself shows (the same field views), the filters must combine as the screen promises,
and the status tiles must count every session, not just the filtered ones.
What: `review_rows` on stored `Session` models built from the cost-review fixture profile and on
bare sessions: one row per session with the §3.2 columns, the AND of `status`, `cluster`, `q`, the
counts taken before filters. Truncation (AC-21.7) is the store's flag, tested in the store and API tests.
Must not: touch the store or the clock; the function is pure.
"""

from __future__ import annotations

from typing import Any

from app.models.process_discovery_schemas import DocumentRecord, Message, Profile, Session, SessionStatus
from app.services.process_discovery.admin.listing import review_rows
from app.services.process_discovery.domain.field_spec import PROFILE_SPECS, STEP_SPECS
from app.services.process_discovery.profile.views import field_views
from tests.fixtures.assessment.profiles import load_profile, nig_vocabulary

VOCAB = nig_vocabulary()


def _session(sid: str, updated: str, **extra: Any) -> Session:
    data: dict[str, Any] = {
        "id": sid,
        "owner_id": "o",
        "created_at": "2026-11-01T00:00:00+00:00",
        "updated_at": updated,
    }
    if "profile" in extra:
        extra["profile"] = Profile.model_validate(extra["profile"])
    return Session(**{**data, **extra})


def _finished() -> Session:
    message = Message.model_validate({"role": "agent", "text": "hi", "at": "2026-11-01T00:00:00+00:00"})
    document = DocumentRecord(
        id="d1", name="invoice-procedure.pdf", kind="pdf", bytes=1, chars=1,
        uploaded_at="2026-11-01T00:00:00+00:00", outcome="read",
    )  # fmt: skip
    return _session(
        "s1", "2026-11-19T10:00:00+00:00", status=SessionStatus.FINISHED, profile=load_profile("eu"),
        messages=[message] * 3, documents=[document],
    )  # fmt: skip


def _sessions() -> list[Session]:
    return [
        _finished(),
        _session("s2", "2026-11-19T11:00:00+00:00"),
        _session("s3", "2026-11-18T09:00:00+00:00", status=SessionStatus.NO_CANDIDATE),
    ]


def test_ac_21_2_every_session_newest_first_with_the_columns():
    rows, _, _ = review_rows(_sessions(), vocab=VOCAB)
    assert [r.id for r in rows] == ["s2", "s1", "s3"]
    s1 = rows[1].model_dump(by_alias=True)
    assert s1["processName"] == "Monthly cost review"
    assert (s1["department"], s1["clusterCode"], s1["clusterName"], s1["region"]) == (
        "Finance",
        "FIN",
        "Finance",
        "Europe",
    )
    assert (s1["status"], s1["createdAt"], s1["updatedAt"]) == (
        "finished",
        "2026-11-01T00:00:00+00:00",
        "2026-11-19T10:00:00+00:00",
    )
    blank = rows[0]
    assert (blank.process_name, blank.department, blank.cluster_code, blank.region) == (None, None, None, None)


def test_ac_21_2_ties_are_ordered_by_id():
    same = "2026-11-19T10:00:00+00:00"
    rows, _, _ = review_rows([_session("b", same), _session("a", same)], vocab=VOCAB)
    assert [r.id for r in rows] == ["a", "b"]


def test_ac_21_3_counts_match_field_views_and_stored_lists():
    session = _finished()
    views = field_views(session.profile.model_dump(mode="json", by_alias=True), counters={}, vocab=VOCAB)
    rows, _, _ = review_rows([session], vocab=VOCAB)
    row = rows[0]
    assert (
        row.fields_total
        == len(views)
        == len(PROFILE_SPECS) + 5 * len([s for s in STEP_SPECS if s.applies_when is None])
    )
    assert row.fields_filled == sum(v["status"] == "complete" for v in views)
    assert (row.steps, row.message_count, row.document_count) == (5, 3, 1)


def test_ac_21_4_filters_combine_with_and():
    sessions = _sessions()
    rows, _, matching = review_rows(sessions, status="finished", q="COST", vocab=VOCAB)
    assert [r.id for r in rows] == ["s1"] and matching == 1
    rows, _, matching = review_rows(sessions, status="active", q="cost", vocab=VOCAB)
    assert rows == [] and matching == 0
    assert [r.id for r in review_rows(sessions, cluster="FIN", vocab=VOCAB)[0]] == ["s1"]
    assert [r.id for r in review_rows(sessions, q="finance", vocab=VOCAB)[0]] == ["s1"]  # department
    assert [r.id for r in review_rows(sessions, q="S3", vocab=VOCAB)[0]] == ["s3"]  # id


def test_ac_21_6_counts_are_taken_before_filters():
    _, counts, matching = review_rows(_sessions(), status="finished", vocab=VOCAB)
    assert counts.model_dump(by_alias=True) == {"total": 3, "active": 1, "finished": 1, "noCandidate": 1}
    assert matching == 1


def test_ac_21_6_no_sessions_all_zero():
    rows, counts, matching = review_rows([], vocab=VOCAB)
    assert rows == [] and matching == 0
    assert counts.model_dump() == {"total": 0, "active": 0, "finished": 0, "no_candidate": 0}
