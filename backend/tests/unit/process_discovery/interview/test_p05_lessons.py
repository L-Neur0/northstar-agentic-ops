"""Tests for the lessons of the p05 evaluation run (spec 14 §3.21, P1-P6).

Why: run 20261121-084902 (a talent acquisition specialist screening applications) showed the agent
never asked what a judgement is based on, asked frequency again though the volume was known, lost a
value read back for confirmation, stored "Excel/SharePoint" as one system, and kept a first-pass
`borderline` scope. These tests hold the general fixes, with the fake model.
What: AC-14.128 to AC-14.136 through `next_ask`, the prompts, the fallbacks and real turns.
Must not: patch a node or bypass a writer.
"""

from __future__ import annotations

from typing import Any

from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.interview.nodes import fallback_question
from app.services.process_discovery.interview.phases import next_ask, progress
from app.services.process_discovery.interview.prompts.guide import guide_system
from app.services.process_discovery.interview.types import Ask
from app.services.process_discovery.profile.mutate import apply_changes
from app.services.process_discovery.profile.scoring import finish_check, score

from ..profile.builders import AT
from .helpers import fake, turn
from .sessions import session_at
from .test_owner_test import OPTIONAL, TIER_A, cells, named, tier_a

CRITERIA = ("approvals", "exceptions", "handover", "decision_criteria")


def with_tier_a(ctx, index: int, kind: str, evidence: str = "weighing experience is my call") -> dict[str, Any]:
    changes = tier_a(index) | {step_cell_key(index, "decision_type"): {"kind": kind, "evidence": evidence}}
    return apply_changes(named(ctx), changes, vocab=ctx.vocab, at=AT).profile


def test_ac_14_128_tier_b_adds_criteria_for_a_judgement_or_mix_step(ctx):
    """AC-14.128: mix → Tier B has decision_criteria and GUIDE quotes the S13 words; rules → it has not."""
    profile = with_tier_a(ctx, 1, "mix")
    ask = next_ask({"profile": profile, "phase": "steps"}, vocab=ctx.vocab)
    assert ask == Ask("cell", cells(1, CRITERIA))
    text = guide_system(
        {"profile": profile, "phase": "steps"}, ask, finish_check(profile, vocab=ctx.vocab), vocab=ctx.vocab
    )
    assert (
        'You said "weighing experience is my call". What do you base that decision on, who sets those criteria' in text
    )
    rules = with_tier_a(ctx, 1, "rules", "same checks every time")
    assert next_ask({"profile": rules, "phase": "steps"}, vocab=ctx.vocab) == Ask("cell", cells(1, OPTIONAL))


def test_ac_14_128_fallback_question_asks_for_the_criteria(ctx):
    """AC-14.128: the code-built Tier B question names the criteria part and keeps "just say no"."""
    profile = with_tier_a(ctx, 1, "judgement")
    ask = next_ask({"profile": profile, "phase": "steps"}, vocab=ctx.vocab)
    text = fallback_question(ask, profile, vocab=ctx.vocab, process_name="x")
    assert "what the decision is based on" in text and "If nothing, just say no" in text


def test_ac_14_129_criteria_alone_keeps_tier_b_open_once(ctx):
    """AC-14.129: approvals and exceptions settled, S14 open → Tier B is asked for S14 alone, once."""
    profile = with_tier_a(ctx, 1, "judgement")
    settled = {
        step_cell_key(1, "approvals"): [{"none": True}],
        step_cell_key(1, "exceptions"): [{"none": True}],
    }
    profile = apply_changes(profile, settled, vocab=ctx.vocab, at=AT).profile
    ask = next_ask({"profile": profile, "phase": "steps"}, vocab=ctx.vocab)
    assert ask == Ask("cell", cells(1, ("handover", "decision_criteria")))


async def test_ac_14_130_a_no_settles_approvals_and_exceptions_and_skips_the_criteria(ctx):
    """AC-14.130: "no" → none rows for approvals and exceptions; S14 empty and skipped; walk moves on."""
    profile = with_tier_a(ctx, 1, "judgement")
    session = session_at(ctx, "steps", profile, last_question={"focus": list(cells(1, CRITERIA))})
    said_no = await turn(session, "no", fake(EXTRACT=[{}], GUIDE=["Next?"]), ctx)
    row = said_no.session.profile.process.substeps[0]
    assert row.approvals[0].model_dump() == {"none": True}
    assert row.exceptions[0].model_dump() == {"none": True}
    assert row.decision_criteria.basis == ""
    assert sorted(row.skipped) == ["decision_criteria", "handover"]
    assert said_no.session.last_question.focus == list(cells(2, TIER_A))


async def test_ac_14_130_criteria_answer_is_written(ctx):
    """AC-14.130: an answer with the criteria writes S14 next to the none row for approvals."""
    profile = with_tier_a(ctx, 1, "judgement")
    session = session_at(ctx, "steps", profile, last_question={"focus": list(cells(1, CRITERIA))})
    extract = {
        step_cell_key(1, "decision_criteria"): {
            "basis": "the hiring manager's must-haves",
            "set_by": "Hiring manager",
            "written": "no",
        },
        step_cell_key(1, "approvals"): [{"none": True}],
    }
    out = await turn(
        session,
        "they send must-haves by e-mail, not written down, no sign-off",
        fake(EXTRACT=[extract], GUIDE=["Next?"]),
        ctx,
    )
    row = out.session.profile.process.substeps[0]
    assert row.decision_criteria.basis == "the hiring manager's must-haves" and row.decision_criteria.written == "no"
    assert row.approvals[0].model_dump() == {"none": True}


def test_ac_14_131_criteria_never_change_score_progress_or_gate(ctx):
    """AC-14.131: S14 has weight 0 and is optional."""
    profile = with_tier_a(ctx, 1, "judgement")
    answered = apply_changes(
        profile, {step_cell_key(1, "decision_criteria"): {"basis": "must-haves"}}, vocab=ctx.vocab, at=AT
    ).profile
    before, after = score(profile, vocab=ctx.vocab), score(answered, vocab=ctx.vocab)
    assert (after.filled_points, after.total_points, after.value) == (
        before.filled_points,
        before.total_points,
        before.value,
    )
    assert progress(answered, {}, vocab=ctx.vocab) == progress(profile, {}, vocab=ctx.vocab)


# --- P3: effort asks duration only when the volume is known (AC-14.132, AC-14.133) ----------------


def walked_no_effort(ctx, *, volume: bool = True) -> dict[str, Any]:
    """Names and Tier A (rules, so no criteria) and Tier B settled for 3 steps; effort open."""
    profile = named(ctx)
    changes: dict[str, Any] = {}
    for i in (1, 2, 3):
        changes |= tier_a(i) | {
            step_cell_key(i, "decision_type"): {"kind": "rules", "evidence": "same every time"},
            step_cell_key(i, "approvals"): [{"none": True}],
            step_cell_key(i, "exceptions"): [{"none": True}],
        }
    out = apply_changes(profile, changes, vocab=ctx.vocab, at=AT).profile
    if not volume:  # written directly: the writer never blanks an answer
        out["process"]["volume"] = {"count": None, "period": "", "raw": ""}
    return out


EFFORT = tuple(step_cell_key(i, "effort") for i in (1, 2, 3))
EFFORT_ASKED = {"focus": list(EFFORT), "offered": {k: {"frequency": "each time"} for k in EFFORT}}


def test_ac_14_132_effort_question_asks_duration_and_states_the_assumption(ctx):
    """AC-14.132: P10 counts → duration only, the assumption named (prompt and fallback)."""
    profile = walked_no_effort(ctx)
    ask = next_ask({"profile": profile, "phase": "steps"}, vocab=ctx.vocab)
    assert ask == Ask("cell", EFFORT)
    state = {"profile": profile, "phase": "steps"}
    text = guide_system(state, ask, finish_check(profile, vocab=ctx.vocab), vocab=ctx.vocab)
    assert "how long each step takes each time" in text and "once per run of the process" in text
    assert "Do not ask how often" in text
    fallback = fallback_question(ask, profile, vocab=ctx.vocab, process_name="x")
    assert fallback.startswith("Roughly how long does each step take each time?")
    assert "I'll assume each step happens once per run of the process" in fallback


async def test_ac_14_132_durations_get_the_assumed_frequency(ctx):
    """AC-14.132: offered "each time" per step; durations → frequency written with the assumption quote."""
    profile = walked_no_effort(ctx)
    session = session_at(ctx, "steps", profile, last_question=EFFORT_ASKED)
    extract = {k: {"duration": d} for k, d in zip(EFFORT, ("3 hours", "1 day", "1 day"), strict=True)}
    out = await turn(session, "3 hours, 1 day, 1 day", fake(EXTRACT=[extract], GUIDE=["Next?"]), ctx)
    rows = out.session.profile.process.substeps
    assert [r.effort.frequency for r in rows] == ["each time"] * 3
    assert [r.effort.duration for r in rows] == ["3 hours", "1 day", "1 day"]
    meta = rows[0].meta["effort"]
    assert meta.source == "expert" and meta.status == "confirmed"
    assert meta.quote == "3 hours, 1 day, 1 day (accepted the agent's assumption)"


async def test_ac_14_132_a_frequency_the_expert_gives_wins(ctx):
    """AC-14.132: "…and step 2 twice per role" keeps EXTRACT's frequency for step 2."""
    profile = walked_no_effort(ctx)
    session = session_at(ctx, "steps", profile, last_question=EFFORT_ASKED)
    extract = {
        EFFORT[0]: {"duration": "3 hours"},
        EFFORT[1]: {"duration": "1 day", "frequency": "twice per role"},
        EFFORT[2]: {"duration": "1 day"},
    }
    out = await turn(session, "3 hours, 1 day twice per role, 1 day", fake(EXTRACT=[extract], GUIDE=["Next?"]), ctx)
    assert [r.effort.frequency for r in out.session.profile.process.substeps] == [
        "each time",
        "twice per role",
        "each time",
    ]


async def test_ac_14_132_the_effort_question_offers_each_time(ctx):
    """AC-14.132: after the walk the stored last question offers "each time" for every listed step."""
    profile = walked_no_effort(ctx)
    tier_b_done = session_at(ctx, "steps", profile, last_question={"focus": list(cells(3, OPTIONAL))})
    out = await turn(tier_b_done, "no", fake(EXTRACT=[{}], GUIDE=["How long?"]), ctx)
    assert out.session.last_question.focus == list(EFFORT)
    assert out.session.last_question.offered == {k: {"frequency": "each time"} for k in EFFORT}


def test_ac_14_133_without_a_volume_the_effort_question_is_unchanged(ctx):
    """AC-14.133: P10 not counting → duration and frequency asked, nothing assumed."""
    profile = walked_no_effort(ctx, volume=False)
    ask = next_ask({"profile": profile, "phase": "steps"}, vocab=ctx.vocab)
    assert ask == Ask("cell", EFFORT)
    fallback = fallback_question(ask, profile, vocab=ctx.vocab, process_name="x")
    assert fallback.startswith("Roughly how long does each step take, and how often?")
    text = guide_system(
        {"profile": profile, "phase": "steps"}, ask, finish_check(profile, vocab=ctx.vocab), vocab=ctx.vocab
    )
    assert "once per run of the process" not in text


# --- P4, P5: prompt rules (AC-14.134, AC-14.135) -----------------------------------------------------


def test_ac_14_134_extractor_rules(ctx):
    """AC-14.134: other keys in passing, one item per thing (with the product-name exception), pronouns."""
    from app.services.process_discovery.interview.prompts.extractor import extractor_system

    text = " ".join(extractor_system(named(ctx), "", {}, vocab=ctx.vocab, phase="steps").split())
    assert "Facts for other keys:" in text and "emit it under that key as well" in text
    assert "One item per thing:" in text and '"SAP S/4HANA"' in text
    assert "Pronouns:" in text and "write the role, not the pronoun" in text


def test_ac_14_135_guide_rules(ctx):
    """AC-14.135: a read-back value goes in `offered`; never ask estimate-or-measured on its own."""
    profile = named(ctx)
    ask = Ask("field", ("process.baseline_metric",))
    text = " ".join(
        guide_system(
            {"profile": profile, "phase": "measure"}, ask, finish_check(profile, vocab=ctx.vocab), vocab=ctx.vocab
        ).split()
    )
    assert "reads back a value the expert already gave" in text and "put that value in `offered`" in text
    assert "Never ask whether a figure is estimated or measured as a question of its own" in text


async def test_ac_14_135_a_yes_to_a_read_back_value_writes_it(ctx):
    """AC-14.135: GUIDE offered "3 working days per role" for P12; "yes" writes it (O6)."""
    from .sessions import BOUNDARIES, profile_with

    profile = profile_with(ctx, *BOUNDARIES, "process.volume", "process.process_owner")
    value = {"value": "3", "unit": "working days per role"}
    session = session_at(
        ctx,
        "measure",
        profile,
        last_question={"focus": ["process.baseline_metric"], "offered": {"process.baseline_metric": value}},
    )
    out = await turn(session, "yes", fake(EXTRACT=[{}], GUIDE=["Next?"]), ctx)
    stored = out.session.profile.process.baseline_metric
    assert (stored.value, stored.unit) == ("3", "working days per role")
