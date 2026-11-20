"""Checks of azure.yaml, the azd parameter mapping and the CI workflow (spec 25 §3.3, §3.6, §3.12).

Why: azd and GitHub Actions read these files only when a deploy runs; a typo there fails the
deploy or, worse, deploys without approval or with a stored secret. These tests read them on
every push.
What: parses `azure.yaml` (service `app`, Docker build, pipeline values), `main.parameters.json`
(every azd value the template needs) and `.github/workflows/ci.yml` (jobs, trigger, approval
environment, OIDC, no Azure secret).
Must not: run azd or call Azure.
Spec: 25. Acceptance criteria: AC-25.21, AC-25.26 (static half), AC-25.30 (amended 2026-11-20,
open workspace: `WORKSPACE_OPEN` defaults to true, the codes are optional); spec 25 Q1 for the trigger.
"""

from __future__ import annotations

import json
from typing import Any

import yaml
from conftest import INFRA, REPO

AZURE = yaml.safe_load((REPO / "azure.yaml").read_text())
CI: dict[Any, Any] = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text())
PARAMS = json.loads((INFRA / "main.parameters.json").read_text())["parameters"]


def test_ac_25_21_azure_yaml_service_app() -> None:
    assert AZURE["infra"] == {"provider": "bicep", "path": "infra", "module": "main"}
    app = AZURE["services"]["app"]
    assert app["host"] == "containerapp"
    assert app["project"] == "."
    assert app["docker"]["path"] == "./Dockerfile"
    assert app["docker"]["context"] == "."
    assert app["docker"]["remoteBuild"] is False
    assert "APP_VERSION=${APP_VERSION}" in app["docker"]["buildArgs"]
    assert "TODO" not in (REPO / "azure.yaml").read_text()


def test_ac_25_21_pipeline_variables_and_secrets() -> None:
    pipeline = AZURE["pipeline"]
    assert pipeline["provider"] == "github"
    assert set(pipeline["secrets"]) == {
        "WORKSPACE_CODE_SPECIALIST",
        "WORKSPACE_CODE_ENGINEER",
        "WORKSPACE_TOKEN_SECRET",
    }
    assert set(pipeline["variables"]) == {
        "AZURE_RESOURCE_GROUP",
        "MIN_REPLICAS",
        "DEVELOPER_PRINCIPAL_ID",
        "WORKSPACE_OPEN",  # AC-25.30
    }


def test_parameters_map_every_azd_value() -> None:
    expected = {
        "environmentName": "${AZURE_ENV_NAME}",
        "location": "${AZURE_LOCATION}",
        "developerPrincipalId": "${DEVELOPER_PRINCIPAL_ID=}",
        "minReplicas": "${MIN_REPLICAS=1}",
        "appExists": "${SERVICE_APP_RESOURCE_EXISTS=false}",
        "workspaceCodeSpecialist": "${WORKSPACE_CODE_SPECIALIST=}",  # AC-25.30: optional
        "workspaceCodeEngineer": "${WORKSPACE_CODE_ENGINEER=}",
        "workspaceTokenSecret": "${WORKSPACE_TOKEN_SECRET}",
        "workspaceOpen": "${WORKSPACE_OPEN=true}",
    }
    assert {k: v["value"] for k, v in PARAMS.items()} == expected
    assert "AZURE_PRINCIPAL_ID" not in json.dumps(PARAMS)  # the CI principal must not get Cosmos access


def _on() -> dict[str, Any]:
    return CI.get("on", CI.get(True))  # YAML 1.1 reads the key `on` as True


def test_checks_and_image_jobs_on_every_push_and_pr() -> None:
    assert {"push", "pull_request"} <= set(_on())
    steps = " ".join(s.get("run", "") for s in CI["jobs"]["checks"]["steps"])
    for target in ("make lint", "make test", "infra-lint", "infra-test"):
        assert target in steps
    image_steps = [s.get("run", "") for s in CI["jobs"]["image"]["steps"]]
    assert "make image-check" in image_steps
    assert "if" not in CI["jobs"]["image"] and "if" not in CI["jobs"]["checks"]


def test_ac_25_26_deploy_only_from_main_after_checks_with_approval_and_oidc() -> None:
    deploy = CI["jobs"]["deploy"]
    assert set(deploy["needs"]) == {"checks", "image"}
    assert "github.ref == 'refs/heads/main'" in deploy["if"]
    assert "pull_request" not in deploy["if"]
    assert deploy["environment"] == "demo"
    assert deploy["permissions"] == {"id-token": "write", "contents": "read"}
    assert deploy["concurrency"] == {"group": "deploy-demo", "cancel-in-progress": False}
    runs = "\n".join(s.get("run", "") for s in deploy["steps"])
    uses = [s.get("uses", "") for s in deploy["steps"]]
    assert any(u.startswith("Azure/setup-azd@") for u in uses)
    assert "--federated-credential-provider github" in runs
    assert "azd provision --no-prompt" in runs and "azd deploy --no-prompt" in runs
    assert runs.index("azd provision") < runs.index("azd deploy") < runs.index("smoke.sh")
    assert "GITHUB_SHA::7" in runs and '"$APP_VERSION"' in runs


def test_ac_25_26_no_azure_secret_in_the_workflow() -> None:
    text = (REPO / ".github" / "workflows" / "ci.yml").read_text()
    secrets_used = {part.split("}}")[0].strip() for part in text.split("secrets.")[1:]}
    assert secrets_used == {"WORKSPACE_CODE_SPECIALIST", "WORKSPACE_CODE_ENGINEER", "WORKSPACE_TOKEN_SECRET"}
    for word in ("client-secret", "AZURE_CREDENTIALS", "AZURE_CLIENT_SECRET"):
        assert word not in text
    assert "azd down" not in text


def test_ac_25_30_deploy_passes_workspace_open_defaulting_to_true() -> None:
    env = CI["jobs"]["deploy"]["env"]
    assert env["WORKSPACE_OPEN"] == "${{ vars.WORKSPACE_OPEN || 'true' }}"
