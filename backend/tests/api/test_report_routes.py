"""API tests for *Finish* with the assessment and the report routes (spec 20 §3.2, §3.5).

Why: *Finish* is where the product spends four model calls and writes the session one last time,
so it must refuse cheaply (not ready, no budget), never pay twice (a second click, a save
conflict), and save exactly once; and the report and the PDF must be the caller's own, only after
*Finish*, and never call the model.
What: the real app with a service on the memory store, the NIG configuration (with the example
catalogue of spec 26), and a `FakeLLM` scripted with the worked replies; the repository's
`replace_session` is wrapped to count writes or to force a concurrent change.
Must not: patch a route or the assessment.
Covers AC-20.13 to AC-20.17, AC-20.44.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.api.process_discovery_routes import get_service
from app.core.access import owner_from_key
from app.core.config import CompanyConfig
from app.models.process_discovery_schemas import Phase, Profile, Session, SessionStatus
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.service import DiscoveryService
from tests.fixtures.assessment.profiles import load_profile
from tests.fixtures.assessment_19.cases import example_catalogue
from tests.unit.process_discovery.export.cases import scripted_llm

from .conftest import KEY_B, NIG, ApiHarness, TickingClock, build_harness, visitor

OWNER = owner_from_key("visitor-a-0123456789abcdef")


def _harness(company: CompanyConfig, llm: FakeLLM | None = None, **service_kw: Any) -> ApiHarness:
    api = build_harness(company)
    llm = llm or scripted_llm()
    service = DiscoveryService(
        api.repo, llm, api.service.ctx, api.service.graph, clock=TickingClock(),
        company=company.model_copy(update={"solutions": example_catalogue()}), config_dir=NIG,
        assessment_timeout=5, **service_kw,
    )  # fmt: skip
    api.client.app.dependency_overrides[get_service] = lambda: service  # pyright: ignore[reportAttributeAccessIssue]
    api.service, api.llm = service, llm
    return api


def _seed(api: ApiHarness, profile: dict[str, Any] | None = None) -> Session:
    return asyncio.run(api.seed(OWNER, phase="review", profile=profile or load_profile("eu")))


def _count_writes(api: ApiHarness) -> list[str]:
    writes: list[str] = []
    real = api.repo.replace_session

    async def counting(session: Session) -> Session:
        writes.append(session.etag or "")
        return await real(session)

    api.repo.replace_session = counting  # type: ignore[method-assign]
    return writes


def _finish(api: ApiHarness, session_id: str, key: str = "visitor-a-0123456789abcdef"):
    return api.client.post(f"/api/sessions/{session_id}/finish", headers=visitor(key))


@pytest.fixture
def api(company: CompanyConfig) -> ApiHarness:
    return _harness(company)


def test_ac_20_13_finish_runs_the_assessment_and_saves_once_with_if_match(api: ApiHarness):
    seeded = _seed(api)
    writes = _count_writes(api)
    response = _finish(api, seeded.id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["status"], body["phase"], body["reportStatus"]) == ("finished", "finished", "mapped")
    assert writes == [seeded.etag]
    stored = asyncio.run(api.repo.get_session(OWNER, seeded.id))
    assert stored is not None and stored.finished_at and stored.ttl is None
    assert stored.assessment is not None and stored.assessment.value is not None
    assert stored.assessment.outcomes == dict.fromkeys(("opportunities", "diagram", "labels", "steps"), "generated")
    assert len(api.llm.calls) == 4  # pyright: ignore[reportOptionalMemberAccess]
    assert '"ttl"' not in api.repo._documents[(OWNER, seeded.id)]  # pyright: ignore[reportPrivateUsage]


def test_ac_20_14_finish_on_a_map_that_is_not_ready_makes_no_call(company: CompanyConfig):
    api = _harness(company, FakeLLM())
    profile = load_profile("eu")
    profile["process"]["tools_confirmed"] = False
    seeded = _seed(api, profile)
    response = _finish(api, seeded.id)
    assert response.status_code == 409
    assert (response.json()["code"], response.json()["reason"]) == ("map_incomplete", "tools_not_confirmed")
    assert api.llm.calls == []  # pyright: ignore[reportOptionalMemberAccess]


def test_ac_20_15_a_second_finish_returns_the_stored_session_with_no_call_and_no_write(api: ApiHarness):
    seeded = _seed(api)
    first = _finish(api, seeded.id).json()
    calls = len(api.llm.calls)  # pyright: ignore[reportOptionalMemberAccess]
    writes = _count_writes(api)
    again = _finish(api, seeded.id)
    assert again.status_code == 200 and again.json()["finishedAt"] == first["finishedAt"]
    assert writes == [] and len(api.llm.calls) == calls  # pyright: ignore[reportOptionalMemberAccess]


def test_ac_20_16_an_exhausted_budget_is_429_and_nothing_changes(company: CompanyConfig):
    api = _harness(company, FakeLLM(), budget_guard=lambda _call: False)
    seeded = _seed(api)
    response = _finish(api, seeded.id)
    assert response.status_code == 429 and response.json()["code"] == "budget_exhausted"
    assert api.llm.calls == []  # pyright: ignore[reportOptionalMemberAccess]
    assert asyncio.run(api.repo.get_session(OWNER, seeded.id)) == seeded


def _conflict_with(api: ApiHarness, change: Any) -> None:
    """The first save meets a concurrent write made by `change(stored) -> stored`."""
    real = api.repo.replace_session
    state = {"done": False}

    async def racing(session: Session) -> Session:
        if not state["done"]:
            state["done"] = True
            current = await api.repo.get_session(OWNER, session.id)
            assert current is not None
            await real(change(current))
        return await real(session)

    api.repo.replace_session = racing  # type: ignore[method-assign]


def test_ac_20_17_a_conflict_on_an_unchanged_session_saves_on_the_second_try(api: ApiHarness):
    seeded = _seed(api)
    _conflict_with(api, lambda s: s.model_copy(update={"updated_at": "2026-11-19T11:00:00+00:00"}))
    response = _finish(api, seeded.id)
    assert response.status_code == 200 and response.json()["status"] == "finished"
    assert len(api.llm.calls) == 4  # pyright: ignore[reportOptionalMemberAccess]


def test_ac_20_17_a_conflict_on_a_changed_session_is_409(api: ApiHarness):
    seeded = _seed(api)

    def edit(s: Session) -> Session:
        profile = s.profile.model_dump(mode="json", by_alias=True)
        profile["process"]["substeps"][0]["pain_points"].append("a new pain")
        return s.model_copy(update={"profile": Profile.model_validate(profile)})

    _conflict_with(api, edit)
    response = _finish(api, seeded.id)
    assert response.status_code == 409 and response.json()["code"] == "conflict"
    assert len(api.llm.calls) == 4  # pyright: ignore[reportOptionalMemberAccess]


def test_ac_20_17_a_conflict_with_a_finish_elsewhere_returns_that_one(api: ApiHarness):
    seeded = _seed(api)
    _conflict_with(api, lambda s: s.model_copy(update={"status": SessionStatus.FINISHED, "phase": Phase.FINISHED,
                                                        "finished_at": "2026-11-19T11:00:00+00:00"}))  # fmt: skip
    response = _finish(api, seeded.id)
    assert response.status_code == 200 and response.json()["finishedAt"] == "2026-11-19T11:00:00+00:00"


def test_the_report_is_409_before_finish_and_404_for_another_visitor(api: ApiHarness):
    seeded = _seed(api)
    for path in ("report", "report.pdf"):
        response = api.client.get(f"/api/sessions/{seeded.id}/{path}", headers=visitor())
        assert response.status_code == 409 and response.json()["code"] == "report_not_ready"
    _finish(api, seeded.id)
    for path in ("report", "report.pdf"):
        assert api.client.get(f"/api/sessions/{seeded.id}/{path}", headers=visitor(KEY_B)).status_code == 404
        assert api.client.get(f"/api/sessions/{seeded.id}/{path}").status_code == 401


def test_ac_20_44_the_report_and_its_pdf_make_no_model_call(api: ApiHarness):
    seeded = _seed(api)
    _finish(api, seeded.id)
    calls = len(api.llm.calls)  # pyright: ignore[reportOptionalMemberAccess]
    report = api.client.get(f"/api/sessions/{seeded.id}/report", headers=visitor())
    assert report.status_code == 200
    body = report.json()
    assert body["atAGlance"]["hours"] == "About 342 hours a year."
    assert [body[k]["number"] for k in ("atAGlance", "process", "measures", "map", "steps", "route", "assessment",
                                        "potential", "readiness", "path", "gaps")] == list(range(1, 12))  # fmt: skip
    pdf = api.client.get(f"/api/sessions/{seeded.id}/report.pdf", headers=visitor())
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"] == 'attachment; filename="discovery-report-monthly-cost-review.pdf"'
    assert len(api.llm.calls) == calls  # pyright: ignore[reportOptionalMemberAccess]
