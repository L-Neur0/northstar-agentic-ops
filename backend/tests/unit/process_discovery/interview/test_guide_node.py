"""Tests for the GUIDE fallback: a turn always ends with a question (spec 14 §3.10; AC-14.49).

Why: if the guide call fails, the expert still gets a plain question built by code for the same
ask target, and the work of EXTRACT is kept. What: raising, whitespace-only and timed-out GUIDE
calls through a real turn, and the fallback of every ask kind (none says "noted", "saved",
"recorded" or mentions a failure).
"""

import asyncio

import pytest

from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.domain.scope import keyword_placement
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.interview.nodes import _fallback  # pyright: ignore[reportPrivateUsage]
from app.services.process_discovery.interview.types import Ask
from app.services.process_discovery.llm import CallType, LLMUnavailableError
from app.services.process_discovery.profile.proposals import FieldProposal, ProposalDiff, apply_proposals

from ..profile.builders import AT, cost_review_profile
from .helpers import fake, make_context, new_session, turn
from .sessions import BOUNDARIES, MEASURE, profile_with

BANNED = ("noted", "saved", "recorded", "trouble", "error", "fail")


class SlowGuide(FakeLLM):
    async def generate_text(self, call_type, messages, *, max_tokens=None):
        await asyncio.sleep(5)
        return "too late"


@pytest.mark.parametrize("reply", [LLMUnavailableError(500), "   "])
async def test_a_failed_guide_gives_the_fallback_and_keeps_the_extract(ctx, reply):
    """AC-14.49."""
    llm = fake(EXTRACT=[{"department": "Finance"}], GUIDE=[reply])
    result = await turn(new_session(ctx), "Finance", llm, ctx)
    assert result.reply == "What is your own role in that department?"
    assert result.session.profile.department == "Finance"


async def test_a_timed_out_guide_gives_the_fallback(nig_config, nig_vocabulary):
    """AC-14.49."""
    ctx = make_context(nig_config, nig_vocabulary, turn_timeout_seconds=2)
    llm = SlowGuide({CallType.EXTRACT: [{}]})
    result = await turn(new_session(ctx), "", llm, ctx)
    assert result.reply == "Which department are you in?"


def fallback_cases(ctx):
    closed = cost_review_profile(ctx.vocab, steps=2)
    walk = profile_with(ctx, *BOUNDARIES, *MEASURE, steps=2)
    proposed = apply_proposals(
        profile_with(ctx),
        ProposalDiff("d1", fields=(FieldProposal("process.trigger", "Month end", "q"),)),
        vocab=ctx.vocab,
        at=AT,
    ).profile
    placement = {"proposal": keyword_placement("FIN"), "placed_for": "x"}
    borderline = {
        "verdict": {
            "verdict": "borderline",
            "score": 3,
            "signals": {
                "multi_role": True,
                "multi_system": True,
                "trigger_and_outcome": True,
                "recurring": False,
                "external_consumer": False,
            },
            "reasoning": "",
        }
    }
    return [
        ({"profile": walk}, Ask("field", ("process.trigger",)), "What starts this process off?"),
        (
            {"profile": walk},
            Ask("cell", (step_cell_key(1, "goal"),)),
            "For step 1: What has to be true for this step to be done?",
        ),
        (
            {"profile": proposed},
            Ask("proposals", ("process.trigger",)),
            "I read this in your document: Trigger: Month end. Is that right? Say yes, or tell me what is different.",
        ),
        (
            {"profile": walk, "placement": placement},
            Ask("cluster", ("process.cluster",), "propose"),
            "Would you file Monthly cost review under Finance:",
        ),
        (
            {"profile": walk},
            Ask("cluster", ("process.cluster",), "picker"),
            "Which of these fits Monthly cost review best?",
        ),
        (
            {"profile": closed},
            Ask("rollups", ("process.all_roles", "process.all_tools")),
            "These are the roles across the steps: Controller. And the systems: SAP. Is that right?",
        ),
        ({"profile": walk, "scope": borderline}, Ask("widening"), "How often does this come round?"),
        (
            {"profile": walk},
            Ask("wrap_up", ("process.business_pain",)),
            "We still need: Business pain. Could you tell me about business pain?",
        ),
    ]


def test_every_ask_kind_has_a_fallback(ctx):
    """AC-14.49."""
    for state, ask, expected in fallback_cases(ctx):
        text = _fallback(state, ask, ctx.vocab)
        assert text.startswith(expected), (ask.kind, text)
        assert not any(word in text.lower() for word in BANNED), text
    ready = cost_review_profile(ctx.vocab, steps=2)
    ready["process"]["roles_confirmed"] = ready["process"]["tools_confirmed"] = True
    assert (
        _fallback({"profile": ready}, Ask("wrap_up"), ctx.vocab)
        == "Is there anything you would like to correct before you press Finish?"
    )
