"""The wire contract of the OPPORTUNITIES call (spec 18 §3.4 item 2).

Why: Azure Structured Outputs runs the schema inside the decoder, and its strict subset forbids most of
what the storage models carry (defaults make fields optional; bounds render as `minimum`). Keeping
a separate wire model means the storage models keep their validation and the decoder gets a schema
it accepts. The vocabularies are `Literal`s, so they render as closed enums the decoder cannot leave.
What: `OpportunityOut`, `StayHumanOut`, `OpportunitiesOut`: every field required, no defaults, no
numeric bounds, `extra="forbid"`. The type and grade literals are pinned to `OpportunityType` and
`Grade` by a test, so the two declarations cannot drift.
Must not: carry ids, saving shares or review state (code sets them), or any default or bound.
Spec 18 §3.4; AC-18.2, AC-18.3.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

OpportunityTypeName = Literal[
    "eliminate", "standardise", "workflow", "integration", "document_ai", "ai_assistant", "ai_agent", "rpa"
]
GradeName = Literal["high", "medium", "low"]


class OpportunityOut(BaseModel):
    """One opportunity as the decoder must write it. `steps` are 1-based STEP numbers; `[]` = whole process."""

    model_config = ConfigDict(extra="forbid")

    title: str
    steps: list[int]
    type: OpportunityTypeName
    what_changes: str
    how: str
    prepare_first: str
    impact: GradeName
    impact_reason: str
    feasibility: GradeName
    feasibility_reason: str
    evidence: str


class StayHumanOut(BaseModel):
    """Steps that should stay with people, why, and the expert's words that show it."""

    model_config = ConfigDict(extra="forbid")

    steps: list[int]
    reason: str
    evidence: str


class OpportunitiesOut(BaseModel):
    """The whole reply. No ids or review fields: code stamps those after grounding."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    opportunities: list[OpportunityOut]
    stay_human: list[StayHumanOut]
