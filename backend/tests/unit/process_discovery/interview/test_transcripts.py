"""Scripted personas: every conversation terminates and passes the phases in order (spec 14 §7; AC-14.29, AC-14.31; product F-09).

Why: "every loop has a counter, and every counter has a maximum" is only true if no conversation,
however unhelpful, can pin the interview. What: state-aware personas drive real turns (EXTRACT
replies scripted from the last question, a generic GUIDE, a fixed CLASSIFY) until `review`; each
must arrive without any field asked more than 5 times or any cell more than 3. A cooperative
expert passes context → find → boundaries → measure → step_count → steps → confirm → review.
Note: the lists are confirmed only by a person (F-10), so every persona says "yes" when the roles
or systems are read back; nothing is ever confirmed automatically (AC-14.19).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.services.process_discovery.domain.field_spec import PHASE_ORDER, step_cell_key
from app.services.process_discovery.interview.graph import build_graph
from app.services.process_discovery.interview.turn import run_turn
from app.services.process_discovery.profile.shapes import parse_step_key

from ..profile.builders import process_changes, step_changes
from .helpers import NOW, new_session

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
ROLLUPS = {"process.all_roles", "process.all_tools"}


class PersonaLLM:
    """An endless scripted model: EXTRACT returns what the persona set for this turn; GUIDE a generic question."""

    def __init__(self) -> None:
        self.next_extract: dict[str, Any] = {}

    async def generate_text(self, call_type, messages, *, max_tokens=None) -> str:
        system = messages[0]["content"]
        marker = "Proposed cluster, word for word: "
        if marker in system:
            return f"Would you file it under {system.split(marker, 1)[1].split(':', 1)[0]}?"
        return "Next question?"

    async def generate_json(self, call_type, messages, *, max_tokens=None) -> dict[str, Any]:
        return dict(self.next_extract)

    async def generate_structured(self, model_cls: type[BaseModel], call_type, messages, *, max_tokens=None):
        return model_cls.model_validate({k: v for k, v in CLASSIFY.items() if k in model_cls.model_fields})

    async def aclose(self) -> None:
        return None


Persona = Callable[[dict[str, Any], str], tuple[str, dict[str, Any]]]


def wrap(answer: Persona) -> Persona:
    def reply(question: dict[str, Any], phase: str) -> tuple[str, dict[str, Any]]:
        if ROLLUPS & set(question.get("focus") or []):
            return "yes", {}
        return answer(question, phase)

    return reply


@wrap
def dont_know(question, phase):
    return "I don't know", {}


@wrap
def thirteen_steps(question, phase):
    if "process.substep_count" in (question.get("focus") or []):
        return "about 13 steps", {"process.substep_count": 13}
    return "no idea", {}


@wrap
def rejects_clusters(question, phase):
    focus = question.get("focus") or []
    if "process.cluster" in focus:
        return ("no" if question.get("confirm") == "cluster" else "none of those fit"), {}
    if phase == "find":
        return "the quarterly access review", {"process.name": "Quarterly access review"}
    return "no idea", {}


@wrap
def off_topic(question, phase):
    return "the weather is lovely today", {"weather": "lovely"}


@wrap
def dots(question, phase):
    return "...", {}


def _value(key: str) -> Any:
    parsed = parse_step_key(key)
    if parsed is not None:
        return step_changes(parsed[0])[key]
    context = {"department": "Finance", "user_function": "Controller", "region": "Europe"}
    return {**context, **process_changes(3), "process.name": "Monthly cost review"}[key]


def cooperative(question, phase):
    focus = question.get("focus") or []
    if ROLLUPS & set(focus) or question.get("confirm") == "cluster" or question.get("proposals"):
        return "yes", {}
    if not focus:
        return "nothing to add", {}
    return f"answer {', '.join(focus)}", {k: _value(k) for k in focus}  # a group is answered at once (§3.19)


async def run(ctx, persona: Persona, limit: int = 300):
    llm = PersonaLLM()
    graph = build_graph(llm, ctx)  # type: ignore[arg-type]
    session = new_session(ctx)
    phases = [session.phase.value]
    for _ in range(limit):
        if session.phase.value == "review":
            return session, phases
        text, extract = persona(session.last_question.model_dump(), session.phase.value)
        llm.next_extract = extract
        result = await run_turn(session, text, llm=llm, graph=graph, ctx=ctx, now=NOW)  # type: ignore[arg-type]
        session = result.session
        phases.append(session.phase.value)
    raise AssertionError(f"did not reach review: phase {session.phase.value}, last question {session.last_question}")


async def test_unhelpful_personas_terminate(ctx):
    """AC-14.29."""
    for persona in (dont_know, thirteen_steps, rejects_clusters, off_topic, dots):
        session, _ = await run(ctx, persona)
        assert max(session.counters.field_asks.values(), default=0) <= 5, persona.__name__
        assert max(session.counters.cell_asks.values(), default=0) <= 3, persona.__name__


async def test_a_cooperative_expert_walks_every_phase_in_order(ctx):
    """AC-14.31."""
    session, phases = await run(ctx, cooperative)
    order = list(dict.fromkeys(phases))
    assert session.last_question.proposals  # §3.19 W8: the agent's proposals are confirmed in bulk in review
    llm = PersonaLLM()
    session = (await run_turn(session, "yes", llm=llm, graph=build_graph(llm, ctx), ctx=ctx, now=NOW)).session  # type: ignore[arg-type]
    assert order == list(PHASE_ORDER)
    assert session.profile.process.substeps_complete is True
    assert session.profile.process.cluster.code == "FIN"
    assert session.score.value == 1.0
    assert max(session.counters.field_asks.values()) == 1
    assert step_cell_key(1, "name") in session.counters.cell_asks
