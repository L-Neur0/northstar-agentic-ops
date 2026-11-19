"""Tests for the stored document record after the spec 17 change request (spec 12 §3.11, AC-12.46, AC-12.47).

Why: the document reader (spec 17) keeps a list of more than six step names for the interview to
help the expert group them, and a refused upload is never stored, so no stored record can say
"rejected".
What: checks the new `step_list` field (default empty, name plus quote per item) and that the
outcome accepts only "read" and "failed".
"""

from typing import Any

import pytest
from pydantic import ValidationError

from app.models.process_discovery_schemas import DocumentRecord

BASE: dict[str, Any] = dict(
    id="d1", name="procedure.docx", kind="docx", bytes=10, chars=5, uploaded_at="2026-11-19T10:00:00Z"
)


def test_step_list_defaults_to_empty_and_keeps_name_and_quote():
    """AC-12.46."""
    assert DocumentRecord(**BASE, outcome="read").step_list == []
    rec = DocumentRecord.model_validate(
        {**BASE, "outcome": "read", "stepList": [{"name": "Export", "quote": "1. Export the data"}]}
    )
    assert rec.step_list[0].name == "Export" and rec.step_list[0].quote == "1. Export the data"


def test_rejected_is_not_a_stored_outcome():
    """AC-12.47: a refused upload stores nothing, so `rejected` cannot appear."""
    with pytest.raises(ValidationError):
        DocumentRecord.model_validate({**BASE, "outcome": "rejected"})
