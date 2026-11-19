"""Tests for the profile skeleton and seeding (spec 13 §3.1; AC-13.1, AC-13.2).

Why: every writer and reader stands on the full shape being present; a skeleton that differs from
the Pydantic models would lose keys on the next save. What: compares the skeleton with the model
dumps and checks seeding keeps what is present and never mutates its input.
"""

import copy

from app.models.process_discovery_schemas import Profile, Step
from app.services.process_discovery.profile.shapes import (
    empty_profile,
    empty_step,
    normalized_profile,
    parse_step_key,
    stored_value,
    value_for,
)


def test_empty_profile_is_the_model_dump():
    """AC-13.1."""
    assert empty_profile() == Profile().model_dump(by_alias=True)
    assert empty_step() == Step().model_dump(by_alias=True)


def test_normalized_profile_seeds_missing_keys_and_keeps_present_ones():
    """AC-13.2: missing volume.raw, a step leaf and the flags are seeded; meta, skipped and values kept."""
    stored = empty_profile()
    del stored["process"]["volume"]["raw"]
    stored["process"]["volume"]["count"] = 4
    del stored["process"]["roles_confirmed"]
    row = empty_step()
    del row["goal"]
    row["name"] = "Export"
    row["__skipped"] = ["owner"]
    stored["process"]["substeps"] = [row]
    stored["__meta"] = {"department": {"source": "expert", "status": "confirmed", "at": "t"}}
    before = copy.deepcopy(stored)
    result = normalized_profile(stored)
    assert stored == before
    assert result["process"]["volume"] == {"count": 4, "period": "", "raw": ""}
    assert result["process"]["roles_confirmed"] is False
    assert result["process"]["substeps"][0]["goal"] == ""
    assert result["process"]["substeps"][0]["__skipped"] == ["owner"]
    assert result["__meta"]["department"]["source"] == "expert"


def test_a_non_dict_process_and_a_non_list_table_are_replaced():
    """AC-13.2."""
    assert normalized_profile({"process": "junk"})["process"] == empty_profile()["process"]
    assert normalized_profile({"process": {"substeps": "junk"}})["process"]["substeps"] == []
    assert normalized_profile(None) == empty_profile()


def test_addresses_are_one_based_and_absent_steps_read_none():
    profile = empty_profile()
    profile["process"]["substeps"] = [{**empty_step(), "name": "Export"}]
    assert parse_step_key("process.substeps[3].roles") == (3, "roles")
    assert stored_value(profile, "process.substeps[1].name") == "Export"
    assert stored_value(profile, "process.substeps[2].name") is None
    assert stored_value(profile, "trigger") == ""
    assert value_for(profile, "department") == ""
