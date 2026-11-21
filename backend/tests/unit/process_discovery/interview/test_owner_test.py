"""Tests for the owner-test amendment: welcome, suggestions, offered values, progress, a shorter walk (spec 14 §3.20).

Why: the product owner's end-to-end test (an HR expert mapping "reviewing CVs") showed a "yes" to
values the agent itself offered was lost (the sensitive data stayed empty; the step names looped
three times and were skipped), "I have no idea" got no suggestion, recurring individual work was
pushed back as a task, the bar read 83 % before the walk, and the walk asked too much. These tests
reproduce those exchanges with the fake model and hold the fixes.
What: AC-14.117 to AC-14.127, through `next_ask`, the prompts, the fallbacks and real turns.
Must not: patch a node or bypass a writer; GUIDE replies are scripted as the model would send them.
"""

import json
from typing import Any

from app.models.process_discovery_schemas import Profile
from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.domain.scope import build_scope_verdict
from app.services.process_discovery.interview.gates import apply_scope_verdict
from app.services.process_discovery.interview.nodes import fallback_question
from app.services.process_discovery.interview.phases import next_ask, progress
from app.services.process_discovery.interview.prompts.extractor import extractor_system
from app.services.process_discovery.interview.prompts.guide import guide_system
from app.services.process_discovery.interview.turn import after_action, welcome
from app.services.process_discovery.interview.types import Ask
from app.services.process_discovery.profile.inferred import propose_tier_c
from app.services.process_discovery.profile.mutate import apply_changes
from app.services.process_discovery.profile.scoring import finish_check, score
from app.services.process_discovery.profile.shapes import empty_profile

from ..profile.builders import AT
from .helpers import fake, turn
from .sessions import BOUNDARIES, MEASURE, profile_with, session_at

TIER_A = ("activities", "roles", "systems", "data", "pain_points", "decision_type")
OPTIONAL = ("approvals", "exceptions", "handover")
NAMES = ("Initial screening", "Requirements and online fact-check", "Shortlist and handoff")
QUICK = ("process.variation", "process.sensitive_data")
CLASSIFY_OK = {
    "scope": {
        "multi_role": True,
        "multi_system": True,
        "trigger_and_outcome": True,
        "recurring": True,
        "external_consumer": True,
        "reasoning": "x",
    },
    "placement": {"code": "HR", "confidence": 0.9, "rationale": "x", "runner_up": None, "runner_up_confidence": None},
}
SENSITIVE = [{"item": "candidate contact details"}, {"item": "employment history"}, {"item": "GDPR"}]


def cells(index: int, leaves: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(step_cell_key(index, leaf) for leaf in leaves)


def guide(question: str, offered: dict[str, Any] | None = None) -> str:
    """A GUIDE reply as the model sends it: one JSON object."""
    return json.dumps({"question": question, "offered": offered or {}})


def dump(profile: Any) -> dict[str, Any]:
    return profile.model_dump(by_alias=True) if isinstance(profile, Profile) else profile


def walked(ctx, steps: int = 3) -> dict[str, Any]:
    """Names, Tier A (with roles) and effort for every step: everything the walk asks, answered."""
    profile = profile_with(ctx, *BOUNDARIES, *MEASURE, steps=steps)
    changes: dict[str, Any] = {}
    for i in range(1, steps + 1):
        changes |= {
            step_cell_key(i, "name"): NAMES[i - 1],
            step_cell_key(i, "activities"): ["download the CVs", "check them"],
            step_cell_key(i, "roles"): [{"role": "Hiring manager"}],
            step_cell_key(i, "systems"): ["the platform", "LinkedIn"],
            step_cell_key(i, "data"): {"inputs": ["CVs"], "outputs": [f"shortlist {i}"]},
            step_cell_key(i, "pain_points"): ["it takes time"],
            step_cell_key(i, "decision_type"): {"kind": "judgement", "evidence": "checking for honesty"},
            step_cell_key(i, "effort"): {"duration": "1 hour", "frequency": "weekly"},
            step_cell_key(i, "approvals"): [{"none": True}],
            step_cell_key(i, "exceptions"): [{"none": True}],
        }
    return propose_tier_c(apply_changes(profile, changes, vocab=ctx.vocab, at=AT).profile, vocab=ctx.vocab, at=AT)


# --- O1 welcome ------------------------------------------------------------------------------------


def test_ac_14_117_the_welcome_says_what_happens_and_both_disclosures(ctx):
    text, question = welcome("Alex", ctx)
    assert text.startswith("Hi Alex! I'm the AI Use Case Discovery Agent.")
    for words in (
        "recurring workflow",
        "transforming with AI",
        "about 20 minutes",
        "add a document",
        "describe the work, not you",
        "transformation team may read this conversation",
    ):
        assert words in text
    assert text.endswith("To start: Which department are you in?")
    assert question.focus == ["department"]


# --- O2 suggestions in find ------------------------------------------------------------------------


def hr_profile(ctx, department: str = "HR") -> dict[str, Any]:
    changes = {"department": department, "user_function": "talent scouting and pre screening", "region": "Europe"}
    return apply_changes(empty_profile(), changes, vocab=ctx.vocab, at=AT).profile


def test_ac_14_118_code_decides_when_the_model_suggests(ctx):
    profile = hr_profile(ctx)
    state = {"profile": profile, "phase": "find", "counters": {"find_turns": 1}}
    ask = next_ask(state, vocab=ctx.vocab)
    assert ask.keys == ("process.name",)
    finish = finish_check(profile, vocab=ctx.vocab)
    text = guide_system(state, ask, finish, vocab=ctx.vocab)
    assert "SUGGEST:" in text and "two or three concrete candidates" in text and "`process.name`" in text
    with_candidate = {**state, "steering": {"candidates": [{"id": "c1", "name": "reviewing CVs", "words": "x"}]}}
    assert "SUGGEST:" not in guide_system(with_candidate, ask, finish, vocab=ctx.vocab)
    capped = {**state, "counters": {"find_turns": 4}}
    assert "SUGGEST:" not in guide_system(capped, ask, finish, vocab=ctx.vocab)
    assert "SUGGEST:" not in guide_system({**state, "phase": "context"}, ask, finish, vocab=ctx.vocab)


async def test_ac_14_118_suggested_candidates_are_offers_only(ctx):
    session = session_at(
        ctx, "find", hr_profile(ctx), scope={}, placement={}, last_question={"focus": ["process.name"]}
    )
    offered = {"process.name": ["screening CVs against a vacancy", "scheduling first interviews", "x", "y"]}
    first = await turn(session, "i have no idea", fake(EXTRACT=[{}], GUIDE=[guide("For example...?", offered)]), ctx)
    assert first.session.last_question.offered == {"process.name": offered["process.name"][:3]}
    assert first.session.profile.process.name == ""
    plain = await turn(first.session, "yes", fake(EXTRACT=[{}], GUIDE=["Which one?"]), ctx)
    assert plain.session.profile.process.name == ""
    picked = await turn(
        first.session,
        "yes the first one",
        fake(EXTRACT=[{"process.name": "screening CVs against a vacancy"}], GUIDE=["Next?"], CLASSIFY=[CLASSIFY_OK]),
        ctx,
    )
    assert picked.session.profile.process.name == "screening CVs against a vacancy"


def test_ac_14_119_recurring_individual_work_is_not_pushed_back(ctx):
    signals = {
        "multi_role": False,
        "multi_system": True,
        "trigger_and_outcome": True,
        "recurring": True,
        "external_consumer": False,
        "reasoning": "One person reviews CVs every week.",
    }
    verdict = build_scope_verdict(signals)
    assert verdict["verdict"] in ("task", "borderline")
    scope, counters = apply_scope_verdict({}, {}, verdict, "reviewing CVs")
    assert scope["awaiting_widening"] is False and counters["widening_count"] == 0
    one_off = build_scope_verdict({**signals, "recurring": False})
    scope, _ = apply_scope_verdict({}, {}, one_off, "reviewing CVs")
    assert scope["awaiting_widening"] is True


# --- O4 progress -----------------------------------------------------------------------------------


def test_ac_14_120_progress_follows_the_interview_path(ctx):
    end_of_measure = profile_with(ctx, *BOUNDARIES, *MEASURE)
    value = progress(end_of_measure, {}, vocab=ctx.vocab)
    assert 0.30 <= value <= 0.40
    assert score(end_of_measure, vocab=ctx.vocab).value > 0.80  # the score alone read "83 %"
    counted = profile_with(ctx, *BOUNDARIES, *MEASURE, steps=3)
    assert progress(counted, {}, vocab=ctx.vocab) == round(18 / (18 + 3 * 8), 4)
    done = walked(ctx, 3)
    assert progress(done, {}, vocab=ctx.vocab) == 1.0
    target_given_up = profile_with(ctx, *BOUNDARIES, *(k for k in MEASURE if k != "process.target_metric"))
    counters = {"field_asks": {"process.target_metric": 1}}
    assert progress(target_given_up, counters, vocab=ctx.vocab) == value
    assert finish_check(done, vocab=ctx.vocab) == finish_check(done, vocab=ctx.vocab)


# --- O5–O7 offered values --------------------------------------------------------------------------


def measure_session(ctx):
    settled = ("process.volume", "process.process_owner", "process.baseline_metric", "process.target_metric")
    profile = profile_with(ctx, *BOUNDARIES, *settled)
    return session_at(ctx, "measure", profile, last_question={"focus": list(QUICK)})


async def test_ac_14_121_guide_offers_are_kept_only_for_the_asked_keys(ctx):
    session = measure_session(ctx)
    question = "What sensitive data is involved, for example candidate contact details, employment history, or GDPR?"
    offered = {"process.sensitive_data": SENSITIVE, "process.trigger": "something else"}
    llm = fake(EXTRACT=[{"process.variation": {"same": "yes"}}], GUIDE=[guide(question, offered)])
    result = await turn(session, "yes", llm, ctx)
    assert result.reply.startswith(question)
    assert result.session.last_question.focus == ["process.sensitive_data"]
    assert result.session.last_question.offered == {"process.sensitive_data": SENSITIVE}
    plain = await turn(session, "yes", fake(EXTRACT=[{}], GUIDE=["Which data is involved?"]), ctx)
    assert plain.reply.startswith("Which data is involved?") and plain.session.last_question.offered == {}
    broken = await turn(
        session,
        "yes",
        fake(
            EXTRACT=[{}],
            GUIDE=['{"question": "Which data'],
        ),
        ctx,
    )
    assert "{" not in broken.reply and broken.session.last_question.offered == {}


async def test_ac_14_122_yes_the_ones_you_listed_writes_the_sensitive_data(ctx):
    """Regression: the test session's "yes the one u have listed" left P15 empty and asked again."""
    session = measure_session(ctx)
    question = "For reviewing CVs, what sensitive data is involved, for example candidate contact details, employment history, or GDPR?"
    first = await turn(
        session,
        "yes",
        fake(
            EXTRACT=[{"process.variation": {"same": "yes"}}],
            GUIDE=[guide(question, {"process.sensitive_data": SENSITIVE})],
        ),
        ctx,
    )
    second = await turn(first.session, "yes the one u have listed", fake(EXTRACT=[{}], GUIDE=["Next?"]), ctx)
    profile = dump(second.session.profile)
    rows = profile["process"]["sensitive_data"]
    assert [r["item"] for r in rows] == ["candidate contact details", "employment history", "GDPR"]
    meta = profile["__meta"]["process.sensitive_data"]
    assert meta["source"] == "expert" and meta["status"] == "confirmed"
    assert meta["quote"] == "yes the one u have listed (accepted the agent's suggestion)"
    assert second.session.last_question.focus == ["process.substep_count"]
    assert second.session.last_question.offered == {}


async def test_ac_14_122_those_are_exact_writes_the_offered_step_names(ctx):
    """Regression: "those are exact" / "yes" / "i confirm" looped three times and the names were skipped."""
    profile = profile_with(ctx, *BOUNDARIES, *MEASURE)
    session = session_at(ctx, "step_count", profile, last_question={"focus": ["process.substep_count"]})
    names = {step_cell_key(i, "name"): NAMES[i - 1] for i in range(1, 4)}
    question = "What are the three steps? For example: 1) Initial screening, 2) Requirements and online fact-check, 3) Shortlist and handoff."
    first = await turn(session, "3", fake(EXTRACT=[{"process.substep_count": 3}], GUIDE=[guide(question, names)]), ctx)
    assert first.session.last_question.offered == names
    second = await turn(first.session, "those are exact", fake(EXTRACT=[{}], GUIDE=["Walk me through it?"]), ctx)
    rows = second.session.profile.process.substeps
    assert [r.name for r in rows] == list(NAMES)
    assert all(not r.skipped for r in rows)
    assert second.session.last_question.focus == list(cells(1, TIER_A))


async def test_ac_14_122_names_offered_on_the_steps_question_set_the_count(ctx):
    profile = profile_with(ctx, *BOUNDARIES, *MEASURE)
    session = session_at(ctx, "measure", profile, last_question={"focus": ["process.sensitive_data"]})
    names = {step_cell_key(i, "name"): NAMES[i - 1] for i in range(1, 4)}
    first = await turn(session, "none", fake(EXTRACT=[{}], GUIDE=[guide("Like these three?", names)]), ctx)
    assert first.session.last_question.focus == ["process.substep_count"]
    second = await turn(first.session, "yes", fake(EXTRACT=[{}], GUIDE=["Next?"]), ctx)
    assert second.session.profile.process.substep_count == 3
    assert [r.name for r in second.session.profile.process.substeps] == list(NAMES)


async def test_ac_14_122_a_no_writes_nothing_and_a_correction_wins(ctx):
    session = measure_session(ctx)
    offered = {"process.sensitive_data": SENSITIVE}
    first = await turn(
        session,
        "yes",
        fake(EXTRACT=[{"process.variation": {"same": "yes"}}], GUIDE=[guide("Which data, e.g. ...?", offered)]),
        ctx,
    )
    no = await turn(first.session, "no", fake(EXTRACT=[{}], GUIDE=["Which then?"]), ctx)
    assert no.session.profile.process.sensitive_data == []
    corrected = await turn(
        first.session,
        "yes, but only the contact details",
        fake(EXTRACT=[{"process.sensitive_data": [{"item": "contact details"}]}], GUIDE=["Next?"]),
        ctx,
    )
    assert [r.model_dump()["item"] for r in corrected.session.profile.process.sensitive_data] == ["contact details"]


def test_ac_14_123_extract_sees_the_offered_values(ctx):
    profile = profile_with(ctx, *BOUNDARIES)
    question = {"focus": ["process.sensitive_data"], "offered": {"process.sensitive_data": SENSITIVE}}
    text = extractor_system(profile, "Which data, e.g. GDPR?", question, vocab=ctx.vocab, phase="measure")
    assert "OFFERED" in text and "candidate contact details" in text
    assert "the ones you listed" in text


# --- O8–O10 the shorter walk -----------------------------------------------------------------------


def named(ctx, steps: int = 3) -> dict[str, Any]:
    profile = profile_with(ctx, *BOUNDARIES, *MEASURE, steps=steps)
    names = {step_cell_key(i, "name"): NAMES[i - 1] for i in range(1, steps + 1)}
    return apply_changes(profile, names, vocab=ctx.vocab, at=AT).profile


def tier_a(index: int) -> dict[str, Any]:
    return {
        step_cell_key(index, "activities"): ["download the CVs"],
        step_cell_key(index, "roles"): [{"role": "Hiring manager"}],
        step_cell_key(index, "systems"): ["the platform"],
        step_cell_key(index, "data"): {"inputs": ["CVs"], "outputs": ["shortlist"]},
        step_cell_key(index, "pain_points"): ["it takes time"],
        step_cell_key(index, "decision_type"): {"kind": "judgement", "evidence": "checking for honesty"},
    }


async def test_ac_14_125_one_optional_question_per_step_never_blocks(ctx):
    profile = apply_changes(named(ctx), tier_a(1), vocab=ctx.vocab, at=AT).profile
    ask = next_ask({"profile": profile, "phase": "steps"}, vocab=ctx.vocab)
    asked = (*OPTIONAL, "decision_criteria")  # §3.21 P1: tier_a is a judgement step, so the criteria join
    assert ask == Ask("cell", cells(1, asked))
    assert "If nothing, just say no" in fallback_question(ask, profile, vocab=ctx.vocab, process_name="x")
    session = session_at(ctx, "steps", profile, last_question={"focus": list(cells(1, asked))})
    said_no = await turn(session, "no", fake(EXTRACT=[{}], GUIDE=["Next?"]), ctx)
    row = said_no.session.profile.process.substeps[0]
    assert row.approvals[0].model_dump() == {"none": True}
    assert row.exceptions[0].model_dump() == {"none": True}
    assert sorted(row.skipped) == ["decision_criteria", "handover"]
    assert said_no.session.last_question.focus == list(cells(2, TIER_A))
    silent = await turn(session, "hm", fake(EXTRACT=[{}], GUIDE=["Next?"]), ctx)
    row = silent.session.profile.process.substeps[0]
    assert sorted(row.skipped) == ["approvals", "decision_criteria", "exceptions", "handover"]
    before = score(profile, vocab=ctx.vocab)
    after = score(dump(silent.session.profile), vocab=ctx.vocab)
    assert after.total_points == before.total_points - 2 and after.filled_points == before.filled_points


def test_ac_14_126_roles_are_in_tier_a_and_tier_c_is_goal_and_owner(ctx):
    profile = named(ctx)
    assert next_ask({"profile": profile, "phase": "steps"}, vocab=ctx.vocab) == Ask("cell", cells(1, TIER_A))
    answered = apply_changes(profile, tier_a(1) | tier_a(2), vocab=ctx.vocab, at=AT).profile
    proposed = propose_tier_c(answered, vocab=ctx.vocab, at=AT)
    rows = proposed["process"]["substeps"]
    assert rows[0]["goal"] and rows[0]["owner"]
    assert rows[0]["handover"] == ""


async def test_ac_14_127_no_confirm_phase_and_finish_without_list_confirmations(ctx):
    profile = walked(ctx, 3)
    assert profile["process"]["substeps_complete"] is True
    assert profile["process"]["roles_confirmed"] is False
    check = finish_check(profile, vocab=ctx.vocab)
    assert check.blocked_by not in ("roles_not_confirmed", "tools_not_confirmed")
    session = session_at(ctx, "confirm", profile)
    moved = after_action(session, ctx=ctx)
    assert moved.phase == "review"
    effort_open = apply_changes(named(ctx), tier_a(1) | tier_a(2) | tier_a(3), vocab=ctx.vocab, at=AT).profile
    effort = tuple(step_cell_key(i, "effort") for i in range(1, 4))
    optional = {
        k: [{"none": True}]
        for i in range(1, 4)
        for k in (step_cell_key(i, "approvals"), step_cell_key(i, "exceptions"))
    }
    effort_open = apply_changes(effort_open, optional, vocab=ctx.vocab, at=AT).profile
    session = session_at(ctx, "steps", effort_open, last_question={"focus": list(effort)})
    answers = {k: {"duration": "1 hour", "frequency": "weekly"} for k in effort}
    result = await turn(session, "an hour each, weekly", fake(EXTRACT=[answers], GUIDE=["Anything to correct?"]), ctx)
    assert result.session.phase == "review"


async def test_ac_14_122b_a_plain_yes_to_the_quick_pair_is_a_yes_to_the_same_everywhere(ctx):
    """Found in the live check: "yes" to the two quick questions wrote nothing and looped (§3.20 O11)."""
    session = measure_session(ctx)
    question = "Which data, for example candidate contact details, employment history or GDPR?"
    result = await turn(
        session, "yes", fake(EXTRACT=[{}], GUIDE=[guide(question, {"process.sensitive_data": SENSITIVE})]), ctx
    )
    assert result.session.profile.process.variation.same == "yes"
    assert result.session.profile.process.sensitive_data == []
    assert result.session.last_question.focus == ["process.sensitive_data"]
    second = await turn(result.session, "yes the one u have listed", fake(EXTRACT=[{}], GUIDE=["Next?"]), ctx)
    assert len(second.session.profile.process.sensitive_data) == 3


async def test_ac_14_122c_same_everywhere_in_a_longer_reply_completes_the_variation(ctx):
    """Live check: "…, yes it is the same everywhere" left P14 invalid (`same` held the sentence) 5 times (O11)."""
    session = measure_session(ctx)
    text = "this is a centralized function, so i handle every region, yes it is the same everywhere"
    extract = {"process.variation": {"same": "yes it is the same everywhere"}}
    result = await turn(session, text, fake(EXTRACT=[extract], GUIDE=["Which data?"]), ctx)
    assert result.session.profile.process.variation.same == "yes"
    assert result.session.last_question.focus == ["process.sensitive_data"]
    differs = await turn(session, "no, every region has its own way", fake(EXTRACT=[{}], GUIDE=["What differs?"]), ctx)
    assert differs.session.profile.process.variation.same != "yes"


async def test_ac_14_118c_the_process_name_is_the_experts_words_never_an_unpicked_offer(ctx):
    """Live check: "mainly reviewing CVs" was stored as the offered "Checking CVs against vacancy requirements"."""
    offered = ["Checking CVs against vacancy requirements", "Scheduling first interviews"]
    session = session_at(
        ctx,
        "find",
        hr_profile(ctx),
        scope={},
        placement={},
        last_question={"focus": ["process.name"], "offered": {"process.name": offered}},
    )
    own = await turn(
        session, "mainly reviewing CVs", fake(EXTRACT=[{"process.name": offered[0]}], GUIDE=["Reviewing CVs?"]), ctx
    )
    assert own.session.profile.process.name == ""
    words = await turn(
        session,
        "mainly reviewing CVs",
        fake(EXTRACT=[{"process.name": "reviewing CVs"}], GUIDE=["Next?"], CLASSIFY=[CLASSIFY_OK]),
        ctx,
    )
    assert words.session.profile.process.name == "reviewing CVs"
    picked = await turn(
        session,
        "the second one",
        fake(EXTRACT=[{"process.name": offered[1]}], GUIDE=["Next?"], CLASSIFY=[CLASSIFY_OK]),
        ctx,
    )
    assert picked.session.profile.process.name == offered[1]
    text = extractor_system(
        hr_profile(ctx),
        "Which?",
        {"focus": ["process.name"], "offered": {"process.name": offered}},
        vocab=ctx.vocab,
        phase="find",
    )
    assert "their own words" in text
