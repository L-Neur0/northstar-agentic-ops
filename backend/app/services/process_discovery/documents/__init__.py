"""Start from your documents: checks, text, BPMN read in code, one READ_DOCUMENT call, quote-checked proposals (spec 17).

Why: an expert can upload a procedure, a process map or an example output so the interview asks
only for what the document does not say. Nothing read from a document counts until the expert
confirms it (AD-10), and uploaded files are never stored: only the capped, cleaned text is kept.
What: re-exports the functions the service composes (`read_document`, `remove_document`,
`document_views`) and the types it needs. Must not: import a peer (`admin`, `artifacts`, `export`,
`overview`), `service.py`, or anything from `interview` except `interview.prompts.common.render_profile`;
build objects at import time. Spec 17 §2, §4; AC-17.39.
"""

from .context import ReadingContext, reading_context
from .intake import DocumentKind, DocumentNotFound, DocumentRejected
from .pipeline import DocumentRead, DocumentReport, DocumentView, document_views, read_document, remove_document

__all__ = [
    "DocumentKind",
    "DocumentNotFound",
    "DocumentRead",
    "DocumentRejected",
    "DocumentReport",
    "DocumentView",
    "ReadingContext",
    "document_views",
    "read_document",
    "reading_context",
    "remove_document",
]
