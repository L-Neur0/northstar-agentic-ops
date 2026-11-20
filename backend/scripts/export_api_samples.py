"""Writes real JSON responses of the interview API for the frontend contract tests (spec 23 §3.12.6 and Q1).

Why: the frontend mirrors the wire models by hand, so a drift between the two only shows when the
browser meets the real server; recording real responses lets the frontend tests parse exactly what
the API sends, without a running server or a model.
What: builds the real app on the in-memory store with the scripted model (the same harness and
script as the API flow test), plays the monthly cost review, and saves one file per response
(create session, a turn, set cluster, finish blocked, confirm roles, finish ok, list sessions, list
ideas, taxonomy, config, and the 401 / 404 / 422 error bodies) into `frontend/src/test/fixtures/api/`.
Spec 23 part 2 adds the document samples (upload of the procedure .docx with its scripted reply,
the document list, confirm, reject, remove, the 415 refusal) and the report samples (the report of
the finished EU profile, built with the scripted assessment of the report route tests, and the 409
`report_not_ready` body).
Must not: call Azure, read `.env`, or write anywhere else. Rerun with
`cd backend && uv run python scripts/export_api_samples.py`. Spec 15 part 2 §3.3–3.4; AC-23.5.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import load_company_config  # noqa: E402
from app.services.process_discovery.llm import CallType  # noqa: E402
from tests.api.conftest import KEY_A, KEY_B, NIG, build_harness, visitor  # noqa: E402
from tests.api.test_interview_flow import CLASSIFY, SCRIPT  # noqa: E402

OUT = BACKEND.parent / "frontend" / "src" / "test" / "fixtures" / "api"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    api = build_harness(load_company_config(NIG))
    assert api.llm is not None
    api.llm.add(CallType.EXTRACT, *(reply for _, reply in SCRIPT))
    api.llm.add(CallType.GUIDE, *["Could you tell me more?"] * 40)
    api.llm.add(CallType.CLASSIFY, *[CLASSIFY] * 10)
    client = api.client
    written: list[str] = []

    def save(name: str, response: Any, expected: int) -> Any:
        assert response.status_code == expected, (name, response.status_code, response.text)
        data = response.json()
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(name)
        return data

    session = save("create-session", client.post("/api/sessions", json={"displayName": "Anna"}, headers=visitor()), 201)
    sid = session["id"]
    for index, (text, _) in enumerate(SCRIPT):
        response = client.post(f"/api/sessions/{sid}/messages", json={"text": text}, headers=visitor())
        if index == 3:  # the turn that keeps an idea
            save("turn", response, 200)
        assert response.status_code == 200, response.text
    save("set-cluster", client.put(f"/api/sessions/{sid}/cluster", json={"code": "FIN"}, headers=visitor()), 200)
    save("finish-blocked", client.post(f"/api/sessions/{sid}/finish", headers=visitor()), 409)
    save("confirm-roles", client.post(f"/api/sessions/{sid}/confirm", json={"target": "roles"}, headers=visitor()), 200)
    client.post(f"/api/sessions/{sid}/confirm", json={"target": "tools"}, headers=visitor())
    save("finish-ok", client.post(f"/api/sessions/{sid}/finish", headers=visitor()), 200)
    save("list-sessions", client.get("/api/sessions", headers=visitor()), 200)
    save("list-ideas", client.get("/api/ideas", headers=visitor()), 200)
    save("taxonomy", client.get("/api/taxonomy"), 200)
    save("config", client.get("/api/config"), 200)
    save("error-visitor-key", client.get("/api/sessions"), 401)
    save("error-not-found", client.get(f"/api/sessions/{sid}", headers=visitor(KEY_B)), 404)
    save(
        "error-invalid-value",
        client.post(f"/api/sessions/{sid}/messages", json={"text": ""}, headers=visitor(KEY_A)),
        422,
    )
    document_samples(save)
    report_samples(save)
    print(f"wrote {len(written)} samples to {OUT.relative_to(BACKEND.parent)}: {', '.join(written)}")


def document_samples(save: Any) -> None:
    """Spec 23 part 2: the document routes on worked example 1 (the procedure .docx, scripted reply)."""
    import asyncio

    from app.core.access import owner_from_key
    from tests.unit.process_discovery.documents.helpers import FIXTURES, procedure_profile, procedure_reply

    api = build_harness(load_company_config(NIG))
    assert api.llm is not None
    api.llm.add(CallType.READ_DOCUMENT, procedure_reply())
    seeded = asyncio.run(api.seed(owner_from_key(KEY_A), profile=procedure_profile(api.service.ctx.vocab)))
    client, sid = api.client, seeded.id
    docx = (FIXTURES / "cost_review_procedure.docx").read_bytes()
    kind = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    files = {"file": ("Monthly cost review procedure.docx", docx, kind)}
    upload = save("upload-document", client.post(f"/api/sessions/{sid}/documents", files=files, headers=visitor()), 201)
    save("list-documents", client.get(f"/api/sessions/{sid}/documents", headers=visitor()), 200)
    proposed = [v["key"] for v in upload["session"]["fieldViews"] if v["status"] == "proposed"]
    save(
        "confirm-proposals",
        client.post(f"/api/sessions/{sid}/proposals/confirm", json={"keys": proposed[:1]}, headers=visitor()),
        200,
    )
    save(
        "reject-proposals",
        client.post(f"/api/sessions/{sid}/proposals/reject", json={"keys": proposed[1:2]}, headers=visitor()),
        200,
    )
    doc_id = upload["document"]["id"]
    save("remove-document", client.delete(f"/api/sessions/{sid}/documents/{doc_id}", headers=visitor()), 200)
    bad = {"file": ("photo.png", b"not a document", "image/png")}
    save("error-document-type", client.post(f"/api/sessions/{sid}/documents", files=bad, headers=visitor()), 415)


def report_samples(save: Any) -> None:
    """Spec 23 part 2: the report of the finished EU profile, and 409 `report_not_ready` before *Finish*."""
    import asyncio

    from app.api.process_discovery_routes import get_service
    from app.core.access import owner_from_key
    from app.services.process_discovery.service import DiscoveryService
    from tests.api.conftest import TickingClock
    from tests.fixtures.assessment.profiles import load_profile
    from tests.fixtures.assessment_19.cases import example_catalogue
    from tests.unit.process_discovery.export.cases import scripted_llm

    company = load_company_config(NIG)
    api = build_harness(company)
    service = DiscoveryService(
        api.repo, scripted_llm(), api.service.ctx, api.service.graph, clock=TickingClock(),
        company=company.model_copy(update={"solutions": example_catalogue()}), config_dir=NIG,
        assessment_timeout=5,
    )  # fmt: skip
    api.client.app.dependency_overrides[get_service] = lambda: service  # pyright: ignore[reportAttributeAccessIssue]
    api.service = service
    seeded = asyncio.run(api.seed(owner_from_key(KEY_A), phase="review", profile=load_profile("eu")))
    client, sid = api.client, seeded.id
    save("error-report-not-ready", client.get(f"/api/sessions/{sid}/report", headers=visitor()), 409)
    finished = client.post(f"/api/sessions/{sid}/finish", headers=visitor())
    assert finished.status_code == 200, finished.text
    save("report", client.get(f"/api/sessions/{sid}/report", headers=visitor()), 200)


if __name__ == "__main__":
    main()
