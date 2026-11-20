"""Seeding the demo overview with finished evaluation sessions, only when asked (spec 24 §3.12).

Why: the workspace and the overview look empty on a fresh demo, and a finished simulated interview
is a realistic example. But demo data must never be mistaken for a real employee's interview, and
the store must not fill up with copies, so seeding is explicit, picky and idempotent.
What: `seedable` (a `seed: true` persona that finished, with report quality ≥ 85 % and no loop) and
`seed`, which writes each stored session under the owner `sha256(EVAL_SEED_VISITOR_KEY)` with the
fixed id `eval-<persona id>` and `simulated: true`, replacing an existing copy (delete, then create).
Ideas are not seeded.
Must not: run without `--seed-cosmos`, outside an in-process run, or touch any other document.
Spec 24 §3.12; AC-24.26.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any, Protocol

from .persona import Persona
from .scorecard import QUALITY_TARGET, PersonaScore


class SeedRepository(Protocol):
    async def delete_session(self, owner_id: str, session_id: str, etag: str | None = None) -> bool: ...
    async def create_session(self, session: Any) -> Any: ...


def seedable(persona: Persona, score: PersonaScore) -> bool:
    return (
        persona.seed and score.status == "finished" and score.quality >= QUALITY_TARGET and score.behaviour.loops == 0
    )


async def seed(
    entries: Sequence[tuple[Persona, PersonaScore, Any]], repository: SeedRepository, visitor_key: str
) -> list[str]:
    """Write each seedable stored session (a `Session` model); returns the ids written."""
    owner = hashlib.sha256(visitor_key.encode("ascii")).hexdigest()
    written: list[str] = []
    for persona, score, session in entries:
        if session is None or not seedable(persona, score):
            continue
        session_id = f"eval-{persona.id}"
        copy = session.model_copy(
            deep=True, update={"id": session_id, "owner_id": owner, "simulated": True, "etag": None}
        )
        await repository.delete_session(owner, session_id)
        await repository.create_session(copy)
        written.append(session_id)
    return written
