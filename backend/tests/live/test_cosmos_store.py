"""Opt-in live test of the Cosmos store against the real container (spec 15 §7, AC-15.26).

Why: the fake container proves the repository logic, but only the real account proves the wiring:
Entra auth with `az login` (no key), the database and container that Bicep created, `If-Match`
on replace, the partition-scoped summary query and the container TTL setting.
What: with `RUN_LIVE=1` and `COSMOS_ENDPOINT` set, opens the store from the settings in
`backend/.env`, then runs create, get, replace, conflict, list and delete for a fresh random owner,
and removes everything it wrote at the end.
Must not: run in CI or by default (it is marked `live` and skipped), use a key, or touch any
owner but its own random one.
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.core.settings import Settings
from app.models.process_discovery_schemas import Phase, Session
from app.services.store.cosmos import open_cosmos
from app.services.store.repository import ConflictError

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE") != "1" or not os.environ.get("COSMOS_ENDPOINT"),
        reason="live Cosmos call; set RUN_LIVE=1 and COSMOS_ENDPOINT",
    ),
]

AT = "2026-11-19T10:00:00+00:00"


async def test_ac_15_26_live_round_trip():
    settings = Settings(store="cosmos")  # pyright: ignore[reportCallIssue]
    assert settings.store == "cosmos"
    repo = await open_cosmos(settings)
    owner = f"live-test-{uuid.uuid4().hex}"
    try:
        health = await repo.check()
        assert health.ok, health.detail
        assert health.ttl_enabled is True

        created = await repo.create_session(Session(owner_id=owner, created_at=AT, updated_at=AT))
        assert created.etag and created.ttl == settings.session_retention_days * 86400

        got = await repo.get_session(owner, created.id)
        assert got == created
        assert await repo.get_session("someone-else", created.id) is None

        replaced = await repo.replace_session(created.model_copy(update={"phase": Phase.FIND}))
        assert replaced.etag != created.etag
        with pytest.raises(ConflictError):
            await repo.replace_session(created.model_copy(update={"phase": Phase.MEASURE}))

        [summary] = await repo.list_sessions(owner)
        assert summary.id == created.id and summary.phase is Phase.FIND and summary.message_count == 0

        assert await repo.delete_session(owner, created.id) is True
        assert await repo.delete_session(owner, created.id) is False
    finally:
        await repo.delete_owner_data(owner)
        await repo.close()
