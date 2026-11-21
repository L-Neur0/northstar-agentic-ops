"""Tests for the stored and wire models of the session and idea documents (spec 12 §3.11).

Why: the session document is what Cosmos keeps; a key the models do not declare must fail loudly in
tests instead of vanishing on the next save, and a bad step count must never make a session
unloadable. Storage keys are camelCase while the profile keeps registry keys.
What: the step-count before-validator, the step limit, `extra="forbid"`, alias dumping, the
defaults of a new session and idea, and the shapes `scope.py` returns. Implements AC-12.41 to
AC-12.43.
"""

import pytest
from pydantic import ValidationError

from app.models.process_discovery_schemas import (
    Assessment,
    FinishBlock,
    OpportunityType,
    Phase,
    Placement,
    Profile,
    ScopeVerdict,
    Session,
    SessionStatus,
    Step,
    TaxonomyOut,
)
from app.services.process_discovery.domain import scope
from app.services.process_discovery.domain.field_spec import PROCESS_POINTS

AT = "2026-11-20T09:00:00Z"


def new_session(**extra) -> Session:
    return Session(owner_id="hash", created_at=AT, updated_at=AT, **extra)


# --- AC-12.41 ----------------------------------------------------------------------------------


@pytest.mark.parametrize("count", [13, 1, 0, 7])
def test_out_of_range_step_count_moves_to_rejected(count):
    """AC-12.41: loads without raising; storage never holds an out-of-range count."""
    process = Profile.model_validate({"process": {"substep_count": count}}).process
    assert process.substep_count is None
    assert process.substep_count_rejected == count


def test_in_range_count_stays():
    """AC-12.41 (the in-range side)."""
    process = Profile.model_validate({"process": {"substep_count": 4, "substep_count_rejected": None}}).process
    assert (process.substep_count, process.substep_count_rejected) == (4, None)


def test_seven_steps_raise():
    """AC-12.41: more than 6 steps is a writer bug."""
    with pytest.raises(ValidationError):
        Profile.model_validate({"process": {"substeps": [{} for _ in range(7)]}})
    assert len(Profile.model_validate({"process": {"substeps": [{} for _ in range(6)]}}).process.substeps) == 6


@pytest.mark.parametrize(
    "build",
    [
        lambda: Profile.model_validate({"department": "x", "surprise": 1}),
        lambda: Step.model_validate({"name": "x", "surprise": 1}),
        lambda: Profile.model_validate({"process": {"surprise": 1}}),
        lambda: Session.model_validate({"ownerId": "h", "createdAt": AT, "updatedAt": AT, "surprise": 1}),
    ],
    ids=["profile", "step", "process", "session"],
)
def test_undeclared_keys_raise(build):
    """AC-12.41."""
    with pytest.raises(ValidationError):
        build()


def test_rows_are_none_rows_or_real_rows():
    """§3.11 rule 1: a none row stays a none row; an empty row is not a row."""
    step = Step.model_validate({"roles": [{"none": True}, {"role": "AP clerk"}]})
    assert step.model_dump(by_alias=True)["roles"] == [{"none": True}, {"role": "AP clerk", "contribution": ""}]
    for bad in ([{}], [{"role": ""}], [{"none": False}], [{"none": True, "role": "x"}]):
        with pytest.raises(ValidationError):
            Step.model_validate({"roles": bad})


def test_loops_back_to_is_a_positive_step_number():
    """§3.11: `loops_back_to` is 1-based."""
    with pytest.raises(ValidationError):
        Step.model_validate({"exceptions": [{"description": "x", "loops_back_to": 0}]})


# --- AC-12.42 ----------------------------------------------------------------------------------


def test_session_dumps_camel_case_outside_the_profile():
    """AC-12.42."""
    session = new_session(etag="abc", raw_substeps=[Step(name="Collect")])
    session.profile.process.end_result = "Cost report"
    dumped = session.model_dump(by_alias=True, mode="json")
    assert dumped["ownerId"] == "hash"
    assert dumped["rawSubsteps"][0]["name"] == "Collect"
    assert "pain_points" in dumped["rawSubsteps"][0]
    assert dumped["score"]["filledPoints"] == 0
    assert dumped["counters"]["fieldAsks"] == {}
    assert "etag" not in dumped
    assert dumped["profile"]["process"]["end_result"] == "Cost report"
    assert "__meta" in dumped["profile"]


def test_snake_and_camel_input_both_validate():
    """AC-12.42."""
    camel = Session.model_validate({"ownerId": "h", "createdAt": AT, "updatedAt": AT, "rawSubsteps": []})
    snake = Session.model_validate({"owner_id": "h", "created_at": AT, "updated_at": AT, "raw_substeps": []})
    assert camel.owner_id == snake.owner_id == "h"


def test_a_session_round_trips():
    """§3.11: a dump validates back to an equal model."""
    session = new_session()
    again = Session.model_validate(session.model_dump(by_alias=True, mode="json"))
    assert again == session


# --- AC-12.43 ----------------------------------------------------------------------------------


def test_new_session_defaults():
    """AC-12.43."""
    session = new_session()
    assert session.status is SessionStatus.ACTIVE and session.phase is Phase.CONTEXT
    assert session.type == "session"
    assert (session.score.value, session.score.filled_points, session.score.total_points) == (0, 0, PROCESS_POINTS)
    counters = session.counters
    assert counters.field_asks == {} and counters.cell_asks == {}
    assert (counters.find_turns, counters.widening_count, counters.confirm_turns) == (0, 0, 0)
    assert session.assessment is None and session.report is None and session.briefs == []
    assert session.profile == Profile()
    assert session.id and new_session().id != session.id
    assert session.etag is None and session.ttl is None and session.finished_at is None


def test_new_idea_defaults():
    """AC-12.43."""
    from app.models.process_discovery_schemas import Idea

    idea = Idea(
        owner_id="h", name="Supplier onboarding", words="we onboard suppliers", from_session_id="s1", created_at=AT
    )
    assert idea.status == "open" and idea.type == "idea" and idea.started_session_id is None
    assert idea.model_dump(by_alias=True)["fromSessionId"] == "s1"


# --- Shapes shared with the domain --------------------------------------------------------------


def test_scope_and_placement_shapes_match_scope_py(nig_taxonomy):
    """§3.11: `ScopeVerdict` and `Placement` have exactly the shapes `scope.py` returns."""
    verdict = scope.build_scope_verdict({"multi_role": True})
    assert ScopeVerdict.model_validate(verdict).model_dump() == {**verdict, "refreshed": False}
    refreshed = scope.refresh_scope_from_map(verdict, roles=["a", "b"], systems=["x", "y"])  # spec 12 §3.13
    assert ScopeVerdict.model_validate(refreshed).model_dump() == refreshed
    for placement in (
        scope.build_placement({"code": "FIN", "confidence": 0.9}, nig_taxonomy),
        scope.keyword_placement("FIN"),
        scope.unknown_placement(),
    ):
        assert Placement.model_validate(placement).model_dump() == placement


def test_enums():
    """§3.11: enum values used by other specs and by `rates.yaml`."""
    assert [p.value for p in Phase] == [
        "context",
        "find",
        "boundaries",
        "measure",
        "step_count",
        "steps",
        "confirm",
        "review",
        "finished",
        "no_candidate",
    ]
    assert [b.value for b in FinishBlock] == [
        "below_gate",
        "substeps_incomplete",
        "roles_not_confirmed",
        "tools_not_confirmed",
    ]
    from app.core.config import OPPORTUNITY_TYPES

    assert tuple(t.value for t in OpportunityType) == OPPORTUNITY_TYPES


def test_assessment_defaults_and_saving_share_bounds():
    """§3.11: the containers fixed here; saving share 0–0.9."""
    assessment = Assessment()
    assert assessment.opportunities == [] and assessment.diagram is None
    from app.models.process_discovery_schemas import Opportunity

    with pytest.raises(ValidationError):
        Opportunity.model_validate(
            {"id": "o1", "title": "t", "type": "rpa", "impact": "high", "feasibility": "low", "savingShare": 0.95}
        )


def test_taxonomy_out_from_config(nig_taxonomy):
    """§3.11: the taxonomy route model."""
    out = TaxonomyOut.model_validate(
        {"clusters": [{"code": c.code, "name": c.name, "description": c.description} for c in nig_taxonomy.clusters]}
    )
    assert out.clusters[0].model_dump() == {
        "code": "FIN",
        "name": "Finance",
        "description": nig_taxonomy.clusters[0].description,
    }


@pytest.fixture(scope="module")
def nig_taxonomy():
    from pathlib import Path

    from app.core.config import load_company_config

    return load_company_config(Path(__file__).resolve().parents[4] / "config" / "nig").taxonomy
