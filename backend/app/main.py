"""The FastAPI app factory: one container serves the API and the built frontend (spec 10 §3.8).

Why: every route, middleware and shared object is assembled in one place, in a fixed order, from
settings checked at start-up. Nothing is created at import time, so tests build an app from
explicit settings and the environment cannot leak in.
What: `create_app(settings)` loads the company config (fail fast), sets up logging and telemetry,
builds the limiter and the daily budget (spec 16), stores shared objects on `app.state` in the
lifespan (the store is opened there once, checked, and closed on shutdown; an unhealthy store is
logged as an error but start-up continues, spec 15 AC-15.22, AC-15.23; then the LLM client with
the budget guard and usage hook, the interview context, the graph and the `DiscoveryService`,
spec 15 part 2 §4; with no model endpoint the service still runs and a turn answers 503), installs
the `{code, message}` error handlers, adds middleware (per-IP limit, correlation id, security
headers, CORS only in local runs), mounts the routers, and serves `frontend/dist` with a page
fallback for any non-API path. Run with `uvicorn app.main:app --factory`.
Must not: hold business logic; routes call the engine facade (spec 15).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.api import document_routes, meta_routes, process_discovery_routes, report_routes, workspace_routes
from app.api.errors import install_error_handlers
from app.core.config import load_company_config
from app.core.logging import configure_logging
from app.core.rate_limit import BudgetTracker, IpLimitMiddleware, build_limiter
from app.core.settings import Settings
from app.core.telemetry import configure_telemetry
from app.services import process_discovery as engine
from app.services.store import create_repository
from app.utils.security_headers import CorrelationIdMiddleware, SecurityHeadersMiddleware

if TYPE_CHECKING:
    from app.services.process_discovery.llm import LLM

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, *, llm: LLM | None = None) -> FastAPI:
    """Build the app. Raises on invalid settings or company configuration.

    `llm` replaces the client the lifespan would build (the evaluation's scripted end-to-end run,
    spec 24 AC-24.28); production passes nothing.
    """
    injected = llm
    settings = settings or Settings()
    company = load_company_config(settings.company_config_dir)
    configure_logging(settings.log_level)
    configure_telemetry(settings)
    limiter = build_limiter(settings)
    budget = BudgetTracker(settings.daily_token_budget, clock=lambda: datetime.now(UTC))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.company = company
        store = await create_repository(settings)
        health = await store.check()
        if not health.ok:
            logger.error(
                "store_unhealthy",
                extra={"store": settings.store, "ttlEnabled": health.ttl_enabled, "detail": health.detail},
            )
        app.state.store = store
        app.state.store_health = health
        try:
            llm = injected or engine.create_llm(settings, budget_guard=budget.guard, usage_hook=budget.record)
        except engine.LLMConfigError as exc:
            logger.error("llm_unavailable", extra={"detail": str(exc)})
            llm = None
        ctx = engine.build_context(company, settings)
        graph = engine.build_graph(llm, ctx) if llm is not None else None
        app.state.service = engine.DiscoveryService(
            store, llm, ctx, graph, clock=lambda: datetime.now(UTC).isoformat(), company=company,
            config_dir=settings.company_config_dir, budget_guard=budget.guard,
            assessment_timeout=settings.assessment_call_timeout_seconds,
        )  # fmt: skip
        try:
            yield
        finally:
            if llm is not None:
                await llm.aclose()
            await store.close()

    app = FastAPI(title="Discovery Agent", version=settings.app_version, lifespan=lifespan)
    # Set state now too, so dependencies work in tests that skip the lifespan.
    app.state.settings = settings
    app.state.company = company
    app.state.limiter = limiter
    app.state.budget = budget
    install_error_handlers(app)

    # Middleware: the last added runs first, so add from innermost to outermost.
    if settings.deployment_stage == "local":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(IpLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.deployment_stage != "local")
    app.add_middleware(CorrelationIdMiddleware)

    app.include_router(meta_routes.router)
    app.include_router(process_discovery_routes.router)
    app.include_router(report_routes.router)
    app.include_router(document_routes.router)
    app.include_router(workspace_routes.router)
    app.include_router(workspace_routes.review)
    _serve_frontend(app, settings.frontend_dist)
    return app


def _serve_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built single-page app; any non-API path returns `index.html`."""
    index = dist / "index.html"

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_not_found(rest: str) -> JSONResponse:
        return JSONResponse({"code": "not_found", "message": f"No API route /api/{rest}"}, status_code=404)

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        if index.exists():
            return FileResponse(index)
        return JSONResponse({"code": "not_found", "message": "Frontend not built"}, status_code=404)


app = create_app
