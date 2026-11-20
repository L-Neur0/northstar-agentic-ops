"""Tests for the OPPORTUNITIES call through `FakeLLM` (spec 18 §3.4, §3.9; AC-18.4, AC-18.16, AC-18.39).

Why: the call must ask once, with the right call type, the system prompt and the fenced profile; any
client error must become `OpportunitiesFailedError` (there is no fallback content); and the one
`assessment_call` log line must carry counts only. `FakeLLM` applies the real client's rules, so an
invalid reply fails here the way it would in production.
"""

from __future__ import annotations

import logging

import pytest

from app.services.process_discovery.artifacts.analysis.analysis import OpportunitiesFailedError, run_opportunities
from app.services.process_discovery.artifacts.analysis.prompts import OPPORTUNITIES_SYSTEM, opportunities_user
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.llm import (
    CallType,
    LLMBudgetExceededError,
    LLMEmptyResponseError,
    LLMInvalidOutputError,
    LLMUnavailableError,
)
from tests.fixtures.assessment.profiles import load_profile, nig_config, nig_vocabulary
from tests.fixtures.assessment.replies import opportunities_reply

RATES = nig_config().rates
SENTINEL = "ZQX-SENTINEL-4711"


async def _run(*replies):
    llm = FakeLLM({CallType.OPPORTUNITIES: list(replies)})
    result = await run_opportunities(load_profile("eu"), llm, RATES, vocab=nig_vocabulary())
    return result, llm


async def test_one_call_with_the_call_type_the_system_prompt_and_the_fenced_profile():
    """AC-18.4."""
    result, llm = await _run(opportunities_reply())
    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert (call.call_type, call.method, call.model_name) == (CallType.OPPORTUNITIES, "structured", "OpportunitiesOut")
    assert call.messages[0] == {"role": "system", "content": OPPORTUNITIES_SYSTEM}
    assert call.messages[1] == {
        "role": "user",
        "content": opportunities_user(load_profile("eu"), vocab=nig_vocabulary()),
    }
    assert [o.id for o in result.opportunities] == ["o1", "o2", "o3", "o4"]
    llm.assert_all_used()


@pytest.mark.parametrize(
    "error",
    [LLMEmptyResponseError("refused"), LLMUnavailableError(503), LLMBudgetExceededError("budget")],
    ids=lambda e: type(e).__name__,
)
async def test_every_client_error_becomes_opportunities_failed(error):
    """AC-18.16."""
    with pytest.raises(OpportunitiesFailedError) as raised:
        await _run(error)
    assert raised.value.__cause__ is error


async def test_an_empty_reply_is_a_failure():
    """AC-18.16: the fake applies the empty-reply rule."""
    with pytest.raises(OpportunitiesFailedError) as raised:
        await _run("   ")
    assert isinstance(raised.value.__cause__, LLMEmptyResponseError)


async def test_an_invalid_reply_twice_is_a_failure():
    """AC-18.16: strict schema plus one retry, then `LLMInvalidOutputError`."""
    with pytest.raises(OpportunitiesFailedError) as raised:
        await _run({"summary": 1}, "not json")
    assert isinstance(raised.value.__cause__, LLMInvalidOutputError)


async def test_an_empty_list_is_not_a_failure():
    """AC-18.15."""
    result, _ = await _run({"summary": "Nothing to automate.", "opportunities": [], "stay_human": []})
    assert result.opportunities == [] and result.summary == "Nothing to automate."


async def test_one_log_line_with_outcome_and_counts_and_no_text(caplog):
    """AC-18.39: counts only; a sentinel in the profile and the reply never reaches a log record."""
    profile = load_profile("eu")
    profile["process"]["business_pain"] += f" {SENTINEL}"
    reply = opportunities_reply()
    reply["summary"] += SENTINEL
    reply["opportunities"][0]["title"] += SENTINEL
    llm = FakeLLM({CallType.OPPORTUNITIES: [reply]})
    with caplog.at_level(logging.DEBUG):
        await run_opportunities(profile, llm, RATES, vocab=nig_vocabulary())
    lines = [r for r in caplog.records if r.getMessage() == "assessment_call"]
    assert len(lines) == 1
    record = lines[0].__dict__
    assert record["call"] == "OPPORTUNITIES" and record["outcome"] == "generated"
    assert record["kept"] == 4 and record["dropped"] == {"step": 1, "quote": 1, "invalid": 0, "cap": 0}
    assert isinstance(record["duration_ms"], int)
    for r in caplog.records:
        assert SENTINEL not in r.getMessage() and SENTINEL not in repr(r.__dict__)


async def test_a_failed_call_logs_one_failed_line(caplog):
    with caplog.at_level(logging.DEBUG), pytest.raises(OpportunitiesFailedError):
        await _run(LLMUnavailableError(500))
    lines = [r for r in caplog.records if r.getMessage() == "assessment_call"]
    assert len(lines) == 1
    assert lines[0].__dict__["outcome"] == "failed" and lines[0].__dict__["error"] == "LLMUnavailableError"
