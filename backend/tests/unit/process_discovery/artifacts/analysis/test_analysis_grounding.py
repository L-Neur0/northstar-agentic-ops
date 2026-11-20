"""Tests for grounding the OPPORTUNITIES reply in the profile (spec 18 §3.5–3.6; AC-18.5 to AC-18.15, AC-18.17).

Why: the model can cite a step that does not exist, quote words nobody said, grade a change "very
high" or return fifty entries; none of that may reach the report. Each entry is checked on its own and
a bad one is dropped and counted, never fatal. These tests feed `ground_opportunities` the worked §3.5
reply and deliberately broken variants of it, on the cost-review fixture and the real NIG rates.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.models.process_discovery_schemas import Opportunity
from app.services.process_discovery.artifacts.analysis.analysis import carry_reviews, ground_opportunities
from app.services.process_discovery.artifacts.analysis.schemas import OpportunitiesOut
from tests.fixtures.assessment.profiles import load_profile, nig_config
from tests.fixtures.assessment.replies import opportunities_reply

RATES = nig_config().rates


def _ground(reply: Any):
    return ground_opportunities(reply, load_profile("eu"), RATES)


def _one(**overrides: Any) -> dict[str, Any]:
    entry = opportunities_reply()["opportunities"][0]
    entry.update(overrides)
    return entry


def _reply(*entries: dict[str, Any], **top: Any) -> dict[str, Any]:
    return {"summary": "s", "opportunities": list(entries), "stay_human": [], **top}


# --- the worked example ------------------------------------------------------------------------------


def test_the_worked_example_keeps_o1_to_o4():
    """AC-18.5."""
    result = _ground(opportunities_reply())
    rows = [(o.id, o.type.value, o.substeps, o.evidence_key) for o in result.opportunities]
    assert rows == [
        ("o1", "document_ai", [1, 2], "process.business_pain"),
        ("o2", "ai_assistant", [5], "process.substeps[5].pain_points"),
        ("o3", "workflow", [4], "process.substeps[4].pain_points"),
        ("o4", "standardise", [1], "process.variation"),
    ]
    assert result.dropped == {"step": 1, "quote": 1, "invalid": 0, "cap": 0}
    assert all(o.evidence_source == "expert" for o in result.opportunities)


def test_the_worked_example_keeps_the_stay_human_step():
    result = _ground(opportunities_reply())
    assert len(result.stay_human) == 1
    stay = result.stay_human[0]
    assert stay.substeps == [5] and stay.evidence == "write the commentary"
    assert stay.evidence_key.startswith("process.substeps[5].")


def test_a_wire_model_reply_is_grounded_the_same_way():
    reply = OpportunitiesOut.model_validate(opportunities_reply())
    assert _ground(reply) == _ground(opportunities_reply())


# --- steps (O2) --------------------------------------------------------------------------------------


@pytest.mark.parametrize("steps", [[0], [6], [-1], [1, 9], [True], ["1"], [1.5], [None], "1", None, {"a": 1}])
def test_any_step_outside_the_profile_drops_the_opportunity(steps):
    """AC-18.6: an invented step is an invented claim, so the whole opportunity goes."""
    result = _ground(_reply(_one(steps=steps)))
    assert result.opportunities == [] and result.dropped["step"] == 1


def test_an_empty_step_list_is_the_whole_process():
    """AC-18.6."""
    result = _ground(_reply(_one(steps=[])))
    assert result.opportunities[0].substeps == []


def test_duplicate_steps_are_removed_and_sorted():
    """AC-18.6."""
    assert _ground(_reply(_one(steps=[2, 1, 2]))).opportunities[0].substeps == [1, 2]


# --- evidence (O7) -----------------------------------------------------------------------------------


@pytest.mark.parametrize("evidence", ["the system crashes every day", "by hand", "sites send late … by hand", "", None])
def test_an_unverified_quote_drops_the_opportunity_whatever_its_grades(evidence):
    """AC-18.7."""
    result = _ground(_reply(_one(evidence=evidence, impact="high", feasibility="high")))
    assert result.opportunities == [] and result.dropped["quote"] == 1


def test_the_stored_evidence_is_the_quote_with_its_edges_stripped():
    result = _ground(_reply(_one(evidence="“I copy the numbers into the master file by hand.”")))
    assert result.opportunities[0].evidence == "I copy the numbers into the master file by hand"


# --- invalid entries (O3–O6) --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"type": "decision_support"},
        {"type": None},
        {"title": ""},
        {"title": "   \n\t "},
        {"title": ["list"]},
        {"what_changes": ""},
        {"how": None},
        {"impact": "very high"},
        {"feasibility": "HIGH"},
        {"impact": None},
    ],
    ids=repr,
)
def test_an_invalid_entry_is_dropped_and_the_others_survive(overrides):
    """AC-18.10: one bad entry never drops the others."""
    result = _ground(_reply(_one(**overrides), _one(title="Good one")))
    assert [o.title for o in result.opportunities] == ["Good one"]
    assert result.dropped == {"step": 0, "quote": 0, "invalid": 1, "cap": 0}


@pytest.mark.parametrize("garbage", ["not an object", 7, None, ["x"]])
def test_an_entry_that_is_not_an_object_is_invalid(garbage):
    result = _ground(_reply(garbage, _one()))
    assert len(result.opportunities) == 1 and result.dropped["invalid"] == 1


@pytest.mark.parametrize("reply", [{}, {"opportunities": "x", "stay_human": 3, "summary": 5}, None, "text"])
def test_a_malformed_reply_gives_an_empty_result_not_an_error(reply):
    result = _ground(reply)
    assert result.opportunities == [] and result.stay_human == [] and result.summary == ""


# --- caps and cleaning (O1, O4, O5, O8) ---------------------------------------------------------------


def test_long_texts_are_capped_with_an_ellipsis():
    """AC-18.11."""
    entry = _one(
        title="t" * 500,
        what_changes="w" * 5000,
        how="h" * 5000,
        prepare_first="p" * 5000,
        impact_reason="i" * 5000,
        feasibility_reason="f" * 5000,
    )
    result = _ground(_reply(entry, summary="s" * 5000))
    o = result.opportunities[0]
    assert len(o.title) == 200 and o.title.endswith("…")
    for text in (o.what_changes, o.how, o.prepare_first, o.impact_reason, o.feasibility_reason, result.summary):
        assert len(text) == 1500 and text.endswith("…")


def test_the_title_is_cleaned_to_one_line():
    o = _ground(_reply(_one(title="Read\x00 the\n\nsite   files"))).opportunities[0]
    assert o.title == "Read the site files"


@pytest.mark.parametrize("summary", [None, 3, {"text": "nested"}, ["a"]])
def test_a_non_string_summary_becomes_empty(summary):
    """AC-18.11."""
    assert _ground(_reply(_one(), summary=summary)).summary == ""


def test_more_than_twelve_grounded_opportunities_keep_the_first_twelve():
    """AC-18.12."""
    result = _ground(_reply(*[_one(title=f"O{i}") for i in range(15)]))
    assert [o.title for o in result.opportunities] == [f"O{i}" for i in range(12)]
    assert result.dropped["cap"] == 3


def test_only_the_first_fifty_raw_entries_are_read():
    """AC-18.12: entry 51 is good but never read."""
    entries = [_one(steps=[9])] * 50 + [_one(title="Late")]
    result = _ground(_reply(*entries))
    assert result.opportunities == []
    assert result.dropped == {"step": 50, "quote": 0, "invalid": 0, "cap": 1}


# --- what code sets (O9) ------------------------------------------------------------------------------


def test_code_sets_ids_review_share_and_blocked_by():
    """AC-18.13."""
    result = _ground(opportunities_reply())
    assert [o.id for o in result.opportunities] == ["o1", "o2", "o3", "o4"]
    assert all(o.review == "pending" and o.review_note == "" and o.blocked_by == [] for o in result.opportunities)
    assert [o.saving_share for o in result.opportunities] == [
        RATES.saving_share[o.type.value] for o in result.opportunities
    ]


# --- stay human -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"steps": []}, "step"),
        ({"steps": [8]}, "step"),
        ({"steps": [True]}, "step"),
        ({"reason": ""}, "invalid"),
        ({"reason": None}, "invalid"),
        ({"evidence": "a person must always decide"}, "quote"),
    ],
)
def test_a_bad_stay_human_entry_is_dropped(overrides, reason):
    """AC-18.14."""
    entry = {**opportunities_reply()["stay_human"][0], **overrides}
    result = _ground(_reply(stay_human=[entry]))
    assert result.stay_human == [] and result.dropped[reason] == 1


def test_at_most_six_stay_human_entries_are_kept():
    """AC-18.14."""
    entry = opportunities_reply()["stay_human"][0]
    result = _ground(_reply(stay_human=[entry] * 8))
    assert len(result.stay_human) == 6


def test_a_stay_human_reason_is_capped_at_600():
    entry = {**opportunities_reply()["stay_human"][0], "reason": "r" * 900}
    reason = _ground(_reply(stay_human=[entry])).stay_human[0].reason
    assert len(reason) == 600 and reason.endswith("…")


def test_an_empty_list_with_a_summary_is_a_valid_result():
    """AC-18.15."""
    result = _ground(_reply(summary="Nothing in the profile supports an automation."))
    assert result.opportunities == [] and result.summary.startswith("Nothing")


# --- carry_reviews (§3.6) -------------------------------------------------------------------------------


def _opp(oid: str, kind: str, steps: list[int], **extra: Any) -> Opportunity:
    return Opportunity(id=oid, title=oid, type=kind, substeps=steps, impact="high", feasibility="high", **extra)  # pyright: ignore[reportArgumentType]


def test_carry_reviews_copies_review_note_and_adjusted_share():
    """AC-18.17."""
    old = [
        _opp("o1", "workflow", [4], review="adjusted", review_note="fewer sites", saving_share=0.1),
        _opp("o2", "document_ai", [1, 2], review="accepted", review_note="ok", saving_share=0.3),
    ]
    new = [_opp("o1", "document_ai", [2, 1], saving_share=0.6), _opp("o2", "workflow", [4], saving_share=0.4)]
    out = carry_reviews(old, new)
    assert [(o.review, o.review_note, o.saving_share) for o in out] == [
        ("accepted", "ok", 0.6),  # not adjusted: the share stays the configured one
        ("adjusted", "fewer sites", 0.1),
    ]


def test_carry_reviews_uses_each_old_opportunity_once_and_leaves_others_pending():
    """AC-18.17."""
    old = [_opp("o1", "workflow", [4], review="rejected", review_note="no")]
    new = [_opp("o1", "workflow", [4]), _opp("o2", "workflow", [4]), _opp("o3", "workflow", [3])]
    assert [o.review for o in carry_reviews(old, new)] == ["rejected", "pending", "pending"]
