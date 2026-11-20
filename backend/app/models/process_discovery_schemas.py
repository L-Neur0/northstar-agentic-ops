"""Pydantic models for the session and idea documents and the shared wire models (spec 12 §3.11).

Why: the profile is stored, sent and graded, and those three views must agree. The profile models
mirror the field registry one to one (a parity test enforces it), so a key the registry does not
know fails loudly in tests instead of disappearing on the next save, and an out-of-range step
count can never make a session unloadable.
What: three bases (`ProfileModel` keeps registry keys; `StorageModel` and `WireModel` use camelCase
aliases), the enums, the profile with its rows and sidecars (`__meta`, `__skipped`), the session and
idea documents (with the steering state and idea signals of spec 14 §3.15), the assessment
containers that specs 18, 19, 20, 21, 23 and 26 fill, and the shared wire models. Every dump uses
`by_alias=True`. Every field added after the first stored session has a default, so a document
saved before the addition still loads; the money fields parked by spec 19 (R5) are typed `None`.
Must not: hold rules of "answered" (that is `domain.field_spec`), read a clock (times are passed
in), or restate a limit or a total (they are imported from the registry).
Tests: AC-12.25, AC-12.28, AC-12.39 to AC-12.43; the amendments in `test_contract_amendments.py`
(spec 14 §3.15, spec 18 §4.4, spec 19 §4.3, spec 26 §4.2, AC-19.39).
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer, model_validator
from pydantic.alias_generators import to_camel

from app.services.process_discovery.domain.field_spec import (
    MAX_STEPS,
    MIN_STEPS,
    PROCESS_POINTS,
    REJECTED_COUNT_KEY,
    SOURCE_DOCUMENT,
    SOURCE_SPECIALIST,
)

MAX_STEERING_CANDIDATES = 5  # candidates kept per session while steering (spec 14 §3.15 item 1)

# --- Bases ----------------------------------------------------------------------------------------


class ProfileModel(BaseModel):
    """The profile and its parts: registry keys, the same in storage and on the wire."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class StorageModel(BaseModel):
    """Stored documents and everything in them except the profile content: camelCase keys."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class WireModel(BaseModel):
    """API requests and responses: camelCase keys, unknown keys ignored."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


# --- Enums ----------------------------------------------------------------------------------------


class Phase(StrEnum):
    CONTEXT = "context"
    FIND = "find"
    BOUNDARIES = "boundaries"
    MEASURE = "measure"
    STEP_COUNT = "step_count"
    STEPS = "steps"
    CONFIRM = "confirm"
    REVIEW = "review"
    FINISHED = "finished"
    NO_CANDIDATE = "no_candidate"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    FINISHED = "finished"
    NO_CANDIDATE = "no_candidate"


class MessageRole(StrEnum):
    EXPERT = "expert"
    AGENT = "agent"


class FieldStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INVALID = "invalid"
    PROPOSED = "proposed"
    SKIPPED = "skipped"
    EMPTY = "empty"
    DEFERRED = "deferred"
    GIVEN_UP = "given_up"


class FinishBlock(StrEnum):
    """Why *Finish* is closed, in the order spec 13 checks them."""

    BELOW_GATE = "below_gate"
    SUBSTEPS_INCOMPLETE = "substeps_incomplete"
    ROLES_NOT_CONFIRMED = "roles_not_confirmed"
    TOOLS_NOT_CONFIRMED = "tools_not_confirmed"


class OpportunityType(StrEnum):
    """The kinds of change; `rates.yaml` uses the same keys."""

    ELIMINATE = "eliminate"
    STANDARDISE = "standardise"
    WORKFLOW = "workflow"
    INTEGRATION = "integration"
    DOCUMENT_AI = "document_ai"
    AI_ASSISTANT = "ai_assistant"
    AI_AGENT = "ai_agent"
    RPA = "rpa"


class Grade(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# --- Provenance -----------------------------------------------------------------------------------


class FieldMeta(StorageModel):
    """Who wrote a field and whether it is confirmed (§3.6). JSON keys: source, status, documentId, quote, by, at.

    `replaces` (spec 17 Q5, AC-17.62): on a document proposal that completes a partly answered field,
    the value and meta it replaced, `{"value": ..., "meta": {...} | None}`, restored exactly on a no.
    """

    source: Literal["expert", "document", "specialist"]
    status: Literal["proposed", "confirmed"]
    document_id: str | None = None
    quote: str | None = None
    by: str | None = None
    at: str
    replaces: dict[str, Any] | None = None

    @model_serializer(mode="wrap")
    def _drop_empty_replaces(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """`replaces` is stored only when present, so every other meta keeps its six keys."""
        data: dict[str, Any] = handler(self)
        if data.get("replaces") is None:
            data.pop("replaces", None)
        return data

    @model_validator(mode="after")
    def _rules(self) -> FieldMeta:
        if self.source == SOURCE_DOCUMENT and not (self.document_id and self.quote):
            raise ValueError("a document value needs documentId and quote")
        if self.status == "proposed" and not self.quote:
            raise ValueError("a proposed value needs a quote")
        if self.source == SOURCE_SPECIALIST:
            if not self.by:
                raise ValueError("a specialist value needs by")
            if self.status == "proposed":
                raise ValueError("a specialist value is never proposed")
        return self


# --- Profile ----------------------------------------------------------------------------------------


class NoneRow(ProfileModel):
    """`{"none": true}`: asked, and the answer is none."""

    none: Literal[True]


class RoleRow(ProfileModel):
    role: str = Field(min_length=1)
    contribution: str = ""


class ApprovalRow(ProfileModel):
    approver_role: str = Field(min_length=1)
    waiting_time: str = ""


class ExceptionRow(ProfileModel):
    description: str = Field(min_length=1)
    loops_back_to: int | None = Field(default=None, ge=1)


class SensitiveRow(ProfileModel):
    item: str = Field(min_length=1)
    detail: str = ""


class ClusterRef(ProfileModel):
    code: str = ""
    name: str = ""
    decided_by: str = ""


class Volume(ProfileModel):
    count: int | None = Field(default=None, ge=0)
    period: str = ""
    raw: str = ""


class ProcessOwner(ProfileModel):
    role: str = ""
    none_identified: bool = False


class Baseline(ProfileModel):
    value: str = ""
    unit: str = ""
    qualitative: str = ""
    estimated: bool = False


class Target(ProfileModel):
    value: str = ""
    unit: str = ""


class Variation(ProfileModel):
    same: str = ""
    differences: str = ""


class StepData(ProfileModel):
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)


class StepEffort(ProfileModel):
    duration: str = ""
    frequency: str = ""


class Step(ProfileModel):
    """One main step (S01–S12) with its cell provenance and skipped cells."""

    name: str = ""
    goal: str = ""
    activities: list[str] = Field(default_factory=list)
    roles: list[NoneRow | RoleRow] = Field(default_factory=list)
    owner: str = ""
    systems: list[str] = Field(default_factory=list)
    data: StepData = Field(default_factory=StepData)
    effort: StepEffort = Field(default_factory=StepEffort)
    pain_points: list[str] = Field(default_factory=list)
    approvals: list[NoneRow | ApprovalRow] = Field(default_factory=list)
    exceptions: list[NoneRow | ExceptionRow] = Field(default_factory=list)
    handover: str = ""
    meta: dict[str, FieldMeta] = Field(default_factory=dict, alias="__meta")
    skipped: list[str] = Field(default_factory=list, alias="__skipped")


class Process(ProfileModel):
    """Process fields P04–P16, the steps, the roll-ups and the flags."""

    name: str = ""
    cluster: ClusterRef = Field(default_factory=ClusterRef)
    trigger: str = ""
    end_result: str = ""
    value_at_end: str = ""
    business_pain: str = ""
    volume: Volume = Field(default_factory=Volume)
    process_owner: ProcessOwner = Field(default_factory=ProcessOwner)
    baseline_metric: Baseline = Field(default_factory=Baseline)
    target_metric: Target = Field(default_factory=Target)
    variation: Variation = Field(default_factory=Variation)
    sensitive_data: list[NoneRow | SensitiveRow] = Field(default_factory=list)
    substep_count: int | None = None
    substep_count_rejected: int | None = None
    substeps: list[Step] = Field(default_factory=list, max_length=MAX_STEPS)
    all_roles: list[str] = Field(default_factory=list)
    all_tools: list[str] = Field(default_factory=list)
    substeps_complete: bool = False
    roles_confirmed: bool = False
    tools_confirmed: bool = False

    @model_validator(mode="before")
    @classmethod
    def _park_out_of_range_count(cls, data: Any) -> Any:
        """A count outside 2–6 moves to `substep_count_rejected`; never raises (§3.11 rule 2)."""
        if isinstance(data, dict):
            count = data.get("substep_count")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            if isinstance(count, int) and not isinstance(count, bool) and not MIN_STEPS <= count <= MAX_STEPS:
                data = {**data, "substep_count": None, REJECTED_COUNT_KEY: count}  # pyright: ignore[reportUnknownVariableType]
        return data  # pyright: ignore[reportUnknownVariableType]


class Profile(ProfileModel):
    """The whole profile, as stored and as sent: registry keys plus `__meta`."""

    department: str = ""
    user_function: str = ""
    region: str = ""
    process: Process = Field(default_factory=Process)
    meta: dict[str, FieldMeta] = Field(default_factory=dict, alias="__meta")


# --- Session parts ----------------------------------------------------------------------------------


class Message(StorageModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: MessageRole
    text: str
    at: str


class Score(StorageModel):
    value: float = Field(default=0.0, ge=0, le=1)
    filled_points: int = 0
    total_points: int = PROCESS_POINTS


class Counters(StorageModel):
    field_asks: dict[str, int] = Field(default_factory=dict)
    cell_asks: dict[str, int] = Field(default_factory=dict)
    find_turns: int = 0
    widening_count: int = 0
    confirm_turns: int = 0


class ScopeVerdict(StorageModel):
    """The shape `domain.scope.build_scope_verdict` returns."""

    verdict: Literal["process", "borderline", "task"]
    score: int = Field(ge=0, le=5)
    signals: dict[str, bool]
    reasoning: str = ""


class ScopeState(StorageModel):
    verdict: ScopeVerdict | None = None
    scoped_for: str = ""
    awaiting_widening: bool = False
    widening_asked: bool = False
    overridden: bool = False


class Placement(StorageModel):
    """The shape `domain.scope.build_placement` returns."""

    code: str
    confidence: float
    raw_confidence: float
    runner_up: str
    runner_up_confidence: float
    rationale: str = ""
    ambiguous: bool = False
    source: Literal["model", "keyword"] = "model"


class PlacementState(StorageModel):
    proposal: Placement | None = None
    placed_for: str = ""
    rejected: bool = False


class LastQuestion(StorageModel):
    """What the last question asked about, so code can read a plain yes (spec 14)."""

    focus: list[str] = Field(default_factory=list)
    proposals: list[str] = Field(default_factory=list)
    confirm: Literal["cluster", "roles", "systems", "recommendation"] | None = None


class StepListItem(StorageModel):
    """One step name read from a document with more than six steps, kept for grouping (spec 17)."""

    name: str
    quote: str


class DocumentRecord(StorageModel):
    id: str
    name: str
    kind: Literal["pdf", "docx", "xlsx", "pptx", "csv", "txt", "md", "eml", "bpmn", "png", "jpeg"]
    bytes: int = Field(ge=0)
    chars: int = Field(ge=0)
    truncated: bool = False
    text: str = ""
    uploaded_at: str
    outcome: Literal["read", "failed"]  # a refused upload is never stored (spec 17)
    proposals: int = 0
    step_list: list[StepListItem] = Field(default_factory=list)


class CandidateSignals(StorageModel):
    """The expert's own words for the four steering signals of one candidate (spec 14 §3.15 item 3)."""

    runs: str | None = None
    people: str | None = None
    time: str | None = None
    inputs: str | None = None


class SteeringCandidate(StorageModel):
    """One candidate process heard in `find`, with the numbers code read from its signals (§3.15 item 1)."""

    id: str = Field(pattern=r"^c[1-5]$")
    name: str
    words: str = ""
    signals: CandidateSignals = Field(default_factory=CandidateSignals)
    runs_per_year: float | None = None
    hours_per_year: float | None = None
    people: float | None = None
    data_score: float | None = Field(default=None, ge=0, le=1)
    score: float | None = Field(default=None, ge=0, le=1)
    rank: int | None = Field(default=None, ge=1)


class SteeringState(StorageModel):
    """Steering toward the candidate with the most value and the readiest data (spec 14 §3.15)."""

    status: Literal["off", "collecting", "ranked", "chosen"] = "off"
    candidates: list[SteeringCandidate] = Field(default_factory=list, max_length=MAX_STEERING_CANDIDATES)
    questions: int = Field(default=0, ge=0)
    recommend_asks: int = Field(default=0, ge=0)
    recommended_id: str | None = None
    declined: bool = False


class Cost(StorageModel):
    tokens_in: int = 0
    tokens_out: int = 0
    euros: float = 0.0


# --- Assessment containers (specs 20, 21 may add fields, never rename) -------------------------------

EvidenceSource = Literal["expert", "document", "specialist"]

# Legal BPMN markers per node type; the first is the default (spec 18 §3.7 item 3).
DIAGRAM_MARKERS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "start": ("none", "message", "timer", "conditional", "signal"),
    "task": ("none", "user", "manual", "service", "send", "receive", "script", "business_rule"),
    "gateway": ("exclusive", "parallel", "inclusive", "event_based"),
    "end": ("none", "message", "terminate", "error"),
}


class Opportunity(StorageModel):
    id: str
    title: str
    substeps: list[int] = Field(default_factory=list)
    type: OpportunityType
    what_changes: str = ""
    how: str = ""
    prepare_first: str = ""
    impact: Grade
    impact_reason: str = ""
    feasibility: Grade
    feasibility_reason: str = ""
    evidence: str = ""
    saving_share: float = Field(default=0.0, ge=0, le=0.9)
    review: Literal["pending", "accepted", "adjusted", "rejected"] = "pending"
    review_note: str = ""
    evidence_key: str = ""
    evidence_source: EvidenceSource | None = None
    blocked_by: list[str] = Field(default_factory=list)


class StayHuman(StorageModel):
    substeps: list[int] = Field(default_factory=list)
    reason: str = ""
    evidence: str = ""
    evidence_key: str = ""


class DiagramNode(StorageModel):
    id: str
    type: str
    label: str = ""
    lane: str = ""
    step_index: int | None = None
    marker: str = ""


class DiagramFlow(StorageModel):
    source: str
    target: str
    label: str = ""
    is_default: bool = False


class DataObject(StorageModel):
    """An input or output of one step, drawn beside its task (spec 18 §4.4; built by code)."""

    id: str
    step_index: int = Field(ge=1)
    direction: Literal["input", "output"]
    label: str


class DataStore(StorageModel):
    """A system the steps read or write, drawn once (spec 18 §4.4; built by code)."""

    id: str
    label: str
    steps: list[int] = Field(default_factory=list)


class ProcessDiagram(StorageModel):
    lanes: list[str] = Field(default_factory=list)
    nodes: list[DiagramNode] = Field(default_factory=list)
    flows: list[DiagramFlow] = Field(default_factory=list)
    data_objects: list[DataObject] = Field(default_factory=list)
    data_stores: list[DataStore] = Field(default_factory=list)
    simplified: bool = False
    steps_hash: str = ""


class InputLabel(StorageModel):
    name: str
    format: str
    evidence: str = ""


class DecisionLabel(StorageModel):
    text: str
    kind: str
    evidence: str = ""


class StepLabels(StorageModel):
    step: int = Field(ge=1)
    inputs: list[InputLabel] = Field(default_factory=list)
    decisions: list[DecisionLabel] = Field(default_factory=list)


# Fields typed `None` are parked until the value method is decided (spec 19, refinement R5): no cost,
# rate, share or value can be stored while R5 is open. Deciding R5 changes these types here.


class StepValue(StorageModel):
    """Hours of one step (spec 19 §4.3); a number is None when it cannot be computed."""

    step: int = Field(ge=1)
    name: str = ""
    duration_hours: float | None = None
    runs_per_year: float | None = None
    hours_per_year: float | None = None
    rate: None = None
    share: None = None
    hours_freed: None = None
    value_conservative: None = None
    value_expected: None = None
    problem: str | None = None


class OpportunityValue(StorageModel):
    """Hours of the steps one opportunity covers (spec 19 §4.3)."""

    id: str
    step_hours: float | None = None
    hours_freed: None = None
    value_conservative: None = None
    value_expected: None = None


class ValueResult(StorageModel):
    complete: bool = False
    missing: list[str] = Field(default_factory=list)
    hours_per_year: float | None = None
    cost_today: None = None
    hours_freed: None = None
    value_conservative: None = None
    value_expected: None = None
    currency: str = ""
    runs_per_year: float | None = None
    steps: list[StepValue] = Field(default_factory=list)
    opportunities: list[OpportunityValue] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ReadinessDimension(StorageModel):
    key: str
    level: Literal["high", "medium", "low", "unknown"]
    reason: str = ""
    to_prepare: str = ""
    note: str = ""
    label: str = ""
    steps: list[int] = Field(default_factory=list)


class Readiness(StorageModel):
    dimensions: list[ReadinessDimension] = Field(default_factory=list)


class Path(StorageModel):
    prepare_first: list[str] = Field(default_factory=list)
    quick_wins: list[str] = Field(default_factory=list)
    bigger_changes: list[str] = Field(default_factory=list)
    prepare_items: list[str] = Field(default_factory=list)


class StepRating(StorageModel):
    """The step assessment's rating of one step (spec 26 §4.2); `fit` None = not assessed."""

    step: int = Field(ge=1)
    name: str
    fit: Literal["automate", "assist", "human"] | None = None
    reason: str = ""
    evidence: str = ""
    evidence_key: str = ""
    evidence_source: EvidenceSource | None = None
    route_id: str | None = None
    route_reason: str = ""


class RouteSummary(StorageModel):
    """The recommended route built by code from the ratings and the step hours (spec 26 §3.6)."""

    headline: str = ""
    start_with: list[int] = Field(default_factory=list)
    later: list[int] = Field(default_factory=list)
    fix_first: list[int] = Field(default_factory=list)
    stay_with_people: list[int] = Field(default_factory=list)
    not_routed: list[int] = Field(default_factory=list)
    prepare: list[str] = Field(default_factory=list)


class StepAssessment(StorageModel):
    steps: list[StepRating] = Field(default_factory=list)
    route: RouteSummary | None = None
    inputs_hash: str = ""
    placeholder_catalogue: bool = False


class Assessment(StorageModel):
    summary: str = ""
    opportunities: list[Opportunity] = Field(default_factory=list)
    stay_human: list[StayHuman] = Field(default_factory=list)
    diagram: ProcessDiagram | None = None
    labels: list[StepLabels] = Field(default_factory=list)
    value: ValueResult | None = None
    readiness: Readiness | None = None
    path: Path | None = None
    step_assessment: StepAssessment | None = None
    steps_hash: str = ""
    generated_at: str = ""
    outcomes: dict[
        Literal["opportunities", "diagram", "labels", "steps"], Literal["generated", "fallback", "failed"]
    ] = Field(default_factory=dict)


class ReportState(StorageModel):
    status: Literal["mapped", "validated"] = "mapped"
    validated_at: str | None = None
    validated_by: str | None = None
    note: str = ""


class BriefContent(StorageModel):
    """The implementation brief itself. Spec 23 defines its fields."""


class BriefHistoryEntry(StorageModel):
    status: Literal["draft", "sent", "accepted", "returned"]
    by: str
    at: str
    note: str = ""


class Brief(StorageModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    opportunity_ids: list[str] = Field(default_factory=list)
    content: BriefContent = Field(default_factory=BriefContent)
    status: Literal["draft", "sent", "accepted", "returned"] = "draft"
    questions: str = ""
    history: list[BriefHistoryEntry] = Field(default_factory=list)
    created_at: str
    created_by: str


# --- Documents ---------------------------------------------------------------------------------------


class Session(StorageModel):
    """One interview by one expert about one process (Cosmos document, type `session`)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_id: str
    type: Literal["session"] = "session"
    display_name: str | None = Field(default=None, max_length=40)
    created_at: str
    updated_at: str
    finished_at: str | None = None
    ttl: int | None = None
    status: SessionStatus = SessionStatus.ACTIVE
    phase: Phase = Phase.CONTEXT
    messages: list[Message] = Field(default_factory=list)
    profile: Profile = Field(default_factory=Profile)
    score: Score = Field(default_factory=Score)
    counters: Counters = Field(default_factory=Counters)
    scope: ScopeState = Field(default_factory=ScopeState)
    placement: PlacementState = Field(default_factory=PlacementState)
    last_question: LastQuestion = Field(default_factory=LastQuestion)
    steering: SteeringState = Field(default_factory=SteeringState)
    documents: list[DocumentRecord] = Field(default_factory=list)
    raw_substeps: list[Step] = Field(default_factory=list)
    assessment: Assessment | None = None
    report: ReportState | None = None
    briefs: list[Brief] = Field(default_factory=list)
    cost: Cost = Field(default_factory=Cost)
    etag: str | None = Field(default=None, exclude=True)


class Idea(StorageModel):
    """A candidate process the expert mentioned but did not map yet (Cosmos document, type `idea`)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    owner_id: str
    type: Literal["idea"] = "idea"
    name: str
    words: str = ""
    from_session_id: str
    started_session_id: str | None = None
    status: Literal["open", "started", "dismissed"] = "open"
    created_at: str
    ttl: int | None = None
    signals: CandidateSignals = Field(default_factory=CandidateSignals)
    hours_per_year: float | None = None
    people: float | None = None
    data_score: float | None = Field(default=None, ge=0, le=1)
    score: float | None = Field(default=None, ge=0, le=1)
    rank: int | None = Field(default=None, ge=1)
    recommended: bool = False


# --- Shared wire models ------------------------------------------------------------------------------


class FieldView(WireModel):
    """One field as the panel and the review screen show it. Built by the snapshot (spec 13)."""

    key: str
    id: str
    label: str
    phase: str
    status: FieldStatus
    reason: str = ""
    missing: list[str] = Field(default_factory=list)
    source: str | None = None
    quote: str | None = None
    document_name: str | None = None
    asks: int = 0


class FinishState(WireModel):
    ready: bool
    blocked_by: FinishBlock | None = None
    looks_like_task: bool = False


class ClusterOut(WireModel):
    code: str
    name: str
    description: str


class TaxonomyOut(WireModel):
    clusters: list[ClusterOut]
