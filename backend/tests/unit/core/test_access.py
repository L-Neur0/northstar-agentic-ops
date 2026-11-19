"""Unit tests for the visitor key and the workspace token (spec 16 §3.1, §3.2; AC-16.2, AC-16.3, AC-16.5 to AC-16.8).

Why: the visitor key is the only thing that keeps one expert's sessions from another's, and the
workspace token is the only thing between the open link and the specialist side; both must be
checked as plain functions before any route relies on them.
What: `owner_from_key` (validation, stable sha256), `issue_token` / `read_token` (signature, expiry,
tampering), `check_workspace_code` (constant-time compare, one message for every wrong input) and
the `require_role` dependency on a tiny app (401 without a valid token, 403 on the wrong role).
Must not: call Azure, or log or store the key.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core import access
from app.core.access import (
    AccessError,
    WorkspaceUser,
    check_workspace_code,
    issue_token,
    owner_from_key,
    read_token,
    require_role,
)
from app.core.settings import Settings

SECRET = "s" * 40
NOW = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)
KEY = "abcdefghijklmnopqrstuv"  # 22 characters, the frontend's length


def test_ac_16_2_same_key_same_owner_and_two_keys_differ():
    assert owner_from_key(KEY) == owner_from_key(KEY) == hashlib.sha256(KEY.encode()).hexdigest()
    assert owner_from_key(KEY) != owner_from_key(KEY + "w")


@pytest.mark.parametrize(
    "key",
    ["", "short", "a" * 21, "a" * 65, "abcdefghijklmnopqrstu!", "abcdefghijklmnopqrst uv", "äbcdefghijklmnopqrstuv"],
)
def test_ac_16_1_bad_keys_are_refused(key: str):
    with pytest.raises(AccessError) as caught:
        owner_from_key(key)
    assert caught.value.status == 401 and caught.value.code == "visitor_key_required"
    assert not key or key not in str(caught.value)


@pytest.mark.parametrize("key", ["a" * 22, "A-_z09" * 10 + "abcd"])
def test_ac_16_1_keys_of_22_to_64_url_safe_characters_pass(key: str):
    assert len(owner_from_key(key)) == 64


def test_ac_16_3_the_owner_id_never_contains_the_key():
    assert KEY not in owner_from_key(KEY)


def _settings() -> Settings:
    return Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_ac_16_5_codes_give_their_roles():
    settings = _settings()
    assert check_workspace_code(settings.workspace_code_specialist, settings) == "specialist"
    assert check_workspace_code(settings.workspace_code_engineer, settings) == "engineer"


def test_ac_16_5_token_carries_role_name_and_an_expiry_eight_hours_ahead():
    token, expires_at = issue_token("specialist", "Anna", secret=SECRET, now=NOW)
    assert datetime.fromisoformat(expires_at) == NOW + timedelta(hours=8)
    assert read_token(token, secret=SECRET, now=NOW) == WorkspaceUser("specialist", "Anna")


@pytest.mark.parametrize("code", ["", "wrong", "dev-specialistx", "DEV-SPECIALIST"])
def test_ac_16_6_wrong_codes_are_refused_with_one_message(code: str):
    with pytest.raises(AccessError) as caught:
        check_workspace_code(code, _settings())
    assert caught.value.status == 401 and caught.value.code == "workspace_code_invalid"
    assert str(caught.value) == access.WORKSPACE_CODE_INVALID_MESSAGE


def test_ac_16_7_codes_are_compared_in_constant_time(monkeypatch: pytest.MonkeyPatch):
    seen: list[tuple[bytes, bytes]] = []
    real = access.hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        seen.append((a, b))
        return real(a, b)

    monkeypatch.setattr(access.hmac, "compare_digest", spy)
    settings = _settings()
    check_workspace_code(settings.workspace_code_engineer, settings)
    assert len(seen) == 2  # both codes compared, whichever matches


def _forge(payload: dict[str, object]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{body}.AAAA"


@pytest.mark.parametrize(
    "token",
    [
        "",
        "no-dot",
        "a.b.c",
        _forge({"role": "specialist", "name": "x", "exp": 9_999_999_999}),
    ],
)
def test_ac_16_8_malformed_or_forged_tokens_are_refused(token: str):
    with pytest.raises(AccessError) as caught:
        read_token(token, secret=SECRET, now=NOW)
    assert caught.value.status == 401 and caught.value.code == "workspace_code_required"


def test_ac_16_8_a_tampered_payload_is_refused():
    token, _ = issue_token("engineer", "Ben", secret=SECRET, now=NOW)
    _, signature = token.split(".")
    payload = base64.urlsafe_b64encode(json.dumps({"role": "specialist", "name": "Ben", "exp": 9e9}).encode())
    with pytest.raises(AccessError):
        read_token(f"{payload.rstrip(b'=').decode()}.{signature}", secret=SECRET, now=NOW)


def test_ac_16_8_another_secret_or_an_expired_token_is_refused():
    token, _ = issue_token("specialist", "Anna", secret=SECRET, now=NOW)
    with pytest.raises(AccessError):
        read_token(token, secret="t" * 40, now=NOW)
    with pytest.raises(AccessError):
        read_token(token, secret=SECRET, now=NOW + timedelta(hours=8, seconds=1))


def _role_app() -> TestClient:
    app = FastAPI()
    app.state.settings = Settings(_env_file=None, workspace_token_secret=SECRET)  # pyright: ignore[reportCallIssue]

    @app.exception_handler(AccessError)
    async def handle(_request, exc: AccessError):  # pyright: ignore[reportUnusedFunction]
        from fastapi.responses import JSONResponse

        return JSONResponse({"code": exc.code, "message": str(exc)}, status_code=exc.status)

    @app.get("/specialist-only")
    def only(user: WorkspaceUser = Depends(require_role("specialist"))) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"name": user.name}

    return TestClient(app)


def test_ac_16_8_require_role_answers_401_and_403():
    client = _role_app()
    now = datetime.now(UTC)
    specialist, _ = issue_token("specialist", "Anna", secret=SECRET, now=now)
    engineer, _ = issue_token("engineer", "Ben", secret=SECRET, now=now)
    assert client.get("/specialist-only").json()["code"] == "workspace_code_required"
    assert client.get("/specialist-only", headers={"Authorization": "Bearer junk"}).status_code == 401
    wrong = client.get("/specialist-only", headers={"Authorization": f"Bearer {engineer}"})
    assert wrong.status_code == 403 and wrong.json()["code"] == "forbidden"
    ok = client.get("/specialist-only", headers={"Authorization": f"Bearer {specialist}"})
    assert ok.status_code == 200 and ok.json() == {"name": "Anna"}
