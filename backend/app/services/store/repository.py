"""The repository protocol, its result models and errors, and the rules both stores share (spec 15 §3).

Why: the engine must not care whether sessions live in Cosmos DB or in memory, and the two stores
must not drift apart: retention ttl, owner scoping, type checks, loading a stored document and
logging are the same rules in both, so they are written once here.
What: `SessionRepository` (the protocol the engine receives), `SessionSummary`, `DeletedCounts`,
`StoreHealth`, `StoredIdea` (an `Idea` that carries its etag), the errors, and
`DocumentRepository`, a base that implements the protocol on top of a few storage primitives
that `MemoryRepository` and `CosmosRepository` provide. Whole documents only, never a patch;
every replace needs the etag it was read with (AC-15.1 to AC-15.18, AC-15.24).
Must not: import Azure SDKs, read a clock, log message, profile or document text, or mutate the
models it is given.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Literal, Protocol

from pydantic import Field, ValidationError, field_validator

from app.core.logging import log_event
from app.models.process_discovery_schemas import Idea, Phase, Session, SessionStatus, StorageModel

logger = logging.getLogger(__name__)

SECONDS_PER_DAY = 86_400
SYSTEM_FIELDS = ("_rid", "_self", "_etag", "_attachments", "_ts")
DocType = Literal["session", "idea"]


# --- Errors ----------------------------------------------------------------------------------------


class StoreError(Exception):
    """Base of every store error."""


class ConflictError(StoreError):
    """The etag no longer matches (someone wrote first), the document is gone, or the id exists."""


class CorruptDocumentError(StoreError):
    """A stored document no longer validates. The message names the id, never the content."""


class StoreUnavailableError(StoreError):
    """Network, auth or throttling failure after the SDK's own retries."""


# --- Result models ---------------------------------------------------------------------------------


class SessionSummary(StorageModel):
    """One row of "My processes": no messages, no profile body."""

    id: str
    status: SessionStatus
    phase: Phase
    process_name: str | None = None
    cluster_code: str | None = None
    score: float = 0.0
    message_count: int = 0
    created_at: str
    updated_at: str
    report_status: str | None = None

    @field_validator("process_name", "cluster_code")
    @classmethod
    def _empty_is_none(cls, value: str | None) -> str | None:
        return value or None


class DeletedCounts(StorageModel):
    sessions: int
    ideas: int


class StoreHealth(StorageModel):
    ok: bool
    ttl_enabled: bool | None
    detail: str


class StoredIdea(Idea):
    """An `Idea` as read from the store: it carries the etag a replace needs (`Idea` has none, spec 12)."""

    etag: str | None = Field(default=None, exclude=True)


# --- Protocol ----------------------------------------------------------------------------------------


class SessionRepository(Protocol):
    async def create_session(self, session: Session) -> Session: ...
    async def get_session(self, owner_id: str, session_id: str) -> Session | None: ...
    async def replace_session(self, session: Session) -> Session: ...
    async def delete_session(self, owner_id: str, session_id: str) -> bool: ...
    async def list_sessions(self, owner_id: str) -> list[SessionSummary]: ...
    async def create_idea(self, idea: Idea) -> StoredIdea: ...
    async def get_idea(self, owner_id: str, idea_id: str) -> StoredIdea | None: ...
    async def replace_idea(self, idea: Idea) -> StoredIdea: ...
    async def delete_idea(self, owner_id: str, idea_id: str) -> bool: ...
    async def list_ideas(self, owner_id: str) -> list[StoredIdea]: ...
    async def delete_owner_data(self, owner_id: str) -> DeletedCounts: ...
    async def check(self) -> StoreHealth: ...
    async def close(self) -> None: ...


# --- Shared rules ------------------------------------------------------------------------------------


def owner_prefix(owner_id: str) -> str:
    """What logs carry instead of the owner key."""
    return owner_id[:8]


def _id_field(doc_type: DocType) -> str:
    return "sessionId" if doc_type == "session" else "ideaId"


def retention_ttl(model: Session | Idea, retention_days: int) -> int | None:
    """§3.3: unfinished sessions and open or dismissed ideas expire; the rest are kept."""
    if isinstance(model, Session):
        keep = model.status == SessionStatus.FINISHED
    else:
        keep = model.status == "started"
    return None if keep else retention_days * SECONDS_PER_DAY


def to_document(model: Session | Idea, retention_days: int) -> dict[str, Any]:
    """The whole document as stored: camelCase, no etag, ttl set by the retention rule or absent."""
    doc = model.model_dump(by_alias=True, mode="json")
    doc.pop("etag", None)
    ttl = retention_ttl(model, retention_days)
    if ttl is None:
        doc.pop("ttl", None)
    else:
        doc["ttl"] = ttl
    return doc


def _corrupt(doc_type: DocType, doc_id: str, owner_id: str) -> CorruptDocumentError:
    logger.error(
        "store_corrupt_document",
        extra={"docType": doc_type, _id_field(doc_type): doc_id, "owner": owner_prefix(owner_id)},
    )
    return CorruptDocumentError(f"stored {doc_type} {doc_id} no longer validates")


def load_session(doc: dict[str, Any], owner_id: str) -> Session:
    return _load(Session, "session", doc, owner_id)


def load_idea(doc: dict[str, Any], owner_id: str) -> StoredIdea:
    return _load(StoredIdea, "idea", doc, owner_id)


def _load[M: Session | StoredIdea](cls: type[M], doc_type: DocType, doc: dict[str, Any], owner_id: str) -> M:
    """§3.4: drop system fields, keep `_etag` as `etag`, validate strictly."""
    clean = {k: v for k, v in doc.items() if k not in SYSTEM_FIELDS}
    clean["etag"] = doc.get("_etag")
    try:
        return cls.model_validate(clean)
    except ValidationError:
        raise _corrupt(doc_type, str(doc.get("id")), owner_id) from None


# --- Base implementation ------------------------------------------------------------------------------


class DocumentRepository(ABC):
    """The protocol on top of storage primitives. Subclasses map their backend's errors to store errors."""

    def __init__(self, *, retention_days: int) -> None:
        self.retention_days = retention_days

    # Primitives. Documents are dicts as stored, with `_etag`. `_create` and `_replace` raise
    # `ConflictError`; reads of a missing document return None; `_delete` returns False.
    @abstractmethod
    async def _read(self, owner_id: str, doc_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    async def _create(self, doc: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    async def _replace(self, doc: dict[str, Any], etag: str) -> dict[str, Any]: ...

    @abstractmethod
    async def _delete(self, owner_id: str, doc_id: str) -> bool: ...

    @abstractmethod
    async def _session_summaries(self, owner_id: str) -> list[dict[str, Any]]:
        """Summary rows (camelCase keys of `SessionSummary`), newest `updatedAt` first."""

    @abstractmethod
    async def _ideas(self, owner_id: str) -> list[dict[str, Any]]:
        """Whole idea documents, newest `createdAt` first."""

    @abstractmethod
    async def _ids(self, owner_id: str) -> list[tuple[str, str]]:
        """(id, type) of every document in the owner's partition."""

    @abstractmethod
    async def check(self) -> StoreHealth: ...

    @abstractmethod
    async def close(self) -> None: ...

    # --- sessions ---

    async def create_session(self, session: Session) -> Session:
        stored = await self._create(to_document(session, self.retention_days))
        log_event(logger, "store_session_created", sessionId=session.id, owner=owner_prefix(session.owner_id))
        return load_session(stored, session.owner_id)

    async def get_session(self, owner_id: str, session_id: str) -> Session | None:
        doc = await self._read_typed(owner_id, session_id, "session")
        return load_session(doc, owner_id) if doc is not None else None

    async def replace_session(self, session: Session) -> Session:
        stored = await self._replace(to_document(session, self.retention_days), self._etag_of(session))
        log_event(logger, "store_session_replaced", sessionId=session.id, owner=owner_prefix(session.owner_id))
        return load_session(stored, session.owner_id)

    async def delete_session(self, owner_id: str, session_id: str) -> bool:
        return await self._delete_typed(owner_id, session_id, "session")

    async def list_sessions(self, owner_id: str) -> list[SessionSummary]:
        rows = await self._session_summaries(owner_id)
        summaries: list[SessionSummary] = []
        for row in rows:
            try:
                summaries.append(SessionSummary.model_validate(row))
            except ValidationError:
                raise _corrupt("session", str(row.get("id")), owner_id) from None
        return summaries

    # --- ideas ---

    async def create_idea(self, idea: Idea) -> StoredIdea:
        stored = await self._create(to_document(idea, self.retention_days))
        log_event(logger, "store_idea_created", ideaId=idea.id, owner=owner_prefix(idea.owner_id))
        return load_idea(stored, idea.owner_id)

    async def get_idea(self, owner_id: str, idea_id: str) -> StoredIdea | None:
        doc = await self._read_typed(owner_id, idea_id, "idea")
        return load_idea(doc, owner_id) if doc is not None else None

    async def replace_idea(self, idea: Idea) -> StoredIdea:
        stored = await self._replace(to_document(idea, self.retention_days), self._etag_of(idea))
        log_event(logger, "store_idea_replaced", ideaId=idea.id, owner=owner_prefix(idea.owner_id))
        return load_idea(stored, idea.owner_id)

    async def delete_idea(self, owner_id: str, idea_id: str) -> bool:
        return await self._delete_typed(owner_id, idea_id, "idea")

    async def list_ideas(self, owner_id: str) -> list[StoredIdea]:
        return [load_idea(doc, owner_id) for doc in await self._ideas(owner_id)]

    # --- delete my data ---

    async def delete_owner_data(self, owner_id: str) -> DeletedCounts:
        """F-23. Tries every document; if any delete failed, raises after the rest are gone."""
        counts = {"session": 0, "idea": 0}
        failures = 0
        for doc_id, doc_type in await self._ids(owner_id):
            try:
                if await self._delete(owner_id, doc_id) and doc_type in counts:
                    counts[doc_type] += 1
            except StoreUnavailableError:
                failures += 1
        log_event(
            logger,
            "store_owner_data_deleted",
            owner=owner_prefix(owner_id),
            sessions=counts["session"],
            ideas=counts["idea"],
            failures=failures,
        )
        if failures:
            raise StoreUnavailableError(f"{failures} documents could not be deleted; retry")
        return DeletedCounts(sessions=counts["session"], ideas=counts["idea"])

    # --- helpers ---

    @staticmethod
    def _etag_of(model: Session | Idea) -> str:
        etag = getattr(model, "etag", None)
        if not etag:
            raise ValueError("replace needs the etag the document was read with; a blind overwrite is not allowed")
        return etag

    async def _read_typed(self, owner_id: str, doc_id: str, doc_type: DocType) -> dict[str, Any] | None:
        """Read within the owner's partition; another type or another owner is "not found"."""
        doc = await self._read(owner_id, doc_id)
        if doc is None or doc.get("type") != doc_type:
            return None
        if doc.get("ownerId") != owner_id:  # defence in depth: the partition already scopes it
            logger.warning("store_owner_mismatch", extra={_id_field(doc_type): doc_id, "owner": owner_prefix(owner_id)})
            return None
        return doc

    async def _delete_typed(self, owner_id: str, doc_id: str, doc_type: DocType) -> bool:
        if await self._read_typed(owner_id, doc_id, doc_type) is None:
            return False
        deleted = await self._delete(owner_id, doc_id)
        if deleted:
            log_event(
                logger, f"store_{doc_type}_deleted", **{_id_field(doc_type): doc_id}, owner=owner_prefix(owner_id)
            )
        return deleted
