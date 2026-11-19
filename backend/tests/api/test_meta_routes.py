"""API tests for the public meta routes: taxonomy, runtime config and health (spec 15 part 2 §3.3; AC-15.46, AC-15.47).

Why: the frontend reads the cluster picker, the product name, the regions, the languages and the
upload limits from the server, so a new company is configuration only; the platform's probe reads
health, which must also tell an operator whether the store is reachable.
What: `GET /api/taxonomy` and `GET /api/config` without a visitor key, against the real NIG
configuration; `GET /api/health` with the lifespan run on the memory store.
Must not: depend on Azure.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import CompanyConfig
from app.main import create_app

from .conftest import ApiHarness, make_settings


def test_ac_15_46_taxonomy_lists_the_nine_clusters_in_order_without_a_key(api: ApiHarness, company: CompanyConfig):
    response = api.client.get("/api/taxonomy")
    assert response.status_code == 200
    clusters = response.json()["clusters"]
    assert len(clusters) == 9
    assert [c["code"] for c in clusters] == [c.code for c in company.taxonomy.clusters]
    assert set(clusters[0]) == {"code", "name", "description"}


def test_ac_15_46_config_returns_the_public_runtime_values_without_a_key(api: ApiHarness, company: CompanyConfig):
    response = api.client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "productName": company.organisation.product_name,
        "regions": list(company.organisation.regions),
        "languages": list(company.organisation.languages),
        "documents": {
            "allowedTypes": list(company.documents.allowed_types),
            "maxFiles": company.documents.max_files_per_session,
            "maxFileMb": company.documents.max_file_mb,
        },
    }


def test_ac_15_47_health_includes_the_store_check():
    app = create_app(make_settings(store="memory"))
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["stage"] == "local" and body["version"]
    assert body["store"] == {"ok": True, "ttlEnabled": None}  # the memory store does not simulate ttl
