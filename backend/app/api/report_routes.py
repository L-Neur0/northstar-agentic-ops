"""The report routes: the discovery report as JSON for the screen and as a PDF file (spec 20 §3.5).

Why: after *Finish* the expert reads the report on screen and downloads it; both must come from the
same report model, built on request from the stored session, and neither may call the model
(the assessment was paid for once, at *Finish*). Like every expert route, they are scoped to the
caller's visitor key, so another visitor's session is "not found".
What: `GET /api/sessions/{id}/report` (the `DiscoveryReport`, camelCase) and
`GET /api/sessions/{id}/report.pdf` (`application/pdf`, attachment
`discovery-report-<slug>.pdf`); a session that is not finished is 409 `report_not_ready`.
Must not: import past the engine facade, format anything, or call the model. Spec 20 §3.5;
AC-20.44.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.api.process_discovery_routes import expert, get_service
from app.models.process_discovery_wire import DiscoveryReport
from app.services.process_discovery import DiscoveryService

router = APIRouter(prefix="/api", tags=["report"])


@router.get("/sessions/{session_id}/report", response_model=DiscoveryReport)
async def get_report(
    session_id: str, owner: str = Depends(expert), service: DiscoveryService = Depends(get_service)
) -> DiscoveryReport:
    """The discovery report of a finished session: the cover and eleven parts, display-ready."""
    return await service.report(owner, session_id)


@router.get("/sessions/{session_id}/report.pdf", response_class=Response)
async def get_report_pdf(
    session_id: str, owner: str = Depends(expert), service: DiscoveryService = Depends(get_service)
) -> Response:
    """The same report as a PDF download, rendered off the event loop."""
    pdf, filename = await service.report_pdf(owner, session_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
