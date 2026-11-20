"""Seeding is explicit, picky and idempotent, and marks sessions as simulated (spec 24 §3.12; AC-24.26).

Why: demo data must never pass for a real interview or pile up. What: a fake repository records
deletes and creates; personas and scores decide what is seeded. Must not: touch Cosmos.
"""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel

from eval.evalkit.seed import seed

from .conftest import make_persona
from .test_scorecard import persona_score

KEY = "seed-key-0123456789abcdef"


class FakeSession(BaseModel):
    id: str = "orig"
    owner_id: str = "someone"
    simulated: bool = False
    etag: str | None = "e1"


class FakeRepo:
    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], Any] = {}

    async def delete_session(self, owner_id: str, session_id: str, etag: str | None = None) -> bool:
        return self.docs.pop((owner_id, session_id), None) is not None

    async def create_session(self, session: Any) -> Any:
        self.docs[(session.owner_id, session.id)] = session
        return session


async def test_ac_24_26_only_good_seed_personas_are_written_marked_simulated_and_once():
    repo = FakeRepo()
    good = (make_persona(id="p01-cooperative"), persona_score(), FakeSession())
    not_seed = (make_persona(id="p02-vague", seed=False), persona_score(id="p02-vague"), FakeSession())
    low = (make_persona(id="p03-low"), persona_score(id="p03-low", quality=0.5), FakeSession())
    failed = (make_persona(id="p04-failed"), persona_score(id="p04-failed", status="never_finished"), FakeSession())
    for _ in range(2):
        written = await seed([good, not_seed, low, failed], repo, KEY)
        assert written == ["eval-p01-cooperative"]
    owner = hashlib.sha256(KEY.encode()).hexdigest()
    assert list(repo.docs) == [(owner, "eval-p01-cooperative")]
    stored = repo.docs[(owner, "eval-p01-cooperative")]
    assert stored.simulated is True and stored.etag is None
