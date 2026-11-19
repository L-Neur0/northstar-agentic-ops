"""The discovery service: the use cases behind the interview API, and the engine's composition root (spec 15 part 2 §3.1, §3.2, §4).

Why: every route must load, change and save a session the same way, or a turn, a button and a
second browser tab would overwrite each other. Here every write follows one pattern: load the
caller's session (missing → `SessionNotFound`), refuse a closed one (`SessionClosed`), work on a
new object (inputs are never mutated), stamp `updated_at` (the service owns time), and save the
whole document once with the etag it was read with (a stale etag raises the store's
`ConflictError`; nothing is retried).
What: `DiscoveryService` (create, list, get, delete, turn, confirm, cluster picker, close, finish,
ideas, delete my data, and `view`, which builds the `SessionOut` wire model), its errors,
`build_context` (the interview context from the company config and settings, built once in the
lifespan), and the LLM names the shell needs (`create_llm`, `build_graph`, the errors), so routes
and the lifespan import only the facade. One `service_call` log line per use case: use case,
session id, 8-character owner prefix, outcome, duration; never text.
Must not: call the model outside `process_turn`, decide anything the profile or interview layers
decide, or log message, profile or document text. Spec 15 AC-15.27 to AC-15.45.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from app.core.config import CompanyConfig
from app.core.logging import log_event
from app.core.rate_limit import usage_scope
from app.core.settings import Settings
from app.models.process_discovery_schemas import (
    ClusterOut,
    Cost,
    FieldView,
    FinishState,
    Idea,
    Message,
    MessageRole,
    Phase,
    Profile,
    ReportState,
    Session,
    SessionStatus,
)
from app.models.process_discovery_wire import MessageOut, ScopeOut, ScoreOut, SessionOut
from app.services.store.repository import (
    ConflictError,
    DeletedCounts,
    SessionRepository,
    SessionSummary,
    StoredIdea,
)
from app.utils.prompt_safety import contains_injection_pattern

from .domain.field_spec import META_KEY, SKIPPED_KEY, Vocabulary
from .interview.graph import build_graph
from .interview.replies import Lexicon, cluster_armed
from .interview.turn import TurnResult, after_action, run_turn, welcome
from .interview.types import InterviewContext, InterviewSettings
from .llm import LLM, LLMBudgetExceededError, LLMConfigError, create_llm
from .profile.mutate import UnknownClusterError, close_steps, confirm_rollup
from .profile.mutate import set_cluster as write_cluster
from .profile.proposals import propose_from_idea
from .profile.scoring import FinishCheck, finish_check
from .profile.views import field_views

__all__ = [
    "ConflictError",
    "DiscoveryService",
    "IdeaAlreadyStarted",
    "IdeaNotFound",
    "LLMBudgetExceededError",
    "LLMConfigError",
    "MapIncomplete",
    "NotFound",
    "SessionClosed",
    "SessionNotFound",
    "TurnResult",
    "UnknownCluster",
    "UnsafeInput",
    "build_context",
    "build_graph",
    "create_llm",
]

logger = logging.getLogger("app.service")

#: Wire confirmation targets → the profile's roll-up targets (spec 13 names the systems list `systems`).
ROLLUP_TARGET = {"roles": "roles", "tools": "systems"}


# --- errors -------------------------------------------------------------------------------------------


class NotFound(Exception):
    """The document does not exist for this caller (or belongs to someone else)."""


class SessionNotFound(NotFound):
    pass


class IdeaNotFound(NotFound):
    pass


class SessionClosed(Exception):
    """The session is `finished` or `no_candidate`; only reads and delete are allowed."""


class UnsafeInput(Exception):
    """The message matched the injection screen; nothing was stored and the model was not called."""


class MapIncomplete(Exception):
    """*Finish* is not open yet; `reason` is the first blocker (spec 13 `finish_check`)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"the map is not complete yet: {reason}")
        self.reason = reason


class UnknownCluster(Exception):
    """The picker sent a code the company taxonomy does not declare."""


class IdeaAlreadyStarted(Exception):
    """The idea already has a session."""


# --- composition --------------------------------------------------------------------------------------


def build_context(company: CompanyConfig, settings: Settings) -> InterviewContext:
    """The interview context, built once per process from the company config and the settings."""
    vocab = Vocabulary(taxonomy=company.taxonomy, regions=company.organisation.regions, wording=company.wording)
    return InterviewContext(
        vocab=vocab,
        lexicon=Lexicon.from_config(company.language),
        settings=InterviewSettings(
            guide_history_turns=settings.guide_history_turns,
            turn_timeout_seconds=settings.turn_timeout_seconds,
            placement_min_confidence=settings.placement_min_confidence,
            placement_min_margin=settings.placement_min_margin,
        ),
        product_name=company.organisation.product_name,
    )


def _strip_internals(value: Any) -> Any:
    """The profile as the client sees it: registry keys only, no `__meta` / `__skipped` sidecars."""
    if isinstance(value, dict):
        return {k: _strip_internals(v) for k, v in value.items() if k not in (META_KEY, SKIPPED_KEY)}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list):
        return [_strip_internals(v) for v in value]  # pyright: ignore[reportUnknownVariableType]
    return value


class DiscoveryService:
    """The interview use cases. Built once in the lifespan; `llm` and `graph` are `None` when no model is configured."""

    def __init__(
        self,
        repo: SessionRepository,
        llm: LLM | None,
        ctx: InterviewContext,
        graph: CompiledStateGraph[Any, Any, Any, Any] | None,
        *,
        clock: Callable[[], str],
    ) -> None:
        self.repo = repo
        self.llm = llm
        self.ctx = ctx
        self.graph = graph
        self.clock = clock

    # --- helpers ---

    @asynccontextmanager
    async def _track(self, use_case: str, owner: str, session_id: str | None = None) -> AsyncIterator[None]:
        """One `service_call` line per use case, with the outcome; never text."""
        started = time.monotonic()
        outcome = "ok"
        try:
            yield
        except BaseException as exc:
            outcome = {
                ConflictError: "conflict",
                UnsafeInput: "unsafe_input",
                LLMBudgetExceededError: "budget",
                MapIncomplete: "map_incomplete",
            }.get(type(exc), type(exc).__name__)
            raise
        finally:
            log_event(
                logger,
                "service_call",
                use_case=use_case,
                sessionId=session_id,
                owner=owner[:8],
                outcome=outcome,
                duration_ms=int((time.monotonic() - started) * 1000),
            )

    async def _load(self, owner: str, session_id: str) -> Session:
        session = await self.repo.get_session(owner, session_id)
        if session is None:
            raise SessionNotFound(session_id)
        return session

    async def _load_active(self, owner: str, session_id: str) -> Session:
        session = await self._load(owner, session_id)
        if session.status != SessionStatus.ACTIVE:
            raise SessionClosed(session_id)
        return session

    async def _save(self, session: Session, now: str | None = None) -> Session:
        return await self.repo.replace_session(session.model_copy(update={"updated_at": now or self.clock()}))

    def _profile(self, session: Session) -> dict[str, Any]:
        return session.profile.model_dump(mode="json", by_alias=True)

    def _finish(self, session: Session) -> FinishCheck:
        return finish_check(self._profile(session), vocab=self.ctx.vocab, scope=session.scope.model_dump(mode="json"))

    async def _with_profile(self, session: Session, profile: dict[str, Any]) -> Session:
        """Save a profile changed outside a turn, after `after_action` recomputed the score and phase."""
        changed = after_action(session.model_copy(update={"profile": Profile.model_validate(profile)}), ctx=self.ctx)
        return await self._save(changed)

    # --- sessions ---

    async def create_session(
        self, owner: str, *, display_name: str | None = None, from_idea_id: str | None = None
    ) -> Session:
        """A new session with the fixed welcome (no model call); from an idea, its name is proposed for P04."""
        async with self._track("create_session", owner):
            idea: StoredIdea | None = None
            if from_idea_id is not None:
                idea = await self.repo.get_idea(owner, from_idea_id)
                if idea is None or idea.status == "dismissed":
                    raise IdeaNotFound(from_idea_id)
                if idea.status == "started":
                    raise IdeaAlreadyStarted(from_idea_id)
            now = self.clock()
            text, question = welcome(display_name, self.ctx)
            session = Session(
                owner_id=owner,
                display_name=display_name,
                created_at=now,
                updated_at=now,
                last_question=question,
                messages=[Message(role=MessageRole.AGENT, text=text, at=now)],
            )
            if idea is not None:
                profile = propose_from_idea(self._profile(session), idea.name, idea.words, at=now)
                session = session.model_copy(update={"profile": Profile.model_validate(profile)})
                # Claim the idea first: its etag makes a second, concurrent start a conflict.
                await self.repo.replace_idea(
                    idea.model_copy(update={"status": "started", "started_session_id": session.id})
                )
            return await self.repo.create_session(session)

    async def list_sessions(self, owner: str) -> list[SessionSummary]:
        async with self._track("list_sessions", owner):
            return await self.repo.list_sessions(owner)

    async def get_session(self, owner: str, session_id: str) -> Session:
        async with self._track("get_session", owner, session_id):
            return await self._load(owner, session_id)

    async def delete_session(self, owner: str, session_id: str) -> None:
        async with self._track("delete_session", owner, session_id):
            if not await self.repo.delete_session(owner, session_id):
                raise SessionNotFound(session_id)

    # --- the turn ---

    async def process_turn(self, owner: str, session_id: str, text: str) -> TurnResult:
        """Screen, run the turn (2-3 model calls), save once, then store the new ideas. `ideas` = the ideas added."""
        async with self._track("process_turn", owner, session_id):
            session = await self._load_active(owner, session_id)
            if contains_injection_pattern(text):
                logger.warning("unsafe_input", extra={"sessionId": session_id, "owner": owner[:8]})
                raise UnsafeInput(session_id)
            if self.llm is None or self.graph is None:
                raise LLMConfigError("no model endpoint is configured")
            now = self.clock()
            with usage_scope() as usage:
                result = await run_turn(session, text, llm=self.llm, graph=self.graph, ctx=self.ctx, now=now)
            cost = session.cost
            new = result.session.model_copy(
                update={
                    "cost": Cost(
                        tokens_in=cost.tokens_in + usage.tokens_in,
                        tokens_out=cost.tokens_out + usage.tokens_out,
                        euros=cost.euros,
                    )
                }
            )
            saved = await self._save(new, now)
            added = await self._store_ideas(owner, saved.id, result.ideas, now)
            return TurnResult(saved, result.reply, result.finish, added)

    async def _store_ideas(
        self, owner: str, session_id: str, ideas: list[dict[str, str]], now: str
    ) -> list[dict[str, str]]:
        """Each idea name once per session (any status counts, so a dismissed idea does not come back)."""
        if not ideas:
            return []
        known = {i.name.casefold() for i in await self.repo.list_ideas(owner) if i.from_session_id == session_id}
        added: list[dict[str, str]] = []
        for item in ideas:
            name = item["name"]
            if name.casefold() in known:
                continue
            known.add(name.casefold())
            await self.repo.create_idea(
                Idea(owner_id=owner, name=name, words=item.get("words", ""), from_session_id=session_id, created_at=now)
            )
            added.append(item)
        return added

    # --- actions outside a turn (no model call) ---

    async def confirm(self, owner: str, session_id: str, target: str) -> Session:
        """`roles` / `tools`: confirm the list as shown; `substeps`: close the walk now and trim the count (spec 13)."""
        async with self._track("confirm", owner, session_id):
            if target not in (*ROLLUP_TARGET, "substeps"):
                raise ValueError(f"unknown confirmation target {target!r}")
            session = await self._load_active(owner, session_id)
            profile = self._profile(session)
            if target == "substeps":
                profile = close_steps(profile, vocab=self.ctx.vocab)
            else:
                profile = confirm_rollup(profile, ROLLUP_TARGET[target], vocab=self.ctx.vocab)
            return await self._with_profile(session, profile)

    async def set_cluster(self, owner: str, session_id: str, code: str) -> Session:
        """The cluster picker: P05 `decided_by: picker`, then the phase moves as after a turn."""
        async with self._track("set_cluster", owner, session_id):
            session = await self._load_active(owner, session_id)
            try:
                profile = write_cluster(
                    self._profile(session), code, decided_by="picker", vocab=self.ctx.vocab, at=self.clock()
                )
            except UnknownClusterError:
                raise UnknownCluster(code) from None
            return await self._with_profile(session, profile)

    async def close_without_candidate(self, owner: str, session_id: str) -> Session:
        """The expert found no process worth mapping. Only ever on the expert's request, never by the agent."""
        async with self._track("close_without_candidate", owner, session_id):
            session = await self._load_active(owner, session_id)
            now = self.clock()
            closed = session.model_copy(
                update={"status": SessionStatus.NO_CANDIDATE, "phase": Phase.NO_CANDIDATE, "finished_at": now}
            )
            return await self._save(closed, now)

    async def finish(self, owner: str, session_id: str) -> Session:
        """*Finish*: refused with the first blocker, else the map is stored as finished and `mapped`."""
        async with self._track("finish", owner, session_id):
            session = await self._load_active(owner, session_id)
            check = self._finish(session)
            if not check.ready:
                raise MapIncomplete(check.blocked_by or "below_gate")
            now = self.clock()
            finished = session.model_copy(
                update={
                    "status": SessionStatus.FINISHED,
                    "phase": Phase.FINISHED,
                    "finished_at": now,
                    "report": ReportState(status="mapped"),
                }
            )
            return await self._save(finished, now)

    # --- ideas and data ---

    async def list_ideas(self, owner: str) -> list[StoredIdea]:
        """The caller's ideas, newest first; dismissed ones are left out."""
        async with self._track("list_ideas", owner):
            return [i for i in await self.repo.list_ideas(owner) if i.status != "dismissed"]

    async def _open_idea(self, owner: str, idea_id: str) -> StoredIdea:
        idea = await self.repo.get_idea(owner, idea_id)
        if idea is None or idea.status == "dismissed":
            raise IdeaNotFound(idea_id)
        return idea

    async def dismiss_idea(self, owner: str, idea_id: str) -> None:
        """Dismissed, not deleted: the same name is not offered again from that session."""
        async with self._track("dismiss_idea", owner):
            idea = await self._open_idea(owner, idea_id)
            await self.repo.replace_idea(idea.model_copy(update={"status": "dismissed"}))

    async def start_idea(self, owner: str, idea_id: str) -> Session:
        return await self.create_session(owner, from_idea_id=idea_id)

    async def delete_owner_data(self, owner: str) -> DeletedCounts:
        async with self._track("delete_owner_data", owner):
            return await self.repo.delete_owner_data(owner)

    # --- the view ---

    def view(self, session: Session) -> SessionOut:
        """The session as the client sees it: no counters, no last question, no sidecars."""
        vocab = self.ctx.vocab
        profile = self._profile(session)
        check = self._finish(session)
        documents = [{"id": d.id, "name": d.name} for d in session.documents]
        views = field_views(
            profile, counters=session.counters.model_dump(mode="json"), vocab=vocab, documents=documents
        )
        verdict = session.scope.verdict
        state = {
            "placement": session.placement.model_dump(mode="json"),
            "profile": profile,
            "last_question": session.last_question.model_dump(mode="json"),
            "messages": [m.model_dump(mode="json") for m in session.messages],
        }
        armed = cluster_armed(state, vocab=vocab)
        cluster = vocab.taxonomy.by_code(armed) if armed else None
        return SessionOut(
            id=session.id,
            status=session.status,
            phase=session.phase,
            display_name=session.display_name,
            created_at=session.created_at,
            updated_at=session.updated_at,
            finished_at=session.finished_at,
            messages=[MessageOut(id=m.id, role=m.role.value, text=m.text, at=m.at) for m in session.messages],
            profile=_strip_internals(profile),
            field_views=[FieldView.model_validate(v) for v in views],
            score=ScoreOut(
                value=session.score.value,
                filled_points=session.score.filled_points,
                total_points=session.score.total_points,
            ),
            finish=FinishState(ready=check.ready, blocked_by=check.blocked_by, looks_like_task=check.looks_like_task),  # pyright: ignore[reportArgumentType]
            scope=ScopeOut(verdict=verdict.verdict, widened=session.scope.widening_asked) if verdict else None,
            cluster_proposal=(
                ClusterOut(code=cluster.code, name=cluster.name, description=cluster.description) if cluster else None
            ),
            report_status=session.report.status if session.report else None,
        )
