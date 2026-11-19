"""Security headers and correlation ids for every response (spec 10 §3.8).

Why: the app serves both the API and the single-page frontend from one origin, so the browser
protections (content security policy, no sniffing, no framing, HSTS outside local runs) must be
set by the backend itself. Every request also needs an id that ties its log lines together.
What: two small ASGI middlewares, `CorrelationIdMiddleware` (reuses `X-Correlation-Id` or makes a
new one, echoes it back) and `SecurityHeadersMiddleware`.
Must not: add external script sources to the content security policy.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import correlation_id

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'; "
    "base-uri 'self'; form-action 'self'"
)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Set the request's correlation id from the header or a new uuid, and echo it back."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        value = request.headers.get("x-correlation-id") or uuid.uuid4().hex
        token = correlation_id.set(value)
        try:
            response = await call_next(request)
        finally:
            correlation_id.reset(token)
        response.headers["X-Correlation-Id"] = value
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add the browser security headers; HSTS only when `hsts` is on (not in local runs)."""

    def __init__(self, app, hsts: bool) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.hsts = hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if self.hsts:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
