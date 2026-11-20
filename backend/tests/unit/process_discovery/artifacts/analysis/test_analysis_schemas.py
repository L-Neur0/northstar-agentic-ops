"""Strict-mode legality and anti-drift tests for the OPPORTUNITIES wire schema (spec 18 §3.4; AC-18.2, AC-18.3).

Why: Azure rejects a non-conforming `json_schema` payload with a 400 at call time, so every rule of
the strict subset we could plausibly break is asserted here instead, statically, on every run: all
properties required, `additionalProperties: false` on every object, no unsupported keywords, a root
that is an object, and the nesting and property budgets. The second job is anti-drift: the wire
vocabularies must equal the storage enums `OpportunityType` and `Grade`.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, get_args

import pytest

from app.models.process_discovery_schemas import Grade, Opportunity, OpportunityType
from app.services.process_discovery.artifacts.analysis.schemas import (
    GradeName,
    OpportunitiesOut,
    OpportunityOut,
    OpportunityTypeName,
)
from app.services.process_discovery.json_schema import strict_json_schema

UNSUPPORTED_KEYWORDS = {
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "pattern", "format",
    "minItems", "maxItems", "uniqueItems", "contains", "minContains", "maxContains",
    "patternProperties", "propertyNames", "minProperties", "maxProperties",
    "unevaluatedProperties", "unevaluatedItems",
}  # fmt: skip

FORMAT = strict_json_schema(OpportunitiesOut, "OpportunitiesOut")
SCHEMA: dict[str, Any] = FORMAT["json_schema"]["schema"]


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


def _opportunity_schema() -> dict[str, Any]:
    return SCHEMA["properties"]["opportunities"]["items"]


def test_the_payload_is_a_strict_json_schema_response_format():
    """AC-18.2."""
    assert FORMAT["type"] == "json_schema"
    assert FORMAT["json_schema"]["strict"] is True
    assert set(FORMAT["json_schema"]) == {"name", "strict", "schema"}


def test_the_root_is_an_object_not_an_any_of():
    assert SCHEMA["type"] == "object" and "anyOf" not in SCHEMA
    assert list(SCHEMA["properties"]) == ["summary", "opportunities", "stay_human"]


def test_nothing_is_left_behind_a_ref():
    assert "$defs" not in SCHEMA
    for path, _, node in _walk(SCHEMA):
        assert "$ref" not in node, f"unresolved $ref at {path}"


def test_every_object_is_closed_and_all_required():
    for path, _, node in _walk(SCHEMA):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, f"{path} is not closed"
            assert sorted(node.get("required", [])) == sorted(node["properties"]), path


def test_no_unsupported_keyword_survives_anywhere():
    for path, _, node in _walk(SCHEMA):
        assert not (UNSUPPORTED_KEYWORDS & set(node)), path


def test_the_storage_model_would_not_have_been_legal():
    """Pins the premise for a separate wire model: the storage model has bounds and optional fields."""
    storage = Opportunity.model_json_schema()
    assert "maximum" in repr(storage)
    assert sorted(storage["required"]) != sorted(storage["properties"])


def test_the_budgets_are_nowhere_near_the_limits():
    properties = sum(len(n["properties"]) for _, _, n in _walk(SCHEMA) if n.get("type") == "object")
    assert properties <= 100
    assert max(depth for _, depth, _ in _walk(SCHEMA)) <= 5


def test_the_opportunity_has_exactly_the_spec_fields():
    assert list(_opportunity_schema()["properties"]) == [
        "title", "steps", "type", "what_changes", "how", "prepare_first",
        "impact", "impact_reason", "feasibility", "feasibility_reason", "evidence",
    ]  # fmt: skip
    stay = SCHEMA["properties"]["stay_human"]["items"]
    assert list(stay["properties"]) == ["steps", "reason", "evidence"]


def test_the_type_is_a_closed_enum_equal_to_opportunity_type():
    """AC-18.3."""
    values = [t.value for t in OpportunityType]
    assert _opportunity_schema()["properties"]["type"]["enum"] == values
    assert list(get_args(OpportunityTypeName)) == values
    assert list(get_args(OpportunityOut.model_fields["type"].annotation)) == values


def test_both_grades_are_the_grade_enum():
    """AC-18.3."""
    grades = [g.value for g in Grade]
    assert list(get_args(GradeName)) == grades
    for name in ("impact", "feasibility"):
        assert _opportunity_schema()["properties"][name]["enum"] == grades


def test_steps_is_a_plain_integer_list_without_bounds():
    steps = _opportunity_schema()["properties"]["steps"]
    assert steps["type"] == "array" and steps["items"] == {"type": "integer"}


def test_a_well_formed_reply_validates():
    from tests.fixtures.assessment.replies import opportunities_reply

    assert len(OpportunitiesOut.model_validate(opportunities_reply()).opportunities) == 6


@pytest.mark.parametrize("extra", [{"confidence": 0.9}, {"hours": 12}])
def test_the_wire_model_forbids_extras(extra):
    with pytest.raises(ValueError):
        OpportunitiesOut.model_validate({"summary": "s", "opportunities": [], "stay_human": [], **extra})
