"""Playing one persona: document timing, the *Finish* rule, snapshots, artefacts, isolated failures (spec 24 §3.5, §3.6; AC-24.5, AC-24.6, AC-24.9, AC-24.27, AC-24.30).

Why: the order of actions changes the scores, so it is pinned against a fake driver whose phase,
readiness and *Finish* answers follow a script. What: `FakeDriver` (a session that moves phase by
message count and records every call) with `FakeLLM` as the expert. Must not: call a model.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.llm import CallType, LLMUnavailableError
from eval.evalkit.persona import HARD_CAP, PersonaDocument
from eval.evalkit.play import play

from .conftest import make_persona


class FakeDriver:
    """phase_at(n) and ready_at decide the session after n messages; finish answers from `finish_codes`."""

    capture = None

    def __init__(self, phase_at=lambda n: "context", ready_at: int | None = None, finish_codes=(200,), agent="Next?"):
        self.phase_at, self.ready_at, self.finish_codes = phase_at, ready_at, list(finish_codes)
        self.agent = agent
        self.n = 0
        self.log: list[tuple[str, Any]] = []
        self.status = "active"

    def _out(self) -> dict[str, Any]:
        ready = self.ready_at is not None and self.n >= self.ready_at
        return {
            "id": "s1",
            "status": self.status,
            "phase": "finished" if self.status == "finished" else self.phase_at(self.n),
            "messages": [{"role": "agent", "text": self.agent}],
            "profile": {"n": self.n},
            "fieldViews": [],
            "score": {"value": self.n / 100},
            "finish": {"ready": ready},
            "clusterProposal": None,
        }

    async def create(self, display_name):
        self.log.append(("create", display_name))
        return self._out()

    async def get(self, session_id):
        self.log.append(("get", self.n))
        return self._out()

    async def send(self, session_id, text):
        self.n += 1
        self.log.append(("send", text))
        return {"session": self._out()}, 0.01

    async def upload(self, session_id, path: Path):
        self.log.append(("upload", path.name))
        return {"session": self._out(), "report": {"conflicts": 1}}, 0.01

    async def finish(self, session_id):
        code = self.finish_codes.pop(0) if self.finish_codes else 200
        self.log.append(("finish", code))
        if code == 200:
            self.status = "finished"
            return 200, self._out(), 0.5
        return 409, {"code": "map_incomplete", "reason": "roles_not_confirmed"}, 0.1

    async def report(self, session_id):
        return {"steps": {"rows": []}}, b"%PDF-fake"

    async def ideas(self, session_id):
        return []

    async def stored(self, session_id):
        return None

    def last_call(self, session_id):
        return ""


def expert(n: int = 70) -> FakeLLM:
    return FakeLLM({CallType.EXPERT: [f"answer {i}" for i in range(1, n + 1)]})


def _uploads(driver: FakeDriver) -> list[int]:
    """How many messages had been sent when each upload happened."""
    sent, at = 0, []
    for kind, _ in driver.log:
        if kind == "send":
            sent += 1
        elif kind == "upload":
            at.append(sent)
    return at


def _persona_with(at: dict[str, Any]):
    persona = make_persona()
    persona.documents = [PersonaDocument(file="access_review_procedure_2023.md", at=at)]
    return persona


async def test_ac_24_5_documents_are_uploaded_once_at_their_moment():
    phases = lambda n: "steps" if n >= 4 else "measure"  # noqa: E731
    for at, expected in (({"start": True}, [0]), ({"turn": 3}, [2]), ({"phase": "steps"}, [4])):
        driver = FakeDriver(phase_at=phases, ready_at=None)
        run = await play(_persona_with(at), driver, expert(), None)  # pyright: ignore[reportArgumentType]
        assert _uploads(driver) == expected, at
        assert len(run.uploads) == 1


async def test_ac_24_6_finish_waits_for_review_answers_and_records_a_409():
    driver = FakeDriver(phase_at=lambda n: "review" if n >= 5 else "steps", ready_at=5, finish_codes=(409, 200))
    run = await play(make_persona(), driver, expert(), None)  # pyright: ignore[reportArgumentType]
    finishes = [i for i, (kind, _) in enumerate(driver.log) if kind == "finish"]
    assert run.status == "finished"
    assert run.finish_409 == [{"n": 8, "reason": "roles_not_confirmed"}]
    assert run.messages_to_finish == 9  # 5 to reach review, 3 review answers, one more after the 409
    assert len(finishes) == 2


async def test_ac_24_6_review_ends_early_when_the_agent_stops_asking():
    driver = FakeDriver(phase_at=lambda n: "review" if n >= 5 else "steps", ready_at=5, agent="All set. Press Finish.")
    run = await play(make_persona(), driver, expert(), None)  # pyright: ignore[reportArgumentType]
    assert run.messages_to_finish == 5


async def test_ac_24_6_no_finish_within_the_hard_cap_is_never_finished():
    driver = FakeDriver(phase_at=lambda n: "steps", ready_at=None)
    run = await play(make_persona(), driver, expert(), None)  # pyright: ignore[reportArgumentType]
    assert run.status == "never_finished" and run.messages == HARD_CAP
    assert sum(1 for kind, _ in driver.log if kind == "send") == HARD_CAP  # never a 61st message


async def test_ac_24_6_ready_at_the_cap_presses_finish_before_passing_it():
    driver = FakeDriver(phase_at=lambda n: "steps", ready_at=HARD_CAP)
    run = await play(make_persona(), driver, expert(), None)  # pyright: ignore[reportArgumentType]
    assert run.status == "finished" and run.messages_to_finish == HARD_CAP


async def test_ac_24_30_a_snapshot_after_every_message_and_upload(tmp_path):
    driver = FakeDriver(phase_at=lambda n: "review" if n >= 3 else "steps", ready_at=3, agent="Done.")
    run = await play(_persona_with({"turn": 2}), driver, expert(), tmp_path)  # pyright: ignore[reportArgumentType]
    assert [(s.n, s.event) for s in run.snapshots] == [
        (0, "start"),
        (1, "message"),
        (1, "upload"),
        (2, "message"),
        (3, "message"),
    ]
    assert run.messages == 3  # GETs and the upload are not messages
    lines = (tmp_path / "tiny" / "snapshots.jsonl").read_text().splitlines()
    assert len(lines) == 5 and '"fieldViews"' in lines[0]


async def test_ac_24_9_artefacts_are_written(tmp_path):
    driver = FakeDriver(phase_at=lambda n: "review" if n >= 2 else "steps", ready_at=2, agent="Done.")
    await play(make_persona(), driver, expert(), tmp_path)  # pyright: ignore[reportArgumentType]
    folder = tmp_path / "tiny"
    for name in (
        "transcript.md",
        "transcript.json",
        "turns.jsonl",
        "snapshots.jsonl",
        "session.json",
        "report.json",
        "report.pdf",
    ):
        assert (folder / name).exists(), name
    assert (folder / "report.pdf").read_bytes() == b"%PDF-fake"


async def test_ac_24_27_one_persona_failing_does_not_stop_the_others(tmp_path):
    broken = FakeLLM({CallType.EXPERT: [LLMUnavailableError(503)]})
    good, bad = FakeDriver(lambda n: "review", 1, agent="Done."), FakeDriver(lambda n: "steps", None)
    runs = await asyncio.gather(
        play(make_persona(id="bad"), bad, broken, tmp_path),  # pyright: ignore[reportArgumentType]
        play(make_persona(id="good"), good, expert(), tmp_path),  # pyright: ignore[reportArgumentType]
    )
    assert runs[0].status == "error" and "ExpertError" in runs[0].error
    assert runs[1].status == "finished"
    assert (tmp_path / "bad" / "session.json").exists()
