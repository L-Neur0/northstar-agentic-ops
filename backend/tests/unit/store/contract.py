"""The repository contract that every store implementation must pass (spec 15 §3, AC-15.1 to AC-15.18, AC-15.25).

Why: the engine depends only on the repository protocol, so the memory store used in tests and
local runs and the Cosmos store used in Azure must behave the same, or a bug hides in whichever
one the tests do not run. One suite, run against both, is how that stays true.
What: `RepositoryContract`, a test class with no fixtures of its own. A subclass in
`test_memory.py` or `test_cosmos.py` provides the `harness` fixture: the repository plus two hooks
to read and plant a stored document as the backend holds it.
Must not: depend on one implementation's internals; anything implementation-specific (the query
text, SDK error mapping, logging) is tested in that implementation's own file.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from app.models.process_discovery_schemas import (
    ClusterRef,
    Idea,
    Message,
    MessageRole,
    Phase,
    Process,
    Profile,
    ReportState,
    Score,
    Session,
    SessionStatus,
)
from app.services.store.repository import (
    ConflictError,
    CorruptDocumentError,
    DeletedCounts,
    SessionRepository,
)

RETENTION_DAYS = 90
RETENTION_TTL = RETENTION_DAYS * 86400
OWNER = "owner-aaaaaaaa-1111"
OTHER = "owner-bbbbbbbb-2222"
AT = "2026-11-19T10:00:00+00:00"
SYSTEM_FIELDS = ("_rid", "_self", "_etag", "_attachments", "_ts")


@dataclass
class Harness:
    repo: SessionRepository
    stored: Callable[[str, str], dict[str, Any] | None]  # (owner, id) -> stored doc incl. system fields
    put_raw: Callable[[dict[str, Any], str | None], None]  # plant a stored doc (in a partition) as the backend holds it


def new_session(owner: str = OWNER, **extra: Any) -> Session:
    return Session(**{"owner_id": owner, "created_at": AT, "updated_at": AT, **extra})


def new_idea(owner: str = OWNER, **extra: Any) -> Idea:
    return Idea(
        **{"owner_id": owner, "name": "Supplier onboarding", "from_session_id": "s-1", "created_at": AT, **extra}
    )


def without_system(doc: dict[str, Any] | None) -> dict[str, Any]:
    assert doc is not None
    return {k: v for k, v in doc.items() if k not in SYSTEM_FIELDS}


class RepositoryContract:
    """Run by subclasses that provide a `harness` fixture."""

    # --- sessions: create and read ------------------------------------------------------------

    async def test_ac_15_1_create_then_get_returns_equal_session_with_etag(self, harness: Harness):
        session = new_session(phase=Phase.FIND)
        created = await harness.repo.create_session(session)
        got = await harness.repo.get_session(OWNER, session.id)
        assert got is not None
        assert got.etag and created.etag == got.etag
        assert got == created
        expected = {**session.model_dump(by_alias=True, mode="json"), "ttl": RETENTION_TTL}
        assert got.model_dump(by_alias=True, mode="json") == expected

    async def test_ac_15_2_stored_document_shape(self, harness: Harness):
        session = new_session()
        await harness.repo.create_session(session)
        doc = without_system(harness.stored(OWNER, session.id))
        assert doc["id"] == session.id
        assert doc["ownerId"] == OWNER
        assert doc["type"] == "session"
        assert "etag" not in doc and "owner_id" not in doc
        assert "createdAt" in doc and "rawSubsteps" in doc

    async def test_ac_15_3_other_owner_gets_none(self, harness: Harness):
        session = new_session()
        await harness.repo.create_session(session)
        assert await harness.repo.get_session(OTHER, session.id) is None

    async def test_ac_15_3_owner_mismatch_inside_document_is_not_returned(self, harness: Harness):
        doc = {**new_session(owner=OTHER).model_dump(by_alias=True, mode="json"), "_etag": '"e"'}
        harness.put_raw(doc, OWNER)  # in OWNER's partition, but the document names OTHER
        assert await harness.repo.get_session(OWNER, doc["id"]) is None

    async def test_ac_15_4_get_session_with_idea_id_returns_none(self, harness: Harness):
        idea = await harness.repo.create_idea(new_idea())
        assert await harness.repo.get_session(OWNER, idea.id) is None
        session = await harness.repo.create_session(new_session())
        assert await harness.repo.get_idea(OWNER, session.id) is None

    async def test_get_missing_session_returns_none(self, harness: Harness):
        assert await harness.repo.get_session(OWNER, "nope") is None

    # --- sessions: replace and concurrency -----------------------------------------------------

    async def test_ac_15_5_replace_with_current_etag_returns_new_etag(self, harness: Harness):
        created = await harness.repo.create_session(new_session())
        replaced = await harness.repo.replace_session(created.model_copy(update={"phase": Phase.BOUNDARIES}))
        assert replaced.etag and replaced.etag != created.etag
        assert replaced.phase is Phase.BOUNDARIES
        got = await harness.repo.get_session(OWNER, created.id)
        assert got == replaced

    async def test_ac_15_6_second_replace_from_same_read_conflicts(self, harness: Harness):
        created = await harness.repo.create_session(new_session())
        first = created.model_copy(update={"phase": Phase.FIND})
        second = created.model_copy(update={"phase": Phase.MEASURE})
        await harness.repo.replace_session(first)
        with pytest.raises(ConflictError):
            await harness.repo.replace_session(second)
        assert harness.stored(OWNER, created.id)["phase"] == "find"  # pyright: ignore[reportOptionalSubscript]

    async def test_ac_15_6_replace_of_deleted_session_conflicts(self, harness: Harness):
        created = await harness.repo.create_session(new_session())
        await harness.repo.delete_session(OWNER, created.id)
        with pytest.raises(ConflictError):
            await harness.repo.replace_session(created)
        assert harness.stored(OWNER, created.id) is None

    async def test_ac_15_7_replace_without_etag_is_a_value_error(self, harness: Harness):
        await harness.repo.create_session(new_session())
        with pytest.raises(ValueError):
            await harness.repo.replace_session(new_session())

    async def test_ac_15_8_create_with_existing_id_conflicts(self, harness: Harness):
        session = new_session()
        await harness.repo.create_session(session)
        with pytest.raises(ConflictError):
            await harness.repo.create_session(session.model_copy(update={"phase": Phase.FIND}))
        assert harness.stored(OWNER, session.id)["phase"] == "context"  # pyright: ignore[reportOptionalSubscript]

    # --- retention -----------------------------------------------------------------------------

    @pytest.mark.parametrize("status", [SessionStatus.ACTIVE, SessionStatus.NO_CANDIDATE])
    async def test_ac_15_9_unfinished_session_gets_retention_ttl(self, harness: Harness, status: SessionStatus):
        session = new_session(status=status, ttl=5)
        await harness.repo.create_session(session)
        assert harness.stored(OWNER, session.id)["ttl"] == RETENTION_TTL  # pyright: ignore[reportOptionalSubscript]

    async def test_ac_15_9_finished_session_has_no_ttl(self, harness: Harness):
        created = await harness.repo.create_session(new_session())
        replaced = await harness.repo.replace_session(created.model_copy(update={"status": SessionStatus.FINISHED}))
        assert "ttl" not in harness.stored(OWNER, created.id)  # pyright: ignore[reportOperatorIssue]
        assert replaced.ttl is None
        direct = new_session(status=SessionStatus.FINISHED, ttl=99)
        await harness.repo.create_session(direct)
        assert "ttl" not in harness.stored(OWNER, direct.id)  # pyright: ignore[reportOperatorIssue]

    @pytest.mark.parametrize(
        ("status", "ttl"), [("open", RETENTION_TTL), ("dismissed", RETENTION_TTL), ("started", None)]
    )
    async def test_ac_15_10_idea_ttl_follows_status(self, harness: Harness, status: str, ttl: int | None):
        idea = new_idea(status=status, ttl=7)
        await harness.repo.create_idea(idea)
        assert harness.stored(OWNER, idea.id).get("ttl") == ttl  # pyright: ignore[reportOptionalMemberAccess]

    # --- loading stored documents ---------------------------------------------------------------

    async def test_ac_15_11_system_fields_are_stripped_and_etag_kept(self, harness: Harness):
        doc = new_session().model_dump(by_alias=True, mode="json")
        harness.put_raw(
            {**doc, "_rid": "r", "_self": "s", "_etag": '"etag-1"', "_attachments": "attachments/", "_ts": 1}, None
        )
        got = await harness.repo.get_session(OWNER, doc["id"])
        assert got is not None
        assert got.etag == '"etag-1"'
        assert got.model_dump(by_alias=True, mode="json") == doc

    async def test_ac_15_12_unknown_key_raises_corrupt_document_naming_id_only(self, harness: Harness):
        doc = new_session().model_dump(by_alias=True, mode="json")
        harness.put_raw({**doc, "secretKey": "the expert said something private", "_etag": '"e"'}, None)
        with pytest.raises(CorruptDocumentError) as info:
            await harness.repo.get_session(OWNER, doc["id"])
        assert doc["id"] in str(info.value)
        assert "private" not in str(info.value)
        assert info.value.__cause__ is None and info.value.__suppress_context__

    # --- listing ---------------------------------------------------------------------------------

    async def test_ac_15_13_list_sessions_owner_only_newest_first_with_summary(self, harness: Harness):
        older = new_session(updated_at="2026-11-18T09:00:00+00:00")
        newer = new_session(
            updated_at="2026-11-19T09:00:00+00:00",
            phase=Phase.REVIEW,
            profile=Profile(process=Process(name="Monthly cost review", cluster=ClusterRef(code="IT-SEC"))),
            score=Score(value=0.5, filled_points=20, total_points=40),
            messages=[
                Message(role=MessageRole.AGENT, text="Which process?", at=AT),
                Message(role=MessageRole.EXPERT, text="The monthly cost review", at=AT),
            ],
            report=ReportState(status="validated"),
        )
        await harness.repo.create_session(older)
        await harness.repo.create_session(newer)
        await harness.repo.create_session(new_session(owner=OTHER))
        await harness.repo.create_idea(new_idea())

        summaries = await harness.repo.list_sessions(OWNER)
        assert [s.id for s in summaries] == [newer.id, older.id]
        top = summaries[0]
        assert top.process_name == "Monthly cost review"
        assert top.cluster_code == "IT-SEC"
        assert top.score == 0.5
        assert top.message_count == 2
        assert top.report_status == "validated"
        assert top.phase is Phase.REVIEW and top.status is SessionStatus.ACTIVE
        assert top.created_at == AT and top.updated_at == "2026-11-19T09:00:00+00:00"
        bottom = summaries[1]
        assert (bottom.process_name, bottom.cluster_code, bottom.message_count, bottom.report_status) == (
            None,
            None,
            0,
            None,
        )
        assert await harness.repo.list_sessions("nobody") == []

    # --- deleting --------------------------------------------------------------------------------

    async def test_ac_15_15_delete_session_true_once_then_false(self, harness: Harness):
        session = await harness.repo.create_session(new_session())
        assert await harness.repo.delete_session(OWNER, session.id) is True
        assert await harness.repo.delete_session(OWNER, session.id) is False
        assert await harness.repo.get_session(OWNER, session.id) is None

    async def test_ac_15_15_other_owner_cannot_delete(self, harness: Harness):
        session = await harness.repo.create_session(new_session())
        assert await harness.repo.delete_session(OTHER, session.id) is False
        assert await harness.repo.get_session(OWNER, session.id) is not None

    async def test_delete_session_never_deletes_an_idea(self, harness: Harness):
        idea = await harness.repo.create_idea(new_idea())
        assert await harness.repo.delete_session(OWNER, idea.id) is False
        assert await harness.repo.get_idea(OWNER, idea.id) is not None

    # --- ideas (AC-15.16) ------------------------------------------------------------------------

    async def test_ac_15_16_idea_create_get_and_scoping(self, harness: Harness):
        idea = new_idea()
        created = await harness.repo.create_idea(idea)
        assert created.etag
        got = await harness.repo.get_idea(OWNER, idea.id)
        assert got is not None and got == created
        assert got.model_dump(by_alias=True, mode="json") == {
            **idea.model_dump(by_alias=True, mode="json"),
            "ttl": RETENTION_TTL,
        }
        doc = without_system(harness.stored(OWNER, idea.id))
        assert doc["type"] == "idea" and doc["ownerId"] == OWNER and "etag" not in doc
        assert await harness.repo.get_idea(OTHER, idea.id) is None

    async def test_ac_15_16_idea_replace_and_conflict(self, harness: Harness):
        created = await harness.repo.create_idea(new_idea())
        first = created.model_copy(update={"status": "dismissed"})
        second = created.model_copy(update={"status": "started"})
        replaced = await harness.repo.replace_idea(first)
        assert replaced.etag and replaced.etag != created.etag
        with pytest.raises(ConflictError):
            await harness.repo.replace_idea(second)
        assert harness.stored(OWNER, created.id)["status"] == "dismissed"  # pyright: ignore[reportOptionalSubscript]
        with pytest.raises(ValueError):
            await harness.repo.replace_idea(new_idea())
        with pytest.raises(ConflictError):
            await harness.repo.create_idea(created)

    async def test_ac_15_16_idea_delete_and_list(self, harness: Harness):
        old = await harness.repo.create_idea(new_idea(created_at="2026-11-01T00:00:00+00:00"))
        new = await harness.repo.create_idea(new_idea(created_at="2026-11-02T00:00:00+00:00"))
        await harness.repo.create_idea(new_idea(owner=OTHER))
        await harness.repo.create_session(new_session())
        listed = await harness.repo.list_ideas(OWNER)
        assert [i.id for i in listed] == [new.id, old.id]
        assert all(i.etag for i in listed)
        assert await harness.repo.delete_idea(OTHER, old.id) is False
        assert await harness.repo.delete_idea(OWNER, old.id) is True
        assert await harness.repo.delete_idea(OWNER, old.id) is False
        assert [i.id for i in await harness.repo.list_ideas(OWNER)] == [new.id]

    async def test_delete_idea_never_deletes_a_session(self, harness: Harness):
        session = await harness.repo.create_session(new_session())
        assert await harness.repo.delete_idea(OWNER, session.id) is False
        assert await harness.repo.get_session(OWNER, session.id) is not None

    # --- delete my data (AC-15.17) -----------------------------------------------------------------

    async def test_ac_15_17_delete_owner_data(self, harness: Harness):
        for _ in range(2):
            await harness.repo.create_session(new_session())
        await harness.repo.create_idea(new_idea())
        kept_session = await harness.repo.create_session(new_session(owner=OTHER))
        kept_idea = await harness.repo.create_idea(new_idea(owner=OTHER))

        counts = await harness.repo.delete_owner_data(OWNER)
        assert counts == DeletedCounts(sessions=2, ideas=1)
        assert await harness.repo.list_sessions(OWNER) == []
        assert await harness.repo.list_ideas(OWNER) == []
        assert await harness.repo.get_session(OTHER, kept_session.id) is not None
        assert await harness.repo.get_idea(OTHER, kept_idea.id) is not None
        assert await harness.repo.delete_owner_data(OWNER) == DeletedCounts(sessions=0, ideas=0)

    # --- no mutation (AC-15.18) ---------------------------------------------------------------------

    async def test_ac_15_18_inputs_not_mutated_and_outputs_are_new(self, harness: Harness):
        session = new_session(ttl=5)
        before = session.model_dump(by_alias=True, mode="json")
        created = await harness.repo.create_session(session)
        assert created is not session
        assert session.model_dump(by_alias=True, mode="json") == before and session.etag is None and session.ttl == 5

        edited = created.model_copy(update={"status": SessionStatus.FINISHED})
        edited_before, edited_etag = edited.model_dump(by_alias=True, mode="json"), edited.etag
        replaced = await harness.repo.replace_session(edited)
        assert replaced is not edited
        assert edited.model_dump(by_alias=True, mode="json") == edited_before and edited.etag == edited_etag

        got_a = await harness.repo.get_session(OWNER, session.id)
        got_b = await harness.repo.get_session(OWNER, session.id)
        assert got_a is not got_b and got_a is not None
        got_a.messages.append(Message(role=MessageRole.EXPERT, text="x", at=AT))
        assert got_b is not None and got_b.messages == []

        idea = new_idea(ttl=3)
        idea_before = idea.model_dump(by_alias=True, mode="json")
        created_idea = await harness.repo.create_idea(idea)
        assert created_idea is not idea and idea.model_dump(by_alias=True, mode="json") == idea_before
