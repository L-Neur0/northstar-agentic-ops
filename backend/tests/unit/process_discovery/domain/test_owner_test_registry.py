"""Tests for the registry, model and config changes of the owner-test amendment (spec 12, 13; amended 2026-11-21).

Why: the shorter walk moves fields between ask groups, the offered values live on `LastQuestion`, the
progress bar needs its own step weights, and the accept phrases are company configuration. Old Cosmos documents must still load. What: AC-12.53 to AC-12.55, AC-13.62, AC-13.63.
Must not: restate the registry by hand beyond the IDs the spec names.
"""

from pathlib import Path

from app.core.config import load_company_config
from app.models.process_discovery_schemas import LastQuestion, Session
from app.services.process_discovery.domain.field_spec import (
    STEP_SPECS,
    Vocabulary,
    progress_step_specs,
    step_cell_key,
    step_specs_in_group,
)
from app.services.process_discovery.profile.mutate import apply_changes, mark_cells_skipped
from app.services.process_discovery.profile.scoring import finish_check, score

from ..profile.builders import AT, context_changes, process_changes

NIG = Path(__file__).resolve().parents[5] / "config" / "nig"
CONFIG = load_company_config(NIG)
VOCAB = Vocabulary(taxonomy=CONFIG.taxonomy, regions=CONFIG.organisation.regions, wording=CONFIG.wording)


def ids(specs) -> list[str]:
    return [s.id for s in specs]


def test_ac_12_53_groups_after_the_owner_test():
    assert ids(step_specs_in_group("A")) == ["S03", "S04", "S06", "S07", "S09", "S13"]
    assert ids(step_specs_in_group("B")) == ["S10", "S11", "S12", "S14"]  # S14: spec 12 §3.13
    assert all(s.optional and s.max_asks == 1 for s in step_specs_in_group("B"))
    assert ids(step_specs_in_group("C")) == ["S02", "S05"]
    assert ids(progress_step_specs()) == ["S01", "S03", "S04", "S06", "S07", "S08", "S09", "S13"]
    assert all(s.ask_part for s in STEP_SPECS if s.group in ("A", "B"))


def test_ac_12_54_old_documents_load_and_offered_round_trips():
    old = {
        "owner_id": "x",
        "created_at": AT,
        "updated_at": AT,
        "phase": "confirm",
        "last_question": {"focus": ["process.all_roles"], "confirm": "roles"},
        "profile": {"process": {"roles_confirmed": False, "tools_confirmed": True}},
    }
    session = Session.model_validate(old)
    assert session.last_question.offered == {}
    offered = {"process.sensitive_data": [{"item": "GDPR"}]}
    assert LastQuestion.model_validate(LastQuestion(offered=offered).model_dump()).offered == offered


def test_ac_12_55_accept_phrases_are_config():
    assert "those are exact" in CONFIG.language.languages["en"].accept
    words = CONFIG.language.languages["en"].model_dump() | {"accept": ()}
    assert (
        type(CONFIG.language.languages["en"]).model_validate({k: v for k, v in words.items() if k != "accept"}).accept
        == ()
    )


def three_steps() -> dict:
    values = process_changes(3)
    changes = {**context_changes(), **{k: v for k, v in values.items() if not k.startswith("process.substeps")}}
    changes["process.substep_count"] = 3
    return apply_changes({}, changes, vocab=VOCAB, at=AT).profile


def test_ac_13_62_a_skipped_optional_cell_leaves_the_total():
    profile = three_steps()
    full = score(profile, vocab=VOCAB).total_points
    assert full == 18 + 36
    keys = [step_cell_key(i, leaf) for i in range(1, 4) for leaf in ("approvals", "exceptions")]
    skipped = mark_cells_skipped(profile, keys, vocab=VOCAB)
    assert score(skipped, vocab=VOCAB).total_points == full - 6
    none = apply_changes(profile, dict.fromkeys(keys, [{"none": True}]), vocab=VOCAB, at=AT).profile
    assert score(none, vocab=VOCAB).total_points == full


def test_ac_13_63_finish_does_not_wait_for_list_confirmations():
    profile = three_steps()
    profile["process"]["substeps_complete"] = True
    check = finish_check(profile, vocab=VOCAB)
    assert check.blocked_by in (None, "below_gate")
    assert check.blocked_by not in ("roles_not_confirmed", "tools_not_confirmed")
