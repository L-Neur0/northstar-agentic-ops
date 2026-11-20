"""Tests for a source per item (spec 17 §3.21 item 5, P1–P7): a cell filled from two files names both.

Why: before, merging an older document's items into a newer proposal made the whole cell name the
newer file, so the procedure's items showed "(from an image)" after a screenshot was read, and
removing the screenshot took the procedure's items too. Each item now keeps its own source.
What: AC-17.76 (parts and the panel view), AC-17.77 (removal per item, P5 and P6) and AC-17.78
(`fromImage` kept at write time; no file name in meta, parts or conflicts).
Must not: call a model. Spec 17 §3.21 item 5, spec 13 §3.13 items 4–5.
"""

from __future__ import annotations

import json

from app.services.process_discovery.profile.proposals import (
    ConflictOffer,
    FieldProposal,
    ProposalDiff,
    apply_proposals,
    confirm_proposals,
    remove_document_proposals,
)
from app.services.process_discovery.profile.shapes import meta_for, rows_of, stored_value
from app.services.process_discovery.profile.views import field_views

from ..documents.helpers import AT, SITE_STEPS, expert_steps, procedure_profile

SYSTEMS = "process.substeps[4].systems"
EFFORT = "process.substeps[4].effort"


def meta_of(profile, key):
    """The meta entry, which these tests expect to exist."""
    meta = meta_for(profile, key)
    assert meta is not None
    return meta


def two_files(vocab):
    profile = expert_steps(vocab, procedure_profile(vocab), SITE_STEPS)
    d1 = ProposalDiff("d1", step_cells=(FieldProposal(SYSTEMS, ["Ledger system"], "in the ledger system"),))
    profile = apply_proposals(profile, d1, vocab=vocab, at=AT).profile
    d4 = ProposalDiff("d4", step_cells=(FieldProposal(SYSTEMS, ["Planning tool"], "Planning tool"),), from_image=True)
    return apply_proposals(profile, d4, vocab=vocab, at=AT).profile


def test_ac_17_76_a_source_per_item(vocab):
    profile = two_files(vocab)
    assert stored_value(profile, SYSTEMS) == ["Ledger system", "Planning tool"]
    parts = meta_of(profile, SYSTEMS)["parts"]
    assert [(p["item"], p["documentId"], p["fromImage"]) for p in parts] == [
        ("Ledger system", "d1", False),
        ("Planning tool", "d4", True),
    ]
    documents = [{"id": "d1", "name": "procedure.docx"}, {"id": "d4", "name": "planning_tool.png"}]
    [view] = [v for v in field_views(profile, counters={}, vocab=vocab, documents=documents) if v["key"] == SYSTEMS]
    assert [(i["item"], i["document_name"], i["from_image"]) for i in view["items"]] == [
        ("Ledger system", "procedure.docx", False),
        ("Planning tool", "planning_tool.png", True),
    ]


def test_ac_17_77_removal_per_item(vocab):
    profile = two_files(vocab)
    without_image = remove_document_proposals(profile, "d4", vocab=vocab, at=AT).profile
    assert stored_value(without_image, SYSTEMS) == ["Ledger system"]
    meta = meta_of(without_image, SYSTEMS)
    assert (meta["documentId"], meta["status"], "parts" in meta) == ("d1", "proposed", False)
    without_procedure = remove_document_proposals(profile, "d1", vocab=vocab, at=AT).profile
    assert stored_value(without_procedure, SYSTEMS) == ["Planning tool"]
    assert meta_of(without_procedure, SYSTEMS)["documentId"] == "d4"
    confirmed = confirm_proposals(profile, [SYSTEMS], vocab=vocab, at=AT).profile
    kept = remove_document_proposals(confirmed, "d4", vocab=vocab, at=AT).profile
    assert stored_value(kept, SYSTEMS) == ["Ledger system", "Planning tool"]


def test_ac_17_77_removal_of_a_conflict_holder_promotes_the_offer(vocab):
    profile = expert_steps(vocab, procedure_profile(vocab), SITE_STEPS)
    d1 = ProposalDiff("d1", step_cells=(FieldProposal(EFFORT, {"duration": "2 hours", "frequency": "monthly"}, "q1"),))
    profile = apply_proposals(profile, d1, vocab=vocab, at=AT).profile
    d3 = ProposalDiff("d3", conflicts=(ConflictOffer(EFFORT, "frequency", "weekly", "weekly"),))
    profile = apply_proposals(profile, d3, vocab=vocab, at=AT).profile
    assert rows_of(profile)[3]["__conflicts"]["effort"][0]["holderDocumentId"] == "d1"
    dropped = remove_document_proposals(profile, "d3", vocab=vocab, at=AT).profile
    assert "__conflicts" not in rows_of(dropped)[3] or not rows_of(dropped)[3]["__conflicts"]
    assert stored_value(dropped, EFFORT)["frequency"] == "monthly"
    promoted = remove_document_proposals(profile, "d1", vocab=vocab, at=AT).profile
    assert stored_value(promoted, EFFORT) == {"duration": "", "frequency": "weekly"}
    meta = meta_of(promoted, EFFORT)
    assert (meta["documentId"], meta["status"]) == ("d3", "proposed")
    assert not rows_of(promoted)[3].get("__conflicts")


def test_ac_17_78_from_image_is_kept_and_no_file_name_is_stored(vocab):
    profile = two_files(vocab)
    profile = apply_proposals(
        profile,
        ProposalDiff("d4", conflicts=(ConflictOffer(EFFORT, "frequency", "weekly", "Planning tool"),), from_image=True),
        vocab=vocab,
        at=AT,
    ).profile
    gone = remove_document_proposals(profile, "d1", vocab=vocab, at=AT).profile
    assert meta_of(gone, SYSTEMS)["fromImage"] is True
    text = json.dumps(profile)
    assert "planning_tool.png" not in text and "procedure.docx" not in text
