"""The workspace login: an access code and a name in, a short-lived signed token out (spec 16 §3.2).

Why: specialists and engineers reach the review side through a code per role, not an account;
the token they get carries the role and the typed name for edit marks and the audit log, and
expires after 8 hours. Login attempts are limited per IP so the code cannot be guessed quickly.
What: `POST /api/workspace/login`: 5 attempts a minute per IP (429 `rate_limited`), the code
checked in constant time (401 `workspace_code_invalid`, the same message for any wrong input),
one `workspace_login` audit line (role, name, outcome; never the code). The other workspace
routes are spec 21.
Must not: log or echo the code, or say which part of a login was wrong.
Spec 16 AC-16.5, AC-16.6, AC-16.10.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Request

from app.api.errors import ApiError
from app.core.access import AccessError, check_workspace_code, issue_token
from app.core.logging import log_event
from app.core.rate_limit import LOGIN_LIMIT, client_ip, hit
from app.core.settings import Settings
from app.models.process_discovery_wire import LoginIn, LoginOut

router = APIRouter(prefix="/api/workspace", tags=["workspace"])
audit = logging.getLogger("app.audit")


@router.post("/login", response_model=LoginOut)
async def login(body: LoginIn, request: Request) -> LoginOut:
    """Exchange an access code and a name for a workspace token."""
    settings: Settings = request.app.state.settings
    ip = client_ip(request, behind_proxy=settings.deployment_stage != "local")
    if not hit(request.app.state.limiter, LOGIN_LIMIT, "login", ip):
        raise ApiError(429, "rate_limited", "Too many attempts. Please wait a minute and try again.")
    try:
        role = check_workspace_code(body.code, settings)
    except AccessError:
        log_event(audit, "workspace_login", role=None, outcome="invalid_code")
        raise
    token, expires_at = issue_token(role, body.name, secret=settings.workspace_token_secret, now=datetime.now(UTC))
    log_event(audit, "workspace_login", role=role, user_name=body.name, outcome="ok")
    return LoginOut(token=token, role=role, name=body.name, expires_at=expires_at)
