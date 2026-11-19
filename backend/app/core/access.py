"""Access for the prototype: the expert's visitor key and the workspace token (spec 16 §3.1, §3.2; architecture §3.5).

Why: anyone with the link may start a discovery session without an account, yet each expert must
see only their own sessions, and the specialist side must stay behind an access code. The engine
must never see a key or a token, only the `owner_id` derived here.
What: `owner_from_key` (validates the `X-Visitor-Key` and returns its sha256 hex) and the
`require_visitor` dependency; `check_workspace_code` (both codes compared in constant time, one
message for any wrong input), `issue_token` / `read_token` (`base64url(payload).base64url(hmac)`,
8 hours) and the `require_role` dependency factory; `AccessError` carries the HTTP status and code.
Must not: store or log a key, a code or a token; say which part of a login was wrong; read a
clock itself in `issue_token` / `read_token` (the caller passes `now`).
Spec 16, AC-16.1 to AC-16.8.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, NamedTuple, cast

from fastapi import Request

from app.core.settings import Settings

Role = Literal["specialist", "engineer"]
TOKEN_TTL_SECONDS = 8 * 3600
VISITOR_HEADER = "X-Visitor-Key"
_KEY_RE = re.compile(r"[A-Za-z0-9_-]{22,64}")

WORKSPACE_CODE_INVALID_MESSAGE = "The access code is not valid."


class AccessError(Exception):
    """A refused call: `status` and `code` go to the `{code, message}` error body."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class WorkspaceUser(NamedTuple):
    role: Role
    name: str


# --- visitor key ------------------------------------------------------------------------------------


def owner_from_key(key: str) -> str:
    """The owner id of a visitor key (sha256 hex). Raises `AccessError(401)` for a malformed key."""
    if not isinstance(key, str) or not _KEY_RE.fullmatch(key):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise AccessError(401, "visitor_key_required", "A visitor key (22 to 64 URL-safe characters) is required.")
    return hashlib.sha256(key.encode("ascii")).hexdigest()


async def require_visitor(request: Request) -> str:
    """FastAPI dependency: the caller's `owner_id` from `X-Visitor-Key`."""
    return owner_from_key(request.headers.get(VISITOR_HEADER, ""))


# --- workspace code and token -------------------------------------------------------------------------


def check_workspace_code(code: str, settings: Settings) -> Role:
    """The role a code opens. Both codes are always compared, in constant time."""
    given = code.encode("utf-8")
    specialist = hmac.compare_digest(given, settings.workspace_code_specialist.encode("utf-8"))
    engineer = hmac.compare_digest(given, settings.workspace_code_engineer.encode("utf-8"))
    if specialist:
        return "specialist"
    if engineer:
        return "engineer"
    raise AccessError(401, "workspace_code_invalid", WORKSPACE_CODE_INVALID_MESSAGE)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest())


def issue_token(
    role: Role, name: str, *, secret: str, now: datetime, ttl_seconds: int = TOKEN_TTL_SECONDS
) -> tuple[str, str]:
    """A signed token for `role` and `name`, and its expiry as an ISO time."""
    expires = now + timedelta(seconds=ttl_seconds)
    payload = _b64(json.dumps({"role": role, "name": name, "exp": int(expires.timestamp())}).encode("utf-8"))
    return f"{payload}.{_sign(payload, secret)}", expires.isoformat()


_REQUIRED = "A valid workspace token is required."


def read_token(token: str, *, secret: str, now: datetime) -> WorkspaceUser:
    """The user a token names. Malformed, forged, tampered or expired → `AccessError(401)`."""
    payload, dot, signature = token.partition(".")
    if not dot or not payload or "." in signature or not hmac.compare_digest(signature, _sign(payload, secret)):
        raise AccessError(401, "workspace_code_required", _REQUIRED)
    try:
        data = json.loads(_unb64(payload))
    except (binascii.Error, ValueError):
        raise AccessError(401, "workspace_code_required", _REQUIRED) from None
    role, name, exp = data.get("role"), data.get("name"), data.get("exp")
    if role not in ("specialist", "engineer") or not isinstance(name, str) or not isinstance(exp, int | float):
        raise AccessError(401, "workspace_code_required", _REQUIRED)
    if now.timestamp() > exp:
        raise AccessError(401, "workspace_code_required", _REQUIRED)
    return WorkspaceUser(cast(Role, role), name)


def require_role(*roles: Role) -> Callable[[Request], WorkspaceUser]:
    """Dependency factory: the workspace user from `Authorization: Bearer`, with one of `roles` (else 403)."""

    def dependency(request: Request) -> WorkspaceUser:
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AccessError(401, "workspace_code_required", _REQUIRED)
        settings: Settings = request.app.state.settings
        user = read_token(token.strip(), secret=settings.workspace_token_secret, now=datetime.now(UTC))
        if user.role not in roles:
            raise AccessError(403, "forbidden", "This action is not available for your role.")
        return user

    return dependency
