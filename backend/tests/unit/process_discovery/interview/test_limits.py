"""Tests for the ask counters and their limits (spec 14 §3.3, §3.6; AC-14.20 to AC-14.23, AC-14.27, AC-14.28).

Why: every loop has a counter and every counter a maximum; a cooperative expert must never hit a
limit, and an unhelpful one must never pin the interview. What: per-field charging, deferral,
re-asking in review and giving up, the invalid step count, the name at the direct posture, the
assumed step count, and counter hygiene.
"""

import copy

from app.services.process_discovery.domain.field_spec import PROFILE_SPECS
from app.services.process_discovery.interview.phases import (
    charge_asks,
    deferred_keys,
    given_up_keys,
    missing_fields,
    next_ask,
    read_counters,
)
from app.services.process_discovery.profile.scoring import score

from ..profile.builders import process_changes
from .helpers import play
from .sessions import BOUNDARIES, MEASURE, profile_with, session_at


async def test_a_cooperative_expert_charges_each_field_once(ctx):
    """AC-14.20."""
    session = session_at(ctx, "measure", profile_with(ctx, *BOUNDARIES), last_question={"focus": ["process.volume"]})
    values = process_changes()
    results = await play(session, [(f"answer {k}", {k: values[k]}) for k in MEASURE], ctx)
    final = results[-1].session
    assert {k: final.counters.field_asks[k] for k in MEASURE} == dict.fromkeys(MEASURE, 1)
    assert deferred_keys(final.profile.model_dump(by_alias=True), final.counters.model_dump(), vocab=ctx.vocab) == []
    assert [r.session.last_question.focus for r in results[:-1]] == [[k] for k in MEASURE[1:]]


async def test_defer_after_three_then_review_then_give_up(ctx):
    """AC-14.21."""
    keys = [k for k in MEASURE if k != "process.baseline_metric"]
    session = session_at(
        ctx, "measure", profile_with(ctx, *BOUNDARIES, *keys), last_question={"focus": ["process.baseline_metric"]}
    )
    results = await play(session, [("no idea", {})] * 3, ctx)
    after = results[-1].session
    assert after.counters.field_asks["process.baseline_metric"] == 3
    assert after.phase.value == "step_count"
    profile = after.profile.model_dump(by_alias=True)
    counters = after.counters.model_dump()
    assert "process.baseline_metric" in missing_fields(profile, "review", counters, vocab=ctx.vocab)
    counters["field_asks"]["process.baseline_metric"] = 5
    assert given_up_keys(profile, counters, vocab=ctx.vocab) == ["process.baseline_metric"]
    assert "process.baseline_metric" not in missing_fields(profile, "review", counters, vocab=ctx.vocab)
    assert score(profile, vocab=ctx.vocab).filled_points == 15  # 18 minus baseline (2) minus the count (1)


async def test_an_invalid_step_count_holds_its_phase_until_given_up(ctx):
    """AC-14.22."""
    session = session_at(
        ctx, "step_count", profile_with(ctx, *BOUNDARIES, *MEASURE), last_question={"focus": ["process.substep_count"]}
    )
    results = await play(session, [("13 steps", {"process.substep_count": 13})] * 5, ctx)
    assert [r.session.phase.value for r in results] == ["step_count"] * 4 + ["steps"]
    assert results[2].session.last_question.focus == ["process.substep_count"]
    assert results[-1].session.profile.process.substep_count == 2


async def test_the_name_is_charged_only_at_the_direct_posture(ctx):
    """AC-14.23."""
    from app.models.process_discovery_schemas import Profile
    from app.services.process_discovery.profile.mutate import apply_changes
    from app.services.process_discovery.profile.shapes import empty_profile

    from ..profile.builders import AT, context_changes
    from .helpers import new_session

    p = apply_changes(empty_profile(), context_changes(), vocab=ctx.vocab, at=AT).profile
    session = new_session(
        ctx, phase="find", profile=Profile.model_validate(p), last_question={"focus": ["process.name"]}
    )
    results = await play(session, [("not sure really", {})] * 5, ctx)
    counters = results[-1].session.counters
    assert counters.field_asks.get("process.name", 0) == 0
    assert counters.find_turns == 5
    more = await play(results[-1].session, [("still not sure", {})] * 3, ctx)
    assert more[-1].session.counters.field_asks["process.name"] == 3


async def test_a_deferred_count_is_assumed_and_the_walk_starts(ctx):
    """AC-14.27."""
    session = session_at(
        ctx, "step_count", profile_with(ctx, *BOUNDARIES, *MEASURE), last_question={"focus": ["process.substep_count"]}
    )
    results = await play(session, [("not sure", {})] * 3, ctx)
    assert [r.session.profile.process.substep_count for r in results] == [None, None, 2]
    assert results[-1].session.phase.value == "steps"
    assert results[-1].session.last_question.focus == ["process.substeps[1].name"]


def test_counter_hygiene():
    """AC-14.28."""
    corrupt = {"field_asks": {"process.volume": "x", "process.trigger": -2, "process.name": 2}, "find_turns": True}
    clean = read_counters(corrupt)
    assert clean["field_asks"] == {"process.volume": 0, "process.trigger": 0, "process.name": 2}
    assert clean["find_turns"] == 0
    before = copy.deepcopy(corrupt)
    charged = charge_asks(corrupt, {"focus": ["process.volume"]}, "measure", find_turns_before=0)
    assert corrupt == before
    assert charged["field_asks"]["process.volume"] == 1


def test_review_lists_only_fields_that_neither_count_nor_were_given_up(ctx):
    """AC-14.21 (the review list)."""
    profile = profile_with(ctx, *BOUNDARIES)
    state = {"profile": profile, "phase": "review", "counters": {"field_asks": {"process.volume": 5}}}
    ask = next_ask(state, vocab=ctx.vocab)
    assert ask.keys == ("process.process_owner",)
    assert len(PROFILE_SPECS) == 16
