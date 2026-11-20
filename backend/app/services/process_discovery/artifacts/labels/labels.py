"""The LABEL call and the grounding of its reply in the profile (spec 19 §3.3, §3.4).

Why: the Data and Rules readiness dimensions are counted from labels: the format of each input a
step reads and the kind of each decision it takes. The model reads the words; code trusts none of
it until checked. A label must name a real input of a real step, and its evidence must be the
expert's words from that same step (product rule 6). One bad label is dropped and counted, never
fatal; a failed call is a failure (Data and Rules then show as unknown), never invented labels.
What: `run_labels` (one `generate_structured` call, any `LLMError` → `LabelsFailedError`, one
`assessment_call` log line with counts only) and `ground_labels` (pure: rules L1–L6).
Must not: log any text from the profile or the reply, keep an input the step does not list, accept
evidence from another step, or import `analysis/`, `diagram/` or `step_assessment/`.
Spec 19 §3.3, §3.4, §4.2; AC-19.18 to AC-19.22.
"""

from __future__ import annotations

import logging
import time
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

from app.models.process_discovery_schemas import DecisionLabel, InputLabel, StepLabels

from ...domain.field_spec import Vocabulary
from ...llm import LLM, CallType, ChatMessage, LLMError
from ...profile.shapes import as_list, as_mapping, rows_of
from ..evidence import Value, find_evidence, normalise_quote, profile_values, restrict_to_step
from .prompts import LABEL_SYSTEM, labels_user
from .schemas import DECISION_KINDS, INPUT_FORMATS, LabelsOut

logger = logging.getLogger("app.assessment")

MAX_DECISIONS_PER_STEP = 5  # L4
MAX_DECISION_CHARS = 200  # L4
DROP_REASONS: tuple[str, ...] = ("step", "input", "quote", "invalid", "cap")
_ELLIPSIS = "…"


class LabelsFailedError(Exception):
    """The LABEL call returned nothing usable; Data and Rules are then not rated."""


def _one_line(value: Any, limit: int) -> str:
    """Non-strings → "", control characters → space, whitespace collapsed, cut with "…"."""
    if not isinstance(value, str):
        return ""
    text = " ".join("".join(" " if unicodedata.category(ch).startswith("C") else ch for ch in value).split())
    return text if len(text) <= limit else text[: limit - 1] + _ELLIPSIS


def _inputs(
    raw: Any, stored: Sequence[str], values: Sequence[Value], dropped: dict[str, int]
) -> list[InputLabel]:  # fmt: skip
    by_norm = {normalise_quote(name).strip(): name for name in stored}
    out: list[InputLabel] = []
    for item in as_list(raw) or []:
        label = as_mapping(item) or {}
        raw_name = label.get("name")
        name = by_norm.get(normalise_quote(raw_name).strip()) if isinstance(raw_name, str) else None
        if label.get("format") not in INPUT_FORMATS:
            dropped["invalid"] += 1
        elif name is None or any(i.name == name for i in out):
            dropped["input"] += 1
        elif (hit := find_evidence(label.get("evidence"), values)) is None:
            dropped["quote"] += 1
        else:
            out.append(InputLabel(name=name, format=str(label["format"]), evidence=hit.quote))
    return out


def _decisions(raw: Any, values: Sequence[Value], dropped: dict[str, int]) -> list[DecisionLabel]:
    out: list[DecisionLabel] = []
    for item in as_list(raw) or []:
        decision = as_mapping(item) or {}
        text = _one_line(decision.get("text"), MAX_DECISION_CHARS)
        if not text or decision.get("kind") not in DECISION_KINDS:
            dropped["invalid"] += 1
        elif (hit := find_evidence(decision.get("evidence"), values)) is None:
            dropped["quote"] += 1
        elif len(out) >= MAX_DECISIONS_PER_STEP:
            dropped["cap"] += 1
        else:
            out.append(DecisionLabel(text=text, kind=str(decision["kind"]), evidence=hit.quote))
    return out


def ground_labels(
    reply: LabelsOut | Mapping[str, Any], profile: Mapping[str, Any]
) -> tuple[list[StepLabels], dict[str, int]]:
    """One `StepLabels` per step 1..N (empty when nothing was kept) and the drop counts. Pure."""
    data = reply.model_dump() if isinstance(reply, LabelsOut) else as_mapping(reply) or {}
    rows = rows_of(profile)
    values = profile_values(profile)
    dropped = dict.fromkeys(DROP_REASONS, 0)
    kept: dict[int, StepLabels] = {}
    seen: set[int] = set()
    for item in as_list(data.get("steps")) or []:
        entry = as_mapping(item) or {}
        step = entry.get("step")
        if not isinstance(step, int) or isinstance(step, bool) or not 1 <= step <= len(rows) or step in seen:
            dropped["step"] += 1
            continue
        seen.add(step)
        stored = [n for n in as_list((as_mapping(rows[step - 1].get("data")) or {}).get("inputs")) or []
                  if isinstance(n, str) and n.strip()]  # fmt: skip
        step_values = restrict_to_step(values, step)
        kept[step] = StepLabels(
            step=step,
            inputs=_inputs(entry.get("inputs"), stored, step_values, dropped),
            decisions=_decisions(entry.get("decisions"), step_values, dropped),
        )
    return [kept.get(k) or StepLabels(step=k) for k in range(1, len(rows) + 1)], dropped


def _log(outcome: str, started: float, *, kept: int, dropped: Mapping[str, int], error: str = "") -> None:
    """The one `assessment_call` line: counts and codes only, never text."""
    fields: dict[str, Any] = {
        "call": CallType.LABEL.value,
        "outcome": outcome,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "kept": kept,
        "dropped": dict(dropped),
    }
    if error:
        fields["error"] = error
    logger.log(logging.INFO if outcome == "generated" else logging.WARNING, "assessment_call", extra=fields)


async def run_labels(
    profile: Mapping[str, Any],
    llm: LLM,
    *,
    vocab: Vocabulary,
    documents: Sequence[Mapping[str, str]] = (),
) -> tuple[list[StepLabels], dict[str, int]]:
    """One LABEL call, grounded. Raises `LabelsFailedError` on any `LLMError`."""
    messages: list[ChatMessage] = [
        {"role": "system", "content": LABEL_SYSTEM},
        {"role": "user", "content": labels_user(profile, vocab=vocab, documents=documents)},
    ]
    started = time.monotonic()
    try:
        reply = await llm.generate_structured(LabelsOut, CallType.LABEL, messages)
    except LLMError as error:
        _log("failed", started, kept=0, dropped=dict.fromkeys(DROP_REASONS, 0), error=type(error).__name__)
        raise LabelsFailedError("The input and decision labels could not be generated.") from error
    labels, dropped = ground_labels(reply, profile)
    _log("generated", started, kept=sum(len(s.inputs) + len(s.decisions) for s in labels), dropped=dropped)
    return labels, dropped
