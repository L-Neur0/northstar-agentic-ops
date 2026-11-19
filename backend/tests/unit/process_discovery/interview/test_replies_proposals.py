"""Tests for confirming document proposals in the chat (spec 14 §3.7; AC-14.13 to AC-14.16).

Why: the expert has the last word on what a document proposed; a plain yes confirms exactly the
values the last question named, a no rejects them, and a correction outranks the yes.
What: turns on a session holding three proposals, two of them named in the last question.
"""

from app.models.process_discovery_schemas import Profile
from app.services.process_discovery.profile.proposals import FieldProposal, ProposalDiff, apply_proposals

from ..profile.builders import AT, context_changes
from .helpers import fake, new_session, turn

NAME = "Monthly cost review"
TRIGGER, END, PAIN = "process.trigger", "process.end_result", "process.business_pain"


def proposal_session(ctx):
    from app.services.process_discovery.profile.mutate import apply_changes, set_cluster
    from app.services.process_discovery.profile.shapes import empty_profile

    p = apply_changes(empty_profile(), {**context_changes(), "process.name": NAME}, vocab=ctx.vocab, at=AT).profile
    p = set_cluster(p, "FIN", decided_by="proposal", vocab=ctx.vocab, at=AT)
    diff = ProposalDiff(
        "d1",
        fields=(
            FieldProposal(TRIGGER, "Month-end close is completed", "starts once month-end close is completed"),
            FieldProposal(END, "The monthly cost report", "ends with the monthly cost report"),
            FieldProposal(PAIN, "Chasing explanations", "chasing explanations"),
        ),
    )
    p = apply_proposals(p, diff, vocab=ctx.vocab, at=AT).profile
    return new_session(
        ctx,
        phase="boundaries",
        profile=Profile.model_validate(p),
        scope={"verdict": None, "scoped_for": NAME},
        placement={"proposal": None, "placed_for": NAME},
        last_question={"focus": [], "proposals": [TRIGGER, END], "confirm": None},
        messages=[
            {
                "role": "agent",
                "text": "Your procedure says it starts at month-end close and ends with the cost report. Right?",
                "at": AT,
            }
        ],
    )


def status(session, key):
    meta = session.profile.meta.get(key)
    return meta.status if meta else None


async def test_a_short_yes_confirms_exactly_the_named_proposals(ctx):
    """AC-14.13."""
    result = await turn(proposal_session(ctx), "yes", fake(EXTRACT=[{}], GUIDE=["Q?"]), ctx)
    assert (status(result.session, TRIGGER), status(result.session, END), status(result.session, PAIN)) == (
        "confirmed",
        "confirmed",
        "proposed",
    )


async def test_a_short_no_rejects_exactly_the_named_proposals(ctx):
    """AC-14.14."""
    result = await turn(proposal_session(ctx), "no", fake(EXTRACT=[{}], GUIDE=["Q?"]), ctx)
    proc = result.session.profile.process
    assert (proc.trigger, proc.end_result) == ("", "")
    assert TRIGGER not in result.session.profile.meta and END not in result.session.profile.meta
    assert status(result.session, PAIN) == "proposed"


async def test_a_correction_in_the_same_turn_outranks_the_yes(ctx):
    """AC-14.15."""
    llm = fake(EXTRACT=[{TRIGGER: "The ledger is closed on day 3"}], GUIDE=["Q?"])
    result = await turn(proposal_session(ctx), "yes", llm, ctx)
    meta = result.session.profile.meta
    assert result.session.profile.process.trigger == "The ledger is closed on day 3"
    assert (meta[TRIGGER].source, meta[TRIGGER].status) == ("expert", "confirmed")
    assert (meta[END].source, meta[END].status) == ("document", "confirmed")


async def test_a_longer_reply_leaves_them_waiting_and_charges_each(ctx):
    """AC-14.16."""
    session = proposal_session(ctx)
    result = await turn(
        session, "well, it depends on the month really, let me think", fake(EXTRACT=[{}], GUIDE=["Q?"]), ctx
    )
    assert status(result.session, TRIGGER) == "proposed"
    assert result.session.counters.field_asks == {TRIGGER: 1, END: 1}
