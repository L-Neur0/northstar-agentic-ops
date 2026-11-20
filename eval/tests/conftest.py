"""Shared fixtures of the evaluation tests: import paths, the company facts, tiny personas, fake judges (spec 24 §7).

Why: every eval test needs the same fixed inputs (the NIG config, a small persona, a judge with
known answers), and none may call a model. What: puts the repository root and `backend/` on the
import path, loads the company facts once, builds personas from dicts, and offers `FakeJudge`.
Must not: reach Azure or write outside `tmp_path`.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from eval.evalkit.judge import Verdict  # noqa: E402
from eval.evalkit.persona import Company, Persona, load_company  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
TINY = FIXTURES / "personas" / "tiny.yaml"


@pytest.fixture(scope="session")
def company() -> Company:
    return load_company(ROOT / "config" / "nig")


def tiny_data() -> dict[str, Any]:
    return copy.deepcopy(yaml.safe_load(TINY.read_text(encoding="utf-8")))


def make_persona(**changes: Any) -> Persona:
    data = tiny_data()
    data.update(changes)
    return Persona.model_validate(data)


class FakeJudge:
    """Answers from a fixed rule; counts calls (same pair memoised, as the real judge is)."""

    def __init__(self, answer: bool = True) -> None:
        self.answer = answer
        self.pairs: list[tuple[str, str]] = []
        self._memo: dict[tuple[str, str, str, str], Verdict] = {}

    async def same(self, label: str, rule: str, hidden: str, captured: str) -> Verdict:
        key = (label, rule, hidden, captured)
        if key not in self._memo:
            self.pairs.append((hidden, captured))
            self._memo[key] = Verdict(self.answer, "fake")
        return self._memo[key]


def profile_from_truth(persona: Persona) -> dict[str, Any]:
    """A `SessionOut.profile` that captured the persona's truth exactly."""
    fields = copy.deepcopy(persona.truth.fields)
    process: dict[str, Any] = {k.split(".", 1)[1]: v for k, v in fields.items() if k.startswith("process.")}
    process["cluster"] = {"code": fields["process.cluster"], "name": "", "decided_by": "proposal"}
    process["substeps"] = copy.deepcopy(persona.truth.steps)
    return {k: v for k, v in fields.items() if not k.startswith("process.")} | {"process": process}
