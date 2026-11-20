"""`FakeLLM`: scripted model replies for tests of the turn, the documents, the assessment and the API.

Why: those tests must run without a network and still prove what the product does. A fake that
accepted an empty reply or passed invalid output through would let them pass for behaviour the real
client never shows, so the fake applies the same rules as `AzureLLM`.
What: replies scripted per call type and consumed in order (text, dict, model instance or an
exception to raise); the same message check, budget clamp, budget guard, usage hook (tokens
estimated as characters / 4), empty-reply rule and single invalid-output retry as the real client;
a record of every request; loud failures when a script runs out or is left over. Implements
spec 11 §3.9 and AC-11.30.
Must not: make network calls, read the environment (settings default to the declared defaults), or
import anything from the engine except the client it stands in for (`llm.py`).
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.settings import Settings
from app.services.process_discovery.llm import (
    BudgetGuard,
    CallType,
    ChatMessage,
    LLMBudgetExceededError,
    LLMEmptyResponseError,
    LLMInvalidOutputError,
    LLMUsage,
    UsageHook,
    approx_prompt_tokens,
    check_messages,
    deployment_for,
    error_paths,
    parse_json_object,
    report_usage,
    retry_message,
    token_budget,
)

FakeReply = str | dict[str, Any] | BaseModel | Exception
Method = Literal["text", "json", "structured"]
T = TypeVar("T", bound=BaseModel)


class FakeLLMExhaustedError(AssertionError):
    """A call found no scripted reply left for its call type (or replies were left unused)."""


@dataclass(frozen=True)
class RecordedCall:
    """One request the code under test made: what it asked, with a copy of the messages."""

    call_type: CallType
    method: Method
    messages: list[ChatMessage]
    model_name: str | None
    max_tokens: int


class FakeLLM:
    """Implements `LLM` with scripted replies. One request is recorded per reply consumed."""

    def __init__(
        self,
        script: Mapping[CallType, Sequence[FakeReply]] | None = None,
        *,
        settings: Settings | None = None,
        budget_guard: BudgetGuard | None = None,
        usage_hook: UsageHook | None = None,
    ) -> None:
        self._settings = settings
        self._budget_guard = budget_guard
        self._usage_hook = usage_hook
        self._replies: dict[CallType, deque[FakeReply]] = defaultdict(deque)
        self.calls: list[RecordedCall] = []
        for call_type, replies in (script or {}).items():
            self.add(call_type, *replies)

    def add(self, call_type: CallType, *replies: FakeReply) -> None:
        """Append replies for `call_type`, consumed after those already scripted."""
        self._replies[call_type].extend(replies)

    def calls_of(self, call_type: CallType) -> list[RecordedCall]:
        return [call for call in self.calls if call.call_type is call_type]

    def assert_all_used(self) -> None:
        """Fail if any scripted reply was never consumed."""
        left = {ct.value: len(replies) for ct, replies in self._replies.items() if replies}
        if left:
            raise FakeLLMExhaustedError(f"scripted replies left unused: {left}")

    async def aclose(self) -> None:
        return None

    async def generate_text(
        self, call_type: CallType, messages: Sequence[ChatMessage], *, max_tokens: int | None = None
    ) -> str:
        return self._call(call_type, "text", messages, max_tokens, None, self._as_text)

    async def generate_json(
        self, call_type: CallType, messages: Sequence[ChatMessage], *, max_tokens: int | None = None
    ) -> dict[str, Any]:
        return self._call(call_type, "json", messages, max_tokens, None, self._as_json)

    async def generate_structured(
        self,
        model_cls: type[T],
        call_type: CallType,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int | None = None,
    ) -> T:
        def parse(reply: FakeReply) -> T:
            if isinstance(reply, BaseModel):
                if not isinstance(reply, model_cls):
                    raise TypeError(f"scripted {type(reply).__name__} is not a {model_cls.__name__}")
                return reply
            if isinstance(reply, dict):
                return model_cls.model_validate(reply)
            return model_cls.model_validate_json(str(reply))

        return self._call(call_type, "structured", messages, max_tokens, model_cls.__name__, parse)

    # --- the shared rules ---------------------------------------------------------------------------

    def _call(
        self,
        call_type: CallType,
        method: Method,
        messages: Sequence[ChatMessage],
        max_tokens: int | None,
        model_name: str | None,
        parse: Callable[[FakeReply], Any],
    ) -> Any:
        checked = check_messages(messages, call_type)
        budget = token_budget(self._settings, call_type, max_tokens)
        if self._budget_guard is not None and not self._budget_guard(call_type):
            raise LLMBudgetExceededError(f"daily budget refused a {call_type.value} call")
        reply = self._next(call_type, method, checked, model_name, budget)
        try:
            return parse(reply)
        except (ValidationError, ValueError) as first_error:
            retry = [*checked, retry_message(error_paths(first_error))]
            reply = self._next(call_type, method, retry, model_name, budget)
            try:
                return parse(reply)
            except (ValidationError, ValueError) as second_error:
                raise LLMInvalidOutputError(error_paths(second_error)) from None

    def _next(
        self, call_type: CallType, method: Method, messages: list[ChatMessage], model_name: str | None, budget: int
    ) -> FakeReply:
        """Consume and record one reply; raise it if it is an exception; apply the empty-reply rule."""
        queue = self._replies[call_type]
        if not queue:
            raise FakeLLMExhaustedError(f"no scripted reply left for {call_type.value}")
        reply = queue.popleft()
        self.calls.append(RecordedCall(call_type, method, [dict(m) for m in messages], model_name, budget))  # pyright: ignore[reportArgumentType]
        if isinstance(reply, Exception):
            raise reply
        text = reply if isinstance(reply, str) else json.dumps(_jsonable(reply))
        prompt = approx_prompt_tokens(messages)
        completion = len(text) // 4
        report_usage(
            self._usage_hook,
            LLMUsage(call_type, deployment_for(self._settings, call_type), prompt, completion, prompt + completion),
        )
        if isinstance(reply, str) and not reply.strip():
            raise LLMEmptyResponseError("empty")
        return reply

    @staticmethod
    def _as_text(reply: FakeReply) -> str:
        if not isinstance(reply, str):
            raise TypeError(f"generate_text needs a str reply, got {type(reply).__name__}")
        return reply

    @staticmethod
    def _as_json(reply: FakeReply) -> dict[str, Any]:
        if isinstance(reply, BaseModel):
            return reply.model_dump(mode="json")
        if isinstance(reply, dict):
            return json.loads(json.dumps(reply))  # a copy, as a real reply would be
        return parse_json_object(str(reply))


def _jsonable(reply: dict[str, Any] | BaseModel) -> Any:
    return reply.model_dump(mode="json") if isinstance(reply, BaseModel) else reply
