"""The scorecard: one page per run with quality and efficiency side by side, targets and deltas (spec 24 §3.11).

Why: a prompt or code change is only an improvement if the numbers say so, run over run. One fixed
page (JSON for machines, Markdown for people, the Markdown rendered from the JSON with no extra
facts) shows report quality and messages to *Finish* together, every target with ✓ / ✗ / n/a, and
the delta to the last full run, so a regression cannot hide behind a better headline.
What: `PersonaScore`, `TargetRow`, `Scorecard` (Pydantic); `target_rows` (product §8, §3.9 and
§3.9a targets per persona); `build_scorecard` (pass / fail with reasons: a target missed, a failed
session, the judge below 90 %); `render_markdown`; `should_replace_latest` (only a full in-process
run replaces `eval/reports/latest.*`).
Must not: add a fact to the Markdown that is not in the JSON, or let a `n/a` target fail the run.
Spec 24 §3.11; AC-24.23, AC-24.24, AC-24.25.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from .calibrate import Calibration
from .score_behaviour import BehaviourScores
from .score_efficiency import WASTED_TARGET, CurvePoint, EfficiencyScores, sparkline
from .score_fields import FieldResult
from .score_labels import LabelScores

QUALITY_TARGET = 0.85
REPEAT_TARGET = 2
FIT_ROUTE_TARGET = 0.70
TURN_MEDIAN_S, TURN_MAX_S, FINISH_S = 10.0, 150.0, 30.0
APP_COST_EUR = 0.50


class PersonaScore(BaseModel):
    id: str
    version: int
    kind: str
    status: str
    error: str = ""
    quality: float = 0.0
    quality_code: float = 0.0
    correct: int = 0
    total: int = 0
    judged: int = 0
    judge_errors: int = 0
    invented_values: int = 0
    proposed_at_finish: int = 0
    min_conflicts: int = 0
    labels: LabelScores | None = None
    behaviour: BehaviourScores = Field(default_factory=BehaviourScores)
    efficiency: EfficiencyScores
    curve: list[CurvePoint] = Field(default_factory=list)
    wrong: list[FieldResult] = Field(default_factory=list)


class TargetRow(BaseModel):
    persona: str
    name: str
    value: str
    target: str
    status: str  # ✓ | ✗ | n/a | flag
    fails: bool = False
    delta: str = ""


class Scorecard(BaseModel):
    run_id: str
    commit: str = ""
    mode: str = "in-process"
    cache: str = "on"
    deployments: dict[str, str] = Field(default_factory=dict)
    judge_prompt_version: str = ""
    calibration: Calibration
    judge_trusted: bool = True
    passed: bool = False
    reasons: list[str] = Field(default_factory=list)
    personas: list[PersonaScore]
    pooled_quality: float = 0.0
    pooled_quality_code: float = 0.0
    pooled_messages: int = 0
    app_euros_per_finished: float | None = None
    targets: list[TargetRow] = Field(default_factory=list)
    worst: list[dict[str, Any]] = Field(default_factory=list)
    deltas: dict[str, dict[str, str]] = Field(default_factory=dict)


def _row(persona: str, name: str, value: Any, target: str, ok: bool | None, *, fails: bool = True) -> TargetRow:
    if ok is None or value is None:
        return TargetRow(
            persona=persona, name=name, value="n/a" if value is None else str(value), target=target, status="n/a"
        )
    status = "✓" if ok else ("✗" if fails else "flag")
    return TargetRow(persona=persona, name=name, value=str(value), target=target, status=status, fails=fails and not ok)


def _pct(value: float | None) -> str | None:
    return None if value is None else f"{value:.0%}"


def target_rows(p: PersonaScore) -> list[TargetRow]:
    """Every target that applies to one persona (product §8, spec 24 §3.9, §3.9a)."""
    b, e, labels = p.behaviour, p.efficiency, p.labels
    rows = [_row(p.id, "session finished (hard cap 60)", p.status, "finished", not e.failed)]
    if p.kind == "cooperative":
        rows.append(_row(p.id, "report quality", _pct(p.quality), "≥ 85%", p.quality >= QUALITY_TARGET))
    rows += [
        _row(p.id, "messages to Finish", e.messages_to_finish, f"≤ {e.message_target}",
             None if e.messages_to_finish is None else e.messages_to_finish <= e.message_target),
        _row(p.id, "wasted turns", e.wasted, f"≤ {WASTED_TARGET}", e.wasted <= WASTED_TARGET),
        _row(p.id, "plateaus", len(e.plateaus), "0 (flag)", not e.plateaus, fails=False),
        _row(p.id, "loops", b.loops, "0", b.loops == 0),
        _row(p.id, "repeated questions", b.repeats, f"≤ {REPEAT_TARGET}", b.repeats <= REPEAT_TARGET),
        _row(p.id, "invented values", p.invented_values, "0", p.invented_values == 0),
        _row(p.id, "stale kept", b.stale_kept, "0", b.stale_kept == 0),
        _row(p.id, "conflicts", b.conflicts, f"≥ {p.min_conflicts}", b.conflicts >= p.min_conflicts),
        _row(p.id, "turn time median (s)", b.turn_median_s, f"< {TURN_MEDIAN_S:g}",
             None if b.turn_median_s is None else b.turn_median_s < TURN_MEDIAN_S),
        _row(p.id, "turn time max (s)", b.turn_max_s, f"< {TURN_MAX_S:g}",
             None if b.turn_max_s is None else b.turn_max_s < TURN_MAX_S),
        _row(p.id, "Finish time (s)", b.finish_s, f"< {FINISH_S:g}", None if b.finish_s is None else b.finish_s < FINISH_S),
        _row(p.id, "app cost per session (€)", b.app.euros if p.status == "finished" else None, f"< {APP_COST_EUR:.2f}",
             None if b.app.euros is None else b.app.euros < APP_COST_EUR),
    ]  # fmt: skip
    if labels is not None:
        rows += [
            _row(p.id, "cluster", labels.cluster, "hit", labels.cluster),
            _row(p.id, "scope", labels.scope, "hit", labels.scope),
            _row(p.id, "steering", labels.steering, "hit", labels.steering),
        ]
        if labels.routed_steps:
            fit, route = labels.fit_hits / labels.routed_steps, labels.route_hits / labels.routed_steps
            rows.append(_row(p.id, "step fit", _pct(fit), "≥ 70%", fit >= FIT_ROUTE_TARGET))
            rows.append(_row(p.id, "step route", _pct(route), "≥ 70%", route >= FIT_ROUTE_TARGET))
    return rows


def _num(text: str) -> float | None:
    try:
        return float(text.rstrip("%"))
    except ValueError:
        return None


def _delta(now: Any, before: Any, *, pct: bool = False) -> str:
    if now is None or before is None:
        return ""
    diff = float(now) - float(before)
    return f"{diff * 100:+.0f} pt" if pct else f"{diff:+g}"


def build_scorecard(
    run_id: str,
    personas: Sequence[PersonaScore],
    calibration: Calibration,
    previous: Scorecard | None,
    **header: Any,
) -> Scorecard:
    targets = [row for p in personas for row in target_rows(p)]
    reasons = [f"{p.id}: session failed ({p.status})" for p in personas if p.efficiency.failed]
    reasons += [
        f"{r.persona}: {r.name} {r.value} (target {r.target})"
        for r in targets
        if r.fails and r.name != "session finished (hard cap 60)"
    ]
    if not calibration.passed:
        reasons.insert(0, f"judge failed calibration ({calibration.agreement:.0%} < 90%)")
    total = sum(p.total for p in personas)
    finished = [p for p in personas if p.status == "finished" and p.behaviour.app.euros is not None]
    worst = sorted(
        (
            {"persona": p.id, **w.model_dump(include={"key", "hidden", "captured", "method", "reason"})}
            for p in personas
            for w in p.wrong
        ),
        key=lambda w: (w["method"] == "missing", w["persona"]),
    )[:10]
    card = Scorecard(
        run_id=run_id,
        calibration=calibration,
        judge_trusted=calibration.passed,
        passed=not reasons,
        reasons=reasons,
        personas=list(personas),
        pooled_quality=sum(p.correct for p in personas) / total if total else 0.0,
        pooled_quality_code=sum(p.quality_code * p.total for p in personas) / total if total else 0.0,
        pooled_messages=sum(p.efficiency.messages for p in personas),
        app_euros_per_finished=(
            round(sum(p.behaviour.app.euros or 0 for p in finished) / len(finished), 4) if finished else None
        ),
        targets=targets,
        worst=worst,
        **header,
    )
    if previous is not None:
        _apply_deltas(card, previous)
    return card


def _apply_deltas(card: Scorecard, previous: Scorecard) -> None:
    before = {p.id: p for p in previous.personas}
    old_rows = {(r.persona, r.name): r for r in previous.targets}
    for p in card.personas:
        old = before.get(p.id)
        if old is None or old.version != p.version:
            card.deltas[p.id] = {"quality": "new", "messages": "new", "efficiency": "new"}
            continue
        card.deltas[p.id] = {
            "quality": _delta(p.quality, old.quality, pct=True),
            "messages": _delta(p.efficiency.messages_to_finish, old.efficiency.messages_to_finish),
            "efficiency": _delta(p.efficiency.efficiency, old.efficiency.efficiency),
        }
    for row in card.targets:
        old_row = old_rows.get((row.persona, row.name))
        if card.deltas.get(row.persona, {}).get("quality") == "new":
            row.delta = "new"
        elif old_row is not None:
            a, b = _num(row.value), _num(old_row.value)
            row.delta = _delta(a, b) if a is not None and b is not None else ""


def should_replace_latest(*, quick: bool, url: str | None, filtered: bool) -> bool:
    """Only a full in-process run is the new baseline (AC-24.24)."""
    return not quick and not url and not filtered


def _at(curve: Sequence[CurvePoint], n: int, attr: str) -> str:
    point = next((c for c in curve if c.n == n), None)
    return "" if point is None else f"{n}: {getattr(point, attr):.0%}  "


def render_markdown(card: Scorecard) -> str:
    """The Markdown page, built only from the scorecard JSON."""
    trust = "" if card.judge_trusted else " (judged results NOT TRUSTED)"
    lines = [
        f"# Evaluation scorecard {card.run_id}",
        "",
        f"**{'PASS' if card.passed else 'FAIL'}**" + (f": {'; '.join(card.reasons)}" if card.reasons else ""),
        "",
        "| Run | Value |",
        "|---|---|",
        f"| Commit | {card.commit or 'n/a'} |",
        f"| Mode / cache | {card.mode} / {card.cache} |",
        f"| Deployments | {', '.join(f'{k}: {v}' for k, v in card.deployments.items())} |",
        f"| Judge | {card.judge_prompt_version}, agreement {card.calibration.agreement:.0%} "
        f"({card.calibration.agreed}/{card.calibration.pairs}){trust} |",
        "",
        "## Headline: report quality and messages to Finish",
        "",
        "| Persona | Report quality | Δ | Code-only | Messages to Finish | Δ | Efficiency | Δ | Wasted | Plateaus |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in card.personas:
        d = card.deltas.get(p.id, {})
        e = p.efficiency
        name = f"**{p.id} (failed: {p.status})**" if e.failed else p.id
        msgs = "n/a" if e.messages_to_finish is None else f"{e.messages_to_finish} (target {e.message_target})"
        eff = "n/a" if e.efficiency is None else f"{e.efficiency:.2f}"
        lines.append(
            f"| {name} | {p.quality:.0%} ({p.correct}/{p.total}) | {d.get('quality', '')} | {p.quality_code:.0%} | {msgs} "
            f"| {d.get('messages', '')} | {eff} | {d.get('efficiency', '')} | {e.wasted} | {len(e.plateaus)} |"
        )
    lines += [
        f"| **Pooled** | {card.pooled_quality:.0%} | | {card.pooled_quality_code:.0%} | {card.pooled_messages} messages | | | | | |",
        "",
    ]
    lines += ["## Targets", "", "| Persona | Target | Value | Goal | Result | Δ |", "|---|---|---|---|---|---|"]
    lines += [f"| {r.persona} | {r.name} | {r.value} | {r.target} | {r.status} | {r.delta} |" for r in card.targets]
    lines += ["", "## Per persona", "", "| Persona | Cluster | Scope | Steering | Fit | Route | Loops | Repeats | Turn median / max (s) | Finish (s) | Proposals ✓/✎ | App tokens in/out | App € | Expert € | Judge € |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
    for p in card.personas:
        b, lb = p.behaviour, p.labels
        lab = lambda v: "n/a" if v is None else ("✓" if v else "✗")  # noqa: E731
        fit = f"{lb.fit_hits}/{lb.routed_steps}" if lb else "n/a"
        route = f"{lb.route_hits}/{lb.routed_steps}" if lb else "n/a"
        eur = lambda t: "n/a" if t.euros is None else f"{t.euros:.3f}"  # noqa: E731
        lines.append(
            f"| {p.id} | {lab(lb.cluster if lb else None)} | {lab(lb.scope if lb else None)} | {lab(lb.steering if lb else None)} "
            f"| {fit} | {route} | {b.loops} | {b.repeats} | {b.turn_median_s or 'n/a'} / {b.turn_max_s or 'n/a'} "
            f"| {b.finish_s or 'n/a'} | {b.proposals_confirmed}/{b.proposals_rejected} | {b.app.tokens_in}/{b.app.tokens_out} "
            f"| {eur(b.app)} ({', '.join(b.app.deployments)}) | {eur(b.expert)} | {eur(b.judge)} |"
        )
    lines += ["", "## Progress curves", "", "```"]
    for p in card.personas:
        if not p.curve:
            continue
        last = p.curve[-1]
        for attr in ("quality", "score"):
            label = p.id if attr == "quality" else ""
            marks = "".join(_at(p.curve, n, attr) for n in (10, 20, 30) if n < last.n)
            end = f"{last.n} ({'Finish' if p.status == 'finished' else 'last'}): {getattr(last, attr):.0%}"
            lines.append(f"{label:<22} {attr:<8} {sparkline([getattr(c, attr) for c in p.curve])}  {marks}{end}")
    lines += ["```", "", "## Total", ""]
    euros = card.app_euros_per_finished
    lines.append(
        f"Pooled report quality {card.pooled_quality:.0%} (code-only {card.pooled_quality_code:.0%}); "
        f"{card.pooled_messages} expert messages; app € per finished session: {'n/a' if euros is None else f'{euros:.3f}'} "
        "(prices are an assumption, see `eval/prices.yaml`)."
    )
    lines += [
        "",
        "## Worst fields",
        "",
        "| Persona | Field | Hidden | Captured | Method | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for w in card.worst:
        cells = [
            str(w.get(k, "")).replace("|", "/").replace("\n", " ")[:80]
            for k in ("persona", "key", "hidden", "captured", "method", "reason")
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
