"""The workspace reads of the store, `find_session` and `scan_sessions`, on both stores (spec 21 §4.3; AC-21.20).

Why: the workspace reads across every expert's partition, which the expert's routes never do, so
these two reads are the only cross-partition code in the store; the memory store used in tests
and the Cosmos store used in Azure must agree on them, or the workspace works locally and breaks
in the demo.
What: one contract class, run on `MemoryRepository` and on `CosmosRepository` over the fake
container: find by id in any partition (with the etag), newest-first scan with the truncated
flag, ties by id, document text blanked, ideas left out.
Must not: depend on one store's internals beyond the fixtures that build it.
"""

from __future__ import annotations

from typing import cast

import pytest
from azure.cosmos.aio import ContainerProxy

from app.models.process_discovery_schemas import DocumentRecord, SessionStatus
from app.services.store.cosmos import CosmosRepository
from app.services.store.memory import MemoryRepository
from app.services.store.repository import SessionRepository
from tests.unit.store.contract import OTHER, OWNER, RETENTION_DAYS, new_idea, new_session
from tests.unit.store.fake_cosmos import FakeContainer

SECRET = "SECRET-DOCUMENT-TEXT"


def _doc() -> DocumentRecord:
    return DocumentRecord(
        id="d1", name="procedure.pdf", kind="pdf", bytes=10, chars=20, text=SECRET,
        uploaded_at="2026-11-19T10:00:00+00:00", outcome="read",
    )  # fmt: skip


def _at(minute: int) -> str:
    return f"2026-11-19T10:{minute:02d}:00+00:00"


class WorkspaceQueriesContract:
    """Run by subclasses that provide a `repo` fixture."""

    async def test_ac_21_20_find_session_in_any_partition_with_etag(self, repo: SessionRepository):
        mine = await repo.create_session(new_session(OWNER))
        theirs = await repo.create_session(new_session(OTHER))
        found = await repo.find_session(theirs.id)
        assert found is not None and found.owner_id == OTHER and found.etag == theirs.etag
        assert (await repo.find_session(mine.id)) == mine

    async def test_ac_21_20_find_session_misses_unknown_ids_and_ideas(self, repo: SessionRepository):
        idea = await repo.create_idea(new_idea())
        assert await repo.find_session("nope") is None
        assert await repo.find_session(idea.id) is None

    async def test_ac_21_20_scan_returns_every_owner_newest_first_ties_by_id(self, repo: SessionRepository):
        await repo.create_session(new_session(OWNER, id="b", updated_at=_at(1)))
        await repo.create_session(new_session(OTHER, id="a", updated_at=_at(1)))
        await repo.create_session(new_session(OWNER, id="c", updated_at=_at(5), status=SessionStatus.FINISHED))
        await repo.create_idea(new_idea())
        sessions, truncated = await repo.scan_sessions()
        assert [s.id for s in sessions] == ["c", "a", "b"]
        assert truncated is False
        assert all(s.etag for s in sessions)

    async def test_ac_21_20_scan_truncates_to_the_newest(self, repo: SessionRepository):
        for minute in range(5):
            await repo.create_session(new_session(OWNER, id=f"s{minute}", updated_at=_at(minute)))
        sessions, truncated = await repo.scan_sessions(limit=3)
        assert [s.id for s in sessions] == ["s4", "s3", "s2"] and truncated is True
        sessions, truncated = await repo.scan_sessions(limit=5)
        assert len(sessions) == 5 and truncated is False

    async def test_ac_21_20_scan_never_returns_document_text(self, repo: SessionRepository):
        await repo.create_session(new_session(OWNER, documents=[_doc()]))
        sessions, _ = await repo.scan_sessions()
        assert sessions[0].documents[0].name == "procedure.pdf"
        assert SECRET not in sessions[0].model_dump_json()

    async def test_scan_with_no_sessions_is_empty(self, repo: SessionRepository):
        assert await repo.scan_sessions() == ([], False)


class TestMemoryWorkspaceQueries(WorkspaceQueriesContract):
    @pytest.fixture
    def repo(self) -> SessionRepository:
        return MemoryRepository(retention_days=RETENTION_DAYS)


class TestCosmosWorkspaceQueries(WorkspaceQueriesContract):
    @pytest.fixture
    def repo(self) -> SessionRepository:
        return CosmosRepository(cast(ContainerProxy, FakeContainer()), retention_days=RETENTION_DAYS)


async def test_only_the_workspace_reads_cross_partitions():
    """The expert's reads stay in one partition; only `find_session` and `scan_sessions` cross them."""
    container = FakeContainer()
    repo = CosmosRepository(cast(ContainerProxy, container), retention_days=RETENTION_DAYS)
    session = await repo.create_session(new_session(OWNER))
    await repo.list_sessions(OWNER)
    await repo.list_ideas(OWNER)
    await repo.delete_owner_data(OTHER)
    assert None not in container.partitions
    await repo.find_session(session.id)
    await repo.scan_sessions()
    assert container.partitions[-2:] == [None, None]
