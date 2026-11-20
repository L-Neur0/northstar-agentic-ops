"""Opt-in live test: one small procedure uploaded through the HTTP API, read by the real Azure model, then confirmed (spec 17 §3.1, §3.12; architecture §3.4).

Why: the API tests prove the document routes with a scripted model; only a real call proves that
the upload route, the service and the READ_DOCUMENT call compose end to end: the multipart body
is parsed, the real model fills the strict schema with quotes that survive the code check, the
proposals land in the session as `proposed`, and a ✓ makes them count.
What: with `RUN_LIVE=1`, builds the app from `backend/.env` with the in-memory store (your
`az login`, no key, cache off), creates a session, uploads `cost_review_procedure.docx` from
`tests/fixtures/documents/`, prints the report counts and the sentence, checks at least one value
was kept, confirms every pending proposal and checks they count.
Must not: run by default or in CI (marked `live`, skipped), use a key, or print the document text.
Covers AC-17.32 (a real reply through the pipeline) at the API level.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.main import create_app

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="live Azure OpenAI; set RUN_LIVE=1"),
]

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "cost_review_procedure.docx"


def test_live_upload_through_the_api_proposes_quoted_values_the_expert_can_confirm():
    settings = Settings(store="memory", llm_cache_enabled=False)  # pyright: ignore[reportCallIssue]
    headers = {"X-Visitor-Key": secrets.token_urlsafe(24)}
    with TestClient(create_app(settings)) as client:
        session = client.post("/api/sessions", json={}, headers=headers).json()
        response = client.post(
            f"/api/sessions/{session['id']}/documents",
            files={
                "file": (
                    FIXTURE.name,
                    FIXTURE.read_bytes(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        report = body["report"]
        print(f"\nkept={report['kept']} dropped={report['dropped']} message={report['message']!r}")
        assert report["outcome"] == "read"
        assert report["kept"]["fields"] + report["kept"]["steps"] + report["kept"]["cells"] > 0
        pending = [v["key"] for v in body["session"]["fieldViews"] if v["status"] == "proposed"]
        assert pending and all(v["quote"] for v in body["session"]["fieldViews"] if v["status"] == "proposed")
        confirmed = client.post(
            f"/api/sessions/{session['id']}/proposals/confirm", json={"keys": pending}, headers=headers
        )
        assert confirmed.status_code == 200, confirmed.text
        after = confirmed.json()
        assert after["documents"][0]["pending"] == 0
        assert after["score"]["filledPoints"] > body["session"]["score"]["filledPoints"]
