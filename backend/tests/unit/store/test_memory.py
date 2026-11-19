"""Runs the repository contract on the in-memory store (spec 15 §3.6, §7; AC-15.1 to AC-15.18, AC-15.25).

Why: tests and local runs use `MemoryRepository`, so it must keep the same promises as the
Cosmos store: whole documents serialised like Cosmos, a new etag on every write, owner scoping,
retention ttl as a field.
What: provides the `harness` fixture for `RepositoryContract` (reading and planting the JSON text
the memory store keeps) and checks the memory store's own health report.
Must not: test Cosmos behaviour; that lives in `test_cosmos.py`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.services.store.memory import MemoryRepository
from tests.unit.store.contract import RETENTION_DAYS, Harness, RepositoryContract


@pytest.fixture
def harness() -> Harness:
    repo = MemoryRepository(retention_days=RETENTION_DAYS)

    def stored(owner: str, item_id: str) -> dict[str, Any] | None:
        text = repo._documents.get((owner, item_id))
        return json.loads(text) if text is not None else None

    def put_raw(doc: dict[str, Any], partition: str | None) -> None:
        repo._documents[(partition or doc["ownerId"], doc["id"])] = json.dumps(doc)

    return Harness(repo=repo, stored=stored, put_raw=put_raw)


class TestMemoryContract(RepositoryContract):
    """The shared contract, on `MemoryRepository`."""


async def test_memory_store_documents_are_json_text():
    repo = MemoryRepository(retention_days=1)
    from tests.unit.store.contract import new_session

    session = await repo.create_session(new_session())
    text = repo._documents[(session.owner_id, session.id)]
    assert isinstance(text, str) and json.loads(text)["ttl"] == 86400


async def test_ac_15_23_memory_check_is_ok_and_close_is_harmless():
    repo = MemoryRepository(retention_days=RETENTION_DAYS)
    health = await repo.check()
    assert health.ok is True and health.ttl_enabled is None
    await repo.close()
