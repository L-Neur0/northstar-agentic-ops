"""Hours a year for the process, each step and each opportunity (spec 19 §3.2, F-14; hours only, R5).

Why: product rule 3, code makes every number. The report's hours must come from the expert's own
words through one fixed formula, show that formula, and say plainly when a number cannot be made
("Effort of step 4 ("a while") could not be read as a duration.") instead of guessing one.
What: `compute_value` reads each step's duration and frequency with `domain.value_parse`, makes the
step's runs a year (periodic, or per run × the process runs a year) and hours a year, sums them,
sums the steps each opportunity covers, and writes one formula line per number plus the assumptions.
Must not: compute cost, hours freed, euros or saving shares while the value method is parked
(refinement R5: those fields stay `None` and `rates` is not read), read a clock, call a model, or
report anyone's personal time (hours are per process step).
Spec 19 §3.2, §4.1; AC-19.6, AC-19.10 to AC-19.12, AC-19.15, AC-19.16, AC-19.39, AC-19.40.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Rates
from app.models.process_discovery_schemas import Opportunity, OpportunityValue, StepValue, ValueResult

from ..domain.field_spec import step_cell_key
from ..domain.value_parse import HOURS_PER_DAY, parse_duration, parse_frequency, periods_a_year, runs_per_year
from ..profile.shapes import as_mapping, meta_for, process_of, rows_of

MAX_STEP_SHARE = 0.9  # parked with the value method (R5); kept so the spec's interface stays whole
VOLUME_KEY = "process.volume"
WORKING_YEAR_ASSUMPTION = (
    f"A working year is taken as 50 weeks of 5 working days, and a working day as {HOURS_PER_DAY} hours."
)
MIDPOINT_ASSUMPTION = "A range of numbers is read as its midpoint (for example 2-3 hours = 2.5 hours)."


def num(x: float) -> str:
    """A number as shown in formulas: at most two decimals, no trailing zeros."""
    return f"{round(x, 2):.2f}".rstrip("0").rstrip(".")


@dataclass
class _Acc:
    missing: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    formulas: list[str] = field(default_factory=list)
    midpoint: bool = False

    def miss(self, key: str, problem: str) -> None:
        if key not in self.missing:
            self.missing.append(key)
        self.problems.append(problem)


def _is_proposed(meta: Mapping[str, Any] | None) -> bool:
    return meta is not None and meta.get("status") == "proposed"


def _process_runs(profile: Mapping[str, Any], acc: _Acc) -> tuple[float | None, str]:
    """Process runs a year (P10) and the words it was read from, for the per-run formulas."""
    volume = as_mapping(process_of(profile).get("volume")) or {}
    runs = runs_per_year(volume, meta_for(profile, VOLUME_KEY))
    count, period = volume.get("count"), str(volume.get("period") or "").strip()
    periods = periods_a_year(period) if isinstance(count, int) and period else None
    words = f"{count} per {period}" if periods is not None else str(volume.get("raw") or "").strip()
    if runs is not None:
        how = f"{count} × {num(periods)} " if periods is not None else ""
        acc.formulas.append(f'Process runs a year: {how}("{words}") = {num(runs)}')
    return runs, words


def _step(
    index: int, row: Mapping[str, Any], profile: Mapping[str, Any], process_runs: float | None, volume_words: str,
    acc: _Acc,
) -> StepValue:  # fmt: skip
    name = str(row.get("name") or "").strip()
    effort = as_mapping(row.get("effort")) or {}
    duration_text, frequency_text = str(effort.get("duration") or ""), str(effort.get("frequency") or "")
    key = step_cell_key(index, "effort")
    out = StepValue(step=index, name=name)
    if _is_proposed(meta_for(profile, key)):
        problem = f"Effort of step {index} is only proposed from a document and not confirmed yet."
        acc.miss(key, problem)
        return out.model_copy(update={"problem": problem})
    duration, frequency = parse_duration(duration_text), parse_frequency(frequency_text)
    problem = None
    if duration is None:
        problem = f'Effort of step {index} ("{duration_text}") could not be read as a duration.'
    elif frequency is None:
        problem = f'Effort of step {index} ("{frequency_text}") could not be read as a frequency.'
    if problem is not None:
        acc.miss(key, problem)
    if duration is None or frequency is None:
        return out.model_copy(update={"problem": problem, "duration_hours": duration and round(duration.hours, 2)})
    acc.midpoint = acc.midpoint or duration.midpoint or frequency.midpoint
    if frequency.kind == "periodic":
        runs, runs_words = frequency.value, f'"{frequency.text}"'
    elif process_runs is None:
        problem = (
            f'Step {index} runs "{frequency.text}" the process runs, but the process volume '
            f'("{volume_words}") could not be read.'
        )
        acc.miss(VOLUME_KEY, problem)
        return out.model_copy(update={"problem": problem, "duration_hours": round(duration.hours, 2)})
    else:
        runs = frequency.value * process_runs
        runs_words = f'"{frequency.text}" = {num(frequency.value)} × {num(process_runs)} process runs a year'
    hours = duration.hours * runs
    acc.formulas.append(
        f'Step {index} {name}: {num(duration.hours)} h ("{duration.text}") × {num(runs)} runs a year '
        f"({runs_words}) = {num(hours)} h"
    )
    return out.model_copy(
        update={"duration_hours": round(duration.hours, 2), "runs_per_year": round(runs, 2), "hours_per_year": hours}
    )


def _opportunity(opp: Opportunity, steps: Sequence[StepValue], total: float | None, acc: _Acc) -> OpportunityValue:
    if not opp.substeps:
        if total is not None:
            acc.formulas.append(f"Opportunity {opp.id} (whole process): {num(total)} h")
        return OpportunityValue(id=opp.id, step_hours=None if total is None else round(total, 2))
    covered = list(dict.fromkeys(opp.substeps))
    hours = [steps[k - 1].hours_per_year if 1 <= k <= len(steps) else None for k in covered]
    if any(h is None for h in hours):
        return OpportunityValue(id=opp.id, step_hours=None)
    known = [h for h in hours if h is not None]
    acc.formulas.append(
        f"Opportunity {opp.id} (steps {', '.join(str(k) for k in covered)}): "
        f"{' + '.join(num(h) for h in known)} = {num(sum(known))} h"
    )
    return OpportunityValue(id=opp.id, step_hours=round(sum(known), 2))


def compute_value(profile: Mapping[str, Any], opportunities: Sequence[Opportunity], rates: Rates) -> ValueResult:
    """Hours a year per step, in total and per opportunity, with formulas. `rates` is unused while R5 is parked."""
    del rates  # parked (R5): the value method is not decided, so no rate is read
    acc = _Acc()
    process_runs, volume_words = _process_runs(profile, acc)
    steps = [_step(i, row, profile, process_runs, volume_words, acc) for i, row in enumerate(rows_of(profile), start=1)]
    complete = bool(steps) and all(s.hours_per_year is not None for s in steps)
    total = sum(s.hours_per_year or 0 for s in steps) if complete else None
    if total is not None:
        acc.formulas.append(f"Hours a year: {' + '.join(num(s.hours_per_year or 0) for s in steps)} = {num(total)} h")
    opps = [_opportunity(o, steps, total, acc) for o in opportunities]
    assumptions = [WORKING_YEAR_ASSUMPTION] + ([MIDPOINT_ASSUMPTION] if acc.midpoint else [])
    return ValueResult(
        complete=complete,
        missing=acc.missing,
        hours_per_year=None if total is None else round(total, 2),
        runs_per_year=None if process_runs is None else round(process_runs, 2),
        steps=[s.model_copy(update={"hours_per_year": _r(s.hours_per_year)}) for s in steps],
        opportunities=opps,
        problems=acc.problems,
        formulas=acc.formulas,
        assumptions=assumptions,
    )


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 2)
