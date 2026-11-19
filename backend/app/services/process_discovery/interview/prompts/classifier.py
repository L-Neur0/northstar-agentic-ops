"""CLASSIFY: process-or-task and cluster placement for one named activity (spec 14 §3.9; product F-06, F-07).

ACCEPTED FOR NOW — wording to be refined with the product owner. Builds the classifier prompt: the
frame rule, the five numbered signals, the value test, the calibration rows scored by the real
scorer, and the placement part. Adapted: the clusters come from the company configuration
(`taxonomy.prompt_block()`), so taxonomy-specific confusion pairs and governance
caveat are not carried over, and the reply is a strict structured output.

Why: the model only reports five yes/no signals and a cluster with a confidence; whether that is a
process, a borderline case or a task, and whether a cluster may be put to the expert, is decided
by code (`domain.scope`). The rubric and the calibration rows are rendered from the same
declarations the scorer uses, so the prompt and the scorer cannot disagree. A half that is not
needed is absent, not merely ignored, so a settled cluster can never be re-litigated.
What: `FRAME_RULE`, `classifier_system(with_scope, with_placement, taxonomy)` and
`classifier_user(subject, profile)` (department, role and the fenced activity; never the whole profile).
Must not: talk to the expert, accept a cluster name for a code, or see more of the profile than
the rubric needs. Spec 14 §3.9; AC-14.58.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.utils.prompt_safety import fence_instruction, fence_untrusted

from ...domain.scope import CALIBRATION, EXTERNAL_CONSUMER, SIGNAL_KEYS, SIGNALS, score_scope, verdict_for
from ...domain.taxonomy import UNKNOWN_CODE, Taxonomy
from .common import text_value

FRAME_RULE = (
    "Judge ONLY the activity exactly as the expert described it. Do not consider the larger process it may be part "
    "of, and do not count people or systems that appear only downstream of what they described. If the expert says "
    '"I file my timesheet", the subject is *filing a timesheet*, not payroll.'
)

_SCOPE_JSON = """  "scope": {
    "multi_role": true,
    "multi_system": true,
    "trigger_and_outcome": true,
    "recurring": true,
    "external_consumer": false,
    "reasoning": "one sentence"
  }"""

_PLACEMENT_JSON = """  "placement": {
    "code": "FIN",
    "confidence": 0.82,
    "rationale": "one sentence, quoting the expert's own words",
    "runner_up": "PRO",
    "runner_up_confidence": 0.41
  }"""


def signal_block() -> str:
    """The five signals, numbered, from the scorer's own declaration."""
    return "\n".join(f"R{i}. `{key}`: {prose}" for i, (key, prose) in enumerate(SIGNALS, start=1))


def calibration_block() -> str:
    """The worked examples, scored by the real scorer."""
    lines: list[str] = []
    for activity, signals, _expected in CALIBRATION:
        score = score_scope(signals)
        verdict = verdict_for(score, signals[EXTERNAL_CONSUMER])
        answers = " ".join(f"R{i}={'yes' if signals[k] else 'no'}" for i, k in enumerate(SIGNAL_KEYS, start=1))
        lines.append(f'- "{activity}" → {answers} → score {score} → {verdict}')
    return "\n".join(lines)


def classifier_system(*, with_scope: bool, with_placement: bool, taxonomy: Taxonomy) -> str:
    """The CLASSIFY system prompt: only the halves asked for; the absent half is "already decided"."""
    if not with_scope and not with_placement:
        raise ValueError("classifier_system was asked for neither half; the caller should not make the call")
    parts = [
        "You are classifying one business activity described by a process expert during a discovery interview. You "
        "do not talk to the expert and you do not ask questions. You return JSON and nothing else.",
        fence_instruction("ACTIVITY", "The activity"),
        "",
        "=== HOW TO FRAME WHAT YOU ARE JUDGING ===",
        FRAME_RULE,
    ]
    if with_scope:
        parts += [
            "",
            "=== PART 1: IS THIS A PROCESS OR A TASK? ===",
            "Answer each of these five signals true or false, about the activity as framed above:",
            "",
            signal_block(),
            "",
            f"`{EXTERNAL_CONSUMER}` is the value test: someone whose own work is blocked without the output, not a "
            "colleague who merely sees it. Answer it strictly; an activity can satisfy four signals and still be one "
            "person's private routine.",
            "",
            "Worked examples, already scored. Match your answers to these:",
            calibration_block(),
            "",
            "Give one sentence of `reasoning` naming the signals that decided it.",
        ]
    else:
        parts += ["", "Whether this is a process or a task is already decided: do not return it (no `scope` block)."]
    if with_placement:
        parts += [
            "",
            "=== PART 2: WHICH CLUSTER? ===",
            "Place the activity in exactly one of the clusters below. Answer with the CODE, never the cluster name.",
            "",
            taxonomy.prompt_block(),
            "",
            "Give `confidence` in [0, 1] for your choice, and a `runner_up` code with its own confidence, or null for "
            f'both when no second cluster is plausible. If none of the clusters fits, answer "{UNKNOWN_CODE}" rather '
            "than forcing a fit. The `rationale` must quote the expert's own words.",
        ]
    else:
        parts += [
            "",
            "The cluster is already decided: do not return it (no `placement` block) and do not mention clusters.",
        ]
    body = ",\n".join(b for b, on in ((_SCOPE_JSON, with_scope), (_PLACEMENT_JSON, with_placement)) if on)
    parts += ["", "Return exactly this JSON shape:", "{\n" + body + "\n}"]
    return "\n".join(parts)


def classifier_user(subject: str, profile: Mapping[str, Any], *, widening: bool = False) -> str:
    """Department, role and the fenced activity; on a widening pass, a note to re-score."""
    lines = [
        "Department: " + text_value(profile.get("department")),
        "Role: " + text_value(profile.get("user_function")),
        "",
        "The activity as the expert described it:",
        fence_untrusted(subject.strip(), "ACTIVITY"),
    ]
    if widening:
        lines += [
            "",
            "This includes the expert's answer to a follow-up asking who depends on the output. Re-score the activity "
            "as it now stands: the answer may have widened it into a real process, or confirmed it is a task.",
        ]
    lines += ["", "Return the JSON."]
    return "\n".join(lines)
