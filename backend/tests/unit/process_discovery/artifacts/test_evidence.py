"""Tests for the quote check (spec 18 §3.3; AC-18.8, AC-18.9).

Why: "no quote, no claim" is only real if code refuses a paraphrase, a stitched quote or an invented
sentence while forgiving case, curly quotes, dash style and a trailing full stop. The quote check is
shared by OPPORTUNITIES, stay-human steps, LABEL and ASSESS_STEPS, so its rules are pinned here once.
Every key and value comes from the real producer (`profile_values`) over the cost-review fixture.
"""

from __future__ import annotations

import pytest

from app.services.process_discovery.artifacts.evidence import (
    EvidenceHit,
    find_evidence,
    normalise_quote,
    profile_values,
    restrict_to_step,
    restrict_to_step_or_process,
)
from tests.fixtures.assessment.profiles import load_profile

AT = "2026-11-19T10:00:00+00:00"


@pytest.fixture
def values():
    return profile_values(load_profile("eu"))


# --- the §3.3 table, row by row ---------------------------------------------------------------------


def test_a_quote_in_two_fields_hits_the_first_in_table_order(values):
    """§3.3 row 1: the business pain (P09) comes before the step-2 pain point."""
    hit = find_evidence('"I copy the numbers into the master file by hand"', values)
    assert hit == EvidenceHit("process.business_pain", "expert", "I copy the numbers into the master file by hand")


def test_a_substring_of_three_or_more_words_hits(values):
    """AC-18.8: substring of one value with at least three words."""
    hit = find_evidence("copy the numbers into the master file", values)
    assert hit is not None and hit.key == "process.business_pain"


def test_curly_quotes_and_a_full_stop_are_stripped(values):
    """AC-18.9: “…” and the trailing full stop do not stop a real quote."""
    hit = find_evidence("“some site managers answer only after three reminders.”", values)
    assert hit is not None
    assert hit.key == "process.substeps[4].pain_points"
    assert hit.quote == "some site managers answer only after three reminders"


def test_a_whole_short_value_hits(values):
    """AC-18.8: a one-word quote that is a whole value ("Outlook", step 1 systems)."""
    hit = find_evidence("Outlook", values)
    assert hit is not None and hit.key == "process.substeps[1].systems"


def test_a_two_word_fragment_misses(values):
    assert find_evidence("by hand", values) is None


@pytest.mark.parametrize("quote", ["sites send late … by hand", "sites send late ... by hand", "sites send late…"])
def test_a_stitched_quote_misses(values, quote):
    assert find_evidence(quote, values) is None


def test_an_invented_quote_misses(values):
    assert find_evidence("the system crashes every day", values) is None


# --- the other rules -----------------------------------------------------------------------------------


def test_a_quote_longer_than_400_characters_misses():
    long_text = " ".join(["word"] * 120)  # 599 characters
    values = [("process.business_pain", long_text, "expert")]
    assert find_evidence(long_text, values) is None
    assert find_evidence(long_text[:300], values) is not None


def test_a_passage_spanning_two_values_misses(values):
    """AC-18.8: the end of the trigger joined to the start of the end result is not one value."""
    assert find_evidence("completed in SAP A cost report", values) is None


def test_case_whitespace_dashes_and_zero_width_characters_are_ignored():
    """AC-18.9."""
    values = [("process.business_pain", "Totals – checked by hand", "expert")]
    assert find_evidence("TOTALS  -  checked​ by   hand", values) is not None
    assert find_evidence("totals — checked by hand!", values) is not None


def test_non_string_and_empty_quotes_miss(values):
    for quote in (None, 3, ["Outlook"], "", "  ", '""', "..."):
        assert find_evidence(quote, values) is None


def test_a_proposed_value_reports_the_document_source():
    """AC-18.9: a value read from a document is searched, with source `document`."""
    profile = load_profile("eu")
    profile["process"]["substeps"][2]["__meta"] = {
        "pain_points": {
            "source": "document",
            "status": "proposed",
            "documentId": "d1",
            "quote": "the threshold check is done by eye",
            "at": AT,
        },
    }
    hit = find_evidence("the threshold check is done by eye", profile_values(profile))
    assert hit is not None
    assert (hit.key, hit.source) == ("process.substeps[3].pain_points", "document")


def test_a_specialist_value_reports_the_specialist_source():
    profile = load_profile("eu")
    profile["__meta"] = {"process.trigger": {"source": "specialist", "status": "confirmed", "by": "s1", "at": AT}}
    hit = find_evidence("Month-end close is completed in SAP", profile_values(profile))
    assert hit is not None and (hit.key, hit.source) == ("process.trigger", "specialist")


def test_normalise_quote_folds_typography():
    assert normalise_quote("It’s “DONE” — Now") == 'it\'s "done" - now'


# --- what is searched ------------------------------------------------------------------------------------


def test_profile_values_cover_every_text_of_the_table():
    keys = {key for key, _, _ in profile_values(load_profile("eu"))}
    assert {
        "process.name",
        "process.trigger",
        "process.end_result",
        "process.value_at_end",
        "process.business_pain",
        "process.volume",
        "process.process_owner",
        "process.baseline_metric",
        "process.target_metric",
        "process.variation",
    } <= keys
    for leaf in (
        "name",
        "goal",
        "owner",
        "handover",
        "activities",
        "systems",
        "pain_points",
        "data",
        "effort",
        "roles",
        "exceptions",
    ):
        assert f"process.substeps[1].{leaf}" in keys
    assert "process.substeps[5].approvals" in keys
    assert not any(k.startswith(("department", "user_function", "region")) for k in keys)


def test_the_rules_or_judgement_words_are_a_step_value():
    """AC-18.8 (S13, short step walk): the expert's words behind "rules or judgement" are searched as
    a step value; the `kind` code word is not."""
    profile = load_profile("eu")
    step = profile["process"]["substeps"][2]
    step["decision_type"] = {"kind": "mix", "evidence": "the threshold is fixed but the questions are my call"}
    values = profile_values(profile)
    hit = find_evidence("the threshold is fixed but the questions are my call", restrict_to_step_or_process(values, 3))
    assert hit is not None and hit.key == "process.substeps[3].decision_type"
    assert ("process.substeps[3].decision_type", "mix", "expert") not in values


def test_none_rows_and_numbers_add_no_value():
    values = profile_values(load_profile("eu"))
    texts = [text for _, text, _ in values]
    assert "1" not in texts  # volume.count is a number
    assert "process.sensitive_data" not in {k for k, _, _ in values}  # only a none row
    assert "process.substeps[2].roles" not in {k for k, _, _ in values}


def test_restrict_to_step_keeps_only_that_step():
    values = profile_values(load_profile("eu"))
    step4 = restrict_to_step(values, 4)
    assert step4 and all(k.startswith("process.substeps[4].") for k, _, _ in step4)
    assert find_evidence("I copy the numbers into the master file by hand", restrict_to_step(values, 2)) is not None
    assert find_evidence("I copy the numbers into the master file by hand", restrict_to_step(values, 4)) is None


def test_restrict_to_step_or_process_puts_the_step_first_and_never_another_step():
    values = profile_values(load_profile("eu"))
    narrowed = restrict_to_step_or_process(values, 2)
    assert narrowed[0][0].startswith("process.substeps[2].")
    assert not any(
        k.startswith("process.substeps[") and not k.startswith("process.substeps[2].") for k, _, _ in narrowed
    )
    hit = find_evidence("I copy the numbers into the master file by hand", narrowed)
    assert hit is not None and hit.key == "process.substeps[2].pain_points"
    assert find_evidence("Month-end close is completed in SAP", narrowed) is not None


def test_ac_26_22_decision_criteria_words_are_step_evidence() -> None:
    """AC-26.22 (spec 26 §3.9): words copied from a step's S14 are that step's words."""
    from app.services.process_discovery.artifacts.evidence import find_evidence, profile_values, restrict_to_step

    profile = load_profile("eu")
    profile["process"]["substeps"][2]["decision_criteria"] = {
        "basis": "the hiring manager's must-haves and the job ad",
        "set_by": "Hiring manager",
        "written": "partly",
        "varies": "every hiring manager wants something different",
    }
    values = restrict_to_step(profile_values(profile), 3)
    for quote in ("the hiring manager's must-haves", "every hiring manager wants something different"):
        hit = find_evidence(quote, values)
        assert hit is not None and hit.key == "process.substeps[3].decision_criteria"
    partly = find_evidence("partly", values)  # `written` is a code word, never evidence
    assert partly is None or "decision_criteria" not in partly.key
