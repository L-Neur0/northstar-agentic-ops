"""Tests for grounding the MAP reply in the real profile (spec 18 §3.8; AC-18.20 to AC-18.35).

Why: `ground_diagram` is the anti-hallucination layer: whatever the model returned, what comes out
draws only steps that exist, with their real names, in lanes named after real roles, as a connected
start-to-end graph in step order that obeys the BPMN rules; or, when the reply cannot be repaired into
that, the linear map drawn from the steps. These tests feed it deliberately wrong replies, one rule at
a time, on a small two-step profile and on the cost-review fixture. The random-reply fuzz test is in
`test_diagram_fuzz.py`.
"""

from __future__ import annotations

import copy

import pytest

from app.services.process_discovery.artifacts.diagram import grounding
from app.services.process_discovery.artifacts.diagram.grounding import GroundedDiagram, short_event_label


def ground_diagram(reply, profile) -> GroundedDiagram:
    """`grounding.ground_diagram`, for profiles that have steps (so never `None`)."""
    result = grounding.ground_diagram(reply, profile)
    assert result is not None
    return result


def linear_diagram(profile) -> GroundedDiagram:
    result = grounding.linear_diagram(profile)
    assert result is not None
    return result


def _profile(**overrides):
    process = {
        "trigger": "Invoice fails the three-way match",
        "end_result": "Invoice posted and paid",
        "substeps": [
            {"name": "Triage the exception", "owner": "AP Specialist", "roles": [{"role": "Buyer"}]},
            {"name": "Correct and post", "owner": "AP Specialist", "roles": []},
        ],
        "process_owner": {"role": "AP Team Lead"},
    }
    process.update(overrides)
    return {"process": process}


def _reply():
    """A good reply: a gateway where the buyer must confirm the fix."""
    return {
        "lanes": ["AP Specialist", "Buyer"],
        "nodes": [
            {"id": "start", "type": "start", "label": "Match fails", "lane": 0, "step_index": None},
            {"id": "t1", "type": "task", "label": "Triage", "lane": 0, "step_index": 1},
            {"id": "g1", "type": "gateway", "label": "PO correct?", "lane": 0, "step_index": None},
            {"id": "t2", "type": "task", "label": "Post it", "lane": 0, "step_index": 2},
            {"id": "end", "type": "end", "label": "Paid", "lane": 0, "step_index": None},
        ],
        "flows": [
            {"source": "start", "target": "t1", "label": ""},
            {"source": "t1", "target": "g1", "label": ""},
            {"source": "g1", "target": "t2", "label": "yes"},
            {"source": "g1", "target": "t1", "label": "no"},
            {"source": "t2", "target": "end", "label": ""},
        ],
    }


def _by_id(diagram):
    return {n.id: n for n in diagram.nodes}


def _tasks(diagram):
    return sorted((n for n in diagram.nodes if n.type == "task"), key=lambda n: n.step_index)


def _edges(diagram):
    return {(f.source, f.target) for f in diagram.flows}


# --- a good reply is kept (AC-18.20, AC-18.31) -----------------------------


def test_a_good_reply_is_kept_with_its_gateway_and_loop():
    diagram = ground_diagram(_reply(), _profile())
    assert diagram.simplified is False
    gateways = [n for n in diagram.nodes if n.type == "gateway"]
    assert len(gateways) == 2  # the decision g1, plus the merge where the "no" loop comes back
    assert ("g1", "merge") in _edges(diagram) and ("merge", "t1") in _edges(diagram)
    assert {f.label for f in diagram.flows if f.source == "g1"} == {"yes", "no"}


def test_task_labels_are_replaced_by_the_real_sub_step_names():
    diagram = ground_diagram(_reply(), _profile())
    assert [t.label for t in _tasks(diagram)] == ["Triage the exception", "Correct and post"]


def test_a_short_model_label_is_kept_for_start_and_end():
    diagram = ground_diagram(_reply(), _profile())
    nodes = _by_id(diagram)
    assert (nodes["start"].label, nodes["end"].label) == ("Match fails", "Paid")


def test_a_missing_model_label_uses_the_profile_text_when_it_fits():
    reply = _reply()
    reply["nodes"][0]["label"] = ""
    reply["nodes"][4]["label"] = ""
    diagram = ground_diagram(reply, _profile())
    nodes = _by_id(diagram)
    assert nodes["start"].label == "Invoice fails the three-way match"
    assert nodes["end"].label == "Invoice posted and paid"


def test_a_long_model_label_is_replaced_by_the_profiles_first_clause():
    reply = _reply()
    reply["nodes"][0]["label"] = "The invoice arrives and it does not match the purchase order at all"
    profile = _profile(trigger="Invoice fails the three-way match, so AP has to investigate it")
    diagram = ground_diagram(reply, profile)
    assert _by_id(diagram)["start"].label == "Invoice fails the three-way match"


def test_a_model_label_with_more_than_six_words_is_replaced():
    reply = _reply()
    reply["nodes"][0]["label"] = "a b c d e f g"
    diagram = ground_diagram(reply, _profile())
    assert _by_id(diagram)["start"].label == "Invoice fails the three-way match"


def test_linear_diagram_labels_events_with_the_first_clause():
    profile = _profile(trigger="A supplier invoice arrives that does not match the purchase order")
    diagram = linear_diagram(profile)
    assert _by_id(diagram)["start"].label == "A supplier invoice arrives"
    assert _by_id(diagram)["end"].label == "Invoice posted and paid"


def test_short_event_label_keeps_text_that_already_fits():
    assert short_event_label("Invoice posted and paid") == "Invoice posted and paid"
    assert short_event_label("  Invoice   received ") == "Invoice received"
    assert short_event_label("") == ""


def test_short_event_label_cuts_long_text_at_the_first_clause():
    assert (
        short_event_label("A supplier invoice arrives that does not match the purchase order")
        == "A supplier invoice arrives"
    )
    assert (
        short_event_label("Invoice is approved; the payment run picks it up the next business day")
        == "Invoice is approved"
    )


def test_short_event_label_with_an_empty_first_clause_cuts_at_a_word():
    label = short_event_label("(urgent) a supplier invoice arrives without a matching purchase order")
    assert label.startswith("(urgent) a supplier")
    assert label.endswith("…")
    assert len(label) <= 40


def test_short_event_label_cuts_a_single_huge_word():
    label = short_event_label("x" * 58)
    assert label == "X" + "x" * 38 + "…"  # capitalised, then cut


def test_unused_lanes_are_dropped():
    diagram = ground_diagram(_reply(), _profile())
    assert diagram.lanes == ["AP Specialist"]  # nobody was placed in "Buyer"
    assert all(n.lane == "AP Specialist" for n in diagram.nodes)


# --- hallucinated steps and roles (AC-18.21, AC-18.22) ---------------------


def test_an_invented_step_is_dropped():
    reply = _reply()
    reply["nodes"].insert(3, {"id": "t9", "type": "task", "label": "Call the CFO", "lane": 0, "step_index": 9})
    reply["flows"] += [
        {"source": "g1", "target": "t9", "label": "maybe"},
        {"source": "t9", "target": "end", "label": ""},
    ]
    diagram = ground_diagram(reply, _profile())
    assert "t9" not in _by_id(diagram)
    assert all("t9" not in edge for edge in _edges(diagram))
    assert diagram.simplified is False


def test_a_task_without_a_step_is_dropped():
    reply = _reply()
    reply["nodes"].insert(3, {"id": "tx", "type": "task", "label": "Extra", "lane": 0, "step_index": None})
    diagram = ground_diagram(reply, _profile())
    assert "tx" not in _by_id(diagram)


def test_a_second_task_for_the_same_step_is_dropped():
    reply = _reply()
    reply["nodes"].insert(2, {"id": "t1b", "type": "task", "label": "Again", "lane": 0, "step_index": 1})
    diagram = ground_diagram(reply, _profile())
    assert [t.step_index for t in _tasks(diagram)] == [1, 2]


def test_an_invented_role_moves_the_task_to_its_real_owner_lane():
    reply = _reply()
    reply["lanes"] = ["Robot", "AP Specialist"]
    for node in reply["nodes"]:
        node["lane"] = 0  # everything in the invented "Robot" lane
    diagram = ground_diagram(reply, _profile())
    assert "Robot" not in diagram.lanes
    assert all(t.lane == "AP Specialist" for t in _tasks(diagram))


def test_a_task_may_sit_in_the_lane_of_a_role_really_involved_in_that_step():
    reply = _reply()
    reply["nodes"][1]["lane"] = 1  # step 1 in "Buyer": a real role of step 1
    diagram = ground_diagram(reply, _profile())
    assert _by_id(diagram)["t1"].lane == "Buyer"


def test_a_real_role_not_involved_in_the_step_is_not_accepted_for_it():
    reply = _reply()
    reply["nodes"][3]["lane"] = 1  # step 2 in "Buyer": Buyer is not in step 2
    diagram = ground_diagram(reply, _profile())
    assert _by_id(diagram)["t2"].lane == "AP Specialist"


def test_duplicate_lane_names_collapse_case_insensitively():
    reply = _reply()
    reply["lanes"] = ["AP Specialist", "ap specialist "]
    reply["nodes"][3]["lane"] = 1
    diagram = ground_diagram(reply, _profile())
    assert diagram.lanes == ["AP Specialist"]


# --- broken graphs are repaired (AC-18.24, AC-18.25, AC-18.33) -------------


def test_flows_to_unknown_ids_self_loops_and_duplicates_are_dropped():
    reply = _reply()
    reply["flows"] += [
        {"source": "t1", "target": "ghost", "label": ""},
        {"source": "t2", "target": "t2", "label": ""},
        {"source": "t2", "target": "end", "label": ""},
    ]
    diagram = ground_diagram(reply, _profile())
    assert all("ghost" not in edge for edge in _edges(diagram))
    assert ("t2", "t2") not in _edges(diagram)
    assert sum(1 for f in diagram.flows if (f.source, f.target) == ("t2", "end")) == 1


def test_a_missing_start_and_end_are_added():
    reply = _reply()
    reply["nodes"] = [n for n in reply["nodes"] if n["type"] not in ("start", "end")]
    reply["flows"] = [f for f in reply["flows"] if f["source"] != "start" and f["target"] != "end"]
    diagram = ground_diagram(reply, _profile())
    types = [n.type for n in diagram.nodes]
    assert types.count("start") == 1 and types.count("end") >= 1
    assert diagram.simplified is False


def test_extra_start_nodes_are_removed():
    reply = _reply()
    reply["nodes"].append({"id": "start2", "type": "start", "label": "", "lane": 0, "step_index": None})
    reply["flows"].append({"source": "start2", "target": "t2", "label": ""})
    diagram = ground_diagram(reply, _profile())
    assert [n.type for n in diagram.nodes].count("start") == 1


def test_a_dead_end_task_is_connected_onward():
    reply = _reply()
    reply["flows"] = [f for f in reply["flows"] if f["source"] != "t2"]  # t2 goes nowhere
    diagram = ground_diagram(reply, _profile())
    assert any(f.source == "t2" for f in diagram.flows)
    assert diagram.simplified is False


def test_an_unreachable_gateway_is_dropped():
    reply = _reply()
    reply["nodes"].append({"id": "g9", "type": "gateway", "label": "Orphan?", "lane": 0, "step_index": None})
    reply["flows"].append({"source": "g9", "target": "end", "label": "yes"})
    diagram = ground_diagram(reply, _profile())
    assert "g9" not in _by_id(diagram)


def test_labels_are_trimmed_and_control_characters_stripped():
    reply = _reply()
    reply["nodes"][2]["label"] = "PO\x00 correct?\n" + "x" * 500
    diagram = ground_diagram(reply, _profile())
    label = _by_id(diagram)["g1"].label
    assert "\x00" not in label and "\n" not in label
    assert len(label) <= 60


# --- unusable replies fall back to the linear map (AC-18.21, AC-18.26, AC-18.34)


def test_a_missing_step_falls_back_to_the_linear_diagram():
    reply = _reply()
    reply["nodes"] = [n for n in reply["nodes"] if n["id"] != "t2"]
    diagram = ground_diagram(reply, _profile())
    assert diagram.simplified is True
    assert [t.label for t in _tasks(diagram)] == ["Triage the exception", "Correct and post"]


def test_steps_in_the_wrong_order_fall_back_to_the_linear_diagram():
    reply = _reply()
    reply["flows"] = [
        {"source": "start", "target": "t2", "label": ""},
        {"source": "t2", "target": "t1", "label": ""},
        {"source": "t1", "target": "end", "label": ""},
    ]
    assert ground_diagram(reply, _profile()).simplified is True


def test_garbage_falls_back_to_the_linear_diagram():
    for garbage in (None, "not json", [], {"nodes": "x"}, {"lanes": 3, "nodes": [1, 2], "flows": None}):
        diagram = ground_diagram(garbage, _profile())
        assert diagram.simplified is True
        assert len(_tasks(diagram)) == 2


def test_wrong_value_types_never_crash():
    reply = _reply()
    reply["nodes"][1]["step_index"] = "1"
    reply["nodes"][2]["lane"] = True
    reply["nodes"][3]["lane"] = -5
    reply["flows"][0]["source"] = {"x": 1}
    diagram = ground_diagram(reply, _profile())
    assert len(_tasks(diagram)) == 2


def test_no_sub_steps_means_no_diagram():
    assert grounding.ground_diagram(_reply(), _profile(substeps=[])) is None
    assert grounding.linear_diagram(_profile(substeps=[])) is None


def test_ground_diagram_does_not_mutate_its_input():
    reply = _reply()
    before = copy.deepcopy(reply)
    ground_diagram(reply, _profile())
    assert reply == before


# --- the linear map (AC-18.35) ---------------------------------------------


def test_linear_diagram_is_start_then_each_step_then_end():
    diagram = linear_diagram(_profile())
    assert diagram.simplified is True
    ordered = ["start"] + [t.id for t in _tasks(diagram)] + ["end"]
    assert _edges(diagram) == set(zip(ordered, ordered[1:], strict=False))
    assert diagram.lanes == ["AP Specialist"]


def test_linear_diagram_puts_steps_without_an_owner_in_an_other_lane():
    profile = _profile(substeps=[{"name": "A", "owner": ""}, {"name": "B", "owner": "Clerk"}])
    diagram = linear_diagram(profile)
    assert diagram.lanes == ["Other", "Clerk"]


def test_linear_diagram_caps_the_number_of_lanes():
    substeps = [{"name": f"S{i}", "owner": f"Role {i}"} for i in range(12)]
    diagram = linear_diagram(_profile(substeps=substeps))
    assert len(diagram.lanes) <= 9  # 8 roles + "Other"
    assert len(_tasks(diagram)) == 12


# --- markers: task type, event trigger, gateway type (AC-18.23) ------------


def _profile_with_systems(**overrides):
    """Like `_profile`, but step 1 has a system on record (so `user`-type
    markers are not downgraded) and step 2 has none (so they are)."""
    process = {
        "trigger": "Invoice fails the three-way match",
        "end_result": "Invoice posted and paid",
        "substeps": [
            {
                "name": "Triage the exception",
                "owner": "AP Specialist",
                "roles": [{"role": "Buyer"}],
                "systems": ["SAP MM"],
            },
            {"name": "Correct and post", "owner": "AP Specialist", "roles": [], "systems": []},
        ],
        "process_owner": {"role": "AP Team Lead"},
    }
    process.update(overrides)
    return {"process": process}


def test_a_legal_task_marker_is_kept_when_the_step_has_a_system():
    reply = _reply()
    reply["nodes"][1]["marker"] = "service"
    diagram = ground_diagram(reply, _profile_with_systems())
    assert _by_id(diagram)["t1"].marker == "service"


def test_a_system_dependent_task_marker_is_downgraded_without_a_system():
    reply = _reply()
    reply["nodes"][3]["marker"] = "user"  # step 2 has no systems in _profile_with_systems
    diagram = ground_diagram(reply, _profile_with_systems())
    assert _by_id(diagram)["t2"].marker == "manual"


def test_manual_is_always_legal_even_with_a_system():
    reply = _reply()
    reply["nodes"][1]["marker"] = "manual"
    diagram = ground_diagram(reply, _profile_with_systems())
    assert _by_id(diagram)["t1"].marker == "manual"


def test_an_unknown_task_marker_falls_back_to_none():
    reply = _reply()
    reply["nodes"][1]["marker"] = "carrier_pigeon"
    diagram = ground_diagram(reply, _profile_with_systems())
    assert _by_id(diagram)["t1"].marker == "none"


def test_a_gateway_marker_is_taken_from_the_reply():
    reply = _reply()
    reply["nodes"][2]["marker"] = "parallel"
    diagram = ground_diagram(reply, _profile())
    assert _by_id(diagram)["g1"].marker == "parallel"


def test_a_gateway_marker_is_never_none_and_defaults_to_exclusive():
    for bad_marker in (None, "none", "carrier_pigeon", "user"):
        reply = _reply()
        reply["nodes"][2]["marker"] = bad_marker
        diagram = ground_diagram(reply, _profile())
        assert _by_id(diagram)["g1"].marker == "exclusive"


def test_start_and_end_markers_are_taken_from_the_reply():
    reply = _reply()
    reply["nodes"][0]["marker"] = "timer"
    reply["nodes"][4]["marker"] = "terminate"
    diagram = ground_diagram(reply, _profile())
    nodes = _by_id(diagram)
    assert (nodes["start"].marker, nodes["end"].marker) == ("timer", "terminate")


def test_an_end_only_marker_on_a_start_falls_back_to_none():
    reply = _reply()
    reply["nodes"][0]["marker"] = "terminate"  # valid for end, not for start
    diagram = ground_diagram(reply, _profile())
    assert _by_id(diagram)["start"].marker == "none"


def test_synthetic_start_and_end_get_the_plain_marker():
    reply = _reply()
    reply["nodes"] = [n for n in reply["nodes"] if n["type"] not in ("start", "end")]
    reply["flows"] = [f for f in reply["flows"] if f["source"] != "start" and f["target"] != "end"]
    diagram = ground_diagram(reply, _profile())
    starts = [n for n in diagram.nodes if n.type == "start"]
    ends = [n for n in diagram.nodes if n.type == "end"]
    assert all(n.marker == "none" for n in starts + ends)


def test_linear_diagram_marks_a_step_with_a_system_as_user_and_without_as_manual():
    diagram = linear_diagram(_profile_with_systems())
    tasks = {t.step_index: t.marker for t in _tasks(diagram)}
    assert tasks == {1: "user", 2: "manual"}


# --- default flow (AC-18.24) -------------------------------------------------


def test_a_default_flow_leaving_a_gateway_is_kept():
    reply = _reply()
    reply["flows"][2]["is_default"] = True  # g1 -> t2, "yes"
    diagram = ground_diagram(reply, _profile())
    defaults = [(f.source, f.target) for f in diagram.flows if f.is_default]
    assert defaults == [("g1", "t2")]


def test_only_one_default_flow_survives_per_gateway():
    reply = _reply()
    reply["flows"][2]["is_default"] = True  # g1 -> t2
    reply["flows"][3]["is_default"] = True  # g1 -> t1 (also claims default)
    diagram = ground_diagram(reply, _profile())
    defaults = [(f.source, f.target) for f in diagram.flows if f.is_default]
    assert defaults == [("g1", "t2")]  # first one wins


def test_a_default_flow_not_leaving_a_gateway_is_rejected():
    reply = _reply()
    reply["flows"][0]["is_default"] = True  # start -> t1: not a gateway
    diagram = ground_diagram(reply, _profile())
    assert not any(f.is_default for f in diagram.flows)


def test_non_boolean_is_default_is_treated_as_false():
    reply = _reply()
    reply["flows"][2]["is_default"] = "true"  # a string, not a bool
    diagram = ground_diagram(reply, _profile())
    assert not any(f.is_default for f in diagram.flows)


def test_repair_added_flows_are_never_marked_default():
    reply = _reply()
    reply["flows"] = [f for f in reply["flows"] if f["target"] != "end"]  # t2 goes nowhere; repaired
    diagram = ground_diagram(reply, _profile())
    added = [f for f in diagram.flows if f.target == diagram.nodes[-1].id]
    assert added and not any(f.is_default for f in added)


# --- BPMN rules (AC-18.27 to AC-18.31) ---------------------------------------


def _flow(source, target, label="", is_default=False):
    return {"source": source, "target": target, "label": label, "is_default": is_default}


def _node(node_id, node_type, step=None, marker=None, label=""):
    node = {"id": node_id, "type": node_type, "label": label, "lane": 0, "step_index": step}
    if marker:
        node["marker"] = marker
    return node


def test_a_loop_back_into_a_task_gets_an_exclusive_merge():
    diagram = ground_diagram(_reply(), _profile())
    merge = _by_id(diagram)["merge"]
    assert merge.type == "gateway" and merge.marker == "exclusive"
    assert {("start", "merge"), ("g1", "merge"), ("merge", "t1")} <= _edges(diagram)
    assert ("g1", "t1") not in _edges(diagram)
    assert next(f.label for f in diagram.flows if (f.source, f.target) == ("g1", "merge")) == "no"


def test_a_skip_path_gets_a_merge_of_the_splits_type():
    reply = {
        "lanes": ["AP Specialist"],
        "nodes": [
            _node("start", "start"),
            _node("g1", "gateway", marker="exclusive", label="Needs triage?"),
            _node("t1", "task", 1),
            _node("t2", "task", 2),
            _node("end", "end"),
        ],
        "flows": [
            _flow("start", "g1"),
            _flow("g1", "t1", "yes"),
            _flow("g1", "t2", "no"),
            _flow("t1", "t2"),
            _flow("t2", "end"),
        ],
    }
    diagram = ground_diagram(reply, _profile())
    assert diagram.simplified is False
    assert _by_id(diagram)["merge"].marker == "exclusive"
    assert {("g1", "merge"), ("t1", "merge"), ("merge", "t2")} <= _edges(diagram)


def test_parallel_branches_meet_in_a_parallel_merge_before_the_end():
    reply = {
        "lanes": ["AP Specialist"],
        "nodes": [
            _node("start", "start"),
            _node("g1", "gateway", marker="parallel"),
            _node("t1", "task", 1),
            _node("t2", "task", 2),
            _node("end", "end"),
        ],
        "flows": [_flow("start", "g1"), _flow("g1", "t1"), _flow("g1", "t2"), _flow("t1", "end"), _flow("t2", "end")],
    }
    diagram = ground_diagram(reply, _profile())
    assert diagram.simplified is False  # parallel branches need no labels
    assert _by_id(diagram)["merge"].marker == "parallel"
    assert {("t1", "merge"), ("t2", "merge"), ("merge", "end")} <= _edges(diagram)


def test_a_gateway_that_merges_and_splits_gets_a_merge_in_front():
    reply = {
        "lanes": ["AP Specialist"],
        "nodes": [
            _node("start", "start"),
            _node("g1", "gateway", marker="exclusive", label="Complete?"),
            _node("t1", "task", 1),
            _node("t2", "task", 2),
            _node("end", "end"),
        ],
        "flows": [
            _flow("start", "g1"),
            _flow("g1", "t1", "no"),
            _flow("g1", "t2", "yes"),
            _flow("t1", "g1"),
            _flow("t2", "end"),
        ],
    }
    diagram = ground_diagram(reply, _profile())
    assert diagram.simplified is False
    assert _by_id(diagram)["merge"].marker == "exclusive"
    assert {("start", "merge"), ("t1", "merge"), ("merge", "g1")} <= _edges(diagram)
    assert sum(1 for f in diagram.flows if f.target == "g1") == 1


def test_a_pass_through_gateway_is_removed():
    reply = {
        "lanes": ["AP Specialist"],
        "nodes": [
            _node("start", "start"),
            _node("t1", "task", 1),
            _node("g1", "gateway", label="OK?"),
            _node("t2", "task", 2),
            _node("end", "end"),
        ],
        "flows": [_flow("start", "t1"), _flow("t1", "g1"), _flow("g1", "t2", "yes"), _flow("t2", "end")],
    }
    diagram = ground_diagram(reply, _profile())
    assert diagram.simplified is False
    assert "g1" not in _by_id(diagram)
    assert ("t1", "t2") in _edges(diagram)


def test_a_pass_through_gateway_that_would_loop_onto_itself_falls_back():
    reply = {
        "lanes": ["AP Specialist"],
        "nodes": [
            _node("start", "start"),
            _node("t1", "task", 1),
            _node("g1", "gateway", label="Again?"),
            _node("t2", "task", 2),
            _node("end", "end"),
        ],
        "flows": [_flow("start", "t1"), _flow("t1", "g1"), _flow("g1", "t1", "again"), _flow("t2", "end")],
    }
    assert ground_diagram(reply, _profile()).simplified is True


def test_a_task_with_two_outgoing_flows_falls_back():
    reply = _reply()
    reply["flows"] = [_flow("start", "t1"), _flow("t1", "t2"), _flow("t1", "end"), _flow("t2", "end")]
    assert ground_diagram(reply, _profile()).simplified is True


def test_an_unlabelled_decision_branch_falls_back():
    reply = _reply()
    reply["flows"][2]["label"] = ""  # g1 -> t2 had "yes"
    assert ground_diagram(reply, _profile()).simplified is True


def test_an_unlabelled_default_branch_is_allowed():
    reply = _reply()
    reply["flows"][2]["label"] = ""
    reply["flows"][2]["is_default"] = True
    assert ground_diagram(reply, _profile()).simplified is False


def test_a_trigger_marker_without_any_label_becomes_none():
    reply = _reply()
    reply["nodes"][0]["label"] = ""
    reply["nodes"][0]["marker"] = "timer"
    diagram = ground_diagram(reply, _profile(trigger=""))
    assert _by_id(diagram)["start"].marker == "none"


def test_a_trigger_marker_with_a_label_is_kept():
    reply = _reply()
    reply["nodes"][0]["marker"] = "timer"
    assert _by_id(ground_diagram(reply, _profile()))["start"].marker == "timer"


def test_too_many_nodes_after_repairs_falls_back(monkeypatch):
    monkeypatch.setattr(grounding, "MAX_NODES", 5)  # _reply has 5 nodes; the loop's merge makes 6
    assert ground_diagram(_reply(), _profile()).simplified is True


# --- merges and step order (AC-18.26, AC-18.27, AC-18.32) --------------------


def _profile4():
    return _profile(substeps=[{"name": f"Step {i}", "owner": "Clerk", "roles": []} for i in range(1, 5)])


def _reply4(nodes, flows):
    return {"lanes": ["Clerk"], "nodes": nodes, "flows": flows}


def test_a_merge_on_one_branch_does_not_break_the_step_order_check():
    # A rework loop re-enters branch t2 only; the merge inserted there must not
    # make t2 look "later" than its sibling branch t3.
    reply = _reply4(
        [
            _node("s", "start"),
            _node("t1", "task", 1),
            _node("g", "gateway", marker="exclusive", label="Ok?"),
            _node("t2", "task", 2),
            _node("t3", "task", 3),
            _node("t4", "task", 4),
            _node("d", "gateway", marker="exclusive", label="Fixed?"),
            _node("e", "end"),
        ],
        [
            _flow("s", "t1"),
            _flow("t1", "g"),
            _flow("g", "t2", "yes"),
            _flow("g", "t3", "no"),
            _flow("t2", "t4"),
            _flow("t3", "t4"),
            _flow("t4", "d"),
            _flow("d", "t2", "fix"),
            _flow("d", "e", "ok"),
        ],
    )
    diagram = ground_diagram(reply, _profile4())
    assert diagram.simplified is False
    assert _by_id(diagram)["merge"].marker == "exclusive"


def test_a_merge_in_front_of_a_parallel_split_is_exclusive_when_a_loop_comes_back():
    reply = _reply4(
        [
            _node("s", "start"),
            _node("t1", "task", 1),
            _node("g", "gateway", marker="parallel"),
            _node("t2", "task", 2),
            _node("t3", "task", 3),
            _node("j", "gateway", marker="parallel"),
            _node("t4", "task", 4),
            _node("d", "gateway", marker="exclusive", label="Done?"),
            _node("e", "end"),
        ],
        [
            _flow("s", "t1"),
            _flow("t1", "g"),
            _flow("g", "t2"),
            _flow("g", "t3"),
            _flow("t2", "j"),
            _flow("t3", "j"),
            _flow("j", "t4"),
            _flow("t4", "d"),
            _flow("d", "g", "rework"),
            _flow("d", "e", "ok"),
        ],
    )
    diagram = ground_diagram(reply, _profile4())
    assert diagram.simplified is False
    merge_into_g = next(n for n in diagram.nodes if n.type == "gateway" and (n.id, "g") in _edges(diagram))
    assert merge_into_g.marker == "exclusive"


def test_a_merge_in_front_of_a_parallel_split_is_exclusive_after_an_exclusive_split():
    reply = _reply4(
        [
            _node("s", "start"),
            _node("t1", "task", 1),
            _node("x", "gateway", marker="exclusive", label="Known?"),
            _node("t2", "task", 2),
            _node("g", "gateway", marker="parallel"),
            _node("t3", "task", 3),
            _node("t4", "task", 4),
            _node("e", "end"),
        ],
        [
            _flow("s", "t1"),
            _flow("t1", "x"),
            _flow("x", "g", "yes"),
            _flow("x", "t2", "no"),
            _flow("t2", "g"),
            _flow("g", "t3"),
            _flow("g", "t4"),
            _flow("t3", "e"),
            _flow("t4", "e"),
        ],
    )
    diagram = ground_diagram(reply, _profile4())
    assert diagram.simplified is False
    merge_into_g = next(n for n in diagram.nodes if n.type == "gateway" and (n.id, "g") in _edges(diagram))
    assert merge_into_g.marker == "exclusive"


def test_short_event_label_does_not_cut_inside_a_number():
    label = short_event_label("Invoice over 10.000 EUR received from a supplier by email")
    assert label.startswith("Invoice over 10.000 EUR")
    assert label.endswith("…")


# --- nested splits, pass-through labels, event labels (AC-18.27, AC-18.28, AC-18.32)


def test_a_merge_closing_an_outer_decision_is_exclusive_even_with_a_nested_parallel_fork():
    reply = _reply4(
        [
            _node("s", "start"),
            _node("t1", "task", 1),
            _node("x", "gateway", marker="exclusive", label="Known?"),
            _node("p", "gateway", marker="parallel"),
            _node("t2", "task", 2),
            _node("t3", "task", 3),
            _node("j", "gateway", marker="parallel"),
            _node("t4", "task", 4),
            _node("e", "end"),
        ],
        [
            _flow("s", "t1"),
            _flow("t1", "x"),
            _flow("x", "p", "yes"),
            _flow("x", "t4", "no"),
            _flow("p", "t2"),
            _flow("p", "t3"),
            _flow("t2", "j"),
            _flow("t3", "j"),
            _flow("j", "t4"),
            _flow("t4", "e"),
        ],
    )
    diagram = ground_diagram(reply, _profile4())
    assert diagram.simplified is False
    merge_into_t4 = next(n for n in diagram.nodes if n.type == "gateway" and (n.id, "t4") in _edges(diagram))
    assert merge_into_t4.marker == "exclusive"
    assert _by_id(diagram)["j"].marker == "parallel"  # the model's own join is untouched


def test_a_pass_through_gateway_hands_its_branch_label_to_the_surviving_flow():
    reply = _reply4(
        [
            _node("s", "start"),
            _node("t1", "task", 1),
            _node("g0", "gateway", marker="exclusive", label="Ok?"),
            _node("g1", "gateway", marker="exclusive", label="Fine?"),
            _node("t2", "task", 2),
            _node("t3", "task", 3),
            _node("t4", "task", 4),
            _node("e", "end"),
        ],
        [
            _flow("s", "t1"),
            _flow("t1", "g0"),
            _flow("g0", "g1"),
            _flow("g1", "t3", "yes"),
            _flow("g0", "t2", "no"),
            _flow("t2", "t4"),
            _flow("t3", "t4"),
            _flow("t4", "e"),
        ],
    )
    diagram = ground_diagram(reply, _profile4())
    assert diagram.simplified is False
    assert "g1" not in _by_id(diagram)
    assert next(f.label for f in diagram.flows if (f.source, f.target) == ("g0", "t3")) == "yes"


def test_short_event_label_does_not_cut_inside_a_thousands_separator_or_a_time():
    assert short_event_label("Invoice over 1,000 EUR received from a supplier").startswith("Invoice over 1,000 EUR")
    assert short_event_label("Payment at 09:30 is released by the bank each day").startswith("Payment at 09:30")


def test_short_event_label_drops_a_leading_when_and_capitalises():
    assert short_event_label("when the invoice is posted") == "The invoice is posted"
    assert short_event_label("once a customer places an order") == "A customer places an order"


def test_short_event_label_does_not_keep_a_two_word_fragment_as_the_clause():
    label = short_event_label("a corrected, posted invoice released for payment")
    assert label.startswith("A corrected, posted invoice")
    assert label.endswith("…") and len(label) <= 40


# --- the cost-review example and the rule codes (spec 18 §3.8) ----------------------------------------


def _cost_review():
    from tests.fixtures.assessment.profiles import load_profile

    return load_profile("eu")


def _map_reply():
    from tests.fixtures.assessment.replies import map_reply

    return map_reply()


def test_the_cost_review_reply_is_kept_with_its_loop_and_real_names():
    """AC-18.20, AC-18.22: §3.8 example; the invented "Finance Bot" lane is dropped."""
    profile = _cost_review()
    diagram = ground_diagram(_map_reply(), profile)
    assert diagram.simplified is False and diagram.fallback_rule == ""
    names = [s["name"] for s in profile["process"]["substeps"]]
    assert [t.label for t in _tasks(diagram)] == names
    assert diagram.lanes == ["Cost controller"]
    assert _by_id(diagram)["merge"].marker == "exclusive"
    assert {("g1", "merge"), ("start", "merge"), ("merge", "t1")} <= _edges(diagram)
    assert _by_id(diagram)["g1"].label == "Totals match SAP?"


@pytest.mark.parametrize("bad", [9, 0, -1, None, True, "3", 2.0, [1]], ids=repr)
def test_a_task_with_a_step_index_that_is_not_a_real_step_is_dropped(bad):
    """AC-18.21: invented, missing, bool, string and non-int step indexes never draw a task."""
    reply = _reply()
    reply["nodes"].insert(3, {"id": "tx", "type": "task", "label": "Extra", "lane": 0, "step_index": bad})
    diagram = ground_diagram(reply, _profile())
    assert "tx" not in _by_id(diagram) and diagram.simplified is False


def test_more_than_eight_reply_lanes_fold_into_other():
    """AC-18.22: lanes past eight share `Other`."""
    substeps = [{"name": f"S{i}", "owner": f"Role {i}"} for i in range(1, 11)]
    profile = _profile(substeps=substeps)
    reply = {
        "lanes": [f"Role {i}" for i in range(1, 11)],
        "nodes": [_node("s", "start")]
        + [{**_node(f"t{i}", "task", i), "lane": i - 1} for i in range(1, 11)]
        + [_node("e", "end")],
        "flows": [_flow("s", "t1")] + [_flow(f"t{i}", f"t{i + 1}") for i in range(1, 10)] + [_flow("t10", "e")],
    }
    diagram = ground_diagram(reply, profile)
    assert diagram.simplified is False
    assert diagram.lanes == [f"Role {i}" for i in range(1, 9)] + ["Other"]
    assert _by_id(diagram)["t10"].lane == "Other" and _by_id(diagram)["t9"].lane == "Other"
    assert all(n.lane in diagram.lanes for n in diagram.nodes)


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        (None, "G1"),
        (lambda r: r.update(nodes=[n for n in r["nodes"] if n["id"] != "t2"]), "G8"),
        (lambda r: r.update(flows=[_flow("start", "t2"), _flow("t2", "t1"), _flow("t1", "end")]), "G14"),
        (
            lambda r: r.update(flows=[_flow("start", "t1"), _flow("t1", "t2"), _flow("t1", "end"), _flow("t2", "end")]),
            "G16",
        ),
        (lambda r: r["flows"][2].update(label=""), "G17"),
    ],
    ids=["G1", "G8", "G14", "G16", "G17"],
)
def test_a_fallback_names_the_rule_that_forced_it(change, rule):
    """§3.9: the log carries the fallback rule; the linear map is drawn."""
    reply = None
    if change is not None:
        reply = _reply()
        change(reply)
    diagram = ground_diagram(reply, _profile())
    assert diagram.simplified is True and diagram.fallback_rule == rule


def test_an_exception_inside_grounding_falls_back(monkeypatch):
    """G24: a repair bug degrades to the linear map, never raises."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("bug")

    monkeypatch.setattr(grounding, "_apply_bpmn_rules", boom)
    diagram = ground_diagram(_reply(), _profile())
    assert diagram.simplified is True and diagram.fallback_rule == "G24"


def test_more_than_forty_nodes_in_the_reply_falls_back(monkeypatch):
    """AC-18.30 (G8): too many nodes before any repair."""
    reply = _reply()
    reply["nodes"] += [_node(f"g{i}", "gateway", label="?") for i in range(2, 40)]
    diagram = ground_diagram(reply, _profile())
    assert diagram.simplified is True and diagram.fallback_rule == "G8"


def test_every_node_lane_is_one_of_the_lanes():
    diagram = ground_diagram(_map_reply(), _cost_review())
    assert all(n.lane in diagram.lanes for n in diagram.nodes)
