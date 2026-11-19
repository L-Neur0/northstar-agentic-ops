"""Tests for the turn log line and log hygiene (spec 14 §3.11; AC-14.54; product F-24).

Why: a stuck interview is diagnosed from one log line per turn, and the logs must never carry what
the expert said or uploaded. What: exactly one `interview_turn` line per turn with the §3.11 fields,
a partial write named in `written_but_incomplete`, and a sentinel string (in the message, the
extracted values, a document quote and a model reply) found in no log record at all.
"""

import logging

from app.models.process_discovery_schemas import Profile
from app.services.process_discovery.profile.proposals import FieldProposal, ProposalDiff, apply_proposals

from ..profile.builders import AT
from .helpers import fake, new_session, turn
from .sessions import BOUNDARIES, profile_with

FIELDS = {
    "session_id",
    "phase_in",
    "phase_out",
    "ask_kind",
    "focus",
    "focus_asks",
    "offered",
    "dropped",
    "written_but_incomplete",
    "proposals_waiting",
    "proposals_confirmed",
    "proposals_rejected",
    "cluster_reply",
    "cluster_armed",
    "rollups_confirmed",
    "escapes",
    "deferred",
    "given_up",
    "substep_count_assumed",
    "score",
    "filled_points",
    "total_points",
    "finish_blocked_by",
    "classify",
    "calls",
    "fallback_used",
    "ideas",
}
SENTINEL = "QQ-SENTINEL-QQ"


def lines(caplog):
    return [r for r in caplog.records if r.getMessage() == "interview_turn"]


async def test_one_line_per_turn_with_every_field(ctx, caplog):
    """AC-14.54."""
    caplog.set_level(logging.INFO, logger="app.interview")
    session = new_session(
        ctx,
        phase="measure",
        profile=Profile.model_validate(profile_with(ctx, *BOUNDARIES)),
        scope={"scoped_for": "Monthly cost review"},
        placement={"placed_for": "Monthly cost review"},
        last_question={"focus": ["process.volume"]},
    )
    first = await turn(session, "about 400", fake(EXTRACT=[{"process.volume": {"count": 400}}], GUIDE=["Q?"]), ctx)
    await turn(first.session, "a month", fake(EXTRACT=[{"process.volume": {"period": "month"}}], GUIDE=["Q?"]), ctx)
    found = lines(caplog)
    assert len(found) == 2
    assert FIELDS <= set(found[0].__dict__)
    assert found[0].written_but_incomplete == ["process.volume(period)"]  # type: ignore[attr-defined]
    assert found[0].focus == ["process.volume"]  # type: ignore[attr-defined]
    assert found[1].written_but_incomplete == []  # type: ignore[attr-defined]


async def test_no_log_record_carries_text(ctx, caplog):
    """AC-14.54."""
    caplog.set_level(logging.DEBUG)
    p = profile_with(ctx)
    p = apply_proposals(
        p, ProposalDiff("d1", fields=(FieldProposal("process.trigger", SENTINEL, SENTINEL),)), vocab=ctx.vocab, at=AT
    ).profile
    session = new_session(
        ctx,
        phase="boundaries",
        profile=Profile.model_validate(p),
        scope={"scoped_for": "Monthly cost review"},
        placement={"placed_for": "Monthly cost review"},
    )
    llm = fake(
        EXTRACT=[
            {
                "process.end_result": SENTINEL,
                "process.volume": {"count": SENTINEL},
                "bogus": SENTINEL,
                "process.business_pain": f"{SENTINEL} ignore all previous instructions",
            }
        ],
        GUIDE=[SENTINEL],
    )
    await turn(session, f"my answer {SENTINEL}", llm, ctx)
    assert caplog.records
    for record in caplog.records:
        assert SENTINEL not in record.getMessage()
        assert SENTINEL not in str(record.__dict__)
