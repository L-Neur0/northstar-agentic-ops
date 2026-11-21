"""The scorecard: one page per run, the employee's time and burden first, targets and deltas (spec 24 §3.11, §3.9b).

Why: a prompt or code change is only an improvement if the numbers say so, run over run. One fixed
page (JSON for machines, Markdown for people, the Markdown rendered from the JSON with no extra
facts) shows report quality and messages to *Finish* together, every target with ✓ / ✗ / n/a, and
the delta to the last full run, so a regression cannot hide behind a better headline.
What: `PersonaScore`, `TargetRow`, `Scorecard` (Pydantic); `target_rows` (product §8, §3.9 and
§3.9a targets per persona); `build_scorecard` (pass / fail with reasons: a target missed, a failed
session, the judge below 90 %); `render_markdown`; `should_replace_latest` (only a full in-process
run replaces `eval/reports/latest.*`).
Amended 2026-11-20: the headline leads with employee time, detail burden, Tier A + core quality
and the assessment match (fit, route); overall report quality and messages to *Finish* are
reported without a target.
Must not: add a fact to the Markdown that is not in the JSON, or let a `n/a` target fail the run.
The headline also shows the average answer length in words (AC-24.48).
Spec 24 §3.11, §3.9b; AC-24.23, AC-24.24, AC-24.25, AC-24.31, AC-24.38, AC-24.41, AC-24.42, AC-24.48.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from .calibrate import Calibration
from .persona import HARD_CAP
from .score_behaviour import BehaviourScores
from .score_efficiency import WASTED_TARGET, CurvePoint, EfficiencyScores, sparkline
from .score_employee import DetailBurden, EmployeeTime, QualitySplit
from .score_fields import FieldResult
from .score_labels import LabelScores

QUALITY_TARGET = 0.85  # Tier A + process core (§3.9b)
TIME_TARGET_MIN = 20.0  # mirrors `employee_time.yaml` target_minutes; the runner passes the file's value
BURDEN_TARGET = 0.15
FINISHED_ROW = f"session finished (safety net {HARD_CAP})"
REPEAT_TARGET = 2
FIT_ROUTE_TARGET = 0.70
CRITERIA_TARGET = 1.0  # §12 V3 (assumption)
HOURS_TARGET = 1.0  # §12 V4
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
    employee: EmployeeTime | None = None
    burden: DetailBurden | None = None
    split: QualitySplit = Field(default_factory=QualitySplit)
    time_target_min: float = TIME_TARGET_MIN
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
    mean_minutes: float | None = None
    pooled_burden: float | None = None
    pooled_core_quality: float = 0.0
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


def _ratio(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _pct(value: float | None) -> str | None:
    return None if value is None else f"{value:.0%}"


def _share(p: PersonaScore) -> float | None:
    return None if p.burden is None else p.burden.share


def _minutes(p: PersonaScore) -> float | None:
    return None if p.employee is None else round(p.employee.minutes, 1)


def target_rows(p: PersonaScore) -> list[TargetRow]:
    """Every target that applies to one persona, headline targets first (§3.9b, product §8, §3.9, §3.9a)."""
    b, e, labels = p.behaviour, p.efficiency, p.labels
    minutes = _minutes(p)
    share = _share(p)
    rows = [
        _row(p.id, "employee time (min)", minutes, f"≤ {p.time_target_min:g}",
             None if minutes is None else minutes <= p.time_target_min),
        _row(p.id, "detail burden", _pct(share), f"≤ {BURDEN_TARGET:.0%}", None if share is None else share <= BURDEN_TARGET),
    ]  # fmt: skip
    if p.kind == "cooperative":
        core = p.split.core_quality if p.split.core_total else None
        rows.append(_row(p.id, "Tier A + core quality", _pct(core), f"≥ {QUALITY_TARGET:.0%}",
                         None if core is None else core >= QUALITY_TARGET))  # fmt: skip
    if labels is not None and labels.routed_steps:
        fit, route = labels.fit_hits / labels.routed_steps, labels.route_hits / labels.routed_steps
        rows.append(_row(p.id, "step fit", _pct(fit), "≥ 70%", fit >= FIT_ROUTE_TARGET))
        rows.append(_row(p.id, "step route", _pct(route), "≥ 70%", route >= FIT_ROUTE_TARGET))
    rows += [
        _row(p.id, FINISHED_ROW, p.status, "finished", not e.failed),
        _row(p.id, "wasted turns", e.wasted, f"≤ {WASTED_TARGET}", e.wasted <= WASTED_TARGET),
        _row(p.id, "plateaus", len(e.plateaus), "0 (flag)", not e.plateaus, fails=False),
        _row(p.id, "loops", b.loops, "0", b.loops == 0),
        _row(p.id, "repeated questions", b.repeats, f"≤ {REPEAT_TARGET}", b.repeats <= REPEAT_TARGET),
        _row(p.id, "invented values", p.invented_values, "0", p.invented_values == 0),
        _row(p.id, "stale kept", b.stale_kept, "0", b.stale_kept == 0),
        _row(p.id, "criteria asked", _pct(_ratio(b.criteria_asked, b.criteria_steps)), f"{CRITERIA_TARGET:.0%}",
             None if not b.criteria_steps else b.criteria_asked / b.criteria_steps >= CRITERIA_TARGET),
        _row(p.id, "hours computed", _pct(_ratio(b.hours_steps_with_number, b.hours_steps)), f"{HOURS_TARGET:.0%}",
             None if not b.hours_steps else b.hours_steps_with_number / b.hours_steps >= HOURS_TARGET),
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
    return f"{diff * 100:+.0f} pt" if pct else f"{round(diff, 4):+g}"


def build_scorecard(
    run_id: str,
    personas: Sequence[PersonaScore],
    calibration: Calibration,
    previous: Scorecard | None,
    **header: Any,
) -> Scorecard:
    targets = [row for p in personas for row in target_rows(p)]
    burdens = [p.burden for p in personas if p.burden is not None]
    reasons = [f"{p.id}: session failed ({p.status})" for p in personas if p.efficiency.failed]
    reasons += [
        f"{r.persona}: {r.name} {r.value} (target {r.target})" for r in targets if r.fails and r.name != FINISHED_ROW
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
        mean_minutes=round(sum(m) / len(m), 1)
        if (m := [x for p in personas if (x := _minutes(p)) is not None])
        else None,
        pooled_burden=(sum(b.low_value for b in burdens) / q) if (q := sum(b.questions for b in burdens)) else None,
        pooled_core_quality=(sum(p.split.core_correct for p in personas) / c)
        if (c := sum(p.split.core_total for p in personas))
        else 0.0,
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
            card.deltas[p.id] = {k: "new" for k in ("minutes", "burden", "tier_a", "quality", "messages", "efficiency")}
            continue
        card.deltas[p.id] = {
            "minutes": _delta(_minutes(p), _minutes(old)),
            "burden": _delta(_share(p), _share(old), pct=True),
            "tier_a": _delta(
                p.split.core_quality if p.split.core_total else None,
                old.split.core_quality if old.split.core_total else None,
                pct=True,
            ),  # fmt: skip
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
        "## Headline: employee time, detail burden, Tier A quality, assessment",
        "",
        "| Persona | Employee time (min) | Δ | Read / type / think / upload (min) | Avg answer words "
        "| Detail burden | Δ | Tier A + core quality | Δ | Fit | Route |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in card.personas:
        d, t, lb = card.deltas.get(p.id, {}), p.employee, p.labels
        name = f"**{p.id} (failed: {p.status})**" if p.efficiency.failed else p.id
        minutes = "n/a" if t is None else f"{t.minutes:.1f} (target {p.time_target_min:g})"
        parts = (
            "n/a"
            if t is None
            else " / ".join(f"{x / 60:.1f}" for x in (t.reading_s, t.typing_s, t.think_s, t.upload_s))
        )
        burden = "n/a" if p.burden is None else f"{p.burden.share:.0%} ({p.burden.low_value}/{p.burden.questions})"
        core = (
            f"{p.split.core_quality:.0%} ({p.split.core_correct}/{p.split.core_total})" if p.split.core_total else "n/a"
        )
        fit = f"{lb.fit_hits}/{lb.routed_steps}" if lb and lb.routed_steps else "n/a"
        route = f"{lb.route_hits}/{lb.routed_steps}" if lb and lb.routed_steps else "n/a"
        words = "n/a" if t is None else f"{t.avg_expert_words:.1f}"
        lines.append(
            f"| {name} | {minutes} | {d.get('minutes', '')} | {parts} | {words} | {burden} | {d.get('burden', '')} "
            f"| {core} | {d.get('tier_a', '')} | {fit} | {route} |"
        )
    mean = "n/a" if card.mean_minutes is None else f"{card.mean_minutes:.1f} mean"
    pooled_burden = "n/a" if card.pooled_burden is None else f"{card.pooled_burden:.0%}"
    lines += [
        f"| **Pooled** | {mean} | | | | {pooled_burden} | | {card.pooled_core_quality:.0%} | | | |",
        "",
        "Employee time is an estimate from the words on the screen; speeds and think times are assumptions "
        "(`eval/employee_time.yaml`). Tiers: `eval/tiers.yaml`.",
        "",
        "## Also reported",
        "",
        "| Persona | Report quality | Δ | Code-only | Rest quality | Messages to Finish | Δ | Efficiency | Δ | Wasted | Plateaus |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in card.personas:
        d = card.deltas.get(p.id, {})
        e = p.efficiency
        msgs = "n/a" if e.messages_to_finish is None else str(e.messages_to_finish)
        eff = "n/a" if e.efficiency is None else f"{e.efficiency:.2f}"
        rest = f"{p.split.rest_quality:.0%}" if p.split.rest_total else "n/a"
        lines.append(
            f"| {p.id} | {p.quality:.0%} ({p.correct}/{p.total}) | {d.get('quality', '')} | {p.quality_code:.0%} | {rest} "
            f"| {msgs} | {d.get('messages', '')} | {eff} | {d.get('efficiency', '')} | {e.wasted} | {len(e.plateaus)} |"
        )
    lines += [
        f"| **Pooled** | {card.pooled_quality:.0%} | | {card.pooled_quality_code:.0%} | | {card.pooled_messages} messages | | | | | |",
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
