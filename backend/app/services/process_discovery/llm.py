"""The one model client: every AI call in the product goes through here (spec 11; architecture §6.1).

Why: the rules for calling a model are easy to forget at a call site and expensive to get wrong:
a token budget per call type, a 60 s timeout per attempt, retries only on transient errors and
within a wait cap, an error (never an empty success) when the model returns nothing usable, a
strict schema with exactly one retry on invalid output, usage reported to the daily budget even for
rejected replies, and one log line per call that carries no text. Putting them in one client means
no caller has to remember them.
What: `CallType`, the error classes, the `LLM` protocol, `AzureLLM` (the real client over the async
Azure OpenAI SDK, with SDK retries off because this client owns them) and `create_llm`, the factory
the app lifespan calls once (identity-only auth outside stage `local`; nothing is built at import
time). Implements spec 11 §3.1 to §3.8 and AC-11.1 to AC-11.17 and AC-11.21 to AC-11.29.
Must not: log message, reply, refusal or SDK error text; send `temperature` or `top_p`; retry a
refused, truncated or filtered reply; import anything from the engine above it (architecture §3.1).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol, TypedDict, TypeVar

import openai
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI
from pydantic import BaseModel, ValidationError

from app.core.settings import Settings
from app.services.process_discovery.json_schema import strict_json_schema
from app.services.process_discovery.llm_cache import LLMCache
from app.utils.prompt_safety import sanitize_log

logger = logging.getLogger("app.llm")

TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"
RETRYABLE_STATUS = frozenset({408, 429})
MAX_RETRY_PATHS = 10


class CallType(StrEnum):
    """Every model call names its purpose; the purpose picks the deployment, the budget and the log label."""

    EXTRACT = "EXTRACT"
    CLASSIFY = "CLASSIFY"
    GUIDE = "GUIDE"
    READ_DOCUMENT = "READ_DOCUMENT"
    OPPORTUNITIES = "OPPORTUNITIES"
    MAP = "MAP"
    LABEL = "LABEL"
    BRIEF = "BRIEF"
    EXPERT = "EXPERT"


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMUsage:
    """Tokens spent by one response, for the daily budget (spec 16)."""

    call_type: CallType
    deployment: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


BudgetGuard = Callable[[CallType], bool]  # False = refuse the call (spec 16)
UsageHook = Callable[[LLMUsage], None]  # called once per response that carries usage (spec 16)
EmptyReason = Literal["no_choices", "refused", "truncated", "content_filter", "empty"]


class LLMError(RuntimeError):
    """Base of every client error. A `RuntimeError`, so broad guards in callers still catch it."""


class LLMConfigError(LLMError):
    """Bad or missing settings. Names the setting, never its value."""


class LLMBudgetExceededError(LLMError):
    """The budget guard refused the call; no request was made."""


class LLMUnavailableError(LLMError):
    """The transport failed or the service answered with a status that will not improve on retry."""

    def __init__(self, status_code: int | None = None, attempts: int = 1) -> None:
        super().__init__(f"model unavailable (status {status_code}, after {attempts} attempt(s))")
        self.status_code = status_code
        self.attempts = attempts


class LLMEmptyResponseError(LLMError):
    """The reply had no usable text. Carries the reason code only, never the reply or the refusal."""

    def __init__(self, reason: EmptyReason) -> None:
        super().__init__(f"model reply unusable: {reason}")
        self.reason: EmptyReason = reason


class LLMInvalidOutputError(LLMError):
    """The reply failed its format twice. Carries field paths only, never values."""

    def __init__(self, paths: list[str]) -> None:
        super().__init__(f"model output invalid twice (problems at: {', '.join(paths) or '(root)'})")
        self.paths = paths


T = TypeVar("T", bound=BaseModel)


class LLM(Protocol):
    """What every caller depends on; `AzureLLM` and `FakeLLM` implement it."""

    async def generate_text(
        self, call_type: CallType, messages: Sequence[ChatMessage], *, max_tokens: int | None = None
    ) -> str: ...

    async def generate_json(
        self, call_type: CallType, messages: Sequence[ChatMessage], *, max_tokens: int | None = None
    ) -> dict[str, Any]: ...

    async def generate_structured(
        self,
        model_cls: type[T],
        call_type: CallType,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int | None = None,
    ) -> T: ...

    async def aclose(self) -> None: ...


# --- helpers shared with FakeLLM ------------------------------------------------------------------


def approx_prompt_tokens(messages: Sequence[Mapping[str, Any]]) -> int:
    """Characters of all messages divided by four: a size that moves with the prompt, not a tokenizer."""
    return sum(len(str(m.get("content") or "")) for m in messages) // 4


def _setting_default(name: str) -> Any:
    return Settings.model_fields[name].default


def token_budget(settings: Settings | None, call_type: CallType, requested: int | None = None) -> int:
    """The setting for `call_type`, lowered (never raised) by a caller's `requested` value."""
    name = f"llm_max_tokens_{call_type.value.lower()}"
    limit = int(getattr(settings, name) if settings is not None else _setting_default(name))
    return limit if requested is None else min(requested, limit)


def deployment_for(settings: Settings | None, call_type: CallType) -> str:
    """`EXPERT` uses the evaluation deployment; every other call type the app deployment."""
    name = "azure_openai_eval_deployment" if call_type is CallType.EXPERT else "azure_openai_deployment"
    value = getattr(settings, name) if settings is not None else _setting_default(name)
    if not value:
        raise LLMConfigError(f"{name.upper()} is not set; needed for {call_type.value} calls")
    return str(value)


def check_messages(messages: Sequence[Any]) -> list[ChatMessage]:
    """A copy of `messages`, each exactly `{"role": system|user|assistant, "content": str}`, else `ValueError`."""
    checked: list[ChatMessage] = []
    for index, message in enumerate(messages):
        if (
            not isinstance(message, Mapping)
            or set(message) != {"role", "content"}
            or message["role"] not in ("system", "user", "assistant")
            or not isinstance(message["content"], str)
        ):
            raise ValueError(f"message {index} must be {{'role': system|user|assistant, 'content': str}}")
        checked.append({"role": message["role"], "content": message["content"]})
    return checked


def parse_json_object(text: str) -> dict[str, Any]:
    """The reply as a JSON object, else `ValueError` (a JSON array or scalar is invalid too)."""
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("reply is JSON but not an object")
    return value


def error_paths(error: Exception) -> list[str]:
    """At most ten field paths from a validation error (`loc`), never input values."""
    if isinstance(error, ValidationError):
        paths: list[str] = []
        for item in error.errors(include_input=False, include_url=False):
            path = ".".join(str(part) for part in item["loc"]) or "(root)"
            if path not in paths:
                paths.append(path)
        return paths[:MAX_RETRY_PATHS]
    return ["(root)"]


def retry_message(paths: list[str]) -> ChatMessage:
    """The one extra `user` message of the invalid-output retry (spec 11 §3.6 rule 3)."""
    return {
        "role": "user",
        "content": (
            f"Your previous reply did not match the required format (problems at: {', '.join(paths)}). "
            "Reply again with JSON only, matching the format exactly."
        ),
    }


def report_usage(hook: UsageHook | None, usage: LLMUsage) -> None:
    """Call the usage hook; an exception inside it is logged by class and swallowed."""
    if hook is None:
        return
    try:
        hook(usage)
    except Exception as error:  # the hook must never change the call's result
        logger.warning(
            "llm_usage_hook_failed", extra={"call_type": usage.call_type.value, "error_class": type(error).__name__}
        )


# --- the real client ------------------------------------------------------------------------------


@dataclass
class _CallStats:
    """What the log line reports, accumulated over every request of one call."""

    attempts: int = 0
    invalid_retry: bool = False
    served_model: str = ""
    finish_reason: str = ""
    status_code: int | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    outcome: str = "ok"


def _read_reply(response: Any) -> str:
    """The reply text, or `LLMEmptyResponseError` with the first matching reason (spec 11 §3.5)."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise LLMEmptyResponseError("no_choices")
    choice = choices[0]
    message = getattr(choice, "message", None)
    if getattr(message, "refusal", None):
        raise LLMEmptyResponseError("refused")
    finish_reason = getattr(choice, "finish_reason", None)
    if finish_reason == "length":
        raise LLMEmptyResponseError("truncated")
    if finish_reason == "content_filter":
        raise LLMEmptyResponseError("content_filter")
    content = getattr(message, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise LLMEmptyResponseError("empty")
    return content


def _header_wait(error: openai.APIStatusError) -> float | None:
    """The wait the server asked for: `retry-after-ms`, else `retry-after` in seconds, else `None`."""
    headers = error.response.headers
    for name, scale in (("retry-after-ms", 1000.0), ("retry-after", 1.0)):
        raw = headers.get(name)
        if raw is None:
            continue
        try:
            value = float(raw) / scale
        except ValueError:
            continue
        if value >= 0:
            return value
    return None


class AzureLLM:
    """The real client over `AsyncAzureOpenAI`. Implements `LLM`."""

    def __init__(
        self,
        client: AsyncAzureOpenAI,
        settings: Settings,
        *,
        budget_guard: BudgetGuard | None = None,
        usage_hook: UsageHook | None = None,
        cache: LLMCache | None = None,
        credential: AsyncTokenCredential | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._client = client
        self._settings = settings
        self._budget_guard = budget_guard
        self._usage_hook = usage_hook
        self._cache = cache if settings.cache_enabled else None  # never outside stage local
        self._credential = credential
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._first_model: dict[str, str] = {}
        self._model_warned: set[tuple[str, str]] = set()

    async def aclose(self) -> None:
        """Close the HTTP client and the credential (app shutdown)."""
        await self._client.close()
        if self._credential is not None:
            await self._credential.close()

    async def generate_text(
        self, call_type: CallType, messages: Sequence[ChatMessage], *, max_tokens: int | None = None
    ) -> str:
        """Plain text, unchanged. Empty, refused, filtered or truncated is `LLMEmptyResponseError`."""
        return await self._call(call_type, messages, max_tokens, None, "text", lambda text: text)

    async def generate_json(
        self, call_type: CallType, messages: Sequence[ChatMessage], *, max_tokens: int | None = None
    ) -> dict[str, Any]:
        """A JSON object whose keys are not fixed in advance; the caller whitelists them."""
        return await self._call(
            call_type, messages, max_tokens, {"type": "json_object"}, "json_object", parse_json_object
        )

    async def generate_structured(
        self,
        model_cls: type[T],
        call_type: CallType,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int | None = None,
    ) -> T:
        """An instance of `model_cls`, produced under its strict schema and validated by it."""
        response_format = strict_json_schema(model_cls, name=model_cls.__name__)
        return await self._call(
            call_type, messages, max_tokens, response_format, response_format, model_cls.model_validate_json
        )

    async def _call(
        self,
        call_type: CallType,
        messages: Sequence[ChatMessage],
        max_tokens: int | None,
        response_format: dict[str, Any] | None,
        cache_format: dict[str, Any] | str,
        parse: Callable[[str], Any],
    ) -> Any:
        """One call, step by step (spec 11 §3.3). Logs exactly one `llm_call` line, whatever happens."""
        checked = check_messages(messages)
        budget = token_budget(self._settings, call_type, max_tokens)
        deployment = deployment_for(self._settings, call_type)
        stats = _CallStats()
        started = time.monotonic()
        try:
            if self._budget_guard is not None and not self._budget_guard(call_type):
                stats.outcome = "budget_refused"
                raise LLMBudgetExceededError(f"daily budget refused a {call_type.value} call")

            key = None
            if self._cache is not None:
                key = LLMCache.key(deployment, call_type, checked, cache_format)
                cached = self._cache.get(call_type, key)
                if cached is not None:
                    try:
                        value = parse(cached)
                    except (ValidationError, ValueError):
                        pass  # an entry the current parser rejects is a miss
                    else:
                        stats.outcome = "cache_hit"
                        return value

            request = {
                "model": deployment,
                "max_completion_tokens": budget,
                "timeout": self._settings.llm_timeout_seconds,
            }
            if response_format is not None:
                request["response_format"] = response_format
            text = await self._request(call_type, deployment, checked, request, stats)
            try:
                value = parse(text)
            except (ValidationError, ValueError) as first_error:
                stats.invalid_retry = True
                retry = [*checked, retry_message(error_paths(first_error))]
                text = await self._request(call_type, deployment, retry, request, stats)
                try:
                    value = parse(text)
                except (ValidationError, ValueError) as second_error:
                    stats.outcome = "invalid_output"
                    raise LLMInvalidOutputError(error_paths(second_error)) from None

            if self._cache is not None and key is not None:
                self._store(call_type, key, text)
            return value
        except LLMEmptyResponseError as error:
            stats.outcome = "empty" if error.reason == "no_choices" else error.reason
            raise
        except LLMUnavailableError as error:
            stats.outcome = "unavailable"
            stats.status_code = error.status_code
            raise
        except asyncio.CancelledError:
            stats.outcome = "cancelled"
            raise
        finally:
            self._log_call(call_type, deployment, budget, checked, stats, started)

    def _store(self, call_type: CallType, key: str, text: str) -> None:
        """Write a usable reply to the cache; a full disk must not fail the call that produced it."""
        assert self._cache is not None
        try:
            self._cache.put(call_type, key, text)
        except OSError as error:
            logger.warning("llm_cache_write_failed", extra={"key": key, "error_class": type(error).__name__})

    async def _request(
        self,
        call_type: CallType,
        deployment: str,
        messages: list[ChatMessage],
        request: dict[str, Any],
        stats: _CallStats,
    ) -> str:
        """One request through the retry loop; reports usage, then reads the reply."""
        response = await self._send(call_type, {**request, "messages": messages}, stats)
        self._observe(response, call_type, deployment, stats)
        return _read_reply(response)

    async def _send(self, call_type: CallType, kwargs: dict[str, Any], stats: _CallStats) -> Any:
        """The retry loop of spec 11 §3.4: transient errors only, server waits honoured within the cap."""
        retries_left = self._settings.llm_max_retries
        backoff = 1.0
        while True:
            stats.attempts += 1
            try:
                return await self._client.chat.completions.create(**kwargs)
            except openai.APIStatusError as error:
                status: int | None = error.status_code
                if status not in RETRYABLE_STATUS and not 500 <= status <= 599:
                    raise LLMUnavailableError(status, stats.attempts) from None
                wait = _header_wait(error)
                cause: dict[str, Any] = {"status_code": status}
            except openai.APIConnectionError as error:  # includes APITimeoutError
                status = None
                wait = None
                cause = {"error_class": type(error).__name__}
            except Exception as error:  # not retried; `CancelledError` is not an `Exception` and passes through
                raise LLMUnavailableError(None, stats.attempts) from error

            if retries_left <= 0:
                raise LLMUnavailableError(status, stats.attempts)
            if wait is None:
                wait = backoff * (1 + self._rng.uniform(0, 0.25))
            if wait > self._settings.llm_retry_max_wait_seconds:
                raise LLMUnavailableError(status, stats.attempts)
            logger.warning(
                "llm_retry",
                extra={"call_type": call_type.value, "attempt": stats.attempts, "wait_s": round(wait, 3), **cause},
            )
            await self._sleep(wait)
            retries_left -= 1
            backoff *= 2

    def _observe(self, response: Any, call_type: CallType, deployment: str, stats: _CallStats) -> None:
        """Usage to the hook and the stats, served model, finish reason. Never raises on odd shapes."""
        usage = getattr(response, "usage", None)
        if usage is not None:
            counts = [
                int(getattr(usage, name, 0) or 0) for name in ("prompt_tokens", "completion_tokens", "total_tokens")
            ]
            stats.prompt_tokens += counts[0]
            stats.completion_tokens += counts[1]
            stats.total_tokens += counts[2]
            report_usage(self._usage_hook, LLMUsage(call_type, deployment, *counts))
        choices = getattr(response, "choices", None) or []
        stats.finish_reason = str(getattr(choices[0], "finish_reason", "") or "") if choices else ""
        model = getattr(response, "model", None)
        if isinstance(model, str) and model:
            served = sanitize_log(model)[:120]
            stats.served_model = served
            first = self._first_model.setdefault(deployment, served)
            if first != served and (deployment, served) not in self._model_warned:
                self._model_warned.add((deployment, served))
                logger.warning(
                    "llm_model_changed", extra={"deployment": sanitize_log(deployment), "first": first, "now": served}
                )

    def _log_call(
        self,
        call_type: CallType,
        deployment: str,
        budget: int,
        messages: list[ChatMessage],
        stats: _CallStats,
        started: float,
    ) -> None:
        """The one `llm_call` line (spec 11 §3.8): ids, counts and codes only."""
        fields: dict[str, Any] = {
            "call_type": call_type.value,
            "deployment": sanitize_log(deployment),
            "served_model": stats.served_model,
            "outcome": stats.outcome,
            "attempts": stats.attempts,
            "invalid_retry": stats.invalid_retry,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "max_tokens": budget,
            "prompt_tokens": stats.prompt_tokens,
            "completion_tokens": stats.completion_tokens,
            "total_tokens": stats.total_tokens,
            "approx_prompt_tokens": approx_prompt_tokens(messages),
            "finish_reason": stats.finish_reason,
        }
        if stats.outcome == "unavailable":
            fields["status_code"] = stats.status_code
        level = logging.INFO if stats.outcome in ("ok", "cache_hit") else logging.WARNING
        logger.log(level, "llm_call", extra=fields)


def create_llm(
    settings: Settings, *, budget_guard: BudgetGuard | None = None, usage_hook: UsageHook | None = None
) -> AzureLLM:
    """Build the real client once, in the app lifespan (spec 11 §3.1). Raises `LLMConfigError` on bad settings."""
    missing = [
        name
        for name, value in (
            ("AZURE_OPENAI_ENDPOINT", settings.azure_openai_endpoint),
            ("AZURE_OPENAI_DEPLOYMENT", settings.azure_openai_deployment),
        )
        if not value
    ]
    if missing:
        raise LLMConfigError(f"missing setting(s): {', '.join(missing)}")
    api_key = settings.azure_openai_api_key or None  # an empty key counts as not set
    local = settings.deployment_stage == "local"
    if api_key and not local:
        raise LLMConfigError("API keys are only allowed in stage local")

    common: dict[str, Any] = {
        "azure_endpoint": settings.azure_openai_endpoint,
        "api_version": settings.azure_openai_api_version,
        "max_retries": 0,  # this client owns retries
    }
    credential: AsyncTokenCredential | None = None
    if api_key:
        client = AsyncAzureOpenAI(api_key=api_key, **common)
    else:
        if not local and settings.azure_client_id:
            credential = ManagedIdentityCredential(client_id=settings.azure_client_id)
        else:
            credential = DefaultAzureCredential()
        provider = get_bearer_token_provider(credential, TOKEN_SCOPE)
        client = AsyncAzureOpenAI(azure_ad_token_provider=provider, **common)

    cache = None
    if settings.cache_enabled:
        cache = LLMCache(settings.llm_cache_dir)
    elif settings.llm_cache_enabled and not local:
        logger.warning("llm_cache_ignored", extra={"stage": settings.deployment_stage})
    return AzureLLM(
        client, settings, budget_guard=budget_guard, usage_hook=usage_hook, cache=cache, credential=credential
    )
