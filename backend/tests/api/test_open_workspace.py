"""API tests for the open workspace (spec 16 §3.2 item 5, spec 21 §3.6 item 4; amended 2026-11-20 (open workspace)).

Why: for the demo the product owner allows the workspace without an access code, on one
condition: nothing can be deleted there. These tests prove both halves over HTTP, and that the
closed workspace keeps exactly today's behaviour.
What: the real app on the memory store with `WORKSPACE_OPEN=true` (and the default `false` for
contrast): login with a name only, with any code, the unchanged login limit and audit line,
`workspaceOpen` in `GET /api/config`, and delete refused with 403 `forbidden` before any store
call, audited with outcome `refused`.
Must not: patch a route or the settings check; the store is only spied on, never replaced.
Acceptance criteria: AC-16.17, AC-16.18, AC-16.19, AC-21.21.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.access import issue_token
from app.core.config import CompanyConfig
from app.models.process_discovery_schemas import Session

from .conftest import ApiHarness, build_harness

DELETE_OFF = "Deleting is switched off on this open demo."


@pytest.fixture
def open_api(company: CompanyConfig) -> ApiHarness:
    return build_harness(company, workspace_open=True)


def _specialist(api: ApiHarness) -> dict[str, str]:
    value, _ = issue_token(
        "specialist", "Maria (IT)", secret=api.settings.workspace_token_secret, now=datetime.now(UTC)
    )
    return {"Authorization": f"Bearer {value}"}


def _session(api: ApiHarness) -> Session:
    at = "2026-11-19T10:00:00+00:00"
    return asyncio.run(api.repo.create_session(Session(owner_id="a" * 64, created_at=at, updated_at=at)))


# --- AC-16.17, AC-16.18: login ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body", [{"name": "Anna"}, {"code": "wrong", "name": "Anna"}, {"code": "dev-engineer", "name": "Anna"}]
)
def test_ac_16_17_open_login_takes_a_name_and_always_gives_a_specialist(open_api: ApiHarness, body: dict[str, Any]):
    response = open_api.client.post("/api/workspace/login", json=body)
    assert response.status_code == 200
    assert (response.json()["role"], response.json()["name"]) == ("specialist", "Anna")
    headers = {"Authorization": f"Bearer {response.json()['token']}"}
    assert open_api.client.get("/api/review/sessions", headers=headers).status_code == 200


@pytest.mark.parametrize("name", ["", "x" * 41])
def test_ac_16_17_open_login_still_checks_the_name(open_api: ApiHarness, name: str):
    response = open_api.client.post("/api/workspace/login", json={"name": name})
    assert response.status_code == 422 and response.json()["code"] == "invalid_value"


def test_ac_16_18_open_login_keeps_the_limit_and_the_audit_line(open_api: ApiHarness, caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO, logger="app.audit")
    codes = [open_api.client.post("/api/workspace/login", json={"name": "Anna"}).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]
    lines = [r for r in caplog.records if r.name == "app.audit" and r.getMessage() == "workspace_login"]
    assert [(r.role, r.user_name, r.outcome) for r in lines] == [("specialist", "Anna", "ok")] * 5  # type: ignore[attr-defined]


def test_ac_16_18_closed_login_without_a_code_is_refused(company: CompanyConfig):
    api = build_harness(company)
    response = api.client.post("/api/workspace/login", json={"name": "Anna"})
    assert response.status_code == 401 and response.json()["code"] == "workspace_code_invalid"


# --- AC-16.19: config ------------------------------------------------------------------------------------


def test_ac_16_19_config_says_whether_the_workspace_is_open(company: CompanyConfig, open_api: ApiHarness):
    assert build_harness(company).client.get("/api/config").json()["workspaceOpen"] is False
    assert open_api.client.get("/api/config").json()["workspaceOpen"] is True


# --- AC-21.21: delete switched off -----------------------------------------------------------------------


class _Spy:
    """Records every store call made through the repository, then forwards it."""

    def __init__(self, repo: Any) -> None:
        self.repo, self.calls = repo, []

    def __getattr__(self, name: str) -> Any:
        self.calls.append(name)
        return getattr(self.repo, name)


@pytest.mark.parametrize("if_match", [None, '"any"'])
def test_ac_21_21_open_delete_is_403_before_any_store_call(
    open_api: ApiHarness, caplog: pytest.LogCaptureFixture, if_match: str | None
):
    session = _session(open_api)
    spy = _Spy(open_api.service.repo)
    open_api.service.repo = spy  # pyright: ignore[reportAttributeAccessIssue]
    caplog.set_level(logging.INFO, logger="app.audit")
    headers = _specialist(open_api) | ({"If-Match": if_match} if if_match else {})
    for session_id in (session.id, "nope"):
        response = open_api.client.delete(f"/api/review/sessions/{session_id}", headers=headers)
        assert response.status_code == 403
        assert response.json() == {"code": "forbidden", "message": DELETE_OFF}
    assert spy.calls == []
    assert asyncio.run(open_api.repo.find_session(session.id)) is not None
    lines = [r for r in caplog.records if r.name == "app.audit" and r.getMessage() == "workspace_action"]
    assert [(r.action, r.session_id, r.outcome, r.role, r.user_name) for r in lines] == [  # type: ignore[attr-defined]
        ("delete_session", session.id, "refused", "specialist", "Maria (IT)"),
        ("delete_session", "nope", "refused", "specialist", "Maria (IT)"),
    ]


def test_ac_21_21_closed_delete_is_unchanged(company: CompanyConfig):
    api = build_harness(company)
    session = _session(api)
    etag = api.client.get(f"/api/review/sessions/{session.id}", headers=_specialist(api)).headers["ETag"]
    response = api.client.delete(f"/api/review/sessions/{session.id}", headers=_specialist(api) | {"If-Match": etag})
    assert response.status_code == 204
