"""Wire models of the workspace API: the session list, the read-only session view and the conversation (spec 21 §4.2).

Why: the specialist's screens read every expert's sessions, so what they receive is a contract of
its own, narrower than the stored session: no owner id, no display name, no document text, and
messages only on the conversation route. Step-grid cells are display text built by the server, so
the screen never formats a stored value and shows exactly what the report shows.
What: `ReviewRowOut`, `ReviewCountsOut`, `ReviewListOut` (the list), `SummaryOut`, `GridCellOut`,
`GridRowOut`, `StepGridOut`, `DocumentMetaOut`, `ReviewSessionOut` (the view, with the
`DiscoveryReport` of a finished session) and `ConversationOut`, all camelCase through `WireModel`.
Must not: hold logic, or grow a field for messages, document text, `ownerId` or `displayName`
outside `ConversationOut` (AC-21.11). Spec 21 §4.2; AC-21.19.
"""

from __future__ import annotations

from app.models.process_discovery_schemas import Phase, SessionStatus, WireModel
from app.models.process_discovery_wire import DiscoveryReport, MessageOut


class ReviewRowOut(WireModel):
    id: str
    created_at: str
    updated_at: str
    process_name: str | None
    department: str | None
    cluster_code: str | None
    cluster_name: str | None
    region: str | None
    status: SessionStatus
    phase: Phase
    fields_filled: int
    fields_total: int
    steps: int
    message_count: int
    document_count: int


class ReviewCountsOut(WireModel):
    total: int = 0
    active: int = 0
    finished: int = 0
    no_candidate: int = 0


class ReviewListOut(WireModel):
    counts: ReviewCountsOut
    rows: list[ReviewRowOut]
    matching: int
    truncated: bool


class SummaryOut(WireModel):
    department: str | None
    function: str | None
    region: str | None
    process_name: str | None
    cluster_name: str | None
    status: SessionStatus
    phase: Phase
    fields_filled: int
    fields_total: int
    steps_started: int
    steps_expected: int
    completeness: float  # the score value, 0 to 1 (the screen shows it as a percent)
    filled_points: int
    total_points: int
    message_count: int
    document_count: int


class GridCellOut(WireModel):
    value: str  # display text built by the server ("—", "— (skipped)", "(proposed, not confirmed)")
    source: str | None
    status: str | None


class GridRowOut(WireModel):
    key: str
    id: str
    label: str
    cells: list[GridCellOut]  # one cell per step


class StepGridOut(WireModel):
    step_names: list[str]
    rows: list[GridRowOut]


class DocumentMetaOut(WireModel):
    name: str
    kind: str
    bytes: int
    uploaded_at: str
    outcome: str


class ReviewSessionOut(WireModel):
    id: str
    etag: str
    summary: SummaryOut
    steps: StepGridOut
    raw_steps: StepGridOut | None
    documents: list[DocumentMetaOut]
    report: DiscoveryReport | None


class ConversationOut(WireModel):
    session_id: str
    messages: list[MessageOut]
