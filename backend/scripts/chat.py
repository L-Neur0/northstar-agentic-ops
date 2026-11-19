"""`make chat`: the interview in the terminal, driven exactly as the API drives it (spec 14 §3.12).

Why: prompts and the turn are tuned by talking to them; a terminal runner that uses `welcome`,
`run_turn` and `after_action` exactly as the service does, on an in-memory session, lets anyone try
the interview without the web app, and with a scripted model (`--fake`) it is testable.
What: reads expert messages from stdin, prints each agent reply and one status line
(`phase=… score=… (x/y) finish=… ask=… asks=…`), and handles the commands `/profile`,
`/confirm roles|systems`, `/cluster CODE`, `/finish`, `/save PATH`, `/load PATH` and `/quit`.
End of input exits cleanly (0). Against the real model it runs in stage `local`, so the LLM cache
is on. Must not: store anything outside the files named by `/save`, or log message text.
Spec 14 §3.12; AC-14.57.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

from app.core.config import load_company_config  # noqa: E402
from app.core.settings import Settings  # noqa: E402
from app.models.process_discovery_schemas import Message, Profile, Session  # noqa: E402
from app.services.process_discovery.domain.field_spec import Vocabulary  # noqa: E402
from app.services.process_discovery.fake_llm import FakeLLM  # noqa: E402
from app.services.process_discovery.interview.graph import build_graph  # noqa: E402
from app.services.process_discovery.interview.phases import ask_count, read_counters  # noqa: E402
from app.services.process_discovery.interview.replies import Lexicon  # noqa: E402
from app.services.process_discovery.interview.turn import after_action, run_turn, welcome  # noqa: E402
from app.services.process_discovery.interview.types import Ask, InterviewContext, InterviewSettings  # noqa: E402
from app.services.process_discovery.llm import LLM, CallType, LLMBudgetExceededError, create_llm  # noqa: E402
from app.services.process_discovery.profile.mutate import UnknownClusterError, confirm_rollup, set_cluster  # noqa: E402
from app.services.process_discovery.profile.scoring import finish_check  # noqa: E402
from app.services.process_discovery.profile.views import field_views  # noqa: E402


def _now() -> str:
    return datetime.now(UTC).isoformat()


def load_fake(path: Path) -> FakeLLM:
    """A `FakeLLM` from a YAML file: `{EXTRACT: [...], CLASSIFY: [...], GUIDE: [...]}`."""
    script: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return FakeLLM({CallType[str(k)]: list(v or []) for k, v in script.items()})


def status_line(session: Session, ctx: InterviewContext) -> str:
    """`phase=measure score=0.48 (30/62) finish=below_gate ask=process.volume asks=1`."""
    profile = session.profile.model_dump(mode="json", by_alias=True)
    finish = finish_check(profile, vocab=ctx.vocab, scope=session.scope.model_dump(mode="json"))
    question = session.last_question
    keys = tuple(question.focus or question.proposals)
    ask = Ask("rollups" if any(k.startswith("process.all_") for k in keys) else "field", keys)
    asks = ask_count(ask, read_counters(session.counters.model_dump()))
    sc = session.score
    return (
        f"phase={session.phase.value} score={sc.value:.2f} ({sc.filled_points}/{sc.total_points}) "
        f"finish={finish.blocked_by or 'ready'} ask={keys[0] if keys else '-'} asks={asks}"
    )


def _with_profile(session: Session, profile: dict[str, Any], ctx: InterviewContext) -> Session:
    return after_action(session.model_copy(update={"profile": Profile.model_validate(profile)}), ctx=ctx)


def command(line: str, session: Session, ctx: InterviewContext, out: IO[str]) -> tuple[Session, bool]:
    """Run one `/command`; returns the session and whether to quit."""
    name, _, arg = line.strip().partition(" ")
    arg = arg.strip()
    profile = session.profile.model_dump(mode="json", by_alias=True)
    if name == "/quit":
        return session, True
    if name == "/profile":
        documents = [{"id": d.id, "name": d.name} for d in session.documents]
        for view in field_views(profile, counters=session.counters.model_dump(), vocab=ctx.vocab, documents=documents):
            reason = f" - {view['reason']}" if view["reason"] else ""
            print(f"{view['key']}: {view['status']}{reason}", file=out)
    elif name == "/confirm" and arg in ("roles", "systems"):
        session = _with_profile(session, confirm_rollup(profile, arg, vocab=ctx.vocab), ctx)
        print(f"confirmed {arg}", file=out)
    elif name == "/cluster" and arg:
        try:
            changed = set_cluster(profile, arg, decided_by="picker", vocab=ctx.vocab, at=_now())
        except UnknownClusterError:
            print(f"unknown cluster {arg!r}; codes: {', '.join(ctx.vocab.taxonomy.codes())}", file=out)
        else:
            session = _with_profile(session, changed, ctx)
            print(f"cluster set to {arg.upper()}", file=out)
    elif name == "/finish":
        check = finish_check(profile, vocab=ctx.vocab, scope=session.scope.model_dump(mode="json"))
        print(f"ready={check.ready} blocked_by={check.blocked_by} looks_like_task={check.looks_like_task}", file=out)
    elif name == "/save" and arg:
        Path(arg).write_text(session.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
        print(f"saved to {arg}", file=out)
    elif name == "/load" and arg:
        session = Session.model_validate_json(Path(arg).read_text(encoding="utf-8"))
        print(f"loaded {arg}", file=out)
    else:
        print(
            "commands: /profile, /confirm roles|systems, /cluster CODE, /finish, /save PATH, /load PATH, /quit",
            file=out,
        )
        return session, False
    print(status_line(session, ctx), file=out)
    return session, False


async def chat(llm: LLM, ctx: InterviewContext, stdin: IO[str], out: IO[str]) -> int:
    """The loop: welcome, then one turn per line until `/quit` or end of input."""
    graph = build_graph(llm, ctx)
    text, question = welcome(None, ctx)
    now = _now()
    session = Session(owner_id="local-chat", created_at=now, updated_at=now, last_question=question)
    session = session.model_copy(
        update={"messages": [Message.model_validate({"role": "agent", "text": text, "at": now})]}
    )
    print(f"agent> {text}", file=out)
    print(status_line(session, ctx), file=out)
    for raw in stdin:
        line = raw.rstrip("\n")
        if line.startswith("/"):
            session, stop = command(line, session, ctx, out)
            if stop:
                return 0
            continue
        try:
            result = await run_turn(session, line, llm=llm, graph=graph, ctx=ctx, now=_now())
        except LLMBudgetExceededError:
            print("The daily model budget is used up; nothing was saved for that message.", file=out)
            continue
        session = result.session
        print(f"agent> {result.reply}", file=out)
        for idea in result.ideas:
            print(f"idea> {idea['name']}", file=out)
        print(status_line(session, ctx), file=out)
    return 0


def main(argv: list[str] | None = None, stdin: IO[str] | None = None, out: IO[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The Discovery Agent interview in the terminal.")
    parser.add_argument("--fake", type=Path, help="run with a scripted FakeLLM from this YAML file")
    args = parser.parse_args(argv)
    settings = Settings()
    company = load_company_config(settings.company_config_dir)
    vocab = Vocabulary(taxonomy=company.taxonomy, regions=company.organisation.regions, wording=company.wording)
    ctx = InterviewContext(
        vocab=vocab,
        lexicon=Lexicon.from_config(company.language),
        settings=InterviewSettings(),
        product_name=company.organisation.product_name,
    )
    llm: LLM = load_fake(args.fake) if args.fake else create_llm(settings)

    async def run() -> int:
        try:
            return await chat(llm, ctx, stdin or sys.stdin, out or sys.stdout)
        finally:
            await llm.aclose()

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
