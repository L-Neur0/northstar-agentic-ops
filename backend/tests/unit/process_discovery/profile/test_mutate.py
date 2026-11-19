"""Tests for `apply_changes`: whitelist, writability, meta, invalidation, roll-ups (spec 13 §3.4, §3.8; AC-13.17 to AC-13.26).

Why: the expert path is the most frequent writer, and the rules it protects (no model-written flag,
a specialist outranks a later write, a proposal is replaced, roll-ups rebuilt) fail silently.
What: each AC with profiles built by the real writers, keys from the registry.
"""

import copy
import logging

from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.profile.mutate import (
    allowed_changes,
    apply_changes,
    confirm_rollup,
    set_field,
    unknown_change_keys,
)
from app.services.process_discovery.profile.proposals import FieldProposal, ProposalDiff, apply_proposals
from app.services.process_discovery.profile.shapes import empty_profile

from .builders import AT, cost_review_profile


def write(vocab, profile, changes):
    return apply_changes(profile, changes, vocab=vocab, at=AT)


def confirmed_lists(vocab, steps=2):
    profile = cost_review_profile(vocab, steps=steps)
    return confirm_rollup(confirm_rollup(profile, "roles", vocab=vocab), "systems", vocab=vocab)


def test_a_step_write_on_a_closed_loop_reopens_it(vocab):
    """AC-13.17: a write that leaves a row incomplete keeps all three flags down."""
    from app.services.process_discovery.profile.mutate import mark_cells_skipped

    profile = cost_review_profile(vocab, steps=2, filled_steps=1)
    profile = write(vocab, profile, {k: v for k, v in _step2_without_data().items()}).profile
    profile = mark_cells_skipped(profile, [step_cell_key(2, "data")], vocab=vocab)
    profile = confirm_rollup(confirm_rollup(profile, "roles", vocab=vocab), "systems", vocab=vocab)
    assert profile["process"]["substeps_complete"] is True
    r = write(vocab, profile, {step_cell_key(2, "data"): {"inputs": ["actuals"]}})
    proc = r.profile["process"]
    assert (proc["substeps_complete"], proc["roles_confirmed"], proc["tools_confirmed"]) == (False, False, False)


def _step2_without_data():
    from .builders import step_changes

    return step_changes(2, leave_out=("data",))


def test_a_write_that_changes_nothing_does_not_reopen(vocab):
    """AC-13.17."""
    profile = confirmed_lists(vocab)
    r = write(vocab, profile, {step_cell_key(1, "systems"): ["sap"]})
    assert r.written == []
    assert r.profile["process"]["roles_confirmed"] is True


def test_roles_and_systems_writes_reset_only_their_own_flag(vocab):
    """AC-13.18 (on an open walk)."""
    profile = cost_review_profile(vocab, steps=3, filled_steps=2)
    profile = confirm_rollup(confirm_rollup(profile, "roles", vocab=vocab), "systems", vocab=vocab)
    roles = write(vocab, profile, {step_cell_key(3, "roles"): ["Controller"]}).profile["process"]
    assert (roles["roles_confirmed"], roles["tools_confirmed"]) == (False, True)
    systems = write(vocab, profile, {step_cell_key(3, "systems"): ["SAP"]}).profile["process"]
    assert (systems["roles_confirmed"], systems["tools_confirmed"]) == (True, False)


def test_allowed_changes_is_the_extract_whitelist():
    """AC-13.19."""
    changes = {
        "department": "Finance",
        "process.trigger": "x",
        "process.substeps[2].roles": ["A"],
        "process": {"volume": {"count": 1}, "cluster": {"code": "FIN"}, "roles_confirmed": True},
        "process.cluster": {"code": "FIN"},
        "process.substeps_complete": True,
        "process.roles_confirmed": True,
        "process.tools_confirmed": True,
        "process.substep_count_rejected": 9,
        "process.all_roles": ["A"],
        "process.all_tools": ["B"],
        "__meta": {},
        "process.substeps[1].__skipped": ["x"],
        "invented": 1,
    }
    assert allowed_changes(changes) == {
        "department": "Finance",
        "process.trigger": "x",
        "process.substeps[2].roles": ["A"],
        "process": {"volume": {"count": 1}},
    }
    assert allowed_changes(["not", "a", "mapping"]) == {}


def test_apply_changes_refuses_code_owned_keys_even_unfiltered(vocab):
    """AC-13.20."""
    r = write(
        vocab,
        empty_profile(),
        {"process.cluster": {"code": "FIN"}, "process.roles_confirmed": True, "process.substeps_complete": True},
    )
    assert {reason for _, reason in r.refused} == {"not_writable"}
    assert r.profile["process"]["cluster"]["code"] == ""
    assert r.profile["process"]["roles_confirmed"] is False
    assert unknown_change_keys({"volume": {"count": 1}, "process.volume": {}, "department": "x"}) == ["volume"]
    assert write(vocab, empty_profile(), {"volume": {"count": 1}}).refused == [("volume", "unknown_key")]


def test_example_2_partial_write_and_cross_field_verdict(vocab):
    """AC-13.21."""
    r = write(vocab, empty_profile(), {"process.volume": {"count": 400}, "process.cluster": {"code": "FIN"}})
    assert r.written == ["process.volume"]
    verdict = r.verdicts["process.volume"]
    assert verdict.status == "partial"
    assert verdict.missing == ("period",)
    assert verdict.reason == "Volume still needs: period."
    assert "process.cluster" not in r.verdicts
    both = write(
        vocab,
        empty_profile(),
        {
            "process.baseline_metric": {"value": "4", "unit": "hours"},
            "process.target_metric": {"value": "2", "unit": "days"},
        },
    )
    assert both.verdicts["process.target_metric"].status == "invalid"


def test_landed_writes_record_expert_meta_on_the_right_container(vocab):
    """AC-13.22."""
    first = write(vocab, empty_profile(), {"department": "Finance"}).profile
    r = write(vocab, first, {"process.trigger": "x", step_cell_key(1, "goal"): "done"})
    meta = r.profile["__meta"]["process.trigger"]
    assert meta == {"source": "expert", "status": "confirmed", "documentId": None, "quote": None, "by": None, "at": AT}
    assert r.profile["process"]["substeps"][0]["__meta"]["goal"]["source"] == "expert"
    assert r.profile["__meta"]["department"] == first["__meta"]["department"]


def test_a_specialist_field_is_refused(vocab):
    """AC-13.23."""
    profile = set_field(empty_profile(), "process.trigger", "Spec value", by="spec-1", vocab=vocab, at=AT).profile
    r = write(vocab, profile, {"process.trigger": "Expert value"})
    assert r.refused == [("process.trigger", "specialist_owned")]
    assert r.profile["process"]["trigger"] == "Spec value"
    assert r.profile["__meta"]["process.trigger"]["source"] == "specialist"


def test_an_expert_value_replaces_a_proposal(vocab):
    """AC-13.24."""
    base = write(vocab, empty_profile(), {"process.substep_count": 2}).profile
    diff = ProposalDiff("d1", step_cells=(FieldProposal(step_cell_key(1, "systems"), ["Excel"], "in Excel"),))
    proposed = apply_proposals(base, diff, vocab=vocab, at=AT).profile
    r = write(vocab, proposed, {step_cell_key(1, "systems"): ["SAP"]})
    cell = r.profile["process"]["substeps"][0]
    assert cell["systems"] == ["SAP"]
    assert cell["__meta"]["systems"]["source"] == "expert"
    assert cell["__meta"]["systems"]["quote"] is None


def test_apply_changes_never_mutates_and_ignores_non_mappings(vocab):
    """AC-13.25."""
    profile = cost_review_profile(vocab, steps=2)
    before = copy.deepcopy(profile)
    write(vocab, profile, {"process.trigger": "new", step_cell_key(1, "roles"): ["Auditor"]})
    assert profile == before
    r = apply_changes(profile, "junk", vocab=vocab, at=AT)  # type: ignore[arg-type]
    assert r.profile == before and r.written == []


def test_rollups_are_rebuilt_after_every_write(vocab):
    """AC-13.26."""
    r = write(
        vocab, empty_profile(), {step_cell_key(1, "systems"): ["SAP"], step_cell_key(2, "systems"): ["sap", "Excel"]}
    )
    assert r.profile["process"]["all_tools"] == ["SAP", "Excel"]
    none = write(vocab, empty_profile(), {step_cell_key(1, "roles"): [{"none": True}]})
    assert none.profile["process"]["all_roles"] == []


def test_refusals_are_logged_without_the_value(vocab, caplog):
    """AC-13.12 / AC-13.54: key, reason and value type only."""
    caplog.set_level(logging.WARNING, logger="app.profile")
    base = write(vocab, empty_profile(), {"process.substep_count": 4}).profile
    write(vocab, base, {step_cell_key(5, "name"): "SENTINEL-VALUE"})
    record = next(r for r in caplog.records if r.getMessage() == "profile_write_refused")
    assert record.reason == "index_out_of_range"  # type: ignore[attr-defined]
    assert "SENTINEL-VALUE" not in str(record.__dict__)
