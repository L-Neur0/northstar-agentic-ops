"""Tests for the ready-to-finish demo copy (spec 24 §13, D1-D4).

Why: the product owner demos the tool by opening an interview that a simulated employee already did,
then pressing *Finish* live; the copy must be the real conversation and form, not finished, never
expiring, tagged *Simulated*, and owned by the demo key.
What: `demo_copy` (pure) and `write_demo` against a fake repository.
Must not: reach Cosmos or a model. Covers AC-24.57, AC-24.58.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib

import pytest

from app.models.process_discovery_schemas import Session
from eval.demo_session import demo_copy, write_demo

KEY = "Demovisitorkey01234567"


def stored(score: float = 0.97) -> dict:
    return {
        "id": "9a738edc",
        "ownerId": "someone",
        "status": "finished",
        "phase": "finished",
        "finishedAt": "2026-11-21T10:00:00Z",
        "createdAt": "2026-11-21T09:00:00Z",
        "updatedAt": "2026-11-21T10:00:00Z",
        "displayName": "p05-cv-screening",
        "messages": [{"role": "agent", "text": "Hi", "at": "2026-11-21T09:00:00Z"}],
        "score": {"value": score, "filledPoints": 64, "totalPoints": 66},
    }


def test_ac_24_57_the_copy_is_ready_to_finish():
    raw = stored()
    before = copy.deepcopy(raw)
    session = demo_copy(raw, KEY, persona_id="p05-cv-screening", name="Demo")
    assert isinstance(session, Session)
    assert session.id == "demo-p05-cv-screening"
    assert session.owner_id == hashlib.sha256(KEY.encode("ascii")).hexdigest()
    assert (session.status.value, session.phase.value, session.simulated) == ("active", "review", True)
    assert session.finished_at is None and session.assessment is None and session.ttl is None
    assert session.display_name == "Demo"
    assert [m.text for m in session.messages] == ["Hi"] and session.score.value == 0.97
    assert raw == before


def test_ac_24_58_below_the_gate_is_refused_and_the_write_replaces():
    with pytest.raises(ValueError, match="cannot press Finish"):
        demo_copy(stored(0.5), KEY, persona_id="p05-cv-screening", name="Demo")
    calls: list[tuple[str, str]] = []

    class Repo:
        async def delete_session(self, owner_id: str, session_id: str, etag: str | None = None) -> bool:
            calls.append(("delete", session_id))
            return True

        async def create_session(self, session: Session) -> Session:
            calls.append(("create", session.id))
            return session

    session = demo_copy(stored(), KEY, persona_id="p05-cv-screening", name="Demo")
    asyncio.run(write_demo(session, Repo()))
    assert calls == [("delete", "demo-p05-cv-screening"), ("create", "demo-p05-cv-screening")]
