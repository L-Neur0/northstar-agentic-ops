"""Tests for filling gaps in steps the expert already gave: matching, fill-only cells, no new rows (spec 17 §3.10 case B).

Why: once the expert has named the steps, they own the table: a document may fill empty cells of
those rows, matched by name (or by position when the counts agree), but never add, remove or
reorder a row, and never overwrite what a person said.
What: AC-17.27 and AC-17.40 to AC-17.44.
Must not: call a model; profiles are built with the real writers. Spec 17 §3.10, §3.12.
"""

from __future__ import annotations

from typing import Any

from app.services.process_discovery.documents.filter import build_diff, match_steps
from app.services.process_discovery.documents.pipeline import read_message
from app.services.process_discovery.documents.schema import read_document_model
from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.profile.proposals import FieldProposal, ProposalDiff, apply_proposals
from app.services.process_discovery.profile.shapes import rows_of

from .helpers import AT, STEP_NAMES, expert_steps, procedure_profile, procedure_reply, procedure_text, specialist, write

TEXT = procedure_text()


def raw(**fields: Any):
    return read_document_model().model_validate({"document_kind": "procedure", **fields})


def doc_step(name: str, quote: str | None = None, **cells: Any) -> dict[str, Any]:
    return {"name": {"value": name, "quote": quote or name}, **cells}


def keys(skipped) -> list[tuple[str, str]]:
    return [(s.key, s.reason) for s in skipped]


def test_ac_17_27_existing_rows_never_change_shape(vocab):
    profile = expert_steps(vocab, procedure_profile(vocab), ["Export actuals", "Review"])
    many = [doc_step(n) for n in STEP_NAMES] + [doc_step("Review", "Step 4 | Review")] * 4
    for count in (2, 5, 9):
        out = build_diff(raw(steps=many[:count]), document_id="d1", text=TEXT, profile=profile)
        assert out.diff.steps == ()
        assert out.step_list == ()
        applied = apply_proposals(profile, out.diff, vocab=vocab, at=AT).profile
        assert [r["name"] for r in rows_of(applied)] == ["Export actuals", "Review"]


def test_ac_17_40_match_by_name_ignores_case_and_spacing(vocab):
    profile = expert_steps(vocab, procedure_profile(vocab), ["Export actuals", "collect  explanations"])
    data = {"inputs": [], "outputs": [{"value": "Review workbook", "quote": "into the review workbook"}]}
    exceptions = [
        {"description": "Explanation missing", "loops_back_to": None, "quote": "If an explanation is missing"}
    ]
    reply = raw(
        steps=[
            doc_step("Export Actuals", "Export actuals", data=data),
            doc_step("Collect explanations", exceptions=exceptions),
        ]
    )
    out = build_diff(reply, document_id="d1", text=TEXT, profile=profile)
    assert [c.key for c in out.diff.step_cells] == ["process.substeps[1].data", "process.substeps[2].exceptions"]
    assert out.diff.steps == ()
    assert match_steps(["Export Actuals", "Collect  Explanations"], profile) == [1, 2]


def test_ac_17_41_position_only_when_counts_agree(vocab):
    expert = ["Pull numbers", "Check variances", "Chase managers", "Approve", "Send report"]
    systems = [{"value": "Excel", "quote": "the budget in Excel"}]
    offered = raw(steps=[doc_step(n, systems=systems) for n in STEP_NAMES])
    five = expert_steps(vocab, procedure_profile(vocab), expert)
    out = build_diff(offered, document_id="d1", text=TEXT, profile=five)
    assert [c.key for c in out.diff.step_cells] == [step_cell_key(i, "systems") for i in range(1, 6)]
    assert match_steps(list(STEP_NAMES), five) == [1, 2, 3, 4, 5]
    four = expert_steps(vocab, procedure_profile(vocab), expert[:4])
    out = build_diff(offered, document_id="d1", text=TEXT, profile=four)
    assert out.diff.step_cells == ()
    assert keys(out.skipped) == [(f"steps[{i}]", "no_matching_step") for i in range(1, 6)]


def test_ac_17_42_filled_specialist_and_none_cells_are_refused(vocab):
    profile = expert_steps(vocab, procedure_profile(vocab), ["Export actuals", "Review"])
    profile = write(vocab, profile, {step_cell_key(1, "systems"): ["SAP"], step_cell_key(1, "roles"): [{"none": True}]})
    profile = specialist(vocab, profile, step_cell_key(1, "owner"), "Controller")
    earlier = ProposalDiff("d0", step_cells=(FieldProposal(step_cell_key(1, "activities"), ["Export"], "exports"),))
    profile = apply_proposals(profile, earlier, vocab=vocab, at=AT).profile
    cells = procedure_reply()["steps"][0]
    cells["goal"] = {"value": "Actuals are in the workbook", "quote": "into the review workbook"}
    out = build_diff(raw(steps=[cells]), document_id="d1", text=TEXT, profile=profile)
    kept = [c.key for c in out.diff.step_cells]
    assert kept == [step_cell_key(1, leaf) for leaf in ("goal", "activities", "data")]
    assert keys(out.skipped) == [
        (step_cell_key(1, "roles"), "confirmed"),
        (step_cell_key(1, "owner"), "specialist_owned"),
        (step_cell_key(1, "systems"), "confirmed"),
    ]


def test_ac_17_43_an_unmatched_step_is_reported_once(vocab):
    profile = expert_steps(vocab, procedure_profile(vocab), ["Export actuals", "Review", "Send report"])
    offered = raw(
        steps=[
            doc_step("Export actuals", systems=[{"value": "SAP S/4HANA", "quote": "from SAP S/4HANA"}]),
            doc_step("Collect explanations", systems=[{"value": "E-mail", "quote": "by e-mail"}]),
        ]
    )
    out = build_diff(offered, document_id="d1", text=TEXT, profile=profile)
    assert [c.key for c in out.diff.step_cells] == [step_cell_key(1, "systems")]
    assert keys(out.skipped) == [("steps[2]", "no_matching_step")]
    message = read_message("proc.docx", values=1, steps=0, truncated=False, step_list=0, case_b=True, unmatched=1)
    assert message.endswith(
        "You already gave me the steps, so I kept them and only filled gaps. 1 of its steps didn't match yours."
    )


def test_ac_17_44_loops_back_to_follows_the_matched_rows(vocab):
    profile = expert_steps(vocab, procedure_profile(vocab), list(STEP_NAMES))
    loops = [
        {"description": "Back to review", "loops_back_to": 1, "quote": "If an explanation is missing"},
        {"description": "Back to the unknown step", "loops_back_to": 3, "quote": "If an explanation is missing"},
    ]
    offered = raw(
        steps=[
            doc_step("Review", "Step 4 | Review"),
            doc_step("Collect explanations", exceptions=loops),
            doc_step("Close the books", "Monthly cost review"),
        ]
    )
    out = build_diff(offered, document_id="d1", text=TEXT, profile=profile)
    exceptions = next(c for c in out.diff.step_cells if c.key == step_cell_key(3, "exceptions"))
    assert [row["loops_back_to"] for row in exceptions.value] == [4, None]
    assert keys(out.skipped) == [("steps[3]", "no_matching_step")]
