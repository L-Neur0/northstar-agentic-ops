"""Tests for the model client: creation, budgets, reply reading, guard, usage and the log line.

Why: every model call in the product goes through `AzureLLM`, so its rules (identity-only auth
outside local runs, a budget per call type, an error instead of an empty success, usage reported
even for rejected replies, one log line without text) must hold for every caller.
What: a stub SDK client replays completions; the SDK constructors and credentials are replaced
with mocks to check how `create_llm` wires them. No network. Implements spec 11, AC-11.1 to
AC-11.9, AC-11.15 to AC-11.17, AC-11.25 and AC-11.26.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from app.core.settings import Settings
from app.services.process_discovery import llm as llm_module
from app.services.process_discovery.llm import (
    CallType,
    LLMBudgetExceededError,
    LLMConfigError,
    LLMEmptyResponseError,
    LLMError,
    LLMInvalidOutputError,
    LLMUnavailableError,
    LLMUsage,
    approx_prompt_tokens,
    create_llm,
)
from tests.unit.process_discovery.test_llm_support import (
    SENTINEL,
    completion,
    demo_settings,
    events,
    make_llm,
    make_settings,
    messages,
    no_text_in_logs,  # noqa: F401  (autouse fixture)
    one_call_line,
    sent,
    status_error,
)

SCOPE = "https://cognitiveservices.azure.com/.default"


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Replace the SDK client, the credentials and the token provider with mocks."""
    mocks = {
        "AsyncAzureOpenAI": MagicMock(name="AsyncAzureOpenAI"),
        "ManagedIdentityCredential": MagicMock(name="ManagedIdentityCredential"),
        "DefaultAzureCredential": MagicMock(name="DefaultAzureCredential"),
        "get_bearer_token_provider": MagicMock(name="get_bearer_token_provider"),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(llm_module, name, mock)
    return mocks


# --- AC-11.1 to AC-11.4: creation and authentication ---------------------------------------------


def test_demo_with_an_api_key_refuses_to_start(sdk):
    """AC-11.1: keys are for a developer machine only; no client is built."""
    settings = Settings.model_construct(
        deployment_stage="demo", azure_openai_endpoint="https://example.invalid/", azure_openai_api_key="k-123"
    )
    with pytest.raises(LLMConfigError, match="only allowed in stage local"):
        create_llm(settings)
    sdk["AsyncAzureOpenAI"].assert_not_called()
    sdk["ManagedIdentityCredential"].assert_not_called()


def test_demo_uses_the_managed_identity(sdk):
    """AC-11.2: token provider for the Cognitive Services scope, from the managed identity, SDK retries off."""
    llm = create_llm(demo_settings(azure_client_id="client-id-1"))
    sdk["ManagedIdentityCredential"].assert_called_once_with(client_id="client-id-1")
    credential = sdk["ManagedIdentityCredential"].return_value
    sdk["get_bearer_token_provider"].assert_called_once_with(credential, SCOPE)
    kwargs = sdk["AsyncAzureOpenAI"].call_args.kwargs
    assert kwargs["azure_ad_token_provider"] is sdk["get_bearer_token_provider"].return_value
    assert kwargs["max_retries"] == 0
    assert "api_key" not in kwargs
    assert kwargs["azure_endpoint"] == "https://example.invalid/"
    assert kwargs["api_version"] == "2025-04-01-preview"
    sdk["DefaultAzureCredential"].assert_not_called()
    assert llm is not None


def test_demo_without_a_client_id_uses_the_default_credential(sdk):
    """AC-11.2 (table, last column): an empty `AZURE_CLIENT_ID` falls back to `DefaultAzureCredential`."""
    create_llm(demo_settings())
    sdk["ManagedIdentityCredential"].assert_not_called()
    sdk["DefaultAzureCredential"].assert_called_once_with()


def test_local_with_a_key_uses_the_key(sdk):
    """AC-11.3."""
    create_llm(make_settings(azure_openai_api_key="k-local"))
    kwargs = sdk["AsyncAzureOpenAI"].call_args.kwargs
    assert kwargs["api_key"] == "k-local"
    assert kwargs["max_retries"] == 0
    assert "azure_ad_token_provider" not in kwargs
    sdk["DefaultAzureCredential"].assert_not_called()


@pytest.mark.parametrize("key", [None, ""])
def test_local_without_a_key_uses_the_default_credential(sdk, key):
    """AC-11.3: an empty key counts as not set (the SDK rejects an empty key)."""
    create_llm(make_settings(azure_openai_api_key=key))
    sdk["DefaultAzureCredential"].assert_called_once_with()
    sdk["get_bearer_token_provider"].assert_called_once_with(sdk["DefaultAzureCredential"].return_value, SCOPE)
    kwargs = sdk["AsyncAzureOpenAI"].call_args.kwargs
    assert "api_key" not in kwargs and kwargs["max_retries"] == 0


@pytest.mark.parametrize(
    ("values", "key"),
    [
        ({"azure_openai_endpoint": None}, "AZURE_OPENAI_ENDPOINT"),
        ({"azure_openai_endpoint": ""}, "AZURE_OPENAI_ENDPOINT"),
        (
            {"azure_openai_endpoint": "https://secret-endpoint.example/", "azure_openai_deployment": ""},
            "AZURE_OPENAI_DEPLOYMENT",
        ),
    ],
)
def test_a_missing_setting_is_named(sdk, values, key):
    """AC-11.4: the key is named, its value never."""
    with pytest.raises(LLMConfigError) as err:
        create_llm(make_settings(**values))
    assert key in str(err.value)
    assert "secret-endpoint" not in str(err.value)
    sdk["AsyncAzureOpenAI"].assert_not_called()


async def test_aclose_closes_the_client_and_the_credential():
    """§3.1: shutdown closes the HTTP client and the credential."""
    credential = MagicMock()
    credential.close = AsyncMock()
    llm, _, _ = make_llm([], credential=credential)
    await llm.aclose()
    llm._client.close.assert_awaited_once()  # pyright: ignore[reportAttributeAccessIssue]
    credential.close.assert_awaited_once()


# --- AC-11.5, AC-11.6: deployment, timeout and budget per call type --------------------------------


@pytest.mark.parametrize("call_type", list(CallType))
async def test_each_request_carries_timeout_deployment_and_budget(call_type):
    """AC-11.5: and no `temperature` or `top_p` (§3.2 rule 8)."""
    settings = make_settings(azure_openai_deployment="app-chat", azure_openai_eval_deployment="eval-expert")
    llm, create, _ = make_llm([completion()], settings)
    await llm.generate_text(call_type, messages())
    kwargs = sent(create)
    assert kwargs["timeout"] == 60
    assert kwargs["model"] == ("eval-expert" if call_type is CallType.EXPERT else "app-chat")
    assert kwargs["max_completion_tokens"] == getattr(settings, f"llm_max_tokens_{call_type.value.lower()}")
    assert "temperature" not in kwargs and "top_p" not in kwargs and "max_tokens" not in kwargs


def test_the_default_budgets_match_the_spec():
    """AC-11.5: §3.2 table."""
    settings = make_settings()
    budgets = {ct: getattr(settings, f"llm_max_tokens_{ct.value.lower()}") for ct in CallType}
    assert budgets[CallType.GUIDE] == 100_000 and budgets[CallType.OPPORTUNITIES] == 100_000
    assert all(v == 32_000 for ct, v in budgets.items() if ct not in (CallType.GUIDE, CallType.OPPORTUNITIES))


def test_the_step_assessment_has_its_own_call_type_and_budget():
    """AC-11.5 / spec 26 §5: `ASSESS_STEPS` exists, with `LLM_MAX_TOKENS_ASSESS_STEPS` (default 32000, same range)."""
    assert CallType.ASSESS_STEPS.value == "ASSESS_STEPS"
    assert make_settings().llm_max_tokens_assess_steps == 32_000
    assert make_settings(llm_max_tokens_assess_steps=128_000).llm_max_tokens_assess_steps == 128_000
    with pytest.raises(ValidationError):
        make_settings(llm_max_tokens_assess_steps=99)


async def test_an_expert_call_without_an_evaluation_deployment_fails_when_made():
    """AC-11.5 / §3.1 rule 5: the app does not need the evaluation deployment to start."""
    llm, create, _ = make_llm([completion()], make_settings(azure_openai_eval_deployment=""))
    with pytest.raises(LLMConfigError, match="AZURE_OPENAI_EVAL_DEPLOYMENT"):
        await llm.generate_text(CallType.EXPERT, messages())
    create.assert_not_awaited()


@pytest.mark.parametrize(("requested", "expected"), [(1_000_000, 32_000), (32_000, 32_000), (500, 500)])
async def test_a_caller_can_lower_the_budget_but_never_raise_it(requested, expected):
    """AC-11.6."""
    llm, create, _ = make_llm([completion()])
    await llm.generate_text(CallType.EXTRACT, messages(), max_tokens=requested)
    assert sent(create)["max_completion_tokens"] == expected


# --- AC-11.7 to AC-11.9: reading the reply --------------------------------------------------------


async def test_a_normal_completion_is_returned_unchanged():
    """AC-11.7."""
    text = f"  Which department are you in?\n {SENTINEL} "
    llm, create, _ = make_llm([completion(text)])
    assert await llm.generate_text(CallType.GUIDE, messages()) == text
    assert sent(create)["messages"] == messages()


EMPTY_CASES = [
    pytest.param(completion(choices=False), "no_choices", "empty", id="no_choices"),
    pytest.param(completion(None, refusal=f"I cannot help {SENTINEL}"), "refused", "refused", id="refused"),
    pytest.param(
        completion(f"half a JSON {{ {SENTINEL}", finish_reason="length"), "truncated", "truncated", id="truncated"
    ),
    pytest.param(
        completion(f"x {SENTINEL}", finish_reason="content_filter"), "content_filter", "content_filter", id="filter"
    ),
    pytest.param(completion(None), "empty", "empty", id="none"),
    pytest.param(completion(""), "empty", "empty", id="empty"),
    pytest.param(completion(" \n\t "), "empty", "empty", id="whitespace"),
]


@pytest.mark.parametrize(("response", "reason", "outcome"), EMPTY_CASES)
async def test_an_unusable_reply_is_an_error(caplog, response, reason, outcome):
    """AC-11.8: never an empty success; the error carries the reason code only."""
    llm, create, _ = make_llm([response])
    with pytest.raises(LLMEmptyResponseError) as err:
        await llm.generate_text(CallType.GUIDE, messages())
    assert err.value.reason == reason
    assert SENTINEL not in str(err.value) and "cannot help" not in str(err.value)
    assert create.await_count == 1  # not retried (§3.5 rule 4)
    line = one_call_line(caplog)
    assert line["outcome"] == outcome and line["level"] == "WARNING"


async def test_the_checks_run_in_table_order():
    """AC-11.8 / §3.5 rule 1: a refusal that is also cut short reports `refused`."""
    llm, _, _ = make_llm([completion(None, refusal="no", finish_reason="length")])
    with pytest.raises(LLMEmptyResponseError) as err:
        await llm.generate_text(CallType.GUIDE, messages())
    assert err.value.reason == "refused"


@pytest.mark.parametrize(
    "cls", [LLMConfigError, LLMBudgetExceededError, LLMUnavailableError, LLMEmptyResponseError, LLMInvalidOutputError]
)
def test_every_client_error_is_a_runtime_error(cls):
    """AC-11.9: a broad `except RuntimeError` in a caller still catches them."""
    assert issubclass(cls, LLMError) and issubclass(cls, RuntimeError)


def test_error_attributes():
    """AC-11.9 / §4: the attributes callers read."""
    assert LLMUnavailableError(503).status_code == 503
    assert LLMUnavailableError(None, attempts=4).attempts == 4
    assert LLMEmptyResponseError("truncated").reason == "truncated"
    assert LLMInvalidOutputError(["steps.0.name"]).paths == ["steps.0.name"]


@pytest.mark.parametrize(
    "bad",
    [
        [{"role": "tool", "content": "x"}],
        [{"role": "user", "content": 42}],
        [{"role": "user"}],
        [{"role": "user", "content": "x", "name": "n"}],
        ["just a string"],
    ],
)
async def test_a_malformed_message_is_refused_before_any_request(bad):
    """§3.3 step 1."""
    llm, create, _ = make_llm([completion()])
    with pytest.raises(ValueError):
        await llm.generate_text(CallType.GUIDE, bad)
    create.assert_not_awaited()


# --- AC-11.15: cancellation -----------------------------------------------------------------------


async def test_cancelling_while_waiting_propagates_and_is_logged(caplog):
    """AC-11.15: the 150 s turn guard cancels the call; the client must not swallow it."""
    started = asyncio.Event()

    async def forever(_seconds: float) -> None:
        started.set()
        await asyncio.Event().wait()

    llm, _, _ = make_llm([status_error(503), completion()], sleep=forever)
    task = asyncio.create_task(llm.generate_text(CallType.GUIDE, messages()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert one_call_line(caplog)["outcome"] == "cancelled"


# --- AC-11.16: budget guard -----------------------------------------------------------------------


async def test_the_budget_guard_refuses_before_any_request(caplog):
    """AC-11.16."""
    asked: list[CallType] = []

    def guard(call_type: CallType) -> bool:
        asked.append(call_type)
        return False

    llm, create, _ = make_llm([completion()], budget_guard=guard)
    with pytest.raises(LLMBudgetExceededError):
        await llm.generate_text(CallType.GUIDE, messages())
    create.assert_not_awaited()
    assert asked == [CallType.GUIDE]
    assert one_call_line(caplog)["outcome"] == "budget_refused"


async def test_the_guard_is_asked_once_per_call_not_per_retry():
    """§3.3 step 2."""
    asked: list[CallType] = []
    llm, _, _ = make_llm([status_error(503), completion()], budget_guard=lambda ct: asked.append(ct) is None)
    await llm.generate_text(CallType.GUIDE, messages())
    assert asked == [CallType.GUIDE]


# --- AC-11.17: usage hook -------------------------------------------------------------------------


class Answer(BaseModel):
    answer: str


async def test_usage_is_reported_once_per_response():
    """AC-11.17."""
    seen: list[LLMUsage] = []
    llm, _, _ = make_llm([completion(usage=(100, 20, 120))], usage_hook=seen.append)
    await llm.generate_text(CallType.EXTRACT, messages())
    assert seen == [LLMUsage(CallType.EXTRACT, "app-chat", 100, 20, 120)]


async def test_usage_of_a_rejected_reply_is_still_reported():
    """AC-11.17: the tokens were spent even if the reply was truncated."""
    seen: list[LLMUsage] = []
    llm, _, _ = make_llm([completion("cut", finish_reason="length", usage=(50, 9, 59))], usage_hook=seen.append)
    with pytest.raises(LLMEmptyResponseError):
        await llm.generate_text(CallType.GUIDE, messages())
    assert [u.total_tokens for u in seen] == [59]


async def test_usage_of_an_invalid_reply_is_still_reported():
    """AC-11.17: invalid then valid structured output is two responses, two reports."""
    seen: list[LLMUsage] = []
    replies = [completion("not json", usage=(10, 1, 11)), completion('{"answer": "ok"}', usage=(12, 2, 14))]
    llm, _, _ = make_llm(replies, usage_hook=seen.append)
    assert (await llm.generate_structured(Answer, CallType.MAP, messages())).answer == "ok"
    assert [u.total_tokens for u in seen] == [11, 14]


async def test_a_response_without_usage_reports_nothing():
    seen: list[LLMUsage] = []
    llm, _, _ = make_llm([completion(usage=None)], usage_hook=seen.append)
    await llm.generate_text(CallType.GUIDE, messages())
    assert seen == []


async def test_a_failing_hook_does_not_change_the_result(caplog):
    """AC-11.17: the hook's error is logged by class and swallowed."""

    def hook(_usage: LLMUsage) -> None:
        raise RuntimeError(f"store down {SENTINEL}")

    llm, _, _ = make_llm([completion("fine")], usage_hook=hook)
    assert await llm.generate_text(CallType.GUIDE, messages()) == "fine"
    [failure] = events(caplog, "llm_usage_hook_failed")
    assert failure.__dict__["error_class"] == "RuntimeError"


# --- AC-11.25: the log line -----------------------------------------------------------------------

LINE_FIELDS = {
    "call_type",
    "deployment",
    "served_model",
    "outcome",
    "attempts",
    "invalid_retry",
    "duration_ms",
    "max_tokens",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "approx_prompt_tokens",
    "finish_reason",
}


async def test_an_ok_call_logs_one_info_line_with_every_field(caplog):
    """AC-11.25 and the worked example of §3.8."""
    llm, _, _ = make_llm([status_error(429), completion(usage=(5210, 84, 5294))])
    await llm.generate_text(CallType.GUIDE, messages(), max_tokens=600)
    line = one_call_line(caplog)
    assert LINE_FIELDS <= set(line)
    assert line["msg"] == "llm_call" and line["logger"] == "app.llm" and line["level"] == "INFO"
    assert line["call_type"] == "GUIDE" and line["deployment"] == "app-chat"
    assert line["served_model"] == "gpt-test-2026-01-01"
    assert line["outcome"] == "ok" and line["attempts"] == 2 and line["invalid_retry"] is False
    assert line["max_tokens"] == 600 and line["finish_reason"] == "stop"
    assert (line["prompt_tokens"], line["completion_tokens"], line["total_tokens"]) == (5210, 84, 5294)
    assert line["approx_prompt_tokens"] == approx_prompt_tokens(messages())
    assert isinstance(line["duration_ms"], int)
    assert "status_code" not in line


async def test_tokens_are_summed_over_attempts(caplog):
    """§3.8: usage summed over the two requests of an invalid-output retry."""
    replies = [completion("[]", usage=(10, 1, 11)), completion('{"answer": "ok"}', usage=(12, 2, 14))]
    llm, _, _ = make_llm(replies)
    await llm.generate_structured(Answer, CallType.MAP, messages())
    line = one_call_line(caplog)
    assert (line["prompt_tokens"], line["completion_tokens"], line["total_tokens"]) == (22, 3, 25)
    assert line["invalid_retry"] is True and line["attempts"] == 2


async def test_an_unavailable_call_logs_its_status_code(caplog):
    """AC-11.25: `status_code` only on `unavailable`."""
    llm, _, _ = make_llm([status_error(401)])
    with pytest.raises(LLMUnavailableError):
        await llm.generate_text(CallType.GUIDE, messages())
    line = one_call_line(caplog)
    assert line["outcome"] == "unavailable" and line["status_code"] == 401 and line["level"] == "WARNING"
    assert line["served_model"] == ""


async def run_outcome(outcome: str) -> None:
    """Drive one call to `outcome`, swallowing the expected error."""
    plan: dict[str, tuple[list[Any], dict[str, Any]]] = {
        "ok": ([completion('{"P01": "Finance"}')], {}),
        "empty": ([completion(None)], {}),
        "refused": ([completion(None, refusal="no")], {}),
        "truncated": ([completion("x", finish_reason="length")], {}),
        "content_filter": ([completion("x", finish_reason="content_filter")], {}),
        "invalid_output": ([completion("nope"), completion("[1]")], {}),
        "unavailable": ([status_error(404)], {}),
        "budget_refused": ([], {"budget_guard": lambda _ct: False}),
    }
    responses, kwargs = plan[outcome]
    llm, _, _ = make_llm(responses, **kwargs)
    try:
        await llm.generate_json(CallType.EXTRACT, messages())
    except LLMError:
        pass


@pytest.mark.parametrize(
    "outcome",
    ["ok", "empty", "refused", "truncated", "content_filter", "invalid_output", "unavailable", "budget_refused"],
)
async def test_every_outcome_logs_exactly_one_line(caplog, outcome):
    """AC-11.25: one line per call whatever happens, WARNING unless ok."""
    await run_outcome(outcome)
    line = one_call_line(caplog)
    assert line["outcome"] == outcome
    assert LINE_FIELDS <= set(line)
    assert line["level"] == ("INFO" if outcome == "ok" else "WARNING")


async def test_the_deployment_is_sanitised_in_the_log(caplog):
    """§3.8: `deployment` goes through `sanitize_log`."""
    llm, _, _ = make_llm([completion()], make_settings(azure_openai_deployment="app\nchat"))
    await llm.generate_text(CallType.GUIDE, messages())
    assert one_call_line(caplog)["deployment"] == "app chat"


def test_approx_prompt_tokens_is_characters_over_four():
    """§4."""
    msgs: list[Any] = [{"role": "system", "content": "a" * 40}, {"role": "user", "content": "b" * 4}]
    assert approx_prompt_tokens(msgs) == 11
    assert approx_prompt_tokens([]) == 0


# --- AC-11.26: served model changes -----------------------------------------------------------------


async def test_a_changed_served_model_is_warned_once(caplog):
    """AC-11.26: catches a silent model upgrade behind the same deployment name."""
    replies = [completion(model="gpt-a"), completion(model="gpt-b"), completion(model="gpt-b")]
    llm, _, _ = make_llm(replies)
    for _ in range(3):
        await llm.generate_text(CallType.GUIDE, messages())
    [warning] = events(caplog, "llm_model_changed")
    assert warning.levelno == logging.WARNING
    assert (warning.__dict__["first"], warning.__dict__["now"]) == ("gpt-a", "gpt-b")
    assert warning.__dict__["deployment"] == "app-chat"


async def test_the_same_served_model_is_not_warned(caplog):
    llm, _, _ = make_llm([completion(model="gpt-a"), completion(model="gpt-a")])
    await llm.generate_text(CallType.GUIDE, messages())
    await llm.generate_text(CallType.GUIDE, messages())
    assert events(caplog, "llm_model_changed") == []
