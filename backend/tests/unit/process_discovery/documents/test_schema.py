"""Tests for the READ_DOCUMENT output model generated from the field registry (spec 17 §3.7).

Why: a hand-written schema drifts from the registry, and a schema that could express a none row or
a flag would let a document write "there are none" or a confirmation. The model is generated, so
these tests pin what generation must and must not produce.
What: AC-17.20 to AC-17.22.
Must not: restate the registry; every expectation is derived from `proposal_keys()` and the specs.
Spec 17 §3.7.
"""

from __future__ import annotations

import json
from dataclasses import replace

from app.services.process_discovery.documents.schema import build_read_document_model, read_document_model
from app.services.process_discovery.domain.field_spec import (
    DERIVED_SPECS,
    FLAG_KEYS,
    PROFILE_SPECS,
    STEP_SPECS,
    proposal_keys,
)
from app.services.process_discovery.json_schema import strict_json_schema


def schema() -> dict:
    return strict_json_schema(read_document_model(), "ReadDocumentOut")["json_schema"]["schema"]


def test_ac_17_20_top_level_properties_are_the_proposable_leaves():
    leaves = {k.split(".", 1)[1] for k in proposal_keys() if k.startswith("process.") and "substeps[" not in k}
    scoped = {"document_role", "target_step", "target_named_by", "file_description", "target_cells"}  # §3.18
    assert set(read_document_model().model_fields) == {*scoped, "steps", *leaves}
    forbidden = {"department", "user_function", "region", "cluster", "substep_count", "substeps", "__meta"}
    forbidden |= set(FLAG_KEYS) | {d.key.split(".", 1)[1] for d in DERIVED_SPECS}
    assert not forbidden & set(read_document_model().model_fields)


def test_ac_17_20_step_properties_are_the_s_leaves():
    step = schema()["properties"]["steps"]["items"]
    assert set(step["properties"]) == {s.key for s in STEP_SPECS if s.propose}


def test_ac_17_20_the_model_is_built_once():
    assert read_document_model() is read_document_model()


def _walk(node, path=()):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _walk(value, (*path, key))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk(value, (*path, str(i)))


def test_ac_17_21_strict_schema_and_quotes_everywhere():
    payload = strict_json_schema(read_document_model(), "ReadDocumentOut")
    assert payload["json_schema"]["strict"] is True
    objects = [(p, n) for p, n in _walk(payload["json_schema"]["schema"]) if n.get("type") == "object"]
    for path, node in objects:
        assert node["additionalProperties"] is False
        if path == () or path[-2:] == ("steps", "items") or "target_cells" in path[-3:]:
            continue  # the reply itself, a step and the target cells: their parts carry the quotes
        props = set(node["properties"])
        if props == {"inputs", "outputs"}:
            continue  # S07: each item carries its own quote
        assert "quote" in props, path
    text = json.dumps(payload)
    assert '"none"' not in text
    assert "none_identified" not in text
    assert "estimated" not in text
    assert '"boolean"' not in text


def test_ac_17_21_steps_need_a_quoted_name():
    step = schema()["properties"]["steps"]["items"]
    name = step["properties"]["name"]
    assert name.get("type") == "object"  # required, not nullable
    assert set(name["properties"]) == {"value", "quote"}


def test_ac_17_22_a_new_proposable_field_appears_without_code_changes():
    trigger = next(s for s in PROFILE_SPECS if s.key == "process.trigger")
    extra = replace(trigger, id="P99", key="process.handover_note", label="Hand-over note")
    model = build_read_document_model((*PROFILE_SPECS, extra), STEP_SPECS)
    assert "handover_note" in model.model_fields
    not_proposable = replace(extra, key="process.secret_note", propose=False)
    assert "secret_note" not in build_read_document_model((*PROFILE_SPECS, not_proposable), STEP_SPECS).model_fields
