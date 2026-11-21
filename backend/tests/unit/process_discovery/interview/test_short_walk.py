"""Tests for the short step walk: grouped questions chosen by code (spec 14 §3.19; AC-14.105 to AC-14.116).

Why: the evaluation showed the walk asked one step field per message (about 11 per step). The
approved flow asks in groups: the result pair, the two quick yes/no questions, all step names, one
big Tier A question per step (plus one follow-up), one small Tier B question, effort once for all
steps; Tier C is proposed by code and confirmed in bulk in the review. Code picks every group; the
model only words it. What: the groups and their limits through `next_ask` and real turns, the Tier C
proposer, the bulk confirmation, the prompts and fallbacks, and one cooperative interview to *Finish*.
Must not: patch a node or bypass a writer.
"""

from typing import Any

from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.interview.nodes import fallback_question
from app.services.process_discovery.interview.phases import (
    given_up_keys,
    missing_fields,
    next_ask,
    proposal_group,
    wrap_up_keys,
)
from app.services.process_discovery.interview.prompts.extractor import extractor_system
from app.services.process_discovery.interview.prompts.guide import guide_system
from app.services.process_discovery.interview.types import Ask
from app.services.process_discovery.profile.inferred import propose_tier_c
from app.services.process_discovery.profile.mutate import apply_changes
from app.services.process_discovery.profile.scoring import finish_check, score

from ..profile.builders import AT
from .helpers import play
from .sessions import BOUNDARIES, MEASURE, profile_with, session_at

RESULT = ("process.end_result", "process.value_at_end")
QUICK = ("process.variation", "process.sensitive_data")
# amended 2026-11-21 (owner test, §3.20 O8): roles moved to Tier A; Tier B is the optional question
TIER_A = ("activities", "roles", "systems", "data", "pain_points", "decision_type")
# amended 2026-11-21 (§3.21 P1): the fixture's steps are "mix", so the optional question also asks the criteria
TIER_B = ("approvals", "exceptions", "handover", "decision_criteria")
NAMES = ("Collect the cost data", "Consolidate", "Review variances", "Report")


def ask(ctx, profile, phase, **parts):
    return next_ask({"profile": profile, "phase": phase, **parts}, vocab=ctx.vocab)


def cells(index: int, leaves: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(step_cell_key(index, leaf) for leaf in leaves)


def tier_a_answer(index: int) -> dict[str, Any]:
    return {
        step_cell_key(index, "activities"): ["export the actuals", "check the totals"],
        step_cell_key(index, "systems"): ["SAP", "Excel"],
        step_cell_key(index, "data"): {"inputs": [f"input {index}"], "outputs": [f"output {index}"]},
        step_cell_key(index, "pain_points"): ["chasing the sites"],
        step_cell_key(index, "roles"): [{"role": "Site controller", "contribution": "sends the file"}],
        step_cell_key(index, "decision_type"): {"kind": "mix", "evidence": "mostly fixed rules"},
    }


def tier_b_answer(index: int) -> dict[str, Any]:
    return {
        step_cell_key(index, "approvals"): [{"none": True}],
        step_cell_key(index, "exceptions"): [{"description": "totals do not match"}],
        step_cell_key(index, "decision_criteria"): {"basis": "the variance threshold", "written": "yes"},
    }


def named(ctx, steps: int = 4) -> dict[str, Any]:
    profile = profile_with(ctx, *BOUNDARIES, *MEASURE, steps=steps)
    names = {step_cell_key(i, "name"): NAMES[i - 1] for i in range(1, steps + 1)}
    return apply_changes(profile, names, vocab=ctx.vocab, at=AT).profile


def described(ctx, steps: int = 2, *, effort: bool = False) -> dict[str, Any]:
    profile = named(ctx, steps)
    changes: dict[str, Any] = {}
    for i in range(1, steps + 1):
        changes |= tier_a_answer(i) | tier_b_answer(i)
        if effort:
            changes[step_cell_key(i, "effort")] = {"duration": "2 hours", "frequency": "monthly"}
    return apply_changes(profile, changes, vocab=ctx.vocab, at=AT).profile


# --- Process groups ------------------------------------------------------------------------------


async def test_the_result_pair_is_one_question_and_charges_both(ctx):
    """AC-14.105."""
    profile = profile_with(ctx, "process.trigger")
    assert ask(ctx, profile, "boundaries") == ("field", RESULT, None)
    session = session_at(ctx, "boundaries", profile, last_question={"focus": list(RESULT)})
    results = await play(session, [("the cost report", {"process.end_result": "The cost report"})], ctx)
    after = results[-1].session
    assert after.counters.field_asks["process.end_result"] == 1
    assert after.counters.field_asks["process.value_at_end"] == 1
    assert after.last_question.focus == ["process.value_at_end"]


def test_the_quick_yes_no_pair_and_the_follow_up(ctx):
    """AC-14.106."""
    settled = ("process.volume", "process.process_owner", "process.baseline_metric", "process.target_metric")
    profile = profile_with(ctx, *BOUNDARIES, *settled)
    assert ask(ctx, profile, "measure") == ("field", QUICK, None)
    answered = apply_changes(
        profile,
        {"process.variation": {"same": "no"}, "process.sensitive_data": [{"none": True}]},
        vocab=ctx.vocab,
        at=AT,
    ).profile
    assert ask(ctx, answered, "measure") == ("field", ("process.variation",), None)


def test_the_target_is_optional_and_asked_once(ctx):
    """AC-14.107."""
    profile = profile_with(ctx, *BOUNDARIES, "process.volume", "process.process_owner", "process.baseline_metric")
    assert ask(ctx, profile, "measure").keys == ("process.target_metric",)
    counters = {"field_asks": {"process.target_metric": 1}}
    assert ask(ctx, profile, "measure", counters=counters).keys == QUICK
    assert "process.target_metric" in given_up_keys(profile, counters, vocab=ctx.vocab)
    assert "process.target_metric" not in missing_fields(profile, "review", counters, vocab=ctx.vocab)
    assert "process.target_metric" not in wrap_up_keys(profile, counters, vocab=ctx.vocab)


# --- The walk ------------------------------------------------------------------------------------


def test_all_step_names_are_asked_together(ctx):
    """AC-14.108."""
    profile = profile_with(ctx, *BOUNDARIES, *MEASURE, steps=4)
    assert ask(ctx, profile, "steps") == ("cell", tuple(step_cell_key(i, "name") for i in range(1, 5)), None)


async def test_tier_a_one_question_then_one_follow_up_then_tier_b(ctx):
    """AC-14.109."""
    profile = named(ctx, 2)
    assert ask(ctx, profile, "steps") == ("cell", cells(1, TIER_A), None)
    partial = {k: v for k, v in tier_a_answer(1).items() if not k.endswith(("roles", "decision_type"))}
    session = session_at(ctx, "steps", profile, last_question={"focus": list(cells(1, TIER_A))})
    results = await play(session, [("I export and check ...", partial), ("not sure", {})], ctx)
    assert results[0].session.last_question.focus == list(cells(1, ("roles", "decision_type")))
    after = results[1].session
    row = after.profile.process.substeps[0]
    assert row.roles[0].model_dump() == {"none": True}
    assert row.skipped == ["decision_type"]
    # §3.21 P1: rules-or-judgement is unknown (skipped), so the criteria do not apply and are not asked
    assert after.last_question.focus == list(cells(1, ("approvals", "exceptions", "handover")))


async def test_tier_b_is_asked_once_and_skipped_when_given(ctx):
    """AC-14.110 (amended §3.20 O8: optional, so an empty reply skips; a "no" is the none row, AC-14.125)."""
    profile = apply_changes(named(ctx, 2), tier_a_answer(1), vocab=ctx.vocab, at=AT).profile
    session = session_at(ctx, "steps", profile, last_question={"focus": list(cells(1, TIER_B))})
    results = await play(session, [("hm", {})], ctx)
    after = results[-1].session
    row = after.profile.process.substeps[0]
    assert sorted(row.skipped) == ["approvals", "decision_criteria", "exceptions", "handover"]
    assert after.last_question.focus == list(cells(2, TIER_A))
    given = apply_changes(
        profile, {step_cell_key(1, "approvals"): [{"approver_role": "Head of Controlling"}]}, vocab=ctx.vocab, at=AT
    ).profile
    assert ask(ctx, given, "steps").keys == cells(1, ("exceptions", "handover", "decision_criteria"))
    both = apply_changes(given, {step_cell_key(1, "exceptions"): [{"none": True}]}, vocab=ctx.vocab, at=AT).profile
    assert ask(ctx, both, "steps").keys == cells(1, ("handover", "decision_criteria"))  # §3.21 P1: S14 keeps it open
    settled = {step_cell_key(1, "decision_criteria"): {"basis": "the variance threshold"}}
    criteria = apply_changes(both, settled, vocab=ctx.vocab, at=AT).profile
    assert ask(ctx, criteria, "steps").keys == cells(2, TIER_A)  # hand-over alone is never asked


async def test_effort_is_asked_once_for_all_steps(ctx):
    """AC-14.111."""
    profile = described(ctx, 2)
    effort = (step_cell_key(1, "effort"), step_cell_key(2, "effort"))
    assert ask(ctx, profile, "steps") == ("cell", effort, None)
    session = session_at(ctx, "steps", profile, last_question={"focus": list(effort)})
    results = await play(session, [("depends", {}), ("really not sure", {})], ctx)
    assert results[0].session.last_question.focus == list(effort)
    after = results[1].session
    assert [r.skipped for r in after.profile.process.substeps] == [["effort"], ["effort"]]
    assert after.profile.process.substeps_complete is True
    assert after.phase == "review"


# --- Tier C --------------------------------------------------------------------------------------


def test_tier_c_is_proposed_by_code_with_quotes(ctx):
    """AC-14.112."""
    profile = described(ctx, 2, effort=True)
    assert profile["process"]["substeps_complete"] is not True
    proposed = propose_tier_c(profile, vocab=ctx.vocab, at=AT)
    rows = proposed["process"]["substeps"]
    assert rows[0]["goal"] == "output 1 ready"
    assert rows[0]["owner"] == "Cost controller"
    assert rows[0]["handover"] == ""  # §3.20 O9: hand-over is no longer proposed
    for leaf in ("goal", "owner"):
        meta = rows[0]["__meta"][leaf]
        assert meta["source"] == "agent" and meta["status"] == "proposed" and meta["quote"]
    assert proposed["process"]["substeps_complete"] is True
    assert score(proposed, vocab=ctx.vocab) == score(profile, vocab=ctx.vocab)
    own = apply_changes(profile, {step_cell_key(1, "goal"): "Costs are in"}, vocab=ctx.vocab, at=AT).profile
    assert propose_tier_c(own, vocab=ctx.vocab, at=AT)["process"]["substeps"][0]["goal"] == "Costs are in"
    no_role = apply_changes(profile, {}, vocab=ctx.vocab, at=AT).profile
    no_role["user_function"] = ""
    no_role["__meta"].pop("user_function", None)
    rows = propose_tier_c(no_role, vocab=ctx.vocab, at=AT)["process"]["substeps"]
    assert "owner" in rows[0]["__skipped"]


def test_tier_c_waits_for_the_step_answers(ctx):
    """AC-14.112: a step whose Tier A is still open gets no proposal yet."""
    proposed = propose_tier_c(named(ctx, 2), vocab=ctx.vocab, at=AT)
    assert all(not r["goal"] and not r["owner"] for r in proposed["process"]["substeps"])


async def test_agent_proposals_are_confirmed_in_bulk_in_the_review(ctx):
    """AC-14.113."""
    profile = propose_tier_c(described(ctx, 2, effort=True), vocab=ctx.vocab, at=AT)
    agent_keys = [step_cell_key(i, leaf) for i in (1, 2) for leaf in ("goal", "owner")]
    assert proposal_group(profile, "steps", {}, vocab=ctx.vocab) == []
    assert proposal_group(profile, "confirm", {}, vocab=ctx.vocab) == []
    assert sorted(proposal_group(profile, "review", {}, vocab=ctx.vocab)) == sorted(agent_keys)
    profile["process"]["roles_confirmed"] = profile["process"]["tools_confirmed"] = True
    session = session_at(ctx, "review", profile, last_question={"proposals": agent_keys})
    before = score(profile, vocab=ctx.vocab).filled_points
    results = await play(session, [("yes", {})], ctx)
    after = results[-1].session.profile.model_dump(by_alias=True)
    assert score(after, vocab=ctx.vocab).filled_points == before + 4
    assert after["process"]["substeps"][0]["__meta"]["goal"]["status"] == "confirmed"
    assert after["process"]["substeps"][0]["__meta"]["goal"]["source"] == "agent"
    twice = await play(session, [("hmm", {}), ("let me think", {})], ctx)
    skipped = twice[-1].session.profile.process.substeps[0].skipped
    assert {"goal", "owner"} <= set(skipped)


# --- One cooperative interview -------------------------------------------------------------------


async def test_a_cooperative_cost_review_reaches_finish_in_few_questions(ctx):
    """AC-14.114."""
    profile = profile_with(ctx, *BOUNDARIES, *MEASURE)
    session = session_at(ctx, "step_count", profile, last_question={"focus": ["process.substep_count"]})
    script: list[tuple[str, dict[str, Any]]] = [
        (
            "Collect, consolidate, review, report",
            {"process.substep_count": 4, **{step_cell_key(i, "name"): NAMES[i - 1] for i in range(1, 5)}},
        )
    ]
    for i in range(1, 5):
        script += [(f"walkthrough {i}", tier_a_answer(i)), (f"people {i}", tier_b_answer(i))]
    script.append(
        (
            "about two hours each, monthly",
            {step_cell_key(i, "effort"): {"duration": "2 hours", "frequency": "monthly"} for i in range(1, 5)},
        )
    )
    script += [("yes", {})]
    results = await play(session, script, ctx)
    asked = [r.session.last_question for r in results]
    focus = [k for q in asked for k in q.focus]
    assert not any(k.endswith((".goal", ".owner")) for k in focus)
    for i in range(1, 5):
        assert sum(1 for q in asked if any(k.startswith(f"process.substeps[{i}].") for k in q.focus)) <= 3
    final = results[-1].session
    assert final.phase == "review"
    assert finish_check(final.profile.model_dump(by_alias=True), vocab=ctx.vocab).ready is True
    assert score(final.profile.model_dump(by_alias=True), vocab=ctx.vocab).value == 1.0


# --- Prompts and fallbacks -----------------------------------------------------------------------


def test_guide_prompt_and_fallback_for_the_groups(ctx):
    """AC-14.115."""
    profile = named(ctx, 2)
    tier_a = Ask("cell", cells(1, TIER_A))
    state = {"profile": profile, "phase": "steps", "counters": {}}
    finish = finish_check(profile, vocab=ctx.vocab)
    text = guide_system(state, tier_a, finish, vocab=ctx.vocab)
    for label in ("Activities", "Roles involved", "Systems", "Data in and out", "Pain points", "Rules or judgement"):
        assert label in text
    assert "together in ONE question" in text
    assert fallback_question(tier_a, profile, vocab=ctx.vocab, process_name="Monthly cost review") == (
        'Walk me through step 1, "Collect the cost data": what you do, who else is involved, which systems and '
        "files you use, what "
        "comes in and what goes out, what is annoying or slow, and whether it runs on fixed rules, judgement or a mix?"
    )
    follow_up = Ask("cell", cells(1, ("roles", "decision_type")))
    counters = {"cell_asks": dict.fromkeys(follow_up.keys, 1)}
    assert "only the missing ones" in guide_system({**state, "counters": counters}, follow_up, finish, vocab=ctx.vocab)
    effort = Ask("cell", (step_cell_key(1, "effort"), step_cell_key(2, "effort")))
    effort_text = guide_system(state, effort, finish, vocab=ctx.vocab)
    assert "Collect the cost data" in effort_text and "Consolidate" in effort_text
    assert fallback_question(effort, profile, vocab=ctx.vocab, process_name="Monthly cost review") == (
        "Roughly how long does each step take each time? I'll assume each step happens once per run of the process "
        "(about 1 a month); tell me if one happens more often. 1 Collect the cost data, 2 Consolidate"
    )  # §3.21 P3: the volume is known, so only the duration is asked
    tier_b = Ask("cell", cells(1, TIER_B))
    assert fallback_question(tier_b, profile, vocab=ctx.vocab, process_name="x") == (
        'For step 1, "Collect the cost data": any sign-off needed, anything that often goes wrong, anything '
        "special about passing it on, and what the decision is based on, who sets the criteria and whether they are "
        "written down? If nothing, just say no."
    )


def test_extract_prompt_names_the_steps_and_the_rules_shape(ctx):
    """AC-14.116."""
    profile = described(ctx, 2)
    question = {"focus": [step_cell_key(1, "effort"), step_cell_key(2, "effort")]}
    text = extractor_system(profile, "How long does each take?", question, vocab=ctx.vocab, phase="steps")
    assert "The question covered steps 1, 2" in text
    assert '"kind"' in text and "decision_type" in text


def test_extract_prompt_names_the_step_the_question_was_about(ctx):
    """AC-14.116: with step 1's effort still open (asked at the end), a Tier A question about step 2 is about step 2.

    Added after the live check: the bound named the first incomplete row (step 1), and the model wrote
    step 2's answers into step 1.
    """
    profile = apply_changes(named(ctx, 2), tier_a_answer(1) | tier_b_answer(1), vocab=ctx.vocab, at=AT).profile
    question = {"focus": list(cells(2, TIER_A))}
    text = extractor_system(profile, "Walk me through Consolidate", question, vocab=ctx.vocab, phase="steps")
    assert "The step under discussion is step 2." in text
