"""Report quality by code first, the judge only where code cannot decide (spec 24 §3.7; AC-24.10 to AC-24.13).

Why: the headline number must be exact where it can be and honest about what is missing. What:
step alignment, the code rows of the worked example, which rows reach the judge, the denominator
(every truth field) and the "no invention" rule, on hand-written profiles. Must not: call a model.
"""

from __future__ import annotations

import copy

from eval.evalkit.persona import EVAL_DIR, load_personas
from eval.evalkit.score_fields import align_steps, normalise, score_fields

from .conftest import FakeJudge, make_persona, profile_from_truth


def _p01(company):
    return load_personas(EVAL_DIR / "personas", quick=True, company=company)[0]


def _result(scores, key):
    return next(r for r in scores.results if r.key == key)


def test_normalise():
    assert normalise("  The Site   Managers. ") == "site manager"
    assert normalise("Excel") == "excel"


def test_ac_24_10_equal_counts_pair_by_position():
    truth = [{"name": "a"}, {"name": "b"}]
    assert align_steps(truth, [{"name": "x"}, {"name": "y"}]) == [(1, 1), (2, 2)]


def test_ac_24_10_unequal_counts_pair_by_shared_name_words():
    truth = [
        {"name": "Collect the cost data"},
        {"name": "Consolidate the workbook"},
        {"name": "Analyse variances"},
        {"name": "Send report"},
    ]
    captured = [
        {"name": "Gather data"},
        {"name": "Collect cost data"},
        {"name": "Consolidate"},
        {"name": "Variance"},
        {"name": "Lunch"},
    ]
    # step 1 shares two words with captured 2 (one with captured 1); "variances" and "variance" normalise alike
    assert align_steps(truth, captured) == [(1, 2), (2, 3), (3, 4), (4, None)]


async def test_ac_24_10_an_unpaired_true_step_scores_all_eleven_cells_wrong(company):
    persona = _p01(company)
    profile = profile_from_truth(persona)
    profile["process"]["substeps"] = profile["process"]["substeps"][:4] + [
        {"name": "Something else entirely"},
        {"name": "Coffee"},
    ]
    profile["process"]["substeps"][4] = {"name": "Unrelated"}
    scores = await score_fields(persona, profile, FakeJudge(True))
    step5 = [r for r in scores.results if r.key.startswith("process.substeps[5].")]
    assert len(step5) == 11 and not any(r.correct for r in step5)


async def test_ac_24_11_code_rows_of_the_worked_example(company):
    persona = _p01(company)
    profile = profile_from_truth(persona)
    profile["process"]["volume"] = {"count": None, "period": "", "raw": "once a month"}
    profile["process"]["substeps"][3]["effort"] = {"duration": "half a day", "frequency": "monthly"}
    profile["process"]["substeps"][1]["systems"] = ["excel", "the ledger"]
    profile["process"]["substeps"][0]["systems"] = ["Ledger system", "E-mail", "Teams", "SharePoint"]
    judge = FakeJudge(True)
    scores = await score_fields(persona, profile, judge)
    assert _result(scores, "process.volume").correct and _result(scores, "process.volume").method == "code"
    effort = _result(scores, "process.substeps[4].effort")
    assert (effort.correct, effort.method) == (False, "code")
    assert _result(scores, "process.substeps[2].systems").correct
    two_extra = _result(scores, "process.substeps[1].systems")
    assert not two_extra.correct and "2 extra" in two_extra.reason


async def test_ac_24_12_the_judge_sees_only_judge_rows_and_code_non_matches(company):
    persona = _p01(company)
    profile = profile_from_truth(persona)
    judge = FakeJudge(True)
    scores = await score_fields(persona, profile, judge)
    assert judge.pairs == []  # every value equal: code decides all
    assert scores.correct == scores.total == 71

    profile["process"]["trigger"] = "When the books close"
    profile["process"]["region"] = "Europe"
    profile["region"] = "Europe"
    profile["process"]["substeps"][0]["systems"] = ["SAP"]
    profile["process"]["end_result"] = ""
    judge = FakeJudge(True)
    scores = await score_fields(persona, profile, judge)
    assert judge.pairs == [("The month-end close is finished in the ledger system", "When the books close")]
    assert not _result(scores, "region").correct  # code row: never judged
    assert not _result(scores, "process.substeps[1].systems").correct  # systems: code only
    missing = _result(scores, "process.end_result")
    assert (missing.correct, missing.method) == (False, "missing")


async def test_ac_24_12_a_role_that_code_cannot_match_goes_to_the_judge_one_item_at_a_time(company):
    persona = _p01(company)
    profile = profile_from_truth(persona)
    profile["process"]["substeps"][0]["roles"] = [
        {"role": "Controlling analyst", "contribution": ""},
        {"role": "site managers", "contribution": ""},
    ]
    judge = FakeJudge(True)
    scores = await score_fields(persona, profile, judge)
    assert _result(scores, "process.substeps[1].roles").correct
    assert judge.pairs == [("Cost controller", "Controlling analyst")]


async def test_ac_24_13_quality_counts_every_truth_field(company):
    persona = _p01(company)
    profile = profile_from_truth(persona)
    profile["process"]["substeps"] = profile["process"]["substeps"][:4]
    profile["process"]["substep_count"] = 4
    profile["department"] = ""
    scores = await score_fields(persona, profile, FakeJudge(True))
    assert scores.total == 71
    # 4 captured vs 5 true: pairing by name words; "Write and send the report" shares none: 11 wrong
    assert scores.correct == 71 - 11 - 1 - 1  # step 5, department, step count


async def test_ac_24_13_never_disclosed_fields_reward_honesty_and_count_inventions():
    persona = make_persona()
    persona.truth.disclose["process.volume"] = "never"
    persona.truth.disclose["steps[*].effort"] = "never"
    profile = profile_from_truth(persona)
    profile["process"]["volume"] = {"count": None, "period": "", "raw": "it depends"}
    profile["process"]["substeps"][0]["effort"] = {"duration": "", "frequency": ""}
    profile["process"]["substeps"][1]["effort"] = {"duration": "two hours", "frequency": "monthly"}
    scores = await score_fields(persona, copy.deepcopy(profile), FakeJudge(True))
    assert _result(scores, "process.volume").correct
    assert _result(scores, "process.substeps[1].effort").correct
    invented = _result(scores, "process.substeps[2].effort")
    assert not invented.correct and invented.invented
    assert scores.invented_values == 1
