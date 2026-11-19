"""The expert's routes: sessions, the interview turn, the buttons outside a turn, ideas and "delete my data" (spec 15 part 2 §3.3).

Why: the browser drives the whole interview through these thirteen routes, and each must stay a
thin layer: resolve the caller from the visitor key (spec 16), count the call against the
visitor's limit, call one use case of the discovery service, and return the wire model. Every
route is scoped to the caller, so another visitor's session is "not found" (404), never revealed.
What: `router` (prefix `/api`) and `get_service` (the service built once in the lifespan; tests
override it). Errors are raised by the service and mapped to `{code, message}` in `errors.py`.
Must not: import past the engine facade (layer test, AC-15.50), hold business rules, or log text.
Spec 15 AC-15.27 to AC-15.49; spec 16 AC-16.1, AC-16.4, AC-16.9.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Request, Response, status

from app.api.errors import ApiError
from app.core.access import require_visitor
from app.core.rate_limit import hit
from app.models.process_discovery_wire import (
    ClusterIn,
    ConfirmIn,
    CreateSessionIn,
    DeletedOut,
    IdeaListOut,
    IdeaOut,
    MessageIn,
    MessageOut,
    SessionListOut,
    SessionOut,
    SessionSummaryOut,
    TurnOut,
)
from app.services.process_discovery import DiscoveryService

router = APIRouter(prefix="/api", tags=["process-discovery"])


def get_service(request: Request) -> DiscoveryService:
    """FastAPI dependency: the service built in the lifespan."""
    return request.app.state.service


async def expert(request: Request, owner: str = Depends(require_visitor)) -> str:
    """The caller's `owner_id`, after counting the call against the per-visitor limit (spec 16 §3.3)."""
    settings = request.app.state.settings
    if not hit(request.app.state.limiter, settings.rate_limit_per_visitor, "visitor", owner):
        raise ApiError(429, "rate_limited", "Too many requests. Please wait a moment and try again.")
    return owner


# --- sessions ---------------------------------------------------------------------------------------


@router.post("/sessions", status_code=status.HTTP_201_CREATED, response_model=SessionOut)
async def create_session(
    body: CreateSessionIn | None = Body(default=None),
    owner: str = Depends(expert),
    service: DiscoveryService = Depends(get_service),
) -> SessionOut:
    """Start a session: the fixed welcome, no model call; with `fromIdeaId`, the idea's name is proposed."""
    body = body or CreateSessionIn()
    session = await service.create_session(owner, display_name=body.display_name, from_idea_id=body.from_idea_id)
    return service.view(session)


@router.get("/sessions", response_model=SessionListOut)
async def list_sessions(
    owner: str = Depends(expert), service: DiscoveryService = Depends(get_service)
) -> SessionListOut:
    """The caller's sessions, newest first, summary fields only."""
    rows = await service.list_sessions(owner)
    return SessionListOut(sessions=[SessionSummaryOut.model_validate(r.model_dump()) for r in rows])


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: str, owner: str = Depends(expert), service: DiscoveryService = Depends(get_service)
) -> SessionOut:
    return service.view(await service.get_session(owner, session_id))


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str, owner: str = Depends(expert), service: DiscoveryService = Depends(get_service)
) -> Response:
    """Hard delete; there is no undo."""
    await service.delete_session(owner, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/{session_id}/messages", response_model=TurnOut)
async def send_message(
    session_id: str,
    body: MessageIn,
    owner: str = Depends(expert),
    service: DiscoveryService = Depends(get_service),
) -> TurnOut:
    """One interview turn: screened, run, saved once. 409 `conflict` means reload and resend."""
    result = await service.process_turn(owner, session_id, body.text)
    view = service.view(result.session)
    last = view.messages[-1]
    return TurnOut(reply=MessageOut.model_validate(last.model_dump()), session=view, ideas_added=len(result.ideas))


# --- actions outside a turn ---------------------------------------------------------------------------


@router.post("/sessions/{session_id}/confirm", response_model=SessionOut)
async def confirm(
    session_id: str,
    body: ConfirmIn,
    owner: str = Depends(expert),
    service: DiscoveryService = Depends(get_service),
) -> SessionOut:
    """Confirm the roles or systems list as shown (or close the walk); the phase is recomputed."""
    return service.view(await service.confirm(owner, session_id, body.target))


@router.put("/sessions/{session_id}/cluster", response_model=SessionOut)
async def set_cluster(
    session_id: str,
    body: ClusterIn,
    owner: str = Depends(expert),
    service: DiscoveryService = Depends(get_service),
) -> SessionOut:
    """The cluster picker; an unknown code is 422 `unknown_cluster`."""
    return service.view(await service.set_cluster(owner, session_id, body.code))


@router.post("/sessions/{session_id}/close", response_model=SessionOut)
async def close_session(
    session_id: str, owner: str = Depends(expert), service: DiscoveryService = Depends(get_service)
) -> SessionOut:
    """End a session that found no process to map. Only the expert does this, never the agent."""
    return service.view(await service.close_without_candidate(owner, session_id))


@router.post("/sessions/{session_id}/finish", response_model=SessionOut)
async def finish(
    session_id: str, owner: str = Depends(expert), service: DiscoveryService = Depends(get_service)
) -> SessionOut:
    """*Finish*: 409 `map_incomplete` with `reason` while a condition is open (not an error for the client)."""
    return service.view(await service.finish(owner, session_id))


# --- ideas and data ---------------------------------------------------------------------------------


def _idea_out(idea: object) -> IdeaOut:
    return IdeaOut.model_validate(idea, from_attributes=True)


@router.get("/ideas", response_model=IdeaListOut)
async def list_ideas(owner: str = Depends(expert), service: DiscoveryService = Depends(get_service)) -> IdeaListOut:
    return IdeaListOut(ideas=[_idea_out(i) for i in await service.list_ideas(owner)])


@router.delete("/ideas/{idea_id}", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_idea(
    idea_id: str, owner: str = Depends(expert), service: DiscoveryService = Depends(get_service)
) -> Response:
    await service.dismiss_idea(owner, idea_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/ideas/{idea_id}/start", status_code=status.HTTP_201_CREATED, response_model=SessionOut)
async def start_idea(
    idea_id: str, owner: str = Depends(expert), service: DiscoveryService = Depends(get_service)
) -> SessionOut:
    """A new session with the idea's name proposed; a second start is 409 `idea_started`."""
    return service.view(await service.start_idea(owner, idea_id))


@router.delete("/me", response_model=DeletedOut)
async def delete_my_data(owner: str = Depends(expert), service: DiscoveryService = Depends(get_service)) -> DeletedOut:
    """Every session and idea of the caller (F-23). The owner comes from the key, never from the request."""
    counts = await service.delete_owner_data(owner)
    return DeletedOut(sessions=counts.sessions, ideas=counts.ideas)
