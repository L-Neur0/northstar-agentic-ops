"""Tests for provenance: `FieldMeta`, the counting rule and the display status (spec 12 §3.6).

Why: a value read from a document is only a proposal until the expert confirms it (product rule
4). If a proposal ever counted, the score and *Finish* would rest on words the expert never said.
What: checks the `FieldMeta` invariants, that `counts` is the only gate (complete and not proposed),
the order of `field_status`, and that the `__meta` and `__skipped` sidecars survive a round trip.
Implements AC-12.25 to AC-12.28.
"""

import pytest
from pydantic import ValidationError

from app.models.process_discovery_schemas import FieldMeta, Profile
from app.services.process_discovery.domain import field_spec as fs

AT = "2026-11-20T09:14:03Z"
COMPLETE = fs.Verdict("complete")
PARTIAL = fs.Verdict("partial", ("period",), "Volume still needs: period.")
INVALID = fs.Verdict("invalid", ("unit",), "Wrong unit.")


# --- AC-12.25: FieldMeta ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        {"source": "document", "status": "proposed", "quote": "q", "at": AT},
        {"source": "document", "status": "confirmed", "documentId": "d1", "at": AT},
        {"source": "expert", "status": "proposed", "at": AT},
        {"source": "specialist", "status": "confirmed", "at": AT},
        {"source": "specialist", "status": "proposed", "by": "Ana", "quote": "q", "at": AT},
        {"source": "model", "status": "confirmed", "at": AT},
        {"source": "expert", "status": "maybe", "at": AT},
    ],
    ids=[
        "document-no-id",
        "document-no-quote",
        "proposed-no-quote",
        "specialist-no-by",
        "specialist-proposed",
        "unknown-source",
        "unknown-status",
    ],
)
def test_field_meta_rejects_broken_provenance(data):
    """AC-12.25."""
    with pytest.raises(ValidationError):
        FieldMeta.model_validate(data)


@pytest.mark.parametrize(
    "data",
    [
        {"source": "expert", "status": "confirmed", "at": AT},
        {"source": "expert", "status": "proposed", "quote": "the idea's words", "at": AT},
        {"source": "document", "status": "proposed", "documentId": "d1", "quote": "q", "at": AT},
        {"source": "document", "status": "confirmed", "documentId": "d1", "quote": "q", "at": AT},
        {"source": "specialist", "status": "confirmed", "by": "Ana", "at": AT},
    ],
)
def test_field_meta_accepts_valid_provenance(data):
    """AC-12.25 (the allowed shapes); JSON keys are camelCase."""
    meta = FieldMeta.model_validate(data)
    dumped = meta.model_dump(by_alias=True, mode="json")
    assert set(dumped) == {"source", "status", "documentId", "quote", "by", "at"}


# --- AC-12.26: counts ------------------------------------------------------------------------


def test_counts():
    """AC-12.26: complete and not proposed counts; nothing else does."""
    confirmed = {"source": "document", "status": "confirmed", "documentId": "d1", "quote": "q", "at": AT}
    proposed = {"source": "document", "status": "proposed", "documentId": "d1", "quote": "q", "at": AT}
    assert fs.counts(COMPLETE, confirmed)
    assert fs.counts(COMPLETE, None)
    assert not fs.counts(COMPLETE, proposed)
    for verdict in (PARTIAL, INVALID):
        for meta in (None, confirmed, proposed):
            assert not fs.counts(verdict, meta)
    assert fs.is_proposed(proposed) and not fs.is_proposed(confirmed) and not fs.is_proposed(None)


# --- AC-12.27: field_status ------------------------------------------------------------------

PROPOSED = {"source": "document", "status": "proposed", "documentId": "d1", "quote": "q", "at": AT}


@pytest.mark.parametrize(
    ("verdict", "meta", "answered", "skipped", "expected"),
    [
        (PARTIAL, PROPOSED, True, False, "proposed"),
        (COMPLETE, PROPOSED, True, False, "proposed"),
        (COMPLETE, None, True, False, "complete"),
        (PARTIAL, None, False, True, "skipped"),
        (PARTIAL, None, True, True, "skipped"),
        (PARTIAL, None, False, False, "empty"),
        (PARTIAL, PROPOSED, False, False, "empty"),
        (INVALID, None, True, False, "invalid"),
        (PARTIAL, None, True, False, "partial"),
    ],
)
def test_field_status_order(verdict, meta, answered, skipped, expected):
    """AC-12.27: proposed, complete, skipped, empty, invalid, partial, in that order."""
    assert fs.field_status(verdict, meta, answered=answered, skipped=skipped) == expected


# --- AC-12.28: sidecars round-trip -----------------------------------------------------------


def test_sidecars_survive_a_round_trip():
    """AC-12.28: `__meta`, `__skipped` and `documentId` keep their keys."""
    data = Profile().model_dump(by_alias=True)
    data["process"]["trigger"] = "Month-end close is completed in the ledger"
    data["__meta"] = {
        "process.trigger": {
            "source": "document",
            "status": "proposed",
            "documentId": "d1",
            "quote": "The review starts once month-end close is completed",
            "by": None,
            "at": AT,
        }
    }
    step = {
        "name": "Collect costs",
        "systems": ["SAP"],
        "__meta": {
            "systems": {
                "source": "expert",
                "status": "confirmed",
                "documentId": None,
                "quote": None,
                "by": None,
                "at": AT,
            }
        },
        "__skipped": ["goal"],
    }
    data["process"]["substeps"] = [step, {"name": "Review"}]
    dumped = Profile.model_validate(data).model_dump(by_alias=True)
    assert dumped["__meta"] == data["__meta"]
    first = dumped["process"]["substeps"][0]
    assert first["__skipped"] == ["goal"]
    assert first["__meta"]["systems"]["documentId"] is None
    assert "meta" not in dumped and "skipped" not in first
