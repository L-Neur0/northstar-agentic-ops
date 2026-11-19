"""Profile and session builders for the document tests: the monthly cost review, built with the real writers.

Why: a test that hand-types a profile dict proves behaviour on a shape the product never makes.
Every profile here goes through `apply_changes`, `set_field`, `set_cluster` or `apply_proposals`,
so its `__meta` is exactly what the interview, a specialist or a document would have written.
What: the fixed time `AT`, `profile_with`, `expert_steps`, `procedure_profile` (worked example 1's
starting profile), `session_with` and the scripted reply of worked example 1 (`procedure_reply`).
Must not: patch or bypass a writer, or read anything but the fixture folder. Spec 17 §3.15; AC-17.25 to AC-17.44.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.models.process_discovery_schemas import DocumentRecord, Profile, Session
from app.services.process_discovery.domain.field_spec import Vocabulary, step_cell_key
from app.services.process_discovery.profile.mutate import apply_changes, set_cluster, set_field
from app.services.process_discovery.profile.shapes import empty_profile

AT = "2026-11-19T10:00:00+00:00"
FIXTURES = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "documents"
STEP_NAMES = ("Export actuals", "Compare with budget", "Collect explanations", "Review", "Send the cost report")


def write(vocab: Vocabulary, profile: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    return apply_changes(profile, changes, vocab=vocab, at=AT).profile


def specialist(vocab: Vocabulary, profile: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    return set_field(profile, key, value, by="specialist@example.org", vocab=vocab, at=AT).profile


def procedure_profile(vocab: Vocabulary) -> dict[str, Any]:
    """Worked example 1: P01–P03, P04 confirmed by the expert, P05 FIN; no steps."""
    profile = write(
        vocab,
        empty_profile(),
        {
            "department": "Finance",
            "user_function": "Cost controller",
            "region": "Europe",
            "process.name": "Monthly cost review",
        },
    )
    return set_cluster(profile, "FIN", decided_by="proposal", vocab=vocab, at=AT)


def expert_steps(
    vocab: Vocabulary, profile: dict[str, Any], names: list[str], *, count: int | None = None
) -> dict[str, Any]:
    """The expert declares `count` steps (default: one per name) and names each row."""
    changes: dict[str, Any] = {"process.substep_count": count if count is not None else len(names)}
    changes.update({step_cell_key(i, "name"): n for i, n in enumerate(names, start=1)})
    return write(vocab, profile, changes)


def procedure_reply() -> dict[str, Any]:
    return json.loads((FIXTURES / "cost_review_procedure.reply.json").read_text(encoding="utf-8"))


def procedure_text() -> str:
    """The stored text of the procedure fixture (worked example 1)."""
    from app.services.process_discovery.documents.extract import extract_text

    return extract_text("docx", (FIXTURES / "cost_review_procedure.docx").read_bytes(), 60_000).text


def session_with(profile: dict[str, Any], documents: list[DocumentRecord] | None = None) -> Session:
    return Session(
        owner_id="owner-1",
        created_at=AT,
        updated_at=AT,
        profile=Profile.model_validate(profile),
        documents=documents or [],
    )


def record(document_id: str, name: str = "notes.txt") -> DocumentRecord:
    return DocumentRecord(
        id=document_id, name=name, kind="txt", bytes=10, chars=4, text="text", uploaded_at=AT, outcome="read"
    )
