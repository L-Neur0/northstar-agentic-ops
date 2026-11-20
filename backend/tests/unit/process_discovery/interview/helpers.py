"""Helpers for the interview tests: the context, a fresh session, and `play` (spec 14 §7).

Why: every interview test drives the real turn (`run_turn` over the compiled graph) with a scripted
`FakeLLM`, so the helpers build those once, from the real NIG configuration. What: `make_context`,
`new_session`, `fake`, `turn` and `play`, which runs a list of expert messages with scripted
EXTRACT replies and returns every result. Must not: patch a node or bypass a writer.
"""

from __future__ import annotations

from typing import Any

from app.core.config import CompanyConfig
from app.models.process_discovery_schemas import Session
from app.services.process_discovery.domain.field_spec import Vocabulary
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.interview.graph import build_graph
from app.services.process_discovery.interview.replies import Lexicon
from app.services.process_discovery.interview.turn import TurnResult, run_turn, welcome
from app.services.process_discovery.interview.types import InterviewContext, InterviewSettings
from app.services.process_discovery.llm import CallType

NOW = "2026-11-19T10:00:00+00:00"


def make_context(config: CompanyConfig, vocab: Vocabulary, **settings: Any) -> InterviewContext:
    return InterviewContext(
        vocab=vocab,
        lexicon=Lexicon.from_config(config.language),
        settings=InterviewSettings(**settings),
        product_name=config.organisation.product_name,
        steering=config.steering,
    )


def new_session(ctx: InterviewContext, **update: Any) -> Session:
    """A fresh session with the welcome message, as the service creates it; `update` fields are validated."""
    text, question = welcome(None, ctx)
    data: dict[str, Any] = {
        "owner_id": "test",
        "created_at": NOW,
        "updated_at": NOW,
        "last_question": question.model_dump(),
        "messages": [{"role": "agent", "text": text, "at": NOW}],
    }
    data.update({k: (v.model_dump(by_alias=True) if hasattr(v, "model_dump") else v) for k, v in update.items()})
    return Session.model_validate(data)


def fake(**script: list[Any]) -> FakeLLM:
    return FakeLLM({CallType[k]: v for k, v in script.items()})


async def turn(session: Session, text: str, llm: FakeLLM, ctx: InterviewContext) -> TurnResult:
    return await run_turn(session, text, llm=llm, graph=build_graph(llm, ctx), ctx=ctx, now=NOW)


async def play(
    session: Session,
    steps: list[tuple[str, dict[str, Any]]],
    ctx: InterviewContext,
    *,
    classify: list[Any] | None = None,
) -> list[TurnResult]:
    """Run `(expert message, EXTRACT reply)` pairs; GUIDE replies are generic, CLASSIFY replies scripted."""
    llm = FakeLLM()
    for _, reply in steps:
        llm.add(CallType.EXTRACT, reply)
        llm.add(CallType.GUIDE, "Next question?")
    for reply in classify or []:
        llm.add(CallType.CLASSIFY, reply)
    graph = build_graph(llm, ctx)
    results: list[TurnResult] = []
    for text, _ in steps:
        result = await run_turn(session, text, llm=llm, graph=graph, ctx=ctx, now=NOW)
        results.append(result)
        session = result.session
    return results
