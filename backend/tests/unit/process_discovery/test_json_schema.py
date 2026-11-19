"""Tests for the strict-mode schema helper `strict_json_schema` (spec 11 §3.6).

Why: Azure Structured Outputs runs the schema inside the decoder and accepts only a narrow subset:
closed, all-required objects. A schema that strict mode rejects fails a live call; these tests
make it fail here, without a network, instead.
What: builds schemas from small Pydantic models (nested, with defaults, optional, recursive,
dict-valued) and checks the envelope, the inlining, the closing of every object and the refusals.
Implements spec 11, AC-11.18 to AC-11.20.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field

from app.services.process_discovery.json_schema import strict_json_schema


class Step(BaseModel):
    number: int
    name: str = Field(description="As the expert said it")


class MapOut(BaseModel):
    steps: list[Step]
    note: str | None = None


class Owner(BaseModel):
    role: str = "unknown"


class Opportunity(BaseModel):
    title: str
    owner: Owner = Field(default_factory=Owner, description="Who owns the change")
    steps: list[int] = []
    grade: int = 3


class Report(BaseModel):
    opportunities: list[Opportunity]
    lead: Owner | None = None
    summary: str = ""


class Node(BaseModel):
    name: str
    children: list[Node] = []


class Tree(BaseModel):
    root: Node


class WithDict(BaseModel):
    counts: dict[str, int]


def walk(node: Any):
    """Every dict in the schema tree."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def test_the_envelope_is_strict_json_schema():
    """AC-11.18: the call site gets the whole wrapper."""
    payload = strict_json_schema(Report, "Report")
    assert payload["type"] == "json_schema"
    assert payload["json_schema"]["name"] == "Report"
    assert payload["json_schema"]["strict"] is True
    assert payload["json_schema"]["schema"]["type"] == "object"


def test_every_object_is_closed_and_all_required():
    """AC-11.18: nested models with defaults are hardened, with no `$defs` or `$ref` left."""
    schema = strict_json_schema(Report, "Report")["json_schema"]["schema"]
    assert "$defs" not in schema
    objects = [n for n in walk(schema) if n.get("type") == "object"]
    assert len(objects) >= 3
    for node in walk(schema):
        assert "$ref" not in node and "$defs" not in node
    for node in objects:
        assert node["additionalProperties"] is False
        assert node["required"] == list(node["properties"])


def test_the_spec_example():
    """AC-11.18: the worked example of spec 11 §3.6."""
    schema = strict_json_schema(MapOut, "MapOut")["json_schema"]["schema"]
    assert schema["required"] == ["steps", "note"]
    assert schema["additionalProperties"] is False
    step = schema["properties"]["steps"]["items"]
    assert step["type"] == "object"
    assert step["required"] == ["number", "name"]
    assert step["additionalProperties"] is False


def test_optional_fields_stay_nullable():
    """AC-11.18: an optional field becomes required but nullable, as strict mode wants."""
    schema = strict_json_schema(MapOut, "MapOut")["json_schema"]["schema"]
    types = [option.get("type") for option in schema["properties"]["note"]["anyOf"]]
    assert "null" in types and "string" in types


def test_a_description_next_to_a_ref_is_kept():
    """AC-11.19: Pydantic puts the field description beside the `$ref`; it wins."""
    schema = strict_json_schema(Opportunity, "Opportunity")["json_schema"]["schema"]
    owner = schema["properties"]["owner"]
    assert owner["description"] == "Who owns the change"
    assert owner["properties"]["role"]["type"] == "string"


def test_the_top_level_title_is_removed():
    """AC-11.19."""
    schema = strict_json_schema(MapOut, "MapOut")["json_schema"]["schema"]
    assert "title" not in schema


def test_a_recursive_model_is_refused_naming_the_path():
    """AC-11.20: strict mode cannot express recursion here, so fail in a unit test, not live."""
    with pytest.raises(ValueError, match=r"Tree.*root\.children"):
        strict_json_schema(Tree, "Tree")


def test_a_recursive_root_model_is_refused():
    """AC-11.20."""
    with pytest.raises(ValueError, match="Node"):
        strict_json_schema(Node, "Node")


def test_a_dict_field_is_refused_naming_the_path():
    """AC-11.20: a `dict[str, X]` field is an open object, which strict mode cannot express."""
    with pytest.raises(ValueError, match=r"WithDict.*counts"):
        strict_json_schema(WithDict, "WithDict")


@pytest.mark.parametrize("name", ["Map Out", "", "x" * 65, "map.out", "naïve"])
def test_a_bad_name_is_refused(name):
    """AC-11.20: the name must match `^[A-Za-z0-9_-]{1,64}$`."""
    with pytest.raises(ValueError):
        strict_json_schema(MapOut, name)


def test_good_names_are_accepted():
    for name in ("MapOut", "map_out-2", "x" * 64):
        assert strict_json_schema(MapOut, name)["json_schema"]["name"] == name


def test_the_input_model_schema_is_not_mutated():
    """Hardening works on a copy: Pydantic caches nothing we changed."""
    before = MapOut.model_json_schema()
    strict_json_schema(MapOut, "MapOut")
    assert MapOut.model_json_schema() == before
