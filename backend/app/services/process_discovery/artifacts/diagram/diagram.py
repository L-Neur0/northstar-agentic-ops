"""The MAP call, the stored `ProcessDiagram`, and the data objects and stores code adds (spec 18 §3.7–3.9).

Why: every finished profile must have a map (F-13.2), so a bad reply is not a failure here: an
empty, refused or twice-invalid reply is grounded as "no reply" and gives the linear map, flagged
`simplified`. Only a failed call (service unavailable, budget refused) raises `MapCallFailedError`,
and the orchestrator then stores `linear_process_diagram`. Inputs, outputs and systems are drawn
from the profile by code, never by the model, so the screen, the PDF and the BPMN export agree.
What: `run_map` (one `generate_structured` call, grounding, one `assessment_call` log line),
`linear_process_diagram`, `to_process_diagram` (adds data objects, data stores and `steps_hash`).
Must not: store or draw any model content that grounding did not keep; log profile or reply text;
import `artifacts/analysis`.
Spec 18 §3.7–3.9, §4.3; AC-18.19, AC-18.36, AC-18.37, AC-18.39.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from app.models.process_discovery_schemas import DataObject, DataStore, ProcessDiagram

from ...domain.field_spec import Vocabulary
from ...llm import LLM, CallType, ChatMessage, LLMEmptyResponseError, LLMError, LLMInvalidOutputError
from ..fingerprint import map_fingerprint
from .grounding import MAX_LABEL_CHARS, GroundedDiagram, clean, ground_diagram, linear_diagram, substeps_of
from .prompts import MAP_SYSTEM, map_user
from .schemas import ProcessDiagramOut

logger = logging.getLogger("app.assessment")

MAX_DATA_ITEMS = 3  # items named in one data-object label before "+N"
_DIRECTIONS: tuple[tuple[Literal["input", "output"], str, str], ...] = (
    ("input", "inputs", "i"),
    ("output", "outputs", "o"),
)


class MapCallFailedError(Exception):
    """The MAP call itself failed (unavailable, budget) or there is nothing to draw."""


def short_list(items: Any) -> str:
    """Cleaned, de-duplicated (case-insensitive) items, at most three joined by "; ", then " +N"."""
    seen: dict[str, str] = {}
    for item in items if isinstance(items, list) else []:
        text = clean(item, MAX_LABEL_CHARS)
        if text:
            seen.setdefault(text.casefold(), text)
    names = list(seen.values())
    label = "; ".join(names[:MAX_DATA_ITEMS])
    return label + (f" +{len(names) - MAX_DATA_ITEMS}" if len(names) > MAX_DATA_ITEMS else "")


def _data(profile: Mapping[str, Any]) -> tuple[list[DataObject], list[DataStore]]:
    """One input and one output object per step with data; one store per distinct system."""
    objects: list[DataObject] = []
    stores: dict[str, tuple[str, list[int]]] = {}
    for number, step in enumerate(substeps_of(profile), start=1):
        data = step.get("data")
        data = data if isinstance(data, Mapping) else {}
        for direction, key, suffix in _DIRECTIONS:
            label = short_list(data.get(key))
            if label:
                objects.append(DataObject(id=f"do{number}{suffix}", step_index=number, direction=direction,
                                          label=label))  # fmt: skip
        systems = step.get("systems")
        for system in systems if isinstance(systems, list) else []:
            name = clean(system, MAX_LABEL_CHARS)
            if not name:
                continue
            _, steps = stores.setdefault(name.casefold(), (name, []))
            if number not in steps:
                steps.append(number)
    data_stores = [
        DataStore(id=f"ds{i}", label=label, steps=steps) for i, (label, steps) in enumerate(stores.values(), start=1)
    ]
    return objects, data_stores


def to_process_diagram(grounded: GroundedDiagram, profile: Mapping[str, Any]) -> ProcessDiagram:
    """The storage model: the grounded graph, plus data objects and stores from the profile, plus `steps_hash`."""
    objects, stores = _data(profile)
    return ProcessDiagram(
        lanes=grounded.lanes,
        nodes=grounded.nodes,
        flows=grounded.flows,
        data_objects=objects,
        data_stores=stores,
        simplified=grounded.simplified,
        steps_hash=map_fingerprint(profile),
    )


def linear_process_diagram(profile: Mapping[str, Any]) -> ProcessDiagram | None:
    """The map drawn by code alone; `None` without steps."""
    grounded = linear_diagram(profile)
    return to_process_diagram(grounded, profile) if grounded is not None else None


def _log(outcome: str, started: float, *, kept: int, simplified: bool, rule: str = "", error: str = "") -> None:
    """The one `assessment_call` line (§3.9): counts and codes only, never text."""
    fields: dict[str, Any] = {
        "call": CallType.MAP.value,
        "outcome": outcome,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "kept": kept,
        "simplified": simplified,
    }
    if rule:
        fields["fallback_rule"] = rule
    if error:
        fields["error"] = error
    logger.log(logging.INFO if outcome == "generated" else logging.WARNING, "assessment_call", extra=fields)


async def run_map(
    profile: Mapping[str, Any], llm: LLM, *, vocab: Vocabulary, documents: Sequence[Mapping[str, str]] = ()
) -> ProcessDiagram:
    """One MAP call, grounded; a bad reply gives the linear map. Raises `MapCallFailedError` on a failed call."""
    started = time.monotonic()
    if linear_diagram(profile) is None:
        _log("failed", started, kept=0, simplified=False, error="no_steps")
        raise MapCallFailedError("The process has no steps to draw.")
    messages: list[ChatMessage] = [
        {"role": "system", "content": MAP_SYSTEM},
        {"role": "user", "content": map_user(profile, vocab=vocab, documents=documents)},
    ]
    reply: dict[str, Any] | None
    try:
        reply = (await llm.generate_structured(ProcessDiagramOut, CallType.MAP, messages)).model_dump()
    except (LLMEmptyResponseError, LLMInvalidOutputError):
        reply = None  # a bad reply, not a failed call: grounding draws the linear map
    except LLMError as error:
        _log("failed", started, kept=0, simplified=False, error=type(error).__name__)
        raise MapCallFailedError("The process map could not be generated.") from error
    grounded = ground_diagram(reply, profile)
    if grounded is None:  # pragma: no cover - steps were checked above
        raise MapCallFailedError("The process has no steps to draw.")
    _log("fallback" if grounded.simplified else "generated", started, kept=len(grounded.nodes),
         simplified=grounded.simplified, rule=grounded.fallback_rule)  # fmt: skip
    return to_process_diagram(grounded, profile)
