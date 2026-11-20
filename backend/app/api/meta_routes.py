"""Meta routes: health, public runtime settings and the taxonomy (spec 10 §3.8, spec 15 part 2 §3.3).

Why: the container platform needs a cheap probe that also tells an operator whether the store is
reachable, and the frontend needs the cluster picker, the product name, the regions, the
languages and the upload limits from the company configuration without rebuilding the image.
What: `GET /api/health` (status, stage, version and the store check made at start-up, so the probe
stays cheap and touches no store or model), `GET /api/config` and `GET /api/taxonomy`. All three
are public; health is never rate-limited (spec 16 AC-16.11). `workspaceOpen` tells the workspace
screen to drop the code field and the delete button (spec 16 AC-16.19). AC-15.46, AC-15.47.
Must not: expose secrets or settings beyond what the frontend needs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.config import CompanyConfig, get_company
from app.core.settings import Settings, get_settings
from app.models.process_discovery_schemas import ClusterOut, TaxonomyOut
from app.models.process_discovery_wire import ConfigOut, DocumentLimitsOut, HealthOut, StoreHealthOut

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health", response_model=HealthOut)
def health(request: Request, settings: Settings = Depends(get_settings)) -> HealthOut:
    """Liveness probe: the app is up, knows its stage, and how the store answered at start-up."""
    store = getattr(request.app.state, "store_health", None)
    return HealthOut(
        status="ok",
        stage=settings.deployment_stage,
        version=settings.app_version,
        store=StoreHealthOut(ok=bool(store and store.ok), ttl_enabled=store.ttl_enabled if store else None),
    )


@router.get("/config", response_model=ConfigOut)
def public_config(
    company: CompanyConfig = Depends(get_company), settings: Settings = Depends(get_settings)
) -> ConfigOut:
    """The runtime values the frontend shows: product name, regions, languages, upload limits, open workspace."""
    documents = company.documents
    return ConfigOut(
        product_name=company.organisation.product_name,
        regions=list(company.organisation.regions),
        languages=list(company.organisation.languages),
        documents=DocumentLimitsOut(
            allowed_types=list(documents.allowed_types),
            max_files=documents.max_files_per_session,
            max_file_mb=documents.max_file_mb,
            max_image_mb=documents.max_image_mb,
        ),
        workspace_open=settings.workspace_open,
    )


@router.get("/taxonomy", response_model=TaxonomyOut)
def taxonomy(company: CompanyConfig = Depends(get_company)) -> TaxonomyOut:
    """The clusters in configuration order, for the picker."""
    return TaxonomyOut(
        clusters=[ClusterOut(code=c.code, name=c.name, description=c.description) for c in company.taxonomy.clusters]
    )
