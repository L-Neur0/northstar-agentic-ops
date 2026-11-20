"""Strict-mode legality and anti-drift tests for the MAP wire schema (spec 18 §3.7; AC-18.2, AC-18.3).

Why: Azure rejects a non-conforming `json_schema` payload with a 400 at call time, so the strict-subset
rules are asserted statically here, as for the OPPORTUNITIES schema. The second job is anti-drift: the
wire node types and the flat marker union must equal what the storage model accepts
(`DIAGRAM_MARKERS_BY_TYPE`), so a marker added to one cannot silently miss the other.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, get_args

from app.models.process_discovery_schemas import DIAGRAM_MARKERS_BY_TYPE
from app.services.process_discovery.artifacts.diagram.schemas import (
    DiagramMarkerName,
    DiagramNodeTypeName,
    ProcessDiagramOut,
)
from app.services.process_discovery.json_schema import strict_json_schema

UNSUPPORTED_KEYWORDS = {
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern", "format",
    "minItems", "maxItems", "uniqueItems", "contains", "minContains", "maxContains",
    "patternProperties", "propertyNames", "minProperties", "maxProperties",
    "unevaluatedProperties", "unevaluatedItems",
}  # fmt: skip

FORMAT = strict_json_schema(ProcessDiagramOut, "ProcessDiagramOut")
SCHEMA = FORMAT["json_schema"]["schema"]


def _walk(node: Any, path: str = "$", depth: int = 0) -> Iterator[tuple[str, int, Any]]:
    """Every dict node in the schema, with its path and object-nesting depth."""
    if isinstance(node, list):
        for index, item in enumerate(node):
            yield from _walk(item, f"{path}[{index}]", depth)
        return
    if not isinstance(node, dict):
        return
    is_object = node.get("type") == "object"
    yield path, depth, node
    for key, value in node.items():
        yield from _walk(value, f"{path}.{key}", depth + 1 if is_object else depth)


def _node_props() -> dict[str, Any]:
    return SCHEMA["properties"]["nodes"]["items"]["properties"]


def test_the_payload_is_a_strict_json_schema_response_format():
    """AC-18.2."""
    assert FORMAT["type"] == "json_schema" and FORMAT["json_schema"]["strict"] is True


def test_the_root_is_an_object_with_lanes_nodes_and_flows():
    assert SCHEMA["type"] == "object" and "anyOf" not in SCHEMA
    assert list(SCHEMA["properties"]) == ["lanes", "nodes", "flows"]


def test_node_has_a_marker_and_flow_has_is_default():
    assert list(_node_props()) == ["id", "type", "label", "lane", "step_index", "marker"]
    assert list(SCHEMA["properties"]["flows"]["items"]["properties"]) == ["source", "target", "label", "is_default"]


def test_nothing_is_left_behind_a_ref():
    assert "$defs" not in SCHEMA
    assert all("$ref" not in node for _, _, node in _walk(SCHEMA))


def test_every_object_is_closed_and_all_required():
    for path, _, node in _walk(SCHEMA):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, path
            assert sorted(node["required"]) == sorted(node["properties"]), path


def test_no_unsupported_keywords():
    for path, _, node in _walk(SCHEMA):
        assert not (UNSUPPORTED_KEYWORDS & set(node)), path


def test_node_types_equal_the_storage_node_types():
    """AC-18.3."""
    assert list(get_args(DiagramNodeTypeName)) == list(DIAGRAM_MARKERS_BY_TYPE)
    assert _node_props()["type"]["enum"] == list(DIAGRAM_MARKERS_BY_TYPE)


def test_the_marker_union_equals_the_union_of_the_storage_markers():
    """AC-18.3."""
    union = {m for markers in DIAGRAM_MARKERS_BY_TYPE.values() for m in markers}
    assert set(get_args(DiagramMarkerName)) == union
    assert len(get_args(DiagramMarkerName)) == len(union)
    assert set(_node_props()["marker"]["enum"]) == union


def test_step_index_is_nullable_without_a_bound():
    assert {entry["type"] for entry in _node_props()["step_index"]["anyOf"]} == {"integer", "null"}


def test_nesting_stays_within_the_strict_budget():
    assert max(depth for _, depth, _ in _walk(SCHEMA)) <= 5


def test_the_worked_reply_validates():
    from tests.fixtures.assessment.replies import map_reply

    assert len(ProcessDiagramOut.model_validate(map_reply()).nodes) == 8
