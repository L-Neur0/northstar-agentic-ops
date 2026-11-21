"""Tests for the signals and motivations ASSESS_STEPS returns since report v2 (spec 27 §3.2).

Why: the three guiding questions rest on per-step signals (reads varied documents, compares with
criteria, must be exact, fixed rules ...). A signal is only true when the expert's words in that step
show it, so code checks every quote and drops the rest (product rule 6).
What: grounding of signals, `raw_motivations`, and the prompt and schema text.
Must not: call a model. Covers AC-27.2, AC-27.10.
"""

from __future__ import annotations

import copy

from app.services.process_discovery.artifacts.step_assessment.grounding import ground_step_ratings, raw_motivations
from app.services.process_discovery.artifacts.step_assessment.prompts import ASSESS_STEPS_SYSTEM
from app.services.process_discovery.artifacts.step_assessment.schemas import AssessStepsOut, StepRatingOut
from tests.fixtures.assessment.profiles import load_profile
from tests.fixtures.assessment_19.cases import STEPS_REPLY, example_catalogue


def test_ac_27_2_signals_need_that_steps_words():
    reply = copy.deepcopy(STEPS_REPLY)
    reply["steps"][0]["signals"] = [
        {"name": "reads_unstructured", "evidence": "sites send late and in different layouts"},  # step 1: kept
        {"name": "drafts_text", "evidence": "write the commentary"},  # step 5's words: dropped
        {"name": "guess", "evidence": "sites send late and in different layouts"},  # unknown name: dropped
    ]
    ratings, dropped = ground_step_ratings(reply, load_profile("eu"), example_catalogue())
    assert ratings[0].signals == {"reads_unstructured": True}
    assert ratings[0].signal_evidence["reads_unstructured"] == "sites send late and in different layouts"
    assert dropped["signal"] == 2
    assert ratings[4].signals == {"drafts_text": True}


def test_ac_27_2_raw_motivations_are_passed_on_unchecked():
    out = raw_motivations(STEPS_REPLY)
    assert set(out) == {"q1", "q2", "q3"}
    assert out["q1"][1] == "I write the commentary from scratch every month"


def test_ac_27_10_prompt_and_schema():
    text = " ".join(ASSESS_STEPS_SYSTEM.split())
    for name in ("reads_unstructured", "compares_to_criteria", "finds_patterns", "drafts_text", "must_be_exact",
                 "fixed_rules"):  # fmt: skip
        assert f"`{name}`" in text
    assert "GUIDELINES (what AI is good at)" in text and "Never answer yes or no" in text
    assert {"signals"} <= set(StepRatingOut.model_fields)
    assert {"fit_motivation", "assistant_motivation", "worth_motivation"} <= set(AssessStepsOut.model_fields)
