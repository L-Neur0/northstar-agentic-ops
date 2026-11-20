"""Tests for the MAP call, the stored diagram and its data objects and stores (spec 18 §3.7–3.9).

Why: a finished profile must always get a map, so a bad reply (empty, refused, invalid twice) gives
the linear map while only a failed call raises; the stored `ProcessDiagram` carries the map
fingerprint and the data objects and stores code builds from the profile; and the one log line
carries counts and rule codes, never text. Covers AC-18.19, AC-18.35 to AC-18.37 and AC-18.39.
"""

from __future__ import annotations

import logging

import pytest

from app.services.process_discovery.artifacts.diagram.diagram import (
    MapCallFailedError,
    linear_process_diagram,
    run_map,
    short_list,
    to_process_diagram,
)
from app.services.process_discovery.artifacts.diagram.grounding import GroundedDiagram, linear_diagram
from app.services.process_discovery.artifacts.diagram.prompts import MAP_SYSTEM, map_user
from app.services.process_discovery.artifacts.fingerprint import map_fingerprint
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.llm import (
    CallType,
    LLMBudgetExceededError,
    LLMEmptyResponseError,
    LLMInvalidOutputError,
    LLMUnavailableError,
)
from tests.fixtures.assessment.profiles import load_profile, nig_vocabulary
from tests.fixtures.assessment.replies import map_reply

SENTINEL = "ZQX-SENTINEL-4711"


async def _run(*replies, profile=None):
    llm = FakeLLM({CallType.MAP: list(replies)})
    diagram = await run_map(profile or load_profile("eu"), llm, vocab=nig_vocabulary())
    return diagram, llm


async def test_one_call_and_a_good_reply_becomes_a_process_diagram():
    """AC-18.19."""
    profile = load_profile("eu")
    diagram, llm = await _run(map_reply())
    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert (call.call_type, call.model_name) == (CallType.MAP, "ProcessDiagramOut")
    assert call.messages == [
        {"role": "system", "content": MAP_SYSTEM},
        {"role": "user", "content": map_user(profile, vocab=nig_vocabulary())},
    ]
    assert diagram.simplified is False
    assert diagram.steps_hash == map_fingerprint(profile)
    assert [n.label for n in diagram.nodes if n.type == "task"] == [s["name"] for s in profile["process"]["substeps"]]


@pytest.mark.parametrize("error", [LLMEmptyResponseError("refused"), LLMInvalidOutputError(["nodes"])])
async def test_a_bad_reply_gives_the_linear_map(error):
    """AC-18.37."""
    diagram, _ = await _run(error)
    assert diagram.simplified is True
    assert [n.type for n in diagram.nodes] == ["start", "task", "task", "task", "task", "task", "end"]


async def test_an_unrepairable_reply_gives_the_linear_map():
    reply = map_reply()
    reply["nodes"] = [n for n in reply["nodes"] if n["id"] != "t4"]
    diagram, _ = await _run(reply)
    assert diagram.simplified is True and len(diagram.data_stores) == 3


@pytest.mark.parametrize("error", [LLMUnavailableError(503), LLMBudgetExceededError("budget")])
async def test_a_failed_call_raises_map_call_failed(error):
    """AC-18.37."""
    with pytest.raises(MapCallFailedError) as raised:
        await _run(error)
    assert raised.value.__cause__ is error


async def test_a_profile_without_steps_raises_without_calling_the_model():
    profile = load_profile("eu")
    profile["process"]["substeps"] = []
    llm = FakeLLM()
    with pytest.raises(MapCallFailedError):
        await run_map(profile, llm, vocab=nig_vocabulary())
    assert llm.calls == []


# --- data objects and stores (§3.8) -------------------------------------------------------------------


def test_data_objects_and_stores_come_from_the_profile():
    """AC-18.36: §3.8 example, ten objects for five tasks and three stores in first-use order."""
    diagram = linear_process_diagram(load_profile("eu"))
    assert diagram is not None
    assert [(o.id, o.direction) for o in diagram.data_objects[:2]] == [("do1i", "input"), ("do1o", "output")]
    assert len(diagram.data_objects) == 10
    by_id = {o.id: o for o in diagram.data_objects}
    assert by_id["do2i"].label == "set of site files; SAP cost centre report"
    assert [(s.id, s.label, s.steps) for s in diagram.data_stores] == [
        ("ds1", "Outlook", [1, 4, 5]),
        ("ds2", "Excel", [1, 2, 3, 5]),
        ("ds3", "SAP S/4HANA", [2]),
    ]


def test_systems_collapse_case_insensitively_and_empty_data_adds_nothing():
    profile = load_profile("eu")
    profile["process"]["substeps"][2]["systems"] = ["excel", "  ", "Power BI"]
    profile["process"]["substeps"][2]["data"] = {"inputs": [], "outputs": []}
    diagram = linear_process_diagram(profile)
    assert diagram is not None
    assert [s.label for s in diagram.data_stores] == ["Outlook", "Excel", "SAP S/4HANA", "Power BI"]
    assert diagram.data_stores[1].steps == [1, 2, 3, 5]
    assert not any(o.step_index == 3 for o in diagram.data_objects)


def test_short_list_deduplicates_and_counts_the_rest():
    """AC-18.36."""
    assert short_list(["a", "A ", "b", "c", "d", "e", None, 4, ""]) == "a; b; c +2"
    assert short_list(["one\nline"]) == "one line"
    assert short_list("not a list") == ""


def test_to_process_diagram_keeps_the_grounded_graph():
    profile = load_profile("eu")
    grounded = linear_diagram(profile)
    assert isinstance(grounded, GroundedDiagram)
    diagram = to_process_diagram(grounded, profile)
    assert (diagram.lanes, diagram.nodes, diagram.flows) == (grounded.lanes, grounded.nodes, grounded.flows)
    assert diagram.steps_hash == map_fingerprint(profile)


def test_the_linear_map_draws_owners_lanes_and_markers():
    """AC-18.35 on the fixture: one owner lane; every step lists a system, so every task is `user`."""
    diagram = linear_process_diagram(load_profile("eu"))
    assert diagram is not None and diagram.simplified is True
    assert diagram.lanes == ["Cost controller"]
    assert {n.marker for n in diagram.nodes if n.type == "task"} == {"user"}
    assert linear_process_diagram({"process": {"substeps": []}}) is None


# --- logging (§3.9) -------------------------------------------------------------------------------------


async def test_one_log_line_per_call_with_counts_and_no_text(caplog):
    """AC-18.39."""
    profile = load_profile("eu")
    profile["process"]["substeps"][0]["name"] += SENTINEL
    reply = map_reply()
    reply["nodes"][3]["label"] = SENTINEL
    with caplog.at_level(logging.DEBUG):
        await _run(reply, profile=profile)
    lines = [r for r in caplog.records if r.getMessage() == "assessment_call"]
    assert len(lines) == 1
    record = lines[0].__dict__
    assert (record["call"], record["outcome"], record["simplified"]) == ("MAP", "generated", False)
    assert record["kept"] > 0 and isinstance(record["duration_ms"], int)
    for r in caplog.records:
        assert SENTINEL not in r.getMessage() and SENTINEL not in repr(r.__dict__)


async def test_a_fallback_logs_its_rule(caplog):
    reply = map_reply()
    reply["nodes"] = [n for n in reply["nodes"] if n["id"] != "t4"]
    with caplog.at_level(logging.DEBUG):
        await _run(reply)
    record = next(r for r in caplog.records if r.getMessage() == "assessment_call").__dict__
    assert (record["outcome"], record["simplified"], record["fallback_rule"]) == ("fallback", True, "G8")
