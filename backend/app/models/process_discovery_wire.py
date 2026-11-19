"""Wire models of the interview API: what the expert's browser sends and receives (spec 15 part 2 §3.4, spec 16 §3.2).

Why: the stored session carries internals the client must never see (counters, the last
question, the owner id, the etag, `__meta` sidecars), and the client replaces its whole state
with every response, so the response shape is a contract of its own, separate from storage.
What: request bodies (`CreateSessionIn`, `MessageIn`, `ConfirmIn`, `ClusterIn`, `LoginIn`) and
responses (`SessionOut`, `TurnOut`, `SessionSummaryOut`, `IdeaOut`, the list wrappers,
`DeletedOut`, `ConfigOut`, `HealthOut`, `LoginOut`, `ErrorOut`), all camelCase through `WireModel`.
Must not: hold logic or read the store; the service builds `SessionOut` (it owns the views).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from app.models.process_discovery_schemas import (
    ClusterOut,
    FieldView,
    FinishState,
    Phase,
    SessionStatus,
    WireModel,
)

MAX_MESSAGE_CHARS = 16_000

# --- requests ---------------------------------------------------------------------------------------


class CreateSessionIn(WireModel):
    display_name: str | None = Field(default=None, max_length=40)
    from_idea_id: str | None = Field(default=None, max_length=64)


class MessageIn(WireModel):
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("the message is empty")
        return value


class ConfirmIn(WireModel):
    target: Literal["substeps", "roles", "tools"]


class ClusterIn(WireModel):
    code: str = Field(min_length=1, max_length=8)


class LoginIn(WireModel):
    code: str = Field(max_length=200)
    name: str = Field(min_length=1, max_length=40)


# --- responses --------------------------------------------------------------------------------------


class MessageOut(WireModel):
    id: str
    role: Literal["expert", "agent"]
    text: str
    at: str


class ScoreOut(WireModel):
    value: float
    filled_points: int
    total_points: int


class ScopeOut(WireModel):
    verdict: str
    widened: bool


class SessionOut(WireModel):
    id: str
    status: SessionStatus
    phase: Phase
    display_name: str | None
    created_at: str
    updated_at: str
    finished_at: str | None
    messages: list[MessageOut]
    profile: dict[str, Any]
    field_views: list[FieldView]
    score: ScoreOut
    finish: FinishState
    scope: ScopeOut | None
    cluster_proposal: ClusterOut | None
    report_status: Literal["mapped", "validated"] | None


class TurnOut(WireModel):
    reply: MessageOut
    session: SessionOut
    ideas_added: int


class SessionSummaryOut(WireModel):
    id: str
    status: SessionStatus
    phase: Phase
    process_name: str | None
    cluster_code: str | None
    score: float
    message_count: int
    created_at: str
    updated_at: str
    report_status: str | None


class SessionListOut(WireModel):
    sessions: list[SessionSummaryOut]


class IdeaOut(WireModel):
    id: str
    name: str
    words: str
    status: Literal["open", "started", "dismissed"]
    from_session_id: str
    started_session_id: str | None
    created_at: str


class IdeaListOut(WireModel):
    ideas: list[IdeaOut]


class DeletedOut(WireModel):
    sessions: int
    ideas: int


class DocumentLimitsOut(WireModel):
    allowed_types: list[str]
    max_files: int
    max_file_mb: float


class ConfigOut(WireModel):
    product_name: str
    regions: list[str]
    languages: list[str]
    documents: DocumentLimitsOut


class StoreHealthOut(WireModel):
    ok: bool
    ttl_enabled: bool | None


class HealthOut(WireModel):
    status: str
    stage: str
    version: str
    store: StoreHealthOut


class LoginOut(WireModel):
    token: str
    role: Literal["specialist", "engineer"]
    name: str
    expires_at: str


class ErrorOut(WireModel):
    code: str
    message: str
    reason: str | None = None
