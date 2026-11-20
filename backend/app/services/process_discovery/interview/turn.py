"""Entry points of the interview: one turn, a change made outside a turn, and the welcome (spec 14 §3.2, §3.11, §3.12).

Why: the service (spec 15) and the terminal runner (`make chat`) must drive the interview the same
way, so the whole turn (state from the session, the graph, the session from the state, the
*Finish* check, one log line) lives here, and the service only loads, calls and saves. Changes
made outside a turn (Confirm buttons, the cluster picker, ✓/✎ on proposals, a document read) go
through `after_action`, which recomputes the score and the phase exactly as a turn does.
What: `TurnResult`, `hydrate`, `apply_state`, `run_turn`, `after_action` and `welcome`.
Rules it protects: the input session is never mutated; an emptied scope verdict is saved as empty
and a rejected placement as `proposal: None` (with `placed_for` kept); a refused daily budget in
EXTRACT propagates and nothing is saved; the turn log carries keys, counts, codes and times only
(its `steer` object: status, counts and candidate ids, never a name, §3.15 item 15).
Must not: talk to the store or the network itself (the LLM is passed in), or log any text.
Spec 14 §3.2, §3.11, §3.12, §3.15; AC-14.32, AC-14.51 to AC-14.54, AC-14.56, AC-14.75, AC-14.80.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, NamedTuple, cast

from langgraph.graph.state import CompiledStateGraph

from app.core.logging import log_event
from app.models.process_discovery_schemas import (
    Counters,
    LastQuestion,
    Message,
    Phase,
    PlacementState,
    Profile,
    ScopeState,
    Score,
    Session,
    SteeringState,
)

from ..domain.field_spec import spec_by_id
from ..llm import LLM
from ..profile.scoring import FinishCheck, finish_check, score
from ..profile.shapes import as_mapping
from ..profile.verdicts import field_counts
from .gates import current_name
from .phases import advance_phase, read_counters
from .prompts.common import welcome_text
from .types import InterviewContext, TurnState

logger = logging.getLogger("app.interview")


class TurnResult(NamedTuple):
    """A new session, the agent's reply, the *Finish* check and the ideas heard this turn."""

    session: Session
    reply: str
    finish: FinishCheck
    ideas: list[dict[str, Any]]


def hydrate(session: Session, text: str, now: str) -> TurnState:
    """The turn state from the session; the expert's message (when there is one) is appended."""
    messages = [m.model_dump(mode="json") for m in session.messages]
    if text.strip():
        messages.append({"id": str(uuid.uuid4()), "role": "expert", "text": text, "at": now})
    return {
        "messages": messages,
        "user_input": text,
        "profile": session.profile.model_dump(mode="json", by_alias=True),
        "phase": session.phase.value,
        "score": session.score.model_dump(mode="json"),
        "counters": session.counters.model_dump(mode="json"),
        "scope": session.scope.model_dump(mode="json"),
        "placement": session.placement.model_dump(mode="json"),
        "last_question": session.last_question.model_dump(mode="json"),
        "steering": session.steering.model_dump(mode="json"),
        "documents": [{"id": d.id, "name": d.name, "kind": d.kind} for d in session.documents],
        "now": now,
        "classified": False,
        "ideas": [],
        "log": {},
    }


def apply_state(session: Session, state: TurnState) -> Session:
    """A new session from the turn state; the input session is left as it was."""
    scope = dict(state.get("scope") or {})
    if "verdict" in scope and not scope["verdict"]:
        scope["verdict"] = None
    placement = dict(state.get("placement") or {})
    if "proposal" in placement and not placement["proposal"]:
        placement["proposal"] = None
    update: dict[str, Any] = {
        "messages": [Message.model_validate(m) for m in state.get("messages") or []],
        "profile": Profile.model_validate(state.get("profile") or {}),
        "phase": Phase(state.get("phase", session.phase.value)),
        "score": Score.model_validate(state.get("score") or session.score.model_dump()),
        "counters": Counters.model_validate(read_counters(state.get("counters"))),
        "scope": ScopeState.model_validate(scope),
        "placement": PlacementState.model_validate(placement),
        "last_question": LastQuestion.model_validate(state.get("last_question") or {}),
        "steering": SteeringState.model_validate(state.get("steering") or session.steering.model_dump(mode="json")),
        "updated_at": state.get("now") or session.updated_at,
    }
    return session.model_copy(deep=True, update=update)


def _steer_log(steering: SteeringState, ctx: InterviewContext) -> dict[str, Any]:
    """§3.15 item 15: status, counts and ids only; never a candidate's name or words."""
    limit = ctx.steering.max_candidates if ctx.steering is not None else len(steering.candidates)
    return {
        "status": steering.status,
        "questions": steering.questions,
        "candidates": len(steering.candidates),
        "known": [
            sum(v is not None for v in (c.hours_per_year, c.people, c.data_score)) for c in steering.candidates[:limit]
        ],
        "recommended": steering.recommended_id,
    }


def _turn_log(
    session: Session, new: Session, state: TurnState, finish: FinishCheck, ms: int, ctx: InterviewContext
) -> dict[str, Any]:
    log = dict(as_mapping(state.get("log")) or {})
    sc = new.score
    return {
        "session_id": session.id,
        "phase_in": session.phase.value,
        "phase_out": new.phase.value,
        "ask_kind": log.get("ask_kind"),
        "focus": log.get("focus", []),
        "focus_asks": log.get("focus_asks", 0),
        "offered": log.get("offered", []),
        "dropped": log.get("dropped", []),
        "written_but_incomplete": log.get("written_but_incomplete", []),
        "proposals_waiting": log.get("proposals_waiting", 0),
        "proposals_confirmed": log.get("proposals_confirmed", []),
        "proposals_rejected": log.get("proposals_rejected", []),
        "cluster_reply": log.get("cluster_reply", "none"),
        "cluster_armed": (new.placement.proposal.code if new.placement.proposal else None),
        "rollups_confirmed": log.get("rollups_confirmed", []),
        "escapes": log.get("escapes", []),
        "deferred": log.get("deferred", []),
        "given_up": log.get("given_up", []),
        "substep_count_assumed": log.get("substep_count_assumed", False),
        "score": sc.value,
        "filled_points": sc.filled_points,
        "total_points": sc.total_points,
        "finish_blocked_by": finish.blocked_by,
        "classify": log.get("classify"),
        "calls": log.get("calls", {}),
        "fallback_used": log.get("fallback_used", False),
        "ideas": log.get("ideas", 0),
        "steer": _steer_log(new.steering, ctx),
        "extract": log.get("extract", "skipped"),
        "duration_ms": ms,
    }


async def run_turn(
    session: Session,
    text: str,
    *,
    llm: LLM,
    graph: CompiledStateGraph[Any, Any, Any, Any],
    ctx: InterviewContext,
    now: str,
) -> TurnResult:
    """Hydrate → run the graph under the turn guard → apply → *Finish* check → one `interview_turn` line."""
    del llm  # bound into the graph's nodes; kept in the signature so callers state which client runs the turn
    state = hydrate(session, text, now)
    started = time.monotonic()
    state["deadline"] = started + ctx.settings.turn_timeout_seconds
    result = cast(TurnState, await graph.ainvoke(state))  # pyright: ignore[reportUnknownMemberType]
    new = apply_state(session, result)
    finish = finish_check(
        new.profile.model_dump(mode="json", by_alias=True), vocab=ctx.vocab, scope=new.scope.model_dump(mode="json")
    )
    log_event(
        logger,
        "interview_turn",
        **_turn_log(session, new, result, finish, int((time.monotonic() - started) * 1000), ctx),
    )
    return TurnResult(new, str(result.get("reply") or ""), finish, list(result.get("ideas") or []))


def after_action(session: Session, *, ctx: InterviewContext) -> Session:
    """After a change made outside a turn: recompute the score and the phase exactly as a turn does."""
    profile = session.profile.model_dump(mode="json", by_alias=True)
    counters = session.counters.model_dump(mode="json")
    sc = score(profile, vocab=ctx.vocab)
    phase = advance_phase(profile, session.phase.value, counters, vocab=ctx.vocab)
    update: dict[str, Any] = {"score": Score(**sc._asdict()), "phase": Phase(phase)}
    if field_counts(profile, "process.cluster", vocab=ctx.vocab):
        update["placement"] = PlacementState(
            proposal=None,
            placed_for=current_name(profile, vocab=ctx.vocab),
            rejected=session.placement.rejected,
        )
    return session.model_copy(deep=True, update=update)


def welcome(display_name: str | None, ctx: InterviewContext) -> tuple[str, LastQuestion]:
    """The fixed first message (no model call), ending with the P01 question; `last_question.focus = ["department"]`."""
    p01 = spec_by_id("P01")
    question = ctx.vocab.question(p01) if p01 is not None else "Which department are you in?"
    text = welcome_text(display_name, product_name=ctx.product_name, first_question=question)
    return text, LastQuestion(focus=["department"])
