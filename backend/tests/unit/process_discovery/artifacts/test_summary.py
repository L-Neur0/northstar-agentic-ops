"""Tests for the report v2 summary (spec 27 §3.5).

Why: the first thing a reader sees must tell the story in plain sentences: what was mapped, how well
AI fits, the route, a dedicated solution or not, the expert's own target, the hours and what to
prepare. Every sentence is a code template over checked facts, left out when its data is missing.
What: `build_summary` on the p05 CV-screening profile and with parts missing.
Must not: call a model. Covers AC-27.7.
"""

from __future__ import annotations

from app.models.process_discovery_schemas import RouteSummary
from app.services.process_discovery.artifacts.readiness import compute_readiness
from app.services.process_discovery.artifacts.summary import build_summary
from app.services.process_discovery.artifacts.value import compute_value
from tests.fixtures.assessment.profiles import load_cv_screening, nig_config, nig_vocabulary

from .test_questions import P05_RATINGS

CFG = nig_config()
ROUTE = RouteSummary(headline='Start with step 2 "rough first screening" (576 h a year) using NIG CV screening.')


def summary(profile=None, route: RouteSummary | None = ROUTE):
    from app.services.process_discovery.artifacts.questions import answer_questions

    profile = load_cv_screening() if profile is None else profile
    value = compute_value(profile, [], CFG.rates)
    readiness = compute_readiness(profile, [], True, value, CFG.readiness)
    q = answer_questions(profile, P05_RATINGS, [], True, value, readiness, CFG.solutions, CFG.readiness, {})
    return build_summary(profile, q, route, value, vocab=nig_vocabulary())


def test_ac_27_7_p05_sentences():
    s = summary()
    assert s[0] == (
        "We mapped Screening applications for an open role in HR (People & HR): 4 steps, about 6 a month, "
        "three working days per role each time today."
    )
    assert s[1].startswith("AI fit: strong. Steps 2 and 3 (1,152 of 1,944 hours a year)")
    assert s[2] == ROUTE.headline
    assert s[3].startswith("Leans to a dedicated solution: ") and "NIG CV screening" in s[3]
    assert s[4] == "The expert's target is 1 working day per role instead of three working days per role."
    assert s[5] == "About 1,944 hours a year go into this process today: a large process."
    assert len(s) == 6  # nothing low in readiness and no unwritten criteria: no "before starting" sentence


def test_ac_27_7_missing_parts_drop_their_sentences():
    profile = load_cv_screening()
    profile["process"]["target_metric"] = {"value": "", "unit": ""}
    s = summary(profile, route=None)
    assert not any(x.startswith("The expert's target") for x in s)
    assert ROUTE.headline not in s
    profile["process"]["substeps"][2]["decision_criteria"]["written"] = "no"
    s = summary(profile)
    assert s[-1].startswith("Before starting: Write down the decision criteria for step 3")
