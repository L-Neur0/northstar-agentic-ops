"""Tests for the expert's choice after the recommendation, and for steering that ends (spec 14 §3.15 items 7–9; AC-14.72 to AC-14.75).

Why: the agent recommends, the expert decides. A plain yes to the recommendation must name the
process without waiting on a model token; a no must open the list; another candidate's name must
win; and once a process is named, steering stops and what was learned stays on the ideas.
What: real turns over a session whose steering is ranked on Example 1 of §3.15 (or still
collecting), with a scripted EXTRACT, GUIDE and CLASSIFY.
"""

from typing import Any

from app.models.process_discovery_schemas import Profile
from app.services.process_discovery.interview import steering as st
from app.services.process_discovery.llm import CallType
from app.services.process_discovery.profile.mutate import apply_changes
from app.services.process_discovery.profile.shapes import empty_profile, meta_for

from ..profile.builders import AT, context_changes
from .helpers import fake, new_session, turn

EXAMPLE = [
    ("the monthly cost review", "every month", "about 3 days", "6 of us", "site spreadsheets by e-mail"),
    ("chasing site managers", "every week", "2 hours", "about 10 site managers", "phone calls"),
    ("booking travel", "twice a month", "an hour", "just me", "the online booking portal"),
]
RECOMMEND = (
    "Based on what you told me, the monthly cost review looks like the best one to map first: about 288 hours a "
    "year, 6 people, digital inputs. Shall we map it?"
)
SCOPE = {
    "multi_role": True,
    "multi_system": True,
    "trigger_and_outcome": True,
    "recurring": True,
    "external_consumer": True,
    "reasoning": "several roles",
}
CLASSIFY = {
    "scope": SCOPE,
    "placement": {"code": "FIN", "confidence": 0.9, "rationale": "r", "runner_up": None, "runner_up_confidence": None},
}
SCOPE_ONLY = {"scope": SCOPE}  # "cost" is a keyword of Finance, so only the scope half is asked


def steering(ctx, *, status="ranked", signals=True, **update: Any) -> dict[str, Any]:
    cfg = ctx.steering
    state = st.add_candidates(st.read_steering(None), [{"name": row[0], "words": "w"} for row in EXAMPLE])
    if signals:
        raw = [{"name": n, "runs": r, "time": t, "people": p, "inputs": i} for n, r, t, p, i in EXAMPLE]
        state = st.apply_signals(state, raw, cfg)
    state = st.rank({**state, "status": status}, cfg)
    top = st.recommendation(state, cfg)
    return {**state, "recommended_id": top["id"] if top else None, **update}


def find_session(ctx, steer: dict[str, Any], *, find_turns=5, confirm: str | None = "recommendation", agent=RECOMMEND):
    profile = apply_changes(empty_profile(), context_changes(), vocab=ctx.vocab, at=AT).profile
    return new_session(
        ctx,
        phase="find",
        profile=Profile.model_validate(profile),
        counters={"find_turns": find_turns},
        steering=steer,
        last_question={"focus": ["process.name"], "proposals": [], "confirm": confirm},
        messages=[{"role": "agent", "text": agent, "at": AT}],
    )


async def test_a_short_yes_names_the_recommended_process(ctx):
    """AC-14.72."""
    llm = fake(EXTRACT=[{}], CLASSIFY=[SCOPE_ONLY], GUIDE=["Q?"])
    result = await turn(find_session(ctx, steering(ctx)), "yes", llm, ctx)
    profile = result.session.profile.model_dump(mode="json", by_alias=True)
    assert profile["process"]["name"] == "the monthly cost review"
    assert (meta_for(profile, "process.name") or {}).get("source") == "expert"
    assert result.session.steering.status == "chosen"


async def test_ok_or_sure_decides_nothing(ctx):
    """AC-14.72."""
    for text in ("ok", "sure"):
        llm = fake(EXTRACT=[{}], GUIDE=["Q?"])
        result = await turn(find_session(ctx, steering(ctx), find_turns=3), text, llm, ctx)
        assert result.session.profile.process.name == ""
        assert result.session.steering.declined is False


async def test_a_short_no_opens_the_pick_list(ctx):
    """AC-14.72."""
    llm = fake(EXTRACT=[{}], GUIDE=["Which one?"])
    session = find_session(ctx, steering(ctx, recommend_asks=1), find_turns=3)
    result = await turn(session, "no", llm, ctx)
    assert result.session.steering.declined is True
    assert result.session.last_question.focus == ["process.name"]
    assert result.session.last_question.confirm is None
    guide = llm.calls_of(CallType.GUIDE)[0].messages[0]["content"]
    assert "STEERING" in guide and "chasing site managers: about 100 hours a year" in guide


async def test_naming_another_candidate_wins(ctx):
    """AC-14.72."""
    llm = fake(EXTRACT=[{"process.name": "booking travel"}], CLASSIFY=[CLASSIFY], GUIDE=["Q?"])
    result = await turn(find_session(ctx, steering(ctx)), "Let's do booking travel instead", llm, ctx)
    assert result.session.profile.process.name == "booking travel"
    assert result.session.steering.status == "chosen"


async def test_two_recommend_asks_at_most_then_the_direct_posture_proposes_rank_one(ctx):
    """AC-14.73."""
    llm = fake(EXTRACT=[{}], GUIDE=["Q?"])
    session = find_session(ctx, steering(ctx, recommend_asks=2), find_turns=4)
    result = await turn(session, "hmm, not sure", llm, ctx)
    assert result.session.last_question.confirm is None
    assert result.session.steering.recommend_asks == 2
    guide = llm.calls_of(CallType.GUIDE)[0].messages[0]["content"]
    assert "Help the expert settle on the one process to map" in guide
    assert "propose the monthly cost review" in guide


async def test_a_named_process_ends_steering_and_keeps_the_signals_on_the_ideas(ctx):
    """AC-14.74, AC-14.75."""
    steer = steering(ctx, status="collecting", signals=False, questions=1)
    session = find_session(ctx, steer, find_turns=2, confirm=None, agent="How often does each come round?")
    extract = {
        "process.name": "the monthly cost review",
        "candidate_signals": [{"name": "booking travel", "runs": "twice a month", "time": "an hour"}],
    }
    llm = fake(EXTRACT=[extract], CLASSIFY=[SCOPE_ONLY], GUIDE=["Q?"])
    result = await turn(session, "Twice a month for travel, an hour. Let's map the cost review.", llm, ctx)
    assert result.session.steering.status == "chosen"
    assert result.session.last_question.focus != ["steer:runs", "steer:time"]
    names = [i["name"] for i in result.ideas]
    assert "booking travel" in names and "the monthly cost review" not in names
    travel = result.ideas[names.index("booking travel")]
    assert travel["signals"]["runs"] == "twice a month" and travel["hours_per_year"] == 24
    assert {"people", "data_score", "score", "rank", "recommended"} <= set(travel)
