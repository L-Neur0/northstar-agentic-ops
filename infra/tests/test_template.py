"""Static checks of the compiled Bicep template (spec 25 §3.4 to §3.6, §7).

Why: a wrong role, a key left on, a secret in an output or a change to the hand-made AI account
would only show up in Azure, after the damage. These tests catch them on every push, from the
ARM JSON that `az bicep build` produces, with no Azure login.
What: one test (or more) per acceptance criterion; each cites its ID.
Must not: deploy or call Azure. The live halves (what-if, smoke) are run by the user (§3.10).
Spec: 25. Acceptance criteria: AC-25.8 to AC-25.20, AC-25.29 (static half), AC-25.30 (amended
2026-11-20, open workspace: `WORKSPACE_OPEN` and optional codes).
"""

from __future__ import annotations

import json
import re
from typing import Any

from conftest import Build, Resource, module, one

ACR_PULL = "7f951dda-4ed3-4680-a7ca-43fe172d538d"
OPENAI_USER = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
COSMOS_DATA_CONTRIBUTOR = "00000000-0000-0000-0000-000000000002"


def _app(resources: list[Resource]) -> Resource:
    return one(resources, "Microsoft.App/containerApps")


def _container(resources: list[Resource]) -> dict[str, Any]:
    return _app(resources).props["template"]["containers"][0]


def _env(resources: list[Resource]) -> dict[str, dict[str, Any]]:
    """The variables always set (`baseEnv`); the optional workspace codes are checked by AC-25.30."""
    assert _container(resources)["env"] == "[concat(variables('baseEnv'), variables('codeEnv'))]"
    return {e["name"]: e for e in _app(resources).template["variables"]["baseEnv"]}


def _code_vars(resources: list[Resource]) -> tuple[str, str]:
    """The compiled `codeSecrets` and `codeEnv` expressions (one optional entry per workspace code)."""
    variables = _app(resources).template["variables"]
    return variables["codeSecrets"], variables["codeEnv"]


# --- AC-25.8 -------------------------------------------------------------------------------------------


def test_ac_25_8_builds_with_no_linter_warning_or_error(build: Build) -> None:
    assert build.returncode == 0
    assert build.diagnostics == []


# --- AC-25.9, AC-25.10 ---------------------------------------------------------------------------------


def test_ac_25_9_resource_group_scope(template: dict[str, Any]) -> None:
    assert template["$schema"].endswith("/deploymentTemplate.json#")


def test_ac_25_9_ai_account_is_only_referenced(resources: list[Resource]) -> None:
    for r in resources:
        if r.type.startswith("Microsoft.CognitiveServices/"):
            assert r.body.get("existing") is True, f"{r.type} would be created or updated"
    openai = module_template_text(resources, "openai")
    assert "Microsoft.CognitiveServices/accounts" in openai  # read through reference()/resourceId()


def module_template_text(resources: list[Resource], name: str) -> str:
    deployments = [r for r in resources if r.type == "Microsoft.Resources/deployments" and r.body["name"] == name]
    assert deployments, name
    return json.dumps(deployments[0].props["template"])


def test_ac_25_10_only_ga_api_versions(template: dict[str, Any], resources: list[Resource]) -> None:
    for r in resources:
        assert not r.body["apiVersion"].endswith("-preview"), (r.type, r.body["apiVersion"])
    # API versions inside reference()/list*() calls; the model API version parameter is data, not ARM.
    text = json.dumps(template).replace("2025-04-01-preview", "")
    assert not re.search(r"\d{4}-\d{2}-\d{2}-preview", text)


# --- AC-25.11, AC-25.12 --------------------------------------------------------------------------------


def test_ac_25_11_cosmos_account_database_container(resources: list[Resource]) -> None:
    account = one(resources, "Microsoft.DocumentDB/databaseAccounts").props
    assert {"name": "EnableServerless"} in account["capabilities"]
    assert account["disableLocalAuth"] is True
    assert account["backupPolicy"]["continuousModeProperties"]["tier"] == "Continuous7Days"
    assert len(account["locations"]) == 1
    database = one(resources, "Microsoft.DocumentDB/databaseAccounts/sqlDatabases")
    assert "throughput" not in json.dumps(database.props)
    container = one(resources, "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers").props["resource"]
    assert container["partitionKey"]["paths"] == ["/ownerId"]
    assert container["defaultTtl"] == -1
    cosmos = module(_main(resources), "cosmos")["properties"]
    assert cosmos["template"]["parameters"]["databaseName"]["defaultValue"] == "discovery"
    assert cosmos["template"]["parameters"]["containerName"]["defaultValue"] == "sessions"


def _main(resources: list[Resource]) -> dict[str, Any]:
    return next(r.template for r in resources if r.module == "")


def test_ac_25_12_cosmos_data_role_for_identity_and_optional_developer(resources: list[Resource]) -> None:
    cosmos = module(_main(resources), "cosmos")["properties"]
    ids = cosmos["parameters"]["dataContributorPrincipalIds"]["value"]
    assert len(ids) == 2
    assert "'identity'" in ids[0] and "principalId" in ids[0]
    assert ids[1] == "[parameters('developerPrincipalId')]"
    # Variant "developer empty": the module filters empty ids, so only the identity is assigned.
    filtered = cosmos["template"]["variables"]["principalIds"]
    assert "filter(" in filtered and "empty(" in filtered
    assignment = one(resources, "Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments")
    assert assignment.body["copy"]["count"] == "[length(variables('principalIds'))]"
    assert "variables('dataContributorRoleId')" in assignment.props["roleDefinitionId"]
    assert assignment.template["variables"]["dataContributorRoleId"] == COSMOS_DATA_CONTRIBUTOR


# --- AC-25.13, AC-25.14 --------------------------------------------------------------------------------


def _role_assignments(resources: list[Resource]) -> list[Resource]:
    return [r for r in resources if r.type == "Microsoft.Authorization/roleAssignments"]


def test_ac_25_13_identity_roles_on_registry_and_ai_account(resources: list[Resource]) -> None:
    by_module = {r.module: r for r in _role_assignments(resources)}
    assert set(by_module) == {"registry", "openai"}, "only AcrPull and OpenAI User are Azure RBAC roles"
    acr = by_module["registry"]
    assert "variables('acrPullRoleId')" in acr.props["roleDefinitionId"]
    assert acr.template["variables"]["acrPullRoleId"] == ACR_PULL
    assert acr.props["principalId"] == "[parameters('pullPrincipalId')]"
    assert "Microsoft.ContainerRegistry/registries" in acr.body["scope"]
    ai = by_module["openai"]
    assert "variables('openAiUserRoleId')" in ai.props["roleDefinitionId"]
    assert ai.template["variables"]["openAiUserRoleId"] == OPENAI_USER
    assert ai.props["principalId"] == "[parameters('principalId')]"
    assert "Microsoft.CognitiveServices/accounts" in ai.body["scope"]
    for r in (acr, ai):
        assert r.props["principalType"] == "ServicePrincipal"
    main = _main(resources)
    assert "developerPrincipalId" not in json.dumps(module(main, "openai")["properties"]["parameters"])
    assert "developerPrincipalId" not in json.dumps(module(main, "registry")["properties"]["parameters"])


def test_ac_25_14_role_assignment_names_are_deterministic(resources: list[Resource]) -> None:
    assignments = _role_assignments(resources) + [
        r for r in resources if r.type == "Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments"
    ]
    assert len(assignments) == 3
    for r in assignments:
        name = r.body["name"]
        assert "guid(" in name, name
        assert re.search(
            r"guid\(.+, parameters\('\w*principalId'\)|guid\(.+, variables\('principalIds'\)", name, re.I
        ), name
        assert "roleid" in name.lower(), name


# --- AC-25.15, AC-25.16 --------------------------------------------------------------------------------


def test_ac_25_15_registry_basic_no_admin_identity_pull(resources: list[Resource]) -> None:
    registry = one(resources, "Microsoft.ContainerRegistry/registries")
    assert registry.body["sku"]["name"] == "Basic"
    assert registry.props["adminUserEnabled"] is False
    assert registry.props["anonymousPullEnabled"] is False
    pulls = _app(resources).props["configuration"]["registries"]
    assert len(pulls) == 1
    assert pulls[0]["identity"] == "[parameters('identityId')]"
    assert "passwordSecretRef" not in pulls[0]
    secrets = _app(resources).props["configuration"]["secrets"] + "".join(_code_vars(resources))
    assert "password" not in secrets.lower() and "registry" not in secrets.lower()


def test_ac_25_16_log_cap_and_workspace_based_insights(resources: list[Resource]) -> None:
    workspace = one(resources, "Microsoft.OperationalInsights/workspaces").props
    assert workspace["workspaceCapping"]["dailyQuotaGb"] == "[json(parameters('logDailyCapGb'))]"
    assert workspace["retentionInDays"] == 30
    assert workspace["sku"]["name"] == "PerGB2018"
    insights = one(resources, "Microsoft.Insights/components").props
    assert "Microsoft.OperationalInsights/workspaces" in insights["WorkspaceResourceId"]
    main = _main(resources)
    assert main["parameters"]["logDailyCapGb"]["defaultValue"] == "0.5"


# --- AC-25.17, AC-25.18 --------------------------------------------------------------------------------


def test_ac_25_17_ingress_scale_and_size(resources: list[Resource]) -> None:
    app = _app(resources).props
    ingress = app["configuration"]["ingress"]
    assert ingress["external"] is True
    assert ingress["allowInsecure"] is False
    assert ingress["targetPort"] == "[variables('port')]"
    assert module(_main(resources), "containerapp")["properties"]["template"]["variables"]["port"] == 8000
    assert app["configuration"]["activeRevisionsMode"] == "Single"
    assert app["template"]["scale"] == {"minReplicas": "[parameters('minReplicas')]", "maxReplicas": 1}
    assert _container(resources)["resources"] == {"cpu": "[json('0.5')]", "memory": "1Gi"}
    min_param = _main(resources)["parameters"]["minReplicas"]
    assert (min_param["defaultValue"], min_param["minValue"], min_param["maxValue"]) == (1, 0, 1)
    identity = _app(resources).body["identity"]
    assert identity["type"] == "UserAssigned"


def test_ac_25_18_placeholder_first_then_running_image_and_probes(resources: list[Resource]) -> None:
    container = _container(resources)
    assert (
        container["image"] == "[if(parameters('appExists'), parameters('currentImage'), variables('placeholderImage'))]"
    )
    variables = module(_main(resources), "containerapp")["properties"]["template"]["variables"]
    assert variables["placeholderImage"] == "mcr.microsoft.com/k8se/quickstart:latest"
    assert variables["healthPath"] == "/api/health"
    probes = container["probes"]
    assert probes.startswith("[if(parameters('appExists'), createArray(") and probes.endswith(", createArray())]")
    for kind in ("Startup", "Liveness", "Readiness"):
        assert f"'type', '{kind}'" in probes
    assert probes.count("'path', variables('healthPath'), 'port', variables('port')") == 3


def test_ac_25_29_provision_keeps_the_running_image(resources: list[Resource]) -> None:
    main = _main(resources)
    current = module(main, "current-image")["properties"]["template"]
    assert current["resources"] == []  # existing read only, nothing created
    image = current["outputs"]["image"]["value"]
    assert image.startswith("[if(parameters('appExists'), reference(resourceId('Microsoft.App/containerApps'")
    assert "template.containers[0].image" in image
    params = module(main, "containerapp")["properties"]["parameters"]
    assert "'current-image'" in params["currentImage"]["value"]


# --- AC-25.19, AC-25.20 --------------------------------------------------------------------------------


def test_ac_25_19_environment_variables(resources: list[Resource]) -> None:
    env = _env(resources)
    assert env["DEPLOYMENT_STAGE"]["value"] == "demo"
    assert env["STORE"]["value"] == "cosmos"
    assert env["LOG_LEVEL"]["value"] == "INFO"
    assert env["COMPANY_CONFIG_DIR"]["value"] == "/app/config/nig"
    assert env["FRONTEND_DIST"]["value"] == "/app/frontend/dist"
    assert env["AZURE_CLIENT_ID"]["value"] == "[parameters('identityClientId')]"
    expected = {
        "COSMOS_ENDPOINT", "COSMOS_DATABASE", "COSMOS_CONTAINER", "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_EVAL_DEPLOYMENT", "AZURE_OPENAI_API_VERSION",
        "DAILY_TOKEN_BUDGET", "APPLICATIONINSIGHTS_CONNECTION_STRING", "WORKSPACE_TOKEN_SECRET",
        "WORKSPACE_OPEN",
    }  # fmt: skip
    assert expected <= set(env)
    for absent in ("AZURE_OPENAI_API_KEY", "APP_VERSION", "LLM_CACHE_ENABLED"):
        assert absent not in env
    params = module(_main(resources), "containerapp")["properties"]["parameters"]
    assert "'identity'" in params["identityClientId"]["value"] and "clientId" in params["identityClientId"]["value"]


def test_ac_25_20_secrets_are_secret_refs_and_params_secure(resources: list[Resource]) -> None:
    env = _env(resources)
    refs = {
        "WORKSPACE_TOKEN_SECRET": "workspace-token-secret",
        "APPLICATIONINSIGHTS_CONNECTION_STRING": "appinsights-connection-string",
    }
    for var, secret in refs.items():
        assert env[var] == {"name": var, "secretRef": secret}
    secrets = _app(resources).props["configuration"]["secrets"]
    assert secrets.startswith("[concat(createArray(") and secrets.endswith(", variables('codeSecrets'))]")
    assert set(re.findall(r"createObject\('name', '([a-z-]+)', 'value'", secrets)) == set(refs.values())
    code_secrets, code_env = _code_vars(resources)
    for var, secret in (("WORKSPACE_CODE_SPECIALIST", "workspace-code-specialist"),
                        ("WORKSPACE_CODE_ENGINEER", "workspace-code-engineer")):  # fmt: skip
        assert f"createObject('name', '{var}', 'secretRef', '{secret}')" in code_env
        assert f"createObject('name', '{secret}', 'value', parameters(" in code_secrets
    main = _main(resources)
    for name in ("workspaceCodeSpecialist", "workspaceCodeEngineer", "workspaceTokenSecret"):
        assert main["parameters"][name]["type"] == "securestring"
    assert main["parameters"]["workspaceTokenSecret"]["minLength"] == 32


def test_ac_25_20_no_output_carries_a_secret(resources: list[Resource]) -> None:
    for r in resources:
        if r.type != "Microsoft.Resources/deployments":
            continue
        for name, out in r.props["template"].get("outputs", {}).items():
            text = (name + json.dumps(out)).lower()
            for word in ("secret", "password", "connectionstring", "listkeys", "workspacecode"):
                assert word not in text, (r.body["name"], name)
    main = _main(resources)
    assert set(main["outputs"]) == {
        "AZURE_CONTAINER_REGISTRY_ENDPOINT", "SERVICE_APP_NAME", "SERVICE_APP_URI", "COSMOS_ENDPOINT",
        "COSMOS_DATABASE", "COSMOS_CONTAINER", "AZURE_OPENAI_ENDPOINT", "MANAGED_IDENTITY_CLIENT_ID",
    }  # fmt: skip


def test_tags_on_every_new_resource(resources: list[Resource]) -> None:
    for r in resources:
        if r.type == "Microsoft.Resources/deployments" or r.type.count("/") != 1:
            continue  # child resources (database, container) cannot carry tags of their own
        if r.type.startswith("Microsoft.Authorization/") or r.body.get("existing"):
            continue
        assert "tags" in r.body, r.type


# --- AC-25.30 (amended 2026-11-20, open workspace) ---------------------------------------------------------


def test_ac_25_30_workspace_open_parameter_defaults_to_true_and_reaches_the_app(resources: list[Resource]) -> None:
    main = _main(resources)
    workspace_open = main["parameters"]["workspaceOpen"]
    assert (workspace_open["type"], workspace_open["defaultValue"]) == ("bool", True)
    params = module(main, "containerapp")["properties"]["parameters"]
    assert params["workspaceOpen"]["value"] == "[parameters('workspaceOpen')]"
    assert _env(resources)["WORKSPACE_OPEN"]["value"] == "[if(parameters('workspaceOpen'), 'true', 'false')]"


def test_ac_25_30_codes_are_optional_and_set_only_when_given(resources: list[Resource]) -> None:
    main = _main(resources)
    for name in ("workspaceCodeSpecialist", "workspaceCodeEngineer"):
        assert main["parameters"][name]["type"] == "securestring"
        assert main["parameters"][name]["defaultValue"] == ""
    assert "defaultValue" not in main["parameters"]["workspaceTokenSecret"]  # the secret stays required
    code_secrets, code_env = _code_vars(resources)
    for param in ("workspaceCodeSpecialist", "workspaceCodeEngineer"):
        guard = f"if(empty(parameters('{param}')), createArray(), createArray("
        assert guard in code_secrets and guard in code_env
