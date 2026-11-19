"""Parity between the field registry and the Pydantic profile models (spec 12 §3.11).

Why: the registry and the models describe the same profile twice, once as rules and once as
types. If they drift, a field is collected and silently dropped on save, or stored and never
graded; this was the original failure that made the registry necessary.
What: walks every P spec, S leaf, sub-field, derived key and flag and finds exactly one model
field of the right type, with no unknown extras; then checks the empty skeleton and a full
round trip. Implements AC-12.39 and AC-12.40.
"""

import types
import typing
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from app.models.process_discovery_schemas import NoneRow, Process, Profile, Step
from app.services.process_discovery.domain import field_spec as fs

SIDECARS = {"meta", "skipped"}

SCALAR = {"text": str, "list": list[str], "bool": bool}


def _is_optional_int(annotation: Any) -> bool:
    return get_origin(annotation) in (typing.Union, types.UnionType) and set(get_args(annotation)) == {int, type(None)}


def _check_scalar(kind: str, annotation: Any, where: str) -> None:
    if kind == "number":
        assert _is_optional_int(annotation), where
    else:
        assert annotation == SCALAR[kind], where


def _row_model(annotation: Any) -> type[BaseModel]:
    assert get_origin(annotation) is list
    (inner,) = get_args(annotation)
    members = get_args(inner)
    assert len(members) == 2 and members[0] is NoneRow, annotation
    return members[1]


def _check_spec(spec: fs.FieldSpec, annotation: Any) -> None:
    if spec.kind in ("text", "list", "number"):
        _check_scalar(spec.kind, annotation, spec.id)
        return
    sub_model = annotation if spec.kind == "object" else _row_model(annotation)
    assert isinstance(sub_model, type) and issubclass(sub_model, BaseModel), spec.id
    fields = sub_model.model_fields
    assert set(fields) == {sf.key for sf in spec.subfields}, spec.id
    for sf in spec.subfields:
        _check_scalar(sf.kind, fields[sf.key].annotation, f"{spec.id}.{sf.key}")


def test_every_process_field_has_exactly_one_model_field():
    """AC-12.39: P keys, derived keys and flags are the whole of `Profile` and `Process`."""
    profile_fields = set(Profile.model_fields) - SIDECARS
    top = {s.key for s in fs.PROFILE_SPECS if not s.is_process}
    assert profile_fields == top | {"process"}
    process_keys = {s.leaf for s in fs.PROFILE_SPECS if s.is_process}
    derived = {d.key.split(".", 1)[1] for d in fs.DERIVED_SPECS}
    assert set(Process.model_fields) == process_keys | derived | set(fs.FLAG_KEYS) | {"substeps"}
    for spec in fs.PROFILE_SPECS:
        model = Process if spec.is_process else Profile
        _check_spec(spec, model.model_fields[spec.leaf].annotation)
    for key in derived:
        assert Process.model_fields[key].annotation == list[str]


def test_every_step_field_has_exactly_one_model_field():
    """AC-12.39: S leaves are the whole of `Step` apart from its sidecars."""
    assert set(Step.model_fields) - SIDECARS == {s.key for s in fs.STEP_SPECS}
    for spec in fs.STEP_SPECS:
        _check_spec(spec, Step.model_fields[spec.key].annotation)


def test_flags_are_typed():
    """§3.4: three bool flags and the rejected count."""
    fields = Process.model_fields
    assert all(fields[f].annotation is bool for f in ("substeps_complete", "roles_confirmed", "tools_confirmed"))
    assert _is_optional_int(fields["substep_count_rejected"].annotation)


SKELETON = {
    "department": "",
    "user_function": "",
    "region": "",
    "process": {
        "name": "",
        "cluster": {"code": "", "name": "", "decided_by": ""},
        "trigger": "",
        "end_result": "",
        "value_at_end": "",
        "business_pain": "",
        "volume": {"count": None, "period": "", "raw": ""},
        "process_owner": {"role": "", "none_identified": False},
        "baseline_metric": {"value": "", "unit": "", "qualitative": "", "estimated": False},
        "target_metric": {"value": "", "unit": ""},
        "variation": {"same": "", "differences": ""},
        "sensitive_data": [],
        "substep_count": None,
        "substep_count_rejected": None,
        "substeps": [],
        "all_roles": [],
        "all_tools": [],
        "substeps_complete": False,
        "roles_confirmed": False,
        "tools_confirmed": False,
    },
    "__meta": {},
}

EMPTY_STEP = {
    "name": "",
    "goal": "",
    "activities": [],
    "roles": [],
    "owner": "",
    "systems": [],
    "data": {"inputs": [], "outputs": []},
    "effort": {"duration": "", "frequency": ""},
    "pain_points": [],
    "approvals": [],
    "exceptions": [],
    "handover": "",
    "__meta": {},
    "__skipped": [],
}


def test_the_empty_profile_is_the_skeleton():
    """AC-12.40: `Profile().model_dump(by_alias=True)` equals the JSON skeleton of §3.11."""
    assert Profile().model_dump(by_alias=True) == SKELETON
    assert Step().model_dump(by_alias=True) == EMPTY_STEP


def _full_step(i: int) -> dict:
    return {
        "name": f"Step {i}",
        "goal": "Done",
        "activities": ["a", "b"],
        "roles": [{"role": "AP clerk", "contribution": "checks"}] if i % 2 else [{"none": True}],
        "owner": "Controller",
        "systems": ["SAP"],
        "data": {"inputs": ["invoice"], "outputs": ["report"]},
        "effort": {"duration": "2h", "frequency": "weekly"},
        "pain_points": ["slow"],
        "approvals": [{"approver_role": "CFO", "waiting_time": "2 days"}] if i % 2 else [{"none": True}],
        "exceptions": [{"description": "missing data", "loops_back_to": 1}] if i > 1 else [{"none": True}],
        "handover": "email",
        "__meta": {
            "systems": {
                "source": "expert",
                "status": "confirmed",
                "documentId": None,
                "quote": None,
                "by": None,
                "at": "t",
            }
        },
        "__skipped": ["goal"] if i == 3 else [],
    }


def test_a_full_profile_round_trips_unchanged():
    """AC-12.40: sentinels, meta, skipped cells and 6 full steps survive validate → dump."""
    data = {
        **SKELETON,
        "department": "Finance",
        "process": {
            **SKELETON["process"],
            "name": "Monthly cost review",
            "cluster": {"code": "FIN", "name": "Finance", "decided_by": "proposal"},
            "process_owner": {"role": "", "none_identified": True},
            "sensitive_data": [{"none": True}],
            "substep_count": 6,
            "substeps": [_full_step(i) for i in range(1, 7)],
            "all_roles": ["AP clerk"],
            "all_tools": ["SAP"],
            "roles_confirmed": True,
        },
        "__meta": {
            "process.trigger": {
                "source": "document",
                "status": "proposed",
                "documentId": "d1",
                "quote": "q",
                "by": None,
                "at": "2026-11-20T09:14:03Z",
            }
        },
    }
    assert Profile.model_validate(data).model_dump(by_alias=True) == data
    assert Profile.model_validate(data).model_dump(by_alias=True, mode="json") == data
