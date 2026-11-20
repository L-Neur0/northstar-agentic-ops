"""Unit tests for the map drawing of the PDF, `export/bpmn.py` (spec 20 §3.4).

Why: the map is drawn from stored data, and nothing in that data may break the PDF: `layout` must be
total on any graph (cycles, disconnected parts, dangling flows, bad lanes) and `build_drawing` must
always fit the box it is given and render. The fuzz test throws 300 seeded broken diagrams at it.
What: layout invariants (left to right, branches side by side in their lanes, never two nodes on one
spot, bad lanes clamped), drawing invariants (fits, renders, every marker, data objects and stores
from the diagram, extra height only where needed, label caps, loop channel, readable width).
Must not: read the profile; the diagram carries its data objects and stores.
Covers AC-20.40 to AC-20.42 (and the drawing side of AC-20.39).
"""

from __future__ import annotations

import random
import time
from typing import Any

from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Circle, PolyLine
from reportlab.pdfbase.pdfmetrics import stringWidth

from app.models.process_discovery_schemas import DIAGRAM_MARKERS_BY_TYPE, ProcessDiagram
from app.services.process_discovery.export.bpmn import (
    GATEWAY_COLUMN_WIDTH,
    MAX_TEXT_CHARS,
    _short_list,  # pyright: ignore[reportPrivateUsage]
    _text,  # pyright: ignore[reportPrivateUsage]
    _wrap,  # pyright: ignore[reportPrivateUsage]
    build_drawing,
    layout,
)
from app.services.process_discovery.export.branding import Brand
from tests.unit.process_discovery.export.cases import ORG, eu_assessment

BRAND = Brand.from_config(ORG)
MARKERS = sorted({m for ms in DIAGRAM_MARKERS_BY_TYPE.values() for m in ms})


def _walk(shape: Any, cls: type | None = None) -> list[Any]:
    found = []
    if cls is None and hasattr(shape, "text") or cls is not None and isinstance(shape, cls):
        found.append(shape)
    for child in getattr(shape, "contents", []) or []:
        found += _walk(child, cls)
    return found


def _texts(drawing: Any) -> list[str]:
    return [s.text for s in _walk(drawing)]


def _diagram(nodes: list[dict[str, Any]], flows: list[dict[str, Any]], lanes=("AP Specialist", "Buyer"), **extra):
    return {"lanes": list(lanes), "nodes": nodes, "flows": flows, **extra}


def _node(
    node_id: str, node_type: str = "task", lane: Any = 0, label: str = "", step: Any = None, marker: Any = "none"
):
    return {"id": node_id, "type": node_type, "label": label or node_id, "lane": lane, "step_index": step,
            "marker": marker}  # fmt: skip


def _flow(source: Any, target: Any, label: Any = "", is_default: Any = False):
    return {"source": source, "target": target, "label": label, "is_default": is_default}


def _draw(diagram: Any, width: float = 700, height: float = 400, name: str = "") -> Any:
    return build_drawing(diagram, width, height, BRAND, name)


def _renders(drawing: Any) -> bool:
    return renderPDF.drawToString(drawing)[:4] == b"%PDF"  # pyright: ignore[reportUnnecessaryComparison]


LINEAR = _diagram(
    [_node("s", "start"), _node("t1", step=1), _node("t2", lane=1, step=2), _node("e", "end", lane=1)],
    [_flow("s", "t1"), _flow("t1", "t2"), _flow("t2", "e")],
)
BRANCH = _diagram(
    [_node("s", "start"), _node("t1", step=1), _node("g", "gateway", label="OK?"),
     _node("t2", step=2), _node("t3", lane=1, step=3), _node("e", "end")],
    [_flow("s", "t1"), _flow("t1", "g"), _flow("g", "t2", "yes"), _flow("g", "t3", "no"),
     _flow("t2", "e"), _flow("t3", "e"), _flow("t3", "t1", "retry")],
)  # fmt: skip
WITH_DATA = {
    **LINEAR,
    "data_objects": [
        {"id": "do1i", "step_index": 1, "direction": "input", "label": "Invoice PDF"},
        {"id": "do1o", "step_index": 1, "direction": "output", "label": "Checked invoice"},
        {"id": "do2i", "step_index": 2, "direction": "input", "label": "Checked invoice"},
    ],
    "data_stores": [{"id": "ds1", "label": "SAP", "steps": [1, 2]}, {"id": "ds2", "label": "Excel", "steps": [1]}],
}


# --- layout (AC-20.42) ----------------------------------------------------------------------------


def test_ac_20_42_a_linear_flow_runs_left_to_right_in_its_lanes():
    positions = layout(LINEAR)
    columns = [positions[n]["column"] for n in ("s", "t1", "t2", "e")]
    assert columns == sorted(columns) and len(set(columns)) == 4
    assert positions["t2"]["lane"] == 1


def test_ac_20_42_branches_share_a_column_in_different_lanes():
    positions = layout(BRANCH)
    assert positions["t2"]["column"] == positions["t3"]["column"]
    assert positions["t2"]["lane"] != positions["t3"]["lane"]


def test_ac_20_42_two_nodes_never_share_a_spot():
    crowded = _diagram(
        [_node("s", "start"), _node("a"), _node("b"), _node("c"), _node("e", "end")],
        [_flow("s", "a"), _flow("s", "b"), _flow("s", "c"), _flow("a", "e"), _flow("b", "e"), _flow("c", "e")],
        lanes=("One",),
    )
    spots = [(p["column"], p["lane"]) for p in layout(crowded).values()]
    assert len(spots) == len(set(spots))


def test_ac_20_42_bad_lane_values_are_clamped_and_lane_names_are_read():
    diagram = _diagram([_node("a", lane=7), _node("b", lane=-1), _node("c", lane="x"), _node("d", lane=True)], [],
                       lanes=("Only",))  # fmt: skip
    assert all(p["lane"] == 0 for p in layout(diagram).values())
    named = _diagram([_node("a", lane="buyer"), _node("b", lane="AP Specialist")], [])
    assert (layout(named)["a"]["lane"], layout(named)["b"]["lane"]) == (1, 0)


def test_the_stored_model_of_the_eu_map_lays_out_and_draws():
    diagram = eu_assessment().diagram
    assert isinstance(diagram, ProcessDiagram)
    assert len(layout(diagram)) == len(diagram.nodes)
    drawing = _draw(diagram, 700, 400, "Monthly cost review")
    assert _renders(drawing) and "Monthly cost review" in _texts(drawing)
    assert any("site cost" in t for t in _texts(drawing))  # a data object from the diagram


# --- build_drawing (AC-20.40) ------------------------------------------------------------------------


def test_ac_20_40_linear_branching_and_looping_maps_fit_the_box_and_render():
    for diagram in (LINEAR, BRANCH):
        drawing = _draw(diagram)
        assert drawing.width <= 700.01 and drawing.height <= 400.01
        assert _renders(drawing)


def test_ac_20_40_a_big_map_is_scaled_down_to_fit():
    nodes = [_node("s", "start")] + [_node(f"t{i}", lane=i % 4, step=i) for i in range(1, 40)] + [_node("e", "end")]
    ids = [n["id"] for n in nodes]
    drawing = _draw(_diagram(nodes, [_flow(a, b) for a, b in zip(ids, ids[1:], strict=False)],
                             lanes=("A", "B", "C", "D")))  # fmt: skip
    assert drawing.width <= 700.01 and drawing.height <= 400.01 and _renders(drawing)


def test_ac_20_40_a_twelve_column_map_stays_narrow_enough_to_read():
    order = ["s", "t1", "t2", "m1", "t3", "g1", "t4", "m2", "t5", "g2", "t6", "e"]
    kinds = {"s": "start", "e": "end", "g1": "gateway", "g2": "gateway", "m1": "gateway", "m2": "gateway"}
    nodes = []
    for i, node_id in enumerate(order):
        node = _node(
            node_id, kinds.get(node_id, "task"), lane=i % 3, step=int(node_id[1]) if node_id[0] == "t" else None
        )
        if node_id[0] == "m":
            node["label"] = ""
        nodes.append(node)
    diagram = _diagram(nodes, [_flow(a, b) for a, b in zip(order, order[1:], strict=False)], lanes=("A", "B", "C"))
    natural_width = _draw(diagram, 9000, 9000).width / 1.25 / 0.999
    assert natural_width <= 1350
    assert _renders(_draw(diagram))


def test_ac_20_40_every_task_event_and_gateway_marker_draws():
    for marker in DIAGRAM_MARKERS_BY_TYPE["task"]:
        diagram = _diagram([_node("s", "start"), _node("t1", step=1, marker=marker), _node("e", "end")],
                           [_flow("s", "t1"), _flow("t1", "e")])  # fmt: skip
        assert _renders(_draw(diagram))
    for kind in ("start", "end"):
        for marker in DIAGRAM_MARKERS_BY_TYPE[kind]:
            nodes = [_node("s", "start"), _node("t1", step=1), _node("e", "end")]
            nodes[0 if kind == "start" else 2]["marker"] = marker
            assert _renders(_draw(_diagram(nodes, [_flow("s", "t1"), _flow("t1", "e")])))
    for marker in DIAGRAM_MARKERS_BY_TYPE["gateway"]:
        diagram = _diagram(
            [_node("s", "start"), _node("t1", step=1), _node("g", "gateway", label="OK?", marker=marker),
             _node("t2", step=2), _node("e", "end")],
            [_flow("s", "t1"), _flow("t1", "g"), _flow("g", "t2", "yes"), _flow("g", "t1", "no", is_default=True),
             _flow("t2", "e")],
        )  # fmt: skip
        assert _renders(_draw(diagram))


def test_ac_20_40_unknown_markers_fall_back_to_the_type_default():
    diagram = _diagram(
        [_node("s", "start", marker="not-a-marker"), _node("t1", step=1, marker=12345),
         _node("g", "gateway", marker=None), _node("e", "end", marker=["x"])],
        [_flow("s", "t1"), _flow("t1", "g"), _flow("g", "e")],
    )  # fmt: skip
    assert _renders(_draw(diagram))


def test_ac_20_40_data_objects_and_stores_are_drawn_from_the_diagram():
    texts = _texts(_draw(WITH_DATA, 900, 500))
    assert "Invoice PDF" in texts and "SAP; Excel" in texts and "SAP" in texts
    assert any("Checked" in t for t in texts)


def test_ac_20_40_data_rows_add_height_only_where_they_are_needed():
    plain = _draw(LINEAR, 700, 4000)
    with_data = _draw(WITH_DATA, 700, 4000)
    assert with_data.height > plain.height
    only_lane_0 = {**LINEAR, "data_objects": [{"step_index": 1, "direction": "input", "label": "x"}]}
    assert plain.height < _draw(only_lane_0, 700, 4000).height < with_data.height + 0.01


def test_the_pool_shows_the_process_name_only_when_given():
    assert "Invoice handling" in _texts(_draw(LINEAR, name="Invoice handling"))
    assert "Invoice handling" not in _texts(_draw(LINEAR))


def test_many_stores_on_one_step_are_capped_with_a_count():
    stores = [{"label": f"System {i}", "steps": [1]} for i in range(14)]
    drawing = _draw({**LINEAR, "data_stores": stores}, 2000, 600)
    assert any("+11" in t for t in _texts(drawing)) and _renders(drawing)


def test_two_ordinary_document_names_are_never_cut():
    diagram = {**LINEAR, "data_objects": [{"step_index": 1, "direction": "input", "label": "employment contract"},
                                          {"step_index": 1, "direction": "input", "label": "welcome pack"}]}  # fmt: skip
    assert not [t for t in _texts(_draw(diagram, 900, 500)) if t.endswith("…")]


def test_a_gateway_label_stays_inside_its_own_column():
    label = "Supplier disputes the correction?"
    diagram = _diagram(
        [_node("s", "start"), _node("t1", step=1), _node("g", "gateway", label=label), _node("t2", step=2),
         _node("e", "end")],
        [_flow("s", "t1"), _flow("t1", "g"), _flow("g", "t2", "no"), _flow("g", "t1", "yes"), _flow("t2", "e")],
    )  # fmt: skip
    lines = [t for t in _texts(_draw(diagram, 900, 500)) if len(t) > 3 and t in label]
    assert lines and all(stringWidth(t, "Helvetica", 7) <= GATEWAY_COLUMN_WIDTH / 2 - 6 + 0.5 for t in lines)


def test_a_loop_in_a_lower_lane_does_not_climb_through_the_lane_above():
    diagram = _diagram(
        [_node("s", "start"), _node("t1", lane=1, step=1), _node("g", "gateway", lane=1, label="OK?"),
         _node("e", "end", lane=1)],
        [_flow("s", "t1"), _flow("t1", "g"), _flow("g", "t1", "no"), _flow("g", "e", "yes")],
    )  # fmt: skip
    drawing = _draw(diagram, 900, 500)
    start_y = _walk(drawing, Circle)[0].cy
    loops = [p for p in _walk(drawing, PolyLine)
             if len(p.points) == 8 and p.points[0] == p.points[2] and p.points[3] == p.points[5]]  # fmt: skip
    assert loops and max(p.points[3] for p in loops) < start_y - 15


def test_special_characters_and_unicode_draw():
    diagram = _diagram(
        [_node("s", "start", label="A & B < C > D"), _node("t1", label="Prüfung — ✓ 发票 " * 5, step=1),
         _node("e", "end", label="\x00\x07 end")],
        [_flow("s", "t1", "<yes> & \"no\""), _flow("t1", "e")],
    )  # fmt: skip
    assert _renders(_draw(diagram))


def test_empty_or_malformed_diagrams_draw():
    for diagram in ({}, {"lanes": None, "nodes": None, "flows": None}, {"nodes": ["x", 3, None]}, None, "garbage",
                    {"data_objects": "x", "data_stores": [None, {"steps": "1"}]}):  # fmt: skip
        assert _renders(_draw(diagram))


def test_labels_are_capped_and_wrapping_is_fast():
    cut = _text("x" * 500)
    assert len(cut) == MAX_TEXT_CHARS and cut.endswith("…") and _text("short") == "short"
    assert len(_short_list(["y" * 70, "z" * 70, "w" * 70])) <= MAX_TEXT_CHARS
    started = time.perf_counter()
    lines = _wrap("a" * 3000, "Helvetica", 8, 60, 100_000)
    assert "".join(lines) == "a" * 3000 and time.perf_counter() - started < 2.0
    drawing = _draw(_diagram([_node("s", "start"), _node("t1", label="k" * 400), _node("e", "end")],
                             [_flow("s", "t1"), _flow("t1", "e")]), 400, 300)  # fmt: skip
    assert _renders(drawing) and all(len(t) <= MAX_TEXT_CHARS for t in _texts(drawing))


# --- fuzz (AC-20.41) ----------------------------------------------------------------------------------


def test_ac_20_41_three_hundred_broken_diagrams_always_fit_and_render():
    rng = random.Random(1234)
    labels = ["", "Check", "A & B", "<x>", "très long libellé " * 6, "✓", "发票", None, 42]
    for _ in range(300):
        ids = [rng.choice([f"n{i}", f"n{rng.randint(0, 5)}", "", None]) for i in range(rng.randint(0, 45))]
        lanes = rng.choice([[], ["A"], ["A", "B", "C"], ["x" * 200] * 3, None, "notalist"])
        nodes: list[Any] = [
            {"id": node_id, "type": rng.choice(["start", "task", "gateway", "end", "bogus", None]),
             "label": rng.choice(labels), "lane": rng.choice([0, 1, 2, 9, -3, "x", "A", "B", None, True]),
             "step_index": rng.choice([None, 1, 2, "3", -1]), "marker": rng.choice([*MARKERS, "bogus", None, 7, True])}
            for node_id in ids
        ] + rng.choice([[], ["garbage"], [None]])  # fmt: skip
        pool = [i for i in ids if i] + ["ghost"]
        flows = [
            {"source": rng.choice(pool), "target": rng.choice(pool), "label": rng.choice(labels),
             "is_default": rng.choice([True, False, "true", None, 1])}
            for _ in range(rng.randint(0, 60))
        ]  # fmt: skip
        data_objects = [
            rng.choice([None, "x", {"step_index": rng.choice([1, 2, 7, "1", None, -1]),
                                    "direction": rng.choice(["input", "output", "sideways", None]),
                                    "label": rng.choice([*labels, "a" * 300])}])
            for _ in range(rng.randint(0, 8))
        ]  # fmt: skip
        data_stores = rng.choice([None, "x", [{"label": rng.choice(labels), "steps": rng.choice([[1, 2], "1", None, [9]])}
                                              for _ in range(rng.randint(0, 5))]])  # fmt: skip
        width, height = rng.choice([(700, 400), (200, 100), (1000, 600)])
        diagram = {"lanes": lanes, "nodes": nodes, "flows": flows, "data_objects": data_objects,
                   "data_stores": data_stores}  # fmt: skip
        drawing = _draw(diagram, width, height, rng.choice(["", "P" * 300, "A & B"]))
        assert drawing.width <= width + 0.01 and drawing.height <= height + 0.01
        assert _renders(drawing)
