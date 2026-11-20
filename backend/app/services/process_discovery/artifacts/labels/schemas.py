"""The wire contract of the LABEL call (spec 19 §3.3 item 2).

Why: Azure Structured Outputs runs the schema inside the decoder and its strict subset forbids
defaults and bounds, so LABEL gets wire models of its own instead of the stored `StepLabels`. The
format and kind vocabularies are `Literal`s, rendered as closed enums; a test pins them so the
readiness rules (spec 19 §3.5) and the model's words cannot drift.
What: `InputLabelOut`, `DecisionLabelOut`, `StepLabelsOut`, `LabelsOut`, every field required, no
defaults, `extra="forbid"`; `INPUT_FORMATS` and `DECISION_KINDS` for code that re-checks a mapping.
Must not: carry scores, numbers other than the step, or any default or bound.
Spec 19 §3.3; AC-19.17.
"""

from __future__ import annotations

import typing
from typing import Literal

from pydantic import BaseModel, ConfigDict

InputFormat = Literal["structured", "digital_document", "paper", "verbal"]
DecisionKind = Literal["fixed_rule", "explainable_judgement", "pure_judgement"]
INPUT_FORMATS: tuple[str, ...] = typing.get_args(InputFormat)
DECISION_KINDS: tuple[str, ...] = typing.get_args(DecisionKind)


class InputLabelOut(BaseModel):
    """One input of a step, by its exact name, with its format and the expert's words."""

    model_config = ConfigDict(extra="forbid")

    name: str
    format: InputFormat
    evidence: str


class DecisionLabelOut(BaseModel):
    """One decision taken in a step, in at most 15 words, with its kind and the expert's words."""

    model_config = ConfigDict(extra="forbid")

    text: str
    kind: DecisionKind
    evidence: str


class StepLabelsOut(BaseModel):
    """The labels of one `--- STEP n ---`."""

    model_config = ConfigDict(extra="forbid")

    step: int
    inputs: list[InputLabelOut]
    decisions: list[DecisionLabelOut]


class LabelsOut(BaseModel):
    """The whole reply: one entry per step."""

    model_config = ConfigDict(extra="forbid")

    steps: list[StepLabelsOut]
