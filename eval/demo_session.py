"""A ready-to-finish demo session from an evaluation run (spec 24 §13, D1-D4).

Why: the product owner demos the tool by opening an interview a simulated employee already did (the
conversation on the left, the filled form on the right) and pressing *Finish* live, so the audience
sees the report being made. Typing a whole interview in front of an audience is slow; a recorded run
is the real thing, as the product stored it.
What: `demo_copy` turns a stored, finished session into an active one in `review` (no assessment,
report, briefs or finish time, never expiring), owned by the demo key and tagged *Simulated*;
`write_demo` replaces `demo-<persona>` in the store; `main` is the CLI and writes to Cosmos.
Must not: write anything when the session could not press *Finish*, drop the *Simulated* tag, print
or log the key, or touch any other document. Spec 24 §13; AC-24.57, AC-24.58.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Protocol

from app.models.process_discovery_schemas import Phase, Session, SessionStatus

RUNS_DIR = Path(__file__).resolve().parent / "runs"
FINISH_GATE = 0.8  # product: Finish needs 80 % of the points
KEY_MIN = 22


class DemoRepository(Protocol):
    async def delete_session(self, owner_id: str, session_id: str, etag: str | None = None) -> bool: ...
    async def create_session(self, session: Session) -> Any: ...


def demo_copy(stored: dict[str, Any], key: str, *, persona_id: str, name: str) -> Session:
    """The D2 copy of a stored session (camelCase as `session.json` holds it); the input is not changed."""
    session = Session.model_validate(stored)
    if session.score.value < FINISH_GATE:
        raise ValueError(f"the stored session cannot press Finish (score {session.score.value:.0%})")
    owner = hashlib.sha256(key.encode("ascii")).hexdigest()
    return session.model_copy(
        deep=True,
        update={
            "id": f"demo-{persona_id}",
            "owner_id": owner,
            "display_name": name[:40],
            "simulated": True,
            "status": SessionStatus.ACTIVE,
            "phase": Phase.REVIEW,
            "finished_at": None,
            "assessment": None,
            "report": None,
            "briefs": [],
            "ttl": None,
            "etag": None,
        },
    )


async def write_demo(session: Session, repository: DemoRepository) -> None:
    """Replace `demo-<persona>` for its owner: delete, then create."""
    await repository.delete_session(session.owner_id, session.id)
    await repository.create_session(session)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval.demo_session", description="Write a ready-to-finish demo session."
    )
    parser.add_argument("--run", required=True, help="run id under eval/runs/")
    parser.add_argument("--persona", required=True)
    parser.add_argument("--name", default="Demo", help="display name shown in My processes")
    args = parser.parse_args(argv)
    key = os.environ.get("EVAL_SEED_VISITOR_KEY", "")
    if len(key) < KEY_MIN:
        print("demo: EVAL_SEED_VISITOR_KEY (22+ characters) is not set; nothing written", file=sys.stderr)
        return 2
    path = RUNS_DIR / args.run / args.persona / "session.json"
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))["stored"]
        session = demo_copy(stored, key, persona_id=args.persona, name=args.name)
    except (OSError, KeyError, ValueError) as error:
        print(f"demo: cannot build the copy: {error}", file=sys.stderr)
        return 2
    return asyncio.run(_write(session))


async def _write(session: Session) -> int:
    from app.services.store.cosmos import open_cosmos

    from .run import base_settings

    settings = base_settings()
    store = await open_cosmos(settings.model_copy(update={"store": "cosmos"}))
    try:
        await write_demo(session, store)
    finally:
        await store.close()
    print(f"demo: wrote {session.id} ({len(session.messages)} messages, score {session.score.value:.0%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
