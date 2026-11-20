"""The workspace routes: the login (spec 16 §3.2) and the specialist's read-only review of every session (spec 21).

Why: specialists and engineers reach the review side through a code per role, not an account;
the token they get carries the role and the typed name for edit marks and the audit log, and
expires after 8 hours. Login attempts are limited per IP so the code cannot be guessed quickly.
What: `POST /api/workspace/login`: 5 attempts a minute per IP (429 `rate_limited`), the code
checked in constant time (401 `workspace_code_invalid`, the same message for any wrong input),
one `workspace_login` audit line (role, name, outcome; never the code). Spec 21 adds, for the
`specialist` role only: `GET /api/review/sessions` (filters `status`, `cluster`, `q`),
`GET /api/review/sessions/{id}` (with the `ETag` header), `.../conversation`, `.../report.pdf` and
`DELETE /api/review/sessions/{id}` (needs `If-Match`). Each is one call to the engine facade.
Open workspace (`WORKSPACE_OPEN`, amended 2026-11-20): the login takes a name only and always
gives `specialist`; delete is refused with 403 `forbidden` before any store call and audited
`outcome=refused` (an access rule of the shell, like the role check).
Must not: log or echo the code, say which part of a login was wrong, import past the engine facade,
or hold a rule of its own beyond access. Spec 16 AC-16.5, AC-16.6, AC-16.10; spec 21 AC-21.1 to AC-21.19, AC-21.21; spec 16 AC-16.17, AC-16.18.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from app.api.errors import ApiError
from app.api.process_discovery_routes import get_service
from app.core.access import AccessError, Role, WorkspaceUser, check_workspace_code, issue_token, require_role
from app.core.logging import log_event
from app.core.rate_limit import LOGIN_LIMIT, client_ip, hit
from app.core.settings import Settings, get_settings
from app.models.process_discovery_wire import LoginIn, LoginOut
from app.models.workspace_wire import ConversationOut, ReviewListOut, ReviewSessionOut
from app.services.process_discovery import DiscoveryService

router = APIRouter(prefix="/api/workspace", tags=["workspace"])
review = APIRouter(prefix="/api/review", tags=["workspace"])
audit = logging.getLogger("app.audit")
specialist = require_role("specialist")
DELETE_OFF = "Deleting is switched off on this open demo."


@router.post("/login", response_model=LoginOut)
async def login(body: LoginIn, request: Request) -> LoginOut:
    """Exchange an access code and a name for a workspace token."""
    settings: Settings = request.app.state.settings
    ip = client_ip(request, behind_proxy=settings.deployment_stage != "local")
    if not hit(request.app.state.limiter, LOGIN_LIMIT, "login", ip):
        raise ApiError(429, "rate_limited", "Too many attempts. Please wait a minute and try again.")
    try:
        role: Role = "specialist" if settings.workspace_open else check_workspace_code(body.code, settings)
    except AccessError:
        log_event(audit, "workspace_login", role=None, outcome="invalid_code")
        raise
    token, expires_at = issue_token(role, body.name, secret=settings.workspace_token_secret, now=datetime.now(UTC))
    log_event(audit, "workspace_login", role=role, user_name=body.name, outcome="ok")
    return LoginOut(token=token, role=role, name=body.name, expires_at=expires_at)


# --- review (spec 21) --------------------------------------------------------------------------------


@review.get("/sessions", response_model=ReviewListOut)
async def list_sessions(
    status_filter: Literal["active", "finished", "no_candidate"] | None = Query(default=None, alias="status"),
    cluster: str | None = Query(default=None, min_length=1, max_length=8),
    q: str | None = Query(default=None, min_length=1, max_length=100),
    user: WorkspaceUser = Depends(specialist),
    service: DiscoveryService = Depends(get_service),
) -> ReviewListOut:
    """Every session with its row, the status counts and the filtered rows (newest first)."""
    return await service.review_list(user, status=status_filter, cluster=cluster, q=q)


@review.get("/sessions/{session_id}", response_model=ReviewSessionOut)
async def get_session(
    session_id: str,
    response: Response,
    user: WorkspaceUser = Depends(specialist),
    service: DiscoveryService = Depends(get_service),
) -> ReviewSessionOut:
    """The read-only session view; the etag also in the `ETag` header (delete needs it)."""
    view = await service.review_session(user, session_id)
    response.headers["ETag"] = view.etag
    return view


@review.get("/sessions/{session_id}/conversation", response_model=ConversationOut)
async def get_conversation(
    session_id: str, user: WorkspaceUser = Depends(specialist), service: DiscoveryService = Depends(get_service)
) -> ConversationOut:
    """The full conversation, as stored. Every call is audited."""
    return await service.review_conversation(user, session_id)


@review.get("/sessions/{session_id}/report.pdf", response_class=Response)
async def get_report_pdf(
    session_id: str, user: WorkspaceUser = Depends(specialist), service: DiscoveryService = Depends(get_service)
) -> Response:
    """The expert's report PDF, same bytes and file name. Every call is audited."""
    pdf, filename = await service.review_report_pdf(user, session_id)
    return Response(
        content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@review.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_session(
    session_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    user: WorkspaceUser = Depends(specialist),
    service: DiscoveryService = Depends(get_service),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Hard-delete with the current etag (428 without, 409 when stale). Every call is audited."""
    if settings.workspace_open:  # spec 21 §3.6 item 4: refused before any store call
        log_event(audit, "workspace_action", role=user.role, user_name=user.name, action="delete_session",
                  session_id=session_id, outcome="refused")  # fmt: skip
        raise ApiError(403, "forbidden", DELETE_OFF)
    await service.review_delete(user, session_id, if_match)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
