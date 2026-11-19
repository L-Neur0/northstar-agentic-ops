"""Tests for coercion and the merge rules by kind (spec 13 §3.2–§3.3; AC-13.3 to AC-13.11).

Why: a bad change must never corrupt the profile, and every write path shares these filters.
What: scalar coercions, list accumulation, object merges, the P11 none flag, lenient rows, the none
row and `loops_back_to`, mostly through `apply_changes` with registry keys, as the interview writes.
"""

import pytest

from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.profile.coercion import coerce_count, coerce_number, coerce_text
from app.services.process_discovery.profile.mutate import apply_changes
from app.services.process_discovery.profile.shapes import empty_profile
from app.services.process_discovery.profile.verdicts import grade

from .builders import AT, cost_review_profile


def write(vocab, profile, changes):
    return apply_changes(profile, changes, vocab=vocab, at=AT)


def test_scalar_coercion():
    """AC-13.3."""
    assert coerce_number("12") == 12
    assert coerce_number(3.7) == 3
    for bad in ("inf", float("nan"), "1e400", True, -4, "x"):
        assert coerce_number(bad) is None
    assert coerce_text(42) == "42"
    assert coerce_text("   ") is None
    assert coerce_count("x") == 0
    assert coerce_count(-2) == 0


def test_lists_accumulate_case_insensitively(vocab):
    """AC-13.4."""
    key = step_cell_key(1, "systems")
    first = write(vocab, empty_profile(), {key: ["SAP"]})
    second = write(vocab, first.profile, {key: ["sap", "Excel"]})
    assert second.profile["process"]["substeps"][0]["systems"] == ["SAP", "Excel"]
    third = write(vocab, second.profile, {key: "excel"})
    assert key not in third.written
    fourth = write(vocab, third.profile, {key: "Power BI"})
    assert fourth.profile["process"]["substeps"][0]["systems"][-1] == "Power BI"


def test_text_replaces_and_field_spelling_is_normalised(vocab):
    """AC-13.5."""
    r = write(vocab, empty_profile(), {"process.trigger": "  month end  ", "region": "europe"})
    r = write(vocab, r.profile, {"process.trigger": "Month-end close in the ledger"})
    assert r.profile["process"]["trigger"] == "Month-end close in the ledger"
    assert write(vocab, empty_profile(), {"region": "europe"}).profile["region"] == "Europe"
    germany = write(vocab, empty_profile(), {"region": "Germany"}).profile
    assert germany["region"] == "Germany"
    assert grade(germany, "region", vocab=vocab).status == "invalid"
    p14 = write(vocab, empty_profile(), {"process.variation": {"same": "Partly", "differences": "Asia"}}).profile
    assert p14["process"]["variation"]["same"] == "partly"


def test_objects_merge_sub_field_by_sub_field(vocab):
    """AC-13.6."""
    r = write(vocab, empty_profile(), {"process.volume": {"count": "400", "bogus": 1}})
    r = write(vocab, r.profile, {"process.volume": {"period": "year"}})
    assert r.profile["process"]["volume"] == {"count": 400, "period": "year", "raw": ""}
    r = write(vocab, r.profile, {"process.volume": {"period": "month"}})
    assert r.profile["process"]["volume"]["period"] == "month"
    bad = write(vocab, empty_profile(), {"process.volume": {"count": -3}})
    assert bad.refused == [("process.volume", "shape")]


def test_the_owner_none_flag(vocab):
    """AC-13.7."""
    key = "process.process_owner"
    none = write(vocab, empty_profile(), {key: {"none_identified": True}}).profile
    assert none["process"]["process_owner"]["none_identified"] is True
    named = write(vocab, none, {key: {"role": "Controller"}}).profile
    assert named["process"]["process_owner"] == {"role": "Controller", "none_identified": False}
    both = write(vocab, empty_profile(), {key: {"role": "Controller", "none_identified": True}}).profile
    assert both["process"]["process_owner"] == {"role": "Controller", "none_identified": False}
    flag_on_role = write(vocab, named, {key: {"none_identified": True}})
    assert flag_on_role.written == []
    assert flag_on_role.profile["process"]["process_owner"]["role"] == "Controller"
    blank = write(vocab, none, {key: {"role": "  "}})
    assert blank.profile["process"]["process_owner"]["none_identified"] is True


@pytest.mark.parametrize(
    "value",
    ["AP clerk", ["AP clerk"], {"role": "AP clerk"}, [{"name": "AP clerk"}], [{"role": "AP clerk", "x": 1}]],
)
def test_lenient_role_shapes_land_as_rows(vocab, value):
    """AC-13.8."""
    r = write(vocab, empty_profile(), {step_cell_key(1, "roles"): value})
    assert r.profile["process"]["substeps"][0]["roles"] == [{"role": "AP clerk", "contribution": ""}]


def test_rows_without_identity_are_dropped_and_malformed_entries_skipped(vocab):
    """AC-13.8."""
    key = step_cell_key(1, "roles")
    assert write(vocab, empty_profile(), {key: [{"contribution": "signs"}]}).refused == [(key, "shape")]
    r = write(vocab, empty_profile(), {key: [42, {"role": "Manager"}]})
    assert r.profile["process"]["substeps"][0]["roles"] == [{"role": "Manager", "contribution": ""}]


def test_example_1_roles_merge(vocab):
    """AC-13.9 and AC-13.10 (spec 13 example 1)."""
    key = step_cell_key(2, "roles")
    base = write(vocab, empty_profile(), {key: [{"role": "Controller"}]}).profile
    merged = write(vocab, base, {key: ["Site manager", {"role": "controller", "contribution": "checks variances"}]})
    rows = merged.profile["process"]["substeps"][1]["roles"]
    assert rows == [
        {"role": "Controller", "contribution": "checks variances"},
        {"role": "Site manager", "contribution": ""},
    ]
    again = write(vocab, merged.profile, {key: [{"role": "Controller", "contribution": "other"}]})
    assert again.profile["process"]["substeps"][1]["roles"][0]["contribution"] == "checks variances"
    none = write(vocab, merged.profile, {key: [{"none": True}]})
    assert none.written == []
    assert none.profile == merged.profile


@pytest.mark.parametrize("leaf", ["roles", "approvals", "exceptions"])
def test_the_none_row_lands_on_an_empty_cell_and_gives_way(vocab, leaf):
    """AC-13.10."""
    key = step_cell_key(1, leaf)
    r = write(vocab, empty_profile(), {key: [{"none": True}]})
    assert r.profile["process"]["substeps"][0][leaf] == [{"none": True}]
    required = {"roles": "role", "approvals": "approver_role", "exceptions": "description"}[leaf]
    real = write(vocab, r.profile, {key: [{required: "Controller"}]})
    assert {"none": True} not in real.profile["process"]["substeps"][0][leaf]


def test_the_none_row_on_a_filled_cell_does_not_reopen_or_reset(vocab):
    """AC-13.10: on a closed walk with confirmed lists, a none row on a filled cell changes nothing."""
    from app.services.process_discovery.profile.mutate import confirm_rollup

    profile = cost_review_profile(vocab, steps=2)
    profile = confirm_rollup(confirm_rollup(profile, "roles", vocab=vocab), "systems", vocab=vocab)
    r = write(vocab, profile, {step_cell_key(1, "roles"): [{"none": True}]})
    assert r.written == []
    assert r.profile["process"]["roles_confirmed"] is True
    assert r.profile["process"]["substeps_complete"] is True
    sensitive = write(vocab, empty_profile(), {"process.sensitive_data": [{"none": True}]})
    assert sensitive.profile["process"]["sensitive_data"] == [{"none": True}]


def test_loops_back_to_is_bounded(vocab):
    """AC-13.11."""
    base = write(vocab, empty_profile(), {"process.substep_count": 4}).profile
    own = write(vocab, base, {step_cell_key(3, "exceptions"): [{"description": "late", "loops_back_to": 3}]})
    assert own.profile["process"]["substeps"][2]["exceptions"] == [{"description": "late", "loops_back_to": None}]
    far = write(vocab, base, {step_cell_key(3, "exceptions"): [{"description": "late", "loops_back_to": 9}]})
    assert far.profile["process"]["substeps"][2]["exceptions"][0]["loops_back_to"] is None
    ok = write(vocab, base, {step_cell_key(3, "exceptions"): [{"description": "late", "loops_back_to": 2}]})
    assert ok.profile["process"]["substeps"][2]["exceptions"][0]["loops_back_to"] == 2
