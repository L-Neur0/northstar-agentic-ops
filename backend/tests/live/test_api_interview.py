"""Opt-in live test: one short interview through the HTTP API against Azure OpenAI and Cosmos DB, to *Finish* (spec 15 part 2 §7; AC-15.52).

Why: the scripted API test proves the routes compose with a fake model; only the real model and
the real container prove the wiring end to end: the lifespan builds the client with `az login`
(no key), the turns run the real prompts, the whole session is saved to Cosmos with its etag on
every call, and *Finish* opens on a map the real model helped fill.
What: with `RUN_LIVE=1`, builds the app from `backend/.env` with `STORE=cosmos`, plays a
cooperative expert describing the monthly cost review with 2 steps (each message answers the
first open field shown in `fieldViews`, so the script follows the interview rather than a fixed
order), confirms the cluster when the agent proposes one (the picker otherwise), presses Confirm
roles, Confirm systems and *Finish*, and prints the turn count, the session id and the owner
prefix. The session is left in Cosmos for inspection.
Must not: run by default or in CI (marked `live`, skipped), use a key, or loop without a bound.
"""

from __future__ import annotations

import os
import secrets
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.access import owner_from_key
from app.core.settings import Settings
from app.main import create_app

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="live Azure OpenAI and Cosmos; set RUN_LIVE=1"),
]

MAX_TURNS = 30
OPEN = {"empty", "partial", "invalid"}

ANSWERS: dict[str, str] = {
    "department": "I work in Finance.",
    "user_function": "I am a cost controller.",
    "region": "I am based in Europe.",
    "process.name": "The process is the monthly cost review.",
    "process.trigger": "It starts when the month-end close is completed in the ledger.",
    "process.end_result": "At the end we have the monthly cost report.",
    "process.value_at_end": "The CFO uses the report to decide on budget corrections.",
    "process.business_pain": "Chasing explanations for cost variances takes days.",
    "process.volume": "We do it once a month.",
    "process.process_owner": "The Head of Controlling owns the process.",
    "process.baseline_metric": "Today it takes about 4 working days.",
    "process.target_metric": "We would like it to take 2 working days.",
    "process.variation": "It runs the same way every month and at every site.",
    "process.sensitive_data": "No personal or sensitive data is involved, only cost figures.",
    "process.substep_count": "There are 2 steps.",
}
STEPS = {
    1: (
        "Step 1 is 'Export and check the actuals'. The goal is a clean set of actual costs. "
        "I export the actuals from SAP and check them against the budget. The controller does it and owns "
        "the step. Input: the ledger actuals; output: a variance list. It takes about 2 hours, once a month. "
        "The pain point is that the export is slow. There are no approvals and no exceptions. "
        "I hand the variance list over by e-mail."
    ),
    2: (
        "Step 2 is 'Write and send the report'. The goal is that the CFO receives the monthly cost report. "
        "I write the comments in Excel and send the report. The controller writes it and the Head of Controlling "
        "approves it; the controller owns the step. Systems: Excel and Outlook. Input: the variance list; "
        "output: the cost report. It takes about 4 hours, once a month. The pain point is chasing comments. "
        "The approval waits about one day. No exceptions. The report is sent to the CFO by e-mail."
    ),
}


def _next_message(session: dict[str, Any], asked: dict[str, int]) -> str | None:
    """The answer to the first open field; each answer is sent at most twice."""
    for view in session["fieldViews"]:
        key, status = view["key"], view["status"]
        if status not in OPEN or key == "process.cluster":
            continue
        if key.startswith("process.substeps["):
            step = int(key.split("[", 1)[1].split("]", 1)[0])
            answer, tag = STEPS.get(step), f"step{step}"
        else:
            answer, tag = ANSWERS.get(key), key
        if answer is None or asked.get(tag, 0) >= 2:
            continue
        asked[tag] = asked.get(tag, 0) + 1
        return answer
    return None


def test_ac_15_52_live_interview_through_the_api_reaches_finish():
    settings = Settings(store="cosmos")  # pyright: ignore[reportCallIssue]
    if not settings.azure_openai_endpoint or not settings.cosmos_endpoint:
        pytest.skip("AZURE_OPENAI_ENDPOINT and COSMOS_ENDPOINT are needed")
    key = "live-api-" + secrets.token_hex(12)
    headers = {"X-Visitor-Key": key}
    with TestClient(create_app(settings)) as client:
        session = client.post("/api/sessions", json={"displayName": "Live test"}, headers=headers).json()
        sid = session["id"]
        asked: dict[str, int] = {}
        turns = 0
        while session["phase"] not in ("confirm", "review") and turns < MAX_TURNS:
            cluster_open = next(v for v in session["fieldViews"] if v["key"] == "process.cluster")["status"] in OPEN
            if session["clusterProposal"] is not None:
                text: str | None = "Yes, that cluster fits."
            else:
                text = _next_message(session, asked)
            if text is None and cluster_open:
                response = client.put(f"/api/sessions/{sid}/cluster", json={"code": "FIN"}, headers=headers)
                assert response.status_code == 200, response.text
                session = response.json()
                continue
            if text is None:
                text = "That is everything I can tell you about it."
            response = client.post(f"/api/sessions/{sid}/messages", json={"text": text}, headers=headers)
            assert response.status_code == 200, response.text
            session = response.json()["session"]
            turns += 1
            print(f"turn {turns}: phase={session['phase']} score={session['score']['value']}")
        if session["profile"]["process"]["cluster"]["code"] == "":
            session = client.put(f"/api/sessions/{sid}/cluster", json={"code": "FIN"}, headers=headers).json()
        for target in ("roles", "tools"):
            response = client.post(f"/api/sessions/{sid}/confirm", json={"target": target}, headers=headers)
            assert response.status_code == 200, response.text
            session = response.json()
        print(f"before finish: phase={session['phase']} finish={session['finish']}")
        finished = client.post(f"/api/sessions/{sid}/finish", headers=headers)
        print(f"live session {sid} owner {owner_from_key(key)[:8]} turns={turns} finish={finished.status_code}")
        assert finished.status_code == 200, finished.text
        assert finished.json()["status"] == "finished"
        [summary] = [s for s in client.get("/api/sessions", headers=headers).json()["sessions"] if s["id"] == sid]
        assert summary["status"] == "finished"
