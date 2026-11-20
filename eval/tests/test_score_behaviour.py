"""Behaviour and cost by code: loops, repeats, turn times, stale values, tokens and euros (spec 24 §3.9, §3.10; AC-24.20 to AC-24.22).

Why: these are the product §8 targets a good report can still miss; their counting rules are pinned
here. What: hand-built runs, snapshots and `llm_call` lines. Must not: call a model.
"""

from __future__ import annotations

from eval.evalkit.persona import EVAL_DIR, load_personas
from eval.evalkit.play import PersonaRun, Snapshot
from eval.evalkit.score_behaviour import count_loops, score_behaviour, tokens

from .conftest import make_persona

PRICES = {"app-chat": {"in": 1.25, "out": 10.0}}


def _snap(views):
    return Snapshot(
        n=1,
        event="message",
        phase="steps",
        score=0,
        filledPoints=0,
        totalPoints=0,
        finish={},
        profile={},
        fieldViews=views,
    )


def test_ac_24_20_loops():
    assert count_loops([_snap([{"key": "process.volume", "asks": 6}])], [])[0] == 1
    assert count_loops([_snap([{"key": "process.volume", "asks": 5}])], [])[0] == 0
    assert count_loops([_snap([{"key": "process.substeps[1].effort", "asks": 4}])], [])[0] == 1
    assert count_loops([], ["Which system?", "which system", "Which system?"])[0] == 1
    assert count_loops([], ["a", "a", "b", "a"])[0] == 0


def test_ac_24_20_turn_times_count_only_uncached_turns():
    run = PersonaRun("x")
    run.turns = [
        {"event": "message", "wall_ms": 4000, "uncached": True},
        {"event": "message", "wall_ms": 90000, "uncached": False},
        {"event": "message", "wall_ms": 6000, "uncached": True},
    ]
    scores = score_behaviour(make_persona(), run, PRICES)
    assert (scores.turn_median_s, scores.turn_max_s) == (5.0, 6.0)
    run.turns = [{"event": "message", "wall_ms": 4000, "uncached": False}]
    assert score_behaviour(make_persona(), run, PRICES).turn_median_s is None


def test_ac_24_21_tokens_split_and_priced():
    logs = [
        {
            "event": "llm_call",
            "call_type": "GUIDE",
            "deployment": "app-chat",
            "outcome": "ok",
            "prompt_tokens": 1_000_000,
            "completion_tokens": 100_000,
        },
        {
            "event": "llm_call",
            "call_type": "EXTRACT",
            "deployment": "app-chat",
            "outcome": "cache_hit",
            "prompt_tokens": 0,
            "completion_tokens": 0,
        },
        {
            "event": "llm_call",
            "call_type": "EXPERT",
            "deployment": "eval-expert",
            "outcome": "ok",
            "prompt_tokens": 10,
            "completion_tokens": 5,
        },
        {
            "event": "llm_call",
            "call_type": "JUDGE",
            "deployment": "app-chat",
            "outcome": "ok",
            "prompt_tokens": 2000,
            "completion_tokens": 0,
        },
    ]
    app = tokens(logs, PRICES, None, {"EXPERT", "JUDGE"})
    assert (app.tokens_in, app.tokens_out, app.cache_hits, app.calls, app.euros) == (1_000_000, 100_000, 1, 2, 2.25)
    expert = tokens(logs, PRICES, {"EXPERT"}, set())
    assert expert.tokens_in == 10 and expert.euros is None  # eval-expert missing from the prices: tokens only
    assert tokens(logs, PRICES, {"JUDGE"}, set()).euros == 0.0025


def test_ac_24_22_a_stale_volume_is_counted(company):
    p04 = next(p for p in load_personas(EVAL_DIR / "personas", quick=False, company=company) if p.id.startswith("p04"))
    run = PersonaRun("p04")
    run.session = {
        "profile": {"process": {"volume": {"count": None, "period": "", "raw": "twice a year"}, "substeps": []}}
    }
    assert score_behaviour(p04, run, PRICES).stale_kept == 1
    run.session = {"profile": {"process": {"volume": {"count": 1, "period": "quarter", "raw": "every quarter"}}}}
    assert score_behaviour(p04, run, PRICES).stale_kept == 0
