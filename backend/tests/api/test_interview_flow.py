"""A whole interview through the HTTP API with a scripted model, from the welcome to *Finish* (spec 15 part 2 §7; AC-15.51).

Why: each route is tested on its own elsewhere; only a full run proves they compose: the session
the client gets back after every call is the state the next call starts from, the phase walks
forward, the expert's buttons (cluster picker, Confirm roles, Confirm systems) do what the chat
does not, and *Finish* opens exactly when the map is complete.
What: the monthly cost review with two steps, told in 12 expert messages; the EXTRACT replies are
scripted one per message, GUIDE and CLASSIFY replies are generic. Then the picker sets the
cluster, both lists are confirmed, *Finish* is pressed, and the session is listed as finished.
Must not: patch a route, a node or a writer, or reach into the store to move the interview.
"""

from __future__ import annotations

from typing import Any

from app.services.process_discovery.llm import CallType
from tests.unit.process_discovery.profile.builders import step_changes

from .conftest import ApiHarness, visitor

SCOPE = {
    "multi_role": True,
    "multi_system": True,
    "trigger_and_outcome": True,
    "recurring": True,
    "external_consumer": True,
    "reasoning": "several roles and systems",
}
CLASSIFY = {
    "scope": SCOPE,
    "placement": {
        "code": "FIN",
        "confidence": 0.9,
        "rationale": "cost work",
        "runner_up": None,
        "runner_up_confidence": None,
    },
}

SCRIPT: list[tuple[str, dict[str, Any]]] = [
    ("I work in Finance.", {"department": "Finance"}),
    ("I am a cost controller.", {"user_function": "Cost controller"}),
    ("Europe.", {"region": "Europe"}),
    (
        "The monthly cost review. We also onboard suppliers, but that is another story.",
        {
            "process.name": "Monthly cost review",
            "candidates": [{"name": "Supplier onboarding", "words": "We also onboard suppliers"}],
        },
    ),
    (
        "It starts when the month-end close is done in the ledger.",
        {"process.trigger": "Month-end close is completed in the ledger"},
    ),
    (
        "At the end there is the monthly cost report, and the CFO uses it.",
        {
            "process.end_result": "The monthly cost report",
            "process.value_at_end": "The CFO uses it to decide on budget corrections",
            "process.business_pain": "Chasing explanations takes days",
        },
    ),
    (
        "Once a month; the Head of Controlling owns it; it takes about 4 days.",
        {
            "process.volume": {"count": 1, "period": "month"},
            "process.process_owner": {"role": "Head of Controlling"},
            "process.baseline_metric": {"value": "4", "unit": "days"},
        },
    ),
    ("We want 2 days. It is the same every month.", {"process.target_metric": {"value": "2", "unit": "days"}}),
    (
        "Same everywhere; no personal data.",
        {"process.variation": {"same": "yes"}, "process.sensitive_data": [{"none": True}]},
    ),
    ("Two steps.", {"process.substep_count": 2}),
    ("First we export and check the actuals.", step_changes(1)),
    ("Then we write and send the report.", step_changes(2)),
]


def test_ac_15_51_a_scripted_interview_reaches_finish_through_the_api(api: ApiHarness):
    llm = api.llm
    assert llm is not None
    llm.add(CallType.EXTRACT, *(reply for _, reply in SCRIPT))
    llm.add(CallType.GUIDE, *["Could you tell me more?"] * 40)
    llm.add(CallType.CLASSIFY, *[CLASSIFY] * 10)

    session = api.create(displayName="Anna")
    sid = session["id"]
    phases = [session["phase"]]
    ideas = 0
    for text, _ in SCRIPT:
        response = api.client.post(f"/api/sessions/{sid}/messages", json={"text": text}, headers=visitor())
        assert response.status_code == 200, response.text
        turn = response.json()
        session = turn["session"]
        ideas += turn["ideasAdded"]
        phases.append(session["phase"])
    assert len(SCRIPT) >= 12
    assert ideas == 1
    order = list(dict.fromkeys(phases))
    assert order[0] == "context" and order.index("measure") < order.index("steps")

    # The generic GUIDE reply never names the proposed cluster, so the expert uses the picker.
    assert session["profile"]["process"]["cluster"]["code"] == ""
    response = api.client.put(f"/api/sessions/{sid}/cluster", json={"code": "FIN"}, headers=visitor())
    assert response.status_code == 200
    session = response.json()
    assert session["phase"] == "confirm"
    assert session["finish"]["blockedBy"] == "roles_not_confirmed"

    early = api.client.post(f"/api/sessions/{sid}/finish", headers=visitor())
    assert early.status_code == 409 and early.json()["reason"] == "roles_not_confirmed"

    for target in ("roles", "tools"):
        response = api.client.post(f"/api/sessions/{sid}/confirm", json={"target": target}, headers=visitor())
        assert response.status_code == 200
        session = response.json()
    assert session["phase"] == "review" and session["finish"]["ready"] is True

    finished = api.client.post(f"/api/sessions/{sid}/finish", headers=visitor())
    assert finished.status_code == 200
    assert (finished.json()["status"], finished.json()["reportStatus"]) == ("finished", "mapped")

    [summary] = api.client.get("/api/sessions", headers=visitor()).json()["sessions"]
    assert summary["id"] == sid and summary["status"] == "finished"
    assert summary["processName"] == "Monthly cost review" and summary["clusterCode"] == "FIN"
    assert summary["messageCount"] == 1 + 2 * len(SCRIPT)
    [idea] = api.client.get("/api/ideas", headers=visitor()).json()["ideas"]
    assert idea["name"] == "Supplier onboarding"
