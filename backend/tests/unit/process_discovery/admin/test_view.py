"""Unit tests for the read-only session view of the workspace (spec 21 §3.3; AC-21.8 to AC-21.10).

Why: the popup is where a specialist judges one session, so it must show the same statuses and
the same cell text as the report and the interview, and the "as first told" grid must really be
the frozen snapshot, not the current table under another name.
What: `session_view` on the finished EU cost review (summary cards, current grid with display
text, source and status, document metadata, the report passed in) and on an active session
(`report: None`); `rawSteps` built from `raw_substeps` and `None` without a snapshot. The cell
text rule comes from the report (`cell_text`), passed in by the service as it is here.
Must not: build the report itself (the service does) or touch the store.
"""

from __future__ import annotations

from app.models.process_discovery_schemas import DocumentRecord, Profile, Session, Step
from app.services.process_discovery.admin.view import session_view
from app.services.process_discovery.artifacts.report import build_report, cell_text
from app.services.process_discovery.domain.field_spec import STEP_SPECS
from tests.fixtures.assessment.profiles import load_profile
from tests.unit.process_discovery.export.cases import CATALOGUE, ORG, VOCAB, eu_session

SECRET = "SECRET-DOCUMENT-TEXT"


def _document() -> DocumentRecord:
    return DocumentRecord(
        id="d1", name="invoice-procedure.pdf", kind="pdf", bytes=1200, chars=50, text=SECRET,
        uploaded_at="2026-11-19T10:00:00+00:00", outcome="read",
    )  # fmt: skip


def _view(session: Session, *, finished: bool = True):
    report = build_report(session, ORG, VOCAB, CATALOGUE) if finished else None
    return session_view(session, report, vocab=VOCAB, cell_text=cell_text, etag='"e7"')


def test_ac_21_8_finished_session_has_cards_grid_documents_and_report():
    session = eu_session(documents=[_document()])
    view = _view(session)
    summary = view.summary
    assert (summary.department, summary.function, summary.region) == ("Finance", "Cost controlling", "Europe")
    assert (summary.process_name, summary.cluster_name, summary.status, summary.phase) == (
        "Monthly cost review", "Finance", "finished", "finished",
    )  # fmt: skip
    assert summary.steps_started == 5 and summary.steps_expected == 5
    assert summary.fields_total == 16 + 5 * 13 and 0 < summary.fields_filled <= summary.fields_total
    assert summary.completeness == session.score.value
    assert (summary.filled_points, summary.total_points) == (session.score.filled_points, session.score.total_points)
    assert (summary.message_count, summary.document_count) == (0, 1)
    grid = view.steps
    assert len(grid.step_names) == 5 and grid.step_names[0] == session.profile.process.substeps[0].name
    assert [r.id for r in grid.rows] == [s.id for s in STEP_SPECS if s.applies_when is None]  # no judgement step
    name_row = grid.rows[0]
    assert name_row.label == "Step name" and name_row.key == "name"
    assert name_row.cells[0].value == session.profile.process.substeps[0].name
    assert all(isinstance(c.value, str) for r in grid.rows for c in r.cells)
    assert {c.status for r in grid.rows for c in r.cells} <= {
        "complete",
        "partial",
        "empty",
        "skipped",
        "proposed",
        "invalid",
    }
    assert view.documents[0].model_dump(by_alias=True) == {
        "name": "invoice-procedure.pdf", "kind": "pdf", "bytes": 1200,
        "uploadedAt": "2026-11-19T10:00:00+00:00", "outcome": "read",
    }  # fmt: skip
    assert view.report is not None and view.report.map.columns
    assert view.etag == '"e7"' and view.id == session.id
    assert SECRET not in view.model_dump_json()


def test_ac_21_8_grid_cells_are_display_text_like_the_report():
    session = eu_session()
    view = _view(session)
    report = build_report(session, ORG, VOCAB, CATALOGUE)
    for index, column in enumerate(report.map.columns):
        assert [row.cells[index].value for row in view.steps.rows] == [c.value for c in column.cells]
        assert [row.cells[index].status for row in view.steps.rows] == [c.status for c in column.cells]


def test_ac_21_9_active_session_has_no_report():
    session = Session(
        owner_id="o", created_at="2026-11-19T10:00:00+00:00", updated_at="2026-11-19T10:00:00+00:00",
        profile=Profile.model_validate({"department": "IT"}),
    )  # fmt: skip
    view = _view(session, finished=False)
    assert view.report is None and view.raw_steps is None
    assert view.summary.status == "active" and view.summary.department == "IT"
    assert view.steps.step_names == [] and all(r.cells == [] for r in view.steps.rows)


def test_ac_21_10_raw_steps_are_the_frozen_snapshot():
    profile = load_profile("eu")
    raw = [Step.model_validate(r) for r in profile["process"]["substeps"]]
    profile["process"]["substeps"][0]["name"] = "Renamed by a document"
    view = _view(eu_session(profile, raw_substeps=raw))
    assert view.raw_steps is not None
    assert view.steps.rows[0].cells[0].value == "Renamed by a document"
    assert view.raw_steps.rows[0].cells[0].value == raw[0].name != "Renamed by a document"
    assert view.raw_steps.step_names[0] == raw[0].name
    assert all(c.source is None and c.status is None for r in view.raw_steps.rows for c in r.cells)


def test_ac_21_10_no_snapshot_means_null():
    assert _view(eu_session()).raw_steps is None
