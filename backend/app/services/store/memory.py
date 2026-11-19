"""The in-memory store for tests and local runs (spec 15 §3.6, `STORE=memory`).

Why: tests and local runs need a store with the same promises as Cosmos (whole documents, a new
etag on every write, owner scoping, `If-Match` conflicts) without an Azure account. Keeping JSON
text, not model objects, means a stored document is serialised exactly as Cosmos would hold it
and nothing returned can alias what is stored.
What: `MemoryRepository`, the storage primitives of `DocumentRepository` over a dict keyed by
`(ownerId, id)`. The ttl is stored as a field; expiry is not simulated. Passes the shared contract
(AC-15.1 to AC-15.18, AC-15.25).
Must not: hold state across instances, simulate time, or be used in the demo stage (settings
refuse `STORE=memory` there).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.services.store.repository import ConflictError, DocumentRepository, StoreHealth


def _summary(doc: dict[str, Any]) -> dict[str, Any]:
    """The same fields the Cosmos projection selects (see `cosmos.SUMMARY_QUERY`)."""
    process = (doc.get("profile") or {}).get("process") or {}
    return {
        "id": doc["id"],
        "status": doc.get("status"),
        "phase": doc.get("phase"),
        "processName": process.get("name"),
        "clusterCode": (process.get("cluster") or {}).get("code"),
        "score": (doc.get("score") or {}).get("value"),
        "messageCount": len(doc.get("messages") or []),
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt"),
        "reportStatus": (doc.get("report") or {}).get("status"),
    }


class MemoryRepository(DocumentRepository):
    """Documents as JSON text in a dict keyed by `(ownerId, id)`."""

    def __init__(self, *, retention_days: int = 90) -> None:
        super().__init__(retention_days=retention_days)
        self._documents: dict[tuple[str, str], str] = {}

    def _store(self, doc: dict[str, Any]) -> dict[str, Any]:
        stored = {**doc, "_etag": uuid.uuid4().hex}
        self._documents[(doc["ownerId"], doc["id"])] = json.dumps(stored)
        return json.loads(self._documents[(doc["ownerId"], doc["id"])])

    def _partition(self, owner_id: str) -> list[dict[str, Any]]:
        return [json.loads(text) for (owner, _), text in self._documents.items() if owner == owner_id]

    async def _read(self, owner_id: str, doc_id: str) -> dict[str, Any] | None:
        text = self._documents.get((owner_id, doc_id))
        return json.loads(text) if text is not None else None

    async def _create(self, doc: dict[str, Any]) -> dict[str, Any]:
        if (doc["ownerId"], doc["id"]) in self._documents:
            raise ConflictError(f"document {doc['id']} already exists")
        return self._store(doc)

    async def _replace(self, doc: dict[str, Any], etag: str) -> dict[str, Any]:
        current = await self._read(doc["ownerId"], doc["id"])
        if current is None or current.get("_etag") != etag:
            raise ConflictError(f"document {doc['id']} changed since it was read")
        return self._store(doc)

    async def _delete(self, owner_id: str, doc_id: str) -> bool:
        return self._documents.pop((owner_id, doc_id), None) is not None

    async def _session_summaries(self, owner_id: str) -> list[dict[str, Any]]:
        rows = [_summary(d) for d in self._partition(owner_id) if d.get("type") == "session"]
        return sorted(rows, key=lambda r: str(r["updatedAt"]), reverse=True)

    async def _ideas(self, owner_id: str) -> list[dict[str, Any]]:
        docs = [d for d in self._partition(owner_id) if d.get("type") == "idea"]
        return sorted(docs, key=lambda d: str(d.get("createdAt")), reverse=True)

    async def _ids(self, owner_id: str) -> list[tuple[str, str]]:
        return [(d["id"], str(d.get("type"))) for d in self._partition(owner_id)]

    async def check(self) -> StoreHealth:
        return StoreHealth(ok=True, ttl_enabled=None, detail="memory store (ttl not simulated)")

    async def close(self) -> None:
        return None
