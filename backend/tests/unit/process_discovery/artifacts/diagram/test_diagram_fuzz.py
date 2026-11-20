"""Grounding fuzz: random broken MAP replies never break the map (spec 18 §3.8; AC-18.38).

Why: the one-rule-at-a-time tests cover the failures we thought of; a model can combine them in ways
nobody listed. Three hundred seeded random replies (random ids including duplicates and `None`, bogus
types, lanes in and out of range, string and bool step indexes, random markers, ghost flows and
self-loops, random lane lists and `is_default` values), half built from scratch and half damaged
copies of the good cost-review reply, must each give a valid map: every step drawn once with its real
name, known lanes, legal markers, everything reachable, at most 40 nodes, and the input untouched.
"""

from __future__ import annotations

import copy
import random
from typing import Any

import pytest

from app.models.process_discovery_schemas import DIAGRAM_MARKERS_BY_TYPE
from app.services.process_discovery.artifacts.diagram.grounding import OTHER_LANE, ground_diagram
from tests.fixtures.assessment.profiles import load_profile
from tests.fixtures.assessment.replies import map_reply

pytestmark = pytest.mark.slow

ALL_MARKERS = sorted({m for markers in DIAGRAM_MARKERS_BY_TYPE.values() for m in markers})
LABELS = ["", "Check", "A & B", "<x>", "très long libellé " * 6, "✓", "发票", None, 42]
ROLE_NAMES = ["Cost controller", "cost controller ", "Site controller", "Site manager", "CFO",
              "Head of Controlling", "Finance Bot", "x" * 200, None, 3]  # fmt: skip


def _random_reply(rng: random.Random) -> dict[str, Any]:
    node_count = rng.randint(0, 45)
    ids = [rng.choice([f"n{i}", f"n{rng.randint(0, 5)}", "", None, "start", "end"]) for i in range(node_count)]
    nodes: list[Any] = [
        {
            "id": node_id,
            "type": rng.choice(["start", "task", "task", "gateway", "end", "bogus", None]),
            "label": rng.choice(LABELS),
            "lane": rng.choice([0, 1, 2, 9, -3, "x", None, True]),
            "step_index": rng.choice([None, 1, 2, 3, 4, 5, 6, "3", -1, True, 2.0]),
            "marker": rng.choice([*ALL_MARKERS, "bogus-marker", None, 7, True]),
        }
        for node_id in ids
    ] + rng.choice([[], ["garbage"], [None]])
    pool = [i for i in ids if i] + ["ghost"]
    flows = [
        {
            "source": rng.choice(pool),
            "target": rng.choice(pool),
            "label": rng.choice(LABELS),
            "is_default": rng.choice([True, False, "true", None, 1]),
        }  # fmt: skip
        for _ in range(rng.randint(0, 60))
    ]
    lanes = rng.choice([[], rng.sample(ROLE_NAMES, k=rng.randint(1, len(ROLE_NAMES))), None, "notalist"])
    return {"lanes": lanes, "nodes": nodes, "flows": flows}


def _damaged_reply(rng: random.Random) -> dict[str, Any]:
    reply = map_reply()
    for _ in range(rng.randint(1, 4)):
        target = rng.choice(["node", "flow", "lane", "add_flow", "drop"])
        if target == "node" and reply["nodes"]:
            node = rng.choice(reply["nodes"])
            key = rng.choice(["id", "type", "lane", "step_index", "marker", "label"])
            node[key] = rng.choice([None, "t1", 7, True, "gateway", "user", "3", -1, *ALL_MARKERS])
        elif target == "flow" and reply["flows"]:
            flow = rng.choice(reply["flows"])
            flow[rng.choice(["source", "target", "label", "is_default"])] = rng.choice(
                ["t1", "t3", "g1", "end", "start", "ghost", "", None, True, "true"]
            )
        elif target == "lane":
            reply["lanes"] = rng.choice([[], ["Finance Bot"], ROLE_NAMES, None])
        elif target == "add_flow":
            ids = [n["id"] for n in reply["nodes"]] + ["ghost"]
            reply["flows"].append({"source": rng.choice(ids), "target": rng.choice(ids), "label": "",
                                   "is_default": rng.choice([True, False])})  # fmt: skip
        elif reply["flows"]:
            reply["flows"].pop(rng.randrange(len(reply["flows"])))
    return reply


def _reachable(roots: set[str], edges: list[tuple[str, str]]) -> set[str]:
    seen, stack = set(roots), list(roots)
    while stack:
        node = stack.pop()
        for a, b in edges:
            if a == node and b not in seen:
                seen.add(b)
                stack.append(b)
    return seen


def test_random_replies_always_ground_into_a_valid_map():
    """AC-18.38."""
    profile = load_profile("eu")
    steps = profile["process"]["substeps"]
    known = {s["owner"] for s in steps} | {r["role"] for s in steps for r in s["roles"] if "role" in r}
    known |= {profile["process"]["process_owner"]["role"], OTHER_LANE}
    rng = random.Random(1234)
    kept = 0
    for case in range(300):
        reply = _random_reply(rng) if case % 2 else _damaged_reply(rng)
        before = copy.deepcopy(reply)
        diagram = ground_diagram(reply, profile)
        assert reply == before, f"case {case}: input mutated"
        assert diagram is not None
        assert diagram.fallback_rule != "G24", f"case {case}: grounding raised internally"
        kept += not diagram.simplified

        tasks = [n for n in diagram.nodes if n.type == "task"]
        assert sorted(t.step_index for t in tasks if t.step_index is not None) == [1, 2, 3, 4, 5], f"case {case}"
        assert len(tasks) == 5
        for task in tasks:
            assert task.step_index is not None and task.label == steps[task.step_index - 1]["name"]
        assert set(diagram.lanes) <= known and len(diagram.lanes) <= 9, f"case {case}: {diagram.lanes}"
        assert all(n.lane in diagram.lanes for n in diagram.nodes)
        for node in diagram.nodes:
            assert node.marker in DIAGRAM_MARKERS_BY_TYPE[node.type], f"case {case}: {node}"
        assert len(diagram.nodes) <= 40
        ids = {n.id for n in diagram.nodes}
        assert len(ids) == len(diagram.nodes)
        edges = [(f.source, f.target) for f in diagram.flows]
        assert all(a in ids and b in ids for a, b in edges)
        starts = [n.id for n in diagram.nodes if n.type == "start"]
        ends = {n.id for n in diagram.nodes if n.type == "end"}
        assert len(starts) == 1 and ends
        assert _reachable({starts[0]}, edges) == ids, f"case {case}: unreachable node"
        assert _reachable(ends, [(b, a) for a, b in edges]) == ids, f"case {case}: node cannot reach an end"
    assert kept > 0  # some damaged replies must survive grounding, or the fuzz only tests the fallback
