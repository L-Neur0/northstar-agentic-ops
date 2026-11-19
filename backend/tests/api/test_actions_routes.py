"""API tests for the actions outside a turn: confirm, cluster picker, close and finish (spec 15 part 2 §3.3; AC-15.39 to AC-15.43).

Why: these buttons change the map without a model call, and each must recompute the phase and the
*Finish* state exactly as a turn would, refuse what the rules refuse, and store nothing when it
refuses; the client relies on the codes to show the right state.
What: sessions are seeded through the real profile writers (the monthly cost review), then each
route is called over HTTP and the response and the stored session are checked.
Must not: patch a route, a node or a writer.
"""

from __future__ import annotations

import pytest

from app.core.access import owner_from_key
from tests.unit.process_discovery.profile.builders import cost_review_profile

from .conftest import KEY_A, KEY_B, ApiHarness, visitor

OWNER_A = owner_from_key(KEY_A)


def _seed(api: ApiHarness, **update):
    import asyncio

    return asyncio.run(api.seed(OWNER_A, **update))


def _map(api: ApiHarness, **flags: bool):
    profile = cost_review_profile(api.service.ctx.vocab, steps=2)
    profile["process"].update(flags)
    return profile


def test_ac_15_39_confirm_roles_sets_the_flag_and_recomputes_the_phase(api: ApiHarness):
    seeded = _seed(api, phase="confirm", profile=_map(api))
    response = api.client.post(f"/api/sessions/{seeded.id}/confirm", json={"target": "roles"}, headers=visitor())
    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["process"]["roles_confirmed"] is True
    assert body["finish"]["blockedBy"] == "tools_not_confirmed" and body["phase"] == "confirm"
    response = api.client.post(f"/api/sessions/{seeded.id}/confirm", json={"target": "tools"}, headers=visitor())
    body = response.json()
    assert body["profile"]["process"]["tools_confirmed"] is True
    assert body["phase"] == "review" and body["finish"]["ready"] is True


def test_ac_15_39_an_unknown_target_is_422(api: ApiHarness):
    seeded = _seed(api)
    response = api.client.post(f"/api/sessions/{seeded.id}/confirm", json={"target": "systems"}, headers=visitor())
    assert response.status_code == 422 and response.json()["code"] == "invalid_value"


def test_confirm_substeps_on_a_closed_walk_keeps_it_closed(api: ApiHarness):
    seeded = _seed(api, phase="confirm", profile=_map(api))
    response = api.client.post(f"/api/sessions/{seeded.id}/confirm", json={"target": "substeps"}, headers=visitor())
    assert response.status_code == 200
    assert response.json()["profile"]["process"]["substeps_complete"] is True


def test_ac_15_40_a_known_cluster_is_set_by_the_picker_and_moves_the_phase(api: ApiHarness):
    profile = cost_review_profile(api.service.ctx.vocab, steps=2, filled_steps=0, cluster=False)
    seeded = _seed(api, phase="find", profile=profile)
    response = api.client.put(f"/api/sessions/{seeded.id}/cluster", json={"code": "FIN"}, headers=visitor())
    assert response.status_code == 200
    body = response.json()
    cluster = body["profile"]["process"]["cluster"]
    assert (cluster["code"], cluster["decided_by"]) == ("FIN", "picker")
    assert body["phase"] != "find"
    assert body["clusterProposal"] is None


def test_ac_15_40_an_unknown_cluster_is_422_unknown_cluster(api: ApiHarness):
    seeded = _seed(api)
    response = api.client.put(f"/api/sessions/{seeded.id}/cluster", json={"code": "ZZZ"}, headers=visitor())
    assert response.status_code == 422 and response.json()["code"] == "unknown_cluster"
    too_long = api.client.put(f"/api/sessions/{seeded.id}/cluster", json={"code": "X" * 9}, headers=visitor())
    assert too_long.status_code == 422 and too_long.json()["code"] == "invalid_value"


def test_ac_15_41_close_sets_no_candidate_and_later_messages_are_closed(api: ApiHarness):
    seeded = _seed(api)
    response = api.client.post(f"/api/sessions/{seeded.id}/close", headers=visitor())
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["phase"]) == ("no_candidate", "no_candidate") and body["finishedAt"]
    again = api.client.post(f"/api/sessions/{seeded.id}/close", headers=visitor())
    assert again.status_code == 400 and again.json()["code"] == "session_closed"
    message = api.client.post(f"/api/sessions/{seeded.id}/messages", json={"text": "hi"}, headers=visitor())
    assert message.json()["code"] == "session_closed"


@pytest.mark.parametrize(
    ("flags", "reason"),
    [
        ({"substeps_complete": False, "roles_confirmed": True, "tools_confirmed": True}, "substeps_incomplete"),
        ({"roles_confirmed": False, "tools_confirmed": True}, "roles_not_confirmed"),
        ({"roles_confirmed": True, "tools_confirmed": False}, "tools_not_confirmed"),
    ],
)
def test_ac_15_42_finish_on_an_incomplete_map_is_409_with_the_first_blocker(api: ApiHarness, flags, reason):
    seeded = _seed(api, phase="review", profile=_map(api, **flags))
    before = api.client.get(f"/api/sessions/{seeded.id}", headers=visitor()).json()
    response = api.client.post(f"/api/sessions/{seeded.id}/finish", headers=visitor())
    assert response.status_code == 409
    assert response.json()["code"] == "map_incomplete" and response.json()["reason"] == reason
    assert api.client.get(f"/api/sessions/{seeded.id}", headers=visitor()).json() == before


def test_ac_15_43_finish_on_a_complete_map(api: ApiHarness):
    seeded = _seed(api, phase="review", profile=_map(api, roles_confirmed=True, tools_confirmed=True))
    response = api.client.post(f"/api/sessions/{seeded.id}/finish", headers=visitor())
    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["phase"], body["reportStatus"]) == ("finished", "finished", "mapped")
    assert body["finishedAt"]
    stored = api.repo._documents[(OWNER_A, seeded.id)]  # pyright: ignore[reportPrivateUsage]
    assert '"ttl"' not in stored
    again = api.client.post(f"/api/sessions/{seeded.id}/finish", headers=visitor())
    assert again.status_code == 400 and again.json()["code"] == "session_closed"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "confirm", {"target": "roles"}),
        ("PUT", "cluster", {"code": "FIN"}),
        ("POST", "close", None),
        ("POST", "finish", None),
    ],
)
def test_actions_on_another_visitors_session_are_404(api: ApiHarness, method, path, body):
    theirs = api.create(KEY_B)
    response = api.client.request(method, f"/api/sessions/{theirs['id']}/{path}", json=body, headers=visitor(KEY_A))
    assert response.status_code == 404 and response.json()["code"] == "not_found"
