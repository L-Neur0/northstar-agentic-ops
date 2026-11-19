"""Runs the repository contract on the Cosmos store over a fake container, plus Cosmos-only rules (spec 15 §3, §7).

Why: the Cosmos store is what the demo runs on, but unit tests cannot reach Azure. Running the
shared contract on a fake `azure.cosmos.aio` container (real SDK exception classes, etags with
`MatchConditions.IfNotModified`, system fields, partition-scoped queries) proves the repository
logic; the opt-in live test proves the wiring.
What: AC-15.25 (contract on the fake), AC-15.11 and AC-15.12 (via the contract), AC-15.14 (the
list query projects summary fields only), AC-15.19 (SDK errors map to store errors), AC-15.23
(`check()` reports a missing container or TTL off) and AC-15.24 (log lines carry ids, an
8-character owner prefix and counts, never text).
Must not: talk to the network; the live test is `tests/live/test_cosmos_store.py`.
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

import pytest
from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError
from azure.cosmos import exceptions
from azure.cosmos.aio import ContainerProxy

from app.models.process_discovery_schemas import Message, MessageRole
from app.services.store.cosmos import CosmosRepository
from app.services.store.repository import ConflictError, CorruptDocumentError, StoreUnavailableError
from tests.unit.store.contract import AT, OWNER, RETENTION_DAYS, Harness, RepositoryContract, new_idea, new_session
from tests.unit.store.fake_cosmos import FakeContainer


def cosmos_repo(container: FakeContainer, retention_days: int = RETENTION_DAYS, **kwargs: Any) -> CosmosRepository:
    """The fake stands in for the SDK's `ContainerProxy` (duck-typed)."""
    return CosmosRepository(cast(ContainerProxy, container), retention_days=retention_days, **kwargs)


@pytest.fixture
def container() -> FakeContainer:
    return FakeContainer()


@pytest.fixture
def repo(container: FakeContainer) -> CosmosRepository:
    return cosmos_repo(container)


@pytest.fixture
def harness(container: FakeContainer, repo: CosmosRepository) -> Harness:
    return Harness(repo=repo, stored=container.stored, put_raw=container.put_raw)


class TestCosmosContract(RepositoryContract):
    """The shared contract, on `CosmosRepository` over `FakeContainer` (AC-15.25)."""


# --- AC-15.14: the list query never selects the transcript or the profile whole ----------------


async def test_ac_15_14_list_query_projects_summary_fields_only(repo: CosmosRepository, container: FakeContainer):
    await repo.create_session(new_session())
    await repo.list_sessions(OWNER)
    query = " ".join(container.queries[-1].split())
    select = query.split(" FROM ")[0]
    assert "SELECT *" not in select
    assert "ARRAY_LENGTH(c.messages)" in select
    for item in (part.strip() for part in select.removeprefix("SELECT ").split(",")):
        expr = item.split(" AS ")[0].strip()
        assert expr not in ("c.messages", "c.profile", "c"), item
    assert "c.profile.process.name" in select and "c.profile.process.cluster.code" in select
    assert "c.ownerId = @ownerId" in query and "ORDER BY c.updatedAt DESC" in query


# --- AC-15.19: SDK errors map to store errors --------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        exceptions.CosmosHttpResponseError(status_code=503, message="Service Unavailable"),
        exceptions.CosmosHttpResponseError(status_code=429, message="Too many requests"),
        exceptions.CosmosHttpResponseError(status_code=403, message="Forbidden"),
        ServiceRequestError("connection refused"),
        ClientAuthenticationError("no credential"),
    ],
    ids=["503", "429", "403", "connection", "auth"],
)
async def test_ac_15_19_other_errors_become_store_unavailable(
    repo: CosmosRepository, container: FakeContainer, error: Exception
):
    calls: list[Any] = [
        lambda: repo.get_session(OWNER, "x"),
        lambda: repo.create_session(new_session()),
        lambda: repo.list_sessions(OWNER),
        lambda: repo.delete_idea(OWNER, "x"),
        lambda: repo.list_ideas(OWNER),
        lambda: repo.delete_owner_data(OWNER),
    ]
    for call in calls:
        container.fail_next = error
        with pytest.raises(StoreUnavailableError):
            await call()


async def test_ac_15_19_not_found_conflict_and_precondition(repo: CosmosRepository):
    assert await repo.get_session(OWNER, "missing") is None
    assert await repo.get_idea(OWNER, "missing") is None
    assert await repo.delete_session(OWNER, "missing") is False
    assert await repo.delete_idea(OWNER, "missing") is False
    session = await repo.create_session(new_session())
    with pytest.raises(ConflictError):
        await repo.create_session(new_session(id=session.id))
    await repo.replace_session(session)
    with pytest.raises(ConflictError):
        await repo.replace_session(session)  # stale etag -> 412


async def test_store_errors_do_not_carry_document_content(repo: CosmosRepository, container: FakeContainer):
    container.fail_next = exceptions.CosmosHttpResponseError(status_code=503, message="Service Unavailable")
    secret = new_session(messages=[Message(role=MessageRole.EXPERT, text="private words", at=AT)])
    with pytest.raises(StoreUnavailableError) as info:
        await repo.create_session(secret)
    assert "private words" not in str(info.value)


# --- AC-15.23: health ----------------------------------------------------------------------------


async def test_ac_15_23_check_ok_with_ttl_on(repo: CosmosRepository):
    health = await repo.check()
    assert health.ok is True and health.ttl_enabled is True


async def test_ac_15_23_check_reports_ttl_off():
    health = await cosmos_repo(FakeContainer(default_ttl=None)).check()
    assert health.ok is False and health.ttl_enabled is False and "ttl" in health.detail.lower()


async def test_ac_15_23_check_reports_missing_container():
    health = await cosmos_repo(FakeContainer(missing=True)).check()
    assert health.ok is False and health.ttl_enabled is None and "not found" in health.detail.lower()


async def test_ac_15_23_check_reports_unreachable(container: FakeContainer, repo: CosmosRepository):
    container.fail_next = ServiceRequestError("dns")
    health = await repo.check()
    assert health.ok is False and health.ttl_enabled is None


async def test_close_closes_client_and_credential(container: FakeContainer):
    closed: list[str] = []

    class Closable:
        def __init__(self, name: str) -> None:
            self.name = name

        async def close(self) -> None:
            closed.append(self.name)

    repo = cosmos_repo(container, client=Closable("client"), credential=Closable("cred"))
    await repo.close()
    assert closed == ["client", "cred"]


# --- AC-15.24: logging -----------------------------------------------------------------------------

_SECRET = "we fax the invoices to Ludwig"


async def test_ac_15_24_logs_carry_ids_owner_prefix_and_counts_never_text(
    repo: CosmosRepository, container: FakeContainer, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.DEBUG, logger="app")
    session = new_session(messages=[Message(role=MessageRole.EXPERT, text=_SECRET, at=AT)])
    created = await repo.create_session(session)
    await repo.replace_session(created)
    await repo.create_idea(new_idea(words=_SECRET))
    await repo.delete_session(OWNER, session.id)
    container.put_raw({**session.model_dump(by_alias=True, mode="json"), "bad": _SECRET, "_etag": '"e"'})
    with pytest.raises(CorruptDocumentError):
        await repo.get_session(OWNER, session.id)
    await repo.delete_owner_data(OWNER)

    records = [r for r in caplog.records if r.name.startswith("app.services.store")]
    events = {r.getMessage() for r in records}
    assert {"store_session_created", "store_session_replaced", "store_session_deleted"} <= events
    assert {"store_corrupt_document", "store_owner_data_deleted"} <= events
    for record in records:
        fields = {k: v for k, v in vars(record).items() if k in ("sessionId", "ideaId", "owner", "sessions", "ideas")}
        assert "owner" in fields and fields["owner"] == OWNER[:8], record.getMessage()
        dumped = json.dumps(vars(record), default=str)
        assert _SECRET not in dumped and "Ludwig" not in dumped
        assert record.exc_info is None or _SECRET not in str(record.exc_info[1])
    created_line = next(r for r in records if r.getMessage() == "store_session_created")
    assert created_line.sessionId == session.id  # pyright: ignore[reportAttributeAccessIssue]
    deleted = next(r for r in records if r.getMessage() == "store_owner_data_deleted")
    assert deleted.ideas == 1  # pyright: ignore[reportAttributeAccessIssue]
