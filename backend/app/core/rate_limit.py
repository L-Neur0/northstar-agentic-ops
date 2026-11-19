"""Rate limits and the daily model budget that protect the open link (spec 16 §3.3, §3.4).

Why: the prototype runs on a public link without accounts, so one caller must not be able to
flood the app or spend the whole model budget, and the client IP used as a key must not be
something the client can choose.
What: `build_limiter(settings)` (a slowapi `Limiter` on in-memory storage; every limit string is
parsed at start-up so a typo fails the boot, not the first request), `client_ip` (the last
`X-Forwarded-For` hop, which the platform's proxy appends, only behind that proxy; otherwise the
peer address), `hit` (one counted call, False when over the limit), `IpLimitMiddleware` (every
call per client IP, except the health probe), `BudgetTracker` (tokens per
UTC day; `guard` and `record` are the LLM client's budget guard and usage hook; one log line at
80 % and one at 100 % per day) and `usage_scope`, which lets the service add a turn's tokens to
the session's cost.
Must not: log keys, IPs or text; keep state anywhere but in memory (one replica, architecture §10).
Spec 16, AC-16.9 to AC-16.16.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol

from limits import RateLimitItem, parse
from slowapi import Limiter
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logging import log_event
from app.core.settings import Settings

logger = logging.getLogger("app.access")

LOGIN_LIMIT = "5/minute"
HEALTH_PATH = "/api/health"
WARN_SHARE = 0.8


def client_ip(request: Request, *, behind_proxy: bool) -> str:
    """The caller's IP: behind the platform's proxy, the hop it appended (the last one); else the peer."""
    if behind_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else "unknown"


@lru_cache(maxsize=32)
def _item(limit: str) -> RateLimitItem:
    return parse(limit)


def build_limiter(settings: Settings) -> Limiter:
    """The app's limiter. Raises `ValueError` naming the setting when a limit string does not parse."""
    for name, value in (
        ("RATE_LIMIT_PER_VISITOR", settings.rate_limit_per_visitor),
        ("RATE_LIMIT_PER_IP", settings.rate_limit_per_ip),
    ):
        try:
            _item(value)
        except ValueError:
            raise ValueError(f"{name}={value!r} is not a valid rate limit (for example '30/minute')") from None
    behind_proxy = settings.deployment_stage != "local"
    return Limiter(
        key_func=lambda request: client_ip(request, behind_proxy=behind_proxy),
        storage_uri="memory://",
        headers_enabled=False,
    )


def hit(limiter: Limiter, limit: str, scope: str, key: str) -> bool:
    """Count one call of `key` in `scope`; False when that call is over `limit`."""
    return limiter.limiter.hit(_item(limit), scope, key)


class IpLimitMiddleware(BaseHTTPMiddleware):
    """`RATE_LIMIT_PER_IP` on every call except `/api/health`; over it → 429 `rate_limited`."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path != HEALTH_PATH:
            settings: Settings = request.app.state.settings
            ip = client_ip(request, behind_proxy=settings.deployment_stage != "local")
            if not hit(request.app.state.limiter, settings.rate_limit_per_ip, "ip", ip):
                return JSONResponse(
                    {"code": "rate_limited", "message": "Too many requests. Please wait a moment and try again."},
                    status_code=429,
                )
        return await call_next(request)


# --- daily model budget -----------------------------------------------------------------------------


class TokenUsage(Protocol):
    """What the budget reads from one model response (the LLM client's `LLMUsage`)."""

    @property
    def prompt_tokens(self) -> int: ...
    @property
    def completion_tokens(self) -> int: ...


@dataclass
class UsageTotals:
    tokens_in: int = 0
    tokens_out: int = 0


_scope: ContextVar[UsageTotals | None] = ContextVar("usage_scope", default=None)


@contextmanager
def usage_scope() -> Iterator[UsageTotals]:
    """Collect the tokens recorded inside the block (a turn), for the session's cost."""
    totals = UsageTotals()
    token = _scope.set(totals)
    try:
        yield totals
    finally:
        _scope.reset(token)


class BudgetTracker:
    """Tokens (input + output) used per UTC day, in memory. `daily_limit = 0` means unlimited."""

    def __init__(self, daily_limit: int, clock: Callable[[], datetime]) -> None:
        self.daily_limit = daily_limit
        self._clock = clock
        self._day = ""
        self._used = 0
        self._logged: set[str] = set()

    def _roll(self) -> None:
        day = self._clock().date().isoformat()
        if day != self._day:
            self._day, self._used, self._logged = day, 0, set()

    def guard(self, call_type: Any) -> bool:
        """False when the day's total is at or above the limit (the call is refused)."""
        del call_type  # one budget for every call type
        self._roll()
        return self.daily_limit == 0 or self._used < self.daily_limit

    def record(self, usage: TokenUsage) -> None:
        """Add one response's tokens to the day (and to the open `usage_scope`, if any)."""
        self._roll()
        tokens_in, tokens_out = int(usage.prompt_tokens), int(usage.completion_tokens)
        self._used += tokens_in + tokens_out
        totals = _scope.get()
        if totals is not None:
            totals.tokens_in += tokens_in
            totals.tokens_out += tokens_out
        if not self.daily_limit:
            return
        for event, share in (("budget_warning", WARN_SHARE), ("budget_exhausted", 1.0)):
            if self._used >= share * self.daily_limit and event not in self._logged:
                self._logged.add(event)
                log_event(logger, event, day=self._day, used=self._used, limit=self.daily_limit)

    def snapshot(self) -> dict[str, Any]:
        self._roll()
        return {"day": self._day, "used": self._used, "limit": self.daily_limit}
