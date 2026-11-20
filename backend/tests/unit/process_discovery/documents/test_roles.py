"""Tests for reading in context: the role table, the target step, the file description (spec 17 §3.18 items 5–8, 11).

Why: a file uploaded during the step walk is usually an example of one step's output or input, not a
procedure. The model classifies it, but code decides what is used (the role table), which step it
lands on (T1–T5: the model's choice only when the document or the expert's words name the step) and
whether a description of the file has evidence (D1–D5). A step-scoped reading never adds, removes or
reorders rows.
What: AC-17.47 to AC-17.53, with scripted readings (no model call, except the pipeline test of
worked example 4 with `FakeLLM`).
Must not: reach Azure. Spec 17 §3.18.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.process_discovery.documents.context import ReadingContext
from app.services.process_discovery.documents.extract import extract_text
from app.services.process_discovery.documents.filter import build_diff, check_description, resolve_target
from app.services.process_discovery.documents.pipeline import read_document
from app.services.process_discovery.documents.schema import read_document_model
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.llm import CallType
from app.services.process_discovery.profile.proposals import FieldProposal, apply_proposals
from app.services.process_discovery.profile.shapes import rows_of

from .helpers import AT, FIXTURES, SITE_EXPERT, SITE_STEPS, expert_steps, procedure_profile, site_reply, site_session

SITE_TEXT = extract_text("xlsx", (FIXTURES / "site_report_march.xlsx").read_bytes(), 60_000).text
HEADER = "Site | Cost centre | Budget | Actual | Variance | Comment"
DESCRIPTION = "Excel cost report per site with variance comments, one tab per site"
FOCUS3 = ReadingContext(phase="steps", focus_step=3, last_expert=SITE_EXPERT, step_names=tuple(SITE_STEPS))


def raw(**fields: Any):
    return read_document_model().model_validate(fields)


def steps_profile(vocab):
    return expert_steps(vocab, procedure_profile(vocab), SITE_STEPS)


def diff(vocab, reply, *, profile=None, context=FOCUS3, text=SITE_TEXT, name="site_report_march.xlsx"):
    return build_diff(
        raw(**reply),
        document_id="d2",
        text=text,
        profile=profile if profile is not None else steps_profile(vocab),
        vocab=vocab,
        context=context,
        name=name,
    )


EVERYTHING = {
    "trigger": {"value": "Variance above budget", "quote": "Variance"},
    "steps": [
        {"name": {"value": "North", "quote": "North"}},
        {"name": {"value": "South", "quote": "South"}},
    ],
    "target_cells": {"systems": [{"value": "Excel", "quote": "Cost centre"}]},
    "file_description": {"value": DESCRIPTION, "quote": HEADER},
}


@pytest.mark.parametrize(
    ("role", "kept_cells", "not_used"),
    [
        ("whole_process", set(), {"target_cells", "file_description"}),
        ("step_output_example", {"process.substeps[3].systems", "process.substeps[3].data"}, {"steps"}),
        ("step_input_example", {"process.substeps[3].systems", "process.substeps[3].data"}, {"steps"}),
        ("step_material", {"process.substeps[3].systems"}, {"steps", "file_description"}),
        ("other", {"process.substeps[3].systems"}, {"steps", "file_description"}),
    ],
)
def test_ac_17_47_role_table(vocab, role, kept_cells, not_used):
    out = diff(vocab, {**EVERYTHING, "document_role": role})
    assert [f.key for f in out.diff.fields] == ["process.trigger"]  # process fields: kept for every role
    assert {c.key for c in out.diff.step_cells} == kept_cells
    assert {s.key for s in out.skipped if s.reason == "not_used"} == not_used
    assert out.diff.steps == ()


def test_ac_17_47_bpmn_reading_is_whole_process(fixture_bytes):
    from app.services.process_discovery.documents.bpmn_read import read_bpmn

    assert read_bpmn(fixture_bytes("access_review.bpmn"), 60_000).raw.document_role == "whole_process"  # type: ignore[attr-defined]


def _target(model_step, by, *, message="nothing here", text="no names", focus: int | None = 3, rows=5):
    context = ReadingContext(focus_step=focus, last_expert=message, step_names=tuple(SITE_STEPS))
    return resolve_target({"target_step": model_step, "target_named_by": by}, text=text, context=context, rows=rows)


def test_ac_17_48_target_step_rules():
    assert _target(4, "expert", message="the report from step 4") == (4, "expert")
    assert _target(4, "expert", message="here is the review file") == (4, "expert")  # row 4's name "Review"
    assert _target(4, "expert", message="here it is") == (3, "focus")
    assert _target(2, "document", text="Compare with budget, per site") == (2, "document")
    assert _target(7, "document", text="anything") == (3, "focus")
    assert _target(None, None) == (3, "focus")
    assert _target(4, "expert", message="here it is", focus=None) == (None, "none")
    assert _target(2, "document", text="x", rows=0) == (None, "none")


def test_ac_17_48_no_target_is_reported_once(vocab):
    out = diff(vocab, {**EVERYTHING, "document_role": "step_output_example"}, context=ReadingContext())
    assert out.target_step is None and out.target_source == "none"
    assert [s for s in out.skipped if s.reason == "no_target_step"] == [
        type(out.skipped[0])("target_step", "no_target_step")
    ]
    assert out.diff.step_cells == ()


async def test_ac_17_48_no_rows_sentence(vocab, docs_config, fixture_bytes):
    session = site_session(vocab, procedure_profile(vocab))
    llm = FakeLLM({CallType.READ_DOCUMENT: [site_reply()]})
    from app.services.process_discovery.documents.context import reading_context

    result = await read_document(
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
    assert result.report.message.endswith(
        "It looks like it belongs to one step; we haven't listed the steps yet, so I used only what fits the whole process."
    )


async def test_ac_17_49_worked_example_4(vocab, docs_config, fixture_bytes):
    from app.services.process_discovery.documents.context import reading_context

    session = site_session(vocab)
    llm = FakeLLM({CallType.READ_DOCUMENT: [site_reply()]})
    result = await read_document(
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
    llm.assert_all_used()
    assert result.diff.step_cells == (
        FieldProposal("process.substeps[3].data", {"inputs": [], "outputs": [DESCRIPTION]}, HEADER),
    )
    assert result.diff.steps == () and result.diff.fields == ()
    report = result.report.model_dump(by_alias=True)
    assert (report["targetStep"], report["targetSource"], report["documentRole"]) == (3, "focus", "step_output_example")
    assert (result.role, result.target_step, result.from_image) == ("step_output_example", 3, False)


def test_ac_17_50_input_description_and_material(vocab):
    out = diff(vocab, {**EVERYTHING, "document_role": "step_input_example", "target_cells": None})
    [cell] = out.diff.step_cells
    assert cell.key == "process.substeps[3].data" and cell.value["inputs"][0] == DESCRIPTION
    out = diff(vocab, {**EVERYTHING, "document_role": "step_material"})
    assert [c.key for c in out.diff.step_cells] == ["process.substeps[3].systems"]
    assert ("file_description", "not_used") in {(s.key, s.reason) for s in out.skipped}


@pytest.mark.parametrize(
    ("description", "excerpt", "reason"),
    [
        ("Cost repor", HEADER, None),  # 10 characters is enough
        ("Cost repo", HEADER, "description_invalid"),
        (DESCRIPTION, "Site | Cost", "quote_invalid"),
        (DESCRIPTION, "Site | Cost centre | Budget | Forecast", "quote_not_found"),
        ("Quarterly fleet maintenance plan", HEADER, "description_unsupported"),
        ("Cost report, questions to someone@example.com", HEADER, "personal_data"),
        ("Cost report, see www.x.com", HEADER, "personal_data"),
        ("Cost report, call +49 89 1234567", HEADER, "personal_data"),
    ],
)
def test_ac_17_51_description_checks(description, excerpt, reason):
    assert check_description(description, excerpt, text=SITE_TEXT, name="site_report_march.xlsx") == reason


def test_ac_17_51_the_file_name_supports_a_description():
    assert check_description("Monthly snapshot", HEADER, text=SITE_TEXT, name="monthly_snapshot.xlsx") is None


def test_ac_17_52_merge_into_a_proposed_cell_and_refuse_an_expert_cell(vocab):
    profile = steps_profile(vocab)
    first = build_diff(
        raw(
            document_role="step_input_example",
            file_description={"value": "Ledger export per cost centre", "quote": "Cost centre | Budget"},
        ),
        document_id="d1",
        text=SITE_TEXT,
        profile=profile,
        vocab=vocab,
        context=FOCUS3,
        name="ledger.xlsx",
    )
    profile = apply_proposals(profile, first.diff, vocab=vocab, at=AT).profile
    out = diff(vocab, {**EVERYTHING, "document_role": "step_output_example", "target_cells": None}, profile=profile)
    [cell] = out.diff.step_cells
    assert cell.value == {"inputs": ["Ledger export per cost centre"], "outputs": [DESCRIPTION]}
    written = apply_proposals(profile, out.diff, vocab=vocab, at=AT).profile
    row = rows_of(written)[2]
    assert row["data"] == {"inputs": ["Ledger export per cost centre"], "outputs": [DESCRIPTION]}
    assert row["__meta"]["data"]["documentId"] == "d2"

    from .helpers import write

    expert = write(vocab, steps_profile(vocab), {"process.substeps[3].data": {"inputs": ["A"], "outputs": ["B"]}})
    out = diff(vocab, {**EVERYTHING, "document_role": "step_output_example", "target_cells": None}, profile=expert)
    assert out.diff.step_cells == ()
    assert ("process.substeps[3].data", "confirmed") in {(s.key, s.reason) for s in out.skipped}


def test_ac_17_53_a_step_scoped_reading_never_changes_the_rows(vocab):
    profile = steps_profile(vocab)
    out = diff(vocab, {**EVERYTHING, "document_role": "step_output_example"}, profile=profile)
    assert out.diff.steps == () and out.step_list == ()
    assert all(not c.key.endswith(".name") for c in out.diff.step_cells)
    assert all(f.key != "process.substep_count" for f in out.diff.fields)
    written = apply_proposals(profile, out.diff, vocab=vocab, at=AT).profile
    assert [r["name"] for r in rows_of(written)] == SITE_STEPS
