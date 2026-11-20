"""Tests for the two assessment fingerprints (spec 18 §3.10, AC-18.18).

Why: a fingerprint that misses a change leaves the report out of date, and one that moves on a
confirmation re-runs paid calls and throws away specialist reviews for nothing. Each test changes one
thing in the cost-review fixture and checks which fingerprint moves. Absent and empty values must
hash the same, because a stored profile and a seeded one are the same profile.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.services.process_discovery.artifacts.fingerprint import ai_input_fingerprint, map_fingerprint
from tests.fixtures.assessment.profiles import load_profile

AT = "2026-11-19T10:00:00+00:00"

Edit = Callable[[dict[str, Any]], None]


def _set(path: str, value: Any) -> Edit:
    def edit(profile: dict[str, Any]) -> None:
        *parents, leaf = path.split("/")
        node: Any = profile
        for part in parents:
            node = node[int(part)] if part.isdigit() else node[part]
        node[int(leaf) if leaf.isdigit() else leaf] = value

    return edit


def _changed(fingerprint: Callable[[dict[str, Any]], str], edit: Edit) -> bool:
    before = load_profile("eu")
    after = load_profile("eu")
    edit(after)
    return fingerprint(before) != fingerprint(after)


S = "process/substeps"

AI_MOVES = {
    "pain point": _set(f"{S}/1/pain_points", ["something else"]),
    "effort": _set(f"{S}/0/effort", {"duration": "2 hours", "frequency": "every month"}),
    "P14 variation": _set("process/variation", {"same": "yes", "differences": ""}),
    "business pain": _set("process/business_pain", "new pain"),
    "step goal": _set(f"{S}/2/goal", "another goal"),
}
AI_STAYS = {
    "__meta": _set("__meta", {"process.trigger": {"source": "specialist", "status": "confirmed", "by": "s", "at": AT}}),
    "step __meta": _set(
        f"{S}/0/__meta", {"name": {"source": "specialist", "status": "confirmed", "by": "s", "at": AT}}
    ),
    "__skipped": _set(f"{S}/0/__skipped", ["goal"]),
    "a flag": _set("process/roles_confirmed", False),
    "P01 department": _set("department", "Controlling"),
    "P05 cluster": _set("process/cluster", {"code": "IT", "name": "IT", "decided_by": "expert"}),
    "roll-up": _set("process/all_tools", []),
}
MAP_MOVES = {
    "step name": _set(f"{S}/0/name", "Collect files"),
    "owner": _set(f"{S}/0/owner", "Site controller"),
    "role": _set(f"{S}/3/roles", [{"role": "Plant manager", "contribution": ""}]),
    "system": _set(f"{S}/2/systems", ["Power BI"]),
    "input": _set(f"{S}/2/data", {"inputs": ["budget"], "outputs": ["list of variances"]}),
    "output": _set(f"{S}/2/data", {"inputs": ["consolidated cost file", "budget"], "outputs": ["chart"]}),
    "approval": _set(f"{S}/4/approvals", [{"approver_role": "CFO", "waiting_time": "1 day"}]),
    "exception": _set(f"{S}/1/exceptions", [{"description": "totals differ", "loops_back_to": 1}]),
    "loop target": _set(f"{S}/1/exceptions", [{"description": "totals do not match SAP", "loops_back_to": 2}]),
    "trigger": _set("process/trigger", "Day 3 after close"),
}
MAP_STAYS = {
    "pain point": AI_MOVES["pain point"],
    "effort": AI_MOVES["effort"],
    "approval waiting time": _set(
        f"{S}/4/approvals", [{"approver_role": "Head of Controlling", "waiting_time": "2 days"}]
    ),
    "__meta": AI_STAYS["__meta"],
}


@pytest.mark.parametrize("edit", AI_MOVES.values(), ids=AI_MOVES.keys())
def test_ai_input_fingerprint_moves_with_what_the_calls_read(edit):
    assert _changed(ai_input_fingerprint, edit)


@pytest.mark.parametrize("edit", AI_STAYS.values(), ids=AI_STAYS.keys())
def test_ai_input_fingerprint_ignores_meta_flags_and_context(edit):
    assert not _changed(ai_input_fingerprint, edit)


@pytest.mark.parametrize("edit", MAP_MOVES.values(), ids=MAP_MOVES.keys())
def test_map_fingerprint_moves_with_what_the_map_is_drawn_from(edit):
    assert _changed(map_fingerprint, edit)


@pytest.mark.parametrize("edit", MAP_STAYS.values(), ids=MAP_STAYS.keys())
def test_map_fingerprint_ignores_pain_and_effort(edit):
    assert not _changed(map_fingerprint, edit)


def test_absent_and_empty_values_hash_the_same():
    full = load_profile("eu")
    sparse = load_profile("eu")
    del sparse["process"]["substeps"][0]["handover"]
    full["process"]["substeps"][0]["handover"] = ""
    del sparse["process"]["target_metric"]
    full["process"]["target_metric"] = {"value": "", "unit": ""}
    assert ai_input_fingerprint(full) == ai_input_fingerprint(sparse)
    assert map_fingerprint(full) == map_fingerprint(sparse)


def test_fingerprints_are_sha256_hex_and_stable():
    profile = load_profile("eu")
    assert len(ai_input_fingerprint(profile)) == 64 and len(map_fingerprint(profile)) == 64
    assert ai_input_fingerprint(profile) == ai_input_fingerprint(load_profile("eu"))
