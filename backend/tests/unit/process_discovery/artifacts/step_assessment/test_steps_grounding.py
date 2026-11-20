"""Tests for the grounding of ASSESS_STEPS replies (spec 26 §3.5).

Why: nothing the model writes is trusted. A step that does not exist, a quote from another step, a
route that is not one of the company's tools or does not serve the step's fit must each be caught
by code, and a bad entry must never cost the others.
What: `ground_step_ratings` on the shared EU fixture with the §3.2 reply, then one test per rule
A1–A10 with adversarial entries; the real NIG catalogue for the reuse-before-build ids.
Must not: call a model.
Covers AC-26.4 to AC-26.10.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.services.process_discovery.artifacts.step_assessment.grounding import ground_step_ratings
from app.services.process_discovery.artifacts.step_assessment.schemas import AssessStepsOut
from tests.fixtures.assessment.profiles import load_profile, nig_config
from tests.fixtures.assessment_19.cases import STEPS_REPLY, example_catalogue

CAT = example_catalogue()


def _reply() -> dict[str, Any]:
    return copy.deepcopy(STEPS_REPLY)


def _ground(reply: Any, catalogue=CAT):
    return ground_step_ratings(reply, load_profile("eu"), catalogue)


def _entry(step: Any, **over: Any) -> dict[str, Any]:
    base = {"step": step, "fit": "automate", "reason": "A reason.", "evidence": "the threshold check is done by eye",
            "route": "", "route_reason": ""}  # fmt: skip
    return {**base, **over}


def test_ac_26_4_worked_example() -> None:
    """AC-26.4: 5 ratings with the §3.2 fits, routes and evidence keys; nothing dropped."""
    ratings, dropped = _ground(_reply())
    assert [(r.step, r.fit, r.route_id) for r in ratings] == [
        (1, "assist", "fix-first"),
        (2, "automate", "custom-ai-app"),
        (3, "automate", "low-code-flow"),
        (4, "automate", "low-code-flow"),
        (5, "assist", "office-assistant"),
    ]
    assert [r.evidence_key for r in ratings] == [f"process.substeps[{k}].pain_points" for k in range(1, 6)]
    assert all(r.evidence_source == "expert" for r in ratings)
    assert set(dropped.values()) == {0}


def test_ac_26_4_accepts_the_typed_reply() -> None:
    ratings, _ = _ground(AssessStepsOut.model_validate(_reply()))
    assert ratings[1].route_id == "custom-ai-app"


@pytest.mark.parametrize("bad_step", [0, 7, True, "2"])
def test_ac_26_5_bad_step_dropped(bad_step: Any) -> None:
    """AC-26.5: step 0, 7, a bool or a string → dropped (`step`)."""
    reply = _reply()
    reply["steps"].append(_entry(bad_step))
    ratings, dropped = _ground(reply)
    assert dropped["step"] == 1 and len(ratings) == 5


def test_ac_26_5_first_entry_per_step_wins() -> None:
    reply = _reply()
    reply["steps"].append(_entry(3, fit="human", route="stays-with-people"))
    ratings, dropped = _ground(reply)
    assert ratings[2].fit == "automate" and dropped["step"] == 1


def test_ac_26_6_quote_checks() -> None:
    """AC-26.6: invented quote or a quote from another step → dropped (`quote`); a P09 quote is accepted."""
    reply = _reply()
    reply["steps"][0]["evidence"] = "the system crashes every day"
    reply["steps"][2]["evidence"] = "some site managers answer only after three reminders"  # step 4's words
    reply["steps"][3]["evidence"] = "Every site sends its own spreadsheet"  # P09
    ratings, dropped = _ground(reply)
    assert dropped["quote"] == 2
    assert ratings[0].fit is None and ratings[2].fit is None
    assert ratings[3].evidence_key == "process.business_pain"


def test_ac_26_6_step_value_wins_over_process_value() -> None:
    """A quote in both the step and P09 hits the step (`restrict_to_step_or_process`)."""
    ratings, _ = _ground(_reply())
    assert ratings[1].evidence_key == "process.substeps[2].pain_points"


def test_ac_26_7_unknown_route() -> None:
    """AC-26.7: an unknown id → route None, fit and reason kept, counted; "" → None, not counted."""
    reply = _reply()
    reply["steps"][2]["route"] = "acme-copilot"
    reply["steps"][3]["route"] = ""
    ratings, dropped = _ground(reply)
    assert (ratings[2].fit, ratings[2].route_id, ratings[2].route_reason) == ("automate", None, "")
    assert ratings[2].reason
    assert ratings[3].route_id is None
    assert dropped["route"] == 1


def test_ac_26_8_route_must_serve_the_fit() -> None:
    """AC-26.8: `stays-with-people` on automate, `office-assistant` on human → route None, counted."""
    reply = _reply()
    reply["steps"][1]["route"] = "stays-with-people"
    reply["steps"][4]["fit"] = "human"
    ratings, dropped = _ground(reply)
    assert ratings[1].route_id is None and ratings[4].route_id is None
    assert ratings[4].fit == "human"
    assert dropped["route"] == 2


def test_ac_26_9_invalid_and_caps() -> None:
    """AC-26.9: unknown fit or empty reason → dropped (`invalid`); reasons capped with "…"; 50 raw entries."""
    reply = _reply()
    reply["steps"][0]["fit"] = "maybe"
    reply["steps"][1]["reason"] = "   "
    reply["steps"][2]["reason"] = "x" * 700
    reply["steps"][2]["route_reason"] = "y" * 500
    ratings, dropped = _ground(reply)
    assert dropped["invalid"] == 2
    assert len(ratings[2].reason) == 600 and ratings[2].reason.endswith("…")
    assert len(ratings[2].route_reason) == 400 and ratings[2].route_reason.endswith("…")
    many = {
        "steps": [_entry(9)] * 49
        + [_entry(3)]
        + [_entry(4, evidence="some site managers answer only after three reminders")] * 3
    }
    ratings, dropped = _ground(many)
    assert dropped["cap"] == 3 and dropped["step"] == 49
    assert ratings[2].fit == "automate" and ratings[3].fit is None


def test_ac_26_10_one_rating_per_step_with_real_names() -> None:
    """AC-26.10: skipped steps are `fit = None`; names are the profile's, never the model's."""
    reply = {"steps": [_entry(3)]}
    ratings, _ = _ground(reply)
    assert [r.step for r in ratings] == [1, 2, 3, 4, 5]
    assert [r.fit for r in ratings] == [None, None, "automate", None, None]
    assert ratings[2].name == "Analyse variances"
    assert ratings[0].name == "Collect site spreadsheets"


def test_nig_catalogue_ids_are_accepted() -> None:
    """The real NIG catalogue: an existing internal tool id with the right fit is kept."""
    reply = {"steps": [_entry(4, evidence="some site managers answer only after three reminders",
                              route="ticket-routing")]}  # fmt: skip
    ratings, dropped = _ground(reply, nig_config().solutions)
    assert ratings[3].route_id == "ticket-routing" and dropped["route"] == 0
