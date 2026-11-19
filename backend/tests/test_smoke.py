"""Smoke tests for the app shell (spec 10 §3.8).

Why: every later route lives inside this shell, so its basics (health, headers, the built
frontend, CORS, correlation ids) must hold before anything else is built.
What: builds the app with explicit settings and calls it through FastAPI's test client.
Implements AC-10.2, AC-10.11, AC-10.13 to AC-10.15.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.settings import Settings
from app.main import create_app

DEMO = dict(
    deployment_stage="demo",
    store="cosmos",
    cosmos_endpoint="https://x",
    workspace_code_specialist="s-123456",
    workspace_code_engineer="e-123456",
    workspace_token_secret="x" * 32,
)


def client(tmp_path=None, **values):
    if tmp_path is not None:
        values.setdefault("frontend_dist", str(tmp_path))
    settings = Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]
    return TestClient(create_app(settings))


def test_health(tmp_path):
    """AC-10.2."""
    r = client(tmp_path).get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["stage"] == "local" and "version" in body


def test_security_headers_on_every_response(tmp_path):
    """AC-10.13."""
    r = client(tmp_path).get("/api/health")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "DENY"
    assert "strict-transport-security" not in r.headers


def test_hsts_outside_local(tmp_path):
    r = client(tmp_path, **DEMO).get("/api/health")
    assert "max-age" in r.headers["strict-transport-security"]


def test_correlation_id_is_reused_or_created(tmp_path):
    """AC-10.11."""
    c = client(tmp_path)
    assert c.get("/api/health", headers={"X-Correlation-Id": "given-1"}).headers["x-correlation-id"] == "given-1"
    assert c.get("/api/health").headers["x-correlation-id"]


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "index.html").write_text("<html>discovery</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    return tmp_path


def test_spa_routes_return_the_page(dist):
    """AC-10.14."""
    c = client(dist)
    assert "discovery" in c.get("/").text
    assert "discovery" in c.get("/process-discovery/abc").text
    assert c.get("/assets/app.js").text == "console.log(1)"


def test_unknown_api_path_is_a_json_404(dist):
    """AC-10.14: the page fallback never swallows an API path."""
    r = client(dist).get("/api/unknown")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_cors_only_in_local(tmp_path):
    """AC-10.15."""
    origin = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}
    assert "access-control-allow-origin" in client(tmp_path).options("/api/health", headers=origin).headers
    assert "access-control-allow-origin" not in client(tmp_path, **DEMO).options("/api/health", headers=origin).headers
