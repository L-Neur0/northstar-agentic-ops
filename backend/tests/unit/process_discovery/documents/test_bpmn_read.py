"""Tests for reading a BPMN 2.0 file in code: steps, order, lanes, process fields, safety (spec 17 §3.6).

Why: a process map already holds the steps, their order and the roles (lanes); reading it in code
costs nothing, cannot invent anything and needs no model call (AD-12). It is also XML from an
untrusted source, so entities and DTDs must never be expanded.
What: AC-17.8 and AC-17.17 to AC-17.19, and the choice of the process with the most named tasks.
Must not: make a network call or a model call. Spec 17 §3.6, §3.16.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.process_discovery.documents.bpmn_read import read_bpmn
from app.services.process_discovery.documents.intake import DocumentRejected

BUDGET = 60_000


def step_names(raw) -> list[str]:
    return [s.name.value for s in raw.steps]


def step_roles(raw) -> list[list[str]]:
    return [[r.role for r in s.roles] for s in raw.steps]


@pytest.mark.parametrize("fixture", ["xxe.bpmn", "entities.bpmn"])
def test_ac_17_8_dtd_and_entities_are_unreadable(fixture_bytes, fixture):
    with pytest.raises(DocumentRejected) as caught:
        read_bpmn(fixture_bytes(fixture), BUDGET)
    assert caught.value.code == "document_unreadable"


def test_ac_17_17_worked_example_2(fixture_bytes):
    read = read_bpmn(fixture_bytes("access_review.bpmn"), BUDGET)
    assert read.text.text == (
        "Process: Quarterly access review\n"
        "Start: Quarter starts\n"
        "Step 1: Export user access list (lane: IT security analyst)\n"
        "Step 2: Review access per employee (lane: Line manager)\n"
        "Step 3: Request access removal (lane: Line manager)\n"
        "Step 4: Remove access and document (lane: IT security analyst)\n"
        "End: Access review signed off"
    )
    raw: Any = read.raw
    assert raw.document_kind == "process_map"
    assert (raw.name.value, raw.name.quote) == ("Quarterly access review", "Quarterly access review")
    assert (raw.trigger.value, raw.trigger.quote) == ("Quarter starts", "Quarter starts")
    assert (raw.end_result.value, raw.end_result.quote) == ("Access review signed off", "Access review signed off")
    assert step_names(raw) == [
        "Export user access list",
        "Review access per employee",
        "Request access removal",
        "Remove access and document",
    ]
    assert step_roles(raw) == [["IT security analyst"], ["Line manager"], ["Line manager"], ["IT security analyst"]]
    assert all(s.name.quote == s.name.value for s in raw.steps)
    assert raw.steps[0].roles[0].quote == "IT security analyst"
    assert read.processes_ignored == 0


def test_ac_17_18_back_edge_unnamed_task_and_laneless_task(fixture_bytes):
    raw: Any = read_bpmn(fixture_bytes("access_review_edge.bpmn"), BUDGET).raw
    assert step_names(raw) == [
        "Export user access list",
        "Review access per employee",
        "Request access removal",
        "Remove access and document",
        "Archive the evidence",
    ]
    assert step_roles(raw)[-1] == []


def test_ac_17_19_nine_tasks_in_order(fixture_bytes):
    read = read_bpmn(fixture_bytes("long_process.bpmn"), BUDGET)
    assert step_names(read.raw) == [
        "Receive request",
        "Check identity",
        "Classify request",
        "Check budget",
        "Get approval",
        "Order item",
        "Receive item",
        "Hand over item",
        "Close request",
    ]


def test_the_process_with_most_named_tasks_is_read(fixture_bytes):
    read = read_bpmn(fixture_bytes("two_processes.bpmn"), BUDGET)
    raw: Any = read.raw
    assert read.processes_ignored == 1
    assert raw.name.value == "Supplier onboarding"  # from the participant: the process has no name
    assert len(raw.steps) == 5
    assert raw.trigger.value == "Form received"


def test_names_are_collapsed_and_tasks_capped():
    ns = "http://www.omg.org/spec/BPMN/20100524/MODEL"
    tasks = "".join(f'<task id="t{i}" name="Task   {i}"/>' for i in range(501))
    data = f'<definitions xmlns="{ns}"><process id="p">{tasks}</process></definitions>'.encode()
    with pytest.raises(DocumentRejected) as caught:
        read_bpmn(data, BUDGET)
    assert caught.value.code == "document_unreadable"
    assert caught.value.message == "This diagram is too large to read."
    small = (
        f'<definitions xmlns="{ns}"><process id="p"><task id="a" name="  Check \n  order "/></process></definitions>'
    )
    assert step_names(read_bpmn(small.encode(), BUDGET).raw) == ["Check order"]
