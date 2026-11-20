"""The shapes threaded through one interview turn: the LangGraph state, the context and the ask target (spec 14 §3.2, §4).

Why: the nodes, the graph, the prompts and the turn entry points all name the same shapes, and
naming them without importing the logic that fills them keeps the dependencies one-way. The saved
keys mirror the session (spec 12); the turn-local ones are dropped after the turn, so the
conversation's cross-turn state lives only in `counters`, `scope`, `placement`, `last_question` and
`steering` (§3.15).
What: `TurnState` (a `TypedDict`, total=False, every key LangGraph may merge), `InterviewSettings`,
`InterviewContext` (vocabulary, lexicon, settings, product name, steering config; built once in the lifespan) and
`Ask` (the one thing the next question is about, chosen by code).
Must not: hold logic, read the environment, or create anything at import time.
Spec 14 §3.2, §3.15, §4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, TypedDict

from app.core.config import SteeringConfig

from ..domain.field_spec import Vocabulary

if TYPE_CHECKING:
    from .replies import Lexicon


class TurnState(TypedDict, total=False):
    """Mutable state of one turn. Saved keys mirror the session; the rest is dropped after the turn."""

    # saved (mirrors the session, spec 12)
    messages: list[dict[str, Any]]
    profile: dict[str, Any]
    phase: str
    score: dict[str, Any]
    counters: dict[str, Any]
    scope: dict[str, Any]
    placement: dict[str, Any]
    last_question: dict[str, Any]
    steering: dict[str, Any]
    # turn-local
    user_input: str
    now: str
    deadline: float
    reply: str
    ideas: list[dict[str, Any]]
    classified: bool
    documents: list[dict[str, str]]
    log: dict[str, Any]


@dataclass(frozen=True)
class InterviewSettings:
    """The four interview settings (spec 14 §4); the lifespan builds them from `Settings`."""

    guide_history_turns: int = 30
    turn_timeout_seconds: float = 150.0
    placement_min_confidence: float = 0.60
    placement_min_margin: float = 0.15


@dataclass(frozen=True)
class InterviewContext:
    """Everything a turn needs that is not in the session: built once per process."""

    vocab: Vocabulary
    lexicon: Lexicon
    settings: InterviewSettings = field(default_factory=InterviewSettings)
    product_name: str = "Discovery Agent"
    #: Steering toward value and ready data (§3.15); `None` turns it off.
    steering: SteeringConfig | None = None


AskKind = Literal["widening", "proposals", "steer", "recommend", "cluster", "field", "cell", "rollups", "wrap_up"]


class Ask(NamedTuple):
    """The one ask target of a turn: its kind, the keys it is about, and the cluster or recommendation mode."""

    kind: AskKind
    keys: tuple[str, ...] = ()
    mode: Literal["propose", "picker", "recommend", "pick"] | None = None
