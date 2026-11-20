"""Tests for the stored fields the assessment and steering amendments add (specs 14, 18, 19, 20, 26).

Why: four features (steering, the map with data, hours and readiness, the step assessment) are built
in parallel on one shared models file, so the fields they store are fixed here first. Stored models
forbid unknown keys, so every field must be declared with a default: a session saved before this
change must still load, or the next read of an existing session would fail.
What: the new fields and models of spec 18 §4.4, spec 19 §4.3, spec 26 §4.2, spec 14 §3.15 items 1
and 14 and the outcome key of spec 20 §3.1: their defaults, their camelCase storage keys, their
bounds, the parked (R5) money fields that can only be `None`, and a session dumped before the change.
Must not: test behaviour that fills these fields (that is each feature's own tests).
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.process_discovery_schemas import (
    DIAGRAM_MARKERS_BY_TYPE,
    Assessment,
    CandidateSignals,
    DataObject,
    DataStore,
    Idea,
    LastQuestion,
    Opportunity,
    OpportunityValue,
    ProcessDiagram,
    ReadinessDimension,
    RouteSummary,
    Session,
    StayHuman,
    SteeringCandidate,
    SteeringState,
    StepAssessment,
    StepRating,
    StepValue,
    ValueResult,
)
from app.models.process_discovery_schemas import (
    Path as SuggestedPath,
)

AT = "2026-11-20T09:00:00Z"
BEFORE = Path(__file__).resolve().parents[2] / "fixtures" / "sessions" / "stored_before_contract_update.json"


def opportunity(**extra) -> dict:
    return {"id": "o1", "title": "t", "type": "rpa", "impact": "high", "feasibility": "low", **extra}


# --- Stored before this change -----------------------------------------------------------------------


def test_a_session_and_idea_stored_before_this_change_still_load():
    """Spec 12 §3.11 rule (fields may be added, never break a stored document): defaults fill the new fields."""
    stored = json.loads(BEFORE.read_text())
    session = Session.model_validate(stored["session"])
    assert session.steering == SteeringState()
    assessment = session.assessment
    assert assessment is not None and assessment.step_assessment is None
    assert assessment.opportunities[0].evidence_key == "" and assessment.opportunities[0].blocked_by == []
    assert assessment.diagram is not None and assessment.diagram.data_objects == []
    assert assessment.value is not None and assessment.value.steps == []
    idea = Idea.model_validate(stored["idea"])
    assert idea.signals == CandidateSignals() and idea.recommended is False and idea.rank is None
    again = Session.model_validate(session.model_dump(by_alias=True, mode="json"))
    assert again == session


# --- Spec 18 §4.4 -------------------------------------------------------------------------------------


def test_opportunity_and_stay_human_carry_where_the_quote_was_found():
    """Spec 18 §4.4 (AC-18.13 sets `blocked_by == []`): evidence key and source, blocked_by."""
    opp = Opportunity.model_validate(
        opportunity(evidenceKey="process.substeps[1].pain_points", evidenceSource="document", blockedBy=["data"])
    )
    assert (opp.evidence_key, opp.evidence_source, opp.blocked_by) == (
        "process.substeps[1].pain_points",
        "document",
        ["data"],
    )
    assert Opportunity.model_validate(opportunity()).blocked_by == []
    with pytest.raises(ValidationError):
        Opportunity.model_validate(opportunity(evidenceSource="model"))
    stay = StayHuman.model_validate({"substeps": [2], "evidenceKey": "process.business_pain"})
    assert stay.model_dump(by_alias=True)["evidenceKey"] == "process.business_pain"


def test_the_diagram_holds_data_objects_and_stores():
    """Spec 18 §4.4: data objects per step (input or output) and data stores used by steps."""
    diagram = ProcessDiagram.model_validate(
        {
            "dataObjects": [{"id": "d1", "stepIndex": 1, "direction": "input", "label": "site spreadsheets"}],
            "dataStores": [{"id": "ds1", "label": "finance system", "steps": [1, 3]}],
        }
    )
    assert diagram.data_objects == [DataObject(id="d1", step_index=1, direction="input", label="site spreadsheets")]
    assert diagram.data_stores == [DataStore(id="ds1", label="finance system", steps=[1, 3])]
    assert ProcessDiagram().data_objects == [] and ProcessDiagram().data_stores == []
    with pytest.raises(ValidationError):
        DataObject.model_validate({"id": "d1", "stepIndex": 1, "direction": "sideways", "label": "x"})


def test_markers_by_type_match_the_table():
    """Spec 18 §3.7 item 3: legal markers per node type; the first one is the default."""
    assert DIAGRAM_MARKERS_BY_TYPE == {
        "start": ("none", "message", "timer", "conditional", "signal"),
        "task": ("none", "user", "manual", "service", "send", "receive", "script", "business_rule"),
        "gateway": ("exclusive", "parallel", "inclusive", "event_based"),
        "end": ("none", "message", "terminate", "error"),
    }


# --- Spec 19 §4.3 -------------------------------------------------------------------------------------


def test_value_result_holds_hours_per_step_and_per_opportunity():
    """Spec 19 §4.3 (AC-19.6 shape): hours fields; numbers None when not computable."""
    value = ValueResult.model_validate(
        {
            "currency": "EUR",
            "runsPerYear": 12,
            "steps": [{"step": 1, "name": "Collect", "durationHours": 6, "runsPerYear": 12, "hoursPerYear": 72}],
            "opportunities": [{"id": "o1", "stepHours": 168}],
            "problems": [],
            "formulas": ["12 runs × 6 h = 72 h"],
            "assumptions": [],
        }
    )
    assert value.steps[0] == StepValue(step=1, name="Collect", duration_hours=6, runs_per_year=12, hours_per_year=72)
    assert value.opportunities[0] == OpportunityValue(id="o1", step_hours=168)
    assert value.steps[0].problem is None and value.opportunities[0].step_hours == 168
    assert ValueResult().steps == [] and ValueResult().runs_per_year is None


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (ValueResult, {"costToday": 30780}),
        (ValueResult, {"hoursFreed": 147.36}),
        (ValueResult, {"valueConservative": 1.0}),
        (ValueResult, {"valueExpected": 1.0}),
        (StepValue, {"step": 1, "rate": 90}),
        (StepValue, {"step": 1, "share": 0.4}),
        (StepValue, {"step": 1, "hoursFreed": 1}),
        (StepValue, {"step": 1, "valueConservative": 1}),
        (StepValue, {"step": 1, "valueExpected": 1}),
        (OpportunityValue, {"id": "o1", "hoursFreed": 1}),
        (OpportunityValue, {"id": "o1", "valueConservative": 1}),
        (OpportunityValue, {"id": "o1", "valueExpected": 1}),
    ],
)
def test_parked_money_fields_can_only_be_none(model, data):
    """AC-19.39: while R5 is parked every cost, share and value field is None; a number cannot be stored."""
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_readiness_dimension_and_path_gain_their_fields():
    """Spec 19 §4.3 (AC-19.35 `prepare_items`)."""
    dim = ReadinessDimension.model_validate({"key": "data", "level": "low", "label": "Data", "steps": [1, 4]})
    assert (dim.label, dim.steps) == ("Data", [1, 4])
    assert ReadinessDimension(key="data", level="high").steps == []
    path = SuggestedPath.model_validate({"prepareItems": ["standard"]})
    assert path.prepare_items == ["standard"] and SuggestedPath().prepare_items == []


# --- Spec 26 §4.2 and spec 20 §3.1 ---------------------------------------------------------------------


def test_step_assessment_models_store_in_camel_case():
    """Spec 26 §4.2: ratings, the route summary and the step assessment container."""
    rating = StepRating(
        step=1,
        name="Collect",
        fit="automate",
        reason="Same layout every month",
        evidence="we copy every file by hand",
        evidence_key="process.substeps[1].pain_points",
        evidence_source="expert",
        route_id="low-code-flow",
        route_reason="Fixed rules",
    )
    route = RouteSummary(headline="Start with step 1.", start_with=[1], prepare=["A written rule"])
    stored = StepAssessment(steps=[rating], route=route, inputs_hash="a:b", placeholder_catalogue=False)
    dumped = stored.model_dump(by_alias=True, mode="json")
    assert dumped["steps"][0]["routeId"] == "low-code-flow" and dumped["steps"][0]["evidenceKey"]
    assert dumped["route"]["startWith"] == [1] and dumped["route"]["stayWithPeople"] == []
    assert dumped["inputsHash"] == "a:b" and dumped["placeholderCatalogue"] is False
    assert StepAssessment.model_validate(dumped) == stored
    assert StepRating(step=2, name="Check").fit is None


@pytest.mark.parametrize("bad", [{"fit": "maybe"}, {"evidenceSource": "model"}, {"surprise": 1}])
def test_a_bad_step_rating_is_refused(bad):
    """Spec 26 §4.2: fit and evidence source are closed sets; stored models forbid unknown keys."""
    with pytest.raises(ValidationError):
        StepRating.model_validate({"step": 1, "name": "Collect", **bad})


def test_assessment_gains_the_step_assessment_and_the_steps_outcome():
    """Spec 26 §4.2 and spec 20 §3.1: outcomes keys are opportunities, diagram, labels, steps."""
    assessment = Assessment.model_validate(
        {"stepAssessment": {"steps": []}, "outcomes": {"steps": "generated", "diagram": "fallback"}}
    )
    assert assessment.step_assessment == StepAssessment()
    assert assessment.outcomes["steps"] == "generated"
    with pytest.raises(ValidationError):
        Assessment.model_validate({"outcomes": {"route": "generated"}})


# --- Spec 14 §3.15 ----------------------------------------------------------------------------------


def test_a_new_session_has_steering_off():
    """Spec 14 §3.15 item 1: the steering state starts `off` with nothing asked."""
    steering = Session(owner_id="h", created_at=AT, updated_at=AT).steering
    assert steering.status == "off" and steering.candidates == []
    assert (steering.questions, steering.recommend_asks, steering.recommended_id, steering.declined) == (
        0,
        0,
        None,
        False,
    )


def test_steering_state_stores_candidates_with_signals_and_scores():
    """Spec 14 §3.15 item 1 (Example 1 row 1): the expert's words and the numbers code read from them."""
    state = SteeringState.model_validate(
        {
            "status": "ranked",
            "candidates": [
                {
                    "id": "c1",
                    "name": "the monthly cost review",
                    "words": "the monthly cost review",
                    "signals": {
                        "runs": "every month",
                        "time": "about 3 days",
                        "people": "6 of us",
                        "inputs": "site spreadsheets by e-mail",
                    },
                    "runsPerYear": 12,
                    "hoursPerYear": 288,
                    "people": 6,
                    "dataScore": 1.0,
                    "score": 0.788,
                    "rank": 1,
                }
            ],
            "questions": 3,
            "recommendAsks": 1,
            "recommendedId": "c1",
        }
    )
    candidate = state.candidates[0]
    assert candidate.signals.time == "about 3 days" and candidate.hours_per_year == 288
    assert state.model_dump(by_alias=True, mode="json")["candidates"][0]["dataScore"] == 1.0
    assert SteeringCandidate(id="c4", name="booking travel").signals == CandidateSignals()


@pytest.mark.parametrize(
    "bad",
    [
        {"status": "done"},
        {"candidates": [{"id": f"c{i}", "name": "x"} for i in range(1, 7)]},
        {"candidates": [{"id": "c9", "name": "x"}]},
        {"candidates": [{"id": "c1", "name": "x", "score": 1.5}]},
        {"candidates": [{"id": "c1", "name": "x", "dataScore": -0.1}]},
        {"candidates": [{"id": "c1", "name": "x", "rank": 0}]},
        {"questions": -1},
    ],
    ids=["status", "six-candidates", "bad-id", "score-above-1", "data-below-0", "rank-0", "negative-count"],
)
def test_a_bad_steering_state_is_refused(bad):
    """Spec 14 §3.15 item 1: four statuses, at most 5 candidates `c1…c5`, scores in [0, 1], ranks from 1."""
    with pytest.raises(ValidationError):
        SteeringState.model_validate(bad)


def test_last_question_can_arm_a_recommendation():
    """Spec 14 §3.15 item 7: `confirm` gains `recommendation`."""
    assert LastQuestion(focus=["process.name"], confirm="recommendation").confirm == "recommendation"


def test_an_idea_carries_the_steering_signals():
    """Spec 14 §3.15 item 14: signals, hours a year, people, data score, score, rank, recommended."""
    idea = Idea.model_validate(
        {
            "ownerId": "h",
            "name": "booking travel",
            "fromSessionId": "s1",
            "createdAt": AT,
            "signals": {"runs": "twice a month", "people": "just me"},
            "hoursPerYear": 24,
            "people": 1,
            "dataScore": 1.0,
            "score": 0.324,
            "rank": 2,
            "recommended": False,
        }
    )
    assert idea.signals.runs == "twice a month" and idea.signals.time is None
    assert (idea.hours_per_year, idea.people, idea.data_score, idea.score, idea.rank) == (24, 1, 1.0, 0.324, 2)
    assert idea.model_dump(by_alias=True)["hoursPerYear"] == 24
