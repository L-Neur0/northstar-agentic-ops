"""`python -m eval.run`: the evaluation runner's command line (spec 24 §3.5, §3.6, §3.11).

Why: one command must run the whole evaluation the same way every time: check the setup before any
model call (exit 2 on a bad persona, a bad calibration file, or a judge on the expert's deployment),
calibrate the judge, play the personas (in process by default, or against a URL), score them, write
the run folder and the scorecard, and exit 0 only when every target is met. `make eval` calls it.
What: `parse_args` and `run_eval`, which wires the clients (the app's, the EXPERT client with the
disk cache unless `--fresh`, and the JUDGE client with the cache always on), runs the personas at
most `--parallel` at once, scores them, writes `run.json`, `calibration.json`, the per-persona
`score.json` and `curve.json`, the scorecard, and replaces `eval/reports/latest.*` only after a full
in-process run. With `--seed-cosmos` it seeds finished sessions (§3.12).
Must not: seed without the flag, replace `latest.*` after a quick, URL or filtered run, or call a
model before the checks pass.
Spec 24 §3.5, §3.11, §4; AC-24.15, AC-24.16, AC-24.24, AC-24.25.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.settings import BACKEND_DIR, Settings
from app.services.process_discovery.llm import LLM, LLMConfigError, create_llm

from .evalkit.calibrate import CalibrationFileError, calibrate, load_pairs
from .evalkit.driver import PERSONA, InProcessDriver, LogCapture, UrlDriver, in_process_settings
from .evalkit.judge import JUDGE_PROMPT_VERSION, DeploymentClash, Judge, check_deployments
from .evalkit.persona import EVAL_DIR, Persona, PersonaError, load_company, load_personas
from .evalkit.play import PersonaRun, play
from .evalkit.score_behaviour import load_prices, score_behaviour
from .evalkit.score_efficiency import progress_curve, score_efficiency, word_set
from .evalkit.score_fields import score_fields
from .evalkit.score_labels import score_labels
from .evalkit.scorecard import PersonaScore, Scorecard, build_scorecard, render_markdown, should_replace_latest

TOKENS_PER_PERSONA_ESTIMATE = 1_000_000  # §3.13: app + expert + judge, for the URL-mode guard


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m eval.run", description="Run the Discovery Agent evaluation.")
    parser.add_argument("--quick", action="store_true", help="only personas with quick: true")
    parser.add_argument("--fresh", action="store_true", help="no disk cache for app and EXPERT calls")
    parser.add_argument("--url", help="run against a running app instead of in process")
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--persona", action="append", default=[], help="only this persona id (repeatable)")
    parser.add_argument("--seed-cosmos", action="store_true", help="seed finished sessions into Cosmos")
    parser.add_argument("--calibrate-only", action="store_true")
    parser.add_argument("--max-tokens", type=int, default=3_000_000, help="URL mode: stop before exceeding")
    return parser.parse_args(argv)


def base_settings() -> Settings:
    """`backend/.env` settings with a relative company folder read from the backend folder."""
    settings = Settings()
    folder = settings.company_config_dir
    if not folder.is_absolute():
        settings = settings.model_copy(update={"company_config_dir": (BACKEND_DIR / folder).resolve()})
    return settings


async def _score(
    persona: Persona,
    run: PersonaRun,
    judge: Judge,
    prices: Any,
    words: frozenset[str],
    capture: LogCapture,
    folder: Path,
) -> PersonaScore:
    token = PERSONA.set(persona.id)
    try:
        views = run.session.get("fieldViews") or []
        fields = await score_fields(persona, run.session.get("profile") or {}, judge, views)
        curve = await progress_curve(persona, run.snapshots, judge)
    finally:
        PERSONA.reset(token)
    run.logs = capture.for_persona(persona.id) or run.logs
    expert_texts = [str(m.get("text", "")) for m in run.transcript if m.get("role") == "expert"]
    efficiency = score_efficiency(
        persona,
        run.snapshots,
        fields.correct,
        words,
        messages_to_finish=run.messages_to_finish,
        expert_texts=expert_texts,
        code_replies=run.code_replies,
    )
    score = PersonaScore(
        id=persona.id,
        version=persona.version,
        kind=persona.kind,
        status=run.status,
        error=run.error,
        quality=fields.quality,
        quality_code=fields.code_quality,
        correct=fields.correct,
        total=fields.total,
        judged=fields.judged,
        judge_errors=fields.judge_errors,
        invented_values=fields.invented_values,
        proposed_at_finish=fields.proposed_at_finish,
        min_conflicts=persona.expected.min_conflicts,
        labels=score_labels(persona, run) if run.session else None,
        behaviour=score_behaviour(persona, run, prices),
        efficiency=efficiency,
        curve=curve,
        wrong=[r for r in fields.results if not r.correct],
    )
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "score.json").write_text(
        json.dumps(
            {"fields": [r.model_dump() for r in fields.results], "score": score.model_dump(exclude={"curve"})}, indent=2
        ),
        encoding="utf-8",
    )
    (folder / "curve.json").write_text(json.dumps([c.model_dump() for c in curve], indent=2), encoding="utf-8")
    return score


def _quiet_logs(run_dir: Path) -> None:
    """App log lines go to the run folder, not the terminal."""
    handler = logging.FileHandler(run_dir / "app.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().handlers[:] = [handler]


async def run_eval(
    args: argparse.Namespace,
    *,
    settings: Settings | None = None,
    app_llm: LLM | None = None,
    expert_llm: LLM | None = None,
    judge_llm: LLM | None = None,
    personas_dir: Path = EVAL_DIR / "personas",
    calibration_file: Path = EVAL_DIR / "judge_calibration.yaml",
    runs_dir: Path = EVAL_DIR / "runs",
    reports_dir: Path = EVAL_DIR / "reports",
    out: Any = sys.stdout,
) -> int:
    """The whole run; returns the exit code (0 pass, 1 fail, 2 could not start)."""
    started = datetime.now(UTC)
    try:
        settings = settings or base_settings()
        check_deployments(settings)
        company = load_company(Path(settings.company_config_dir))
        personas = load_personas(personas_dir, quick=args.quick, company=company, only=tuple(args.persona))
        pairs = load_pairs(calibration_file)
        prices = load_prices(EVAL_DIR / "prices.yaml")
        cache_dir = EVAL_DIR / ".cache" / "llm"
        app_settings = in_process_settings(settings, llm_cache_enabled=not args.fresh)
        if expert_llm is None:
            expert_llm = create_llm(
                in_process_settings(settings, llm_cache_enabled=not args.fresh, llm_cache_dir=cache_dir)
            )
        if judge_llm is None:
            judge_llm = create_llm(in_process_settings(settings, llm_cache_enabled=True, llm_cache_dir=cache_dir))
    except (DeploymentClash, PersonaError, CalibrationFileError, LLMConfigError, OSError, ValueError) as error:
        print(f"eval: cannot start: {error}", file=out)
        return 2
    if not personas:
        print("eval: cannot start: no persona selected", file=out)
        return 2

    run_id = started.strftime("%Y%m%d-%H%M%S")
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    mode = f"url {args.url}" if args.url else "in-process"
    capture = LogCapture()
    capture.install()
    judge = Judge(judge_llm)
    words = word_set(company.yes_no_words)
    deployments = {
        "app": settings.azure_openai_deployment,
        "expert": settings.azure_openai_eval_deployment,
        "judge": settings.azure_openai_judge_deployment,
    }
    run_info: dict[str, Any] = {
        "run_id": run_id,
        "commit": os.environ.get("GIT_COMMIT", ""),
        "mode": mode,
        "cache": "off (app, expert)" if args.fresh else "on",
        "deployments": deployments,
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "personas": {p.id: p.version for p in personas},
        "started": started.isoformat(),
    }

    token = PERSONA.set("calibration")
    try:
        calibration = await calibrate(judge, pairs)
    finally:
        PERSONA.reset(token)
    (run_dir / "calibration.json").write_text(calibration.model_dump_json(indent=2), encoding="utf-8")
    print(f"eval: judge agreement {calibration.agreement:.0%} ({'pass' if calibration.passed else 'FAIL'})", file=out)
    if args.calibrate_only:
        return 0 if calibration.passed else 1

    driver = UrlDriver(args.url) if args.url else InProcessDriver(app_settings, llm=app_llm, capture=capture)
    if args.url:
        driver.capture = None
    _quiet_logs(run_dir)  # after `create_app`, which points the root logger at stdout
    gate = asyncio.Semaphore(max(1, args.parallel))
    started_personas = 0
    runs: dict[str, PersonaRun] = {}
    scores: list[PersonaScore] = []
    async with driver:

        async def one(persona: Persona) -> None:
            nonlocal started_personas
            async with gate:
                if args.url and (started_personas + 1) * TOKENS_PER_PERSONA_ESTIMATE > args.max_tokens:
                    print(f"eval: {persona.id} skipped: --max-tokens would be exceeded", file=out)
                    return
                started_personas += 1
                print(f"eval: playing {persona.id}", file=out)
                runs[persona.id] = await play(persona, driver, expert_llm, run_dir)
                print(
                    f"eval: {persona.id} {runs[persona.id].status} after {runs[persona.id].messages} messages", file=out
                )

        await asyncio.gather(*(one(p) for p in personas))
        for persona in personas:
            if persona.id in runs:
                scores.append(
                    await _score(persona, runs[persona.id], judge, prices, words, capture, run_dir / persona.id)
                )

        previous = None
        latest = reports_dir / "latest.json"
        if latest.exists():
            previous = Scorecard.model_validate_json(latest.read_text(encoding="utf-8"))
        card = build_scorecard(
            run_id,
            scores,
            calibration,
            previous,
            commit=run_info["commit"],
            mode=mode,
            cache=run_info["cache"],
            deployments=deployments,
            judge_prompt_version=JUDGE_PROMPT_VERSION,
        )
        markdown = render_markdown(card)
        (run_dir / "scorecard.json").write_text(card.model_dump_json(indent=2), encoding="utf-8")
        (run_dir / "scorecard.md").write_text(markdown, encoding="utf-8")
        if should_replace_latest(quick=args.quick, url=args.url, filtered=bool(args.persona)):
            reports_dir.mkdir(parents=True, exist_ok=True)
            (reports_dir / "latest.json").write_text(card.model_dump_json(indent=2), encoding="utf-8")
            (reports_dir / "latest.md").write_text(markdown, encoding="utf-8")

        if args.seed_cosmos:
            await _seed(args, settings, personas, scores, runs, driver, out)

    run_info["ended"] = datetime.now(UTC).isoformat()
    (run_dir / "run.json").write_text(json.dumps(run_info, indent=2), encoding="utf-8")
    for closing in (expert_llm, judge_llm):
        await closing.aclose()
    print(f"eval: {'PASS' if card.passed else 'FAIL'}; scorecard {run_dir / 'scorecard.md'}", file=out)
    for reason in card.reasons:
        print(f"  - {reason}", file=out)
    return 0 if card.passed else 1


async def _seed(args: argparse.Namespace, settings: Settings, personas: list[Persona], scores: list[PersonaScore],
                runs: dict[str, PersonaRun], driver: Any, out: Any) -> None:  # fmt: skip
    """§3.12: only in process, only with the flag; the store is Cosmos from the environment."""
    if args.url or not isinstance(driver, InProcessDriver):
        print("eval: --seed-cosmos works only in process; nothing seeded", file=out)
        return
    from app.services.store.cosmos import open_cosmos

    from .evalkit.seed import seed

    key = os.environ.get("EVAL_SEED_VISITOR_KEY", "")
    if len(key) < 22:
        print("eval: EVAL_SEED_VISITOR_KEY (22+ characters) is not set; nothing seeded", file=out)
        return
    by_id = {s.id: s for s in scores}
    entries = [(p, by_id[p.id], await driver.stored_model(runs[p.id].session_id)) for p in personas if p.id in by_id]
    store = await open_cosmos(settings.model_copy(update={"store": "cosmos"}))
    try:
        written = await seed(entries, store, key)
    finally:
        await store.close()
    print(f"eval: seeded {len(written)} session(s): {', '.join(written) or 'none'}", file=out)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run_eval(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
