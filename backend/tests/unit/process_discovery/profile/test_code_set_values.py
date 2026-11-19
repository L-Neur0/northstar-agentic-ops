"""Tests for the values only code sets: the cluster and the list confirmations (spec 13 §3.7; AC-13.30, AC-13.31).

Why: the cluster and the confirmations are product decisions a model must never make; their only
writers are these functions. What: the cluster write and its meta, the unknown-code error, and the
roll-up confirmation (rebuilt before the flag is raised).
"""

import pytest

from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.profile.mutate import (
    UnknownClusterError,
    apply_changes,
    confirm_rollup,
    set_cluster,
)
from app.services.process_discovery.profile.shapes import empty_profile

from .builders import AT


def test_set_cluster(vocab):
    """AC-13.30."""
    p = set_cluster(empty_profile(), "FIN", decided_by="picker", vocab=vocab, at=AT)
    assert p["process"]["cluster"] == {"code": "FIN", "name": "Finance", "decided_by": "picker"}
    assert p["__meta"]["process.cluster"]["source"] == "expert"
    assert p["__meta"]["process.cluster"]["status"] == "confirmed"
    with pytest.raises(UnknownClusterError) as error:
        set_cluster(empty_profile(), "XYZ", decided_by="picker", vocab=vocab, at=AT)
    assert error.value.code == "XYZ"
    s = set_cluster(empty_profile(), "IT", decided_by="specialist", vocab=vocab, at=AT, by="spec-1")
    assert s["__meta"]["process.cluster"]["source"] == "specialist"
    assert s["__meta"]["process.cluster"]["by"] == "spec-1"


def test_confirm_rollup_rebuilds_before_raising(vocab):
    """AC-13.31."""
    profile = apply_changes(empty_profile(), {step_cell_key(1, "roles"): ["Controller"]}, vocab=vocab, at=AT).profile
    profile["process"]["all_roles"] = ["Stale"]
    confirmed = confirm_rollup(profile, "roles", vocab=vocab)
    assert confirmed["process"]["all_roles"] == ["Controller"]
    assert confirmed["process"]["roles_confirmed"] is True
    assert confirm_rollup(empty_profile(), "systems", vocab=vocab)["process"]["tools_confirmed"] is True
    for bad in ("steps", "tools", ""):
        with pytest.raises(ValueError):
            confirm_rollup(empty_profile(), bad, vocab=vocab)
