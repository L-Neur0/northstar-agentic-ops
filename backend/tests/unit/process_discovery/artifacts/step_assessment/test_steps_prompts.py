"""Tests for the ASSESS_STEPS prompt, the catalogue block and the wire schema (spec 26 §3.3, §3.4).

Why: the model only knows the rules the prompt states, so each rule of §3.4 is pinned by a phrase,
including the decision note's reuse-before-build order (existing internal tool, then the licensed
assistant, then low code, then a custom build). The routes must reach the prompt only from
configuration, and the strict schema must build with the fit pinned to the catalogue's `AIFit`.
What: phrase checks on `ASSESS_STEPS_SYSTEM`, one catalogue line per entry, a sentinel entry that
appears only through configuration, and `strict_json_schema(AssessStepsOut, "AssessStepsOut")`.
Must not: call a model.
Covers AC-26.2, AC-26.3 (prompt half), AC-26.20.
"""

from __future__ import annotations

import typing
from pathlib import Path

from app.core.config import AIFit, SolutionCatalogue
from app.services.process_discovery.artifacts.profile_fence import PROFILE_FENCE_INSTRUCTION
from app.services.process_discovery.artifacts.step_assessment.prompts import (
    ASSESS_STEPS_SYSTEM,
    assess_steps_system,
    render_catalogue,
)
from app.services.process_discovery.artifacts.step_assessment.schemas import AssessStepsOut, FitName
from app.services.process_discovery.json_schema import strict_json_schema
from tests.fixtures.assessment.profiles import nig_config
from tests.fixtures.assessment_19.cases import example_catalogue

PACKAGE = Path(__file__).resolve().parents[5] / "app/services/process_discovery/artifacts/step_assessment"


def test_ac_26_2_strict_schema_and_pinned_fit() -> None:
    """AC-26.2: the strict schema builds; the wire fit equals the catalogue's `AIFit`."""
    schema = strict_json_schema(AssessStepsOut, "AssessStepsOut")
    assert schema
    assert set(typing.get_args(FitName)) == set(typing.get_args(AIFit)) == {"automate", "assist", "human"}


def test_ac_26_3_every_rule_by_phrase() -> None:
    """AC-26.3 (prompt): every rule of §3.4, the fence sentence and the JSON-only line."""
    phrases = [
        "senior process and AI analyst",
        "never invent a system, input, role or pain",
        "exactly one entry per `--- STEP n ---`",
        "`automate`: AI or automation can do the step",
        "`assist`: AI drafts, reads, checks or suggests",
        "`human`: judgement, relationships, accountability or physical work",
        "`reason`: one or two sentences",
        "copied exactly from THAT step or from the process fields",
        "whose `fits` include the step's fit",
        'Use "" if no entry fits. Never invent an id, never name a vendor or product',
        "paper or verbal, or teams do it differently, prefer a `fix_first` entry",
        "`route_reason`: one sentence on why this route fits better than the next best",
        "Never give hours, money, savings or scores",
        PROFILE_FENCE_INSTRUCTION,
        "Return only JSON matching the schema.",
    ]
    lowered = ASSESS_STEPS_SYSTEM.casefold()
    assert [p for p in phrases if p.casefold() not in lowered] == []


def test_reuse_before_build_order() -> None:
    """Decision note: existing internal tool first, then the licensed assistant, then low code, then custom build."""
    order = ["`existing_internal`", "`off_the_shelf`", "`low_code`", "`custom_build`"]
    positions = [ASSESS_STEPS_SYSTEM.index(token) for token in order]
    assert positions == sorted(positions)
    assert 'whenever its "choose when" matches' in ASSESS_STEPS_SYSTEM.replace("\\\n", "")


def test_ac_26_3_one_catalogue_line_per_entry() -> None:
    """AC-26.3: one line per entry with its id, category and fits; appended after the rules."""
    catalogue = nig_config().solutions
    block = render_catalogue(catalogue)
    lines = block.splitlines()[1:]
    assert len(lines) == len(catalogue.solutions) == 13
    for line, entry in zip(lines, catalogue.solutions, strict=True):
        assert line.startswith(f"- {entry.id}: {entry.name} [{entry.category}; fits: ")
        assert len(line) <= 2 + 300 + len(" …(truncated)")
    assert assess_steps_system(catalogue).startswith(ASSESS_STEPS_SYSTEM)
    assert assess_steps_system(catalogue).endswith(block)


def test_ac_26_20_tool_names_come_only_from_configuration() -> None:
    """AC-26.20: a sentinel entry reaches the prompt from configuration; no catalogue name is in the code."""
    data = example_catalogue().model_dump(mode="json")
    data["solutions"][0]["name"] = "Zyxel Sentinel Helper"
    assert "Zyxel Sentinel Helper" in render_catalogue(SolutionCatalogue.model_validate(data))
    code = "\n".join(p.read_text(encoding="utf-8") for p in PACKAGE.glob("*.py"))
    for entry in nig_config().solutions.solutions:
        assert entry.name not in code
    assert "Copilot" not in code
