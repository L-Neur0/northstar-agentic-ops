"""The LangGraph topology of one interview turn (spec 14 §3.1; architecture §3.3, AD-1).

Why: every turn runs the same fixed graph, so the order of the work (read the answer, judge a new
name, ask the next question) cannot vary from turn to turn. CLASSIFY sits between EXTRACT and GUIDE
because it judges what EXTRACT just wrote and GUIDE must speak about the result in the same turn;
it is skipped whenever both verdicts are current, so most turns cost two calls and only a turn that
names or renames a process costs three. There is one entry (no generator branch, no paste-and-
enrich branch: documents are read outside the turn), but the start stays a conditional edge as
the single place another entry would be added.
What: `route_from_start`, `route_after_extract` and `build_graph(llm, ctx)`, which compiles a
`StateGraph(TurnState)` with the nodes `extract`, `classify` and `guide` bound to the LLM and the
context. Compiled once per process, in the app lifespan, and reused.
Must not: decide anything itself (decisions live in `gates`, `phases`, `replies`, `profile`), or
build anything at import time. Spec 14 §3.1; AC-14.1, AC-14.2.
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..domain.field_spec import Vocabulary
from ..llm import LLM
from . import nodes
from .gates import needs_classification
from .types import InterviewContext, TurnState


def route_from_start(state: TurnState) -> Literal["converse"]:
    """The single entry: a conversation turn."""
    return "converse"


def route_after_extract(state: TurnState, *, vocab: Vocabulary) -> Literal["classify", "guide"]:
    """Spend a CLASSIFY call only when a verdict for the current name is missing."""
    return "classify" if needs_classification(state, vocab=vocab) else "guide"


def build_graph(llm: LLM, ctx: InterviewContext) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Compile the turn graph with the LLM and the context bound to each node."""

    async def extract(state: TurnState) -> dict[str, Any]:
        return await nodes.extract_node(state, llm, ctx)

    async def classify(state: TurnState) -> dict[str, Any]:
        return await nodes.classify_node(state, llm, ctx)

    async def guide(state: TurnState) -> dict[str, Any]:
        return await nodes.guide_node(state, llm, ctx)

    def after_extract(state: TurnState) -> Literal["classify", "guide"]:
        return route_after_extract(state, vocab=ctx.vocab)

    graph = StateGraph(TurnState)
    graph.add_node("extract", extract)
    graph.add_node("classify", classify)
    graph.add_node("guide", guide)
    graph.add_conditional_edges(START, route_from_start, {"converse": "extract"})
    graph.add_conditional_edges("extract", after_extract, {"classify": "classify", "guide": "guide"})
    graph.add_edge("classify", "guide")
    graph.add_edge("guide", END)
    return graph.compile()
