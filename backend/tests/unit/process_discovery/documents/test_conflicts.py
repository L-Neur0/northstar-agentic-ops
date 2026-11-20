"""Tests for document conflicts (spec 17 §3.21): a differing value is kept and asked, never dropped or written.

Why: in the live check the expert said "a cost report" for step 3's outputs and the site report said
more; code dropped the file's value and told the expert "found nothing new". Now a differing value is
recorded as a conflict the expert decides, a list from two files is merged, the same meaning in other
words ("monthly" / "every month") is never a conflict, and a specialist's value still wins silently.
What: AC-17.70 to AC-17.75, AC-17.79 to AC-17.81 through `read_document`, `build_diff` and
`apply_proposals`, on worked example 5 (the monthly cost review).
Must not: call a real model (scripted `FakeLLM` replies only). Spec 17 §3.21.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from app.services.process_discovery.documents.context import ReadingContext, reading_context
from app.services.process_discovery.documents.filter import build_diff
from app.services.process_discovery.documents.pipeline import read_document
from app.services.process_discovery.documents.schema import read_document_model
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.llm import CallType
from app.services.process_discovery.profile.proposals import (
    ConflictOffer,
    FieldProposal,
    ProposalDiff,
    apply_proposals,
)
from app.services.process_discovery.profile.shapes import meta_for, rows_of, stored_value

from .helpers import AT, SITE_STEPS, expert_steps, procedure_profile, site_reply, site_session, specialist, write

DATA = "process.substeps[3].data"
EFFORT = "process.substeps[4].effort"
SYSTEMS = "process.substeps[4].systems"
HEADER = "Site | Cost centre | Budget | Actual | Variance | Comment"
DESCRIPTION = "Excel cost report per site with variance comments, one tab per site"
SLIDES = "Review: weekly, in Excel. The trigger is the month end close is completed."


def meta_of(profile, key):
    """The meta entry, which these tests expect to exist."""
    meta = meta_for(profile, key)
    assert meta is not None
    return meta


def example_5(vocab) -> dict[str, Any]:
    """Worked example 5's state: expert outputs "a cost report"; d1 proposed step 4 effort and systems."""
    profile = expert_steps(vocab, procedure_profile(vocab), SITE_STEPS)
    profile = write(vocab, profile, {DATA: {"outputs": ["a cost report"]}})
    d1 = ProposalDiff(
        "d1",
        step_cells=(
            FieldProposal(EFFORT, {"duration": "2 hours", "frequency": "monthly"}, "takes 2 hours every month"),
            FieldProposal(SYSTEMS, ["Ledger system"], "in the ledger system"),
        ),
    )
    return apply_proposals(profile, d1, vocab=vocab, at=AT).profile


def slides_reading(vocab, profile, *, frequency: str | None = "weekly", systems=("Excel",), text=SLIDES):
    """Upload B: `review_slides.pptx` (d3), whole process, offers step 4 effort and systems."""
    step: dict[str, Any] = {"name": {"value": "Review", "quote": "Review"}}
    if frequency:
        step["effort"] = {"duration": None, "frequency": frequency, "quote": "Review"}
    if systems:
        step["systems"] = [{"value": s, "quote": "in Excel"} for s in systems]
    raw = read_document_model().model_validate({"document_role": "whole_process", "steps": [step]})
    return build_diff(raw, document_id="d3", text=text, profile=profile, vocab=vocab, name="review_slides.pptx")


async def upload_a(vocab, docs_config, fixture_bytes, profile):
    session = site_session(vocab, profile)
    llm = FakeLLM({CallType.READ_DOCUMENT: [site_reply()]})
    return await read_document(
        session,
        filename="site_report_march.xlsx",
        data=fixture_bytes("site_report_march.xlsx"),
        llm=llm,
        config=docs_config,
        document_id="d2",
        now=AT,
        vocab=vocab,
        context=reading_context(session, vocab=vocab),
    )


async def test_ac_17_70_worked_example_5_upload_a(vocab, docs_config, fixture_bytes):
    profile = example_5(vocab)
    result = await upload_a(vocab, docs_config, fixture_bytes, profile)
    assert result.diff.step_cells == () and result.diff.fields == ()
    assert result.diff.conflicts == (ConflictOffer(DATA, "outputs", [DESCRIPTION], HEADER),)
    before_value, before_meta = stored_value(profile, DATA), meta_of(profile, DATA)
    written = apply_proposals(profile, result.diff, vocab=vocab, at=AT)
    assert written.conflicts == ("process.substeps[3].data.outputs",)
    row = rows_of(written.profile)[2]
    assert row["__conflicts"]["data"] == [
        {
            "sub": "outputs",
            "kind": "expert",
            "holderDocumentId": None,
            "value": [DESCRIPTION],
            "documentId": "d2",
            "quote": HEADER,
            "fromImage": False,
            "list": True,
            "status": "open",
            "at": AT,
        }
    ]
    assert stored_value(written.profile, DATA) == before_value
    assert meta_of(written.profile, DATA) == before_meta
    report = result.report.model_dump(by_alias=True)
    assert report["conflicts"] == 1
    assert "conflicts_with_expert" not in {s["reason"] for s in report["skipped"]}
    assert report["message"] == (
        'I read "site_report_march.xlsx". It differs from what I have in 1 place; I\'ll ask you which to keep.'
    )


def test_ac_17_71_same_or_covered_is_not_a_conflict(vocab):
    profile = expert_steps(vocab, procedure_profile(vocab), SITE_STEPS)
    profile = write(vocab, profile, {DATA: {"outputs": [DESCRIPTION.upper() + "."]}})
    raw = read_document_model().model_validate(
        {
            "document_role": "step_output_example",
            "target_step": 3,
            "target_named_by": "focus",
            "file_description": {"value": DESCRIPTION, "quote": HEADER},
        }
    )
    context = ReadingContext(phase="steps", focus_step=3, step_names=tuple(SITE_STEPS))
    out = build_diff(raw, document_id="d2", text=HEADER, profile=profile, vocab=vocab, context=context, name="r.xlsx")
    assert out.diff.conflicts == () and out.diff.step_cells == ()
    assert (DATA, "same_value") in {(s.key, s.reason) for s in out.skipped}
    systems = write(vocab, profile, {SYSTEMS: ["Ledger system", "Excel"]})
    out = slides_reading(vocab, systems, frequency=None, systems=("excel",))
    assert out.diff.conflicts == ()
    assert (SYSTEMS, "same_value") in {(s.key, s.reason) for s in out.skipped}


def test_ac_17_72_partly_answered_object_gives_a_proposal_and_a_conflict(vocab):
    profile = write(vocab, procedure_profile(vocab), {"process.volume": {"count": 14}})
    raw = read_document_model().model_validate(
        {
            "document_role": "whole_process",
            "volume": {"count": 12, "period": "month", "raw": None, "quote": "every month"},
        }
    )
    out = build_diff(raw, document_id="d1", text="It runs every month.", profile=profile, vocab=vocab)
    [field] = out.diff.fields
    assert (field.key, field.value["count"], field.value["period"]) == ("process.volume", 14, "month")
    assert out.diff.conflicts == (ConflictOffer("process.volume", "count", 12, "every month"),)
    written = apply_proposals(profile, out.diff, vocab=vocab, at=AT).profile
    assert meta_of(written, "process.volume")["replaces"]["value"]["count"] == 14
    assert written["__conflicts"]["process.volume"][0]["sub"] == "count"


def test_ac_17_73_worked_example_5_upload_b(vocab):
    profile = example_5(vocab)
    out = slides_reading(vocab, profile)
    assert out.diff.conflicts == (ConflictOffer(EFFORT, "frequency", "weekly", "Review"),)
    written = apply_proposals(profile, out.diff, vocab=vocab, at=AT).profile
    [record] = rows_of(written)[3]["__conflicts"]["effort"]
    assert (record["kind"], record["holderDocumentId"], record["value"]) == ("document", "d1", "weekly")
    assert stored_value(written, EFFORT) == {"duration": "2 hours", "frequency": "monthly"}
    assert stored_value(written, SYSTEMS) == ["Ledger system", "Excel"]
    meta = meta_of(written, SYSTEMS)
    assert meta["status"] == "proposed"
    assert [(p["item"], p["documentId"]) for p in meta["parts"]] == [("Ledger system", "d1"), ("Excel", "d3")]
    assert "systems" not in rows_of(written)[3].get("__conflicts", {})


def test_ac_17_74_specialist_and_none_row(vocab):
    profile = expert_steps(vocab, procedure_profile(vocab), SITE_STEPS)
    profile = specialist(vocab, profile, SYSTEMS, ["SAP"])
    out = slides_reading(vocab, profile, frequency=None)
    assert out.diff.conflicts == ()
    assert (SYSTEMS, "specialist_owned") in {(s.key, s.reason) for s in out.skipped}
    approvals = "process.substeps[2].approvals"
    profile = write(vocab, profile, {approvals: [{"none": True}]})
    raw = read_document_model().model_validate(
        {
            "document_role": "whole_process",
            "steps": [
                {
                    "name": {"value": "Compare with budget", "quote": "Compare with budget"},
                    "approvals": [
                        {"approver_role": "Controller", "waiting_time": None, "quote": "Compare with budget"}
                    ],
                }
            ],
        }
    )
    out = build_diff(raw, document_id="d1", text="Compare with budget", profile=profile, vocab=vocab)
    [conflict] = out.diff.conflicts
    written = apply_proposals(profile, out.diff, vocab=vocab, at=AT).profile
    assert conflict.key == approvals
    assert rows_of(written)[1]["__conflicts"]["approvals"][0]["list"] is False


def test_ac_17_75_limits(vocab):
    profile = write(
        vocab,
        procedure_profile(vocab),
        {
            "process.trigger": "A1",
            "process.end_result": "B1",
            "process.value_at_end": "C1",
            "process.business_pain": "D1",
            "process.target_metric": {"value": "E1", "unit": "F1"},
            "process.variation": {"same": "G1", "differences": "H1"},
        },
    )
    text = "trigger end result value pain target variation"
    reply = {
        "trigger": {"value": "A2", "quote": "trigger"},
        "end_result": {"value": "B2", "quote": "end result"},
        "value_at_end": {"value": "C2", "quote": "value"},
        "business_pain": {"value": "D2", "quote": "pain"},
        "target_metric": {"value": "E2", "unit": "F2", "quote": "target"},
        "variation": {"same": "G2", "differences": "H1", "quote": "variation"},
    }
    raw = read_document_model().model_validate({"document_role": "whole_process", **reply})
    out = build_diff(raw, document_id="d2", text=text, profile=profile, vocab=vocab)
    assert [(c.key, c.sub) for c in out.diff.conflicts] == [
        ("process.trigger", None),
        ("process.end_result", None),
        ("process.value_at_end", None),
        ("process.business_pain", None),
        ("process.target_metric", "value"),
        ("process.target_metric", "unit"),
    ]
    assert ("process.variation", "too_many_conflicts") in {(s.key, s.reason) for s in out.skipped}
    bad = read_document_model().model_validate(
        {"document_role": "whole_process", "trigger": {"value": "A3", "quote": "not in the text at all"}}
    )
    out = build_diff(bad, document_id="d3", text=text, profile=profile, vocab=vocab)
    assert out.diff.conflicts == ()
    assert ("process.trigger", "quote_not_found") in {(s.key, s.reason) for s in out.skipped}
    offer = ProposalDiff("d2", conflicts=(ConflictOffer("process.trigger", None, "A2", "q"),))
    first = apply_proposals(profile, offer, vocab=vocab, at=AT)
    second = apply_proposals(
        first.profile,
        ProposalDiff("d4", conflicts=(ConflictOffer("process.trigger", None, "A4", "q4"),)),
        vocab=vocab,
        at="2026-11-20T10:00:00+00:00",
    )
    [record] = second.profile["__conflicts"]["process.trigger"]
    assert (record["documentId"], record["value"], record["at"]) == ("d4", "A4", "2026-11-20T10:00:00+00:00")


async def test_ac_17_79_log_counts_conflicts_never_values(vocab, docs_config, fixture_bytes, caplog):
    caplog.set_level(logging.INFO)
    await upload_a(vocab, docs_config, fixture_bytes, example_5(vocab))
    [line] = [r for r in caplog.records if r.getMessage() == "document_read"]
    assert line.__dict__["conflicts"] == 1
    for record in caplog.records:
        assert "variance comments" not in str(record.__dict__)


@pytest.mark.parametrize(
    ("key", "stored", "offered"),
    [
        (EFFORT, {"frequency": "monthly"}, {"frequency": "every month"}),
        (EFFORT, {"frequency": "monthly"}, {"frequency": "1 per month"}),
        (EFFORT, {"frequency": "monthly"}, {"frequency": "Once a month."}),
        (EFFORT, {"duration": "2 hours"}, {"duration": "120 minutes"}),
        ("process.volume", {"count": 12, "period": "month"}, {"count": 12, "period": "monthly"}),
        ("process.trigger", "Month-end close is completed", "month end close is completed."),
    ],
)
def test_ac_17_80_same_meaning_is_not_a_conflict(vocab, key, stored, offered):
    profile = write(vocab, expert_steps(vocab, procedure_profile(vocab), SITE_STEPS), {key: stored})
    from app.services.process_discovery.profile.conflicts import plan_offer

    plan = plan_offer(profile, key, offered, vocab=vocab)
    assert plan.conflicts == () and plan.refusal == "same_value", plan


def test_ac_17_80_a_real_difference_is_a_conflict(vocab):
    from app.services.process_discovery.profile.conflicts import plan_offer

    profile = write(
        vocab, expert_steps(vocab, procedure_profile(vocab), SITE_STEPS), {EFFORT: {"frequency": "monthly"}}
    )
    plan = plan_offer(profile, EFFORT, {"frequency": "weekly"}, vocab=vocab)
    assert [(c.sub, c.value, c.kind) for c in plan.conflicts] == [("frequency", "weekly", "expert")]


def test_ac_17_81_same_meaning_between_documents_and_list_merge(vocab):
    profile = example_5(vocab)
    out = slides_reading(vocab, profile, frequency="every month", systems=("Planning tool",))
    assert out.diff.conflicts == ()
    written = apply_proposals(profile, out.diff, vocab=vocab, at=AT).profile
    assert stored_value(written, EFFORT)["frequency"] == "monthly"
    assert stored_value(written, SYSTEMS) == ["Ledger system", "Planning tool"]
