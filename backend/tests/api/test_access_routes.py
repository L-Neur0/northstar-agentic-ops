"""API tests for access over HTTP: the visitor key, the workspace login, the rate limits and the daily budget (spec 16; AC-16.1, 16.3 to 16.6, 16.9 to 16.11, 16.14).

Why: the open link has no accounts, so these checks are the only thing that keeps one expert's
sessions private, keeps the specialist side behind a code, and stops one caller from spending the
model budget or flooding the app; each must hold on every route, not only in a unit test.
What: every expert route without or with a bad key (401), every expert route against another
visitor's session (404), the key never stored or logged, login with each code and with wrong
input, the per-visitor, per-IP and login limits, health never limited, and a used-up budget.
Must not: call Azure or sleep; limits are set low through settings instead.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest

from app.core.access import owner_from_key
from app.services.process_discovery.llm import CallType

from .conftest import KEY_A, KEY_B, ApiHarness, build_harness, visitor

EXPERT_ROUTES = [
    ("POST", "/api/sessions", {}),
    ("GET", "/api/sessions", None),
    ("GET", "/api/sessions/{id}", None),
    ("DELETE", "/api/sessions/{id}", None),
    ("POST", "/api/sessions/{id}/messages", {"text": "hello"}),
    ("POST", "/api/sessions/{id}/confirm", {"target": "roles"}),
    ("PUT", "/api/sessions/{id}/cluster", {"code": "FIN"}),
    ("POST", "/api/sessions/{id}/close", None),
    ("POST", "/api/sessions/{id}/finish", None),
    ("GET", "/api/ideas", None),
    ("DELETE", "/api/ideas/{id}", None),
    ("POST", "/api/ideas/{id}/start", None),
    ("DELETE", "/api/me", None),
]


@pytest.mark.parametrize(("method", "path", "body"), EXPERT_ROUTES)
@pytest.mark.parametrize("key", [None, "short", "x" * 65, "abcdefghijklmnopqrstu!", "abcdefghij klmnopqrstuv"])
def test_ac_16_1_expert_routes_need_a_valid_visitor_key(api: ApiHarness, method, path, body, key):
    headers = {} if key is None else {"X-Visitor-Key": key}
    response = api.client.request(method, path.format(id="any"), json=body, headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == "visitor_key_required"


@pytest.mark.parametrize(("method", "path", "body"), [r for r in EXPERT_ROUTES if "{id}" in r[1]])
def test_ac_16_4_another_visitors_session_or_idea_is_404_on_every_route(api: ApiHarness, method, path, body):
    theirs = api.create(KEY_B)
    response = api.client.request(method, path.format(id=theirs["id"]), json=body, headers=visitor(KEY_A))
    assert response.status_code == 404 and response.json()["code"] == "not_found"
    assert api.client.get(f"/api/sessions/{theirs['id']}", headers=visitor(KEY_B)).json() == theirs


def test_ac_16_3_the_key_is_in_no_stored_document_and_no_log_line(api: ApiHarness, caplog: pytest.LogCaptureFixture):
    assert api.llm is not None
    with caplog.at_level(logging.DEBUG):
        created = api.create(KEY_A)
        api.llm.add(CallType.EXTRACT, {"department": "Finance"})
        api.llm.add(CallType.GUIDE, "Your role?")
        api.client.post(f"/api/sessions/{created['id']}/messages", json={"text": "Finance"}, headers=visitor())
        api.client.get("/api/sessions", headers=visitor())
    stored = json.dumps(list(api.repo._documents.values()))  # pyright: ignore[reportPrivateUsage]
    assert KEY_A not in stored and owner_from_key(KEY_A) in stored
    lines = [r.getMessage() + json.dumps(vars(r), default=str) for r in caplog.records]
    assert lines and not [line for line in lines if KEY_A in line]
    assert not [line for line in lines if owner_from_key(KEY_A) in line]  # only the 8-character prefix


def test_ac_16_5_login_with_each_code(api: ApiHarness):
    settings = api.settings
    before = datetime.now(UTC)
    for code, role in (
        (settings.workspace_code_specialist, "specialist"),
        (settings.workspace_code_engineer, "engineer"),
    ):
        response = api.client.post("/api/workspace/login", json={"code": code, "name": "Anna"})
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"token", "role", "name", "expiresAt"}
        assert (body["role"], body["name"]) == (role, "Anna")
        expires = datetime.fromisoformat(body["expiresAt"])
        assert before + timedelta(hours=8) <= expires <= datetime.now(UTC) + timedelta(hours=8)


@pytest.mark.parametrize("code", ["wrong", "", "dev-specialist ", "DEV-ENGINEER"])
def test_ac_16_6_a_wrong_code_is_401_with_the_same_message(api: ApiHarness, code: str):
    response = api.client.post("/api/workspace/login", json={"code": code, "name": "Anna"})
    assert response.status_code == 401
    assert response.json() == {"code": "workspace_code_invalid", "message": "The access code is not valid."}


@pytest.mark.parametrize("name", ["", "x" * 41])
def test_login_name_must_be_1_to_40_characters(api: ApiHarness, name: str):
    response = api.client.post("/api/workspace/login", json={"code": "dev-specialist", "name": name})
    assert response.status_code == 422 and response.json()["code"] == "invalid_value"


def test_ac_16_9_more_than_the_visitor_limit_is_429_and_others_are_not_affected(company):
    api = build_harness(company, rate_limit_per_visitor="3/minute")
    for _ in range(3):
        assert api.client.get("/api/sessions", headers=visitor(KEY_A)).status_code == 200
    over = api.client.get("/api/sessions", headers=visitor(KEY_A))
    assert over.status_code == 429 and over.json()["code"] == "rate_limited"
    assert api.client.get("/api/sessions", headers=visitor(KEY_B)).status_code == 200


def test_ac_16_9_the_default_visitor_limit_is_30_a_minute(company):
    api = build_harness(company, rate_limit_per_visitor="30/minute")
    codes = [api.client.get("/api/ideas", headers=visitor()).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429


def test_the_per_ip_limit_covers_every_call(company):
    api = build_harness(company, rate_limit_per_ip="2/minute")
    assert api.client.get("/api/taxonomy").status_code == 200
    assert api.client.get("/api/config").status_code == 200
    over = api.client.get("/api/taxonomy")
    assert over.status_code == 429 and over.json()["code"] == "rate_limited"


def test_ac_16_10_more_than_5_logins_a_minute_from_one_ip_is_429(api: ApiHarness):
    codes = [api.client.post("/api/workspace/login", json={"code": "wrong", "name": "x"}).status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]


def test_ac_16_11_health_is_never_rate_limited(company):
    api = build_harness(company, rate_limit_per_ip="1/minute")
    assert all(api.client.get("/api/health").status_code == 200 for _ in range(10))


def test_ac_16_14_a_used_up_budget_is_429_and_no_model_request_is_made(company):
    api = build_harness(company, daily_token_budget=100)
    assert api.llm is not None
    created = api.create()
    api.budget.record(_Usage(100, 0))
    api.llm.add(CallType.EXTRACT, {"department": "Finance"})
    response = api.client.post(f"/api/sessions/{created['id']}/messages", json={"text": "Finance"}, headers=visitor())
    assert response.status_code == 429 and response.json()["code"] == "budget_exhausted"
    assert api.llm.calls == []
    assert api.client.get(f"/api/sessions/{created['id']}", headers=visitor()).json() == created


class _Usage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
