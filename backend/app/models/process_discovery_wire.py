"""Wire models of the interview API: what the expert's browser sends and receives (spec 15 part 2 §3.4, spec 16 §3.2).

Why: the stored session carries internals the client must never see (counters, the last
question, the owner id, the etag, `__meta` sidecars), and the client replaces its whole state
with every response, so the response shape is a contract of its own, separate from storage.
What: request bodies (`CreateSessionIn`, `MessageIn`, `ConfirmIn`, `ClusterIn`, `ProposalKeysIn`,
`LoginIn`) and responses (`SessionOut`, `TurnOut`, `SessionSummaryOut`, `IdeaOut`, `DocumentOut`,
`DocumentReportOut`, `DocumentUploadOut`, the list wrappers, `DeletedOut`, `ConfigOut`,
`HealthOut`, `LoginOut`, `ErrorOut`), all camelCase through `WireModel`, and the discovery report
(`DiscoveryReport` and its part models, spec 20 §4), which lives here so that `artifacts/` can build
it and `export/` can print it without one peer importing the other.
Must not: hold logic or read the store; the service builds `SessionOut` (it owns the views). A
document is listed by its counts only: its text and its step-list quotes never go on the wire
(spec 17 §3.13, F-23.3).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from app.models.process_discovery_schemas import (
    ClusterOut,
    FieldStatus,
    FieldView,
    FinishState,
    Phase,
    ProcessDiagram,
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


class ProposalKeysIn(WireModel):
    """The proposals the expert confirms (✓) or rejects (✎), by field or step cell key (spec 13 §3.6)."""

    keys: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(min_length=1, max_length=200)


class LoginIn(WireModel):
    code: str = Field(default="", max_length=200)  # ignored when the workspace is open (spec 16 §3.2 item 5)
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


class DocumentOut(WireModel):
    """One uploaded document as the expert's panel lists it; `pending` = its values still waiting for ✓ / ✎."""

    id: str
    name: str
    kind: str
    bytes: int
    chars: int
    truncated: bool
    uploaded_at: str
    outcome: Literal["read", "failed"]
    proposals: int
    pending: int


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
    documents: list[DocumentOut] = Field(default_factory=list[DocumentOut])


class TallyOut(WireModel):
    fields: int = 0
    steps: int = 0
    cells: int = 0


class SkippedOut(WireModel):
    """A value the reading dropped: key and reason, never the value or the quote."""

    key: str
    reason: str
    items: int | None = None


class DocumentReportOut(WireModel):
    """What one upload produced (spec 17 §3.17): counts and the one sentence the expert is told (§3.12)."""

    document_id: str
    outcome: Literal["read", "failed"]
    reader: Literal["model", "bpmn"]
    document_role: str | None = None
    target_step: int | None = None
    target_source: Literal["document", "expert", "focus", "none"] = "none"
    from_image: bool = False
    truncated: bool
    offered: TallyOut
    kept: TallyOut
    dropped: int
    skipped: list[SkippedOut]
    step_list: int
    message: str
    #: Conflicts the reading recorded (spec 17 §3.21 item 6).
    conflicts: int = 0


class DocumentUploadOut(WireModel):
    """The upload response; `reply` is the agent's question about the file (spec 14 §3.16), also the last message."""

    session: SessionOut
    document: DocumentOut
    report: DocumentReportOut
    reply: MessageOut


class DocumentListOut(WireModel):
    documents: list[DocumentOut]


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


class IdeaSignalsOut(WireModel):
    """The expert's own words for the four steering signals of an idea (spec 14 §3.15)."""

    runs: str | None = None
    people: str | None = None
    time: str | None = None
    inputs: str | None = None


class IdeaOut(WireModel):
    id: str
    name: str
    words: str
    status: Literal["open", "started", "dismissed"]
    from_session_id: str
    started_session_id: str | None
    created_at: str
    signals: IdeaSignalsOut = Field(default_factory=IdeaSignalsOut)
    hours_per_year: float | None = None
    people: float | None = None
    data_score: float | None = None
    score: float | None = None
    rank: int | None = None
    recommended: bool = False


class IdeaListOut(WireModel):
    ideas: list[IdeaOut]


class DeletedOut(WireModel):
    sessions: int
    ideas: int


class DocumentLimitsOut(WireModel):
    allowed_types: list[str]
    max_files: int
    max_file_mb: float
    max_image_mb: float


class ConfigOut(WireModel):
    product_name: str
    regions: list[str]
    languages: list[str]
    documents: DocumentLimitsOut
    workspace_open: bool = False  # spec 16 AC-16.19


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


# --- the discovery report (spec 20 §3.3, §4) ----------------------------------------------------------
# Built by `artifacts/report.py` from the stored session, read by the screen (as JSON) and by
# `export/report_pdf.py`. Every string is display-ready: neither the client nor the PDF formats a value.

ReportNoteKind = Literal["missing", "failed", "empty", "simplified", "incomplete", "task", "one_off", "error"]


class ReportNote(WireModel):
    kind: ReportNoteKind
    text: str


class ReportPartBase(WireModel):
    number: int
    title: str
    note: ReportNote | None = None


class ReportField(WireModel):
    key: str
    label: str
    value: str
    status: FieldStatus | None = None
    source: str | None = None
    quote: str | None = None


class ReportCover(WireModel):
    product_name: str
    company_name: str
    process_name: str
    department: str
    cluster: str
    region: str
    owner: str
    date: str
    status: str


class TopOpportunity(WireModel):
    id: str
    title: str
    steps_label: str
    hours: str


class AtAGlancePart(ReportPartBase):
    hours: str = ""
    route_headline: str | None = None
    top: list[TopOpportunity] = Field(default_factory=list)
    prepare: list[str] = Field(default_factory=list)


class FieldsPart(ReportPartBase):
    fields: list[ReportField] = Field(default_factory=list)
    notes: list[ReportNote] = Field(default_factory=list)


class StepColumn(WireModel):
    number: int
    name: str
    cells: list[ReportField] = Field(default_factory=list)


class MapPart(ReportPartBase):
    diagram: ProcessDiagram | None = None
    process_name: str = ""
    caption: str | None = None
    systems: list[str] = Field(default_factory=list)
    columns: list[StepColumn] = Field(default_factory=list)
    row_labels: list[str] = Field(default_factory=list)


class StepRow(WireModel):
    number: int
    name: str
    hours: str
    fit: str | None = None
    fit_label: str
    route_id: str | None = None
    route_name: str
    route_reason: str = ""
    reason: str = ""
    evidence: str = ""
    evidence_label: str = ""


class StepsPart(ReportPartBase):
    rows: list[StepRow] = Field(default_factory=list)
    catalogue_note: str | None = None


class RouteItem(WireModel):
    number: int
    name: str
    hours: str = ""
    route_name: str = ""
    reason: str = ""


class RouteGroup(WireModel):
    key: str
    title: str
    items: list[RouteItem] = Field(default_factory=list)


class RoutePart(ReportPartBase):
    headline: str = ""
    groups: list[RouteGroup] = Field(default_factory=list)
    prepare: list[str] = Field(default_factory=list)
    catalogue_note: str | None = None


class ReportOpportunity(WireModel):
    id: str
    title: str
    steps_label: str
    type_label: str
    what_changes: str = ""
    how: str = ""
    prepare_first: str = ""
    impact: str
    impact_reason: str = ""
    feasibility: str
    feasibility_reason: str = ""
    evidence: str = ""
    evidence_label: str = ""
    review: str | None = None


class ReportStayHuman(WireModel):
    steps_label: str
    reason: str = ""
    evidence: str = ""


class AssessmentPart(ReportPartBase):
    summary: str = ""
    opportunities: list[ReportOpportunity] = Field(default_factory=list)
    stay_human: list[ReportStayHuman] = Field(default_factory=list)


class StepValueRow(WireModel):
    number: int
    name: str
    hours_per_run: str
    runs_per_year: str
    hours_per_year: str


class OpportunityValueRow(WireModel):
    id: str
    title: str
    steps_label: str
    step_hours: str


class TotalsRow(WireModel):
    hours: str


class PotentialPart(ReportPartBase):
    complete: bool = False
    steps: list[StepValueRow] = Field(default_factory=list)
    opportunities: list[OpportunityValueRow] = Field(default_factory=list)
    totals: TotalsRow = Field(default_factory=lambda: TotalsRow(hours="—"))
    formulas: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    parked_line: str = ""


class ReadinessRow(WireModel):
    key: str
    label: str
    question: str
    level: str
    level_label: str
    reason: str = ""
    to_prepare: str = ""
    note: str = ""


class ReadinessPart(ReportPartBase):
    dimensions: list[ReadinessRow] = Field(default_factory=list)
    footer: str = ""


class PathItem(WireModel):
    opportunity_id: str
    title: str
    steps_label: str
    step_hours: str


class PathGroup(WireModel):
    key: str
    title: str
    prepare_lines: list[str] = Field(default_factory=list)
    items: list[PathItem] = Field(default_factory=list)
    empty_text: str | None = None


class PathPart(ReportPartBase):
    groups: list[PathGroup] = Field(default_factory=list)


class DocumentRow(WireModel):
    name: str
    outcome: str


class GapsPart(ReportPartBase):
    fields: list[ReportField] = Field(default_factory=list)
    documents: list[DocumentRow] = Field(default_factory=list)
    closing_note: str = ""


class DiscoveryReport(WireModel):
    """The cover and the eleven parts, in order (F-16). No overall score or verdict, by design (AC-20.27)."""

    cover: ReportCover
    at_a_glance: AtAGlancePart
    process: FieldsPart
    measures: FieldsPart
    map: MapPart
    steps: StepsPart
    route: RoutePart
    assessment: AssessmentPart
    potential: PotentialPart
    readiness: ReadinessPart
    path: PathPart
    gaps: GapsPart
    generated_at: str

    def parts(self) -> list[ReportPartBase]:
        """The eleven parts in report order."""
        return [self.at_a_glance, self.process, self.measures, self.map, self.steps, self.route,
                self.assessment, self.potential, self.readiness, self.path, self.gaps]  # fmt: skip
