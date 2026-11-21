"""Tests for the ASSESS_STEPS call through `FakeLLM` (spec 26 §3.3, §3.8).

Why: the call must ask once, with its call type, the rules plus the catalogue, and the fenced
profile; every client error must become `StepAssessmentFailedError` (no fallback ratings); and the
one `assessment_call` log line must carry counts only, never profile or reply text.
What: `run_step_assessment` with scripted replies, errors and a sentinel in profile and reply.
Must not: reach the network (`FakeLLM` applies the real client's rules).
Covers AC-26.3 (call half), AC-26.11, AC-26.18.
"""

from __future__ import annotations

import copy
import logging

import pytest

from app.services.process_discovery.artifacts.step_assessment.prompts import assess_steps_system, assess_steps_user
from app.services.process_discovery.artifacts.step_assessment.steps import (
    StepAssessmentFailedError,
    run_step_assessment,
)
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.llm import (
    CallType,
    LLMBudgetExceededError,
    LLMEmptyResponseError,
    LLMInvalidOutputError,
    LLMUnavailableError,
)
from tests.fixtures.assessment.profiles import load_profile, nig_vocabulary
from tests.fixtures.assessment_19.cases import STEPS_REPLY, example_catalogue

CAT = example_catalogue()
SENTINEL = "ZQX-SENTINEL-2626"


async def _run(*replies, profile=None):
    llm = FakeLLM({CallType.ASSESS_STEPS: list(replies)})
    result = await run_step_assessment(load_profile("eu") if profile is None else profile, llm, CAT,
                                       vocab=nig_vocabulary())  # fmt: skip
    return result, llm


async def test_ac_26_3_one_call_with_rules_catalogue_and_fenced_profile() -> None:
    """AC-26.3 (call): one structured ASSESS_STEPS call; system = rules + catalogue; user = fenced profile."""
    (ratings, dropped, _motivations), llm = await _run(copy.deepcopy(STEPS_REPLY))
    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert (call.call_type, call.method, call.model_name) == (CallType.ASSESS_STEPS, "structured", "AssessStepsOut")
    assert call.messages[0] == {"role": "system", "content": assess_steps_system(CAT)}
    assert call.messages[1] == {
        "role": "user",
        "content": assess_steps_user(load_profile("eu"), vocab=nig_vocabulary()),
    }
    assert "<<<PROFILE" in call.messages[1]["content"] and "PROFILE>>>" in call.messages[1]["content"]
    assert [r.route_id for r in ratings] == ["fix-first", "custom-ai-app", "low-code-flow", "low-code-flow",
                                             "office-assistant"]  # fmt: skip
    assert set(dropped.values()) == {0}
    llm.assert_all_used()


@pytest.mark.parametrize(
    "error",
    [LLMEmptyResponseError("refused"), LLMUnavailableError(503), LLMBudgetExceededError("budget")],
    ids=lambda e: type(e).__name__,
)
async def test_ac_26_11_client_errors_fail(error: Exception) -> None:
    """AC-26.11: each client error → `StepAssessmentFailedError`, chained."""
    with pytest.raises(StepAssessmentFailedError) as raised:
        await _run(error)
    assert raised.value.__cause__ is error


async def test_ac_26_11_invalid_twice_and_empty_fail() -> None:
    with pytest.raises(StepAssessmentFailedError) as raised:
        await _run({"steps": "no"}, "not json")
    assert isinstance(raised.value.__cause__, LLMInvalidOutputError)
    with pytest.raises(StepAssessmentFailedError) as raised:
        await _run("  ")
    assert isinstance(raised.value.__cause__, LLMEmptyResponseError)


async def test_ac_26_18_one_log_line_counts_only(caplog: pytest.LogCaptureFixture) -> None:
    """AC-26.18: one line with outcome, kept, drops by reason and `placeholder_catalogue`; no text."""
    profile = load_profile("eu")
    profile["process"]["business_pain"] += f" {SENTINEL}"
    reply = copy.deepcopy(STEPS_REPLY)
    reply["steps"][0]["reason"] += SENTINEL
    reply["steps"][2]["route"] = "acme-copilot"
    reply["steps"][3]["evidence"] = f"invented {SENTINEL} words"
    reply["steps"][3]["signals"] = []  # no rescue by a signal quote (spec 27)
    with caplog.at_level(logging.DEBUG):
        await _run(reply, profile=profile)
    lines = [r for r in caplog.records if r.getMessage() == "assessment_call"]
    assert len(lines) == 1
    record = lines[0].__dict__
    assert (record["call"], record["outcome"], record["kept"]) == ("ASSESS_STEPS", "generated", 4)
    assert record["dropped"] == {"step": 0, "quote": 1, "invalid": 0, "cap": 0, "route": 1, "signal": 0, "rescued": 0}
    assert record["placeholder_catalogue"] is True
    assert isinstance(record["duration_ms"], int)
    for r in caplog.records:
        assert SENTINEL not in r.getMessage() and SENTINEL not in repr(r.__dict__)


async def test_ac_26_18_failed_call_logs_failed(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG), pytest.raises(StepAssessmentFailedError):
        await _run(LLMUnavailableError(500))
    lines = [r for r in caplog.records if r.getMessage() == "assessment_call"]
    assert len(lines) == 1 and lines[0].__dict__["outcome"] == "failed"
    assert lines[0].__dict__["error"] == "LLMUnavailableError"
