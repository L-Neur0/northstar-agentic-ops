"""State integrity across the profile layer: model round trips, purity and log hygiene (spec 13; AC-13.52 to AC-13.54).

Why: every profile this layer returns is saved through the Pydantic models; a key the models do not
know, or a none row that collapses to `[]`, would be lost on the next save. The layer must also be
pure and must never log a value. What: round trips of profiles from every writer, an AST purity
check of `profile/`, and a sentinel test over the log records of a busy write sequence.
"""

import ast
import logging
from pathlib import Path

import pytest

from app.models.process_discovery_schemas import Profile
from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.profile.mutate import apply_changes, mark_cells_skipped, set_field
from app.services.process_discovery.profile.proposals import FieldProposal, ProposalDiff, StepProposal, apply_proposals
from app.services.process_discovery.profile.scoring import score
from app.services.process_discovery.profile.shapes import empty_profile

from .builders import AT, cost_review_profile

PROFILE_DIR = Path(__file__).resolve().parents[4] / "app" / "services" / "process_discovery" / "profile"
SENTINEL = "ZZ-SENTINEL-VALUE-ZZ"


def produced(vocab):
    yield empty_profile()
    yield cost_review_profile(vocab, steps=4)
    yield cost_review_profile(vocab, steps=6, filled_steps=2)
    p = apply_changes(
        empty_profile(), {"process.substep_count": 13, step_cell_key(3, "roles"): [{"none": True}]}, vocab=vocab, at=AT
    ).profile
    yield mark_cells_skipped(p, [step_cell_key(3, "goal")], vocab=vocab)
    diff = ProposalDiff(
        "d1",
        fields=(FieldProposal("process.trigger", "T", "t"),),
        steps=(StepProposal((FieldProposal("name", "A", "A"),)), StepProposal((FieldProposal("name", "B", "B"),))),
    )
    yield apply_proposals(empty_profile(), diff, vocab=vocab, at=AT).profile
    yield set_field(empty_profile(), "process.trigger", "S", by="spec", vocab=vocab, at=AT).profile


def test_round_trip(vocab):
    """AC-13.52."""
    for profile in produced(vocab):
        dumped = Profile.model_validate(profile).model_dump(by_alias=True)
        assert dumped == profile
        assert score(dumped, vocab=vocab) == score(profile, vocab=vocab)
    none = apply_changes(empty_profile(), {step_cell_key(1, "roles"): [{"none": True}]}, vocab=vocab, at=AT).profile
    assert Profile.model_validate(none).model_dump(by_alias=True)["process"]["substeps"][0]["roles"] == [{"none": True}]


FORBIDDEN_MODULES = {
    "time",
    "random",
    "os",
    "pathlib",
    "socket",
    "urllib",
    "requests",
    "httpx",
    "io",
    "shutil",
    "subprocess",
}


@pytest.mark.parametrize("path", sorted(PROFILE_DIR.glob("*.py")), ids=lambda p: p.name)
def test_profile_modules_are_pure(path):
    """AC-13.53: no clock, randomness, file or network modules."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module.split(".")[0]]
        assert not FORBIDDEN_MODULES.intersection(names), f"{path.name} imports {names}"
        if isinstance(node, ast.Attribute) and node.attr in ("now", "utcnow", "today"):
            pytest.fail(f"{path.name} reads a clock")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            pytest.fail(f"{path.name} opens a file")


def test_same_inputs_same_outputs(vocab):
    """AC-13.53."""
    assert cost_review_profile(vocab, steps=3) == cost_review_profile(vocab, steps=3)


def test_no_log_record_carries_a_value(vocab, caplog):
    """AC-13.54."""
    caplog.set_level(logging.DEBUG)
    p = apply_changes(empty_profile(), {"process.substep_count": 2}, vocab=vocab, at=AT).profile
    apply_changes(
        p,
        {
            step_cell_key(5, "name"): SENTINEL,
            "process.volume": {"count": SENTINEL},
            "volume": SENTINEL,
            "process.cluster": SENTINEL,
            step_cell_key(1, "roles"): [{"contribution": SENTINEL}],
        },
        vocab=vocab,
        at=AT,
    )
    diff = ProposalDiff(
        "d1", fields=(FieldProposal("process.trigger", SENTINEL, ""), FieldProposal("region", SENTINEL, "q"))
    )
    apply_proposals(p, diff, vocab=vocab, at=AT)
    assert caplog.records
    for record in caplog.records:
        assert SENTINEL not in record.getMessage()
        assert SENTINEL not in str(record.__dict__)
