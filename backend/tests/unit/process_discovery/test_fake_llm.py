"""Tests for `FakeLLM`, the scripted stand-in for the model client (spec 11 §3.9).

Why: the turn, the documents, the assessment and the API are tested without a network, through
`FakeLLM`. If the fake were more forgiving than the real client (an empty reply accepted, an invalid
reply passed through), those tests would prove behaviour the product does not have.
What: scripts replies per call type and checks ordering, recording, scripted exceptions, the
empty-reply and invalid-output rules, the budget clamp, the guard, the usage hook and the loud
failures. Implements spec 11, AC-11.30.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.services.process_discovery.fake_llm import FakeLLM, FakeLLMExhaustedError, RecordedCall
from app.services.process_discovery.llm import (
    LLM,
    CallType,
    ChatMessage,
    LLMBudgetExceededError,
    LLMEmptyResponseError,
    LLMInvalidOutputError,
    LLMUnavailableError,
    LLMUsage,
)


class Answer(BaseModel):
    answer: str


def msgs(text: str = "hello") -> list[ChatMessage]:
    return [{"role": "system", "content": "sys"}, {"role": "user", "content": text}]


def test_the_fake_implements_the_protocol():
    """AC-11.30: the same `LLM` protocol as the real client."""
    fake: LLM = FakeLLM()
    assert fake is not None


async def test_replies_come_back_per_call_type_in_order():
    """AC-11.30."""
    fake = FakeLLM(
        {CallType.GUIDE: ["Which department are you in?", "How often?"], CallType.EXTRACT: [{"P01": "Finance"}]}
    )
    assert await fake.generate_text(CallType.GUIDE, msgs()) == "Which department are you in?"
    assert await fake.generate_json(CallType.EXTRACT, msgs()) == {"P01": "Finance"}
    assert await fake.generate_text(CallType.GUIDE, msgs()) == "How often?"
    fake.assert_all_used()


async def test_add_appends_replies():
    fake = FakeLLM()
    fake.add(CallType.MAP, Answer(answer="a"), '{"answer": "b"}', {"answer": "c"})
    assert (await fake.generate_structured(Answer, CallType.MAP, msgs())).answer == "a"
    assert (await fake.generate_structured(Answer, CallType.MAP, msgs())).answer == "b"
    assert (await fake.generate_structured(Answer, CallType.MAP, msgs())).answer == "c"


async def test_a_json_string_is_parsed_for_generate_json():
    fake = FakeLLM({CallType.EXTRACT: ['{"P01": "Finance"}']})
    assert await fake.generate_json(CallType.EXTRACT, msgs()) == {"P01": "Finance"}


async def test_every_call_is_recorded_with_a_copy_of_the_messages():
    """AC-11.30: call type, method, messages (copied), model name and max tokens."""
    fake = FakeLLM({CallType.GUIDE: ["q"], CallType.MAP: [{"answer": "a"}]})
    sent = msgs()
    await fake.generate_text(CallType.GUIDE, sent, max_tokens=600)
    await fake.generate_structured(Answer, CallType.MAP, sent)
    sent[1]["content"] = "mutated later"
    assert fake.calls == [
        RecordedCall(CallType.GUIDE, "text", msgs(), None, 600),
        RecordedCall(CallType.MAP, "structured", msgs(), "Answer", 32_000),
    ]
    assert fake.calls_of(CallType.MAP) == [fake.calls[1]]


async def test_the_budget_is_clamped_to_the_setting():
    """AC-11.30: like the real client, a caller can lower the budget but never raise it."""
    fake = FakeLLM({CallType.GUIDE: ["a", "b"]})
    await fake.generate_text(CallType.GUIDE, msgs(), max_tokens=10**6)
    await fake.generate_text(CallType.GUIDE, msgs(), max_tokens=100)
    assert [c.max_tokens for c in fake.calls] == [100_000, 100]


async def test_scripted_exceptions_are_raised():
    """AC-11.30."""
    fake = FakeLLM({CallType.GUIDE: [LLMEmptyResponseError("truncated"), LLMUnavailableError(503)]})
    with pytest.raises(LLMEmptyResponseError) as empty:
        await fake.generate_text(CallType.GUIDE, msgs())
    assert empty.value.reason == "truncated"
    with pytest.raises(LLMUnavailableError) as unavailable:
        await fake.generate_text(CallType.GUIDE, msgs())
    assert unavailable.value.status_code == 503


@pytest.mark.parametrize("reply", ["", "   \n"])
@pytest.mark.parametrize("method", ["text", "json", "structured"])
async def test_an_empty_reply_is_an_error(reply, method):
    """AC-11.30: the empty-reply rule of the real client."""
    fake = FakeLLM({CallType.MAP: [reply]})
    with pytest.raises(LLMEmptyResponseError) as err:
        if method == "text":
            await fake.generate_text(CallType.MAP, msgs())
        elif method == "json":
            await fake.generate_json(CallType.MAP, msgs())
        else:
            await fake.generate_structured(Answer, CallType.MAP, msgs())
    assert err.value.reason == "empty"


async def test_an_invalid_reply_consumes_the_next_one_as_the_retry():
    """AC-11.30: the invalid-output rule of the real client, including the retry message."""
    fake = FakeLLM({CallType.MAP: ['{"wrong": 1}', {"answer": "ok"}]})
    assert (await fake.generate_structured(Answer, CallType.MAP, msgs())).answer == "ok"
    first, retry = fake.calls
    assert retry.messages[:-1] == first.messages
    assert retry.messages[-1]["role"] == "user" and "answer" in retry.messages[-1]["content"]


async def test_two_invalid_replies_raise():
    """AC-11.30."""
    fake = FakeLLM({CallType.EXTRACT: ["[1, 2]", "not json"]})
    with pytest.raises(LLMInvalidOutputError):
        await fake.generate_json(CallType.EXTRACT, msgs())


async def test_a_model_of_the_wrong_class_is_a_test_bug():
    fake = FakeLLM({CallType.MAP: [Answer(answer="a")]})

    class Other(BaseModel):
        answer: str

    with pytest.raises(TypeError):
        await fake.generate_structured(Other, CallType.MAP, msgs())


async def test_an_exhausted_call_type_fails_loudly():
    """AC-11.30: the error names the call type."""
    fake = FakeLLM({CallType.GUIDE: ["only one"]})
    await fake.generate_text(CallType.GUIDE, msgs())
    with pytest.raises(FakeLLMExhaustedError, match="GUIDE"):
        await fake.generate_text(CallType.GUIDE, msgs())
    with pytest.raises(FakeLLMExhaustedError, match="CLASSIFY"):
        await fake.generate_text(CallType.CLASSIFY, msgs())


def test_assert_all_used_fails_when_replies_remain():
    """AC-11.30."""
    fake = FakeLLM({CallType.GUIDE: ["unused"]})
    with pytest.raises(AssertionError, match="GUIDE"):
        fake.assert_all_used()


async def test_the_budget_guard_works_the_same():
    """AC-11.30: guard refuses before a reply is consumed."""
    fake = FakeLLM({CallType.GUIDE: ["q"]}, budget_guard=lambda _ct: False)
    with pytest.raises(LLMBudgetExceededError):
        await fake.generate_text(CallType.GUIDE, msgs())
    assert fake.calls == []
    with pytest.raises(AssertionError):
        fake.assert_all_used()


async def test_usage_is_estimated_as_characters_over_four():
    """AC-11.30: tokens estimated as characters / 4; a failing hook is swallowed."""
    seen: list[LLMUsage] = []
    fake = FakeLLM({CallType.EXPERT: ["x" * 40]}, usage_hook=seen.append)
    await fake.generate_text(CallType.EXPERT, [{"role": "user", "content": "y" * 80}])
    assert seen == [LLMUsage(CallType.EXPERT, "eval-expert", 20, 10, 30)]

    def broken(_usage: LLMUsage) -> None:
        raise RuntimeError("hook down")

    fake = FakeLLM({CallType.GUIDE: ["q"]}, usage_hook=broken)
    assert await fake.generate_text(CallType.GUIDE, msgs()) == "q"


async def test_malformed_messages_are_refused():
    """Same message check as the real client."""
    fake = FakeLLM({CallType.GUIDE: ["q"]})
    with pytest.raises(ValueError):
        await fake.generate_text(CallType.GUIDE, [{"role": "tool", "content": "x"}])  # pyright: ignore[reportArgumentType]


async def test_aclose_is_a_no_op():
    await FakeLLM().aclose()
