"""API tests for ideas and "delete my data" (spec 15 part 2 §3.3; product F-01, F-23; AC-15.38, AC-15.44, AC-15.45).

Why: ideas are the processes an expert mentions in passing; they must be kept once, listed only to
their owner, dismissable, and startable exactly once. "Delete my data" must remove everything of
the caller and nothing of anyone else, because it is the expert's privacy promise.
What: a turn in `find` that names a second process stores one idea; listing, dismissing and
starting go over HTTP; `DELETE /api/me` counts and removes the caller's documents.
Must not: patch a route or a node.
"""

from __future__ import annotations

import asyncio

from app.core.access import owner_from_key
from app.models.process_discovery_schemas import Idea
from app.services.process_discovery.llm import CallType

from .conftest import KEY_A, KEY_B, ApiHarness, visitor

OWNER_A = owner_from_key(KEY_A)
OWNER_B = owner_from_key(KEY_B)
AT = "2026-11-19T09:00:00+00:00"


def _idea(api: ApiHarness, owner: str = OWNER_A, name: str = "Supplier onboarding"):
    idea = Idea(owner_id=owner, name=name, words="we also onboard suppliers", from_session_id="s-0", created_at=AT)
    return asyncio.run(api.repo.create_idea(idea))


def test_ac_15_38_ideas_from_a_turn_are_stored_once_per_name_and_listed(api: ApiHarness):
    assert api.llm is not None
    seeded = asyncio.run(api.seed(OWNER_A, phase="find"))
    candidates = [{"name": "Supplier onboarding", "words": "we also onboard suppliers"}]
    for _ in range(2):
        api.llm.add(CallType.EXTRACT, {"candidates": candidates})
        api.llm.add(CallType.GUIDE, "Which one shall we map?")
    path = f"/api/sessions/{seeded.id}/messages"
    first = api.client.post(path, json={"text": "we also onboard suppliers"}, headers=visitor())
    second = api.client.post(path, json={"text": "supplier onboarding, as I said"}, headers=visitor())
    assert (first.json()["ideasAdded"], second.json()["ideasAdded"]) == (1, 0)
    [idea] = api.client.get("/api/ideas", headers=visitor()).json()["ideas"]
    assert set(idea) == {
        "id",
        "name",
        "words",
        "status",
        "fromSessionId",
        "startedSessionId",
        "createdAt",
        "signals",
        "hoursPerYear",
        "people",
        "dataScore",
        "score",
        "rank",
        "recommended",
    }
    assert (idea["name"], idea["status"], idea["fromSessionId"]) == ("Supplier onboarding", "open", seeded.id)
    assert api.client.get("/api/ideas", headers=visitor(KEY_B)).json() == {"ideas": []}


def test_ac_15_44_dismiss_is_204_then_404_and_never_another_visitors(api: ApiHarness):
    mine = _idea(api)
    theirs = _idea(api, OWNER_B)
    assert api.client.delete(f"/api/ideas/{theirs.id}", headers=visitor()).status_code == 404
    assert api.client.delete(f"/api/ideas/{mine.id}", headers=visitor()).status_code == 204
    assert api.client.get("/api/ideas", headers=visitor()).json() == {"ideas": []}
    again = api.client.delete(f"/api/ideas/{mine.id}", headers=visitor())
    assert again.status_code == 404 and again.json()["code"] == "not_found"


def test_ac_15_44_start_creates_a_session_and_twice_is_409(api: ApiHarness):
    idea = _idea(api)
    response = api.client.post(f"/api/ideas/{idea.id}/start", headers=visitor())
    assert response.status_code == 201
    session = response.json()
    assert session["profile"]["process"]["name"] == "Supplier onboarding"
    name_view = next(v for v in session["fieldViews"] if v["key"] == "process.name")
    assert name_view["status"] == "proposed" and name_view["quote"] == "we also onboard suppliers"
    [listed] = api.client.get("/api/ideas", headers=visitor()).json()["ideas"]
    assert (listed["status"], listed["startedSessionId"]) == ("started", session["id"])
    again = api.client.post(f"/api/ideas/{idea.id}/start", headers=visitor())
    assert again.status_code == 409 and again.json()["code"] == "idea_started"
    assert api.client.post(f"/api/ideas/{idea.id}/start", headers=visitor(KEY_B)).status_code == 404


def test_ac_15_28_create_with_from_idea_id(api: ApiHarness):
    idea = _idea(api)
    response = api.client.post("/api/sessions", json={"fromIdeaId": idea.id}, headers=visitor())
    assert response.status_code == 201
    assert response.json()["profile"]["process"]["name"] == "Supplier onboarding"
    missing = api.client.post("/api/sessions", json={"fromIdeaId": "nope"}, headers=visitor())
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"


def test_ac_15_45_delete_me_removes_every_document_of_the_caller_only(api: ApiHarness):
    api.create(KEY_A)
    api.create(KEY_A)
    _idea(api)
    theirs = api.create(KEY_B)
    _idea(api, OWNER_B)
    response = api.client.delete("/api/me", headers=visitor())
    assert response.status_code == 200 and response.json() == {"sessions": 2, "ideas": 1}
    assert api.client.get("/api/sessions", headers=visitor()).json() == {"sessions": []}
    assert api.client.get(f"/api/sessions/{theirs['id']}", headers=visitor(KEY_B)).status_code == 200
    assert len(api.client.get("/api/ideas", headers=visitor(KEY_B)).json()["ideas"]) == 1


def test_the_ideas_list_shows_the_steering_signals_and_the_recommended_flag(api: ApiHarness):
    """Spec 14 §3.15: a steered idea carries its signals, numbers, rank and the recommended flag."""
    idea = Idea.model_validate({
        "owner_id": OWNER_A, "name": "Supplier onboarding", "words": "we onboard suppliers",
        "from_session_id": "s-0", "created_at": AT, "signals": {"runs": "every week", "inputs": "a PDF form"},
        "hours_per_year": 120.0, "people": 3.0, "data_score": 0.5, "score": 0.42, "rank": 1, "recommended": True,
    })  # fmt: skip
    asyncio.run(api.repo.create_idea(idea))
    [listed] = api.client.get("/api/ideas", headers=visitor()).json()["ideas"]
    assert listed["signals"] == {"runs": "every week", "people": None, "time": None, "inputs": "a PDF form"}
    assert (listed["hoursPerYear"], listed["rank"], listed["recommended"], listed["score"]) == (120.0, 1, True, 0.42)
