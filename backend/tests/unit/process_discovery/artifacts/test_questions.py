"""Tests for the three guiding questions of report v2 (spec 27 §3.3).

Why: the product owner wants the assessment to answer "is this a good AI use case?", "a dedicated
solution or a general assistant?" and "is it worth it?", as levels with reasons, never yes or no
(product rule: no go / no-go). Code decides every level from grounded signals and facts (rules 2, 3).
What: `answer_questions` on the p05 CV-screening profile (the demo case) and on small variations.
Must not: call a model.
Covers AC-27.1, AC-27.3 to AC-27.6.
"""

from __future__ import annotations

import pytest

from app.models.process_discovery_schemas import DecisionLabel, StepLabels, StepRating
from app.services.process_discovery.artifacts.questions import (
    LEVEL_WORDS,
    answer_questions,
    step_level,
)
from app.services.process_discovery.artifacts.readiness import compute_readiness
from app.services.process_discovery.artifacts.value import compute_value
from tests.fixtures.assessment.profiles import load_cv_screening, nig_config

CFG = nig_config()
LANGUAGE = ("reads_unstructured", "compares_to_criteria", "finds_patterns", "drafts_text")


def rating(step: int, *signals: str, route: str | None = None, fit: str | None = "assist") -> StepRating:
    return StepRating(
        step=step,
        name=f"Step {step}",
        fit=fit,  # pyright: ignore[reportArgumentType]
        route_id=route,
        signals=dict.fromkeys(signals, True),
        signal_evidence={s: "x" for s in signals},
    )


P05_RATINGS = [
    rating(1, "fixed_rules", fit="automate"),
    rating(2, "reads_unstructured", "compares_to_criteria", route="cv-screening"),
    rating(3, "reads_unstructured", "compares_to_criteria", route="cv-screening"),
    rating(4),
]


def answer(profile=None, ratings=P05_RATINGS, labels=(), labels_ok=True, motivations=None):
    profile = load_cv_screening() if profile is None else profile
    value = compute_value(profile, [], CFG.rates)
    readiness = compute_readiness(profile, list(labels), labels_ok, value, CFG.readiness)
    return answer_questions(
        profile, ratings, list(labels), labels_ok, value, readiness, CFG.solutions, CFG.readiness, motivations or {}
    )


# --- AC-27.1: step levels -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("signals", "kind", "level"),
    [
        (("reads_unstructured", "compares_to_criteria"), "judgement", "strong"),
        (("reads_unstructured", "must_be_exact"), "judgement", "partial"),
        ((), "mix", "partial"),
        (("fixed_rules",), "rules", "weak"),
        ((), "rules", "weak"),
        (("fixed_rules", "drafts_text"), "mix", "strong"),
    ],
)
def test_ac_27_1_step_levels(signals, kind, level):
    row = {"decision_type": {"kind": kind, "evidence": "x"}}
    assert step_level(rating(1, *signals), row).level == level


def test_ac_27_1_not_assessed_is_not_rated():
    assert step_level(rating(1, fit=None), {}).level == "not_rated"


# --- AC-27.3: Q1 for the process --------------------------------------------------------------------


def test_ac_27_3_p05_strong_by_hours():
    q = answer()
    assert [s.level for s in q.steps] == ["weak", "strong", "strong", "partial"]
    assert q.q1.level == "strong"
    assert q.q1.reasons[0].startswith("Steps 2 and 3 (1,152 of 1,944 hours a year)")
    assert "Step 1" in " ".join(q.q1.reasons) and "script" in " ".join(q.q1.reasons)


def test_ac_27_3_partial_and_weak_and_unknown_hours():
    one_strong = [
        rating(1, "fixed_rules"),
        rating(2, "drafts_text"),
        rating(3, "fixed_rules"),
        rating(4, "fixed_rules"),
    ]
    assert answer(ratings=one_strong).q1.level == "partial"  # 576 of 1,944 hours
    assert answer(ratings=[rating(i, "fixed_rules") for i in range(1, 5)]).q1.level == "weak"
    profile = load_cv_screening()
    for row in profile["process"]["substeps"]:
        row["effort"] = {"duration": "", "frequency": ""}
    assert answer(profile).q1.level == "strong"  # 2 of 4 steps strong, by count


# --- AC-27.4: Q2 ---------------------------------------------------------------------------------------


def test_ac_27_4_p05_leans_to_a_dedicated_solution():
    q2 = answer().q2
    assert q2.level == "strong" and LEVEL_WORDS["q2"]["strong"] == "Leans to a dedicated solution"
    text = " ".join(q2.reasons)
    assert "personal data" in text
    assert "about 72 times a year" in text
    assert "NIG CV screening" in text
    assert "recruiting system" in text


def test_ac_27_4_no_facts_a_general_assistant_is_enough():
    profile = load_cv_screening()
    profile["process"]["sensitive_data"] = [{"none": True}]
    profile["process"]["volume"] = {"count": 1, "period": "month", "raw": ""}
    for row in profile["process"]["substeps"]:
        row["systems"] = ["Excel"]
        row["decision_criteria"] = {"basis": "", "set_by": "", "written": "", "varies": ""}
    ratings = [rating(1, "fixed_rules"), rating(2, "drafts_text"), rating(3, "drafts_text"), rating(4)]
    q2 = answer(profile, ratings=ratings).q2
    assert q2.level == "weak" and LEVEL_WORDS["q2"]["weak"] == "A general assistant is enough"


# --- AC-27.5: Q3 ---------------------------------------------------------------------------------------


def _with_hours(duration: str):
    profile = load_cv_screening()
    for row in profile["process"]["substeps"]:
        row["effort"] = {"duration": duration, "frequency": "each time"}
    profile["process"]["volume"] = {"count": 1, "period": "month", "raw": ""}
    return profile


@pytest.mark.parametrize(("duration", "level"), [("13 hours", "strong"), ("3 hours", "partial"), ("1 hour", "weak")])
def test_ac_27_5_q3_levels_from_hours(duration, level):
    assert answer(_with_hours(duration)).q3.level == level  # 4 steps x 12 runs: 624 h, 144 h, 48 h


def test_ac_27_5_not_rated_names_the_field():
    profile = load_cv_screening()
    profile["process"]["substeps"][0]["effort"] = {"duration": "it depends", "frequency": "each time"}
    q3 = answer(profile).q3
    assert q3.level == "not_rated" and "Effort" in " ".join(q3.reasons)


def test_ac_27_5_prepare_and_risks():
    profile = load_cv_screening()
    profile["process"]["substeps"][2]["decision_criteria"]["written"] = "no"
    labels = [StepLabels(step=3, decisions=[DecisionLabel(text="pick", kind="pure_judgement", evidence="x")])]
    q = answer(profile, labels=labels)
    assert any("step 3" in p.lower() and "write down" in p.lower() for p in q.prepare)
    risks = " ".join(q.risks)
    assert "personal data" in risks
    assert "they differ for every hiring manager" in risks
    assert "pure judgement" in risks.lower()


# --- AC-27.6: never a verdict; motivations grounded or the code reason --------------------------------


def test_ac_27_6_no_verdict_words_and_checked_motivations():
    good = {"q1": ("It reads CVs.", "rough first screening"), "q2": ("Bad.", "words nobody said")}
    q = answer(motivations=good)
    words = {w for answer_ in (q.q1, q.q2, q.q3) for w in (answer_.level, *answer_.reasons)}
    assert not words & {"yes", "no", "go", "no-go", "Yes", "No"}
    for key in ("q1", "q2", "q3"):
        assert all(
            word not in LEVEL_WORDS[key][level].lower().split() for level in LEVEL_WORDS[key] for word in ("yes", "no")
        )
    assert q.q1.motivation == "It reads CVs." and q.q1.evidence == "rough first screening"
    assert q.q2.motivation == "" and q.q2.evidence == ""  # quote not in the profile: code reason only
