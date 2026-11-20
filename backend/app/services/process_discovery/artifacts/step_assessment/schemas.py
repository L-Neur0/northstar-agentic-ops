"""The wire contract of the ASSESS_STEPS call (spec 26 §3.3 item 2).

Why: Azure Structured Outputs runs the schema inside the decoder, and its strict subset forbids
defaults and bounds, so the call gets its own wire model instead of the stored `StepRating`. The fit
is a `Literal`, rendered as a closed enum the decoder cannot leave; a test pins it to `AIFit` so the
catalogue's fits and the model's fits cannot drift.
What: `StepRatingOut` (one entry per `--- STEP n ---`) and `AssessStepsOut` (the whole reply). Every
field is required, no defaults, `extra="forbid"`.
Must not: carry the step name, the evidence key or any number other than the step (code sets them),
or name a route: `route` is free text checked by code against the catalogue.
Spec 26 §3.3; AC-26.2.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

FitName = Literal["automate", "assist", "human"]


class StepRatingOut(BaseModel):
    """One step's fit, reason, quoted evidence and route id (`""` when no catalogue entry fits)."""

    model_config = ConfigDict(extra="forbid")

    step: int
    fit: FitName
    reason: str
    evidence: str
    route: str
    route_reason: str


class AssessStepsOut(BaseModel):
    """The whole reply: one entry per step."""

    model_config = ConfigDict(extra="forbid")

    steps: list[StepRatingOut]
