"""Tests for the raw step snapshot (spec 13 §3.12; AC-13.51).

Why: the snapshot must never contain a word the expert did not say, so it is frozen once, before
the first non-expert write. What: copy when empty, unchanged when taken, unaffected by later edits.
"""

from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.profile.mutate import apply_changes
from app.services.process_discovery.profile.raw_snapshot import freeze_raw_substeps
from app.services.process_discovery.profile.shapes import empty_profile

from .builders import AT


def test_freeze_once(vocab):
    """AC-13.51."""
    profile = apply_changes(empty_profile(), {step_cell_key(1, "name"): "Export"}, vocab=vocab, at=AT).profile
    raw = freeze_raw_substeps([], profile)
    assert raw == profile["process"]["substeps"]
    assert freeze_raw_substeps([], empty_profile()) == []
    edited = apply_changes(profile, {step_cell_key(1, "name"): "Export actuals"}, vocab=vocab, at=AT).profile
    again = freeze_raw_substeps(raw, edited)
    assert again == raw
    assert again[0]["name"] == "Export"
