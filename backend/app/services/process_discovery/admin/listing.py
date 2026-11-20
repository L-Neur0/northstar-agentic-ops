"""The workspace session list: one row per session, the filters and the status counts (spec 21 §3.2).

Why: the specialist starts from a list of every expert's sessions, and its numbers must be the
interview's own: "fields filled" counts the same field views the expert's panel shows, so the
list never disagrees with the session it opens. The counts are taken before the filters, so the
status tiles stay put while the specialist searches.
What: `review_rows(sessions, status, cluster, q, vocab)` returns the filtered rows (newest
`updatedAt` first, ties by id), the counts and the number of matching rows; `field_counts` and
`context_of` are shared with the session view.
Must not: do I/O, read a clock, return a message, a document text, the owner or the display name,
or import another engine peer. Spec 21 §3.2; AC-21.2 to AC-21.6.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.models.process_discovery_schemas import Session, SessionStatus
from app.models.workspace_wire import ReviewCountsOut, ReviewRowOut

from ..domain.field_spec import Vocabulary
from ..profile.shapes import as_mapping, process_of, rows_of
from ..profile.views import field_views


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def profile_of(session: Session) -> dict[str, Any]:
    return session.profile.model_dump(mode="json", by_alias=True)


def context_of(profile: dict[str, Any], *, vocab: Vocabulary) -> dict[str, str | None]:
    """Department, role, region, process name and cluster as stored (empty → `None`)."""
    process = process_of(profile)
    cluster = as_mapping(process.get("cluster")) or {}
    code = _text(cluster.get("code"))
    known = vocab.taxonomy.by_code(code)
    return {
        "department": _text(profile.get("department")),
        "function": _text(profile.get("user_function")),
        "region": _text(profile.get("region")),
        "process_name": _text(process.get("name")),
        "cluster_code": code,
        "cluster_name": known.name if known else _text(cluster.get("name")),
    }


def views_of(session: Session, profile: dict[str, Any], *, vocab: Vocabulary) -> list[dict[str, Any]]:
    """The field views exactly as the expert's panel builds them (spec 13 §3.11)."""
    documents = [{"id": d.id, "name": d.name} for d in session.documents]
    return field_views(profile, counters=session.counters.model_dump(mode="json"), vocab=vocab, documents=documents)


def field_counts(views: Sequence[dict[str, Any]]) -> tuple[int, int]:
    """(complete views, all views)."""
    return sum(v["status"] == "complete" for v in views), len(views)


def _row(session: Session, *, vocab: Vocabulary) -> ReviewRowOut:
    profile = profile_of(session)
    context = context_of(profile, vocab=vocab)
    filled, total = field_counts(views_of(session, profile, vocab=vocab))
    return ReviewRowOut(
        id=session.id, created_at=session.created_at, updated_at=session.updated_at,
        process_name=context["process_name"], department=context["department"],
        cluster_code=context["cluster_code"], cluster_name=context["cluster_name"], region=context["region"],
        status=session.status, phase=session.phase, fields_filled=filled, fields_total=total,
        steps=len(rows_of(profile)), message_count=len(session.messages), document_count=len(session.documents),
        simulated=session.simulated,
    )  # fmt: skip


def _matches(row: ReviewRowOut, *, status: str | None, cluster: str | None, q: str | None) -> bool:
    if status is not None and row.status != status:
        return False
    if cluster is not None and (row.cluster_code or "").casefold() != cluster.casefold():
        return False
    if q:
        needle = q.casefold()
        return any(needle in (text or "").casefold() for text in (row.process_name, row.department, row.id))
    return True


def review_rows(
    sessions: Sequence[Session],
    *,
    status: str | None = None,
    cluster: str | None = None,
    q: str | None = None,
    vocab: Vocabulary,
) -> tuple[list[ReviewRowOut], ReviewCountsOut, int]:
    """The filtered rows, the counts of every session by status, and the number of matching rows."""
    ordered = sorted(sorted(sessions, key=lambda s: s.id), key=lambda s: s.updated_at, reverse=True)
    counts = ReviewCountsOut(
        total=len(ordered),
        active=sum(s.status == SessionStatus.ACTIVE for s in ordered),
        finished=sum(s.status == SessionStatus.FINISHED for s in ordered),
        no_candidate=sum(s.status == SessionStatus.NO_CANDIDATE for s in ordered),
    )
    rows = [r for r in (_row(s, vocab=vocab) for s in ordered) if _matches(r, status=status, cluster=cluster, q=q)]
    return rows, counts, len(rows)
