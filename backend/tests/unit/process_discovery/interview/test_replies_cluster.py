"""Tests for reading cluster replies in code (spec 14 §3.7; AC-14.6 to AC-14.12).

Why: placement used to hang on one model token; a plain yes, a no, or a cluster name are now read
by code from the state. What: armed proposals, short yes and no, naming a cluster, the lexicon, a
settled cluster, a yes to a code that no longer resolves, and (refinement R9) a yes that opens a
sentence ("Yes, that cluster fits."), replayed from a live run where it was ignored twice and the
third cluster question became the picker.
"""

from app.models.process_discovery_schemas import Profile
from app.services.process_discovery.domain.scope import keyword_placement
from app.services.process_discovery.interview.replies import Lexicon, cluster_armed, read_cluster_reply
from app.services.process_discovery.llm import CallType
from app.services.process_discovery.profile.mutate import apply_changes, set_cluster
from app.services.process_discovery.profile.shapes import empty_profile

from ..profile.builders import AT
from .helpers import fake, new_session, turn

NAME = "Monthly cost review"


def named_profile(ctx, cluster: str | None = None):
    p = apply_changes(
        empty_profile(),
        {"department": "Finance", "user_function": "Controller", "region": "Europe", "process.name": NAME},
        vocab=ctx.vocab,
        at=AT,
    ).profile
    return set_cluster(p, cluster, decided_by="proposal", vocab=ctx.vocab, at=AT) if cluster else p


def cluster_session(
    ctx,
    code: str | None = "FIN",
    agent="Would you file it under Finance: planning, recording money?",
    confirm: str | None = "cluster",
    rejected=False,
    cluster=None,
):
    proposal = None
    if code:
        proposal = {**keyword_placement("FIN"), "code": code}
    return new_session(
        ctx,
        phase="find",
        profile=Profile.model_validate(named_profile(ctx, cluster)),
        scope={"verdict": None, "scoped_for": NAME},
        placement={"proposal": proposal, "placed_for": NAME, "rejected": rejected},
        last_question={"focus": ["process.cluster"], "proposals": [], "confirm": confirm},
        messages=[{"role": "agent", "text": agent, "at": AT}],
    )


def as_state(session, text):
    state = {
        "profile": session.profile.model_dump(mode="json", by_alias=True),
        "placement": session.placement.model_dump(mode="json"),
        "last_question": session.last_question.model_dump(mode="json"),
        "messages": [
            *(m.model_dump(mode="json") for m in session.messages),
            {"role": "expert", "text": text, "at": AT},
        ],
    }
    return state


async def test_a_short_yes_sets_the_cluster_without_the_model(ctx):
    """AC-14.6."""
    llm = fake(EXTRACT=[{}], GUIDE=["Q?"])
    result = await turn(cluster_session(ctx), "yes", llm, ctx)
    assert result.session.profile.process.cluster.model_dump() == {
        "code": "FIN",
        "name": "Finance",
        "decided_by": "proposal",
    }


async def test_a_short_no_rejects_and_the_picker_follows(ctx):
    """AC-14.7."""
    llm = fake(EXTRACT=[{}, {}], GUIDE=["Which fits?", "Q?"])
    session = cluster_session(ctx)
    first = await turn(session, "no", llm, ctx)
    placement = first.session.placement
    assert placement.rejected is True and placement.proposal is None and placement.placed_for == NAME
    assert first.session.last_question.confirm is None
    assert first.session.last_question.focus == ["process.cluster"]
    guide = llm.calls_of(CallType.GUIDE)[0].messages[0]["content"]
    assert "The expert said no to the proposed cluster." in guide
    assert "- IT & Security:" in guide
    await turn(first.session, "hmm let me think about it", llm, ctx)
    assert llm.calls_of(CallType.CLASSIFY) == []


def test_naming_a_cluster_sets_it(ctx):
    """AC-14.8."""
    lexicon = ctx.lexicon
    state = as_state(cluster_session(ctx), "it and security")
    assert read_cluster_reply(state, "it and security", vocab=ctx.vocab, lexicon=lexicon) == (True, "named", "IT")
    after_rejection = as_state(cluster_session(ctx, code=None, confirm=None, rejected=True), "Finance")
    assert read_cluster_reply(after_rejection, "Finance", vocab=ctx.vocab, lexicon=lexicon) == (True, "named", "FIN")


async def test_naming_a_different_cluster_switches_in_a_turn(ctx):
    """AC-14.8."""
    llm = fake(EXTRACT=[{}], GUIDE=["Q?"])
    result = await turn(cluster_session(ctx), "Procurement", llm, ctx)
    assert result.session.profile.process.cluster.code == "PRO"
    assert result.session.profile.process.cluster.decided_by == "named"


def test_a_settled_cluster_and_the_department_answer_are_left_alone(ctx):
    """AC-14.9."""
    settled = as_state(cluster_session(ctx, cluster="FIN"), "Procurement")
    assert read_cluster_reply(settled, "Procurement", vocab=ctx.vocab, lexicon=ctx.lexicon).verdict is None
    session = new_session(ctx)
    state = as_state(session, "Finance")
    assert read_cluster_reply(state, "Finance", vocab=ctx.vocab, lexicon=ctx.lexicon).verdict is None


def test_arming_needs_the_whole_word_and_the_recorded_question(ctx):
    """AC-14.10."""
    inside = as_state(cluster_session(ctx, code="IT", agent="Do you work with them every month?"), "yes")
    assert cluster_armed(inside, vocab=ctx.vocab) is None
    whole = as_state(cluster_session(ctx, code="IT", agent="Would you file this under IT & Security?"), "yes")
    assert cluster_armed(whole, vocab=ctx.vocab) == "IT"
    unrecorded = as_state(cluster_session(ctx, confirm=None), "yes")
    assert cluster_armed(unrecorded, vocab=ctx.vocab) is None


def test_the_lexicon(ctx, nig_config):
    """AC-14.11."""
    state = as_state(cluster_session(ctx), "x")
    for text in ("ok", "okay", "sure", "fine", "yes it is right but the cluster is wrong for us", "well yes, but"):
        assert read_cluster_reply(state, text, vocab=ctx.vocab, lexicon=ctx.lexicon).verdict is None, text
    for text in ("that's right", "Stimmt!", "yes", "Ja genau"):
        assert read_cluster_reply(state, text, vocab=ctx.vocab, lexicon=ctx.lexicon).verdict is True, text
    lexicon = Lexicon.from_config(nig_config.language)
    assert {"yes", "stimmt", "thats right"} <= lexicon.yes
    assert {"no", "nein"} <= lexicon.no


async def test_a_yes_to_an_unresolvable_code_is_a_rejection(ctx):
    """AC-14.12."""
    llm = fake(EXTRACT=[{}], GUIDE=["Q?"])
    session = cluster_session(ctx, code="ZZ", agent="Would you file it under ZZ?")
    result = await turn(session, "yes", llm, ctx)
    assert result.session.profile.process.cluster.code == ""
    assert result.session.placement.rejected is True
    assert result.session.placement.proposal is None


# --- R9: a yes that opens a sentence (live transcript, replayed) ------------------------------------------

SCOPE = {
    "multi_role": True,
    "multi_system": True,
    "trigger_and_outcome": True,
    "recurring": True,
    "external_consumer": True,
    "reasoning": "several roles",
}
PROPOSE = (
    "The monthly cost review fits under Finance: Planning, recording and reporting money. "
    "Does that fit how you would file it?"
)


async def test_a_yes_opening_a_short_sentence_confirms_the_proposal_in_one_turn(ctx):
    """AC-14.6, AC-14.47 (R9). Replays the live run: context, the name, then "Yes, that cluster fits."

    Before the fix the reply decided nothing, the agent proposed Finance again, the same reply was
    ignored again, and the third cluster question was the picker with the suggestion gone.
    """
    llm = fake(
        EXTRACT=[{"department": "Finance"}, {"user_function": "cost controller"}, {"region": "Europe"}]
        + [{"process.name": "monthly cost review"}, {}],
        GUIDE=["Your role?", "Region?", "Normal week?", PROPOSE, "What starts it?"],
        CLASSIFY=[{"scope": SCOPE}],
    )
    session = new_session(ctx)
    for text in ("I work in Finance.", "I am a cost controller.", "I am based in Europe."):
        session = (await turn(session, text, llm, ctx)).session
    named = await turn(session, "The process is the monthly cost review.", llm, ctx)
    assert named.session.placement.proposal is not None and named.session.placement.proposal.code == "FIN"
    assert named.session.last_question.confirm == "cluster"
    answered = await turn(named.session, "Yes, that cluster fits.", llm, ctx)
    cluster = answered.session.profile.process.cluster
    assert (cluster.code, cluster.decided_by) == ("FIN", "proposal")
    assert answered.session.last_question.focus != ["process.cluster"]


def test_an_opening_yes_needs_a_clean_rest(ctx):
    """AC-14.11 (R9): the yes must open the reply, and the rest must not say no or name another cluster."""
    state = as_state(cluster_session(ctx, agent=PROPOSE), "x")
    for text in ("Yes, that cluster fits.", "Yes. It starts when the month-end close is done.", "Ja, passt so."):
        assert read_cluster_reply(state, text, vocab=ctx.vocab, lexicon=ctx.lexicon).verdict is True, text
    for text in ("Yes, but that is wrong for us", "Yes, though I would say Legal", "well yes, but", "I guess yes."):
        assert read_cluster_reply(state, text, vocab=ctx.vocab, lexicon=ctx.lexicon).verdict is None, text
