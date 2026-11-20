"""The expert's document routes: upload, list and remove documents, and confirm or reject their proposals (architecture §3.4, spec 17 §3.1, §3.12, §3.13).

Why: an expert can start from a procedure or a process map, but nothing read from it may count
until they confirm it (AD-10), and the uploaded file must never outlive the request (AD-11). These
five routes stay thin: resolve and rate-count the caller (spec 16), refuse an oversized body before
reading it, hand the bytes to one service use case, and return the wire model. Every route is
scoped to the caller, so another visitor's session is 404.
What: `router` (prefix `/api`): `POST/GET /sessions/{id}/documents`,
`DELETE /sessions/{id}/documents/{docId}`, `POST /sessions/{id}/proposals/confirm` and
`/proposals/reject`. Limits come from the company's `documents.yaml`; refusals are mapped to
`{code, message}` in `errors.py` (409 `document_limit`, 413 `document_too_large`, 415
`document_type`, 422 `document_unreadable`, 400 `unsafe_input`).
Must not: import past the engine facade, store, log or echo the bytes, the file name or the text,
or hold a business rule.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, status
from starlette.datastructures import UploadFile

from app.api.errors import ApiError
from app.api.process_discovery_routes import expert, get_service
from app.models.process_discovery_wire import DocumentListOut, DocumentUploadOut, ProposalKeysIn, SessionOut
from app.services.process_discovery import DiscoveryService

router = APIRouter(prefix="/api", tags=["documents"])

MB = 1_048_576
#: Room for the multipart boundaries and part headers around the file itself.
MULTIPART_OVERHEAD = 64 * 1024

UPLOAD_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}


def _missing_file() -> ApiError:
    return ApiError(422, "invalid_value", "file: a file is required.")


@router.post(
    "/sessions/{session_id}/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentUploadOut,
    openapi_extra=UPLOAD_BODY,
)
async def upload_document(
    session_id: str,
    request: Request,
    owner: str = Depends(expert),
    service: DiscoveryService = Depends(get_service),
) -> DocumentUploadOut:
    """Upload one document (multipart field `file`). Its values come back as proposals with quotes."""
    config = request.app.state.company.documents
    limit = int(config.max_file_mb * MB)
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit + MULTIPART_OVERHEAD:
        raise ApiError(413, "document_too_large", f"This file is larger than {config.max_file_mb:g} MB.")
    form = await request.form(max_files=1, max_fields=5)
    try:
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise _missing_file()
        data = await upload.read(limit + 1)  # one byte over is enough for the size check
        filename = upload.filename or ""
    finally:
        await form.close()
    session, report = await service.upload_document(owner, session_id, filename=filename, data=data, config=config)
    return service.upload_view(session, report)


@router.get("/sessions/{session_id}/documents", response_model=DocumentListOut)
async def list_documents(
    session_id: str, owner: str = Depends(expert), service: DiscoveryService = Depends(get_service)
) -> DocumentListOut:
    """The session's documents with their counts; never their text."""
    return DocumentListOut(documents=service.document_list(await service.get_session(owner, session_id)))


@router.delete("/sessions/{session_id}/documents/{document_id}", response_model=SessionOut)
async def remove_document(
    session_id: str,
    document_id: str,
    owner: str = Depends(expert),
    service: DiscoveryService = Depends(get_service),
) -> SessionOut:
    """Remove a document and its unconfirmed proposals; values already confirmed from it stay."""
    return service.view(await service.remove_document(owner, session_id, document_id))


@router.post("/sessions/{session_id}/proposals/confirm", response_model=SessionOut)
async def confirm_proposals(
    session_id: str,
    body: ProposalKeysIn,
    owner: str = Depends(expert),
    service: DiscoveryService = Depends(get_service),
) -> SessionOut:
    """✓ on proposals: they now count; keys that are not proposals are ignored."""
    return service.view(await service.confirm_proposals(owner, session_id, body.keys))


@router.post("/sessions/{session_id}/proposals/reject", response_model=SessionOut)
async def reject_proposals(
    session_id: str,
    body: ProposalKeysIn,
    owner: str = Depends(expert),
    service: DiscoveryService = Depends(get_service),
) -> SessionOut:
    """✎ on proposals: they are cleared, and the interview asks for them."""
    return service.view(await service.reject_proposals(owner, session_id, body.keys))
