"""Reading a BPMN 2.0 file in code: the process, its steps in order, lanes as roles (spec 17 §3.6; AD-12).

Why: a process map already states the steps, their order and who does them. Reading it in code
costs nothing, cannot invent a value and needs no model call; the output has the same shape as the
model's (`ReadDocumentOut`), so the quote check and the fill-only filter are one code path for
both. The file is untrusted XML, so it is parsed with `defusedxml` and refused at any DTD or entity.
What: `BpmnRead` and `read_bpmn(data, budget)`: picks the process with the most named tasks, orders
its tasks with `domain.node_order.rank_nodes` (loops do not change the order), maps each task's
innermost lane to a role, takes P04, P06 and P07 from the process, start and end names, and
renders the stored text one item per line; each quote is the element name it came from.
Must not: reach the network, expand an entity, read more than 500 flow nodes, read the inside of
a sub-process, or call a model. Spec 17 §3.6, §3.16; AC-17.8, AC-17.17 to AC-17.19.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring
from pydantic import BaseModel

from ..domain.node_order import rank_nodes
from .extract import ExtractedText, clean_and_cap
from .intake import BPMN_NS, unreadable
from .schema import read_document_model

MAX_FLOW_NODES = 500
TOO_LARGE = "This diagram is too large to read."
NS = f"{{{BPMN_NS}}}"

TASK_TYPES = frozenset(
    {
        "task",
        "userTask",
        "manualTask",
        "serviceTask",
        "scriptTask",
        "businessRuleTask",
        "sendTask",
        "receiveTask",
        "callActivity",
        "subProcess",
    }
)
EVENT_TYPES = frozenset({"startEvent", "endEvent", "intermediateCatchEvent", "intermediateThrowEvent", "boundaryEvent"})
GATEWAY_TYPES = frozenset(
    {"exclusiveGateway", "parallelGateway", "inclusiveGateway", "eventBasedGateway", "complexGateway"}
)
FLOW_TYPES = TASK_TYPES | EVENT_TYPES | GATEWAY_TYPES


@dataclass(frozen=True)
class BpmnRead:
    """The stored text, the raw reading in the model's shape, and how many other processes were ignored."""

    text: ExtractedText
    raw: BaseModel
    processes_ignored: int


def _local(element: Element) -> str:
    tag = element.tag
    return tag[len(NS) :] if isinstance(tag, str) and tag.startswith(NS) else ""


def _name(element: Element | None) -> str:
    return " ".join((element.get("name") or "").split()) if element is not None else ""


def _flow_nodes(process: Element) -> list[Element]:
    return [child for child in process if _local(child) in FLOW_TYPES]


def _named_tasks(process: Element) -> int:
    return sum(1 for n in _flow_nodes(process) if _local(n) in TASK_TYPES and _name(n))


def _lanes(process: Element) -> dict[str, str]:
    """Task id → name of the innermost lane listing it (a deeper lane overrides its parent)."""
    lanes: dict[str, str] = {}

    def walk(lane_set: Element) -> None:
        for lane in lane_set.findall(f"{NS}lane"):
            for ref in lane.findall(f"{NS}flowNodeRef"):
                if ref.text:
                    lanes[ref.text.strip()] = _name(lane)
            for child in lane.findall(f"{NS}childLaneSet"):
                walk(child)

    for lane_set in process.findall(f"{NS}laneSet"):
        walk(lane_set)
    return lanes


def _q(value: str) -> dict[str, str] | None:
    return {"value": value, "quote": value} if value else None


def read_bpmn(data: bytes, budget: int) -> BpmnRead:
    """Read the BPMN bytes in code; `document_unreadable` on a DTD, an entity, no process or > 500 nodes."""
    try:
        root = fromstring(data, forbid_dtd=True)
    except (DefusedXmlException, SyntaxError, ValueError):
        raise unreadable() from None
    processes = root.findall(f"{NS}process")
    if not processes:
        raise unreadable()
    process = max(processes, key=_named_tasks)  # `max` keeps the first of equals
    nodes = _flow_nodes(process)
    if len(nodes) > MAX_FLOW_NODES:
        raise unreadable(TOO_LARGE)

    ids = [n.get("id") or f"_{i}" for i, n in enumerate(nodes)]
    flows = [((f.get("sourceRef") or ""), (f.get("targetRef") or "")) for f in process.findall(f"{NS}sequenceFlow")]
    rank, _ = rank_nodes(ids, flows)
    position = {node_id: i for i, node_id in enumerate(ids)}
    by_id = dict(zip(ids, nodes, strict=True))

    tasks = sorted(
        (i for i, n in zip(ids, nodes, strict=True) if _local(n) in TASK_TYPES and _name(n)),
        key=lambda i: (rank[i], position[i]),
    )
    lanes = _lanes(process)

    participant = next((p for p in root.iter(f"{NS}participant") if p.get("processRef") == process.get("id")), None)
    name = _name(process) or _name(participant)
    start = next((_name(n) for n in nodes if _local(n) == "startEvent"), "")
    ends = [i for i, n in zip(ids, nodes, strict=True) if _local(n) == "endEvent"]
    last_end = max(ends, key=lambda i: (rank[i], -position[i])) if ends else None
    end = _name(by_id[last_end]) if last_end is not None else ""

    lines: list[str] = []
    if name:
        lines.append(f"Process: {name}")
    if start:
        lines.append(f"Start: {start}")
    steps: list[dict[str, Any]] = []
    for number, task_id in enumerate(tasks, start=1):
        task_name = _name(by_id[task_id])
        lane = lanes.get(task_id, "")
        lines.append(f"Step {number}: {task_name}" + (f" (lane: {lane})" if lane else ""))
        roles = [{"role": lane, "contribution": None, "quote": lane}] if lane else []
        steps.append({"name": {"value": task_name, "quote": task_name}, "roles": roles})
    if end:
        lines.append(f"End: {end}")

    text = clean_and_cap("\n".join(lines), budget)
    raw = read_document_model().model_validate(
        {
            "document_role": "whole_process",
            "name": _q(name),
            "trigger": _q(start),
            "end_result": _q(end),
            "steps": steps,
        }
    )
    return BpmnRead(text, raw, len(processes) - 1)
