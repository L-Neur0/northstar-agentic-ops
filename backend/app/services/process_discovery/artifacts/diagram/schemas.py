"""The wire contract of the MAP call (spec 18 §3.7 item 2).

Why: same split as the OPPORTUNITIES schema: Azure's strict subset needs every field required, no
defaults and no bounds, and the storage `ProcessDiagram` keeps its own shape (lane names, data objects
and stores built by code). `grounding.py` is what turns one into the other.
What: `DiagramNodeOut`, `DiagramFlowOut`, `ProcessDiagramOut`. Node `type` and `marker` are closed
`Literal`s, so the decoder cannot emit an element code cannot draw; the marker is the flat union of all
types' markers (strict mode has no per-type enum), and grounding checks it fits the node's type.
A test pins both literals to `DIAGRAM_MARKERS_BY_TYPE`, so the declarations cannot drift.
Must not: carry data objects, data stores, ids of the session or any default or bound.
Spec 18 §3.7; AC-18.2, AC-18.3.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

DiagramNodeTypeName = Literal["start", "task", "gateway", "end"]

DiagramMarkerName = Literal[
    "none", "message", "timer", "conditional", "signal",
    "user", "manual", "service", "send", "receive", "script", "business_rule",
    "exclusive", "parallel", "inclusive", "event_based",
    "terminate", "error",
]  # fmt: skip


class DiagramNodeOut(BaseModel):
    """One BPMN element. `lane` is a 0-based index into `lanes`; `step_index` is the 1-based step a task
    draws, null for events and gateways."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: DiagramNodeTypeName
    label: str
    lane: int
    step_index: int | None
    marker: DiagramMarkerName


class DiagramFlowOut(BaseModel):
    """A sequence flow between two node ids. `is_default` is legal only leaving a gateway."""

    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    label: str
    is_default: bool


class ProcessDiagramOut(BaseModel):
    """The whole reply."""

    model_config = ConfigDict(extra="forbid")

    lanes: list[str]
    nodes: list[DiagramNodeOut]
    flows: list[DiagramFlowOut]
