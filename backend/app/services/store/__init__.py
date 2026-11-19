"""Persistence behind one repository protocol, with a Cosmos DB implementation and an in-memory one for tests and local runs.

One document per session, written whole with optimistic concurrency (spec 15). The engine depends
only on the protocol, never on Cosmos directly. This module adds the factory the app lifespan
calls (`create_repository`, AC-15.20) and the `get_store` dependency (AC-15.22); it builds nothing
at import time (AC-15.21).
"""

from __future__ import annotations

from fastapi import Request

from app.core.settings import Settings
from app.services.store.cosmos import open_cosmos
from app.services.store.memory import MemoryRepository
from app.services.store.repository import SessionRepository


async def create_repository(settings: Settings) -> SessionRepository:
    """The store named by `STORE`. Cosmos uses `DefaultAzureCredential`, never a key."""
    if settings.store == "cosmos":
        return await open_cosmos(settings)
    return MemoryRepository(retention_days=settings.session_retention_days)


def get_store(request: Request) -> SessionRepository:
    """FastAPI dependency: the store opened in the lifespan."""
    return request.app.state.store
