"""Tests for confirming the roles and systems lists with a plain yes (spec 14 §3.7; AC-14.17 to AC-14.19).

Why: the confirmation phase exits only on two flags a person raises; a plain yes in the chat must
count, but never outside the question, never over an edit, and never automatically.
What: turns in `confirm` on a closed walk, with the lists named in the last question, named only
by cue words, or not named at all; and the cases where nothing may be confirmed.
"""

from app.models.process_discovery_schemas import Profile
from app.services.process_discovery.domain.field_spec import step_cell_key

from ..profile.builders import AT, cost_review_profile
from .helpers import fake, new_session, turn

NAME = "Monthly cost review"
ROLES, TOOLS = "process.all_roles", "process.all_tools"


def confirm_session(
    ctx,
    focus=(ROLES,),
    agent="Here are the roles across the steps: Controller. Right?",
    phase="confirm",
    closed=True,
    counters=None,
):
    profile = (
        cost_review_profile(ctx.vocab, steps=2) if closed else cost_review_profile(ctx.vocab, steps=2, filled_steps=1)
    )
    return new_session(
        ctx,
        phase=phase,
        profile=Profile.model_validate(profile),
        scope={"verdict": None, "scoped_for": NAME},
        placement={"proposal": None, "placed_for": NAME},
        last_question={"focus": list(focus), "proposals": [], "confirm": "roles" if focus else None},
        messages=[{"role": "agent", "text": agent, "at": AT}],
        counters=counters or {},
    )


def flags(result):
    proc = result.session.profile.process
    return proc.roles_confirmed, proc.tools_confirmed


async def test_the_named_lists_are_confirmed(ctx):
    """AC-14.17."""
    one = await turn(confirm_session(ctx), "yes", fake(EXTRACT=[{}], GUIDE=["Q?"]), ctx)
    assert flags(one) == (True, False)
    both = await turn(confirm_session(ctx, focus=(ROLES, TOOLS)), "correct", fake(EXTRACT=[{}], GUIDE=["Q?"]), ctx)
    assert flags(both) == (True, True)
    assert both.session.phase.value == "review"


async def test_cues_decide_without_keys_and_roles_come_first(ctx):
    """AC-14.18."""
    cued = await turn(
        confirm_session(ctx, focus=(), agent="And the systems: SAP. Is that the full list of tools?"),
        "yes",
        fake(EXTRACT=[{}], GUIDE=["Q?"]),
        ctx,
    )
    assert flags(cued) == (False, True)
    plain = await turn(
        confirm_session(ctx, focus=(), agent="Does that look right?"), "yes", fake(EXTRACT=[{}], GUIDE=["Q?"]), ctx
    )
    assert flags(plain) == (True, False)


async def test_nothing_is_confirmed_out_of_place(ctx):
    """AC-14.19."""
    outside = await turn(confirm_session(ctx, phase="review"), "yes", fake(EXTRACT=[{}], GUIDE=["Q?"]), ctx)
    assert flags(outside) == (False, False)
    edit = fake(EXTRACT=[{step_cell_key(1, "roles"): ["Auditor"]}], GUIDE=["Q?"])
    edited = await turn(confirm_session(ctx), "yes", edit, ctx)
    assert flags(edited) == (False, False)
    open_walk = await turn(confirm_session(ctx, closed=False), "yes", fake(EXTRACT=[{}], GUIDE=["Q?"]), ctx)
    assert flags(open_walk) == (False, False)
    many = await turn(
        confirm_session(ctx, counters={"confirm_turns": 40}), "hmm", fake(EXTRACT=[{}], GUIDE=["Q?"]), ctx
    )
    assert flags(many) == (False, False)
