"""Tests for the CLASSIFY step: failures, thresholds and the one-off note (spec 14 §3.10; AC-14.37, AC-14.38).

Why: a failed classifier is not evidence about the expert's work, so the turn continues with the
neutral verdict; placement thresholds come from settings; the one-off note is said once.
What: a failing CLASSIFY, a confidence under a raised threshold, and the ONE-OFF block on the
turn the verdict was produced and not after.
"""

import logging

from app.models.process_discovery_schemas import Profile
from app.services.process_discovery.llm import CallType, LLMUnavailableError
from app.services.process_discovery.profile.mutate import apply_changes
from app.services.process_discovery.profile.shapes import empty_profile

from ..profile.builders import AT, context_changes
from .helpers import fake, make_context, new_session, turn

NAME = "Quarterly access review"


def find_session(ctx):
    p = apply_changes(empty_profile(), context_changes(), vocab=ctx.vocab, at=AT).profile
    return new_session(ctx, phase="find", profile=Profile.model_validate(p))


async def test_a_failed_classify_gives_the_neutral_verdict(ctx):
    """AC-14.37."""
    llm = fake(EXTRACT=[{"process.name": NAME}], CLASSIFY=[LLMUnavailableError(503)], GUIDE=["Q?"])
    result = await turn(find_session(ctx), "the quarterly access review", llm, ctx)
    scope, placement = result.session.scope, result.session.placement
    assert scope.verdict is not None and (scope.verdict.verdict, scope.verdict.score) == ("borderline", 0)
    assert scope.scoped_for == NAME and placement.placed_for == NAME
    assert placement.proposal is not None and placement.proposal.code == "UNKNOWN"
    assert result.reply == "Q?"


async def test_thresholds_come_from_settings_and_raw_confidence_is_logged(nig_config, nig_vocabulary, caplog):
    """AC-14.37."""
    caplog.set_level(logging.INFO, logger="app.interview")
    ctx = make_context(nig_config, nig_vocabulary, placement_min_confidence=0.9)
    classify = {
        "scope": {
            "multi_role": True,
            "multi_system": True,
            "trigger_and_outcome": True,
            "recurring": True,
            "external_consumer": True,
            "reasoning": "r",
        },
        "placement": {
            "code": "IT",
            "confidence": 0.8,
            "rationale": "r",
            "runner_up": None,
            "runner_up_confidence": None,
        },
    }
    llm = fake(EXTRACT=[{"process.name": NAME}], CLASSIFY=[classify], GUIDE=["Q?"])
    result = await turn(find_session(ctx), "x", llm, ctx)
    assert result.session.placement.proposal is not None
    assert result.session.placement.proposal.code == "UNKNOWN"
    assert result.session.placement.proposal.raw_confidence == 0.8
    line = [r for r in caplog.records if r.getMessage() == "interview_turn"][-1]
    assert line.classify == {"halves": ["scope", "placement"], "keyword_hit": False, "raw_confidence": 0.8}  # type: ignore[attr-defined]


async def test_the_one_off_block_is_rendered_only_on_the_classifying_turn(ctx):
    """AC-14.38."""
    one_off = {
        "scope": {
            "multi_role": True,
            "multi_system": True,
            "trigger_and_outcome": True,
            "recurring": False,
            "external_consumer": True,
            "reasoning": "a migration",
        },
    }  # "crm" is a cluster keyword, so only the scope half is asked
    llm = fake(EXTRACT=[{"process.name": "CRM migration"}, {}], CLASSIFY=[one_off], GUIDE=["Q1?", "Q2?"])
    first = await turn(find_session(ctx), "we migrated the CRM", llm, ctx)
    await turn(first.session, "hmm", llm, ctx)
    guides = [c.messages[0]["content"] for c in llm.calls_of(CallType.GUIDE)]
    assert "ONE-OFF:" in guides[0]
    assert "ONE-OFF:" not in guides[1]
