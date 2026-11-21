"""Report quality by code first, the judge only where code cannot decide (spec 24 §3.7; AC-24.10 to AC-24.13, AC-24.44 to AC-24.47).

Why: the headline number must be exact where it can be and honest about what is missing. What:
step matching by content (renamed, reordered, merged and missing steps), the code rows of the worked example, which rows reach the judge, the denominator
(every truth field) and the "no invention" rule, on hand-written profiles. Must not: call a model.
"""

from __future__ import annotations

import copy

from eval.evalkit.persona import EVAL_DIR, PROCESS_KEYS, STEP_LEAVES, load_personas
from eval.evalkit.score_fields import align_steps, normalise, score_fields

from .conftest import FakeJudge, make_persona, profile_from_truth

P01_FIELDS = len(PROCESS_KEYS) + 5 * len(STEP_LEAVES)  # registry-derived: 16 + 5 × 12 = 76


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


def _step(name, activities=(), systems=(), inputs=(), outputs=()):
    return {"name": name, "activities": list(activities), "systems": list(systems),
            "data": {"inputs": list(inputs), "outputs": list(outputs)}}  # fmt: skip


TRIAGE = [
    _step("Read the new ticket", ["open the ticket", "read the description", "check attachments"],
          ["Ticketing system"], ["new ticket"], ["understood request"]),
    _step("Set category and priority", ["pick the category", "set the priority from the priority matrix"],
          ["Ticketing system", "Priority matrix"], ["understood request"], ["categorised ticket"]),
    _step("Assign to a resolver group", ["look up the resolver group", "assign the ticket"],
          ["Ticketing system", "Resolver group list"], ["categorised ticket"], ["assigned ticket"]),
    _step("Follow up unassigned tickets", ["check the unassigned queue", "escalate old tickets"],
          ["Ticketing system", "Team chat"], ["unassigned queue"], ["escalated tickets"]),
]  # fmt: skip


def test_ac_24_44_steps_are_matched_by_content_not_by_name():
    captured = [
        _step("First pass", ["open the ticket", "read the description", "check attachments", "call the user back"],
              ["ticketing system"], ["description", "attachments"], ["an understood request"]),
        _step("Check the unassigned ones", ["check the unassigned queue", "chase anything sitting too long"],
              ["ticketing system", "team chat"], ["unassigned queue"], ["escalated tickets"]),
    ]  # fmt: skip
    # no name word is shared with step 1; steps 2 and 3 are covered by no captured step: missing
    assert align_steps(TRIAGE, captured) == [(1, 1), (2, None), (3, None), (4, 2)]


def test_ac_24_44_renamed_and_reordered_steps_follow_their_content():
    captured = [TRIAGE[1] | {"name": "Triage"}, TRIAGE[0] | {"name": "Intake"}, TRIAGE[3], TRIAGE[2]]
    assert align_steps(TRIAGE, captured) == [(1, 2), (2, 1), (3, 4), (4, 3)]


def test_ac_24_45_a_step_that_merges_two_true_steps_covers_both():
    merged = _step("Categorise and assign",
                   ["pick the category", "set the priority from the matrix", "look up the resolver group", "assign it"],
                   ["Ticketing system", "Priority matrix", "Resolver group list"],
                   ["understood request"], ["assigned ticket"])  # fmt: skip
    captured = [TRIAGE[0], merged, TRIAGE[3]]
    assert align_steps(TRIAGE, captured) == [(1, 1), (2, 2), (3, 2), (4, 3)]


async def test_ac_24_45_a_merged_step_is_scored_against_each_covered_true_step(company):
    persona = _p01(company)
    profile = profile_from_truth(persona)
    steps = profile["process"]["substeps"]
    merged = copy.deepcopy(steps[1])
    merged["activities"] = steps[1]["activities"] + steps[2]["activities"]
    merged["systems"] = ["Excel", "Ledger system", "Budget file", "PowerPoint"]
    profile["process"]["substeps"] = [steps[0], merged, steps[3], steps[4]]
    scores = await score_fields(persona, profile, FakeJudge(True))
    step3 = {r.key.rsplit(".", 1)[1]: r for r in scores.results if r.key.startswith("process.substeps[3].")}
    step2 = {r.key.rsplit(".", 1)[1]: r for r in scores.results if r.key.startswith("process.substeps[2].")}
    assert step2["systems"].correct and step3["systems"].correct  # the merged step's extras are not held against them
    assert step3["activities"].captured.startswith("copy the data")  # scored against the merged step's cells


async def test_ac_24_10_an_unpaired_true_step_scores_every_scored_cell_wrong(company):
    persona = _p01(company)
    profile = profile_from_truth(persona)
    profile["process"]["substeps"] = profile["process"]["substeps"][:4] + [
        {"name": "Something else entirely"},
        {"name": "Coffee"},
    ]
    profile["process"]["substeps"][4] = {"name": "Unrelated"}
    scores = await score_fields(persona, profile, FakeJudge(True))
    step5 = [r for r in scores.results if r.key.startswith("process.substeps[5].")]
    assert len(step5) == len(STEP_LEAVES) and not any(r.correct for r in step5)


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
    assert scores.correct == scores.total == P01_FIELDS

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
    profile["process"]["substeps"][4]["roles"] = [{"role": "Finance director", "contribution": "approves"}]
    judge = FakeJudge(True)
    scores = await score_fields(persona, profile, judge)
    assert _result(scores, "process.substeps[5].roles").correct
    assert judge.pairs == [("Head of Controlling", "Finance director")]  # the expert's own role is implied


async def test_ac_24_13_quality_counts_every_truth_field(company):
    persona = _p01(company)
    profile = profile_from_truth(persona)
    profile["process"]["substeps"] = profile["process"]["substeps"][:4]
    profile["process"]["substep_count"] = 4
    profile["department"] = ""
    scores = await score_fields(persona, profile, FakeJudge(True))
    assert scores.total == P01_FIELDS
    # 4 captured vs 5 true: step 5 is covered by no captured step: every scored cell wrong
    assert scores.correct == P01_FIELDS - len(STEP_LEAVES) - 1 - 1  # step 5, department, step count


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


async def test_ac_24_11_rules_or_judgement_is_scored_by_code_on_its_kind():
    persona = make_persona()
    profile = profile_from_truth(persona)
    steps = profile["process"]["substeps"]
    steps[0]["decision_type"] = {"kind": "rules", "evidence": "other words entirely"}
    steps[1]["decision_type"] = {"kind": "judgement", "evidence": "same checks every month"}
    judge = FakeJudge(answer=True)
    scores = await score_fields(persona, profile, judge)
    cells = {r.key: r for r in scores.results if r.key.endswith("decision_type")}
    assert (
        cells["process.substeps[1].decision_type"].correct
        and cells["process.substeps[1].decision_type"].method == "code"
    )
    assert not cells["process.substeps[2].decision_type"].correct and judge.pairs == []


async def test_ac_24_46_a_missing_step_gets_no_credit_for_never_disclosed_cells():
    persona = make_persona()
    persona.truth.disclose["steps[*].effort"] = "never"
    profile = profile_from_truth(persona)
    profile["process"]["substeps"] = []
    scores = await score_fields(persona, profile, FakeJudge(True))
    effort = [r for r in scores.results if r.key.endswith(".effort")]
    assert len(effort) == 2 and not any(r.correct for r in effort)  # empty effort would be "honest" in a captured step


async def test_ac_24_47_the_experts_own_role_is_optional_in_step_roles():
    persona = make_persona()
    persona.truth.steps[0]["roles"] = [{"role": "Cost controller", "contribution": "checks"}]
    persona.truth.steps[1]["roles"] = [
        {"role": "Cost controller", "contribution": "writes"},
        {"role": "Head of Controlling", "contribution": "approves"},
    ]
    profile = profile_from_truth(persona)
    profile["process"]["substeps"][0]["roles"] = [{"none": True}]  # "nobody else"
    profile["process"]["substeps"][1]["roles"] = [
        {"role": "I", "contribution": "write"},
        {"role": "Head of Controlling", "contribution": "approves"},
    ]
    scores = await score_fields(persona, profile, FakeJudge(False))
    assert _result(scores, "process.substeps[1].roles").correct
    assert _result(scores, "process.substeps[2].roles").correct
    profile["process"]["substeps"][1]["roles"] = [{"none": True}]
    scores = await score_fields(persona, profile, FakeJudge(False))
    assert not _result(scores, "process.substeps[2].roles").correct  # another person is still required


async def test_spec_24_12_v2_decision_criteria_are_scored_when_the_truth_has_them():
    """§12 V2: S14 truth adds one scored field; basis by the judge, `written` and `set_by` by code."""
    from .conftest import tiny_data

    data = tiny_data()
    data["truth"]["steps"][1]["decision_type"] = {"kind": "mix", "evidence": "my call"}
    data["truth"]["steps"][1]["decision_criteria"] = {"basis": "the manager's must-haves", "written": "no"}
    persona = make_persona(truth=data["truth"])
    assert persona.truth_field_count == make_persona().truth_field_count + 1
    profile = profile_from_truth(persona)
    key = "process.substeps[2].decision_criteria"
    same = await score_fields(persona, profile, FakeJudge(answer=True))
    cell = next(r for r in same.results if r.key == key)
    assert cell.correct and same.total == persona.truth_field_count
    profile["process"]["substeps"][1]["decision_criteria"] = {"basis": "the must-haves", "written": "yes"}
    wrong = next(r for r in (await score_fields(persona, profile, FakeJudge(answer=True))).results if r.key == key)
    assert not wrong.correct and "written" in wrong.reason
    profile["process"]["substeps"][1]["decision_criteria"] = {}
    empty = next(r for r in (await score_fields(persona, profile, FakeJudge(answer=True))).results if r.key == key)
    assert not empty.correct
