"""The process-or-task rubric and the placement arithmetic (spec 12 §3.9; product F-06, F-07).

Why: the CLASSIFY call only reports five yes/no signals and a cluster with a confidence; whether
the work is a process, a borderline case or one person's task, and whether a cluster may be put
to the expert, is decided here by code (product rule 2), so it holds whatever the model returned.
Scope ("is it a process?") and placement ("which cluster?") are kept apart on purpose: a task can
place confidently and must still be caught by the rubric.
What: the five signals with their questions, `build_scope_verdict` and its banding (with
`external_consumer` as a cap, not a fifth vote), the neutral verdict for a failed call, the
calibration rows, and `build_placement` with its confidence floor and runner-up margin.
Must not: read the environment or a clock, call a model, or recompute a verdict from a stored score
(the neutral verdict is the one case where they differ). Thresholds passed in are checked, never
clamped. Tests: AC-12.33 to AC-12.37.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from .taxonomy import UNKNOWN_CODE, Taxonomy

SIGNALS: tuple[tuple[str, str], ...] = (
    ("multi_role", "More than one person or role takes part."),
    ("multi_system", "More than one system, tool or document is involved."),
    ("trigger_and_outcome", "It has a recognisable trigger and a recognisable outcome."),
    ("recurring", "It recurs as normal work, not a one-off."),
    ("external_consumer", "Someone outside the expert's own work depends on the output."),
)
SIGNAL_KEYS: tuple[str, ...] = tuple(key for key, _ in SIGNALS)
SIGNAL_QUESTIONS: dict[str, str] = {
    "multi_role": "Who else gets pulled in when this comes round?",
    "multi_system": "Which tools, systems or documents do you touch to get it done?",
    "trigger_and_outcome": "What sets this off, and how do you know it is finished?",
    "recurring": "How often does this come round?",
    "external_consumer": "Who is waiting on the result once you are done?",
}
EXTERNAL_CONSUMER = "external_consumer"
RECURRING = "recurring"

VERDICT_PROCESS, VERDICT_BORDERLINE, VERDICT_TASK = "process", "borderline", "task"
PROCESS_FLOOR, BORDERLINE_FLOOR = 4, 3
MIN_CONFIDENCE, MIN_MARGIN = 0.60, 0.15

SOURCE_MODEL, SOURCE_KEYWORD = "model", "keyword"


def _signals(*values: bool) -> dict[str, bool]:
    return dict(zip(SIGNAL_KEYS, values, strict=True))


#: Examples shown to CLASSIFY; the scorer must agree with every row (AC-12.35).
CALIBRATION: tuple[tuple[str, dict[str, bool], str], ...] = (
    ("I book my flight for a site visit", _signals(True, True, True, True, False), VERDICT_BORDERLINE),
    ("I file my weekly timesheet", _signals(False, False, True, True, False), VERDICT_TASK),
    ("I export a report from the ERP every Monday", _signals(False, False, False, True, False), VERDICT_TASK),
    ("Approving supplier invoices over €10k", _signals(True, True, True, True, True), VERDICT_PROCESS),
    ("Onboarding a new engineer", _signals(True, True, True, True, True), VERDICT_PROCESS),
    ("The monthly cost review", _signals(True, True, True, True, True), VERDICT_PROCESS),
    ("We migrated the CRM last year", _signals(True, True, True, False, True), VERDICT_PROCESS),
    ("The quarterly access review", _signals(True, True, True, True, True), VERDICT_PROCESS),
)


def _mapping(value: object) -> Mapping[str, Any]:
    return cast("Mapping[str, Any]", value) if isinstance(value, Mapping) else {}


def normalise_signals(raw: Any) -> dict[str, bool]:
    """Exactly the five signals; only a literal `true` counts (not "true", not 1)."""
    source = _mapping(raw)
    return {key: source.get(key) is True for key in SIGNAL_KEYS}


def score_scope(signals: Mapping[str, Any]) -> int:
    """How many of the five signals hold, 0–5."""
    return sum(1 for value in normalise_signals(signals).values() if value)


def verdict_for(score: int, external_consumer: bool) -> str:
    """Band a score. Without `external_consumer` a high score stays borderline."""
    if score >= PROCESS_FLOOR:
        return VERDICT_PROCESS if external_consumer else VERDICT_BORDERLINE
    if score == BORDERLINE_FLOOR:
        return VERDICT_BORDERLINE
    return VERDICT_TASK


def build_scope_verdict(raw: Any) -> dict[str, Any]:
    """`{verdict, score, signals, reasoning}` from the CLASSIFY scope block."""
    signals = normalise_signals(raw)
    score = sum(signals.values())
    reasoning = _mapping(raw).get("reasoning")
    return {
        "verdict": verdict_for(score, signals[EXTERNAL_CONSUMER]),
        "score": score,
        "signals": signals,
        "reasoning": reasoning.strip() if isinstance(reasoning, str) else "",
    }


def neutral_scope_verdict() -> dict[str, Any]:
    """What a failed CLASSIFY yields: borderline with score 0. Not knowing earns one more question."""
    return {"verdict": VERDICT_BORDERLINE, "score": 0, "signals": dict.fromkeys(SIGNAL_KEYS, False), "reasoning": ""}


def failed_signals(verdict: Mapping[str, Any]) -> tuple[str, ...]:
    """The signals that did not hold, in rubric order."""
    signals = _mapping(_mapping(verdict).get("signals"))
    return tuple(key for key in SIGNAL_KEYS if signals.get(key) is not True)


def is_one_off(verdict: Mapping[str, Any]) -> bool:
    """A process that does not recur (F-06.5)."""
    v = _mapping(verdict)
    return v.get("verdict") == VERDICT_PROCESS and _mapping(v.get("signals")).get(RECURRING) is not True


# --- Placement --------------------------------------------------------------------------------


def _code(value: Any, taxonomy: Taxonomy) -> str:
    """A declared code, or UNKNOWN. A cluster name is not a code."""
    if not isinstance(value, str):
        return UNKNOWN_CODE
    cluster = taxonomy.by_code(value)
    return cluster.code if cluster is not None else UNKNOWN_CODE


def _confidence(value: Any) -> float:
    """Clamped to [0, 1]; non-numbers and bools are 0."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _check_threshold(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1, got {value}")


def build_placement(
    raw: Any,
    taxonomy: Taxonomy,
    *,
    min_confidence: float = MIN_CONFIDENCE,
    min_margin: float = MIN_MARGIN,
) -> dict[str, Any]:
    """The placement state from the CLASSIFY placement block.

    Below `min_confidence` the code becomes UNKNOWN with confidence 0; `raw_confidence` keeps the
    model's own number. `ambiguous` when the lead over the runner-up is under `min_margin`.
    """
    _check_threshold("min_confidence", min_confidence)
    _check_threshold("min_margin", min_margin)
    source = _mapping(raw)
    code = _code(source.get("code"), taxonomy)
    raw_confidence = _confidence(source.get("confidence"))
    confidence = raw_confidence
    runner_up = _code(source.get("runner_up"), taxonomy)
    runner_up_confidence = 0.0 if runner_up == UNKNOWN_CODE else _confidence(source.get("runner_up_confidence"))
    if confidence < min_confidence:
        code, confidence = UNKNOWN_CODE, 0.0
    rationale = source.get("rationale")
    margin = round(confidence - runner_up_confidence, 9)
    return {
        "code": code,
        "confidence": confidence,
        "raw_confidence": raw_confidence,
        "runner_up": runner_up,
        "runner_up_confidence": runner_up_confidence,
        "rationale": rationale.strip() if isinstance(rationale, str) else "",
        "ambiguous": code != UNKNOWN_CODE and margin < min_margin,
        "source": SOURCE_MODEL,
    }


def keyword_placement(code: str) -> dict[str, Any]:
    """A placement from a single keyword match: certain, no runner-up (F-07.1)."""
    return {
        "code": code.strip().upper(),
        "confidence": 1.0,
        "raw_confidence": 1.0,
        "runner_up": UNKNOWN_CODE,
        "runner_up_confidence": 0.0,
        "rationale": "Matched a keyword of this cluster.",
        "ambiguous": False,
        "source": SOURCE_KEYWORD,
    }


def unknown_placement() -> dict[str, Any]:
    """The complete empty placement, for a failed CLASSIFY."""
    return {
        "code": UNKNOWN_CODE,
        "confidence": 0.0,
        "raw_confidence": 0.0,
        "runner_up": UNKNOWN_CODE,
        "runner_up_confidence": 0.0,
        "rationale": "",
        "ambiguous": False,
        "source": SOURCE_MODEL,
    }


def proposable_code(placement: Mapping[str, Any] | None) -> str:
    """The code the agent may put to the expert, or "" when unknown, ambiguous or malformed."""
    p = _mapping(placement)
    code = p.get("code")
    if not isinstance(code, str) or not code.strip() or code == UNKNOWN_CODE or p.get("ambiguous") is True:
        return ""
    return code
