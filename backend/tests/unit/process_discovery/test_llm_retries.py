"""Tests for the model client's retry rules (spec 11 §3.4).

Why: a transient 429 or 503 must not cost the expert a turn, but a 400 or 401 repeats if the same
request is sent, and a server that asks for a minute will not be ready in time for a turn. The
client retries only what can succeed, waits what the server asks (within a cap) and gives up fast
otherwise, so the caller's fallback runs.
What: a stub SDK client raises real `openai` errors built on `httpx` responses; an injected sleep
records the waits and a seeded random source makes the jitter deterministic. No real waiting.
Implements spec 11, AC-11.10 to AC-11.14.
"""

from __future__ import annotations

import pytest

from app.services.process_discovery.llm import CallType, LLMUnavailableError
from tests.unit.process_discovery.test_llm_support import (
    completion,
    connection_error,
    events,
    make_llm,
    make_settings,
    messages,
    no_text_in_logs,  # noqa: F401  (autouse fixture)
    one_call_line,
    status_error,
    timeout_error,
)


async def test_transient_errors_are_retried_until_success(caplog):
    """AC-11.10: 429, 503, then success: three attempts, two retry warnings."""
    llm, create, sleeps = make_llm([status_error(429), status_error(503), completion("ok")])
    assert await llm.generate_text(CallType.GUIDE, messages()) == "ok"
    assert create.await_count == 3
    retries = events(caplog, "llm_retry")
    assert len(retries) == 2
    assert [r.__dict__["attempt"] for r in retries] == [1, 2]
    assert [r.__dict__["status_code"] for r in retries] == [429, 503]
    assert all(r.__dict__["call_type"] == "GUIDE" for r in retries)
    assert [r.__dict__["wait_s"] for r in retries] == pytest.approx(sleeps.waits, abs=1e-3)
    assert one_call_line(caplog)["attempts"] == 3


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
async def test_every_transient_status_is_retried(status):
    """§3.4 table: 408, 429 and 5xx."""
    llm, create, _ = make_llm([status_error(status), completion("ok")])
    assert await llm.generate_text(CallType.GUIDE, messages()) == "ok"
    assert create.await_count == 2


@pytest.mark.parametrize("error", [connection_error, timeout_error], ids=["connection", "timeout"])
async def test_transport_errors_give_up_after_four_attempts(caplog, error):
    """AC-11.11: 1 + 3 retries, then `LLMUnavailableError` with `attempts == 4`."""
    llm, create, sleeps = make_llm([error() for _ in range(10)])
    with pytest.raises(LLMUnavailableError) as err:
        await llm.generate_text(CallType.GUIDE, messages())
    assert err.value.attempts == 4 and err.value.status_code is None
    assert create.await_count == 4 and len(sleeps.waits) == 3
    retries = events(caplog, "llm_retry")
    assert [r.__dict__["error_class"] for r in retries] == [error().__class__.__name__] * 3
    assert one_call_line(caplog)["outcome"] == "unavailable"


async def test_the_retry_count_follows_the_setting():
    """§3.4 rule 1: `LLM_MAX_RETRIES` bounds the attempts."""
    llm, create, _ = make_llm([status_error(503)] * 5, make_settings(llm_max_retries=0))
    with pytest.raises(LLMUnavailableError) as err:
        await llm.generate_text(CallType.GUIDE, messages())
    assert create.await_count == 1 and err.value.attempts == 1 and err.value.status_code == 503


async def test_the_last_status_code_is_reported():
    """§3.4 rule 4."""
    llm, _, _ = make_llm([status_error(429), status_error(500), status_error(502), status_error(503)])
    with pytest.raises(LLMUnavailableError) as err:
        await llm.generate_text(CallType.GUIDE, messages())
    assert err.value.status_code == 503 and err.value.attempts == 4


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
async def test_a_client_error_is_not_retried(status):
    """AC-11.12: exactly one attempt; the status code travels on the error."""
    llm, create, sleeps = make_llm([status_error(status), completion("never")])
    with pytest.raises(LLMUnavailableError) as err:
        await llm.generate_text(CallType.GUIDE, messages())
    assert err.value.status_code == status and err.value.attempts == 1
    assert create.await_count == 1 and sleeps.waits == []


async def test_an_unexpected_exception_is_wrapped_and_chained():
    """§3.4 table, last row: not retried, `status_code=None`, original chained."""
    original = KeyError("surprise")
    llm, create, _ = make_llm([original, completion("never")])
    with pytest.raises(LLMUnavailableError) as err:
        await llm.generate_text(CallType.GUIDE, messages())
    assert err.value.status_code is None and err.value.__cause__ is original
    assert create.await_count == 1


async def test_retry_after_seconds_is_honoured():
    """AC-11.13."""
    llm, _, sleeps = make_llm([status_error(429, {"retry-after": "3"}), completion("ok")])
    await llm.generate_text(CallType.GUIDE, messages())
    assert sleeps.waits == [3.0]


async def test_retry_after_ms_wins_over_seconds():
    """AC-11.13: `retry-after-ms` first, then `retry-after`."""
    llm, _, sleeps = make_llm([status_error(429, {"retry-after-ms": "1500", "retry-after": "9"}), completion("ok")])
    await llm.generate_text(CallType.GUIDE, messages())
    assert sleeps.waits == [1.5]


async def test_without_a_header_the_wait_backs_off_with_jitter():
    """AC-11.13: 1 s, 2 s, 4 s, each plus at most 25 %."""
    llm, _, sleeps = make_llm([status_error(429)] * 3 + [completion("ok")])
    await llm.generate_text(CallType.GUIDE, messages())
    assert len(sleeps.waits) == 3
    for wait, base in zip(sleeps.waits, (1, 2, 4), strict=True):
        assert base <= wait <= base * 1.25


async def test_an_unreadable_header_falls_back_to_backoff():
    llm, _, sleeps = make_llm([status_error(503, {"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"}), completion("ok")])
    await llm.generate_text(CallType.GUIDE, messages())
    assert 1 <= sleeps.waits[0] <= 1.25


async def test_the_jitter_is_deterministic_with_a_seeded_source():
    """§3.4 rule 6: injectable random source."""
    first = make_llm([status_error(429), completion("ok")])
    second = make_llm([status_error(429), completion("ok")])
    for llm, _, _ in (first, second):
        await llm.generate_text(CallType.GUIDE, messages())
    assert first[2].waits == second[2].waits


async def test_a_wait_above_the_cap_is_not_waited(caplog):
    """AC-11.14: a server asking for 45 s is not ready in time for a turn; fail fast."""
    llm, create, sleeps = make_llm([status_error(429, {"retry-after": "45"}), completion("never")])
    with pytest.raises(LLMUnavailableError) as err:
        await llm.generate_text(CallType.GUIDE, messages())
    assert err.value.status_code == 429 and err.value.attempts == 1
    assert sleeps.waits == [] and create.await_count == 1
    assert one_call_line(caplog)["outcome"] == "unavailable"


async def test_the_cap_follows_the_setting():
    """§3.4 rule 3: `LLM_RETRY_MAX_WAIT_SECONDS`."""
    llm, _, sleeps = make_llm(
        [status_error(429, {"retry-after": "45"}), completion("ok")], make_settings(llm_retry_max_wait_seconds=60)
    )
    assert await llm.generate_text(CallType.GUIDE, messages()) == "ok"
    assert sleeps.waits == [45.0]
