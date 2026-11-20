"""The read-only session view of the workspace: summary cards, the step grid now and as first told, documents (spec 21 §3.3).

Why: a specialist judges one session from this view, so it must show what the interview and the
report show: the same field statuses (from the field views) and the same cell text (the report's
cell rule, passed in by the service because that rule lives in a peer this module may not
import). The "as first told" grid is built from the frozen `raw_substeps`, so the specialist can
see what the expert said before documents changed the table.
What: `session_view(session, report, vocab, cell_text, etag)` returns `ReviewSessionOut`;
`step_grid(rows, views, vocab, cell_text)` builds one grid (one row per S01–S12 field, one cell
per step: display text, source, status; `views=None` for the snapshot, whose cells carry no
source or status).
Must not: do I/O, read a clock, build the report (the service does), return a message, document
text, the owner or the display name, or import another engine peer. Spec 21 §3.3; AC-21.8 to
AC-21.10.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from app.models.process_discovery_schemas import Session
from app.models.process_discovery_wire import DiscoveryReport
from app.models.workspace_wire import (
    DocumentMetaOut,
    GridCellOut,
    GridRowOut,
    ReviewSessionOut,
    StepGridOut,
    SummaryOut,
)

from ..domain.field_spec import SKIPPED_KEY, STEP_SPECS, Vocabulary, step_cell_key
from ..profile.coercion import coerce_count
from ..profile.shapes import as_list, process_of, rows_of
from ..profile.verdicts import step_is_started
from .listing import context_of, field_counts, profile_of, views_of


class CellText(Protocol):
    """The report's cell rule (`artifacts.report.cell_text`), handed in by the service."""

    def __call__(self, leaf: str, value: Any, *, skipped: bool, proposed: bool) -> str: ...


def step_grid(
    rows: Sequence[Mapping[str, Any]],
    views: Mapping[str, Mapping[str, Any]] | None,
    *,
    vocab: Vocabulary,
    cell_text: CellText,
) -> StepGridOut:
    """One grid row per step field, one cell per step; `views=None` leaves source and status empty."""
    grid_rows: list[GridRowOut] = []
    for spec in STEP_SPECS:
        cells: list[GridCellOut] = []
        for index, row in enumerate(rows, start=1):
            view = (views or {}).get(step_cell_key(index, spec.key), {})
            status = view.get("status")
            skipped = spec.key in (as_list(row.get(SKIPPED_KEY)) or []) or status == "skipped"
            text = cell_text(spec.key, row.get(spec.key), skipped=skipped, proposed=status == "proposed")
            cells.append(GridCellOut(value=text, source=view.get("source"), status=status))
        grid_rows.append(GridRowOut(key=spec.key, id=spec.id, label=vocab.label(spec), cells=cells))
    names = [str(row.get("name") or "").strip() or f"Step {i}" for i, row in enumerate(rows, start=1)]
    return StepGridOut(step_names=names, rows=grid_rows)


def session_view(
    session: Session, report: DiscoveryReport | None, *, vocab: Vocabulary, cell_text: CellText, etag: str
) -> ReviewSessionOut:
    """The popup body for any status; `report` is `None` before *Finish*."""
    profile = profile_of(session)
    context = context_of(profile, vocab=vocab)
    views = views_of(session, profile, vocab=vocab)
    filled, total = field_counts(views)
    rows = rows_of(profile)
    summary = SummaryOut(
        department=context["department"], function=context["function"], region=context["region"],
        process_name=context["process_name"], cluster_name=context["cluster_name"],
        status=session.status, phase=session.phase, fields_filled=filled, fields_total=total,
        steps_started=sum(step_is_started(r, vocab=vocab) for r in rows),
        steps_expected=coerce_count(process_of(profile).get("substep_count")),
        completeness=session.score.value, filled_points=session.score.filled_points,
        total_points=session.score.total_points, message_count=len(session.messages),
        document_count=len(session.documents),
    )  # fmt: skip
    raw = [r.model_dump(mode="json", by_alias=True) for r in session.raw_substeps]
    return ReviewSessionOut(
        id=session.id,
        etag=etag,
        summary=summary,
        steps=step_grid(rows, {v["key"]: v for v in views}, vocab=vocab, cell_text=cell_text),
        raw_steps=step_grid(raw, None, vocab=vocab, cell_text=cell_text) if raw else None,
        documents=[
            DocumentMetaOut(name=d.name, kind=d.kind, bytes=d.bytes, uploaded_at=d.uploaded_at, outcome=d.outcome)
            for d in session.documents
        ],
        report=report,
        simulated=session.simulated,
    )
