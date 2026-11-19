"""Shared fixtures for the API tests: the real app with a service on the in-memory store and a scripted model (spec 15 §7, spec 16 §7).

Why: every route test must go through the real app (middleware, error handlers, access
dependencies, rate limits) while the model and the store stay deterministic, so the service is
built on `MemoryRepository` and `FakeLLM` and swapped in through the `get_service` dependency.
What: `ApiHarness` (the client, the service, the store, the fake model, a ticking clock) and
helpers to send visitor keys and seed sessions built with the real profile writers.
Must not: patch a route, a node or a writer; nothing here talks to Azure.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.process_discovery_routes import get_service
from app.core.config import CompanyConfig, load_company_config
from app.core.rate_limit import BudgetTracker
from app.core.settings import Settings
from app.main import create_app
from app.models.process_discovery_schemas import Message, Profile, Session
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.interview.graph import build_graph
from app.services.process_discovery.service import DiscoveryService, build_context
from app.services.store.memory import MemoryRepository

NIG = Path(__file__).resolve().parents[3] / "config" / "nig"
KEY_A = "visitor-a-0123456789abcdef"
KEY_B = "visitor-b-0123456789abcdef"
START = datetime(2026, 11, 19, 10, 0, tzinfo=UTC)


def visitor(key: str = KEY_A) -> dict[str, str]:
    return {"X-Visitor-Key": key}


class TickingClock:
    """A clock that moves one second per reading, so "newest first" is deterministic."""

    def __init__(self) -> None:
        self._ticks = itertools.count()

    def __call__(self) -> str:
        return (START + timedelta(seconds=next(self._ticks))).isoformat()


@dataclass
class ApiHarness:
    client: TestClient
    service: DiscoveryService
    repo: MemoryRepository
    llm: FakeLLM | None
    settings: Settings
    company: CompanyConfig
    budget: BudgetTracker
    extra: dict[str, Any] = field(default_factory=dict)

    def create(self, key: str = KEY_A, **body: Any) -> dict[str, Any]:
        response = self.client.post("/api/sessions", json=body, headers=visitor(key))
        assert response.status_code == 201, response.text
        return response.json()

    async def seed(self, owner: str, **update: Any) -> Session:
        """Store a session for `owner` with fields given as model values (profile as a dict)."""
        now = self.service.clock()
        data: dict[str, Any] = {"owner_id": owner, "created_at": now, "updated_at": now}
        if "profile" in update:
            update["profile"] = Profile.model_validate(update["profile"])
        data.update(update)
        session = Session(**data)
        if not session.messages:
            session = session.model_copy(
                update={"messages": [Message.model_validate({"role": "agent", "text": "Welcome", "at": now})]}
            )
        return await self.repo.create_session(session)


@pytest.fixture(scope="session")
def company() -> CompanyConfig:
    return load_company_config(NIG)


def make_settings(**values: Any) -> Settings:
    values.setdefault("company_config_dir", str(NIG))
    values.setdefault("frontend_dist", "/nonexistent-frontend-dist")
    return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


def build_harness(company: CompanyConfig, *, unconfigured: bool = False, **settings_values: Any) -> ApiHarness:
    """The app with a service on a fresh memory store; the fake model reports to the app's budget."""
    settings_values.setdefault("rate_limit_per_visitor", "1000/minute")
    settings_values.setdefault("rate_limit_per_ip", "1000/minute")
    settings = make_settings(**settings_values)
    app = create_app(settings)
    budget: BudgetTracker = app.state.budget
    llm = None if unconfigured else FakeLLM(budget_guard=budget.guard, usage_hook=budget.record)
    ctx = build_context(company, settings)
    repo = MemoryRepository(retention_days=settings.session_retention_days)
    graph = build_graph(llm, ctx) if llm is not None else None
    service = DiscoveryService(repo, llm, ctx, graph, clock=TickingClock())
    app.dependency_overrides[get_service] = lambda: service
    return ApiHarness(TestClient(app), service, repo, llm, settings, company, budget)


@pytest.fixture
def api(company: CompanyConfig) -> ApiHarness:
    return build_harness(company)
