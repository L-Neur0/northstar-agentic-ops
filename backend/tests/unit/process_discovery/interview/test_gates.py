"""Tests for the classification gates and the widening machine (spec 14 §3.4, §3.8; AC-14.33 to AC-14.36).

Why: CLASSIFY is paid for only when a verdict for the current name is missing, and the widening
question is bounded per session. What: `needs_scope` / `needs_placement`, `apply_scope_verdict`, the
widening ask target, and the CLASSIFY subject on a widening pass.
"""

from app.models.process_discovery_schemas import Profile
from app.services.process_discovery.domain.scope import build_scope_verdict
from app.services.process_discovery.interview.gates import (
    apply_scope_verdict,
    classification_subject,
    needs_placement,
    needs_scope,
)
from app.services.process_discovery.interview.phases import next_ask
from app.services.process_discovery.llm import CallType
from app.services.process_discovery.profile.mutate import apply_changes, set_cluster
from app.services.process_discovery.profile.proposals import propose_from_idea
from app.services.process_discovery.profile.shapes import empty_profile

from ..profile.builders import AT
from .helpers import fake, new_session, turn

NAME = "Quarterly access review"


def named(ctx, name=NAME):
    return apply_changes(empty_profile(), {"process.name": name}, vocab=ctx.vocab, at=AT).profile


def verdict(label):
    signals = {"process": (1, 1, 1, 1, 1), "borderline": (1, 1, 1, 0, 0), "task": (0, 0, 1, 1, 0)}[label]
    keys = ("multi_role", "multi_system", "trigger_and_outcome", "recurring", "external_consumer")
    return build_scope_verdict({**{k: bool(v) for k, v in zip(keys, signals, strict=True)}, "reasoning": "r"})


def test_the_gates(ctx):
    """AC-14.33."""
    assert not needs_scope({"profile": empty_profile()}, vocab=ctx.vocab)
    idea = propose_from_idea(empty_profile(), NAME, "words", at=AT)
    assert not needs_placement({"profile": idea}, vocab=ctx.vocab)
    fresh = {"profile": named(ctx), "scope": {}, "placement": {}}
    assert needs_scope(fresh, vocab=ctx.vocab) and needs_placement(fresh, vocab=ctx.vocab)
    current = {"profile": named(ctx), "scope": {"scoped_for": NAME}, "placement": {"placed_for": NAME}}
    assert not needs_scope(current, vocab=ctx.vocab) and not needs_placement(current, vocab=ctx.vocab)
    renamed = {**current, "profile": named(ctx, "Access review")}
    assert needs_scope(renamed, vocab=ctx.vocab) and needs_placement(renamed, vocab=ctx.vocab)
    settled = {
        **renamed,
        "profile": set_cluster(named(ctx, "Access review"), "IT", decided_by="picker", vocab=ctx.vocab, at=AT),
    }
    assert not needs_placement(settled, vocab=ctx.vocab)
    widening = {**current, "scope": {"scoped_for": NAME, "awaiting_widening": True}}
    assert needs_scope(widening, vocab=ctx.vocab)


def test_the_widening_machine(ctx):
    """AC-14.34."""
    scope, counters = apply_scope_verdict({}, {"widening_count": 0}, verdict("borderline"), NAME)
    assert scope["awaiting_widening"] is True and counters["widening_count"] == 1
    scope, counters = apply_scope_verdict(scope, counters, verdict("task"), NAME)
    assert scope["awaiting_widening"] is False and scope["overridden"] is True and scope["widening_asked"] is True
    scope, counters = apply_scope_verdict(scope, counters, verdict("task"), "Renamed")
    assert scope["awaiting_widening"] is True and counters["widening_count"] == 2
    scope, counters = apply_scope_verdict(scope, counters, verdict("process"), "Renamed")
    assert scope["awaiting_widening"] is False and scope["overridden"] is True
    scope, counters = apply_scope_verdict(scope, counters, verdict("task"), "Third name")
    assert scope["awaiting_widening"] is False and counters["widening_count"] == 2
    process, _ = apply_scope_verdict({}, {}, verdict("process"), NAME)
    assert process["awaiting_widening"] is False and process["widening_asked"] is False


async def test_the_widening_question_is_asked_even_when_the_phase_moved_on(ctx):
    """AC-14.35."""
    from app.services.process_discovery.domain.scope import keyword_placement

    profile = apply_changes(
        empty_profile(),
        {"department": "IT", "user_function": "Analyst", "region": "Europe", "process.name": "Password reset"},
        vocab=ctx.vocab,
        at=AT,
    ).profile
    session = new_session(
        ctx,
        phase="find",
        profile=Profile.model_validate(profile),
        placement={"proposal": keyword_placement("IT"), "placed_for": "Password reset"},
        last_question={"focus": ["process.cluster"], "confirm": "cluster"},
        messages=[{"role": "agent", "text": "Would you file it under IT & Security?", "at": AT}],
    )
    llm = fake(
        EXTRACT=[{}],
        CLASSIFY=[
            {
                "scope": {
                    "multi_role": False,
                    "multi_system": False,
                    "trigger_and_outcome": True,
                    "recurring": True,
                    "external_consumer": False,
                    "reasoning": "one person",
                }
            }
        ],
        GUIDE=["Who depends on it?"],
    )
    result = await turn(session, "yes", llm, ctx)
    assert result.session.profile.process.cluster.code == "IT"
    assert result.session.scope.awaiting_widening is True
    assert result.session.phase.value == "boundaries"
    assert result.session.last_question.focus == []
    assert "Ask ONE widening question" in llm.calls_of(CallType.GUIDE)[0].messages[0]["content"]
    state = {
        "profile": result.session.profile.model_dump(by_alias=True),
        "phase": "boundaries",
        "scope": {"awaiting_widening": True},
    }
    assert next_ask(state, vocab=ctx.vocab).kind == "widening"


def test_the_widening_subject(ctx):
    """AC-14.36."""
    state = {
        "profile": named(ctx),
        "scope": {"awaiting_widening": True},
        "messages": [
            {"role": "agent", "text": "Who uses the result?"},
            {"role": "expert", "text": "The audit team relies on it"},
        ],
    }
    subject = classification_subject(state, vocab=ctx.vocab)
    assert (
        subject
        == f"{NAME}\n\nWidening question asked: Who uses the result?\n\nFollow-up answer: The audit team relies on it"
    )
    assert classification_subject({**state, "scope": {}}, vocab=ctx.vocab) == NAME
