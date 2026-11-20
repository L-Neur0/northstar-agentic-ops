"""Tests for steering inside real turns: length, the guide prompts, the fallbacks and the log (spec 14 §3.15; AC-14.76 to AC-14.78, AC-14.80).

Why: steering must keep the find phase short (a recommendation by find question 6 at the latest),
tell the guide exactly what to ask (the steered names and only the missing signals; the code's why
lines for the recommendation), fall back to plain code-built questions, and log no candidate name.
What: two scripted experts (one answers every steering question, one ignores them), the GUIDE
system prompt for `steer` and `recommend`, the fallbacks of item 13, and a sentinel log check.
The rule list is shared with `test_prompts_guide.py` (AC-14.58); spec 14 §3.15 items 10, 12–15.
"""

import logging
from typing import Any

from app.models.process_discovery_schemas import Profile
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.interview import steering as st
from app.services.process_discovery.interview.graph import build_graph
from app.services.process_discovery.interview.nodes import _fallback  # pyright: ignore[reportPrivateUsage]
from app.services.process_discovery.interview.prompts.guide import RULES, guide_system
from app.services.process_discovery.interview.turn import TurnResult, run_turn
from app.services.process_discovery.interview.types import Ask
from app.services.process_discovery.llm import CallType
from app.services.process_discovery.profile.mutate import apply_changes
from app.services.process_discovery.profile.scoring import FinishCheck, score
from app.services.process_discovery.profile.shapes import empty_profile

from ..profile.builders import AT, context_changes
from .helpers import NOW, new_session

LOCKED = FinishCheck(False, "below_gate", False)
BANNED = ("noted", "saved", "recorded", "trouble", "error", "fail")
NAMES = ("the monthly cost review", "chasing site managers", "booking travel")
ANSWERS: dict[tuple[str, ...], dict[str, dict[str, str]]] = {
    ("runs", "time"): {
        NAMES[0]: {"runs": "every month", "time": "about 3 days"},
        NAMES[1]: {"runs": "every week", "time": "2 hours"},
        NAMES[2]: {"runs": "twice a month", "time": "an hour"},
    },
    ("people",): {NAMES[0]: {"people": "6 of us"}, NAMES[1]: {"people": "about 10"}, NAMES[2]: {"people": "just me"}},
    ("inputs",): {
        NAMES[0]: {"inputs": "site spreadsheets by e-mail"},
        NAMES[1]: {"inputs": "phone calls"},
        NAMES[2]: {"inputs": "the booking portal"},
    },
}


def find_session(ctx, **parts: Any):
    profile = apply_changes(empty_profile(), context_changes(), vocab=ctx.vocab, at=AT).profile
    return new_session(ctx, phase="find", profile=Profile.model_validate(profile), **parts)


async def play_find(ctx, answer_steering: bool) -> list[TurnResult]:
    """Find question 1 is answered with nothing, question 2 with three candidates, then the steering questions."""
    llm = FakeLLM()
    graph = build_graph(llm, ctx)
    session = find_session(ctx)
    results: list[TurnResult] = []
    for number in range(1, 8):
        focus = tuple(session.last_question.focus)
        extract: dict[str, Any] = {}
        if number == 2:
            extract = {"candidates": [{"name": n, "words": "I do it"} for n in NAMES]}
        elif answer_steering and focus and focus[0].startswith("steer:"):
            signals = tuple(k.removeprefix("steer:") for k in focus)
            group = next(v for k, v in ANSWERS.items() if set(signals) <= set(k))
            extract = {"candidate_signals": [{"name": n, **group[n]} for n in NAMES]}
        llm.add(CallType.EXTRACT, extract)
        llm.add(CallType.GUIDE, "Next question?")
        result = await run_turn(session, f"answer {number}", llm=llm, graph=graph, ctx=ctx, now=NOW)
        results.append(result)
        session = result.session
    return results


async def test_a_cooperative_expert_gets_the_recommendation_by_find_question_6(ctx):
    """AC-14.76."""
    results = await play_find(ctx, answer_steering=True)
    asks = [r.session.last_question for r in results]
    # the question asked after reply k is find question k + 1
    kinds = ["recommend" if q.confirm == "recommendation" else (q.focus[0] if q.focus else "") for q in asks]
    assert kinds[1:4] == ["steer:runs", "steer:people", "steer:inputs"]
    assert "recommend" in kinds[:5]
    assert results[4].session.steering.recommended_id == "c1"
    assert results[4].session.steering.questions == 3


async def test_an_expert_who_ignores_steering_reaches_direct_with_three_steering_asks(ctx):
    """AC-14.76."""
    results = await play_find(ctx, answer_steering=False)
    last = results[-1].session
    assert last.steering.questions <= ctx.steering.max_questions
    assert last.counters.find_turns >= 6
    steer_asks = [
        r
        for r in results
        if r.session.last_question.focus[:1] and r.session.last_question.focus[0].startswith("steer:")
    ]
    assert len(steer_asks) <= 3
    assert last.counters.field_asks.get("steer:runs") is None


def steer_state(ctx, **update: Any) -> dict[str, Any]:
    cfg = ctx.steering
    s = st.add_candidates(st.read_steering(None), [{"name": n, "words": "w"} for n in NAMES])
    s = st.apply_signals(s, [{"name": n, "runs": "monthly", "time": "a day"} for n in NAMES], cfg)
    s = st.rank({**s, "status": "collecting", **update}, cfg)
    profile = apply_changes(empty_profile(), context_changes(), vocab=ctx.vocab, at=AT).profile
    return {
        "profile": profile,
        "phase": "find",
        "score": score(profile, vocab=ctx.vocab)._asdict(),
        "counters": {"find_turns": 3},
        "steering": s,
    }


def test_the_steer_prompt_names_every_candidate_and_only_the_missing_signals(ctx):
    """AC-14.77."""
    state = steer_state(ctx)
    text = guide_system(state, Ask("steer", ("steer:people",)), LOCKED, vocab=ctx.vocab)
    this_turn = text.split("THIS TURN:", 1)[1].split("STILL MISSING:", 1)[0]
    assert all(n in this_turn for n in NAMES)
    assert "how many people" in this_turn
    assert "how often" not in this_turn and "files or systems" not in this_turn
    assert "Stop opening new ground" not in text


def test_the_recommend_prompt_holds_the_steering_block_and_its_rules(ctx):
    """AC-14.77."""
    cfg = ctx.steering
    state = steer_state(ctx, status="ranked")
    raw = [
        {"name": n, "people": p, "inputs": i}
        for n, p, i in zip(NAMES, ("6", "10", "just me"), ("excel", "calls", "portal"), strict=True)
    ]
    state["steering"] = st.advance(
        st.apply_signals(state["steering"], raw, cfg), phase="find", name_counts=False, posture="open", cfg=cfg
    )
    text = guide_system(state, Ask("recommend", ("process.name",), "recommend"), LOCKED, vocab=ctx.vocab)
    assert "STEERING" in text
    top = st.ranked(state["steering"])[0]
    assert st.why_line(top) in text and "(recommended)" in text
    assert "the expert decides" in text and "never rank" in text
    assert "except the numbers in the STEERING block" in RULES


def test_steering_fallbacks(ctx):
    """AC-14.78."""
    cfg = ctx.steering
    state = steer_state(ctx)
    steer = _fallback(state, Ask("steer", ("steer:people",)), ctx.vocab)
    assert steer.startswith("To pick the best one to map first:") and all(n in steer for n in NAMES)
    ranked = st.advance(
        st.apply_signals(state["steering"], [{"name": n, "people": "4", "inputs": "excel"} for n in NAMES], cfg),
        phase="find",
        name_counts=False,
        posture="open",
        cfg=cfg,
    )
    state = {**state, "steering": ranked}
    top = st.ranked(ranked)[0]
    recommend = _fallback(state, Ask("recommend", ("process.name",), "recommend"), ctx.vocab)
    assert recommend.startswith(f"Based on what you told me, {top['name']} looks like the best one to map first: ")
    assert recommend.endswith("Shall we map it? Say yes, or name another one.")
    pick = _fallback(state, Ask("recommend", ("process.name",), "pick"), ctx.vocab)
    assert pick.startswith("Which of these would you like to map now?")
    assert all(st.why_line(c) in pick for c in st.ranked(ranked))
    for text in (steer, recommend, pick):
        assert not any(word in text.lower() for word in BANNED), text


async def test_a_failed_guide_on_a_steer_turn_uses_the_fallback(ctx):
    """AC-14.78."""
    llm = FakeLLM()
    llm.add(CallType.EXTRACT, {"candidates": [{"name": n, "words": "w"} for n in NAMES]})
    llm.add(CallType.GUIDE, "   ")
    result = await run_turn(find_session(ctx), "a few things", llm=llm, graph=build_graph(llm, ctx), ctx=ctx, now=NOW)
    assert result.reply.startswith("To pick the best one to map first:")


async def test_the_log_carries_the_steer_object_and_no_names(ctx, caplog):
    """AC-14.80."""
    caplog.set_level(logging.DEBUG)
    sentinel = "QQ-SENTINEL-QQ"
    llm = FakeLLM()
    llm.add(
        CallType.EXTRACT,
        {"candidates": [{"name": f"{sentinel} {i}", "words": sentinel} for i in range(3)]},
    )
    llm.add(CallType.GUIDE, "Q?")
    await run_turn(find_session(ctx), "x", llm=llm, graph=build_graph(llm, ctx), ctx=ctx, now=NOW)
    [line] = [r for r in caplog.records if r.getMessage() == "interview_turn"]
    steer = line.__dict__["steer"]
    assert steer == {"status": "collecting", "questions": 1, "candidates": 3, "known": [0, 0, 0], "recommended": None}
    for record in caplog.records:
        assert sentinel not in str(record.__dict__)
