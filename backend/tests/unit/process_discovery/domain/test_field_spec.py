"""Tests for the field registry's shape, totals, addresses, whitelists and roll-ups (spec 12).

Why: every other layer derives its fields, weights, questions and whitelists from the registry, so
a wrong key or weight here is a silent error everywhere (a field collected and never scored).
What: checks the registry against the tables of spec 12 §3.4–§3.7 and product §5, using real
producer output (the empty `Profile` dump, `extract_keys()`, `resolve_address`) rather than
hand-typed keys. Implements AC-12.1 to AC-12.6 and AC-12.17 to AC-12.24.
"""

import dataclasses

import pytest

from app.models.process_discovery_schemas import Phase, Profile, Step
from app.services.process_discovery.domain import field_spec as fs

P_TABLE = [
    ("P01", "department", "text", 1, "context"),
    ("P02", "user_function", "text", 1, "context"),
    ("P03", "region", "text", 1, "context"),
    ("P04", "process.name", "text", 1, "find"),
    ("P05", "process.cluster", "object", 1, "find"),
    ("P06", "process.trigger", "text", 1, "boundaries"),
    ("P07", "process.end_result", "text", 1, "boundaries"),
    ("P08", "process.value_at_end", "text", 1, "boundaries"),
    ("P09", "process.business_pain", "text", 1, "boundaries"),
    ("P10", "process.volume", "object", 1, "measure"),
    ("P11", "process.process_owner", "object", 1, "measure"),
    ("P12", "process.baseline_metric", "object", 2, "measure"),
    ("P13", "process.target_metric", "object", 2, "measure"),
    ("P14", "process.variation", "object", 1, "measure"),
    ("P15", "process.sensitive_data", "object_list", 1, "measure"),
    ("P16", "process.substep_count", "number", 1, "step_count"),
]
S_TABLE = [
    ("S01", "name", "text", 1),
    ("S02", "goal", "text", 1),
    ("S03", "activities", "list", 1),
    ("S04", "roles", "object_list", 1),
    ("S05", "owner", "text", 1),
    ("S06", "systems", "list", 1),
    ("S07", "data", "object", 1),
    ("S08", "effort", "object", 1),
    ("S09", "pain_points", "list", 1),
    ("S10", "approvals", "object_list", 1),
    ("S11", "exceptions", "object_list", 1),
    ("S12", "handover", "text", 0),
    ("S13", "decision_type", "object", 1),
    ("S14", "decision_criteria", "object", 0),  # spec 12 §3.13 (2026-11-21)
]

# Product §5.1 and §5.2, default wording, verbatim.
QUESTIONS = {
    "P01": "Which department are you in?",
    "P02": "What is your own role in that department?",
    "P03": "Which region do you work in?",
    "P04": "Thinking about a normal week, which piece of work comes round again and again and takes you the most time?",
    "P06": "What starts this process off?",
    "P07": "What exists at the end that did not exist before?",
    "P08": "Who uses that result, and what for?",
    "P09": "What hurts most about this process today?",
    "P10": "How often does this process run?",
    "P11": "Who owns this process end to end?",
    "P12": "How would you measure how this process performs today?",
    "P13": "Where would that number need to get to?",
    "P14": "Do other teams or regions do this the same way? A yes or no is enough.",
    "P15": "Does it involve personal or sensitive data, or a regulation? A yes or no is enough.",
    "P16": "List the main steps in order, 2 to 6.",
    "S01": "What would you call this step?",
    "S02": "What has to be true for this step to be done?",
    "S03": "What do you actually do in this step?",
    "S04": "Who else is involved, and what do they contribute?",
    "S05": "Who is accountable for this step?",
    "S06": "Which systems or tools do you use here?",
    "S07": "What information goes in, and what comes out?",
    "S08": "How long does this step take, and how often?",
    "S09": "What is annoying or slow about this step?",
    "S10": "Does anything here need an approval or sign-off?",
    "S11": "What goes wrong here, and where do you end up when it does?",
    "S12": "How does the work get to whoever does the next step?",
    "S13": "Is this step mostly fixed rules, judgement, or a mix?",
    "S14": "What do you base that decision on, who sets those criteria, and are they written down?",
}

ALL_SPECS = (*fs.PROFILE_SPECS, *fs.STEP_SPECS)


def spec_of(field_id: str) -> fs.FieldSpec:
    found = fs.spec_by_id(field_id)
    assert found is not None, field_id
    return found


# --- AC-12.1 / AC-12.2: the registry ---------------------------------------------------------


def test_registry_matches_the_process_table():
    """AC-12.1: P01–P16 in declaration order with keys, kinds, weights and phases of §3.4."""
    assert [(s.id, s.key, s.kind, s.weight, s.phase) for s in fs.PROFILE_SPECS] == P_TABLE


def test_registry_matches_the_step_table():
    """AC-12.1: S01–S14 in order; every step spec sits in the `steps` phase."""
    assert [(s.id, s.key, s.kind, s.weight) for s in fs.STEP_SPECS] == S_TABLE
    assert {s.phase for s in fs.STEP_SPECS} == {"steps"}


def test_derived_specs_and_unique_ids():
    """AC-12.1: D01–D02 follow, and every ID is unique across the three series."""
    assert [(d.id, d.key) for d in fs.DERIVED_SPECS] == [("D01", "process.all_roles"), ("D02", "process.all_tools")]
    ids = [s.id for s in ALL_SPECS] + [d.id for d in fs.DERIVED_SPECS]
    assert len(ids) == len(set(ids)) == 32


def test_keys_are_unique_and_shaped_per_series():
    """AC-12.2: P01–P03 top level, P04–P16 under `process.`, S keys bare leaves."""
    p_keys = [s.key for s in fs.PROFILE_SPECS]
    s_keys = [s.key for s in fs.STEP_SPECS]
    assert len(p_keys) == len(set(p_keys)) and len(s_keys) == len(set(s_keys))
    assert all("." not in k for k in p_keys[:3])
    assert all(k.startswith("process.") for k in p_keys[3:])
    assert all("." not in k and "[" not in k for k in s_keys)
    assert [s.is_process for s in fs.PROFILE_SPECS] == [False] * 3 + [True] * 13
    assert fs.PROFILE_SPECS[9].leaf == "volume"


# --- AC-12.3: sub-fields and groups ----------------------------------------------------------


def test_object_specs_declare_scalar_subfields_and_real_groups():
    """AC-12.3: objects declare sub-fields; object_list sub-fields are scalar; groups are real."""
    for spec in ALL_SPECS:
        if spec.kind in ("object", "object_list"):
            assert spec.subfields, spec.id
        else:
            assert not spec.subfields, spec.id
        if spec.kind == "object_list":
            assert all(sf.kind in ("text", "number", "bool") for sf in spec.subfields), spec.id
        names = {sf.key for sf in spec.subfields}
        for group in spec.complete_when:
            assert group and set(group) <= names, spec.id
        assert not (spec.complete_when and spec.validator), spec.id


def test_validators_sit_on_the_documented_fields():
    """AC-12.3: the cross-field and vocabulary rules are validators, nothing else is."""
    assert {s.id for s in ALL_SPECS if s.validator} == {"P03", "P05", "P13", "P14", "P16", "S13", "S14"}
    assert spec_of("P10").complete_when == (("count", "period"), ("raw",))


def test_subfield_label_defaults_to_the_key_with_spaces():
    """§4: `SubFieldSpec.label` defaults to the key with underscores as spaces."""
    assert fs.SubFieldSpec("approver_role", "text").label == "approver role"
    assert fs.SubFieldSpec("x", "text", label="Thing").label == "Thing"


# --- AC-12.4: phases -------------------------------------------------------------------------


def test_phase_strings_match_the_enum():
    """AC-12.4: every phase string in the registry is a `Phase` value."""
    values = {p.value for p in Phase}
    assert set(fs.PHASE_ORDER) <= values
    assert {s.phase for s in ALL_SPECS} <= values
    assert set(fs.PHASE_ORDER) | {"confirm", "finished", "no_candidate"} == values  # confirm: old sessions only


def test_phase_order_and_collecting_phases():
    """AC-12.4 (amended 2026-11-21, §3.20 O10: no `confirm` on the path)."""
    assert fs.PHASE_ORDER == ("context", "find", "boundaries", "measure", "step_count", "steps", "review")
    assert fs.COLLECTING_PHASES == fs.PHASE_ORDER[:5]
    for phase in fs.COLLECTING_PHASES:
        assert fs.specs_for_phase(phase), phase
    assert "finished" not in fs.PHASE_ORDER and "no_candidate" not in fs.PHASE_ORDER
    assert [s.id for s in fs.specs_for_phase("boundaries")] == ["P06", "P07", "P08", "P09"]


# --- AC-12.5: points -------------------------------------------------------------------------


def test_points_are_derived_from_the_weights():
    """AC-12.5 (amended 2026-11-20, short step walk): 18 process points, 12 per step, totals as documented."""
    assert fs.PROCESS_POINTS == 18
    assert fs.STEP_POINTS == 12
    assert [fs.total_points_for(n) for n in (None, 0, 2, 6, 9)] == [18, 18, 42, 90, 90]
    assert [fs.total_points_for(n) for n in (4, 5)] == [66, 78]


def test_limits_and_constants():
    """§3.5: the limits every other layer reads, defined once."""
    assert (fs.MIN_STEPS, fs.MAX_STEPS) == (2, 6)
    assert fs.COMPLETENESS_GATE == 0.80
    assert (fs.FIELD_ASK_LIMIT, fs.REVIEW_ASK_LIMIT, fs.CELL_ASK_LIMIT) == (3, 2, 3)
    assert (fs.WIDENING_LIMIT, fs.CONFIRM_TURN_LIMIT) == (2, 6)
    assert (fs.FIND_FOCUS_TURN, fs.FIND_DIRECT_TURN, fs.ACTIVITIES_SOFT_MAX) == (4, 6, 5)
    assert spec_of("S03").max_items == fs.ACTIVITIES_SOFT_MAX
    assert [s.id for s in fs.scored_step_specs()] == [*(f"S{i:02d}" for i in range(1, 12)), "S13"]


# --- AC-12.6: questions and rules ------------------------------------------------------------


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.id)
def test_every_spec_has_a_rule_and_the_product_question(spec):
    """AC-12.6: a rule on every spec; the product's default wording on all but P05."""
    assert spec.rule.strip()
    assert spec.question == QUESTIONS.get(spec.id, "")


def test_handover_is_unscored_and_asked_once():
    """AC-12.6: S12 has weight 0 and `max_asks == 1`."""
    s12 = spec_of("S12")
    assert (s12.weight, s12.max_asks) == (0, 1)
    assert spec_of("P05").question == ""


# --- AC-12.17: has_any_answer ----------------------------------------------------------------


def _value(profile: dict, spec: fs.FieldSpec):
    node = profile
    for part in spec.key.split("."):
        node = node[part]
    return node


def test_nothing_in_the_empty_profile_is_an_answer():
    """AC-12.17: false for every field of the empty profile and of an empty step."""
    empty = Profile().model_dump(by_alias=True)
    for spec in fs.PROFILE_SPECS:
        assert not fs.has_any_answer(spec, _value(empty, spec)), spec.id
    step = Step().model_dump(by_alias=True)
    for spec in fs.STEP_SPECS:
        assert not fs.has_any_answer(spec, step[spec.key]), spec.id


@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.id)
def test_one_subfield_set_is_an_answer(spec):
    """AC-12.17: true after one sub-field (or the value itself) is set."""
    filled = {"text": "x", "list": ["x"], "number": 3, "bool": True}
    if spec.kind == "object":
        sf = spec.subfields[0]
        value = {sf.key: filled[sf.kind]}
    elif spec.kind == "object_list":
        sf = spec.subfields[0]
        value = [{sf.key: filled[sf.kind]}]
    else:
        value = filled[spec.kind]
    assert fs.has_any_answer(spec, value)


def test_a_stored_false_is_never_an_answer():
    """F-05.5: `none_identified: false` is not an answer."""
    owner = spec_of("P11")
    assert not fs.has_any_answer(owner, {"role": "", "none_identified": False})
    assert fs.has_any_answer(owner, {"role": "", "none_identified": True})
    assert fs.has_any_answer(spec_of("S04"), [{"none": True}])


# --- AC-12.18: addresses ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected_id", "index"),
    [
        ("department", "P01", None),
        ("process.volume", "P10", None),
        ("volume", "P10", None),
        ("process.substeps[2].systems", "S06", 2),
        ("name", "P04", None),
        ("process.name", "P04", None),
    ],
)
def test_resolve_address_resolves_the_three_forms(key, expected_id, index):
    """AC-12.18: dotted key, 1-based step cell and bare leaf all resolve."""
    resolved = fs.resolve_address(key)
    assert resolved is not None
    spec, idx = resolved
    assert (spec.id, idx) == (expected_id, index)


@pytest.mark.parametrize(
    "key",
    ["process.substeps[0].name", "process.substeps[2].unknown", "process.all_roles", "substeps_complete", "__meta", ""],
)
def test_resolve_address_refuses_what_is_not_a_field(key):
    """AC-12.18: step 0, unknown leaves, roll-ups, flags and sidecars do not resolve."""
    assert fs.resolve_address(key) is None


def test_step_keys():
    """AC-12.18: step cell keys are 1-based; the template uses `i`."""
    assert fs.step_cell_key(1, "roles") == "process.substeps[1].roles"
    assert fs.step_key_template("roles") == "process.substeps[i].roles"
    assert fs.step_spec_by_leaf("name") == spec_of("S01")
    assert fs.step_spec_by_leaf("volume") is None
    assert fs.spec_by_id("P99") is None


# --- AC-12.19 – AC-12.21: whitelists ---------------------------------------------------------

STEP_TEMPLATES = [f"process.substeps[i].{leaf}" for _, leaf, _, _ in S_TABLE]


def test_extract_keys():
    """AC-12.19: every P key except the cluster, then every step template (S14 since §3.13); nothing else."""
    keys = fs.extract_keys()
    assert keys == [k for _, k, *_ in P_TABLE if k != "process.cluster"] + STEP_TEMPLATES
    forbidden = {"process.cluster", "process.all_roles", "process.all_tools", "__meta", "__skipped"}
    forbidden |= {f"process.{f}" for f in fs.FLAG_KEYS} | set(fs.FLAG_KEYS)
    forbidden |= {"placement_confirmed", "assent", "confirmed"}
    assert not forbidden & set(keys)
    for key in keys:
        if "[i]" not in key:
            assert fs.resolve_address(key) is not None


def test_proposal_keys():
    """AC-12.20: P04, P06–P15 and the 12 step templates."""
    expected = ["P04", "P06", "P07", "P08", "P09", "P10", "P11", "P12", "P13", "P14", "P15"]
    assert fs.proposal_keys() == [spec_of(i).key for i in expected] + STEP_TEMPLATES


def test_specialist_keys():
    """§3.7: every P key and every step template."""
    assert fs.specialist_keys() == [k for _, k, *_ in P_TABLE] + STEP_TEMPLATES


def test_whitelists_are_filters_of_the_registry(monkeypatch):
    """AC-12.21: flipping `extract` or `propose` on a copied spec removes it from the list."""
    trigger = spec_of("P06")
    patched = tuple(
        dataclasses.replace(s, extract=False, propose=False) if s is trigger else s for s in fs.PROFILE_SPECS
    )
    monkeypatch.setattr(fs, "PROFILE_SPECS", patched)
    assert "process.trigger" not in fs.extract_keys()
    assert "process.trigger" not in fs.proposal_keys()
    assert "process.trigger" in fs.specialist_keys()


# --- AC-12.22 / AC-12.23: lenient rows and shape hints ---------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("AP clerk", [{"role": "AP clerk"}]),
        (["AP clerk", "Site manager"], [{"role": "AP clerk"}, {"role": "Site manager"}]),
        ({"role": "AP clerk"}, [{"role": "AP clerk"}]),
        ([{"name": "AP clerk"}], [{"role": "AP clerk"}]),
        ([{"none": True}], [{"none": True}]),
        (42, None),
        (None, None),
    ],
)
def test_lenient_object_rows(value, expected):
    """AC-12.22: each model shape folds onto rows; non-row-like input is `None`."""
    assert fs.lenient_object_rows(spec_of("S04"), value) == expected


def test_required_subfield():
    """§3.4: the identifying sub-field of each row kind."""
    assert [fs.required_subfield(spec_of(i)) for i in ("P15", "S04", "S10", "S11")] == [
        "item",
        "role",
        "approver_role",
        "description",
    ]
    assert fs.required_subfield(spec_of("P06")) is None


def test_object_list_shape_hints():
    """AC-12.23: one line per P15, S04, S10, S11 naming every sub-field, optional ones marked."""
    hints = fs.object_list_shape_hints()
    keys = ["process.sensitive_data", *(f"process.substeps[i].{leaf}" for leaf in ("roles", "approvals", "exceptions"))]
    assert len(hints) == 4
    for hint, key, spec_id in zip(hints, keys, ("P15", "S04", "S10", "S11"), strict=True):
        assert f'"{key}"' in hint
        for sf in spec_of(spec_id).subfields:
            assert f'"{sf.key}"' in hint
            assert (f'"{sf.key}": <{sf.kind}, optional>' in hint) is (not sf.required)


# --- AC-12.24: roll-ups ----------------------------------------------------------------------


def _profile_with_steps(*steps: dict) -> dict:
    profile = Profile().model_dump(by_alias=True)
    profile["process"]["substeps"] = [Step.model_validate(s).model_dump(by_alias=True) for s in steps]
    return profile


def test_recompute_derived_rebuilds_from_scratch():
    """AC-12.24: case-insensitive de-dup, first spelling kept, none rows ignored, removals disappear."""
    profile = _profile_with_steps(
        {"roles": [{"role": "AP clerk"}, {"role": "Controller"}], "systems": ["SAP", "Excel"]},
        {"roles": [{"none": True}], "systems": ["sap", " Outlook "]},
        {"roles": [{"role": "ap CLERK"}], "systems": []},
    )
    profile["process"]["all_roles"] = ["Stale role"]
    derived = fs.recompute_derived(profile)
    assert derived == {
        "process.all_roles": ["AP clerk", "Controller"],
        "process.all_tools": ["SAP", "Excel", "Outlook"],
    }
    profile["process"]["substeps"][0]["roles"] = [{"role": "AP clerk"}]
    assert fs.recompute_derived(profile)["process.all_roles"] == ["AP clerk"]


def test_recompute_derived_on_garbage_is_empty():
    """AC-12.24: a profile without steps rolls up to empty lists, never raises."""
    assert fs.recompute_derived({}) == {"process.all_roles": [], "process.all_tools": []}
