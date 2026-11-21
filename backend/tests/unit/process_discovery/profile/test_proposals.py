"""Tests for document proposals: fill-only writes, confirm, reject, remove, ideas (spec 13 §3.6; AC-13.33 to AC-13.44).

Why: the expert has the last word: a proposal may fill a gap, never overrule a person, and never
counts until confirmed. What: every rule of §3.6 and example 4, with `ProposalDiff` as the
document reader (spec 17) builds it.
"""

from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.profile.mutate import apply_changes, confirm_rollup, mark_cells_skipped, set_field
from app.services.process_discovery.profile.proposals import (
    FieldProposal,
    ProposalDiff,
    StepProposal,
    apply_proposals,
    confirm_proposals,
    propose_from_idea,
    proposed_keys,
    reject_proposals,
    remove_document_proposals,
)
from app.services.process_discovery.profile.scoring import score
from app.services.process_discovery.profile.shapes import empty_profile
from app.services.process_discovery.profile.verdicts import field_counts

from .builders import AT, context_changes, cost_review_profile, step_changes

STEP_NAMES = ("Export actuals", "Compare with budget", "Collect explanations", "Review", "Send the cost report")


def write(vocab, profile, changes):
    return apply_changes(profile, changes, vocab=vocab, at=AT).profile


def context(vocab):
    return write(vocab, empty_profile(), context_changes())


def procedure_diff(document_id="d1", names=STEP_NAMES):
    return ProposalDiff(
        document_id,
        fields=(
            FieldProposal(
                "process.trigger", "Month-end close is completed", "The review starts once month-end close is completed"
            ),
        ),
        steps=tuple(StepProposal((FieldProposal("name", n, n),)) for n in names),
    )


def test_a_proposal_is_stored_with_document_meta_and_does_not_score(vocab):
    """AC-13.33."""
    base = context(vocab)
    r = apply_proposals(base, procedure_diff(), vocab=vocab, at=AT)
    meta = r.profile["__meta"]["process.trigger"]
    assert meta == {
        "source": "document",
        "status": "proposed",
        "documentId": "d1",
        "quote": "The review starts once month-end close is completed",
        "by": None,
        "at": AT,
    }
    assert score(r.profile, vocab=vocab) == score(base, vocab=vocab)
    assert "process.trigger" in r.applied


def test_not_proposable_and_no_quote(vocab):
    """AC-13.34."""
    keys = [
        "department",
        "user_function",
        "region",
        "process.cluster",
        "process.substep_count",
        "process.substeps_complete",
        "process.all_roles",
    ]
    diff = ProposalDiff("d1", fields=tuple(FieldProposal(k, "x", "q") for k in keys))
    r = apply_proposals(empty_profile(), diff, vocab=vocab, at=AT)
    assert {reason for _, reason in r.refused} == {"not_proposable"}
    assert len(r.refused) == len(keys)
    no_quote = apply_proposals(
        empty_profile(), ProposalDiff("d1", fields=(FieldProposal("process.trigger", "x", " "),)), vocab=vocab, at=AT
    )
    assert no_quote.refused == [("process.trigger", "no_quote")]
    no_doc = apply_proposals(
        empty_profile(), ProposalDiff("", fields=(FieldProposal("process.trigger", "x", "q"),)), vocab=vocab, at=AT
    )
    assert no_doc.refused == [("process.trigger", "no_quote")]


def test_fill_only(vocab):
    """AC-13.35."""
    expert = write(vocab, empty_profile(), {"process.trigger": "Expert words"})
    assert apply_proposals(expert, procedure_diff(names=()), vocab=vocab, at=AT).refused == [
        ("process.trigger", "conflict")  # spec 17 §3.21: a differing value is never written
    ]
    specialist = set_field(empty_profile(), "process.trigger", "Spec", by="s", vocab=vocab, at=AT).profile
    assert apply_proposals(specialist, procedure_diff(names=()), vocab=vocab, at=AT).refused == [
        ("process.trigger", "specialist_owned")
    ]
    first = apply_proposals(empty_profile(), procedure_diff(names=()), vocab=vocab, at=AT).profile
    confirmed_doc = confirm_proposals(first, ["process.trigger"], vocab=vocab, at=AT).profile
    assert apply_proposals(confirmed_doc, procedure_diff("d2", names=()), vocab=vocab, at=AT).refused == [
        ("process.trigger", "same_value")
    ]
    newer = ProposalDiff("d2", fields=(FieldProposal("process.trigger", "Newer reading", "newer"),))
    replaced = apply_proposals(first, newer, vocab=vocab, at=AT)
    # Spec 17 §3.21 C5: a newer document no longer replaces a proposed single value; it is a conflict.
    assert replaced.refused == [("process.trigger", "conflict")]
    assert replaced.profile["__meta"]["process.trigger"]["documentId"] == "d1"


def test_rows_only_on_an_empty_table(vocab):
    """AC-13.36."""
    r = apply_proposals(empty_profile(), procedure_diff(names=STEP_NAMES + ("Six", "Seven")), vocab=vocab, at=AT)
    assert len(r.profile["process"]["substeps"]) == 6
    assert r.profile["process"]["substep_count"] is None
    assert (step_cell_key(7, "name"), "index_out_of_range") in r.refused
    three = write(vocab, empty_profile(), {"process.substep_count": 3})
    bounded = apply_proposals(three, procedure_diff(), vocab=vocab, at=AT)
    assert len(bounded.profile["process"]["substeps"]) == 3
    started = write(vocab, empty_profile(), {step_cell_key(1, "name"): "Export"})
    refused = apply_proposals(started, procedure_diff(), vocab=vocab, at=AT)
    assert (step_cell_key(2, "name"), "table_not_empty") in refused.refused
    cell = ProposalDiff("d1", step_cells=(FieldProposal(step_cell_key(1, "systems"), ["SAP"], "from SAP"),))
    landed = apply_proposals(started, cell, vocab=vocab, at=AT)
    assert landed.applied == [step_cell_key(1, "systems")]
    missing_row = ProposalDiff("d1", step_cells=(FieldProposal(step_cell_key(4, "systems"), ["SAP"], "from SAP"),))
    assert apply_proposals(started, missing_row, vocab=vocab, at=AT).refused == [
        (step_cell_key(4, "systems"), "index_out_of_range")
    ]


def test_bounds_and_skip_marks(vocab):
    """AC-13.37."""
    for count in (5_000_000, -1):
        diff = ProposalDiff("d1", fields=(FieldProposal("process.volume", {"count": count, "period": "month"}, "q"),))
        assert apply_proposals(empty_profile(), diff, vocab=vocab, at=AT).refused == [
            ("process.volume", "out_of_bounds")
        ]
    base = write(vocab, empty_profile(), {"process.substep_count": 2, **step_changes(1, leave_out=("goal",))})
    skipped = mark_cells_skipped(base, [step_cell_key(1, "goal")], vocab=vocab)
    diff = ProposalDiff("d1", step_cells=(FieldProposal(step_cell_key(1, "goal"), "Done", "done"),))
    lifted = apply_proposals(skipped, diff, vocab=vocab, at=AT).profile
    assert lifted["process"]["substeps"][0]["__skipped"] == []


def test_a_proposal_that_moves_a_rollup_clears_its_confirmation(vocab):
    """AC-13.38."""
    profile = cost_review_profile(vocab, steps=3, filled_steps=2)
    profile = confirm_rollup(confirm_rollup(profile, "roles", vocab=vocab), "systems", vocab=vocab)
    add_role = ProposalDiff(
        "d1", step_cells=(FieldProposal(step_cell_key(3, "roles"), [{"role": "Auditor"}], "the auditor"),)
    )
    r = apply_proposals(profile, add_role, vocab=vocab, at=AT).profile["process"]
    assert (r["roles_confirmed"], r["tools_confirmed"]) == (False, True)
    goal = ProposalDiff("d1", step_cells=(FieldProposal(step_cell_key(3, "goal"), "Done", "done"),))
    g = apply_proposals(profile, goal, vocab=vocab, at=AT).profile["process"]
    assert (g["roles_confirmed"], g["tools_confirmed"]) == (True, True)


def test_confirm_keeps_provenance_and_counts(vocab):
    """AC-13.39."""
    proposed = apply_proposals(empty_profile(), procedure_diff(names=()), vocab=vocab, at=AT).profile
    assert not field_counts(proposed, "process.trigger", vocab=vocab)
    r = confirm_proposals(proposed, ["process.trigger", "process.end_result"], vocab=vocab, at="later")
    meta = r.profile["__meta"]["process.trigger"]
    assert (meta["status"], meta["source"], meta["documentId"], meta["at"]) == ("confirmed", "document", "d1", "later")
    assert meta["quote"].startswith("The review starts")
    assert r.profile["process"]["trigger"] == proposed["process"]["trigger"]
    assert field_counts(r.profile, "process.trigger", vocab=vocab)
    assert r.written == ["process.trigger"]


def test_example_4_confirming_the_step_names_sets_the_count(vocab):
    """AC-13.40."""
    base = context(vocab)
    proposed = apply_proposals(base, procedure_diff(), vocab=vocab, at=AT).profile
    assert len(proposed_keys(proposed)) == 6
    assert score(proposed, vocab=vocab) == (round(3 / 18, 4), 3, 18)
    names = [step_cell_key(i, "name") for i in range(1, 6)]
    confirmed = confirm_proposals(proposed, names, vocab=vocab, at=AT).profile
    assert confirmed["process"]["substep_count"] == 5
    assert score(confirmed, vocab=vocab)[1:] == (9, 78)
    one = apply_proposals(
        empty_profile(),
        ProposalDiff("d1", steps=(StepProposal((FieldProposal("name", "Only", "Only"),)),)),
        vocab=vocab,
        at=AT,
    ).profile
    assert (
        confirm_proposals(one, [step_cell_key(1, "name")], vocab=vocab, at=AT).profile["process"]["substep_count"]
        is None
    )


def test_reject_clears_values_meta_and_trailing_rows(vocab):
    """AC-13.41."""
    diff = ProposalDiff(
        "d1",
        steps=(
            StepProposal((FieldProposal("name", "A", "A"), FieldProposal("roles", [{"role": "Clerk"}], "clerk"))),
            StepProposal((FieldProposal("name", "B", "B"),)),
        ),
    )
    proposed = apply_proposals(empty_profile(), diff, vocab=vocab, at=AT).profile
    assert proposed["process"]["all_roles"] == ["Clerk"]
    r = reject_proposals(proposed, [step_cell_key(2, "name"), step_cell_key(1, "roles")], vocab=vocab, at=AT).profile
    assert len(r["process"]["substeps"]) == 1
    assert r["process"]["substeps"][0]["roles"] == []
    assert "roles" not in r["process"]["substeps"][0]["__meta"]
    assert r["process"]["all_roles"] == []


def test_removing_a_document_removes_only_its_open_proposals(vocab):
    """AC-13.42."""
    d1 = ProposalDiff(
        "d1", fields=(FieldProposal("process.trigger", "T", "t"), FieldProposal("process.end_result", "E", "e"))
    )
    d2 = ProposalDiff("d2", fields=(FieldProposal("process.business_pain", "P", "p"),))
    profile = apply_proposals(
        apply_proposals(empty_profile(), d1, vocab=vocab, at=AT).profile, d2, vocab=vocab, at=AT
    ).profile
    profile = confirm_proposals(profile, ["process.trigger"], vocab=vocab, at=AT).profile
    r = remove_document_proposals(profile, "d1", vocab=vocab, at=AT).profile
    assert r["process"]["trigger"] == "T"
    assert r["process"]["end_result"] == ""
    assert r["process"]["business_pain"] == "P"


def test_proposed_keys_are_in_ask_order(vocab):
    """AC-13.43."""
    diff = ProposalDiff(
        "d1",
        fields=(
            FieldProposal("process.volume", {"count": 1, "period": "month"}, "q"),
            FieldProposal("process.trigger", "T", "t"),
        ),
        steps=(
            StepProposal((FieldProposal("name", "A", "A"), FieldProposal("systems", ["SAP"], "sap"))),
            StepProposal((FieldProposal("name", "B", "B"),)),
        ),
    )
    profile = apply_proposals(empty_profile(), diff, vocab=vocab, at=AT).profile
    assert proposed_keys(profile) == [
        "process.trigger",
        "process.volume",
        step_cell_key(1, "name"),
        step_cell_key(1, "systems"),
        step_cell_key(2, "name"),
    ]


def test_propose_from_idea(vocab):
    """AC-13.44."""
    p = propose_from_idea(empty_profile(), "Monthly cost review", "the cost review we do every month", at=AT)
    assert p["process"]["name"] == "Monthly cost review"
    meta = p["__meta"]["process.name"]
    assert (meta["source"], meta["status"], meta["quote"]) == (
        "expert",
        "proposed",
        "the cost review we do every month",
    )
    named = write(vocab, empty_profile(), {"process.name": "Mine"})
    assert propose_from_idea(named, "Other", "w", at=AT) == named
