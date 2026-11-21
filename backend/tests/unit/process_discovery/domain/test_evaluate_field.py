"""Tests for `evaluate_field`, the single definition of "answered" (spec 12 §3.2, §3.4, §3.10).

Why: completeness, *Finish*, the next question and the review screen all read this one Verdict.
If it calls a half-answered volume complete, the score lies; if its sentence is vague, the agent
re-asks the whole question instead of the missing part.
What: the worked examples and validator sentences of spec 12, graded against the real NIG
vocabulary, plus wording overrides. Implements AC-12.7 to AC-12.16 and AC-12.45.
"""

import pytest
from pydantic import ValidationError

from app.models.process_discovery_schemas import Profile
from app.services.process_discovery.domain import field_spec as fs
from app.services.process_discovery.domain.field_spec import Vocabulary, WordingOverrides, evaluate_field


def spec(field_id: str) -> fs.FieldSpec:
    found = fs.spec_by_id(field_id)
    assert found is not None
    return found


def empty_profile() -> dict:
    return Profile().model_dump(by_alias=True)


def grade(field_id, value, vocab, profile=None):
    return evaluate_field(spec(field_id), value, profile if profile is not None else empty_profile(), vocab)


# --- AC-12.7 / AC-12.8: volume -----------------------------------------------------------------


def test_volume_with_count_only_names_the_period(nig_vocabulary):
    """AC-12.7."""
    verdict = grade("P10", {"count": 400, "period": "", "raw": ""}, nig_vocabulary)
    assert verdict == fs.Verdict("partial", ("period",), "Volume still needs: period.")
    assert not verdict.is_complete


def test_volume_raw_alone_is_complete(nig_vocabulary):
    """AC-12.8: the second group is enough."""
    verdict = grade("P10", {"count": None, "period": "", "raw": "a few hundred a month"}, nig_vocabulary)
    assert verdict.status == "complete" and verdict.reason == "" and verdict.is_complete


def test_empty_volume_asks_for_the_first_group(nig_vocabulary):
    """AC-12.8: a tie goes to the first declared group, not the shortest."""
    verdict = grade("P10", {"count": None, "period": "", "raw": ""}, nig_vocabulary)
    assert verdict.status == "partial"
    assert verdict.missing == ("count", "period")
    assert verdict.reason == "Volume still needs: count, period."


def test_a_bool_count_is_not_a_number(nig_vocabulary):
    """§3.2: a number is present when not null and not a bool."""
    assert grade("P10", {"count": True, "period": "month"}, nig_vocabulary).missing == ("count",)


# --- AC-12.9 / AC-12.10: owner, baseline -------------------------------------------------------


def test_owner_none_flag(nig_vocabulary):
    """AC-12.9: `none_identified: false` is not an answer; `true` is."""
    partial = grade("P11", {"role": "", "none_identified": False}, nig_vocabulary)
    assert (partial.status, partial.missing) == ("partial", ("role",))
    assert grade("P11", {"role": "", "none_identified": True}, nig_vocabulary).is_complete


def test_qualitative_baseline_is_complete(nig_vocabulary):
    """AC-12.10."""
    value = {"value": "", "unit": "", "qualitative": "takes most of the first week", "estimated": False}
    assert grade("P12", value, nig_vocabulary).is_complete


# --- AC-12.11: target --------------------------------------------------------------------------


def _with_baseline(unit: str, qualitative: str = "") -> dict:
    profile = empty_profile()
    profile["process"]["baseline_metric"] = {
        "value": "3" if unit else "",
        "unit": unit,
        "qualitative": qualitative,
        "estimated": False,
    }
    return profile


def test_target_in_another_unit_is_invalid(nig_vocabulary):
    """AC-12.11: the reason names both units."""
    verdict = grade("P13", {"value": "2", "unit": "days"}, nig_vocabulary, _with_baseline("hours"))
    assert verdict.status == "invalid"
    assert verdict.reason == ('The target is in "days" but the time today is in "hours"; both need the same unit.')


def test_target_unit_comparison_ignores_case_and_spaces(nig_vocabulary):
    """AC-12.11: "days" and " Days " are the same unit."""
    assert grade("P13", {"value": "2", "unit": "days"}, nig_vocabulary, _with_baseline(" Days ")).is_complete


def test_target_against_a_qualitative_baseline_is_complete(nig_vocabulary):
    """AC-12.11: no unit to compare with."""
    profile = _with_baseline("", qualitative="slow")
    assert grade("P13", {"value": "2", "unit": "days"}, nig_vocabulary, profile).is_complete


def test_target_without_unit_is_partial(nig_vocabulary):
    """§3.4 validator table."""
    verdict = grade("P13", {"value": "2", "unit": ""}, nig_vocabulary)
    assert verdict == fs.Verdict("partial", ("unit",), "Target still needs: unit.")


# --- AC-12.12: object lists --------------------------------------------------------------------

OBJECT_LISTS = {"P15": "Sensitive data or regulation", "S04": "Roles involved", "S10": "Approvals", "S11": "Exceptions"}


@pytest.mark.parametrize("field_id", OBJECT_LISTS)
def test_object_list_none_row_and_empty(field_id, nig_vocabulary):
    """AC-12.12: the none row is complete; an empty list is partial with the "none" sentence."""
    assert grade(field_id, [{"none": True}], nig_vocabulary).is_complete
    verdict = grade(field_id, [], nig_vocabulary)
    required = fs.required_subfield(spec(field_id))
    assert required is not None
    label = required.replace("_", " ")
    assert verdict.status == "partial"
    assert verdict.missing == (required,)
    assert verdict.reason == f'{OBJECT_LISTS[field_id]} still needs: {label}. "There are none" is also an answer.'


@pytest.mark.parametrize("field_id", OBJECT_LISTS)
def test_object_list_row_without_its_required_subfield(field_id, nig_vocabulary):
    """AC-12.12: a row lacking its identifying sub-field is partial; one real row is complete."""
    the_spec = spec(field_id)
    required = fs.required_subfield(the_spec)
    optional = next(sf.key for sf in the_spec.subfields if not sf.required)
    filler = 2 if optional == "loops_back_to" else "x"
    assert grade(field_id, [{optional: filler}], nig_vocabulary).status == "partial"
    assert grade(field_id, [{required: "x"}], nig_vocabulary).is_complete


def test_approvals_sentence_matches_the_spec(nig_vocabulary):
    """§3.2 worked example, verbatim."""
    assert grade("S10", [], nig_vocabulary).reason == (
        'Approvals still needs: approver role. "There are none" is also an answer.'
    )


# --- AC-12.13: step count ----------------------------------------------------------------------


def test_step_count(nig_vocabulary):
    """AC-12.13."""
    assert grade("P16", 4, nig_vocabulary).is_complete
    empty = grade("P16", None, nig_vocabulary)
    assert empty == fs.Verdict("partial", ("substep_count",), "Number of main steps has not been answered yet.")
    rejected = empty_profile()
    rejected["process"]["substep_count_rejected"] = 13
    verdict = grade("P16", None, nig_vocabulary, rejected)
    assert verdict.status == "invalid"
    assert verdict.reason == "13 steps is outside 2–6: group them into at most 6 main steps."
    assert grade("P16", True, nig_vocabulary).status == "partial"
    assert grade("P16", "4", nig_vocabulary).status == "partial"


@pytest.mark.parametrize("count", [1, 7])
def test_out_of_range_count_is_invalid(count, nig_vocabulary):
    """AC-12.13 / §3.4: same sentence with that number."""
    verdict = grade("P16", count, nig_vocabulary)
    assert verdict.status == "invalid"
    assert verdict.reason.startswith(f"{count} steps is outside 2–6")


# --- AC-12.14: region --------------------------------------------------------------------------


def test_region(nig_vocabulary):
    """AC-12.14."""
    assert grade("P03", "europe", nig_vocabulary).is_complete
    assert grade("P03", " Asia-Pacific ", nig_vocabulary).is_complete
    invalid = grade("P03", "Germany", nig_vocabulary)
    assert invalid.status == "invalid"
    assert invalid.reason == '"Germany" is not one of the regions: North America, Europe, Middle East, Asia-Pacific.'
    assert grade("P03", "", nig_vocabulary) == fs.Verdict("partial", ("region",), "Region has not been answered yet.")
    assert nig_vocabulary.region("europe") == "Europe"
    assert nig_vocabulary.region("Germany") is None


# --- AC-12.15: cluster -------------------------------------------------------------------------


def test_cluster(nig_vocabulary):
    """AC-12.15."""
    assert grade("P05", {"code": "FIN", "name": "Finance", "decided_by": "proposal"}, nig_vocabulary).is_complete
    invalid = grade("P05", {"code": "XYZ", "name": "", "decided_by": ""}, nig_vocabulary)
    assert (invalid.status, invalid.reason) == ("invalid", '"XYZ" is not one of the clusters.')
    empty = grade("P05", {"code": "", "name": "", "decided_by": ""}, nig_vocabulary)
    assert empty == fs.Verdict("partial", ("code",), "Cluster has not been confirmed yet.")


# --- AC-12.16: variation -----------------------------------------------------------------------


def test_variation(nig_vocabulary):
    """AC-12.16."""
    assert grade("P14", {"same": "yes", "differences": ""}, nig_vocabulary).is_complete
    partial = grade("P14", {"same": "no", "differences": ""}, nig_vocabulary)
    assert partial == fs.Verdict("partial", ("differences",), "Same way everywhere still needs: differences.")
    assert grade("P14", {"same": "partly", "differences": "Asia uses a form"}, nig_vocabulary).is_complete
    invalid = grade("P14", {"same": "maybe", "differences": ""}, nig_vocabulary)
    assert (invalid.status, invalid.reason) == ("invalid", "Same way everywhere must be yes, no or partly.")
    empty = grade("P14", {"same": "", "differences": ""}, nig_vocabulary)
    assert (empty.status, empty.reason) == ("partial", "Same way everywhere has not been answered yet.")


# --- Text, list and step objects ---------------------------------------------------------------


def test_text_list_and_step_objects(nig_vocabulary):
    """§3.2 rule 5 and the step object groups (S07 both lists, S08 both texts)."""
    assert grade("P06", "  ", nig_vocabulary) == fs.Verdict(
        "partial", ("trigger",), "Trigger has not been answered yet."
    )
    assert grade("P06", "Month-end close", nig_vocabulary).is_complete
    assert grade("S06", [], nig_vocabulary).status == "partial"
    assert grade("S06", ["SAP"], nig_vocabulary).is_complete
    assert grade("S07", {"inputs": ["invoice"], "outputs": []}, nig_vocabulary).missing == ("outputs",)
    assert grade("S08", {"duration": "2h", "frequency": "weekly"}, nig_vocabulary).is_complete
    assert grade("S08", "not a dict", nig_vocabulary).missing == ("duration", "frequency")


# --- AC-12.45: wording overrides ---------------------------------------------------------------


def test_unknown_wording_id_is_rejected():
    """AC-12.45: an override for a field that does not exist is a config error."""
    with pytest.raises(ValidationError, match="P99"):
        WordingOverrides.model_validate({"fields": {"P99": {"label": "Nope"}}})


def test_label_override_reaches_the_reason(nig_vocabulary):
    """AC-12.45: `Vocabulary.label` returns the override and the partial sentence uses it."""
    wording = WordingOverrides.model_validate({"fields": {"P06": {"label": "Starting point"}}})
    vocab = Vocabulary(taxonomy=nig_vocabulary.taxonomy, regions=nig_vocabulary.regions, wording=wording)
    assert vocab.label(spec("P06")) == "Starting point"
    assert vocab.question(spec("P06")) == spec("P06").question
    assert evaluate_field(spec("P06"), "", empty_profile(), vocab).reason.startswith("Starting point")
    assert nig_vocabulary.label(spec("P06")) == "Trigger"


def test_question_override(nig_vocabulary):
    """§3.10: a question override replaces the default wording; IDs and keys never change."""
    wording = WordingOverrides.model_validate({"fields": {"S06": {"question": "Which tools?"}}})
    vocab = Vocabulary(taxonomy=nig_vocabulary.taxonomy, regions=nig_vocabulary.regions, wording=wording)
    assert vocab.question(spec("S06")) == "Which tools?"
    assert vocab.label(spec("S06")) == "Systems"


def test_ac_27_11_target_unit_ignores_singular_and_plural():
    """AC-27.11 (spec 27 §3.6 R1): "1 working day per role" is in the unit of "3 working days per role"."""
    from app.services.process_discovery.domain.field_spec import same_unit

    assert same_unit("working day per role", "working days per role")
    assert same_unit("Hours", "hour")
    assert not same_unit("hours", "days")
    assert not same_unit("working days", "working days per role")
