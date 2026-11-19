"""Shared stubs for the LLM client tests (spec 11 §7); this module holds no tests of its own.

Why: the client tests are split by concern (creation and reply reading, retries, structured output,
cache), and each needs the same stub SDK client, completions, `openai` errors built on real
`httpx` responses, a recording sleep and settings built from explicit values. One copy keeps them
consistent.
What: helpers plus one autouse fixture, `no_text_in_logs`, that every LLM test module imports. It
puts a sentinel string in every message and reply and fails the test if any log record (or the
JSON line it formats to) contains it: spec 11 AC-11.25. No network, no environment reads.
"""

from __future__ import annotations

import json
import logging
import random
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import openai
import pytest

from app.core.logging import JsonFormatter
from app.core.settings import Settings
from app.services.process_discovery.llm import AzureLLM, ChatMessage

SENTINEL = "SENTINEL-7f3a9"
REQUEST = httpx.Request("POST", "https://example.invalid/openai/deployments/x/chat/completions")


def make_settings(**values: Any) -> Settings:
    """Local settings from explicit values only (no `.env`), with an endpoint set."""
    values.setdefault("azure_openai_endpoint", "https://example.invalid/")
    values.setdefault("llm_cache_enabled", False)
    return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


def demo_settings(**values: Any) -> Settings:
    """Valid demo-stage settings (cosmos, real workspace secrets)."""
    return make_settings(
        deployment_stage="demo",
        store="cosmos",
        cosmos_endpoint="https://cosmos.example.invalid/",
        workspace_code_specialist="s-123456",
        workspace_code_engineer="e-123456",
        workspace_token_secret="x" * 32,
        **values,
    )


def messages(extra: str = "") -> list[ChatMessage]:
    """A system and a user message, both carrying the sentinel."""
    return [
        {"role": "system", "content": f"You guide the interview. {SENTINEL}"},
        {"role": "user", "content": f"I run the monthly cost review. {SENTINEL} {extra}"},
    ]


def completion(
    content: str | None = f"Which department are you in? {SENTINEL}",
    *,
    finish_reason: str = "stop",
    refusal: str | None = None,
    choices: bool = True,
    model: str = "gpt-test-2026-01-01",
    usage: tuple[int, int, int] | None = (100, 20, 120),
) -> SimpleNamespace:
    """A chat completion shaped like the SDK's."""
    message = SimpleNamespace(content=content, refusal=refusal)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    tokens = (
        SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1], total_tokens=usage[2]) if usage else None
    )
    return SimpleNamespace(choices=[choice] if choices else [], model=model, usage=tokens)


def status_error(status: int, headers: dict[str, str] | None = None) -> openai.APIStatusError:
    """An SDK status error whose message carries the sentinel (it must never be logged)."""
    response = httpx.Response(status, headers=headers or {}, request=REQUEST)
    return openai.APIStatusError(f"error {status}: {SENTINEL}", response=response, body={"detail": SENTINEL})


def connection_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(message=f"connection reset {SENTINEL}", request=REQUEST)


def timeout_error() -> openai.APITimeoutError:
    return openai.APITimeoutError(request=REQUEST)


class Sleeps:
    """An injectable `sleep` that records the waits and returns at once."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def stub_client(responses: list[Any]) -> SimpleNamespace:
    """A stand-in for `AsyncAzureOpenAI`: `chat.completions.create` replays `responses` in order."""
    create = AsyncMock(side_effect=responses)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=AsyncMock())


def make_llm(
    responses: list[Any], settings: Settings | None = None, **kwargs: Any
) -> tuple[AzureLLM, AsyncMock, Sleeps]:
    """An `AzureLLM` over a stub client; returns the client, its `create` mock and the sleeps."""
    client = stub_client(responses)
    sleeps = Sleeps()
    kwargs.setdefault("sleep", sleeps)
    kwargs.setdefault("rng", random.Random(7))
    llm = AzureLLM(cast(Any, client), settings or make_settings(), **kwargs)
    return llm, client.chat.completions.create, sleeps


def sent(create: AsyncMock, index: int = -1) -> dict[str, Any]:
    """The keyword arguments of one request."""
    return dict(create.await_args_list[index].kwargs)


def events(caplog: pytest.LogCaptureFixture, name: str) -> list[logging.LogRecord]:
    """The captured records of one event."""
    return [r for r in caplog.records if r.getMessage() == name]


def one_call_line(caplog: pytest.LogCaptureFixture) -> dict[str, Any]:
    """The single `llm_call` line, as the JSON the formatter writes."""
    records = events(caplog, "llm_call")
    assert len(records) == 1, f"expected one llm_call line, got {len(records)}"
    return json.loads(JsonFormatter().format(records[0]))


@pytest.fixture(autouse=True)
def no_text_in_logs(caplog: pytest.LogCaptureFixture):
    """AC-11.25: no log record, formatted or raw, carries message, reply or SDK error text."""
    caplog.set_level(logging.DEBUG)
    yield
    formatter = JsonFormatter()
    for record in caplog.records:
        assert SENTINEL not in formatter.format(record), f"text leaked into log event {record.getMessage()!r}"
