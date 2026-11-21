"""Tests for the field views the panel and the review screen show (spec 13 §3.11; AC-13.50).

Why: the client never computes a status, so every status of the §3.11 order must be produced here
from a profile built with the real writers. What: one view per field and per cell; each status;
reason, source, quote, document name and asks.
"""

from app.models.process_discovery_schemas import FieldView
from app.services.process_discovery.domain.field_spec import PROFILE_SPECS, STEP_SPECS, step_cell_key
from app.services.process_discovery.profile.mutate import apply_changes, mark_cells_skipped
from app.services.process_discovery.profile.proposals import FieldProposal, ProposalDiff, apply_proposals
from app.services.process_discovery.profile.shapes import empty_profile
from app.services.process_discovery.profile.views import field_views

from .builders import AT


def test_every_status_and_the_details(vocab):
    """AC-13.50."""
    profile = apply_changes(
        empty_profile(),
        {
            "department": "Finance",
            "region": "Germany",
            "process.volume": {"count": 4},
            "process.substep_count": 2,
            step_cell_key(1, "name"): "Export",
        },
        vocab=vocab,
        at=AT,
    ).profile
    diff = ProposalDiff("d1", fields=(FieldProposal("process.trigger", "Month end", "starts at month end"),))
    profile = apply_proposals(profile, diff, vocab=vocab, at=AT).profile
    profile = mark_cells_skipped(profile, [step_cell_key(1, "goal")], vocab=vocab)
    counters = {
        "field_asks": {"process.end_result": 5, "process.value_at_end": 3, "process.business_pain": 1},
        "cell_asks": {step_cell_key(1, "goal"): 3},
    }
    views = field_views(profile, counters=counters, vocab=vocab, documents=[{"id": "d1", "name": "Procedure.docx"}])
    assert len(views) == len(PROFILE_SPECS) + 2 * len([s for s in STEP_SPECS if s.applies_when is None])
    by_key = {v["key"]: v for v in views}
    assert by_key["process.trigger"]["status"] == "proposed"
    assert by_key["process.trigger"]["document_name"] == "Procedure.docx"
    assert by_key["process.trigger"]["quote"] == "starts at month end"
    assert by_key["process.trigger"]["source"] == "document"
    assert by_key["department"]["status"] == "complete"
    assert by_key["department"]["source"] == "expert"
    assert by_key["department"]["quote"] is None
    assert by_key[step_cell_key(1, "goal")]["status"] == "skipped"
    assert by_key[step_cell_key(1, "goal")]["asks"] == 3
    assert by_key["process.end_result"]["status"] == "given_up"
    assert by_key["process.value_at_end"]["status"] == "deferred"
    assert by_key["process.business_pain"]["status"] == "empty"
    assert by_key["process.business_pain"]["asks"] == 1
    assert by_key["region"]["status"] == "invalid"
    assert by_key["process.volume"]["status"] == "partial"
    assert by_key["process.volume"]["reason"] == "Volume still needs: period."
    assert by_key["process.volume"]["missing"] == ["period"]
    assert by_key[step_cell_key(1, "name")]["phase"] == "steps"
    for view in views:
        FieldView.model_validate(view)
