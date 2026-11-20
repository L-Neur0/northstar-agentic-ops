"""Grounding the model's process map in the real profile (spec 18 §3.8, rules G1–G24).

Why: this is the anti-hallucination layer between the MAP reply and what is stored and drawn.
Structured Outputs guarantees the reply's shape; nothing guarantees its content, so none of it is
trusted. Tasks survive only for real steps and carry the real step names; lanes only for real roles;
markers only when legal for their type (and never claiming a system the step does not list); flows
are repaired into one connected start-to-end graph that meets the steps in order and obeys the BPMN
rules (merges where paths join, no pass-through gateways, no unnamed decisions). A reply that cannot
be repaired falls back to `linear_diagram`, the start → step 1 → … → step N → end map drawn by code,
so even a completely wrong answer gives a correct, simpler map.
What: `ground_diagram`, `linear_diagram`, `short_event_label` and `GroundedDiagram` (with the rule
that forced a fallback, for the log). Pure: no I/O, no clock; never mutates its input; any exception
inside degrades to the linear map (G24).
Must not: invent a step, role or system; keep a model label on a task; import `artifacts/analysis`.
Spec 18 §3.8, §4.3; AC-18.20 to AC-18.35, AC-18.38.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.models.process_discovery_schemas import DIAGRAM_MARKERS_BY_TYPE, DiagramFlow, DiagramNode

from ...domain.node_order import rank_nodes

logger = logging.getLogger("app.assessment")

MAX_LABEL_CHARS = 60
MAX_FLOW_LABEL_CHARS = 20
MAX_ID_CHARS = 40
MAX_NODES = 40  # more is not a readable one-page map
MAX_LANES = 8  # distinct role lanes before the rest share OTHER_LANE
MAX_RAW_ITEMS = 200  # replies are never iterated past this many entries
MAX_EVENT_LABEL_CHARS = 40
MAX_EVENT_LABEL_WORDS = 6

OTHER_LANE = "Other"
NODE_TYPES = tuple(DIAGRAM_MARKERS_BY_TYPE)

# Where a sentence's first clause ends; a comma or colon inside "1,000" or "10:30" is not a break.
_CLAUSE_BREAK = re.compile(r"[,;:.](?=\s|$)|\(| - | (?:and|when|because|which|that) ", re.IGNORECASE)
# A trigger written as "when …" reads better as a state: "The invoice is posted".
_LEADING_CONJUNCTION = re.compile(r"^(?:when|if|once|after)\s+", re.IGNORECASE)
# Event markers that name a trigger; meaningless on an event with no label (G23).
_TRIGGER_MARKERS = {"message", "timer", "conditional", "signal"}
# Task markers that claim a system did or supported the work (G7).
_SYSTEM_DEPENDENT_TASK_MARKERS = {"user", "service", "script", "business_rule", "send", "receive"}
# Split types whose branches must say which answer they are (G17).
_LABELLED_SPLITS = {"exclusive", "inclusive", "event_based"}


@dataclass
class GroundedDiagram:
    """The storage-ready pieces of a `ProcessDiagram`; `fallback_rule` names why a linear map was drawn."""

    lanes: list[str] = field(default_factory=list)
    nodes: list[DiagramNode] = field(default_factory=list)
    flows: list[DiagramFlow] = field(default_factory=list)
    simplified: bool = False
    fallback_rule: str = ""


Node = dict[str, Any]
Flow = dict[str, Any]


def clean(value: Any, limit: int) -> str:
    """One line, control characters removed, capped with "…"; "" for anything that is not a string."""
    if not isinstance(value, str):
        return ""
    text = "".join(" " if unicodedata.category(ch).startswith("C") else ch for ch in value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _norm(value: Any) -> str:
    return clean(value, 200).casefold()


def _default_marker(node_type: str) -> str:
    return DIAGRAM_MARKERS_BY_TYPE[node_type][0]


def short_event_label(text: str) -> str:
    """`text` as a start or end label of at most 40 characters: whole if it fits, else its first clause
    (at least three words), else cut at a word boundary with "…". A leading "when/if/once/after" is
    dropped and the first letter capitalised."""
    text = _LEADING_CONJUNCTION.sub("", " ".join(text.split()))
    text = text[:1].upper() + text[1:]
    if len(text) <= MAX_EVENT_LABEL_CHARS:
        return text
    clause = _CLAUSE_BREAK.split(text, maxsplit=1)[0].strip()
    if len(clause.split()) >= 3 and len(clause) <= MAX_EVENT_LABEL_CHARS:
        return clause
    cut = (clause if len(clause.split()) >= 3 else text)[: MAX_EVENT_LABEL_CHARS - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:-") + "…"


def _event_label(model_label: str, profile_label: str) -> str:
    """The model's own label when it is short enough (G23), else the profile's."""
    if model_label and len(model_label) <= MAX_EVENT_LABEL_CHARS and len(model_label.split()) <= MAX_EVENT_LABEL_WORDS:
        return model_label
    return profile_label or short_event_label(model_label)


# --- reading the profile ------------------------------------------------------------------------------


def _process(profile: Any) -> Mapping[str, Any]:
    process = profile.get("process") if isinstance(profile, Mapping) else None
    return process if isinstance(process, Mapping) else {}


def substeps_of(profile: Any) -> list[Mapping[str, Any]]:
    substeps = _process(profile).get("substeps")
    if not isinstance(substeps, list):
        return []
    return [s if isinstance(s, Mapping) else {} for s in substeps]


def _step_name(substep: Mapping[str, Any], number: int) -> str:
    return clean(substep.get("name"), MAX_LABEL_CHARS) or f"Step {number}"


def _step_owner(substep: Mapping[str, Any]) -> str:
    return clean(substep.get("owner"), MAX_LABEL_CHARS)


def _has_systems(substep: Mapping[str, Any]) -> bool:
    systems = substep.get("systems")
    return isinstance(systems, list) and any(clean(s, MAX_LABEL_CHARS) for s in systems)


def _step_roles(substep: Mapping[str, Any]) -> list[str]:
    """The step owner plus every roles-involved role (none rows add nothing)."""
    roles = [_step_owner(substep)]
    rows = substep.get("roles")
    for entry in rows if isinstance(rows, list) else []:
        if isinstance(entry, Mapping):
            roles.append(clean(entry.get("role"), MAX_LABEL_CHARS))
    return [r for r in roles if r]


def _process_field(profile: Any, key: str) -> str:
    """The trigger or end result as a short event label."""
    return short_event_label(clean(_process(profile).get(key), 500))


def _known_roles(profile: Any, substeps: list[Mapping[str, Any]]) -> dict[str, str]:
    """Every real role in the profile, normalised → display form (first spelling wins)."""
    known: dict[str, str] = {}
    for substep in substeps:
        for role in _step_roles(substep):
            known.setdefault(role.casefold(), role)
    owner = _process(profile).get("process_owner")
    owner_role = clean(owner.get("role"), MAX_LABEL_CHARS) if isinstance(owner, Mapping) else ""
    if owner_role:
        known.setdefault(owner_role.casefold(), owner_role)
    return known


def _as_index(value: Any) -> int | None:
    """An int that is really an int: not a bool, not a numeric string."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _resolve_marker(node_type: str, raw_marker: Any) -> str:
    """`raw_marker` if legal for `node_type`, else the type's default (G7)."""
    if isinstance(raw_marker, str) and raw_marker in DIAGRAM_MARKERS_BY_TYPE[node_type]:
        return raw_marker
    return _default_marker(node_type)


def _task_marker(substep: Mapping[str, Any], requested: str) -> str:
    """A marker that claims a system becomes `manual` when the step lists none (G7)."""
    if requested in _SYSTEM_DEPENDENT_TASK_MARKERS and not _has_systems(substep):
        return "manual"
    return requested


def _lane_list(names_in_order: list[str]) -> tuple[list[str], dict[str, int]]:
    """Distinct lane names (case-insensitive) in first-seen order, those past 8 folded into `Other`."""
    lanes: list[str] = []
    index: dict[str, int] = {}
    other = OTHER_LANE.casefold()
    for name in names_in_order:
        key = name.casefold()
        if key in index:
            continue
        if len(lanes) >= MAX_LANES and key != other:
            if other not in index:
                index[other] = len(lanes)
                lanes.append(OTHER_LANE)
            index[key] = index[other]
            continue
        index[key] = len(lanes)
        lanes.append(name)
    return lanes, index


# --- the linear map -----------------------------------------------------------------------------------


def linear_diagram(profile: Mapping[str, Any]) -> GroundedDiagram | None:
    """start → step 1 → … → step N → end in the owners' lanes; `None` when there are no steps."""
    substeps = substeps_of(profile)
    if not substeps:
        return None
    owners = [_step_owner(s) or OTHER_LANE for s in substeps]
    lanes, lane_index = _lane_list(owners)

    def lane(name: str) -> str:
        return lanes[lane_index[name.casefold()]]

    nodes = [DiagramNode(id="start", type="start", label=_process_field(profile, "trigger"), lane=lane(owners[0]),
                         marker="none")]  # fmt: skip
    for number, (substep, owner) in enumerate(zip(substeps, owners, strict=True), start=1):
        # Without a model, a step with a system is a person using it, a step with none is done by hand.
        marker = "user" if _has_systems(substep) else "manual"
        nodes.append(DiagramNode(id=f"t{number}", type="task", label=_step_name(substep, number), lane=lane(owner),
                                 step_index=number, marker=marker))  # fmt: skip
    nodes.append(DiagramNode(id="end", type="end", label=_process_field(profile, "end_result"), lane=lane(owners[-1]),
                             marker="none"))  # fmt: skip
    flows = [DiagramFlow(source=a.id, target=b.id) for a, b in zip(nodes, nodes[1:], strict=False)]
    return GroundedDiagram(lanes=lanes, nodes=nodes, flows=flows, simplified=True)


# --- grounding ------------------------------------------------------------------------------------------


def ground_diagram(reply: Any, profile: Mapping[str, Any]) -> GroundedDiagram | None:
    """The reply grounded in `profile`, or the linear map when it cannot be repaired; `None` only without steps."""
    linear = linear_diagram(profile)
    if linear is None:
        return None
    try:
        grounded = _ground(reply, profile)
    except Exception as error:  # G24: a repair bug degrades to the linear map, never crashes
        logger.warning("map_grounding_error", extra={"error": type(error).__name__})
        grounded = "G24"
    if isinstance(grounded, str):
        linear.fallback_rule = grounded
        return linear
    return grounded


def _ground(reply: Any, profile: Mapping[str, Any]) -> GroundedDiagram | str:
    """The grounded map, or the rule (G-code) that makes it unrepairable."""
    if not isinstance(reply, Mapping):
        return "G1"
    substeps = substeps_of(profile)
    step_count = len(substeps)
    known = _known_roles(profile, substeps)

    # G2: a reply lane counts only if it names a real role.
    raw_lanes = reply.get("lanes")
    lane_names: dict[int, str] = {}
    for i, name in enumerate(raw_lanes[:MAX_RAW_ITEMS] if isinstance(raw_lanes, list) else []):
        role = known.get(_norm(name))
        if role:
            lane_names[i] = role

    # --- nodes (G3–G8) ---
    nodes: list[Node] = []
    ids: set[str] = set()
    task_for_step: dict[int, str] = {}
    raw_nodes = reply.get("nodes")
    for raw in raw_nodes[:MAX_RAW_ITEMS] if isinstance(raw_nodes, list) else []:
        if not isinstance(raw, Mapping):
            continue
        node_id = clean(raw.get("id"), MAX_ID_CHARS)
        node_type = raw.get("type")
        if not node_id or node_id in ids or node_type not in NODE_TYPES:
            continue
        lane_raw = _as_index(raw.get("lane"))
        lane_name = lane_names.get(lane_raw) if lane_raw is not None else None
        marker = _resolve_marker(node_type, raw.get("marker"))

        if node_type == "task":
            step = _as_index(raw.get("step_index"))
            if step is None or not 1 <= step <= step_count or step in task_for_step:
                continue  # G4: an invented, missing or repeated step
            substep = substeps[step - 1]
            allowed = {r.casefold() for r in _step_roles(substep)}
            if not (lane_name and lane_name.casefold() in allowed):
                lane_name = _step_owner(substep) or OTHER_LANE  # G5
            label = _step_name(substep, step)  # G6
            marker = _task_marker(substep, marker)
            task_for_step[step] = node_id
        else:
            step = None
            label = clean(raw.get("label"), MAX_LABEL_CHARS)
        ids.add(node_id)
        nodes.append({"id": node_id, "type": node_type, "label": label, "lane": lane_name, "step": step,
                      "marker": marker})  # fmt: skip

    if len(task_for_step) != step_count or len(nodes) > MAX_NODES:
        return "G8"
    by_id = {n["id"]: n for n in nodes}

    # --- flows (G9, G10) ---
    flows: list[Flow] = []
    seen: set[tuple[str, str]] = set()
    default_claimed: set[str] = set()
    raw_flows = reply.get("flows")
    for raw in raw_flows[:MAX_RAW_ITEMS] if isinstance(raw_flows, list) else []:
        if not isinstance(raw, Mapping):
            continue
        source = clean(raw.get("source"), MAX_ID_CHARS)
        target = clean(raw.get("target"), MAX_ID_CHARS)
        if source not in by_id or target not in by_id or source == target or (source, target) in seen:
            continue
        if by_id[target]["type"] == "start" or by_id[source]["type"] == "end":
            continue
        seen.add((source, target))
        is_default = (
            raw.get("is_default") is True and by_id[source]["type"] == "gateway" and source not in default_claimed
        )
        if is_default:
            default_claimed.add(source)
        flows.append({"source": source, "target": target, "label": clean(raw.get("label"), MAX_FLOW_LABEL_CHARS),
                      "is_default": is_default})  # fmt: skip

    def remove(node_id: str) -> None:
        nodes.remove(by_id.pop(node_id))
        flows[:] = [f for f in flows if node_id not in (f["source"], f["target"])]

    def add_flow(source: str, target: str) -> None:
        if (source, target) not in {(f["source"], f["target"]) for f in flows}:
            flows.append({"source": source, "target": target, "label": "", "is_default": False})

    def add_node(base: str, node_type: str) -> str:
        node_id, n = base, 2
        while node_id in by_id:
            node_id, n = f"{base}{n}", n + 1
        by_id[node_id] = {"id": node_id, "type": node_type, "label": "", "lane": None, "step": None,
                          "marker": _default_marker(node_type)}  # fmt: skip
        nodes.append(by_id[node_id])
        return node_id

    # --- G11: one start, at least one end ---
    starts = [n["id"] for n in nodes if n["type"] == "start"]
    for extra in starts[1:]:
        remove(extra)
    start_id = starts[0] if starts else add_node("start", "start")
    if not any(f["source"] == start_id for f in flows):
        add_flow(start_id, task_for_step[1])
    end_ids = [n["id"] for n in nodes if n["type"] == "end"] or [add_node("end", "end")]

    # --- G12: orphans in, dead ends out ---
    for _ in range(len(nodes) + 1):  # removing a node can orphan another; bounded
        incoming = {f["target"] for f in flows}
        orphans = [n["id"] for n in nodes if n["type"] in ("gateway", "end") and n["id"] not in incoming]
        if not orphans:
            break
        for node_id in orphans:
            if node_id in end_ids and len(end_ids) == 1:
                continue  # the only end is wired below instead
            remove(node_id)
            if node_id in end_ids:
                end_ids.remove(node_id)
    for step, node_id in sorted(task_for_step.items()):
        if not any(f["target"] == node_id for f in flows):
            add_flow(task_for_step.get(step - 1, start_id), node_id)
    for node in list(nodes):
        if node["type"] != "end" and not any(f["source"] == node["id"] for f in flows):
            next_task = task_for_step.get(node["step"] + 1) if node["step"] else None
            add_flow(node["id"], next_task or end_ids[0])

    # --- G13, G14: validate on the model's own graph ---
    if not _connected(start_id, set(end_ids), [n["id"] for n in nodes], flows):
        return "G13"
    # Ranked before merges are added: a merge on one branch would push that branch's task a rank later.
    ranks, _ = rank_nodes([n["id"] for n in nodes], [(f["source"], f["target"]) for f in flows])
    step_ranks = [ranks[task_for_step[s]] for s in range(1, step_count + 1)]
    if any(a > b for a, b in zip(step_ranks, step_ranks[1:], strict=False)):
        return "G14"

    # --- G15–G21: BPMN rules ---
    broken = _apply_bpmn_rules(nodes, flows)
    if broken:
        return broken
    return _finish(nodes, flows, profile, start_id, end_ids, task_for_step)


def _connected(start_id: str, end_ids: set[str], node_ids: list[str], flows: list[Flow]) -> bool:
    """Every node reachable from the start, and every node able to reach an end (G13)."""

    def reach(roots: set[str], edges: list[tuple[str, str]]) -> set[str]:
        adjacency: dict[str, list[str]] = {}
        for a, b in edges:
            adjacency.setdefault(a, []).append(b)
        seen, stack = set(roots), list(roots)
        while stack:
            for nxt in adjacency.get(stack.pop(), []):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    forward = [(f["source"], f["target"]) for f in flows]
    everything = set(node_ids)
    return reach({start_id}, forward) >= everything and reach(end_ids, [(b, a) for a, b in forward]) >= everything


def _apply_bpmn_rules(nodes: list[Node], flows: list[Flow]) -> str | None:
    """Make the repaired graph valid BPMN, in place. `None` when it is; else the rule only a guess could fix."""

    def incoming(node_id: str) -> list[Flow]:
        return [f for f in flows if f["target"] == node_id]

    def outgoing(node_id: str) -> list[Flow]:
        return [f for f in flows if f["source"] == node_id]

    def insert_merge_before(target_id: str, marker: str) -> None:
        ids = {n["id"] for n in nodes}
        merge_id, n = "merge", 2
        while merge_id in ids:
            merge_id, n = f"merge{n}", n + 1
        position = next(i for i, node in enumerate(nodes) if node["id"] == target_id)
        nodes.insert(position, {"id": merge_id, "type": "gateway", "label": "", "lane": None, "step": None,
                                "marker": marker})  # fmt: skip
        for f in incoming(target_id):
            f["target"] = merge_id
        flows.append({"source": merge_id, "target": target_id, "label": "", "is_default": False})

    # G15 (BPMN rule 4): a gateway with one flow in and one out decides nothing; drop it.
    for gateway in [n for n in nodes if n["type"] == "gateway"]:
        ins, outs = incoming(gateway["id"]), outgoing(gateway["id"])
        if len(ins) == 1 and len(outs) == 1:
            source, target = ins[0]["source"], outs[0]["target"]
            if source == target or any(f["source"] == source and f["target"] == target for f in flows):
                return "G15"
            ins[0]["target"] = target
            if not ins[0]["label"] and not ins[0]["is_default"]:
                ins[0]["label"], ins[0]["is_default"] = outs[0]["label"], outs[0]["is_default"]
            flows[:] = [f for f in flows if f is not outs[0]]
            nodes.remove(gateway)

    # G16 (rule 3): a task or the start leading to several places hides a decision code cannot name.
    for node in nodes:
        if node["type"] in ("task", "start") and len(outgoing(node["id"])) > 1:
            return "G16"

    # G17 (rule 6): every branch of a decision says which answer it is; the default may stay unlabelled.
    for node in nodes:
        outs = outgoing(node["id"])
        if node["type"] == "gateway" and len(outs) > 1 and node["marker"] in _LABELLED_SPLITS:
            if any(not f["label"] and not f["is_default"] for f in outs):
                return "G17"

    # G18 (rule 5): a gateway that both merges and splits becomes a merge followed by a split.
    for node in [n for n in nodes if n["type"] == "gateway"]:
        if len(incoming(node["id"])) > 1 and len(outgoing(node["id"])) > 1:
            insert_merge_before(node["id"], _merge_marker(node["id"], nodes, flows))

    # G19 (rule 2): paths that join at a task or an end meet in a merge gateway first.
    for node in [n for n in nodes if n["type"] in ("task", "end")]:
        if len(incoming(node["id"])) > 1:
            insert_merge_before(node["id"], _merge_marker(node["id"], nodes, flows))

    # G21 (rule 9): the repairs must still leave a readable one-page map.
    if len(nodes) > MAX_NODES:
        return "G21"
    return None


def _merge_marker(target_id: str, nodes: list[Node], flows: list[Flow]) -> str:
    """G20: exclusive for a loop coming back, else the type of the nearest split whose branches meet
    here (it reaches at least two of the arriving flows' sources by forward edges), else exclusive."""
    ranks, back = rank_nodes([n["id"] for n in nodes], [(f["source"], f["target"]) for f in flows])
    arriving = [f for f in flows if f["target"] == target_id]
    if any((f["source"], f["target"]) in back for f in arriving):
        return "exclusive"
    forward: dict[str, list[str]] = {}
    for f in flows:
        if (f["source"], f["target"]) not in back:
            forward.setdefault(f["source"], []).append(f["target"])
    sources = {f["source"] for f in arriving}

    def reached(start: str) -> set[str]:
        seen, stack = {start}, [start]
        while stack:
            for nxt in forward.get(stack.pop(), []):
                if nxt != target_id and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    meeting = [
        n
        for n in nodes
        if n["type"] == "gateway" and len(forward.get(n["id"], [])) > 1 and len(sources & reached(n["id"])) >= 2
    ]
    if not meeting:
        return "exclusive"
    return max(meeting, key=lambda n: ranks[n["id"]])["marker"]


def _finish(
    nodes: list[Node],
    flows: list[Flow],
    profile: Mapping[str, Any],
    start_id: str,
    end_ids: list[str],
    task_for_step: dict[int, str],
) -> GroundedDiagram:
    """G22 lanes, G23 event labels, then the storage models."""
    lane_of: dict[str, str | None] = {n["id"]: n["lane"] for n in nodes}
    for _ in range(len(nodes)):
        pending = [n for n in nodes if lane_of[n["id"]] is None]
        if not pending:
            break
        for node in pending:
            neighbours = [f["target"] for f in flows if f["source"] == node["id"]]
            neighbours += [f["source"] for f in flows if f["target"] == node["id"]]
            lane_of[node["id"]] = next((lane_of[x] for x in neighbours if lane_of.get(x)), None)
    first_task_lane = lane_of[task_for_step[1]] or OTHER_LANE
    resolved = {node_id: lane or first_task_lane for node_id, lane in lane_of.items()}

    ordered = [resolved[task_for_step[s]] for s in sorted(task_for_step)] + [resolved[n["id"]] for n in nodes]
    lanes, lane_index = _lane_list(ordered)

    trigger, end_result = _process_field(profile, "trigger"), _process_field(profile, "end_result")
    out_nodes: list[DiagramNode] = []
    for node in nodes:
        label = node["label"]
        if node["id"] == start_id:
            label = _event_label(label, trigger)
        elif node["id"] in end_ids:
            label = _event_label(label, end_result)
        marker = node["marker"]
        if node["type"] in ("start", "end") and not label and marker in _TRIGGER_MARKERS:
            marker = "none"  # a trigger icon on an event nobody named says nothing
        out_nodes.append(DiagramNode(id=node["id"], type=node["type"], label=label,
                                     lane=lanes[lane_index[resolved[node["id"]].casefold()]],
                                     step_index=node["step"], marker=marker))  # fmt: skip
    out_flows = [
        DiagramFlow(source=f["source"], target=f["target"], label=f["label"], is_default=f["is_default"]) for f in flows
    ]
    return GroundedDiagram(lanes=lanes, nodes=out_nodes, flows=out_flows, simplified=False)
