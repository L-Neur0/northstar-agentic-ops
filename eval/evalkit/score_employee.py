"""The employee's side of a session: estimated time, detail burden, quality split by field value (spec 24 §3.9b).

Why: the product owner decided on 2026-11-20 that what costs the employee is time and being asked
for details that add little, not the number of messages. A session of 40 short yes/no messages can
cost less than one of 20 long ones, and a question about a step's hand-over costs as much time as
one about its systems while adding far less to the assessment. These numbers make that visible.
What: `employee_time` (reading + typing + thinking + uploads, constants from
`eval/employee_time.yaml`), `detail_burden` (share of questions whose focus holds only low-value
fields, from the turn log's `focus` keys), `quality_split` (field results on Tier A + process core
vs the rest), and the loaders for the two YAML files.
Must not: hold a constant or a tier in code (both are evaluation data, marked as assumptions in
the YAML files), call a model, or read anything but what it is given.
The average answer length (`avg_expert_words`) is reported beside the time (AC-24.48).
Spec 24 §3.9b; AC-24.37 to AC-24.41, AC-24.48.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, computed_field

from .score_fields import FieldResult

CELL = re.compile(r"^process\.substeps\[[^\]]*\]\.([a-z_]+)")


class TimeModel(BaseModel):
    """The assumed speeds and times of `eval/employee_time.yaml`."""

    model_config = ConfigDict(extra="forbid")
    reading_wpm: float = Field(gt=0)
    typing_wpm: float = Field(gt=0)
    think_seconds: float = Field(ge=0)
    short_answer_think_seconds: float = Field(ge=0)
    short_answer_max_words: int = Field(ge=0)
    upload_seconds: float = Field(ge=0)
    target_minutes: float = Field(gt=0)


class Tiers(BaseModel):
    """Field value tiers of `eval/tiers.yaml`."""

    model_config = ConfigDict(extra="forbid")
    step_leaves: dict[str, Literal["A", "B", "C"]]
    low_value_tiers: list[Literal["A", "B", "C"]] = Field(default_factory=lambda: ["C"])  # pyright: ignore[reportUnknownLambdaType]
    low_value_process: list[str] = Field(default_factory=list)
    process_core: list[str] = Field(default_factory=list)

    def leaf(self, key: str) -> str | None:
        match = CELL.match(key)
        return match.group(1) if match else None

    def is_low_value(self, key: str) -> bool:
        leaf = self.leaf(key)
        if leaf is not None:
            return self.step_leaves.get(leaf) in self.low_value_tiers
        return key in self.low_value_process

    def is_core(self, key: str) -> bool:
        """Tier A step cell or a process core field (the first share of the quality split)."""
        leaf = self.leaf(key)
        if leaf is not None:
            return self.step_leaves.get(leaf) == "A"
        return key in self.process_core


class EmployeeTime(BaseModel):
    reading_s: float = 0.0
    typing_s: float = 0.0
    think_s: float = 0.0
    upload_s: float = 0.0
    agent_messages: int = 0
    expert_messages: int = 0
    agent_words: int = 0
    expert_words: int = 0

    @computed_field
    @property
    def avg_expert_words(self) -> float:
        """Average answer length in words (A2: a busy person writes about 15-45 words)."""
        return round(self.expert_words / self.expert_messages, 1) if self.expert_messages else 0.0

    @property
    def seconds(self) -> float:
        return self.reading_s + self.typing_s + self.think_s + self.upload_s

    @property
    def minutes(self) -> float:
        return self.seconds / 60


class DetailBurden(BaseModel):
    questions: int
    low_value: int
    low_value_keys: list[str] = Field(default_factory=list)

    @property
    def share(self) -> float:
        return self.low_value / self.questions if self.questions else 0.0


class QualitySplit(BaseModel):
    core_correct: int = 0
    core_total: int = 0
    rest_correct: int = 0
    rest_total: int = 0

    @property
    def core_quality(self) -> float:
        return self.core_correct / self.core_total if self.core_total else 0.0

    @property
    def rest_quality(self) -> float:
        return self.rest_correct / self.rest_total if self.rest_total else 0.0


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_time_model(path: Path) -> TimeModel:
    return TimeModel.model_validate(_yaml(path))


def load_tiers(path: Path) -> Tiers:
    return Tiers.model_validate(_yaml(path))


def _word_count(text: Any) -> int:
    return len(str(text or "").split())


def employee_time(transcript: Sequence[Mapping[str, Any]], uploads: int, model: TimeModel) -> EmployeeTime:
    """Reading (agent words), typing (expert words), think time per expert message, uploads (AC-24.37)."""
    out = EmployeeTime(upload_s=uploads * model.upload_seconds)
    for message in transcript:
        words = _word_count(message.get("text"))
        if message.get("role") == "agent":
            out.agent_messages += 1
            out.agent_words += words
        elif message.get("role") == "expert":
            out.expert_messages += 1
            out.expert_words += words
            short = words <= model.short_answer_max_words
            out.think_s += model.short_answer_think_seconds if short else model.think_seconds
    out.reading_s = out.agent_words / model.reading_wpm * 60
    out.typing_s = out.expert_words / model.typing_wpm * 60
    return out


def detail_burden(turns: Sequence[Mapping[str, Any]], tiers: Tiers) -> DetailBurden | None:
    """Share of questions whose focus holds only low-value fields; `None` without a turn log (AC-24.39)."""
    questions, low, keys = 0, 0, list[str]()
    for record in turns:
        focus = [str(k) for k in record.get("focus") or []]
        if not focus:
            continue
        questions += 1
        if all(tiers.is_low_value(k) for k in focus):
            low += 1
            keys += focus
    if questions == 0:
        return None
    return DetailBurden(questions=questions, low_value=low, low_value_keys=keys)


def quality_split(results: Sequence[FieldResult], tiers: Tiers) -> QualitySplit:
    """The §3.7 field results on Tier A + process core vs the rest (AC-24.41)."""
    split = QualitySplit()
    for r in results:
        if tiers.is_core(r.key):
            split.core_total += 1
            split.core_correct += int(r.correct)
        else:
            split.rest_total += 1
            split.rest_correct += int(r.correct)
    return split
