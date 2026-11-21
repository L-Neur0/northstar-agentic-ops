"""The three guiding questions of the transformation assessment (spec 27 §3.3).

Why: a manager reading the report asks three things: is this a good AI use case, does it need a
dedicated solution or will a general assistant (Copilot, ChatGPT) do, and is it worth it. The tool
guides and never judges (product rule: no go / no-go), so each answer is a level with reasons, and
code sets every level (rules 2, 3) from facts already checked: the grounded step signals of
ASSESS_STEPS, the hours a year, the readiness checklist, the profile and the catalogue.
What: `step_level` (Q1 for one step), `answer_questions` (Q1 for the process, Q2, Q3, the prepare
list and the risks, plus the model's motivation lines, kept only when their quote is the expert's
words), and `LEVEL_WORDS` (how each level reads in the report).
Must not: call a model, read a clock, do I/O, use money (parked, R5), or ever say yes, no, go or no-go.
Spec 27 §3.3; AC-27.1, AC-27.3 to AC-27.6.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.core.config import ReadinessConfig, SolutionCatalogue
from app.models.process_discovery_schemas import (
    Level,
    QuestionAnswer,
    Questions,
    Readiness,
    StepFit,
    StepLabels,
    StepRating,
    ValueResult,
)

from ..domain.field_spec import is_none_row
from ..profile.shapes import as_list, as_mapping, parse_step_key, process_of, rows_of
from .evidence import find_evidence, profile_values
from .readiness import match_application

LANGUAGE_SIGNALS = ("reads_unstructured", "compares_to_criteria", "finds_patterns", "drafts_text")
SIGNALS = (*LANGUAGE_SIGNALS, "must_be_exact", "fixed_rules")
SINGULAR = {"read": "reads", "compare": "compares", "look": "looks", "write": "writes"}
SIGNAL_PHRASES = {
    "reads_unstructured": "read documents or text that vary in layout or wording",
    "compares_to_criteria": "compare them with criteria",
    "finds_patterns": "look for patterns across many items",
    "drafts_text": "write or summarise text",
}
STRONG_HOURS_SHARE = 0.5  # §9 Q1: strong steps hold at least half the hours a year
REPEAT_RUNS_PER_YEAR = 50  # §9 Q1: "repeats" from about weekly
DEDICATED_FACTS = 2  # §9 Q1: two facts lean to a dedicated solution

LEVEL_WORDS: dict[str, dict[str, str]] = {
    "q1": {"strong": "Strong fit", "partial": "Partial fit", "weak": "Weak fit: rules or a script would do",
           "not_rated": "Not rated"},
    "q2": {"strong": "Leans to a dedicated solution", "partial": "Either can work",
           "weak": "A general assistant is enough", "not_rated": "Not rated"},
    "q3": {"strong": "Large", "partial": "Moderate", "weak": "Small", "not_rated": "Not rated"},
}  # fmt: skip
QUESTION_TEXT = {
    "q1": "Is this a good AI use case?",
    "q2": "A dedicated AI solution, or a general assistant?",
    "q3": "Is it worth it?",
}


def _steps_phrase(steps: Sequence[int]) -> str:
    """ "Step 2", "Steps 2 and 3", "Steps 1, 2 and 4"."""
    if len(steps) == 1:
        return f"Step {steps[0]}"
    return f"Steps {', '.join(str(s) for s in steps[:-1])} and {steps[-1]}"


def _singular(phrase: str) -> str:
    first, _, rest = phrase.partition(" ")
    return f"{SINGULAR.get(first, first)} {rest}".strip()


def _and(items: Sequence[str]) -> str:
    """ "a", "a and b", "a, b and c"."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _hours(x: float) -> str:
    return f"{x:,.0f}"


def _kind(row: Mapping[str, Any]) -> str:
    return str((as_mapping(row.get("decision_type")) or {}).get("kind") or "").strip().casefold()


def step_level(rating: StepRating, row: Mapping[str, Any]) -> StepFit:
    """Q1 for one step (§3.3): language signals without `must_be_exact` → strong; with it, or judgement
    without a language signal → partial; otherwise (fixed rules, or nothing AI is good at) → weak."""
    if rating.fit is None:
        return StepFit(step=rating.step, level="not_rated")
    on = {s for s in SIGNALS if rating.signals.get(s)}
    language = [s for s in LANGUAGE_SIGNALS if s in on]
    if language and "must_be_exact" not in on:
        return StepFit(step=rating.step, level="strong", because=[SIGNAL_PHRASES[s] for s in language])
    if language:
        because = [SIGNAL_PHRASES[s] for s in language] + ["the result must be exact, so a person checks it"]
        return StepFit(step=rating.step, level="partial", because=because)
    if _kind(row) in ("judgement", "mix") and "fixed_rules" not in on:
        return StepFit(step=rating.step, level="partial", because=["a person's judgement decides; AI can assist"])
    return StepFit(step=rating.step, level="weak", because=["fixed rules: rules or a script would do it"])


def _step_hours(value: ValueResult) -> dict[int, float]:
    return {s.step: s.hours_per_year for s in value.steps if s.hours_per_year is not None}


def _q1(fits: Sequence[StepFit], value: ValueResult) -> QuestionAnswer:
    rated = [f for f in fits if f.level != "not_rated"]
    if not rated:
        return QuestionAnswer(level="not_rated", reasons=["No step could be assessed."])
    strong = [f for f in rated if f.level == "strong"]
    partial = [f for f in rated if f.level == "partial"]
    weak = [f for f in rated if f.level == "weak"]
    hours = _step_hours(value)
    total = value.hours_per_year
    if total:
        share = sum(hours.get(f.step, 0.0) for f in strong) / total
    else:
        share = len(strong) / len(rated)
    level: Level = "strong" if strong and share >= STRONG_HOURS_SHARE else "partial" if strong or partial else "weak"
    reasons: list[str] = []
    if strong:
        because = list(dict.fromkeys(p for f in strong for p in f.because))
        nums = [f.step for f in strong]
        where = _steps_phrase(nums)
        if total:
            where += f" ({_hours(sum(hours.get(n, 0.0) for n in nums))} of {_hours(total)} hours a year)"
        text = " and ".join(because)
        if len(nums) == 1:  # "Step 2 reads …", "Steps 2 and 3 read …"
            text = " and ".join(_singular(b) for b in because)
        reasons.append(f"{where} {text}.")
    if partial:
        reasons.append(f"{_steps_phrase([f.step for f in partial])}: AI can assist, a person decides.")
    if weak:
        verb = "follows" if len(weak) == 1 else "follow"
        reasons.append(f"{_steps_phrase([f.step for f in weak])} {verb} fixed rules: a script or rules would do it.")
    return QuestionAnswer(level=level, reasons=reasons)


def _real_rows(value: Any) -> list[Mapping[str, Any]]:
    return [r for r in (as_mapping(x) for x in as_list(value) or []) if r is not None and not is_none_row(r)]


def _q2(
    profile: Mapping[str, Any],
    ratings: Sequence[StepRating],
    fits: Sequence[StepFit],
    value: ValueResult,
    catalogue: SolutionCatalogue,
    cfg: ReadinessConfig,
) -> QuestionAnswer:
    rows = rows_of(profile)
    ai_steps = [f.step for f in fits if f.level in ("strong", "partial")]
    reasons: list[str] = []
    facts = 0
    sensitive = [str(r.get("item") or "").strip() for r in _real_rows(process_of(profile).get("sensitive_data"))]
    if sensitive:
        facts += 1
        reasons.append(f"It handles {', '.join(sensitive)}, which should stay in a controlled company tool.")
    systems: list[str] = []
    for n in ai_steps:
        for system in as_list(rows[n - 1].get("systems")) or [] if n <= len(rows) else []:
            app = match_application(str(system), cfg) if isinstance(system, str) else None
            if isinstance(system, str) and system.strip() and (app is None or not app.general_tool):
                systems.append(system.strip())
    systems = list(dict.fromkeys(systems))
    if systems:
        facts += 1
        reasons.append(f"The AI would need a connector to reach {_and(systems)}.")
    runs = value.runs_per_year
    criteria = [
        str((as_mapping(rows[n - 1].get("decision_criteria")) or {}).get("basis") or "").strip()
        for n in ai_steps
        if n <= len(rows)
    ]
    criteria = [c for c in criteria if c]
    if runs is not None and runs >= REPEAT_RUNS_PER_YEAR and criteria:
        facts += 1
        reasons.append(
            f"It runs about {runs:g} times a year with the same instructions ({criteria[0]}); in a general "
            "assistant someone would upload the files and retype them every time."
        )
    by_id = {r.step: r for r in ratings}
    internal = [
        s
        for n in ai_steps
        if (r := by_id.get(n)) is not None and r.route_id and (s := catalogue.get(r.route_id)) is not None
        if s.category == "existing_internal"
    ]
    internal = list({s.id: s for s in internal}.values())
    if internal:
        reasons.append(f"{' and '.join(s.name for s in internal)} already exists and fits these steps.")
    level: Level = "strong" if internal or facts >= DEDICATED_FACTS else "partial" if facts == 1 else "weak"
    if level == "weak":
        reasons.append("No sensitive data, connector or repeated instructions: a general assistant can do it.")
    return QuestionAnswer(level=level, reasons=reasons)


def _missing_label(key: str) -> str:
    parsed = parse_step_key(key)
    if parsed is not None:
        return f"{parsed[1].replace('_', ' ').capitalize()} (step {parsed[0]})"
    return key.removeprefix("process.").replace("_", " ").capitalize()


def _q3(value: ValueResult, cfg: ReadinessConfig) -> QuestionAnswer:
    if value.hours_per_year is None:
        fields = ", ".join(_missing_label(k) for k in value.missing) or "the effort of each step"
        return QuestionAnswer(level="not_rated", reasons=[f"Hours a year could not be computed: {fields}."])
    hours, t = value.hours_per_year, cfg.thresholds
    level: Level = (
        "strong"
        if hours >= t.min_hours_per_year_high
        else "partial"
        if hours >= t.min_hours_per_year_medium
        else "weak"
    )
    runs = f" ({value.runs_per_year:g} runs a year)" if value.runs_per_year else ""
    return QuestionAnswer(level=level, reasons=[f"About {_hours(hours)} hours a year go into this process{runs}."])


def _prepare(rows: Sequence[Mapping[str, Any]], fits: Sequence[StepFit], readiness: Readiness) -> list[str]:
    out = [
        f"{d.label or d.key.capitalize()}: {d.to_prepare}"
        for d in readiness.dimensions
        if d.level == "low" and d.to_prepare
    ]
    for f in fits:
        if f.level in ("strong", "partial") and f.step <= len(rows):
            crit = as_mapping(rows[f.step - 1].get("decision_criteria")) or {}
            if str(crit.get("written") or "").strip().casefold() == "no":
                out.append(
                    f"Write down the decision criteria for step {f.step} (today: {crit.get('basis') or 'not written'})."
                )
    return out


def _risks(profile: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], labels: Sequence[StepLabels]) -> list[str]:
    out: list[str] = []
    sensitive = [str(r.get("item") or "").strip() for r in _real_rows(process_of(profile).get("sensitive_data"))]
    if sensitive:
        out.append(f"Sensitive data ({', '.join(sensitive)}): plan a human check and keep it in a controlled tool.")
    for i, row in enumerate(rows, start=1):
        varies = str((as_mapping(row.get("decision_criteria")) or {}).get("varies") or "").strip()
        if varies:
            out.append(f'Step {i}: the judgement varies: "{varies}".')
    pure = sorted({lab.step for lab in labels for d in lab.decisions if d.kind == "pure_judgement"})
    if pure:
        out.append(f"{_steps_phrase(pure)}: pure judgement decisions; keep a person in charge.")
    with_exceptions = sum(1 for row in rows if _real_rows(row.get("exceptions")))
    if rows and with_exceptions * 2 > len(rows):
        out.append(f"Exceptions in {with_exceptions} of {len(rows)} steps.")
    return out


def _motivation(answer: QuestionAnswer, raw: tuple[str, str] | None, values: Any) -> QuestionAnswer:
    """Keep the model's motivation only when its quote is the expert's words (rule 6)."""
    if raw is None:
        return answer
    text, quote = (" ".join(str(x).split()) for x in raw)
    hit = find_evidence(quote, values) if text and quote else None
    if hit is None:
        return answer
    return answer.model_copy(update={"motivation": text[:400], "evidence": hit.quote})


def answer_questions(
    profile: Mapping[str, Any],
    ratings: Sequence[StepRating],
    labels: Sequence[StepLabels],
    labels_ok: bool,
    value: ValueResult,
    readiness: Readiness,
    catalogue: SolutionCatalogue,
    cfg: ReadinessConfig,
    motivations: Mapping[str, tuple[str, str]],
) -> Questions:
    """Q1, Q2 and Q3 with their reasons, the prepare list and the risks. Pure."""
    rows = rows_of(profile)
    by_step = {r.step: r for r in ratings}
    fits = [step_level(by_step.get(i) or StepRating(step=i, name=""), rows[i - 1]) for i in range(1, len(rows) + 1)]
    values = profile_values(profile)
    q1 = _motivation(_q1(fits, value), motivations.get("q1"), values)
    q2 = _motivation(_q2(profile, ratings, fits, value, catalogue, cfg), motivations.get("q2"), values)
    q3 = _motivation(_q3(value, cfg), motivations.get("q3"), values)
    del labels_ok  # the pure-judgement risk simply has no labels when LABEL failed
    return Questions(steps=fits, q1=q1, q2=q2, q3=q3, prepare=_prepare(rows, fits, readiness),
                     risks=_risks(profile, rows, labels))  # fmt: skip
