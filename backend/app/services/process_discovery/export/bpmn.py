"""The process map drawn as a reportlab picture for the PDF: pool, lanes, BPMN shapes, data objects and stores (spec 20 §3.4).

Why: the report's map must always draw, whatever is stored: the diagram is grounded before it is
saved (spec 18), but a stored document can still be old, damaged or edited, and nothing in it may
make the PDF fail. So this module trusts nothing: it normalises ids, types, lanes (a lane is a role
name, or an index; anything else is lane 0), step numbers, markers and flows before drawing.
What: `layout` (node id → column, lane, type: columns by `domain.node_order.rank_nodes`, two nodes
of the same rank and lane side by side, never on one spot) and `build_drawing` (one pool with the
process name read vertically and one lane per role; start thin circle, end thick circle, trigger
icons; tasks as rounded boxes "Step n" with task-type icons; gateway diamonds with ×, +, ○ or a
pentagon; orthogonal arrows with labels, back edges as loops through a channel above the higher
lane, default flows with a slash; data objects (inputs left, outputs right) and data stores under
the tasks with dotted associations, from `diagram.data_objects` and `diagram.data_stores`). Drawn
at natural size, then scaled to fit the box, never above 1.25×.
Must not: import `artifacts/`, read the profile (the diagram carries its data objects and stores),
or hard-code a colour (they come from the `Brand`). Known limit: past about 12 steps a map is hard
to read on one page; the product caps steps at 6.
Spec 20 §3.4 (Map drawing); AC-20.39 to AC-20.42.
"""

from __future__ import annotations

# The reportlab stubs type shape keyword arguments (colours, widths) too narrowly for real calls.
# pyright: reportArgumentType=false
import math
import unicodedata
from collections.abc import Mapping
from typing import Any

from reportlab.graphics.shapes import (
    Circle,
    Drawing,
    Ellipse,
    Group,
    Line,
    Polygon,
    PolyLine,
    Rect,
    String,
)
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth

from app.models.process_discovery_schemas import DIAGRAM_MARKERS_BY_TYPE

from ..domain.node_order import rank_nodes
from .branding import BORDER, CARD, MUTED, PAGE, TEXT, Brand

NODE_TYPES = ("start", "task", "gateway", "end")

#: The gateway type drawn when a stored `marker` is missing or not one of the
#: four gateway types — never trust stored data, the same defensive stance
#: `_normalize` already takes on every other field.
_DEFAULT_MARKER_FOR_TYPE = {"gateway": "exclusive"}


def _valid_marker(node_type: str, marker: Any) -> str:
    allowed = DIAGRAM_MARKERS_BY_TYPE.get(node_type, [])
    if isinstance(marker, str) and marker in allowed:
        return marker
    return _DEFAULT_MARKER_FOR_TYPE.get(node_type, "none")


# Natural-size geometry, in points (the whole drawing is scaled afterwards).
#: The pool's label band (process name, vertical) and each lane's (role name,
#: vertical), side by side on the left.
POOL_LABEL_WIDTH = 24
LANE_LABEL_WIDTH = 26
LABEL_BANDS_WIDTH = POOL_LABEL_WIDTH + LANE_LABEL_WIDTH
#: Extra lane height, only in lanes whose tasks have data or systems, for the row
#: under the tasks: inputs left of the task's centre, its systems under the
#: centre, outputs right. Room for icons and a 4-line label.
DATA_ROW_HEIGHT = 62
DATA_OBJECT_W, DATA_OBJECT_H = 14, 18
DATA_OBJECT_OFFSET = 44
DATA_LABEL_W = 42
DATA_LABEL_LINES = 4
DATA_STORE_W, DATA_STORE_H = 26, 22
#: A column holding a task needs the box plus arrow room; a column of only
#: events/gateways is much narrower — sizing columns by content keeps wide
#: processes from being scaled down (and their text shrunk) needlessly.
COLUMN_WIDTH = 132
GATEWAY_COLUMN_WIDTH = 100  # room for the question label at the diamond's upper left
MERGE_COLUMN_WIDTH = 64  # a gateway with no question to print
NARROW_COLUMN_WIDTH = 76
LANE_HEIGHT = 120
TASK_WIDTH, TASK_HEIGHT = 108, 60
TASK_FONT_SIZE = 9
GATEWAY_HALF = 22
EVENT_RADIUS = 15
LOOP_CHANNEL_GAP = 9
#: Never blow a tiny diagram up past this — text would look oversized.
MAX_SCALE = 1.25

#: Longest single label the drawing will take. Labels come from the model and
#: from free-text answers; anything past this is unreadable in a node
#: anyway and only costs layout time, so it is cut here with an ellipsis.
MAX_TEXT_CHARS = 80
_ELLIPSIS = "…"


def _clip(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    """`text` cut to at most `limit` characters, ending in an ellipsis when
    anything was dropped."""
    if len(text) <= limit:
        return text
    return text[: max(limit - len(_ELLIPSIS), 0)] + _ELLIPSIS


def _text(value: Any) -> str:
    """Printable single-line text in the standard fonts' encoding: control
    characters dropped, anything the built-in Helvetica cannot encode → "?",
    and never longer than `MAX_TEXT_CHARS`."""
    if not isinstance(value, str):
        return ""
    text = "".join(" " if unicodedata.category(ch).startswith("C") else ch for ch in value)
    text = " ".join(text.split())
    text = text.encode("cp1252", errors="replace").decode("cp1252")
    return _clip(text)


def _get(raw: Mapping[str, Any], key: str) -> Any:
    """A stored field by its snake_case name or its camelCase alias."""
    if key in raw:
        return raw[key]
    head, *rest = key.split("_")
    return raw.get(head + "".join(w.capitalize() for w in rest))


def _source(diagram: Any) -> Mapping[str, Any]:
    if hasattr(diagram, "model_dump"):
        try:
            diagram = diagram.model_dump(warnings=False)
        except Exception:
            return {}
    return diagram if isinstance(diagram, Mapping) else {}  # pyright: ignore[reportUnknownVariableType]


def _lane_index(value: Any, lanes: list[str]) -> int:
    """A lane given as a role name (stored maps) or an index (older maps); anything else is lane 0."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value if 0 <= value < len(lanes) else 0
    if isinstance(value, str):
        wanted = _text(value).casefold()
        return next((i for i, name in enumerate(lanes) if name.casefold() == wanted), 0)
    return 0


def _normalize(diagram: Any) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Lanes, nodes and flows cleaned into shapes the drawing can always handle."""
    source = _source(diagram)
    raw_lanes = source.get("lanes") if isinstance(source.get("lanes"), list) else []
    lanes = [_text(name) for name in raw_lanes or []] or [""]

    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    raw_nodes = source.get("nodes") if isinstance(source.get("nodes"), list) else []
    for raw in raw_nodes or []:
        if not isinstance(raw, Mapping):
            continue
        node_id = _text(raw.get("id"))
        node_type = raw.get("type")
        if not node_id or node_id in seen or node_type not in NODE_TYPES:
            continue
        lane = _lane_index(raw.get("lane"), lanes)
        step = _get(raw, "step_index")
        step = step if isinstance(step, int) and not isinstance(step, bool) and step >= 1 else None
        marker = _valid_marker(node_type, raw.get("marker"))
        seen.add(node_id)
        nodes.append({"id": node_id, "type": node_type, "label": _text(raw.get("label")), "lane": lane,
                      "step": step, "marker": marker})  # fmt: skip

    flows: list[dict[str, Any]] = []
    by_id = {n["id"]: n for n in nodes}
    default_claimed: set[str] = set()
    raw_flows = source.get("flows") if isinstance(source.get("flows"), list) else []
    for raw in raw_flows or []:
        if not isinstance(raw, Mapping):
            continue
        a, b = _text(raw.get("source")), _text(raw.get("target"))
        if a not in seen or b not in seen or a == b:
            continue
        is_default = _get(raw, "is_default") is True and by_id[a]["type"] == "gateway" and a not in default_claimed
        if is_default:
            default_claimed.add(a)
        flows.append({"source": a, "target": b, "label": _text(raw.get("label")), "is_default": is_default})
    return lanes, nodes, flows


def _layout(nodes: list[dict[str, Any]], flows: list[dict[str, Any]]):
    ranks, back = rank_nodes([n["id"] for n in nodes], [(f["source"], f["target"]) for f in flows])
    by_rank: dict[int, list[dict[str, Any]]] = {}
    for node in nodes:
        by_rank.setdefault(ranks[node["id"]], []).append(node)

    positions: dict[str, dict[str, Any]] = {}
    column = 0
    for rank in sorted(by_rank):
        offsets: dict[int, int] = {}
        for node in by_rank[rank]:
            offset = offsets.get(node["lane"], 0)
            offsets[node["lane"]] = offset + 1
            positions[node["id"]] = {"column": column + offset, "lane": node["lane"], "type": node["type"]}
        column += max(offsets.values())
    return positions, back, column


def layout(diagram: Any) -> dict[str, dict[str, Any]]:
    """node id → `{"column", "lane", "type"}`: columns left to right by rank,
    two nodes of the same rank and lane side by side, never on the same spot."""
    _, nodes, flows = _normalize(diagram)
    positions, _, _ = _layout(nodes, flows)
    return positions


def _wrap(text: str, font: str, size: float, width: float, max_lines: int) -> list[str]:
    """`text` wrapped to `width`, hard-cutting words that are wider than a line,
    at most `max_lines` lines (the last one ellipsized if text was left over)."""

    def widest_prefix(line: str) -> int:
        """Length of the longest prefix of `line` that fits `width` (at least 1
        character, so progress is always made). Binary search: `stringWidth`
        is monotonic in the prefix length, and a decrementing scan would be
        quadratic in a long space-free label."""
        lo, hi = 1, len(line)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if stringWidth(line[:mid], font, size) <= width:
                lo = mid
            else:
                hi = mid - 1
        return lo

    lines: list[str] = []
    for line in simpleSplit(text, font, size, width):
        while stringWidth(line, font, size) > width and len(line) > 1:
            cut = widest_prefix(line)
            lines.append(line[:cut])
            line = line[cut:]
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and stringWidth(last + "…", font, size) > width:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


def _text_block(
    group, lines: list[str], x: float, top: float, font: str, size: float, color, anchor: str = "middle"
) -> None:

    for i, line in enumerate(lines):
        group.add(
            String(
                x, top - (i + 1) * (size + 1.5), line, fontName=font, fontSize=size, fillColor=color, textAnchor=anchor
            )
        )


def _half_extent(node_type: str) -> tuple[float, float]:
    if node_type == "task":
        return TASK_WIDTH / 2, TASK_HEIGHT / 2
    if node_type == "gateway":
        return GATEWAY_HALF, GATEWAY_HALF
    return EVENT_RADIUS, EVENT_RADIUS


def _arrow(
    group, points: list[float], color, label: str, label_at: tuple[float, float], is_default: bool = False
) -> None:

    group.add(PolyLine(points, strokeColor=color, strokeWidth=1))
    (x1, y1), (x2, y2) = (points[-4], points[-3]), (points[-2], points[-1])
    dx, dy = x2 - x1, y2 - y1
    length = max((dx * dx + dy * dy) ** 0.5, 0.001)
    ux, uy = dx / length, dy / length
    size = 6
    group.add(
        Polygon(
            [
                x2,
                y2,
                x2 - size * ux - size / 2 * uy,
                y2 - size * uy + size / 2 * ux,
                x2 - size * ux + size / 2 * uy,
                y2 - size * uy - size / 2 * ux,
            ],
            fillColor=color,
            strokeColor=color,
            strokeWidth=0.5,
        )
    )
    if is_default:
        # BPMN's default-flow mark: a short diagonal tick across the line,
        # close to where it leaves the gateway (the segment's own start).
        fx1, fy1, fx2, fy2 = points[0], points[1], points[2], points[3]
        fdx, fdy = fx2 - fx1, fy2 - fy1
        flen = max((fdx * fdx + fdy * fdy) ** 0.5, 0.001)
        fux, fuy = fdx / flen, fdy / flen
        along = min(10, flen / 2)
        tx, ty = fx1 + fux * along, fy1 + fuy * along
        px, py = -fuy * 5, fux * 5
        group.add(Line(tx - px, ty - py, tx + px, ty + py, strokeColor=color, strokeWidth=1.3))
    if label:
        group.add(String(label_at[0], label_at[1], label[:24], fontName="Helvetica", fontSize=7, fillColor=color))


def _icon_envelope(group, cx: float, cy: float, width: float, color, bg, filled: bool) -> None:
    """A small message envelope: outline (unfilled = catching/receiving) or
    solid (filled = throwing/sending), with the classic folded-flap seam."""

    height = width * 0.66
    x0, y0 = cx - width / 2, cy - height / 2
    group.add(Rect(x0, y0, width, height, fillColor=(color if filled else None), strokeColor=color, strokeWidth=0.9))
    seam_color = bg if filled else color
    group.add(
        PolyLine(
            [x0, y0 + height, cx, y0 + height * 0.35, x0 + width, y0 + height], strokeColor=seam_color, strokeWidth=0.8
        )
    )


def _draw_task_marker(group, x: float, y: float, marker: str, color) -> None:
    """A small icon at a task's top-left corner naming its BPMN task type.
    Simplified glyphs drawn from primitive shapes only — no icon font."""

    s = 11
    if marker == "none":
        return
    if marker == "user":
        group.add(Circle(x, y + s * 0.22, s * 0.2, fillColor=color, strokeColor=None))
        group.add(
            Polygon(
                [
                    x - s * 0.38,
                    y - s * 0.32,
                    x + s * 0.38,
                    y - s * 0.32,
                    x + s * 0.24,
                    y - s * 0.02,
                    x - s * 0.24,
                    y - s * 0.02,
                ],
                fillColor=color,
                strokeColor=None,
            )
        )
    elif marker == "manual":
        group.add(
            Rect(
                x - s * 0.28,
                y - s * 0.32,
                s * 0.56,
                s * 0.4,
                rx=2,
                ry=2,
                fillColor=None,
                strokeColor=color,
                strokeWidth=0.9,
            )
        )
        for dx in (-0.16, 0, 0.16):
            group.add(Line(x + dx * s, y + s * 0.08, x + dx * s, y + s * 0.34, strokeColor=color, strokeWidth=0.9))
    elif marker == "service":
        r = s * 0.26
        group.add(Circle(x, y, r, fillColor=None, strokeColor=color, strokeWidth=1.0))
        for k in range(6):
            angle = math.pi / 3 * k
            tx, ty = x + math.cos(angle) * r * 1.6, y + math.sin(angle) * r * 1.6
            group.add(Rect(tx - 1.1, ty - 1.1, 2.2, 2.2, fillColor=color, strokeColor=None))
    elif marker in ("send", "receive"):
        _icon_envelope(group, x, y, s * 0.9, color, CARD, filled=(marker == "send"))
    elif marker == "script":
        group.add(
            Rect(x - s * 0.28, y - s * 0.34, s * 0.56, s * 0.68, fillColor=None, strokeColor=color, strokeWidth=0.9)
        )
        group.add(
            PolyLine(
                [x - s * 0.16, y + s * 0.1, x, y - s * 0.02, x - s * 0.16, y - s * 0.14, x + s * 0.05, y - s * 0.24],
                strokeColor=color,
                strokeWidth=0.8,
            )
        )
    elif marker == "business_rule":
        group.add(
            Rect(x - s * 0.3, y - s * 0.32, s * 0.6, s * 0.64, fillColor=None, strokeColor=color, strokeWidth=0.9)
        )
        group.add(Line(x - s * 0.3, y, x + s * 0.3, y, strokeColor=color, strokeWidth=0.7))
        group.add(Line(x, y - s * 0.32, x, y + s * 0.32, strokeColor=color, strokeWidth=0.7))


def _draw_event_marker(group, x: float, y: float, marker: str, color, bg, is_end: bool) -> None:
    """A small trigger icon inside a start/end event circle. Message and
    signal are unfilled (catching) at the start, filled (throwing) at the end
    — `error`/`terminate` only ever appear at the end, per `DIAGRAM_MARKERS_BY_TYPE`."""

    if marker == "none":
        return
    if marker == "message":
        _icon_envelope(group, x, y, 15, color, bg, filled=is_end)
    elif marker == "timer":
        r = 9
        group.add(Circle(x, y, r, fillColor=None, strokeColor=color, strokeWidth=0.9))
        group.add(Line(x, y, x, y + r * 0.6, strokeColor=color, strokeWidth=1.0))
        group.add(Line(x, y, x + r * 0.5, y, strokeColor=color, strokeWidth=1.0))
    elif marker == "conditional":
        w, h = 12, 15
        group.add(Rect(x - w / 2, y - h / 2, w, h, fillColor=None, strokeColor=color, strokeWidth=0.8))
        for dy in (0.28, 0, -0.28):
            group.add(Line(x - w / 2 + 2, y + dy * h, x + w / 2 - 2, y + dy * h, strokeColor=color, strokeWidth=0.7))
    elif marker == "signal":
        r = 9
        group.add(
            Polygon(
                [x, y + r * 0.65, x + r * 0.6, y - r * 0.45, x - r * 0.6, y - r * 0.45],
                fillColor=(color if is_end else None),
                strokeColor=color,
                strokeWidth=1.0,
            )
        )
    elif marker == "terminate":
        group.add(Circle(x, y, 7, fillColor=color, strokeColor=color))
    elif marker == "error":
        group.add(
            Polygon(
                [x - 6, y - 8, x - 1, y + 1, x + 3, y - 3, x + 6, y + 8, x + 1, y - 1, x - 3, y + 3],
                fillColor=None,
                strokeColor=color,
                strokeWidth=1.1,
            )
        )


def _draw_gateway_marker(group, x: float, y: float, marker: str, color) -> None:
    """The inner glyph naming a gateway's BPMN type. Missing/invalid markers
    never reach here — `_normalize`/`_valid_marker` always resolve a gateway
    to one of these four first."""

    if marker == "parallel":
        group.add(Line(x - 7, y, x + 7, y, strokeColor=color, strokeWidth=2))
        group.add(Line(x, y - 7, x, y + 7, strokeColor=color, strokeWidth=2))
    elif marker == "inclusive":
        group.add(Circle(x, y, 7, fillColor=None, strokeColor=color, strokeWidth=2))
    elif marker == "event_based":
        pts = []
        for k in range(5):
            angle = math.pi / 2 + 2 * math.pi * k / 5
            pts += [x + math.cos(angle) * 6, y + math.sin(angle) * 6]
        group.add(Polygon(pts, fillColor=None, strokeColor=color, strokeWidth=1.0))
    else:  # exclusive (the default gateway type)
        group.add(Line(x - 7, y - 7, x + 7, y + 7, strokeColor=color, strokeWidth=2))
        group.add(Line(x - 7, y + 7, x + 7, y - 7, strokeColor=color, strokeWidth=2))


def _short_list(values: Any, limit: int = 3) -> str:
    """`values` (a list of strings) as one short label: cleaned, deduplicated,
    at most `limit` items (then "+N")."""
    if not isinstance(values, list):
        return ""
    items = list(dict.fromkeys(t for t in (_text(v) for v in values) if t))
    text = "; ".join(items[:limit])
    return _clip(text + (f" +{len(items) - limit}" if len(items) > limit else ""))


def _step_artifacts(diagram: Any) -> dict[int, dict[str, Any]]:
    """Per step number: the data it reads (`inputs`), writes (`outputs`) and the stores it uses, read from the
    diagram's data objects and data stores (spec 18: made by code from the profile, never by the model)."""
    source = _source(diagram)
    found: dict[int, dict[str, list[Any]]] = {}

    def slot(step: Any) -> dict[str, list[Any]] | None:
        if not isinstance(step, int) or isinstance(step, bool) or step < 1:
            return None
        return found.setdefault(step, {"inputs": [], "outputs": [], "systems": []})

    objects = source.get("data_objects", source.get("dataObjects"))
    for raw in objects if isinstance(objects, list) else []:
        if isinstance(raw, Mapping):
            bucket = slot(_get(raw, "step_index"))
            direction = raw.get("direction")
            if bucket is not None and direction in ("input", "output"):
                bucket["inputs" if direction == "input" else "outputs"].append(raw.get("label"))
    stores = source.get("data_stores", source.get("dataStores"))
    for raw in stores if isinstance(stores, list) else []:
        if isinstance(raw, Mapping):
            steps = raw.get("steps")
            for step in steps if isinstance(steps, list) else []:
                bucket = slot(step)
                if bucket is not None:
                    bucket["systems"].append(raw.get("label"))
    return {step: {k: _short_list(v) for k, v in data.items()} for step, data in found.items()}


def _dotted(group, points: list[float], color) -> None:

    group.add(PolyLine(points, strokeColor=color, strokeWidth=0.8, strokeDashArray=[2, 2]))


def _open_arrowhead(group, x1: float, y1: float, x2: float, y2: float, color) -> None:
    """BPMN's data-association head: two short strokes, not a filled triangle."""

    dx, dy = x2 - x1, y2 - y1
    length = max((dx * dx + dy * dy) ** 0.5, 0.001)
    ux, uy = dx / length, dy / length
    size = 4.5
    group.add(
        PolyLine(
            [
                x2 - size * ux - size / 2 * uy,
                y2 - size * uy + size / 2 * ux,
                x2,
                y2,
                x2 - size * ux + size / 2 * uy,
                y2 - size * uy - size / 2 * ux,
            ],
            strokeColor=color,
            strokeWidth=0.8,
        )
    )


def _draw_data_object(group: Group, cx: float, top: float, label: str) -> None:
    """A BPMN data object: a page with a folded corner, its label underneath."""

    x0 = cx - DATA_OBJECT_W / 2
    y0 = top - DATA_OBJECT_H
    fold = 5
    group.add(
        Polygon(
            [x0, y0, x0, top, x0 + DATA_OBJECT_W - fold, top, x0 + DATA_OBJECT_W, top - fold, x0 + DATA_OBJECT_W, y0],
            fillColor=CARD,
            strokeColor=MUTED,
            strokeWidth=0.9,
        )
    )
    group.add(
        PolyLine(
            [x0 + DATA_OBJECT_W - fold, top, x0 + DATA_OBJECT_W - fold, top - fold, x0 + DATA_OBJECT_W, top - fold],
            strokeColor=MUTED,
            strokeWidth=0.7,
        )
    )
    _text_block(group, _wrap(label, "Helvetica", 6, DATA_LABEL_W, DATA_LABEL_LINES), cx, y0 - 1, "Helvetica", 6, MUTED)


def _draw_data_store(group: Group, cx: float, top: float, label: str) -> None:
    """A BPMN data store: a cylinder, its label underneath."""

    rx, ry = DATA_STORE_W / 2, 4
    bottom = top - DATA_STORE_H
    stroke = MUTED
    group.add(Ellipse(cx, bottom + ry, rx, ry, fillColor=CARD, strokeColor=stroke, strokeWidth=0.9))
    group.add(Rect(cx - rx, bottom + ry, DATA_STORE_W, DATA_STORE_H - 2 * ry, fillColor=CARD, strokeColor=None))
    group.add(Line(cx - rx, bottom + ry, cx - rx, top - ry, strokeColor=stroke, strokeWidth=0.9))
    group.add(Line(cx + rx, bottom + ry, cx + rx, top - ry, strokeColor=stroke, strokeWidth=0.9))
    group.add(Ellipse(cx, top - ry, rx, ry, fillColor=CARD, strokeColor=stroke, strokeWidth=0.9))
    _text_block(
        group, _wrap(label, "Helvetica", 6, DATA_LABEL_W, DATA_LABEL_LINES), cx, bottom - 1, "Helvetica", 6, MUTED
    )


def _vertical_text(group, lines: list[str], cx: float, cy: float, font: str, size: float, color) -> None:
    """`lines` read bottom-to-top, the block centred on (cx, cy)."""

    rotated = Group(transform=(0, 1, -1, 0, cx, cy))
    lead = size + 1.5
    for k, line in enumerate(lines):
        rotated.add(
            String(
                0,
                ((len(lines) - 1) / 2 - k) * lead - size * 0.3,
                line,
                fontName=font,
                fontSize=size,
                fillColor=color,
                textAnchor="middle",
            )
        )
    group.add(rotated)


def build_drawing(diagram: Any, width: float, height: float, brand: Brand, process_name: str = "") -> Drawing:
    """The diagram as a reportlab `Drawing` no larger than `width` × `height`.

    `process_name` is read vertically on the pool; the data objects and stores come from the diagram.
    """
    lanes, nodes, flows = _normalize(diagram)
    positions, back, column_count = _layout(nodes, flows)
    lane_count = len(lanes)
    back_list = sorted(back)

    # What each task reads, writes and uses: data in/out, data stores.
    step_data = _step_artifacts(diagram)
    node_data: dict[str, dict[str, Any]] = {
        n["id"]: step_data[n["step"]] for n in nodes if n["type"] == "task" and n["step"] in step_data
    }
    lane_has_data = [
        any(
            any((node_data.get(n["id"]) or {}).get(k) for k in ("inputs", "outputs", "systems"))
            for n in nodes
            if n["lane"] == i
        )
        for i in range(lane_count)
    ]

    # A loop runs in the headroom above the nodes of the higher of its two lanes,
    # one channel per loop, so it only crosses the lanes it has to.
    loop_slot: dict[tuple[str, str], tuple[int, int]] = {}
    loops_in_lane = [0] * lane_count
    for edge in back_list:
        lane = min(positions[edge[0]]["lane"], positions[edge[1]]["lane"])
        loop_slot[edge] = (lane, loops_in_lane[lane])
        loops_in_lane[lane] += 1
    lane_heights = [
        LANE_HEIGHT + (DATA_ROW_HEIGHT if has else 0) + LOOP_CHANNEL_GAP * loops_in_lane[i]
        for i, has in enumerate(lane_has_data)
    ]

    widths = [NARROW_COLUMN_WIDTH] * max(column_count, 1)
    for n in nodes:
        wanted = {"task": COLUMN_WIDTH, "gateway": GATEWAY_COLUMN_WIDTH if n["label"] else MERGE_COLUMN_WIDTH}.get(
            n["type"], NARROW_COLUMN_WIDTH
        )
        column = positions[n["id"]]["column"]
        widths[column] = max(widths[column], wanted)
    left_edges = [LABEL_BANDS_WIDTH + sum(widths[:i]) for i in range(len(widths))]
    natural_width = LABEL_BANDS_WIDTH + sum(widths)
    lanes_height = natural_height = sum(lane_heights)
    lane_bottoms = [sum(lane_heights[i + 1 :]) for i in range(lane_count)]

    def centre(node_id: str) -> tuple[float, float]:
        p = positions[node_id]
        x = left_edges[p["column"]] + widths[p["column"]] / 2
        y = lane_bottoms[p["lane"]] + (DATA_ROW_HEIGHT if lane_has_data[p["lane"]] else 0) + LANE_HEIGHT / 2
        return x, y

    def column_width(node_id: str) -> float:
        return widths[positions[node_id]["column"]]

    group = Group()

    # Pool: a band with the process name, then a band per lane with its role.
    group.add(Rect(0, 0, natural_width, lanes_height, fillColor=None, strokeColor=BORDER, strokeWidth=1.2))
    group.add(Rect(0, 0, POOL_LABEL_WIDTH, lanes_height, fillColor=CARD, strokeColor=BORDER, strokeWidth=0.8))
    pool_lines = _wrap(_text(process_name), "Helvetica-Bold", 8, lanes_height - 14, 2)
    if pool_lines:
        _vertical_text(group, pool_lines, POOL_LABEL_WIDTH / 2, lanes_height / 2, "Helvetica-Bold", 8, TEXT)
    for i, name in enumerate(lanes):
        y = lane_bottoms[i]
        group.add(
            Rect(
                POOL_LABEL_WIDTH,
                y,
                natural_width - POOL_LABEL_WIDTH,
                lane_heights[i],
                fillColor=None,
                strokeColor=BORDER,
                strokeWidth=0.8,
            )
        )
        group.add(
            Rect(
                POOL_LABEL_WIDTH,
                y,
                LANE_LABEL_WIDTH,
                lane_heights[i],
                fillColor=CARD,
                strokeColor=BORDER,
                strokeWidth=0.8,
            )
        )
        lines = _wrap(name, "Helvetica-Bold", 8, lane_heights[i] - 12, 2)
        if lines:
            _vertical_text(
                group,
                lines,
                POOL_LABEL_WIDTH + LANE_LABEL_WIDTH / 2,
                y + lane_heights[i] / 2,
                "Helvetica-Bold",
                8,
                brand.primary,
            )

    # Flows under the nodes.
    for f in flows:
        a, b, label, is_default = f["source"], f["target"], f["label"], f["is_default"]
        (xa, ya), (xb, yb) = centre(a), centre(b)
        (hwa, hha), (hwb, hhb) = _half_extent(positions[a]["type"]), _half_extent(positions[b]["type"])
        if (a, b) in back:
            lane, slot = loop_slot[(a, b)]
            channel = lane_bottoms[lane] + lane_heights[lane] - LOOP_CHANNEL_GAP * (slot + 1)
            points = [xa, ya + hha, xa, channel, xb, channel, xb, yb + hhb]
            _arrow(group, points, MUTED, label, (xa + 4, channel + 2), is_default)
        elif positions[a]["type"] == "gateway" and abs(ya - yb) > 0.5:
            start_y = ya + hha if yb > ya else ya - hha
            points = [xa, start_y, xa, yb, xb - hwb, yb]
            _arrow(group, points, MUTED, label, (xa + 4, (start_y + yb) / 2), is_default)
        elif abs(ya - yb) <= 0.5:
            points = [xa + hwa, ya, xb - hwb, yb]
            _arrow(group, points, MUTED, label, (xa + hwa + 4, ya + 4), is_default)
        else:
            gap = (xb - hwb) - (xa + hwa)
            jog = xb - hwb - min(18, max(gap, 0) / 2)
            points = [xa + hwa, ya, jog, ya, jog, yb, xb - hwb, yb]
            _arrow(group, points, MUTED, label, (xa + hwa + 4, ya + 4), is_default)

    # Data objects: inputs under the task's left half, outputs under its right.
    for node in nodes:
        data = node_data.get(node["id"])
        if not data:
            continue
        x, y = centre(node["id"])
        task_bottom = y - TASK_HEIGHT / 2
        icon_top = lane_bottoms[node["lane"]] + DATA_ROW_HEIGHT - 4
        if data["inputs"]:
            ox = x - DATA_OBJECT_OFFSET
            _draw_data_object(group, ox, icon_top, data["inputs"])
            _dotted(group, [ox, icon_top, ox, task_bottom], MUTED)
            _open_arrowhead(group, ox, icon_top, ox, task_bottom, MUTED)
        if data["outputs"]:
            ox = x + DATA_OBJECT_OFFSET
            _draw_data_object(group, ox, icon_top, data["outputs"])
            _dotted(group, [ox, task_bottom, ox, icon_top], MUTED)
            _open_arrowhead(group, ox, task_bottom, ox, icon_top, MUTED)
        if data["systems"]:
            _draw_data_store(group, x, icon_top, data["systems"])
            _dotted(group, [x, task_bottom, x, icon_top], MUTED)

    # Nodes on top.
    for node in nodes:
        x, y = centre(node["id"])
        kind = node["type"]
        if kind == "task":
            group.add(
                Rect(
                    x - TASK_WIDTH / 2,
                    y - TASK_HEIGHT / 2,
                    TASK_WIDTH,
                    TASK_HEIGHT,
                    rx=6,
                    ry=6,
                    fillColor=CARD,
                    strokeColor=brand.primary,
                    strokeWidth=1.2,
                )
            )
            _draw_task_marker(group, x - TASK_WIDTH / 2 + 11, y + TASK_HEIGHT / 2 - 12, node["marker"], brand.primary)
            if node["step"]:
                group.add(
                    String(
                        x + TASK_WIDTH / 2 - 5,
                        y + TASK_HEIGHT / 2 - 10,
                        f"Step {node['step']}",
                        fontName="Helvetica",
                        fontSize=6.5,
                        fillColor=brand.primary,
                        textAnchor="end",
                    )
                )
            lines = _wrap(node["label"], "Helvetica", TASK_FONT_SIZE, TASK_WIDTH - 12, 3)
            top = y + len(lines) * (TASK_FONT_SIZE + 1.5) / 2 - 3
            _text_block(group, lines, x, top, "Helvetica", TASK_FONT_SIZE, TEXT)
        elif kind == "gateway":
            h = GATEWAY_HALF
            diamond = [x, y + h, x + h, y, x, y - h, x - h, y]
            group.add(Polygon(diamond, fillColor=CARD, strokeColor=brand.primary, strokeWidth=1.2))
            if node["marker"] == "event_based":
                # A double outline is this gateway type's own BPMN marker.
                inset = 5
                group.add(
                    Polygon(
                        [x, y + h - inset, x + h - inset, y, x, y - h + inset, x - h + inset, y],
                        fillColor=None,
                        strokeColor=brand.primary,
                        strokeWidth=0.8,
                    )
                )
            _draw_gateway_marker(group, x, y, node["marker"], brand.primary)
            # Upper-left of the diamond, right-aligned: clear of the arrows that
            # leave from its top (loops) and right (the main path).
            label_width = column_width(node["id"]) / 2 - 6
            lines = _wrap(node["label"], "Helvetica", 7, label_width, 3)
            _text_block(group, lines, x - 6, y + h + len(lines) * 8.5, "Helvetica", 7, TEXT, anchor="end")
        else:
            group.add(
                Circle(
                    x,
                    y,
                    EVENT_RADIUS,
                    fillColor=PAGE,
                    strokeColor=brand.primary,
                    strokeWidth=3.5 if kind == "end" else 1.5,
                )
            )
            _draw_event_marker(group, x, y, node["marker"], brand.primary, PAGE, kind == "end")
            lines = _wrap(node["label"], "Helvetica", 7, column_width(node["id"]) - 8, 3)
            _text_block(group, lines, x, y - EVENT_RADIUS - 2, "Helvetica", 7, MUTED)

    scale = min(width / natural_width, height / natural_height, MAX_SCALE) * 0.999
    group.transform = (scale, 0, 0, scale, 0, 0)
    drawing = Drawing(natural_width * scale, natural_height * scale)
    drawing.add(group)
    return drawing
