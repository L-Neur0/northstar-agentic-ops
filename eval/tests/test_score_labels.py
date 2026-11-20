"""Labels by code: cluster, scope, steering, fit and route (spec 24 §3.9; AC-24.19).

Why: these labels are exact, so code checks them against `expected`; steering is checked from the
stored session. What: hand-built `PersonaRun` values for the tiny persona and p03.
Must not: call a model.
"""

from __future__ import annotations

from eval.evalkit.persona import EVAL_DIR, load_personas
from eval.evalkit.play import PersonaRun
from eval.evalkit.score_labels import score_labels

from .conftest import make_persona


def _run(**changes) -> PersonaRun:
    run = PersonaRun("x", status="finished")
    run.session = {
        "profile": {"process": {"cluster": {"code": "FIN"}, "name": "Monthly cost review"}},
        "scope": {"verdict": "process"},
    }
    run.stored = {"steering": {"status": "off"}}
    run.report = {"steps": {"rows": [{"number": 1, "name": "Step 1", "fit": "assist", "routeId": "fix-first"},
                                     {"number": 2, "name": "Step 2", "fit": "human", "routeId": "stays-with-people"}]}}  # fmt: skip
    for key, value in changes.items():
        setattr(run, key, value)
    return run


def test_ac_24_19_cluster_scope_fit_and_route():
    labels = score_labels(make_persona(), _run())
    assert (labels.cluster, labels.scope, labels.steering) == (True, True, True)
    assert (labels.fit_hits, labels.route_hits, labels.routed_steps) == (1, 1, 1)
    wrong = _run(session={"profile": {"process": {"cluster": {"code": "HR"}}}, "scope": {"verdict": "task"}})
    labels = score_labels(make_persona(), wrong)
    assert (labels.cluster, labels.scope) == (False, False)


def test_ac_24_19_steering_null_expects_off_and_url_mode_is_n_a():
    assert score_labels(make_persona(), _run(stored={"steering": {"status": "ranked"}})).steering is False
    assert score_labels(make_persona(), _run(stored=None)).steering is None


def test_ac_24_19_p03_recommendation_chosen_and_ideas(company):
    p03 = next(p for p in load_personas(EVAL_DIR / "personas", quick=False, company=company) if p.id.startswith("p03"))
    steering = {
        "status": "chosen",
        "recommendedId": "c2",
        "candidates": [{"id": "c1", "name": "filing my timesheet"}, {"id": "c2", "name": "Onboarding new site staff"}],
    }
    run = _run(stored={"steering": steering})
    run.session = {
        "profile": {"process": {"cluster": {"code": "HR"}, "name": "Onboarding new site staff"}},
        "scope": {"verdict": "process"},
    }
    run.ideas = [{"name": "Filing my timesheet"}, {"name": "Safety training records"}, {"name": "Ordering PPE"}]
    assert score_labels(p03, run).steering is True
    run.ideas = run.ideas[:2]
    assert score_labels(p03, run).steering is False


def test_an_unfinished_session_has_no_scope_fit_or_route_to_score():
    labels = score_labels(make_persona(), _run(status="never_finished", report=None))
    assert labels.scope is None and labels.routed_steps == 0
