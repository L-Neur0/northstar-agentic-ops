"""Judge calibration: the judge must agree with hand labels before its answers count (spec 24 §3.8 J6, J7).

Why: a judge that says "same" too easily would inflate report quality, and one that is too strict
would hide real progress. Running it first on about thirty pairs a person has labelled (numbers off
by one, negations, partial lists, synonyms, other units) measures that, every run, on the same model.
What: `CalibrationPair`, `load_pairs` (the YAML file, with its shape rule: 25-40 pairs, at least 12
true and 12 false), and `calibrate`, which judges every pair and computes agreement; below 90 %
the judge fails, the scorecard marks judged results "not trusted" and the run exits 1.
Must not: change a label to fit the judge, or skip pairs.
Spec 24 §3.8; AC-24.17, AC-24.18.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .judge import Judge

AGREEMENT_GATE = 0.90


class CalibrationPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    rule: str = ""
    hidden: str
    captured: str
    label: bool
    note: str = ""


class PairResult(BaseModel):
    field: str
    label: bool
    judged: bool
    agree: bool
    reason: str


class Calibration(BaseModel):
    pairs: int = 0
    agreed: int = 0
    agreement: float = 0.0
    passed: bool = False
    results: list[PairResult] = Field(default_factory=list)


class CalibrationFileError(ValueError):
    """The calibration file breaks its shape rule."""


def load_pairs(path: Path) -> list[CalibrationPair]:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    pairs = [CalibrationPair.model_validate(p) for p in data.get("pairs") or []]
    trues = sum(1 for p in pairs if p.label)
    if not 25 <= len(pairs) <= 40 or trues < 12 or len(pairs) - trues < 12:
        raise CalibrationFileError(f"{path.name}: needs 25-40 pairs with at least 12 true and 12 false")
    return pairs


async def calibrate(judge: Judge, pairs: list[CalibrationPair]) -> Calibration:
    """Judge every pair; agreement = judge equals label / all pairs; passes at 90 % or more."""
    results: list[PairResult] = []
    for pair in pairs:
        verdict = await judge.same(pair.field, pair.rule, pair.hidden, pair.captured)
        results.append(
            PairResult(
                field=pair.field,
                label=pair.label,
                judged=verdict.same_meaning,
                agree=verdict.same_meaning == pair.label and not verdict.error,
                reason=verdict.reason,
            )
        )
    agreed = sum(1 for r in results if r.agree)
    agreement = agreed / len(results) if results else 0.0
    return Calibration(
        pairs=len(results),
        agreed=agreed,
        agreement=agreement,
        passed=agreement >= AGREEMENT_GATE - 1e-9,
        results=results,
    )
