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

import asyncio
from typing import Any

from app.core.access import owner_from_key
from app.services.process_discovery.llm import CallType
from tests.unit.process_discovery.profile.builders import step_changes

from .conftest import KEY_A, ApiHarness, visitor

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
    # no roles and systems confirmation (spec 14 §3.20 O10, AC-14.127): straight to the review
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


def _tier_a(index: int) -> dict[str, Any]:
    cell = f"process.substeps[{index}]"
    return {
        f"{cell}.activities": ["export the actuals", "check the totals"],
        f"{cell}.systems": ["SAP", "Excel"],
        f"{cell}.data": {"inputs": [f"input {index}"], "outputs": [f"output {index}"]},
        f"{cell}.pain_points": ["chasing the sites"],
        f"{cell}.roles": [{"role": "Site controller"}],
        f"{cell}.decision_type": {"kind": "mix", "evidence": "mostly fixed rules"},
    }


SHORT_WALK: list[tuple[str, dict[str, Any]]] = [
    *SCRIPT[:9],
    (
        "Collect the cost data, then report.",
        {"process.substep_count": 2, "process.substeps[1].name": "Collect", "process.substeps[2].name": "Report"},
    ),
    ("I export the actuals from SAP ...", _tier_a(1)),
    (
        "No sign-off; sometimes the totals do not match.",
        {
            "process.substeps[1].approvals": [{"none": True}],
            "process.substeps[1].exceptions": [{"description": "the totals do not match"}],
        },
    ),  # fmt: skip
    ("I write the report in Excel ...", _tier_a(2)),
    ("No.", {}),
    (
        "Two hours and one day, monthly.",
        {
            "process.substeps[1].effort": {"duration": "2 hours", "frequency": "monthly"},
            "process.substeps[2].effort": {"duration": "1 day", "frequency": "monthly"},
        },
    ),
]


def _view(session: dict[str, Any], key: str) -> dict[str, Any]:
    return next(v for v in session["fieldViews"] if v["key"] == key)


def test_ac_14_114_the_short_step_walk_through_the_api(api: ApiHarness):
    """Spec 14 §3.19 (amended §3.20) through the HTTP API: grouped questions, agent proposals, one bulk yes in the
    review; the step names show at once (AC-14.124) and the progress is on the wire (AC-14.120)."""
    llm = api.llm
    assert llm is not None
    llm.add(CallType.EXTRACT, *(reply for _, reply in SHORT_WALK), {}, {})
    llm.add(CallType.GUIDE, *["Could you tell me more?"] * 40)
    llm.add(CallType.CLASSIFY, *[CLASSIFY] * 10)
    sid = api.create()["id"]
    session: dict[str, Any] = {}
    focus: list[list[str]] = []
    views: list[dict[str, Any]] = []
    for text, _ in SHORT_WALK:
        response = api.client.post(f"/api/sessions/{sid}/messages", json={"text": text}, headers=visitor())
        assert response.status_code == 200, response.text
        session = response.json()["session"]
        views.append(session)
        stored = asyncio.run(api.repo.get_session(owner_from_key(KEY_A), sid))
        assert stored is not None
        focus.append(stored.last_question.focus)
    assert focus[9] == [f"process.substeps[1].{leaf}" for leaf in
                        ("activities", "roles", "systems", "data", "pain_points", "decision_type")]  # fmt: skip
    assert focus[10] == [f"process.substeps[1].{leaf}" for leaf in
                         ("approvals", "exceptions", "handover", "decision_criteria")]  # §3.21 P1: a mix step  # fmt: skip
    # AC-14.124: the names are in the profile and the step views right after the expert listed them
    assert [r["name"] for r in views[9]["profile"]["process"]["substeps"]] == ["Collect", "Report"]
    assert _view(views[9], "process.substeps[1].name")["status"] == "complete"
    assert 0 < views[8]["score"]["progress"] < views[9]["score"]["progress"] < 1  # AC-14.120 on the wire
    assert focus[13] == ["process.substeps[1].effort", "process.substeps[2].effort"]
    assert not any(k.endswith((".goal", ".owner")) for f in focus for k in f)
    goal = _view(session, "process.substeps[1].goal")
    assert (goal["status"], goal["source"]) == ("proposed", "agent") and goal["quote"]

    session = api.client.put(f"/api/sessions/{sid}/cluster", json={"code": "FIN"}, headers=visitor()).json()
    assert session["phase"] == "review" and session["finish"]["ready"] is True

    # The buttons do not speak: the next message gets the review question, the agent's proposals in one group.
    api.client.post(f"/api/sessions/{sid}/messages", json={"text": "What else?"}, headers=visitor())
    stored = asyncio.run(api.repo.get_session(owner_from_key(KEY_A), sid))
    assert stored is not None and "process.substeps[1].goal" in stored.last_question.proposals
    response = api.client.post(f"/api/sessions/{sid}/messages", json={"text": "yes"}, headers=visitor())
    after = response.json()["session"]
    assert _view(after, "process.substeps[1].goal")["status"] == "complete"
    assert _view(after, "process.substeps[2].owner")["status"] == "complete"
    assert after["score"]["value"] > session["score"]["value"]
