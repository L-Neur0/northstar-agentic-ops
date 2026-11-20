"""API tests for the workspace routes: list, session view, conversation, report PDF and delete (spec 21 §3, §4.1; AC-21.1, AC-21.7, AC-21.11 to AC-21.19).

Why: the workspace reads every expert's sessions, so its guards must hold on every route: the
specialist role, nothing private in the list or the view, the conversation only on its own logged
route, delete only with the current etag; and none of it may change a session or spend a model call.
What: the real app on the memory store with the NIG configuration, the example catalogue and a
`FakeLLM` that must stay unused; sessions are seeded straight into the store (a finished cost
review with marker strings in its name, messages and document text, an active one), tokens are
issued with the app's secret, audit lines are read from the `app.audit` logger.
Must not: patch a route, the service or the store's reads.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

import pytest

from app.api.process_discovery_routes import get_service
from app.core.access import Role, issue_token, owner_from_key
from app.core.config import CompanyConfig
from app.models.process_discovery_schemas import DocumentRecord, Idea, Message, Session
from app.models.workspace_wire import (
    ConversationOut,
    DocumentMetaOut,
    GridCellOut,
    GridRowOut,
    ReviewCountsOut,
    ReviewListOut,
    ReviewRowOut,
    ReviewSessionOut,
    StepGridOut,
    SummaryOut,
)
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.service import DiscoveryService
from tests.fixtures.assessment_19.cases import example_catalogue
from tests.unit.process_discovery.export.cases import eu_session

from .conftest import KEY_A, NIG, ApiHarness, TickingClock, build_harness, visitor

OWNER = owner_from_key(KEY_A)
MARK_MESSAGE, MARK_DOC, MARK_NAME = "MARKER-MESSAGE-TEXT", "MARKER-DOCUMENT-TEXT", "MARKER-NAME"
AT = "2026-11-19T10:00:00+00:00"


def token(api: ApiHarness, role: Role = "specialist", name: str = "Maria (IT)") -> dict[str, str]:
    value, _ = issue_token(role, name, secret=api.settings.workspace_token_secret, now=datetime.now(UTC))
    return {"Authorization": f"Bearer {value}"}


def _document() -> DocumentRecord:
    return DocumentRecord(
        id="d1", name="invoice-procedure.pdf", kind="pdf", bytes=1200, chars=50, text=MARK_DOC,
        uploaded_at=AT, outcome="read",
    )  # fmt: skip


def _messages(n: int) -> list[Message]:
    return [
        Message.model_validate({"role": "agent" if i % 2 == 0 else "expert", "text": f"{MARK_MESSAGE} {i}", "at": AT})
        for i in range(n)
    ]


@pytest.fixture
def api(company: CompanyConfig) -> ApiHarness:
    api = build_harness(company)
    llm = FakeLLM()
    service = DiscoveryService(
        api.repo, llm, api.service.ctx, None, clock=TickingClock(),
        company=company.model_copy(update={"solutions": example_catalogue()}), config_dir=NIG,
    )  # fmt: skip
    api.client.app.dependency_overrides[get_service] = lambda: service  # pyright: ignore[reportAttributeAccessIssue]
    api.service, api.llm = service, llm
    return api


def _finished(api: ApiHarness) -> Session:
    session = eu_session(
        owner_id=OWNER, display_name=MARK_NAME, messages=_messages(4), documents=[_document()],
        updated_at="2026-11-19T10:00:00+00:00",
    )  # fmt: skip
    return asyncio.run(api.repo.create_session(session))


def _active(api: ApiHarness) -> Session:
    session = Session(
        owner_id=owner_from_key("visitor-b-0123456789abcdef"), created_at=AT, updated_at="2026-11-19T11:00:00+00:00",
        messages=_messages(2),
    )  # fmt: skip
    return asyncio.run(api.repo.create_session(session))


def _audit(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "app.audit" and r.getMessage() == "workspace_action"]


ROUTES = [
    ("GET", "/api/review/sessions"),
    ("GET", "/api/review/sessions/{id}"),
    ("GET", "/api/review/sessions/{id}/conversation"),
    ("GET", "/api/review/sessions/{id}/report.pdf"),
    ("DELETE", "/api/review/sessions/{id}"),
]


# --- AC-21.1: role -----------------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), ROUTES)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nonsense.sig"}, {"Authorization": "Basic x"}])
def test_ac_21_1_no_or_bad_token_is_401(api: ApiHarness, method: str, path: str, headers: dict[str, str]):
    response = api.client.request(method, path.format(id="any"), headers=headers)
    assert response.status_code == 401 and response.json()["code"] == "workspace_code_required"


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_ac_21_1_engineer_token_is_403(api: ApiHarness, method: str, path: str):
    session = _finished(api)
    response = api.client.request(method, path.format(id=session.id), headers=token(api, "engineer"))
    assert response.status_code == 403 and response.json()["code"] == "forbidden"


# --- list -------------------------------------------------------------------------------------------


def test_ac_21_2_list_over_http(api: ApiHarness):
    s1, s2 = _finished(api), _active(api)
    body = api.client.get("/api/review/sessions", headers=token(api)).json()
    assert body["counts"] == {"total": 2, "active": 1, "finished": 1, "noCandidate": 0}
    assert (body["matching"], body["truncated"]) == (2, False)
    assert [r["id"] for r in body["rows"]] == [s2.id, s1.id]
    row = body["rows"][1]
    assert (row["processName"], row["steps"], row["messageCount"], row["documentCount"]) == (
        "Monthly cost review",
        5,
        4,
        1,
    )
    filtered = api.client.get("/api/review/sessions?status=finished&q=cost", headers=token(api)).json()
    assert [r["id"] for r in filtered["rows"]] == [s1.id] and filtered["counts"]["total"] == 2


@pytest.mark.parametrize("query", ["status=open", "q=" + "x" * 101, "q="])
def test_ac_21_5_invalid_filters_are_422(api: ApiHarness, query: str):
    response = api.client.get(f"/api/review/sessions?{query}", headers=token(api))
    assert response.status_code == 422 and response.json()["code"] == "invalid_value"


def test_ac_21_7_more_than_the_limit_is_truncated(api: ApiHarness, monkeypatch: pytest.MonkeyPatch):
    for minute in range(4):
        asyncio.run(
            api.repo.create_session(
                Session(owner_id=OWNER, created_at=AT, updated_at=f"2026-11-19T10:0{minute}:00+00:00")
            )
        )
    monkeypatch.setattr(DiscoveryService, "REVIEW_LIMIT", 3)
    body = api.client.get("/api/review/sessions", headers=token(api)).json()
    assert len(body["rows"]) == 3 and body["truncated"] is True
    assert body["rows"][0]["updatedAt"] == "2026-11-19T10:03:00+00:00"


# --- privacy ------------------------------------------------------------------------------------------


def test_ac_21_11_list_and_view_carry_no_private_text(api: ApiHarness):
    session = _finished(api)
    texts = [
        api.client.get("/api/review/sessions", headers=token(api)).text,
        api.client.get(f"/api/review/sessions/{session.id}", headers=token(api)).text,
    ]
    for text in texts:
        for marker in (MARK_MESSAGE, MARK_DOC, MARK_NAME, OWNER, "ownerId", "displayName"):
            assert marker not in text


# --- session view -------------------------------------------------------------------------------------


def test_ac_21_8_session_view_with_etag_header(api: ApiHarness):
    session = _finished(api)
    response = api.client.get(f"/api/review/sessions/{session.id}", headers=token(api))
    assert response.status_code == 200
    body = response.json()
    assert response.headers["ETag"] == body["etag"]
    assert body["summary"]["processName"] == "Monthly cost review"
    assert body["steps"]["rows"][0]["cells"][0]["value"] == session.profile.process.substeps[0].name
    assert body["documents"][0]["name"] == "invoice-procedure.pdf"
    assert body["report"]["map"]["columns"] and body["rawSteps"] is None


def test_ac_21_9_active_session_view_has_no_report(api: ApiHarness):
    session = _active(api)
    body = api.client.get(f"/api/review/sessions/{session.id}", headers=token(api)).json()
    assert body["report"] is None and body["summary"]["status"] == "active"


def test_unknown_session_is_404(api: ApiHarness):
    response = api.client.get("/api/review/sessions/nope", headers=token(api))
    assert response.status_code == 404 and response.json()["code"] == "not_found"


# --- conversation -------------------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["finished", "active"])
def test_ac_21_12_conversation_in_order(api: ApiHarness, which: str):
    session = _finished(api) if which == "finished" else _active(api)
    body = api.client.get(f"/api/review/sessions/{session.id}/conversation", headers=token(api)).json()
    assert body["sessionId"] == session.id
    assert body["messages"] == [
        {"id": m.id, "role": m.role.value, "text": m.text, "at": m.at} for m in session.messages
    ]


# --- PDF ----------------------------------------------------------------------------------------------


def _stable(pdf: bytes) -> bytes:
    """The PDF without the parts reportlab stamps per render (creation time, document id)."""
    pdf = re.sub(rb"/(CreationDate|ModDate) \([^)]*\)", b"", pdf)
    return re.sub(rb"/ID\s*\[[^\]]*\]", b"", pdf)


def test_ac_21_13_pdf_is_the_experts_pdf(api: ApiHarness):
    session = _finished(api)
    mine = api.client.get(f"/api/review/sessions/{session.id}/report.pdf", headers=token(api))
    theirs = api.client.get(f"/api/sessions/{session.id}/report.pdf", headers=visitor(KEY_A))
    assert mine.status_code == 200 and mine.headers["content-type"] == "application/pdf"
    assert mine.headers["content-disposition"] == theirs.headers["content-disposition"]
    assert "discovery-report-monthly-cost-review.pdf" in mine.headers["content-disposition"]
    assert mine.content[:4] == b"%PDF"
    assert _stable(mine.content) == _stable(theirs.content)


def test_ac_21_14_pdf_before_finish_is_409(api: ApiHarness):
    session = _active(api)
    response = api.client.get(f"/api/review/sessions/{session.id}/report.pdf", headers=token(api))
    assert response.status_code == 409 and response.json()["code"] == "report_not_ready"


# --- delete -------------------------------------------------------------------------------------------


def test_ac_21_15_delete_with_etag_keeps_the_ideas(api: ApiHarness):
    session = _finished(api)
    asyncio.run(
        api.repo.create_idea(
            Idea(owner_id=OWNER, name="Supplier onboarding", from_session_id=session.id, created_at=AT)
        )
    )
    etag = api.client.get(f"/api/review/sessions/{session.id}", headers=token(api)).headers["ETag"]
    response = api.client.delete(f"/api/review/sessions/{session.id}", headers={**token(api), "If-Match": etag})
    assert response.status_code == 204 and response.content == b""
    assert api.client.get(f"/api/review/sessions/{session.id}", headers=token(api)).status_code == 404
    assert api.client.get(f"/api/sessions/{session.id}", headers=visitor(KEY_A)).status_code == 404
    ideas = api.client.get("/api/ideas", headers=visitor(KEY_A)).json()["ideas"]
    assert [i["name"] for i in ideas] == ["Supplier onboarding"]


def test_ac_21_15_bare_etag_without_quotes_is_accepted(api: ApiHarness):
    session = _finished(api)
    etag = api.client.get(f"/api/review/sessions/{session.id}", headers=token(api)).headers["ETag"].strip('"')
    response = api.client.delete(f"/api/review/sessions/{session.id}", headers={**token(api), "If-Match": etag})
    assert response.status_code == 204


@pytest.mark.parametrize(("if_match", "status", "code"), [(None, 428, "etag_required"), ('"stale"', 409, "conflict")])
def test_ac_21_16_delete_without_or_with_stale_etag(api: ApiHarness, if_match: str | None, status: int, code: str):
    session = _finished(api)
    headers = token(api) if if_match is None else {**token(api), "If-Match": if_match}
    response = api.client.delete(f"/api/review/sessions/{session.id}", headers=headers)
    assert response.status_code == status and response.json()["code"] == code
    assert asyncio.run(api.repo.find_session(session.id)) is not None


def test_delete_unknown_session_is_404(api: ApiHarness):
    response = api.client.delete("/api/review/sessions/nope", headers={**token(api), "If-Match": '"x"'})
    assert response.status_code == 404


# --- audit --------------------------------------------------------------------------------------------


def test_ac_21_17_one_audit_line_per_action_also_when_refused(api: ApiHarness, caplog: pytest.LogCaptureFixture):
    finished, active = _finished(api), _active(api)
    caplog.set_level(logging.INFO, logger="app.audit")
    headers = token(api)
    api.client.get("/api/review/sessions", headers=headers)
    api.client.get(f"/api/review/sessions/{finished.id}", headers=headers)
    assert _audit(caplog) == []  # opening a session or the list is not logged (Q1)
    calls: list[tuple[str, str, dict[str, str]]] = [
        ("GET", f"/api/review/sessions/{finished.id}/conversation", {}),
        ("GET", f"/api/review/sessions/{active.id}/report.pdf", {}),
        ("DELETE", f"/api/review/sessions/{finished.id}", {}),
        ("DELETE", f"/api/review/sessions/{finished.id}", {"If-Match": '"stale"'}),
    ]
    for method, path, extra in calls:
        api.client.request(method, path, headers={**headers, **extra})
    lines = [(r.action, r.session_id, r.outcome, r.role, r.user_name) for r in _audit(caplog)]  # type: ignore[attr-defined]
    assert lines == [
        ("view_conversation", finished.id, "ok", "specialist", "Maria (IT)"),
        ("download_report", active.id, "report_not_ready", "specialist", "Maria (IT)"),
        ("delete_session", finished.id, "etag_required", "specialist", "Maria (IT)"),
        ("delete_session", finished.id, "conflict", "specialist", "Maria (IT)"),
    ]
    for record in _audit(caplog):
        dumped = json.dumps({k: str(v) for k, v in vars(record).items()})
        assert MARK_MESSAGE not in dumped and MARK_DOC not in dumped and "Monthly cost review" not in dumped


# --- read-only, no model -------------------------------------------------------------------------------


def test_ac_21_18_no_route_writes_or_calls_the_model(api: ApiHarness):
    finished, active = _finished(api), _active(api)
    before = dict(api.repo._documents)
    for session in (finished, active):
        for path in ("", "/conversation", "/report.pdf"):
            api.client.get(f"/api/review/sessions/{session.id}{path}", headers=token(api))
    api.client.get("/api/review/sessions", headers=token(api))
    api.client.delete(f"/api/review/sessions/{finished.id}", headers=token(api))  # refused: no etag
    assert api.repo._documents == before
    assert isinstance(api.llm, FakeLLM) and api.llm.calls == []


# --- camelCase ----------------------------------------------------------------------------------------


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}  # pyright: ignore[reportUnknownVariableType]
    return set()


def test_ac_21_19_wire_models_are_camel_case(api: ApiHarness):
    session = _finished(api)
    for path in ("", f"/{session.id}", f"/{session.id}/conversation"):
        body = api.client.get(f"/api/review/sessions{path}", headers=token(api)).json()
        assert not [k for k in _keys(body) if "_" in k]
    models = (ReviewRowOut, ReviewCountsOut, ReviewListOut, SummaryOut, GridCellOut, GridRowOut, StepGridOut,
              DocumentMetaOut, ReviewSessionOut, ConversationOut)  # fmt: skip
    for model in models:
        schema = model.model_json_schema(by_alias=True)
        assert not [k for k in schema.get("properties", {}) if "_" in k], model.__name__


# --- spec 24 §3.12: seeded evaluation sessions are marked simulated ----------------------------------


def test_spec_24_simulated_sessions_are_tagged_in_the_list_and_the_view(api: ApiHarness):
    real = _active(api)
    seeded = asyncio.run(
        api.repo.create_session(eu_session(owner_id=OWNER, id="eval-p01-cooperative", simulated=True, updated_at=AT))
    )
    rows = {r["id"]: r for r in api.client.get("/api/review/sessions", headers=token(api)).json()["rows"]}
    assert rows[seeded.id]["simulated"] is True and rows[real.id]["simulated"] is False
    view = api.client.get(f"/api/review/sessions/{seeded.id}", headers=token(api)).json()
    assert view["simulated"] is True


def test_spec_24_old_documents_load_as_not_simulated_and_experts_cannot_set_it(api: ApiHarness):
    stored = Session.model_validate({"ownerId": OWNER, "createdAt": AT, "updatedAt": AT})
    assert stored.simulated is False
    created = api.client.post("/api/sessions", json={"displayName": "x", "simulated": True}, headers=visitor())
    assert created.status_code in (201, 422)
    if created.status_code == 201:
        stored_session = asyncio.run(api.repo.get_session(OWNER, created.json()["id"]))
        assert stored_session is not None and stored_session.simulated is False
