"""The store factory and its place in the app lifespan (spec 15 §3.6, §4; AC-15.20 to AC-15.23).

Why: the store must be built once, from checked settings, with Azure identity and never a key, and
closed on shutdown; a missing container must be loud in the logs without stopping start-up, so the
health probe can still answer. Nothing may be built at import time.
What: `create_repository` picks the implementation from `STORE`; the Cosmos branch uses
`DefaultAzureCredential` (client constructor recorded, no network); importing the store builds no
client or credential (subprocess check); the lifespan puts the store on `app.state.store`, logs an
unhealthy `check()` as an error, and closes it; `get_store` returns it.
Must not: reach Azure; the live test does that.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from azure.identity.aio import DefaultAzureCredential
from fastapi import Request
from fastapi.testclient import TestClient

import app.main as main_module
import app.services.store.cosmos as cosmos_module
from app.core.settings import Settings
from app.main import create_app
from app.services.store import create_repository, get_store
from app.services.store.cosmos import CosmosRepository
from app.services.store.memory import MemoryRepository
from app.services.store.repository import StoreHealth

BACKEND = Path(__file__).resolve().parents[3]


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


# --- AC-15.20 ----------------------------------------------------------------------------------------


async def test_ac_15_20_memory_store_for_store_memory():
    repo = await create_repository(settings(store="memory", session_retention_days=30))
    assert isinstance(repo, MemoryRepository)
    await repo.close()


async def test_ac_15_20_cosmos_store_uses_default_azure_credential_and_no_key(monkeypatch: pytest.MonkeyPatch):
    built: dict[str, Any] = {}

    class RecordingClient:
        def __init__(self, url: str, *args: Any, **kwargs: Any) -> None:
            built.update(url=url, args=args, kwargs=kwargs)
            self.closed = False

        def get_database_client(self, name: str) -> Any:
            built["database"] = name
            return SimpleNamespace(get_container_client=lambda c: built.setdefault("container", c) and object())

        async def close(self) -> None:
            built["closed"] = True

    monkeypatch.setattr(cosmos_module, "CosmosClient", RecordingClient)
    repo = await create_repository(
        settings(
            store="cosmos",
            cosmos_endpoint="https://acct.documents.azure.com:443/",
            cosmos_database="d",
            cosmos_container="c",
        )
    )
    try:
        assert isinstance(repo, CosmosRepository)
        assert built["url"] == "https://acct.documents.azure.com:443/"
        assert built["args"] == ()
        assert isinstance(built["kwargs"].get("credential"), DefaultAzureCredential)
        assert set(built["kwargs"]) == {"credential"}
        assert (built["database"], built["container"]) == ("d", "c")
    finally:
        await repo.close()
    assert built["closed"] is True


def test_session_retention_days_setting_range():
    assert settings().session_retention_days == 90
    with pytest.raises(ValueError):
        settings(session_retention_days=0)
    with pytest.raises(ValueError):
        settings(session_retention_days=366)


# --- AC-15.21 ----------------------------------------------------------------------------------------

_SCRIPT = r"""
import azure.cosmos.aio as cosmos_aio, azure.identity.aio as identity_aio
def refuse(*a, **k):
    raise RuntimeError("client built at import time")
cosmos_aio.CosmosClient.__init__ = refuse
identity_aio.DefaultAzureCredential.__init__ = refuse
import app.services.store, app.services.store.repository, app.services.store.memory, app.services.store.cosmos
import app.main
print("ok")
"""


def test_ac_15_21_importing_the_store_builds_no_client():
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        cwd=BACKEND,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")


# --- AC-15.22 and AC-15.23 ------------------------------------------------------------------------------


class SpyRepository(MemoryRepository):
    def __init__(self, health: StoreHealth) -> None:
        super().__init__(retention_days=90)
        self.health = health
        self.closed = 0

    async def check(self) -> StoreHealth:
        return self.health

    async def close(self) -> None:
        self.closed += 1


def test_ac_15_22_lifespan_opens_once_sets_state_and_closes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    opened: list[SpyRepository] = []

    async def fake_create(s: Settings) -> SpyRepository:
        opened.append(SpyRepository(StoreHealth(ok=True, ttl_enabled=True, detail="ok")))
        return opened[-1]

    monkeypatch.setattr(main_module, "create_repository", fake_create)
    app = create_app(settings(frontend_dist=str(tmp_path)))
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert len(opened) == 1 and app.state.store is opened[0]
        request = cast(Request, SimpleNamespace(app=app))
        assert get_store(request) is opened[0]
        assert opened[0].closed == 0
    assert opened[0].closed == 1


def test_ac_15_22_lifespan_with_the_real_memory_factory(tmp_path: Path):
    app = create_app(settings(store="memory", frontend_dist=str(tmp_path)))
    with TestClient(app):
        assert isinstance(app.state.store, MemoryRepository)


def test_ac_15_23_unhealthy_store_is_logged_and_health_still_answers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    spy = SpyRepository(StoreHealth(ok=False, ttl_enabled=None, detail="container not found"))

    async def fake_create(s: Settings) -> SpyRepository:
        return spy

    monkeypatch.setattr(main_module, "create_repository", fake_create)
    # create_app replaces the root handlers, which would drop caplog's handler.
    monkeypatch.setattr(main_module, "configure_logging", lambda level: None)
    app = create_app(settings(frontend_dist=str(tmp_path)))
    with caplog.at_level(logging.INFO, logger="app"), TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
    errors = [r for r in caplog.records if r.levelno == logging.ERROR and r.getMessage() == "store_unhealthy"]
    assert errors and errors[0].detail == "container not found"  # pyright: ignore[reportAttributeAccessIssue]
    assert spy.closed == 1
