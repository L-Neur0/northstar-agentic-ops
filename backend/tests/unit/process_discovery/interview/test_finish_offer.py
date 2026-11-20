"""Tests for offering *Finish* in long sessions (spec 14 §3.18; AC-14.102 to AC-14.104).

Why: a long session must hear, from code and at fixed points, that it can stop (or what it still
needs before it can), without that line ever closing the walk, moving the phase or charging a field.
What: the 40th and every 10th expert message after it end with the code-built line (on a GUIDE
turn, a fallback turn and a conflict turn), at most 3 gaps by label; the 41st to 49th do not; the
offer changes nothing but `expert_messages`; below the gate the line names what is still needed.
Must not: call a real model or patch a node. Spec 14 §3.18.
"""

from __future__ import annotations

from app.models.process_discovery_schemas import Counters
from app.services.process_discovery.domain.field_spec import PROFILE_SPECS
from app.services.process_discovery.interview.finish_offer import (
    OFFER_END,
    OFFER_LEAD,
    finish_gaps,
    offer_due,
)
from app.services.process_discovery.profile.mutate import confirm_rollup
from app.services.process_discovery.profile.scoring import finish_check
from app.services.process_discovery.profile.shapes import empty_profile

from ..profile.builders import cost_review_profile
from .conflict_helpers import example_session, site_offer
from .helpers import fake, play, turn
from .sessions import profile_with, session_at

PAIN = "process.business_pain"


def label_of(ctx, key):
    return ctx.vocab.label(next(s for s in PROFILE_SPECS if s.key == key))


def ready_session(ctx, expert_messages=0):
    """Review, *Finish* open, one gap (the business pain, given up)."""
    profile = cost_review_profile(ctx.vocab, steps=2)
    profile["process"]["business_pain"] = ""
    profile = confirm_rollup(confirm_rollup(profile, "roles", vocab=ctx.vocab), "systems", vocab=ctx.vocab)
    assert finish_check(profile, vocab=ctx.vocab).ready
    counters = {"field_asks": {PAIN: 5}, "expert_messages": expert_messages}
    return session_at(ctx, "review", profile, counters=counters)


def last_paragraph(reply):
    return reply.rsplit("\n\n", 1)[-1]


def test_ac_14_102_the_offer_is_due_at_40_and_every_10_after():
    due = [n for n in range(1, 81) if offer_due(n, first=40, every=10)]
    assert due == [40, 50, 60, 70, 80]


def test_ac_14_102_counters_carry_expert_messages():
    assert Counters().expert_messages == 0


async def test_ac_14_102_the_40th_message_ends_with_the_offer_the_41st_to_49th_do_not_the_50th_does(ctx):
    session = ready_session(ctx, expert_messages=39)
    results = await play(session, [("Nothing to add.", {}) for _ in range(11)], ctx)
    assert results[-1].session.counters.expert_messages == 50
    with_offer = [i for i, r in enumerate(results, start=40) if last_paragraph(r.reply).startswith(OFFER_LEAD)]
    assert with_offer == [40, 50]
    line = last_paragraph(results[0].reply)
    assert "You can press Finish now" in line
    assert label_of(ctx, PAIN) in line
    assert line.endswith(OFFER_END)
    assert results[0].reply.startswith("Next question?")
    stored = results[0].session.messages[-1].text
    assert stored == results[0].reply


async def test_ac_14_102_a_fallback_reply_also_ends_with_the_offer(ctx):
    session = ready_session(ctx, expert_messages=39)
    result = await turn(session, "Nothing to add.", fake(EXTRACT=[{}], GUIDE=[""]), ctx)
    assert not result.reply.startswith("Next question?")
    assert last_paragraph(result.reply).startswith(OFFER_LEAD)


async def test_ac_14_102_a_conflict_question_also_ends_with_the_line(ctx):
    session = example_session(ctx, site_offer())
    session = session.model_copy(update={"counters": Counters(expert_messages=39)})
    result = await turn(session, "Let me think.", fake(EXTRACT=[{}]), ctx)
    assert result.session.last_question.conflicts  # the conflict question was asked by code
    assert last_paragraph(result.reply).startswith(OFFER_LEAD)


def test_ac_14_102_at_most_three_gaps_by_label(ctx):
    gaps = finish_gaps(empty_profile(), vocab=ctx.vocab)
    assert len(gaps) == 3
    assert all("." not in g for g in gaps)  # labels, never registry keys


async def test_ac_14_103_the_offer_changes_nothing_but_expert_messages(ctx):
    plain = (await turn(ready_session(ctx, 38), "Nothing to add.", fake(EXTRACT=[{}], GUIDE=["Q?"]), ctx)).session
    offered = (await turn(ready_session(ctx, 39), "Nothing to add.", fake(EXTRACT=[{}], GUIDE=["Q?"]), ctx)).session
    assert offered.counters.expert_messages == plain.counters.expert_messages + 1 == 40
    assert offered.counters.model_dump(exclude={"expert_messages"}) == plain.counters.model_dump(
        exclude={"expert_messages"}
    )
    assert offered.phase == plain.phase == ready_session(ctx).phase
    assert offered.last_question == plain.last_question
    assert offered.profile == plain.profile


async def test_ac_14_103_a_61st_message_is_still_answered(ctx):
    session = ready_session(ctx, expert_messages=60)
    result = await turn(session, "One more thing.", fake(EXTRACT=[{}], GUIDE=["Anything else?"]), ctx)
    assert result.reply == "Anything else?"
    assert result.session.phase.value == "review"
    assert result.session.counters.expert_messages == 61


async def test_ac_14_104_below_the_gate_the_line_says_what_is_still_needed(ctx):
    session = session_at(ctx, "measure", profile_with(ctx, "process.trigger"), counters={"expert_messages": 39})
    result = await turn(session, "Not sure.", fake(EXTRACT=[{}], GUIDE=["How often does it run?"]), ctx)
    line = last_paragraph(result.reply)
    assert line.startswith(OFFER_LEAD)
    assert "You can press Finish now" not in line
    assert "Before you can press Finish, we still need:" in line
    needed = line.split("we still need: ", 1)[1].rstrip(".").split(", ")
    assert needed == finish_gaps(result.session.profile.model_dump(by_alias=True), vocab=ctx.vocab)
    assert 1 <= len(needed) <= 3
    assert result.session.phase.value == "measure"
