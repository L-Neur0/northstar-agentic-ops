"""Tests for whole-field proposals on partly answered fields (spec 17 Q5/Q7, decided 2026-11-20).

Why: an expert who named step 3's inputs but not its outputs should be able to upload an output
example and have the outputs proposed. Meta is per field, so the proposal is the WHOLE field: the
expert's sub-values unchanged plus the document's missing ones, marked `proposed` with `replaces`
holding what was there. A yes makes the whole field count; a no restores exactly the previous value
and meta; a document never changes a sub-value a person gave.
What: AC-17.62 to AC-17.65, through `build_diff`, `apply_proposals`, `confirm_proposals`,
`reject_proposals` and an expert correction (`apply_changes`).
Must not: call a model. Spec 17 §3.1 items 5 and 7, §9 Q5 and Q7.
"""

from __future__ import annotations

import copy

from app.services.process_discovery.documents.context import ReadingContext
from app.services.process_discovery.documents.filter import build_diff
from app.services.process_discovery.documents.schema import read_document_model
from app.services.process_discovery.profile.proposals import apply_proposals, confirm_proposals, reject_proposals
from app.services.process_discovery.profile.shapes import meta_for, stored_value
from app.services.process_discovery.profile.verdicts import field_counts

from .helpers import AT, SITE_STEPS, expert_steps, procedure_profile, specialist, write

KEY = "process.substeps[3].data"
TEXT = "Site | Cost centre | Budget\nInputs: ledger export\nVariance report per site"
CONTEXT = ReadingContext(phase="steps", focus_step=3, step_names=tuple(SITE_STEPS))


def inputs_only(vocab):
    profile = expert_steps(vocab, procedure_profile(vocab), SITE_STEPS)
    return write(vocab, profile, {KEY: {"inputs": ["Ledger export"]}})


def output_reading(vocab, profile, *, inputs=()):
    data = {
        "inputs": [{"value": v, "quote": "Inputs: ledger export"} for v in inputs],
        "outputs": [{"value": "Variance report per site", "quote": "Variance report per site"}],
    }
    raw = read_document_model().model_validate({"document_role": "step_output_example", "target_cells": {"data": data}})
    return build_diff(raw, document_id="d1", text=TEXT, profile=profile, vocab=vocab, context=CONTEXT, name="r.xlsx")


def test_ac_17_62_whole_field_proposal_with_replaces(vocab):
    profile = inputs_only(vocab)
    before = copy.deepcopy(stored_value(profile, KEY))
    out = output_reading(vocab, profile)
    [cell] = out.diff.step_cells
    assert cell.value == {"inputs": ["Ledger export"], "outputs": ["Variance report per site"]}
    written = apply_proposals(profile, out.diff, vocab=vocab, at=AT).profile
    meta = meta_for(written, KEY)
    assert meta is not None and meta["status"] == "proposed" and meta["source"] == "document"
    assert meta["replaces"]["value"] == before
    assert meta["replaces"]["meta"]["source"] == "expert"


def test_ac_17_63_confirming_makes_the_field_count(vocab):
    written = apply_proposals(inputs_only(vocab), output_reading(vocab, inputs_only(vocab)).diff, vocab=vocab, at=AT)
    assert not field_counts(written.profile, KEY, vocab=vocab)
    done = confirm_proposals(written.profile, [KEY], vocab=vocab, at=AT).profile
    assert field_counts(done, KEY, vocab=vocab)
    assert stored_value(done, KEY)["inputs"] == ["Ledger export"]
    assert "replaces" not in (meta_for(done, KEY) or {})


def test_ac_17_64_rejecting_restores_exactly(vocab):
    profile = inputs_only(vocab)
    before_value = copy.deepcopy(stored_value(profile, KEY))
    before_meta = copy.deepcopy(meta_for(profile, KEY))
    written = apply_proposals(profile, output_reading(vocab, profile).diff, vocab=vocab, at=AT).profile
    back = reject_proposals(written, [KEY], vocab=vocab, at=AT).profile
    assert stored_value(back, KEY) == before_value
    assert meta_for(back, KEY) == before_meta


def test_ac_17_64_a_correction_keeps_the_experts_inputs(vocab):
    profile = inputs_only(vocab)
    written = apply_proposals(profile, output_reading(vocab, profile).diff, vocab=vocab, at=AT).profile
    corrected = write(vocab, written, {KEY: {"outputs": ["A PDF report"]}})
    assert stored_value(corrected, KEY) == {"inputs": ["Ledger export"], "outputs": ["A PDF report"]}
    assert (meta_for(corrected, KEY) or {}).get("source") == "expert"


def test_ac_17_65_a_differing_expert_value_is_never_changed(vocab):
    profile = inputs_only(vocab)
    out = output_reading(vocab, profile, inputs=["Budget file"])
    [cell] = out.diff.step_cells
    assert cell.value["inputs"] == ["Ledger export"]
    assert (KEY, "conflicts_with_expert", 1) in {(s.key, s.reason, s.items) for s in out.skipped}


def test_ac_17_65_specialist_and_complete_fields_stay_refused(vocab):
    profile = specialist(vocab, inputs_only(vocab), KEY, {"inputs": ["Ledger export"], "outputs": []})
    assert ("process.substeps[3].data", "specialist_owned") in {
        (s.key, s.reason) for s in output_reading(vocab, profile).skipped
    }
    full = write(vocab, inputs_only(vocab), {KEY: {"outputs": ["Report"]}})
    out = output_reading(vocab, full)
    assert out.diff.step_cells == ()
    assert (KEY, "confirmed") in {(s.key, s.reason) for s in out.skipped}


def test_ac_17_62_volume_with_a_count_and_no_period(vocab):
    profile = write(vocab, procedure_profile(vocab), {"process.volume": {"count": 14}})
    raw = read_document_model().model_validate(
        {
            "document_role": "whole_process",
            "volume": {"count": 12, "period": "month", "raw": None, "quote": "every month"},
        }
    )
    out = build_diff(raw, document_id="d1", text="It runs every month.", profile=profile, vocab=vocab)
    [field] = out.diff.fields
    assert (field.value["count"], field.value["period"]) == (14, "month")
    assert ("process.volume", "conflicts_with_expert", 1) in {(s.key, s.reason, s.items) for s in out.skipped}
