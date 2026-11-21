"""The wire contract of the ASSESS_STEPS call (spec 26 §3.3 item 2).

Why: Azure Structured Outputs runs the schema inside the decoder, and its strict subset forbids
defaults and bounds, so the call gets its own wire model instead of the stored `StepRating`. The fit
is a `Literal`, rendered as a closed enum the decoder cannot leave; a test pins it to `AIFit` so the
catalogue's fits and the model's fits cannot drift.
What: `StepRatingOut` (one entry per `--- STEP n ---`) and `AssessStepsOut` (the whole reply). Every
field is required, no defaults, `extra="forbid"`.
Must not: carry the step name, the evidence key or any number other than the step (code sets them),
or name a route: `route` is free text checked by code against the catalogue.
Spec 26 §3.3; AC-26.2. Spec 27 §3.2 (signals and motivations); AC-27.10.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

FitName = Literal["automate", "assist", "human"]


SignalName = Literal[
    "reads_unstructured", "compares_to_criteria", "finds_patterns", "drafts_text", "must_be_exact", "fixed_rules"
]


class SignalOut(BaseModel):
    """A signal that holds for the step (spec 27 §3.2), with the expert's words from that step."""

    model_config = ConfigDict(extra="forbid")

    name: SignalName
    evidence: str


class MotivationOut(BaseModel):
    """A process-level motivation sentence and the expert's words behind it (spec 27 §3.2)."""

    model_config = ConfigDict(extra="forbid")

    text: str
    evidence: str


class StepRatingOut(BaseModel):
    """One step's fit, reason, quoted evidence, route id (`""` when no catalogue entry fits) and signals."""

    model_config = ConfigDict(extra="forbid")

    step: int
    fit: FitName
    reason: str
    evidence: str
    route: str
    route_reason: str
    signals: list[SignalOut]


class AssessStepsOut(BaseModel):
    """The whole reply: one entry per step, and the three motivations (spec 27 §3.2)."""

    model_config = ConfigDict(extra="forbid")

    steps: list[StepRatingOut]
    fit_motivation: MotivationOut
    assistant_motivation: MotivationOut
    worth_motivation: MotivationOut
