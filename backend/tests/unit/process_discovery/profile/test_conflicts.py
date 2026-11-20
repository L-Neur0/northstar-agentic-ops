"""Tests for the write side of conflicts (spec 13 §3.13): storing, choosing, closing, and what never moves.

Why: a conflict is a promise to the expert that nothing changes until they choose. So the record
must sit next to the unit it is about (and move with its row), a choice must write exactly what the
table says with a source per item, the expert's own words must close it, and an open or left
conflict must never change the score or the *Finish* check.
What: AC-13.57 to AC-13.61 through `apply_proposals`, `open_conflicts`, `resolve_conflicts`,
`apply_changes`, `mark_conflicts_left`, `reject_proposals`, `score` and `finish_check`.
Must not: call a model. Spec 13 §3.13.
"""

from __future__ import annotations

from app.services.process_discovery.profile.conflicts import (
    mark_conflicts_left,
    open_conflicts,
    resolve_conflicts,
)
from app.services.process_discovery.profile.mutate import apply_changes
from app.services.process_discovery.profile.proposals import (
    ConflictOffer,
    FieldProposal,
    ProposalDiff,
    apply_proposals,
    reject_proposals,
)
from app.services.process_discovery.profile.scoring import finish_check, score
from app.services.process_discovery.profile.shapes import meta_for, rows_of, stored_value

from ..documents.helpers import AT, SITE_STEPS, expert_steps, procedure_profile, specialist, write

DATA = "process.substeps[3].data"
EFFORT = "process.substeps[4].effort"
DESCRIPTION = "Excel cost report per site with variance comments, one tab per site"
OUTPUTS = ConflictOffer(DATA, "outputs", [DESCRIPTION], "Site | Cost centre")


def meta_of(profile, key):
    """The meta entry, which these tests expect to exist."""
    meta = meta_for(profile, key)
    assert meta is not None
    return meta


def with_conflict(vocab):
    profile = expert_steps(vocab, procedure_profile(vocab), SITE_STEPS)
    profile = write(vocab, profile, {DATA: {"outputs": ["a cost report"]}, "process.trigger": "Month end"})
    diff = ProposalDiff(
        "d2", conflicts=(OUTPUTS, ConflictOffer("process.trigger", None, "Close is completed", "close"))
    )
    return apply_proposals(profile, diff, vocab=vocab, at=AT).profile


def test_ac_13_57_stored_in_the_right_sidecar(vocab):
    profile = with_conflict(vocab)
    assert profile["__conflicts"]["process.trigger"][0]["value"] == "Close is completed"
    assert rows_of(profile)[2]["__conflicts"]["data"][0]["sub"] == "outputs"
    owned = specialist(vocab, with_conflict(vocab), "process.end_result", "A report")
    result = apply_proposals(
        owned,
        ProposalDiff("d3", conflicts=(ConflictOffer("process.end_result", None, "Other", "q"),)),
        vocab=vocab,
        at=AT,
    )
    assert result.refused == [("process.end_result", "specialist_owned")] and result.conflicts == ()
    empty = apply_proposals(
        with_conflict(vocab),
        ProposalDiff("d3", conflicts=(ConflictOffer("process.end_result", None, "A report", "q"),)),
        vocab=vocab,
        at=AT,
    ).profile
    assert stored_value(empty, "process.end_result") == "A report"
    assert meta_of(empty, "process.end_result")["status"] == "proposed"


def test_ac_13_58_the_record_moves_with_its_row(vocab):
    profile = with_conflict(vocab)
    rows = profile["process"]["substeps"]
    rows.insert(2, {**rows[1], "name": "New step", "__conflicts": {}})
    keys = [c.conflict_key for c in open_conflicts(profile)]
    assert "process.substeps[4].data.outputs" in keys


def test_ac_13_59_choices(vocab):
    profile = with_conflict(vocab)
    key = "process.substeps[3].data.outputs"
    both = resolve_conflicts(profile, [key], "both", vocab=vocab, at=AT).profile
    assert stored_value(both, DATA)["outputs"] == ["a cost report", DESCRIPTION]
    parts = meta_of(both, DATA)["parts"]
    assert [(p["item"], p["source"], p["documentId"]) for p in parts] == [
        ("a cost report", "expert", None),
        (DESCRIPTION, "document", "d2"),
    ]
    assert key not in [c.conflict_key for c in open_conflicts(both)]
    offered = resolve_conflicts(profile, [key], "offered", vocab=vocab, at=AT).profile
    assert stored_value(offered, DATA)["outputs"] == [DESCRIPTION]
    assert meta_of(offered, DATA)["status"] == "confirmed"
    current = resolve_conflicts(profile, [key], "current", vocab=vocab, at=AT).profile
    assert stored_value(current, DATA) == stored_value(profile, DATA)
    assert meta_of(current, DATA) == meta_of(profile, DATA)
    assert stored_value(current, "process.trigger") == "Month end"  # no other key changes


def test_ac_13_59_a_sub_field_choice_on_a_replaces_proposal(vocab):
    profile = write(vocab, procedure_profile(vocab), {"process.volume": {"count": 14}})
    diff = ProposalDiff(
        "d1",
        fields=(FieldProposal("process.volume", {"count": 12, "period": "month", "raw": ""}, "every month"),),
        conflicts=(ConflictOffer("process.volume", "count", 12, "every month"),),
    )
    profile = apply_proposals(profile, diff, vocab=vocab, at=AT).profile
    chosen = resolve_conflicts(profile, ["process.volume.count"], "offered", vocab=vocab, at=AT).profile
    assert stored_value(chosen, "process.volume")["count"] == 12
    assert meta_of(chosen, "process.volume")["status"] == "proposed"
    back = reject_proposals(chosen, ["process.volume"], vocab=vocab, at=AT).profile
    assert stored_value(back, "process.volume")["count"] == 12
    assert stored_value(back, "process.volume")["period"] == ""


def test_ac_13_60_own_words_close_and_left_changes_only_status(vocab):
    profile = with_conflict(vocab)
    result = apply_changes(profile, {DATA: {"outputs": ["The site report"]}}, vocab=vocab, at=AT)
    assert result.conflicts_closed == ("process.substeps[3].data.outputs",)
    left = mark_conflicts_left(profile, ["process.trigger"])
    [record] = left["__conflicts"]["process.trigger"]
    assert record["status"] == "left"
    assert stored_value(left, "process.trigger") == "Month end"
    assert {k: v for k, v in record.items() if k != "status"} == {
        k: v for k, v in profile["__conflicts"]["process.trigger"][0].items() if k != "status"
    }


def test_ac_13_61_conflicts_never_change_the_score_or_finish(vocab):
    base = expert_steps(vocab, procedure_profile(vocab), SITE_STEPS)
    base = write(vocab, base, {DATA: {"outputs": ["a cost report"]}, "process.trigger": "Month end"})
    profile = with_conflict(vocab)
    assert score(profile, vocab=vocab) == score(base, vocab=vocab)
    assert finish_check(profile, vocab=vocab) == finish_check(base, vocab=vocab)
    left = mark_conflicts_left(profile, ["process.trigger", "process.substeps[3].data.outputs"])
    assert score(left, vocab=vocab) == score(base, vocab=vocab)
