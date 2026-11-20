"""One error shape for the whole API: `{code, message}` (+ `reason` for `map_incomplete`) (architecture §3.4, spec 15 §3.3).

Why: the client decides what to show from the `code` alone (lock the input, show why *Finish* is
disabled, reload after a conflict), so every failure, whether raised by the service, the store,
access, the limiter or request validation, must arrive in the same shape. Messages are fixed
sentences: an error never echoes what the expert typed.
What: `ApiError` for route-level refusals and `install_error_handlers(app)`, which maps the
service errors (via the engine facade), `ConflictError` and other store errors (503), `AccessError`, request validation (422
`invalid_value`, field paths and pydantic's message only, never the input) and any other
`HTTPException` to that body; anything unexpected is 500 `internal_error`. A refused upload
(`DocumentRejected`) keeps its own code and its one plain sentence (spec 17 §3.2, §3.12), with the
status from `DOCUMENT_STATUS`. A report asked for before *Finish* is 409 `report_not_ready` (spec 20 §3.5).
Must not: include request bodies, message text or exception details from below in a response.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.access import AccessError
from app.services import process_discovery as engine
from app.services.store.repository import StoreError

#: Spec 17 §3.2: each upload refusal code and its HTTP status.
DOCUMENT_STATUS = {
    "document_limit": 409,
    "document_too_large": 413,
    "document_type": 415,
    "document_unreadable": 422,
    "unsafe_input": 400,
}
STATUS_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "not_allowed"}


class ApiError(Exception):
    """A refusal decided in a route: status, code and a fixed message."""

    def __init__(self, status: int, code: str, message: str, **extra: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


def error_response(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse({"code": code, "message": message, **extra}, status_code=status)


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for error in exc.errors()[:5]:
        location = ".".join(str(p) for p in error.get("loc", ()) if p != "body")
        parts.append(f"{location or 'body'}: {error.get('msg', 'invalid')}")
    return "; ".join(parts) or "The request is not valid."


def install_error_handlers(app: FastAPI) -> None:
    """Map every failure the routes can meet to `{code, message}`."""
    fixed: list[tuple[type[Exception], int, str, str]] = [
        (engine.NotFound, 404, "not_found", "Not found."),
        (engine.DocumentNotFound, 404, "not_found", "Not found."),
        (engine.SessionClosed, 400, "session_closed", "This session is closed."),
        (
            engine.UnsafeInput,
            400,
            "unsafe_input",
            "This message contains content that cannot be processed. Please rephrase it.",
        ),
        (engine.ReportNotReady, 409, "report_not_ready", "The report is ready once the map is finished."),
        (engine.UnknownCluster, 422, "unknown_cluster", "This cluster code is not in the taxonomy."),
        (engine.IdeaAlreadyStarted, 409, "idea_started", "A session was already started from this idea."),
        (engine.ConflictError, 409, "conflict", "This session was changed elsewhere. Please reload and try again."),
        (
            engine.LLMBudgetExceededError,
            429,
            "budget_exhausted",
            "The daily budget is used up. Please try again tomorrow.",
        ),
        (engine.LLMConfigError, 503, "model_unavailable", "The interview model is not available right now."),
        (StoreError, 503, "store_unavailable", "Your sessions cannot be reached right now. Please try again."),
        (Exception, 500, "internal_error", "Something went wrong on our side. Please try again."),
    ]
    for exc_type, status, code, message in fixed:

        async def handler(
            _request: Request, _exc: Exception, status: int = status, code: str = code, message: str = message
        ):
            return error_response(status, code, message)

        app.add_exception_handler(exc_type, handler)

    async def map_incomplete(_request: Request, exc: Exception) -> JSONResponse:
        reason = getattr(exc, "reason", "below_gate")
        return error_response(409, "map_incomplete", "The map is not complete yet.", reason=reason)

    async def document_rejected(_request: Request, exc: Exception) -> JSONResponse:
        code = getattr(exc, "code", "document_type")
        return error_response(DOCUMENT_STATUS.get(code, 400), code, getattr(exc, "message", "This file can't be read."))

    async def api_error(_request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, ApiError)
        return error_response(exc.status, exc.code, exc.message, **exc.extra)

    async def access_error(_request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, AccessError)
        return error_response(exc.status, exc.code, str(exc))

    async def validation(_request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)
        return error_response(422, "invalid_value", _validation_message(exc))

    async def http_error(_request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, StarletteHTTPException)
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            return JSONResponse(exc.detail, status_code=exc.status_code)
        code = STATUS_CODES.get(exc.status_code, "error")
        return error_response(exc.status_code, code, str(exc.detail))

    app.add_exception_handler(engine.MapIncomplete, map_incomplete)
    app.add_exception_handler(engine.DocumentRejected, document_rejected)
    app.add_exception_handler(ApiError, api_error)
    app.add_exception_handler(AccessError, access_error)
    app.add_exception_handler(RequestValidationError, validation)
    app.add_exception_handler(StarletteHTTPException, http_error)
