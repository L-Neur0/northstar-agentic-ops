"""Behaviour and cost by code: loops, repeats, turn times, stale values, tokens and euros (spec 24 §3.9, §3.10; AC-24.20 to AC-24.22).

Why: these are the product §8 targets a good report can still miss; their counting rules are pinned
here. What: hand-built runs, snapshots and `llm_call` lines. Must not: call a model.
"""

from __future__ import annotations

from eval.evalkit.persona import EVAL_DIR, load_personas
from eval.evalkit.play import PersonaRun, Snapshot
from eval.evalkit.score_behaviour import count_loops, score_behaviour, tokens

from .conftest import make_persona, tiny_data

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


# --- §12 V3, V4: criteria asked and hours computed (AC-24.53, AC-24.54) ----------------------------


def _judgement_persona(disclose: dict | None = None):
    data = tiny_data()
    data["truth"]["steps"][1]["decision_type"] = {"kind": "mix", "evidence": "my call"}
    if disclose is not None:
        data["truth"]["disclose"] = disclose
    return make_persona(**{k: data[k] for k in ("truth",)})


def _captured_run(asks: int, hours: list[str]):
    from eval.evalkit.persona import Persona  # noqa: F401  (type only)

    persona = _judgement_persona()
    run = PersonaRun("x")
    steps = [dict(s) for s in persona.truth.steps]  # captured = the truth, so alignment is exact
    run.session = {"profile": {"process": {"substeps": steps}}}
    run.snapshots = [_snap([{"key": "process.substeps[2].decision_criteria", "asks": asks}])]
    run.report = {"potential": {"steps": [{"hoursPerYear": h} for h in hours]}}
    return persona, run


def test_ac_24_53_criteria_asked():
    """AC-24.53: the mix step's S14 asked once → 100 %; never asked → 0 %; no judgement step → n/a."""
    persona, run = _captured_run(asks=1, hours=["72 h", "96 h"])
    scores = score_behaviour(persona, run, PRICES)
    assert (scores.criteria_asked, scores.criteria_steps) == (1, 1)
    persona, run = _captured_run(asks=0, hours=["72 h", "96 h"])
    scores = score_behaviour(persona, run, PRICES)
    assert (scores.criteria_asked, scores.criteria_steps) == (0, 1)
    plain = score_behaviour(make_persona(), run, PRICES)
    assert plain.criteria_steps == 0


def test_ac_24_54_hours_computed():
    """AC-24.54: a "—" step lowers the share; effort `disclose: never` makes it n/a; no report → n/a."""
    persona, run = _captured_run(asks=1, hours=["72 h", "—"])
    scores = score_behaviour(persona, run, PRICES)
    assert (scores.hours_steps_with_number, scores.hours_steps) == (1, 2)
    never = _judgement_persona({"steps[*].effort": "never"})
    assert score_behaviour(never, run, PRICES).hours_steps == 0
    run.report = None
    assert score_behaviour(persona, run, PRICES).hours_steps == 0


def test_ac_24_53_54_scorecard_rows():
    """The two rows: 100 % passes, below fails, no steps shows n/a and never fails."""
    from eval.evalkit.scorecard import target_rows

    from .test_scorecard import persona_score as make_score

    def rows(**behaviour):
        score = make_score()
        score.behaviour = score.behaviour.model_copy(update=behaviour)
        return {r.name: r for r in target_rows(score)}

    ok = rows(criteria_asked=1, criteria_steps=1, hours_steps_with_number=3, hours_steps=3)
    assert ok["criteria asked"].status == "✓" and ok["hours computed"].status == "✓"
    bad = rows(criteria_asked=0, criteria_steps=1, hours_steps_with_number=0, hours_steps=3)
    assert bad["criteria asked"].fails and bad["hours computed"].fails
    na = rows()
    assert na["criteria asked"].status == "n/a" and not na["criteria asked"].fails
    assert na["hours computed"].status == "n/a"
