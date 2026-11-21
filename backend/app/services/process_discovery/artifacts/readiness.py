"""The readiness checklist: six dimensions, each with a level, a reason and a "to prepare" line (spec 19 §3.5).

Why: before any AI or automation, the expert and the specialists need to see what is in place and
what to prepare (F-15), and product rule 3 says code makes every level. The levels come from
counted facts in the profile and the checked labels, against thresholds in `readiness.yaml`; the
reasons name those counts so anyone can check them. There is no overall verdict: the tool guides,
it does not judge.
What: `compute_readiness` rates Defined, Standard, Data, Systems, Rules and Risk and size in that
order, names the steps each one concerns (the path uses them), adds the configured to-prepare line
for medium and low, and carries a specialist's note over by key. `match_application` finds the
configured application a named system belongs to.
Must not: produce an overall level or score, call a model, read a clock, or hold company wording
(the lines and the application list are configuration).
Spec 19 §3.5, §3.8, §4.2; AC-19.23 to AC-19.33, AC-19.38, AC-19.49 (decision criteria in the Rules line).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from app.core.config import Application, ReadinessConfig
from app.models.process_discovery_schemas import Readiness, ReadinessDimension, StepLabels, ValueResult

from ..domain.field_spec import Vocabulary, WordingOverrides, is_none_row
from ..domain.taxonomy import Taxonomy
from ..profile.shapes import as_list, as_mapping, process_of, rows_of
from ..profile.verdicts import cell_counts, field_counts
from .value import num

Level = Literal["high", "medium", "low", "unknown"]

DIMENSIONS = ("defined", "standard", "data", "systems", "rules", "risk_size")
LABELS = {
    "defined": "Defined",
    "standard": "Standard",
    "data": "Data",
    "systems": "Systems",
    "rules": "Rules",
    "risk_size": "Risk and size",
}
DIGITAL_FORMATS = frozenset({"structured", "digital_document"})
EXPLAINABLE_KINDS = frozenset({"fixed_rule", "explainable_judgement"})
DIFFERENCES_MAX = 200
NOT_LABELLED = "Not rated: the input labels could not be produced."

# Whether a field counts needs only the registry's grade, not the company's wording or clusters
# (none of the fields read here has a validator that looks at them), so an empty vocabulary will do.
_GRADE_VOCAB = Vocabulary(taxonomy=Taxonomy.model_construct(clusters=()), regions=(), wording=WordingOverrides())


def _counts(profile: Mapping[str, Any], key: str) -> bool:
    return field_counts(profile, key, vocab=_GRADE_VOCAB)


def _level(share: float, high: float, medium: float) -> Level:
    return "high" if share >= high else "medium" if share >= medium else "low"


def _dim(key: str, level: Level, reason: str, steps: Sequence[int]) -> ReadinessDimension:
    return ReadinessDimension(key=key, level=level, reason=reason, label=LABELS[key], steps=list(steps))


def _real_rows(value: Any) -> list[Mapping[str, Any]]:
    return [m for r in as_list(value) or [] if (m := as_mapping(r)) is not None and not is_none_row(r)]


# --- The six dimensions ---------------------------------------------------------------------------


def _defined(profile: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> ReadinessDimension:
    owner = as_mapping(process_of(profile).get("process_owner")) or {}
    parts = {
        "trigger": _counts(profile, "process.trigger"),
        "end result": _counts(profile, "process.end_result"),
        "owner role": _counts(profile, "process.process_owner")
        and bool(str(owner.get("role") or "").strip())
        and owner.get("none_identified") is not True,
    }
    missing = [name for name, present in parts.items() if not present]
    without_goal = [i for i, row in enumerate(rows, 1) if not cell_counts(row, "goal", vocab=_GRADE_VOCAB)]
    n, with_goal = len(rows), len(rows) - len(without_goal)
    goals = f"{with_goal} of {n} steps have a goal"
    if len(missing) >= 2 or with_goal * 2 < n:
        level: Level = "low"
    elif not missing and with_goal == n and n > 0:
        level = "high"
    else:
        level = "medium"
    reason = (
        f"Trigger, end result and owner known; {goals}." if not missing else f"Missing: {', '.join(missing)}; {goals}."
    )
    steps = list(range(1, n + 1)) if missing else without_goal
    return _dim("defined", level, reason, steps)


def _standard(
    profile: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], cfg: ReadinessConfig
) -> tuple[ReadinessDimension, str]:
    """The dimension and the expert's "what differs" words (for the to-prepare line)."""
    all_steps = list(range(1, len(rows) + 1))
    if not _counts(profile, "process.variation"):
        reason = "Not rated: whether teams work the same way has not been answered and confirmed."
        return _dim("standard", "unknown", reason, all_steps), ""
    variation = as_mapping(process_of(profile).get("variation")) or {}
    same = str(variation.get("same") or "").strip().casefold()
    differences = " ".join(str(variation.get("differences") or "").split())[:DIFFERENCES_MAX]
    with_exceptions = sum(1 for row in rows if _real_rows(row.get("exceptions")))
    exceptions = f"exceptions in {with_exceptions} of {len(rows)} steps"
    if same == "no":
        return _dim("standard", "low", f'Teams do it differently: "{differences}".', all_steps), differences
    if same == "partly":
        return _dim("standard", "medium", f'Teams partly do it differently: "{differences}".', all_steps), differences
    share = with_exceptions / len(rows) if rows else 0.0
    level: Level = "high" if share <= cfg.thresholds.exception_share_medium else "medium"
    return _dim("standard", level, f"Same way everywhere; {exceptions}.", all_steps), differences


def _data(rows: Sequence[Mapping[str, Any]], labels: Sequence[StepLabels], cfg: ReadinessConfig) -> ReadinessDimension:
    labelled = [(lab.step, inp.format) for lab in labels for inp in lab.inputs]
    named = {lab.step: {inp.name.casefold() for inp in lab.inputs} for lab in labels}
    unlabelled = [
        str(name)
        for i, row in enumerate(rows, 1)
        for name in as_list((as_mapping(row.get("data")) or {}).get("inputs")) or []
        if isinstance(name, str) and name.strip() and name.casefold() not in named.get(i, set())
    ]
    tail = f" Not labelled: {', '.join(unlabelled)}." if unlabelled else ""
    if not labelled:
        return _dim("data", "unknown", "Not rated: no input could be labelled." + tail, [])
    digital = sum(1 for _, fmt in labelled if fmt in DIGITAL_FORMATS)
    t = cfg.thresholds
    level = _level(digital / len(labelled), t.digital_share_high, t.digital_share_medium)
    steps = sorted({step for step, fmt in labelled if fmt not in DIGITAL_FORMATS})
    return _dim("data", level, f"{digital} of {len(labelled)} labelled inputs are digital.{tail}", steps)


def match_application(system: str, cfg: ReadinessConfig) -> Application | None:
    """The first configured application whose name equals `system`, or one of whose aliases equals it
    or appears in it as a whole word (case-insensitive)."""
    wanted = " ".join(system.split()).casefold()
    if not wanted:
        return None
    for app in cfg.applications:
        if wanted == app.name.strip().casefold():
            return app
        for alias in app.aliases:
            a = alias.strip().casefold()
            if a and (wanted == a or re.search(rf"(?<!\w){re.escape(a)}(?!\w)", wanted)):
                return app
    return None


def _systems(rows: Sequence[Mapping[str, Any]], cfg: ReadinessConfig) -> ReadinessDimension:
    systems: dict[str, str] = {}
    used: dict[str, list[int]] = {}
    for i, row in enumerate(rows, 1):
        for name in as_list(row.get("systems")) or []:
            if isinstance(name, str) and name.strip():
                folded = name.strip().casefold()
                systems.setdefault(folded, name.strip())
                used.setdefault(folded, []).append(i)
    if not systems:
        return _dim("systems", "low", "No system is named in the steps.", range(1, len(rows) + 1))
    known = {k for k in systems if (app := match_application(systems[k], cfg)) is not None and app.export_or_api}
    unknown = [k for k in systems if k not in known]
    t = cfg.thresholds
    level = _level(len(known) / len(systems), t.known_system_share_high, t.known_system_share_medium)
    reason = f"{len(known)} of {len(systems)} systems have a known export or API"
    reason += f" ({', '.join(systems[k] for k in systems if k in known)})" if known else ""
    reason += f"; not: {', '.join(systems[k] for k in unknown)}." if unknown else "."
    steps = sorted({s for k in unknown for s in used[k]})
    return _dim("systems", level, reason, steps)


def _rules(labels: Sequence[StepLabels], cfg: ReadinessConfig) -> ReadinessDimension:
    decisions = [(lab.step, d.kind) for lab in labels for d in lab.decisions]
    if not decisions:
        return _dim("rules", "high", "No decision was found in the steps.", [])
    explainable = sum(1 for _, kind in decisions if kind in EXPLAINABLE_KINDS)
    t = cfg.thresholds
    level = _level(explainable / len(decisions), t.rule_share_high, t.rule_share_medium)
    steps = sorted({step for step, kind in decisions if kind == "pure_judgement"})
    reason = f"{explainable} of {len(decisions)} decisions are fixed rules or explainable."
    return _dim("rules", level, reason, steps)


CRITERIA_STEPS_MAX, CRITERIA_TEXT_MAX = 2, 120
WRITTEN_WORDS = {"no": "not written down", "partly": "partly written down"}


def _criteria(rows: Sequence[Mapping[str, Any]]) -> list[tuple[int, Mapping[str, Any]]]:
    """Steps with decision criteria (S14) that name a basis, in step order (spec 19 §3.8)."""
    out = []
    for i, row in enumerate(rows, start=1):
        crit = as_mapping(row.get("decision_criteria")) or {}
        if _short(crit.get("basis")):
            out.append((i, crit))
    return out


def _short(value: Any) -> str:
    return " ".join(str(value or "").split())[:CRITERIA_TEXT_MAX]


def _criteria_clause(step: int, crit: Mapping[str, Any]) -> str:
    """` Step n today: based on "…", set by …, not written down, varies: "…".`"""
    parts = [f'based on "{_short(crit.get("basis"))}"']
    if set_by := _short(crit.get("set_by")):
        parts.append(f"set by {set_by}")
    if written := WRITTEN_WORDS.get(_short(crit.get("written")).casefold()):
        parts.append(written)
    if varies := _short(crit.get("varies")):
        parts.append(f'varies: "{varies}"')
    return f" Step {step} today: {', '.join(parts)}."


def _with_criteria(
    dim: ReadinessDimension, line: str, rows: Sequence[Mapping[str, Any]]
) -> tuple[ReadinessDimension, str]:
    """Rules: name the criteria in the to-prepare line (medium, low) or flag unwritten ones (high)."""
    found = _criteria(rows)
    if dim.level in ("low", "medium"):
        return dim, line + "".join(_criteria_clause(i, c) for i, c in found[:CRITERIA_STEPS_MAX])
    if dim.level == "high":
        unwritten = [i for i, c in found if _short(c.get("written")).casefold() == "no"]
        if unwritten:
            steps = " and ".join(str(i) for i in unwritten)
            return dim.model_copy(
                update={"reason": f"{dim.reason} Criteria for step {steps} are not written down."}
            ), line
    return dim, line


def _risk_size(
    profile: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], value: ValueResult, cfg: ReadinessConfig
) -> ReadinessDimension:
    all_steps = range(1, len(rows) + 1)
    hours = value.hours_per_year
    if hours is None:
        return _dim("risk_size", "unknown", "Not rated: the hours a year could not be computed.", all_steps)
    t = cfg.thresholds
    sensitive = [str(r.get("item") or "").strip() for r in _real_rows(process_of(profile).get("sensitive_data"))]
    about = f"About {num(hours)} hours a year"
    if hours < t.min_hours_per_year_medium:
        return _dim("risk_size", "low", f"{about}, below {num(t.min_hours_per_year_medium)}.", all_steps)
    if sensitive:
        return _dim("risk_size", "medium", f"{about}; sensitive data: {', '.join(sensitive)}.", all_steps)
    large = " — a large process" if hours >= t.min_hours_per_year_high else ""
    return _dim("risk_size", "high", f"{about} and no sensitive data{large}.", all_steps)


# --- The checklist --------------------------------------------------------------------------------


def compute_readiness(
    profile: Mapping[str, Any],
    labels: Sequence[StepLabels],
    labels_ok: bool,
    value: ValueResult,
    cfg: ReadinessConfig,
    previous: Readiness | None = None,
) -> Readiness:
    """The six dimensions in order, with to-prepare lines from `cfg` and notes carried over from `previous`."""
    rows = rows_of(profile)
    standard, differences = _standard(profile, rows, cfg)
    dims = [
        _defined(profile, rows),
        standard,
        _data(rows, labels, cfg) if labels_ok else _dim("data", "unknown", NOT_LABELLED, []),
        _systems(rows, cfg),
        _rules(labels, cfg) if labels_ok else _dim("rules", "unknown", NOT_LABELLED, []),
        _risk_size(profile, rows, value, cfg),
    ]
    notes = {d.key: d.note for d in previous.dimensions} if previous is not None else {}
    out: list[ReadinessDimension] = []
    for dim in dims:
        line = ""
        if dim.level in ("low", "medium"):
            line = cfg.dimensions[dim.key].to_prepare[dim.level]  # pyright: ignore[reportArgumentType]
            if dim.key == "standard" and differences:
                line += f' What differs today: "{differences}".'
        if dim.key == "rules":
            dim, line = _with_criteria(dim, line, rows)
        out.append(dim.model_copy(update={"to_prepare": line, "note": notes.get(dim.key, "")}))
    return Readiness(dimensions=out)
