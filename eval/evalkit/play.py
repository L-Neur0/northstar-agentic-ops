"""Plays one persona through the API: messages, uploads, snapshots, *Finish*, artefacts (spec 24 §3.5, §3.6).

Why: the order of actions decides what is measured. A document uploaded one turn late, a *Finish*
pressed before the review, or a snapshot missed after an upload would each change the scores
without any change in the product, so the order is fixed here, in one place, and tested.
What: `play` loops until *Finish* or `HARD_CAP` expert messages: it uploads any document now due,
else gets the expert's reply (code first, rule E6, then the EXPERT call) and sends it; after every
message and upload it reads `GET /api/sessions/{id}` and keeps a snapshot; it presses *Finish* when
`finish.ready` is true in the review phase after the review has run (at most 3 review answers), or
before the message that would pass the cap; a 409 is recorded and the loop goes on. Then it reads
the report and writes the artefacts. One persona failing never raises: it ends as `error` or
`rate_limited`.
Must not: show the expert anything but the conversation (`expert.py` decides what it sees), write
to the session except through the API, or count a GET, an upload or *Finish* as a message.
Spec 24 §3.5, §3.6; AC-24.5, AC-24.6, AC-24.9, AC-24.27, AC-24.30.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.services.process_discovery.llm import LLM

from .driver import PERSONA, Driver, RateLimited
from .expert import code_reply, expert_reply
from .persona import EVAL_DIR, HARD_CAP, Persona, PersonaDocument

REVIEW_ANSWERS = 3
APP_EXCLUDED = ("EXPERT", "JUDGE")


@dataclass
class Snapshot:
    n: int
    event: str  # start | message | upload
    phase: str
    score: float
    filledPoints: int
    totalPoints: int
    finish: dict[str, Any]
    profile: dict[str, Any]
    fieldViews: list[dict[str, Any]]


@dataclass
class PersonaRun:
    persona_id: str
    status: str = "running"  # finished | never_finished | error | rate_limited
    error: str = ""
    session_id: str = ""
    messages: int = 0  # expert messages sent (rule: POST .../messages only)
    messages_to_finish: int | None = None
    finish_seconds: float | None = None
    finish_cached: bool = False
    finish_409: list[dict[str, Any]] = field(default_factory=list)
    turns: list[dict[str, Any]] = field(default_factory=list)
    snapshots: list[Snapshot] = field(default_factory=list)
    uploads: list[dict[str, Any]] = field(default_factory=list)
    code_replies: list[int] = field(default_factory=list)  # message numbers answered by rule E6
    transcript: list[dict[str, Any]] = field(default_factory=list)
    session: dict[str, Any] = field(default_factory=dict)
    stored: dict[str, Any] | None = None
    ideas: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] | None = None
    pdf: bytes = field(default=b"", repr=False)
    logs: list[dict[str, Any]] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.status == "finished"


def due(doc: PersonaDocument, n: int, phase: str) -> bool:
    """Is this document due before expert message `n + 1`? (AC-24.5)"""
    if doc.at.get("start"):
        return n == 0
    if "turn" in doc.at:
        return n + 1 >= int(doc.at["turn"])
    return phase == doc.at.get("phase")


def snapshot(n: int, event: str, out: Mapping[str, Any]) -> Snapshot:
    score = out.get("score") or {}
    return Snapshot(
        n=n,
        event=event,
        phase=str(out.get("phase", "")),
        score=float(score.get("value", 0.0)),
        filledPoints=int(score.get("filledPoints", 0)),
        totalPoints=int(score.get("totalPoints", 0)),
        finish=dict(out.get("finish") or {}),
        profile=dict(out.get("profile") or {}),
        fieldViews=list(out.get("fieldViews") or []),
    )


def _turn_record(
    run: PersonaRun, driver: Driver, sid: str, out: Mapping[str, Any], seconds: float, event: str
) -> dict[str, Any]:
    logs = driver.capture.for_call(driver.last_call(sid)) if driver.capture else []
    calls = [r for r in logs if r["event"] == "llm_call" and r.get("call_type") not in APP_EXCLUDED]
    turn_log = next((r for r in logs if r["event"] == "interview_turn"), {})
    focus = list(turn_log.get("focus") or [])
    views = {v.get("key"): v for v in out.get("fieldViews") or []}
    return {
        "n": run.messages,
        "event": event,
        "wall_ms": int(seconds * 1000),
        "phase": out.get("phase"),
        "finish": out.get("finish"),
        "focus": focus,
        "asks": {k: int(views.get(k, {}).get("asks", 0)) for k in focus},
        "app_calls": len(calls),
        "cache_hits": sum(1 for r in calls if r.get("outcome") == "cache_hit"),
        # a turn counts for timing only when none of its app calls was a cache hit (URL mode: no cache)
        "uncached": driver.capture is None or (bool(calls) and all(r.get("outcome") != "cache_hit" for r in calls)),
        "tokens_in": sum(int(r.get("prompt_tokens") or 0) for r in calls),
        "tokens_out": sum(int(r.get("completion_tokens") or 0) for r in calls),
        "fallback_used": bool(turn_log.get("fallback_used", False)),
        "proposals_confirmed": len(turn_log.get("proposals_confirmed") or []),
        "proposals_rejected": len(turn_log.get("proposals_rejected") or []),
    }


async def play(persona: Persona, driver: Driver, expert_llm: LLM, out_dir: Path | None = None) -> PersonaRun:
    """Play one persona; never raises for a persona-level failure (AC-24.27)."""
    run = PersonaRun(persona.id)
    token = PERSONA.set(persona.id)
    try:
        await _loop(persona, driver, expert_llm, run)
    except RateLimited as error:
        run.status, run.error = "rate_limited", str(error)
    except Exception as error:  # an EXPERT failure, a timeout, a 5xx: this persona only
        run.status, run.error = "error", f"{type(error).__name__}: {str(error)[:200]}"
    finally:
        PERSONA.reset(token)
    if driver.capture is not None:
        run.logs = driver.capture.for_persona(persona.id)
    if out_dir is not None:
        write_artefacts(run, out_dir / persona.id)
    return run


async def _loop(persona: Persona, driver: Driver, expert_llm: LLM, run: PersonaRun) -> None:
    session = await driver.create(persona.id)
    sid = run.session_id = session["id"]
    run.snapshots.append(snapshot(0, "start", session))
    pending = list(persona.documents)
    uploaded: list[str] = []
    review_answers = 0
    while session.get("status") == "active":
        for doc in [d for d in pending if due(d, run.messages, str(session.get("phase")))]:
            body, seconds = await driver.upload(sid, EVAL_DIR / "documents" / doc.file)
            pending.remove(doc)
            uploaded.append(doc.file)
            session = body["session"]
            run.uploads.append({"n": run.messages, "file": doc.file, "report": body.get("report"), "seconds": seconds})
            run.turns.append(_turn_record(run, driver, sid, session, seconds, "upload"))
            run.snapshots.append(snapshot(run.messages, "upload", await driver.get(sid)))
        ready = bool((session.get("finish") or {}).get("ready"))
        in_review = session.get("phase") == "review"
        last_agent = next((m for m in reversed(session.get("messages") or []) if m.get("role") == "agent"), {})
        review_done = in_review and (review_answers >= REVIEW_ANSWERS or "?" not in str(last_agent.get("text", "")))
        if ready and (review_done or run.messages >= HARD_CAP):
            status, body, seconds = await driver.finish(sid)
            logs = driver.capture.for_call(driver.last_call(sid)) if driver.capture else []
            if status == 200:
                run.status, run.messages_to_finish, run.finish_seconds = "finished", run.messages, seconds
                run.finish_cached = any(r.get("outcome") == "cache_hit" for r in logs if r["event"] == "llm_call")
                session = body
                break
            run.finish_409.append({"n": run.messages, "reason": body.get("reason")})
        if run.messages >= HARD_CAP:
            break
        reply = code_reply(persona, session)
        if reply is not None:
            run.code_replies.append(run.messages + 1)
        else:
            reply = await expert_reply(persona, session.get("messages") or [], uploaded, expert_llm)
        turn, seconds = await driver.send(sid, reply)
        run.messages += 1
        if in_review:
            review_answers += 1
        session = turn["session"]
        run.turns.append(_turn_record(run, driver, sid, session, seconds, "message"))
        run.snapshots.append(snapshot(run.messages, "message", await driver.get(sid)))
    if run.status == "running":
        run.status = "never_finished"
    run.session = await driver.get(sid)
    run.transcript = list(run.session.get("messages") or [])
    run.stored = await driver.stored(sid)
    run.ideas = await driver.ideas(sid)
    if run.finished:
        run.report, run.pdf = await driver.report(sid)


def _jsonl(path: Path, rows: list[Any]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def write_artefacts(run: PersonaRun, folder: Path) -> None:
    """The per-persona files of §3.6 (score.json and curve.json are written after scoring)."""
    folder.mkdir(parents=True, exist_ok=True)
    phases = {s.n: s.phase for s in run.snapshots}
    lines = [f"# {run.persona_id} ({run.status})", ""]
    expert_n = 0
    rows: list[dict[str, Any]] = []
    for message in run.transcript:
        if message.get("role") == "expert":
            expert_n += 1
        phase = phases.get(expert_n, "")
        rows.append({"turn": expert_n, "phase": phase, "role": message.get("role"), "text": message.get("text")})
        lines.append(f"**{message.get('role')}** (turn {expert_n}, {phase}): {message.get('text')}\n")
    (folder / "transcript.md").write_text("\n".join(lines), encoding="utf-8")
    (folder / "transcript.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    _jsonl(folder / "turns.jsonl", run.turns)
    _jsonl(folder / "snapshots.jsonl", [asdict(s) for s in run.snapshots])
    (folder / "session.json").write_text(
        json.dumps({"sessionOut": run.session, "stored": run.stored, "error": run.error}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if run.report is not None:
        (folder / "report.json").write_text(json.dumps(run.report, indent=2, ensure_ascii=False), encoding="utf-8")
        (folder / "report.pdf").write_bytes(run.pdf)
