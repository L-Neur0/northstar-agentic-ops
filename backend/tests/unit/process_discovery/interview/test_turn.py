"""Tests for the turn entry points: immutability, saved state, the turn guard, the budget and the welcome (spec 14 §3.2, §3.12; AC-14.51 to AC-14.53, AC-14.56).

Why: the service only loads, calls `run_turn` and saves, so `run_turn` must return a new session,
keep a rejection and an emptied verdict as they are, end within the turn timeout with a question,
and stop (saving nothing) when the daily budget refuses EXTRACT. What: those four properties and
the fixed welcome message.
"""

import asyncio
import copy
import time

import pytest

from app.models.process_discovery_schemas import ScopeState
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.interview.turn import apply_state, hydrate, welcome
from app.services.process_discovery.llm import CallType, LLMBudgetExceededError

from .helpers import NOW, fake, make_context, new_session, turn


async def test_run_turn_returns_a_new_session(ctx):
    """AC-14.51."""
    session = new_session(ctx)
    before = copy.deepcopy(session.model_dump())
    result = await turn(session, "Finance", fake(EXTRACT=[{"department": "Finance"}], GUIDE=["Q?"]), ctx)
    assert session.model_dump() == before
    assert result.session is not session
    assert result.session.profile.department == "Finance"
    assert [m.role.value for m in result.session.messages[-2:]] == ["expert", "agent"]


def test_an_emptied_verdict_and_a_rejection_are_saved_as_such(ctx):
    """AC-14.51."""
    session = new_session(
        ctx, scope={"verdict": {"verdict": "task", "score": 1, "signals": {}, "reasoning": ""}, "scoped_for": "x"}
    )
    state = hydrate(session, "", NOW)
    state["scope"] = {**state.get("scope", {}), "verdict": {}}
    state["placement"] = {"proposal": None, "placed_for": "x", "rejected": True}
    saved = apply_state(session, state)
    assert saved.scope == ScopeState(verdict=None, scoped_for="x")
    assert saved.placement.proposal is None and saved.placement.placed_for == "x"


class SlowLLM(FakeLLM):
    async def generate_json(self, call_type, messages, *, max_tokens=None):
        await asyncio.sleep(5)
        return {}

    async def generate_text(self, call_type, messages, *, max_tokens=None):
        await asyncio.sleep(5)
        return "late"


async def test_the_turn_guard(nig_config, nig_vocabulary):
    """AC-14.52: a 2 s turn ends within 3 s with the fallback and the counters charged."""
    ctx = make_context(nig_config, nig_vocabulary, turn_timeout_seconds=2)
    started = time.monotonic()
    result = await turn(new_session(ctx), "Finance", SlowLLM(), ctx)
    assert time.monotonic() - started < 3
    assert result.reply == "Which department are you in?"
    assert result.session.counters.field_asks == {"department": 1}


async def test_the_budget(ctx):
    """AC-14.53."""
    session = new_session(ctx)
    before = session.model_dump()
    with pytest.raises(LLMBudgetExceededError):
        await turn(session, "Finance", fake(EXTRACT=[LLMBudgetExceededError("refused")]), ctx)
    assert session.model_dump() == before
    llm = fake(EXTRACT=[{"department": "Finance"}], GUIDE=[LLMBudgetExceededError("refused")])
    result = await turn(session, "Finance", llm, ctx)
    assert result.reply == "What is your own role in that department?"


def test_the_welcome(ctx):
    """AC-14.56."""
    text, question = welcome("Sam", ctx)
    assert text.startswith("Hi Sam!")
    assert ctx.product_name in text
    assert "I'm the AI Use Case Discovery Agent." in text  # renamed 2026-11-21
    assert "document" in text
    assert "describe the work, not you" in text  # §3.20 O1
    assert "transformation team may read this conversation" in text
    assert text.endswith("Which department are you in?")
    assert question.focus == ["department"]
    assert welcome(None, ctx)[0].startswith("Hi!")
    assert CallType.GUIDE
