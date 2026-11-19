"""Tests for structured and JSON output in the model client (spec 11 §3.6).

Why: every AI output the engine stores passes a strict schema and a Pydantic model. An invalid reply
gets exactly one more chance, with a message that names the failing fields and never repeats input
values; a second failure is an error the caller turns into its fallback, never a third request.
What: a stub SDK client replays valid and invalid replies to `generate_structured` and
`generate_json`; the tests check what was sent and what came back. Implements spec 11, AC-11.21 to
AC-11.24.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.services.process_discovery.json_schema import strict_json_schema
from app.services.process_discovery.llm import CallType, LLMEmptyResponseError, LLMInvalidOutputError
from tests.unit.process_discovery.test_llm_support import (
    SENTINEL,
    completion,
    make_llm,
    messages,
    no_text_in_logs,  # noqa: F401  (autouse fixture)
    one_call_line,
    sent,
)


class Step(BaseModel):
    number: int
    name: str


class MapOut(BaseModel):
    steps: list[Step]
    summary: str


VALID = '{"steps": [{"number": 1, "name": "Collect invoices"}], "summary": "One step"}'
INVALID = f'{{"steps": [{{"number": "{SENTINEL}"}}]}}'


async def test_the_strict_schema_is_sent_and_an_instance_returned():
    """AC-11.21."""
    llm, create, _ = make_llm([completion(VALID)])
    result = await llm.generate_structured(MapOut, CallType.MAP, messages())
    assert isinstance(result, MapOut)
    assert result.steps[0].name == "Collect invoices"
    assert sent(create)["response_format"] == strict_json_schema(MapOut, "MapOut")
    assert create.await_count == 1


async def test_an_invalid_reply_gets_one_retry_naming_the_paths():
    """AC-11.22: the retry adds one `user` message with field paths and no input values."""
    llm, create, _ = make_llm([completion(INVALID), completion(VALID)])
    result = await llm.generate_structured(MapOut, CallType.MAP, messages())
    assert result.summary == "One step"
    assert create.await_count == 2
    first, second = sent(create, 0)["messages"], sent(create, 1)["messages"]
    assert first == messages()
    assert second[:-1] == first and len(second) == len(first) + 1
    extra = second[-1]
    assert extra["role"] == "user"
    assert "steps.0.number" in extra["content"] and "steps.0.name" in extra["content"] and "summary" in extra["content"]
    assert extra["content"].startswith("Your previous reply did not match the required format (problems at: ")
    assert extra["content"].endswith("). Reply again with JSON only, matching the format exactly.")
    assert SENTINEL not in extra["content"]
    assert sent(create, 1)["response_format"] == sent(create, 0)["response_format"]


async def test_the_retry_message_lists_at_most_ten_paths():
    """§3.6 rule 3."""
    many = '{"steps": [' + ",".join(["{}"] * 12) + "]}"
    llm, create, _ = make_llm([completion(many), completion(VALID)])
    await llm.generate_structured(MapOut, CallType.MAP, messages())
    listed = sent(create, 1)["messages"][-1]["content"].split("(problems at: ")[1].split(")")[0]
    assert len(listed.split(", ")) == 10


async def test_two_invalid_replies_raise_with_the_paths(caplog):
    """AC-11.23: no third request."""
    llm, create, _ = make_llm([completion(INVALID), completion('{"steps": []}'), completion(VALID)])
    with pytest.raises(LLMInvalidOutputError) as err:
        await llm.generate_structured(MapOut, CallType.MAP, messages())
    assert err.value.paths == ["summary"]
    assert create.await_count == 2
    assert SENTINEL not in str(err.value)
    line = one_call_line(caplog)
    assert line["outcome"] == "invalid_output" and line["invalid_retry"] is True


async def test_an_empty_reply_does_not_use_up_the_invalid_retry():
    """§3.6 rule 4: raised as is, no second request."""
    llm, create, _ = make_llm([completion(VALID, finish_reason="length"), completion(VALID)])
    with pytest.raises(LLMEmptyResponseError):
        await llm.generate_structured(MapOut, CallType.MAP, messages())
    assert create.await_count == 1


async def test_an_empty_reply_on_the_retry_is_raised_as_is():
    """§3.6 rule 4."""
    llm, create, _ = make_llm([completion("nope"), completion(None, refusal="no")])
    with pytest.raises(LLMEmptyResponseError) as err:
        await llm.generate_structured(MapOut, CallType.MAP, messages())
    assert err.value.reason == "refused" and create.await_count == 2


async def test_generate_json_sends_json_object_and_returns_a_dict():
    """AC-11.24."""
    llm, create, _ = make_llm([completion('{"P01": "Finance", "P02": null}')])
    assert await llm.generate_json(CallType.EXTRACT, messages()) == {"P01": "Finance", "P02": None}
    assert sent(create)["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("bad", ['["P01", "Finance"]', "not json at all", '"just a string"', "42"])
async def test_generate_json_retries_a_reply_that_is_not_an_object(bad):
    """AC-11.24: an array or non-JSON counts as invalid and gets the one retry."""
    llm, create, _ = make_llm([completion(bad), completion('{"P01": "Finance"}')])
    assert await llm.generate_json(CallType.EXTRACT, messages()) == {"P01": "Finance"}
    assert create.await_count == 2
    assert sent(create, 1)["messages"][-1]["role"] == "user"


async def test_generate_json_gives_up_after_two_invalid_replies():
    """AC-11.24 with AC-11.23."""
    llm, create, _ = make_llm([completion("[]"), completion("nope"), completion("{}")])
    with pytest.raises(LLMInvalidOutputError):
        await llm.generate_json(CallType.EXTRACT, messages())
    assert create.await_count == 2


async def test_generate_text_sends_no_response_format():
    llm, create, _ = make_llm([completion("hi")])
    await llm.generate_text(CallType.GUIDE, messages())
    assert "response_format" not in sent(create)
