# 25 · Deployment: container image, Azure infrastructure, CI/CD

> **Status:** built (not yet deployed) · **Implements:** architecture §2 (`Dockerfile`, `azure.yaml`, `infra/`), §5 (database resources), §6.5 (model deployments), §7 (deployment); implementation plan WS5 · **Depends on:** specs 10 (settings, stages, health route, frontend serving, CI), 11 (LLM settings and credentials)
> **Code:** `Dockerfile`, `.dockerignore`, `azure.yaml`, `infra/main.bicep`, `infra/main.parameters.json`, `infra/bicepconfig.json`, `infra/modules/*.bicep`, `infra/scripts/*.sh`, `.github/workflows/ci.yml` · **Tests:** `infra/tests/test_*.py`, `infra/scripts/check-image.sh`, `infra/scripts/smoke.sh`

## 1. Purpose

Ship the Discovery Agent as **one container** on Azure Container Apps, with Cosmos DB serverless and Azure OpenAI reached through **one user-assigned managed identity**, no keys and no stored CI secrets for Azure. The same image runs locally (`docker run`) and on Azure; the whole environment is described in Bicep and deployed with `azd`, by hand the first time and by GitHub Actions with a manual approval after that.

## 2. Where it sits

- **Layer:** outside the app. Nothing here changes Python or TypeScript code. It reads the settings of spec 10 §3.5 and spec 11 §4 and fills them through environment variables.
- **What exists today:**

| Item | State |
|---|---|
| App | `uvicorn app.main:app --factory`; `GET /api/health` → `{"status":"ok","stage":…,"version":…}`; serves `FRONTEND_DIST` with a page fallback (spec 10 §3.8) |
| Settings | `DEPLOYMENT_STAGE=demo` requires `STORE=cosmos` and non-default workspace codes and a token secret of 32+ characters; `AZURE_OPENAI_API_KEY` is refused outside `local` |
| Default paths | `COMPANY_CONFIG_DIR` = `<repo>/config/nig`, `FRONTEND_DIST` = `<repo>/frontend/dist`, both relative to `backend/` |
| `Makefile` | `make build` = `docker build -t discovery-agent:local .` |
| CI | `.github/workflows/ci.yml`: one `checks` job (setup, lint, test) |
| Azure, made by hand | Region **swedencentral**, resource group **`rg-northstar-discovery`**, AI Services account **`northstar-discovery-ai`** (key auth disabled, public network access on) with deployments **`app-chat`** (gpt-5.6-sol, version 2026-07-09, DataZoneStandard, capacity 300) and **`eval-expert`** (gpt-5.4-mini, version 2026-03-17, GlobalStandard, capacity 300). The developer already has *Cognitive Services OpenAI User* on the account. Resource providers App, ContainerRegistry, OperationalInsights, Insights, ManagedIdentity, DocumentDB, CognitiveServices are registered |
| Tools on the developer machine | Azure CLI 2.93, azd 1.39, Docker 29. **Missing:** Bicep CLI (`az bicep install`), GitHub CLI (azd downloads it when needed) |

- **What it changes:** adds the files listed under *Code*; adds jobs `image` and `deploy` to `ci.yml`; adds Make targets `image-check`, `infra-lint`, `infra-test`, `smoke` (shared file, the lead approves); adds `.azure/` to `.gitignore`.

## 3. Behaviour

### 3.1 Key decisions

| # | Decision | Why | Rejected |
|---|---|---|---|
| D1 | **Adopt the AI account as an `existing` resource**; Bicep only reads it (endpoint) and adds one role assignment at its scope | The account and deployments were made by hand with quota already granted. Re-declaring them risks a quota or SKU error on redeploy, silent drift (for example the version upgrade setting), and makes them look owned by this template. `existing` guarantees what-if shows **no change** to them | Idempotent declaration with identical properties: works on day 1, but any property azd or a later API version sees differently becomes a modify or a failure on a resource the demo depends on |
| D2 | `main.bicep` is **resource-group scoped**, targeting the existing `rg-northstar-discovery` (`AZURE_RESOURCE_GROUP`) | The group already holds the AI account; azd must not create a second group | Subscription scope that creates the group (azd default) |
| D3 | **Secrets as Container Apps secrets**, values from the azd environment (`@secure()` parameters); no Key Vault in the prototype | Three small values; Container Apps secrets are encrypted at rest and never in the image or logs. Key Vault adds a resource, a role and reference refresh delays for no gain at this size. Key Vault is a production item (production readiness §3) | Key Vault references; plain environment variables |
| D4 | **Image built by Docker on the machine running azd** (developer or GitHub runner), pushed to ACR with the identity of whoever runs azd; `remoteBuild: false` | Docker is present in both places; ACR Tasks can be restricted on some subscription types. One switch (`remoteBuild: true`) moves the build into ACR if needed | Remote build as default |
| D5 | **One replica**: `maxReplicas 1`, `minReplicas 1` during the demo period (parameter), 0 afterwards | Rate-limit counters, daily budget and caches live in process memory (architecture §10) | Autoscale |
| D6 | **One uvicorn worker**, no Gunicorn | Same reason as D5; the container platform restarts the process | Several workers |
| D7 | First provision uses a **public placeholder image**; probes are set only once the app exists (`appExists`) | The registry is empty before the first deploy, and a fresh AcrPull assignment needs time to take effect. Standard azd pattern | Building and pushing before the app exists (needs a two-layer template) |
| D8 | **Never `azd down`** on this environment | It deletes the whole resource group, including the hand-made AI account and its quota | — |
| D9 | Deploy from CI only through a **protected GitHub environment `demo`** with a required reviewer, signing in with **OIDC** (federated credential) | No Azure secret in GitHub; every deploy is approved by a person | Client secret; deploy on every push without approval |

### 3.2 Container image (`Dockerfile`, `.dockerignore`)

Three stages; the final image mirrors the repo layout, so the default paths of spec 10 work without overrides.

| Stage | Base | Does |
|---|---|---|
| `web` | `node:22-bookworm-slim` (tag pinned to a minor version) | `COPY frontend/package.json frontend/package-lock.json` → `npm ci` → `COPY frontend/` → `npm run build` → `/src/frontend/dist` |
| `deps` | `python:3.12-slim-bookworm` + `uv` binary copied from `ghcr.io/astral-sh/uv:<pinned>` | `COPY backend/pyproject.toml backend/uv.lock` → `uv sync --frozen --no-dev` into `/app/backend/.venv` (`UV_COMPILE_BYTECODE=1`, `UV_LINK_MODE=copy`) |
| `runtime` | `python:3.12-slim-bookworm` (same tag as `deps`) | Creates user `app` (uid/gid **10001**, no shell login, no home writes needed); copies `.venv`, `backend/app`, `config/`, and `dist` from `web`; no `uv`, no Node, no compilers, no tests |

Runtime layout and settings:

| Path in image | From |
|---|---|
| `/app/backend/app/` | `backend/app/` |
| `/app/backend/.venv/` | `deps` stage |
| `/app/config/` | `config/` |
| `/app/frontend/dist/` | `web` stage |

```dockerfile
# runtime stage (abridged)
ARG APP_VERSION=0.0.0-local
ENV PATH="/app/backend/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    APP_VERSION=${APP_VERSION}
WORKDIR /app/backend
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--timeout-graceful-shutdown", "20"]
```

Rules:

1. `APP_VERSION` is a **build argument** (CI passes the short commit SHA), so `/api/health` reports the version of the image actually running. It is not set as a container app variable (that would override it).
2. `DEPLOYMENT_STAGE` has **no default in the image** beyond the settings default (`local`); Azure sets `demo` explicitly (stage never guessed, spec 10).
3. uvicorn keeps its default proxy-header trust (only `127.0.0.1`). Reading the client IP behind the ingress (last `X-Forwarded-For` entry) belongs to spec 16.
4. No `HEALTHCHECK` instruction: Container Apps ignores it; probes are defined in Bicep (§3.5).
5. `.dockerignore` excludes at least: `.git`, `.github`, `.work`, `brief`, `.azure`, `.env*`, `**/node_modules`, `**/.venv`, `**/__pycache__`, `**/.cache`, `frontend/dist`, `backend/tests`, `eval`, `docs`, `specs`, `infra`. **`.work/` and `brief/` must never reach the build context** (confidentiality rule).
6. Requires `frontend/package-lock.json` committed (it exists since the foundation scaffold, spec 10).

### 3.3 `azure.yaml`

```yaml
name: discovery-agent
infra:
  provider: bicep
  path: infra
  module: main
services:
  app:                         # tag azd-service-name: app on the container app
    project: .
    language: py
    host: containerapp
    docker:
      path: ./Dockerfile
      context: .
      remoteBuild: false       # D4
      buildArgs:
        - APP_VERSION=${APP_VERSION}
pipeline:
  provider: github
  variables: [AZURE_RESOURCE_GROUP, MIN_REPLICAS, DEVELOPER_PRINCIPAL_ID]
  secrets: [WORKSPACE_CODE_SPECIALIST, WORKSPACE_CODE_ENGINEER, WORKSPACE_TOKEN_SECRET]
```

### 3.4 Bicep layout and resources

```
infra/
├── main.bicep                targetScope = 'resourceGroup'; wires the modules; outputs
├── main.parameters.json      maps azd environment values to parameters
├── bicepconfig.json          linter: secure-secrets-in-params, outputs-should-not-contain-secrets,
│                             no-hardcoded-env-urls, use-recent-api-versions → error
├── modules/
│   ├── identity.bicep        user-assigned identity
│   ├── monitoring.bicep      Log Analytics (daily cap) + workspace-based App Insights
│   ├── registry.bicep        ACR Basic, admin user off, AcrPull for the identity
│   ├── cosmos.bicep          serverless account, database, container, data-plane roles
│   ├── openai.bicep          existing AI account + Cognitive Services OpenAI User for the identity
│   └── containerapp.bicep    environment + app (ingress, scale, probes, env, secrets)
├── scripts/
│   ├── check-image.sh        local image checks (§3.8)
│   └── smoke.sh              post-deploy smoke check (§3.9)
└── tests/                    pytest checks on the compiled template and files (§7)
```

Names use `token = uniqueString(subscription().id, resourceGroup().id, environmentName)`. Every new resource gets tags `project=northstar-discovery` and `azd-env-name=<env>`. Only GA API versions (no `-preview`).

| Resource | Name (example, env `demo`) | Key settings |
|---|---|---|
| User-assigned identity | `id-discovery-<token>` | Used by the app for ACR pull, Cosmos, OpenAI. Its client id goes to `AZURE_CLIENT_ID` |
| Log Analytics | `log-discovery-<token>` | SKU PerGB2018, retention 30 days, **daily cap `logDailyCapGb` (default 0.5 GB)** |
| App Insights | `appi-discovery-<token>` | Workspace-based on the workspace above; local auth left on (connection string ingestion) |
| Container Registry | `crdiscovery<token>` | **Basic**, `adminUserEnabled: false`, anonymous pull off. Role **AcrPull** (`7f951dda-4ed3-4680-a7ca-43fe172d538d`) to the identity |
| Cosmos DB account | `cosmos-discovery-<token>` | NoSQL, capability `EnableServerless`, **`disableLocalAuth: true`**, single region swedencentral, Session consistency, TLS 1.2 minimum, backup **Continuous7Days**, public network access on (prototype) |
| Cosmos database | `discovery` | No throughput (serverless) |
| Cosmos container | `sessions` | Partition key **`/ownerId`**, **`defaultTtl: -1`** (TTL on, items expire only when they carry `ttl`), default indexing |
| Cosmos data-plane roles | — | **Cosmos DB Built-in Data Contributor** (`00000000-0000-0000-0000-000000000002`) at account scope to the identity, and to `developerPrincipalId` when it is not empty |
| AI Services account | `northstar-discovery-ai` (**existing**) | Read only. Role **Cognitive Services OpenAI User** (`5e0bd9bd-7b93-4f28-af87-19fc36ad61bd`) to the identity, scoped to the account. The developer's existing assignment is **not** redeclared (a duplicate with another name fails with `RoleAssignmentExists`) |
| Container Apps environment | `cae-discovery-<token>` | Consumption, logs to the workspace |
| Container app | `ca-discovery-<token>` | See §3.5 |

Role assignment names are `guid(scope, principalId, roleDefinitionId)`, so re-running provision changes nothing. The app **never creates** databases or containers (the data-plane role cannot, and Bicep owns them); spec 15's Cosmos store only reads and writes items.

### 3.5 Container app

| Setting | Value |
|---|---|
| Identity | The user-assigned identity only |
| Registry | `crdiscovery<token>.azurecr.io`, `identity: <identity id>` (no password) |
| Revisions | Single revision mode |
| Ingress | External, HTTPS only (`allowInsecure: false`), **target port 8000**, transport auto. Request timeout is the platform's (about 240 s); the turn guard of 150 s (architecture §6.1) stays under it |
| Resources | 0.5 vCPU, 1 GiB |
| Scale | `minReplicas = MIN_REPLICAS` (default **1**), `maxReplicas = 1`, no scale rules |
| Image | First provision (`appExists=false`): `mcr.microsoft.com/k8se/quickstart:latest`. Later provisions: the image currently running (read from the existing app), so provision never rolls the app back. `azd deploy` sets the real image |
| Probes (only when `appExists=true`) | **Startup** HTTP GET `/api/health` :8000, period 5 s, failure threshold 24 (2 min). **Liveness** same path, period 30 s, threshold 3. **Readiness** same path, period 10 s, threshold 3. `/api/health` touches no dependency, so a Cosmos or model outage does not restart the container |

Environment variables (worked example, env `demo`):

| Variable | Value | Source |
|---|---|---|
| `DEPLOYMENT_STAGE` | `demo` | Fixed in Bicep |
| `STORE` | `cosmos` | Fixed |
| `COSMOS_ENDPOINT` | `https://cosmos-discovery-<token>.documents.azure.com:443/` | Cosmos module output |
| `COSMOS_DATABASE` / `COSMOS_CONTAINER` | `discovery` / `sessions` | Fixed (same names as the resources) |
| `AZURE_OPENAI_ENDPOINT` | `https://northstar-discovery-ai.cognitiveservices.azure.com/` | `existing` account `properties.endpoint` |
| `AZURE_OPENAI_DEPLOYMENT` | `app-chat` | Parameter `appDeploymentName` |
| `AZURE_OPENAI_EVAL_DEPLOYMENT` | `eval-expert` | Parameter `evalDeploymentName` |
| `AZURE_OPENAI_API_VERSION` | `2025-04-01-preview` | Parameter (the version the smoke call used) |
| `AZURE_CLIENT_ID` | client id of the user-assigned identity | Identity module output, **never** from an azd/CI variable (CI has its own `AZURE_CLIENT_ID` for the deploy principal) |
| `LOG_LEVEL` | `INFO` | Fixed |
| `DAILY_TOKEN_BUDGET` | `2000000` | Parameter `dailyTokenBudget` |
| `COMPANY_CONFIG_DIR` / `FRONTEND_DIST` | `/app/config/nig` / `/app/frontend/dist` | Fixed (explicit, same as the defaults) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | secret ref `appinsights-connection-string` | Monitoring module |
| `WORKSPACE_CODE_SPECIALIST` | secret ref `workspace-code-specialist` | `@secure()` param ← azd env |
| `WORKSPACE_CODE_ENGINEER` | secret ref `workspace-code-engineer` | `@secure()` param ← azd env |
| `WORKSPACE_TOKEN_SECRET` | secret ref `workspace-token-secret` | `@secure()` param (`@minLength(32)`) ← azd env |

**Never set:** `AZURE_OPENAI_API_KEY` (the settings refuse it outside `local`; the account has keys disabled anyway), `LLM_CACHE_ENABLED`, `APP_VERSION`.

### 3.6 Parameters and outputs

| Parameter | Type | Default | From azd env |
|---|---|---|---|
| `environmentName` | string | — | `AZURE_ENV_NAME` |
| `location` | string | `resourceGroup().location` | `AZURE_LOCATION` |
| `openAiAccountName` | string | `northstar-discovery-ai` | — |
| `appDeploymentName` / `evalDeploymentName` | string | `app-chat` / `eval-expert` | — |
| `openAiApiVersion` | string | `2025-04-01-preview` | — |
| `developerPrincipalId` | string | `''` (skip) | `DEVELOPER_PRINCIPAL_ID` |
| `minReplicas` | int, allowed 0–1 | `1` | `MIN_REPLICAS` |
| `logDailyCapGb` | string (decimal) | `'0.5'` | — |
| `dailyTokenBudget` | int | `2000000` | — |
| `appExists` | bool | `false` | `SERVICE_APP_RESOURCE_EXISTS` (set by azd) |
| `workspaceCodeSpecialist`, `workspaceCodeEngineer` | `@secure()` string | — | `WORKSPACE_CODE_SPECIALIST`, `WORKSPACE_CODE_ENGINEER` |
| `workspaceTokenSecret` | `@secure()` string, min 32 | — | `WORKSPACE_TOKEN_SECRET` |

`DEVELOPER_PRINCIPAL_ID` is a dedicated variable on purpose: azd's `AZURE_PRINCIPAL_ID` is the CI principal when CI runs, which would grant Cosmos data access to the pipeline.

| Output (written to the azd env) | Used by |
|---|---|
| `AZURE_CONTAINER_REGISTRY_ENDPOINT` | azd, to push the image |
| `SERVICE_APP_NAME`, `SERVICE_APP_URI` | azd, smoke check |
| `COSMOS_ENDPOINT`, `AZURE_OPENAI_ENDPOINT` | developer, for local runs against Azure |
| `MANAGED_IDENTITY_CLIENT_ID` | checks |

No output contains a secret or a connection string.

### 3.7 Stages

| Stage | Where | Store | Model | Set by |
|---|---|---|---|---|
| `local` | `make dev`, and `docker run` checks | memory (or Cosmos with the developer's role) | `az login` credential or cache | default |
| `test` | pytest | memory | `FakeLLM` | tests |
| `demo` | Azure Container Apps | Cosmos | managed identity | Bicep, explicitly |

### 3.8 Local image check (agent can run)

`infra/scripts/check-image.sh` (Make target `image-check`):

1. `docker build --build-arg APP_VERSION=check -t discovery-agent:local .`
2. `docker run -d -p 8000:8000 -e DEPLOYMENT_STAGE=local discovery-agent:local`; wait up to 30 s for health.
3. `GET /api/health` → 200, `stage` `local`, `version` `check`. `GET /` and `GET /process-discovery/abc` → 200 HTML with the app root. `GET /api/nope` → 404 JSON.
4. `docker run --rm discovery-agent:local id -u` → `10001`; `which uv node npm gcc` finds nothing; `/app/backend/tests`, `/app/.work`, `/app/brief` do not exist.
5. `docker run -e DEPLOYMENT_STAGE=demo discovery-agent:local` (no secrets) exits non-zero within 15 s and its log lists the missing demo settings (fail fast, spec 10).
6. Image size reported; target under 600 MB.

### 3.9 Smoke check after deploy

`infra/scripts/smoke.sh <url> [expected-version]` (agent or CI can run; read only):

| Check | Pass |
|---|---|
| `GET <url>/api/health` | 200 within 10 s, `stage` = `demo`, `version` = expected SHA when given |
| `GET <url>/` | 200, HTML, CSP and HSTS headers present |
| `GET http://<host>/api/health` | Redirect to HTTPS or refused; never a 200 over HTTP |
| `GET <url>/api/nope` | 404 JSON |
| (after spec 15) `POST /api/sessions` then one turn | 200 within 60 s with an agent question (proves Cosmos write and model call through the identity) |

Retries: 10 attempts, 15 s apart (new revision start-up). Exit code non-zero on any failure.

### 3.10 Who runs what

The agent never runs a command that creates, changes or deletes Azure resources.

| Step | Command | Who |
|---|---|---|
| 1 | `az bicep install` (local tool) | Agent or user |
| 2 | `make lint test infra-lint infra-test image-check` | Agent |
| 3 | `azd auth login` (and `az login` for read-only checks) | **User** |
| 4 | `azd env new demo`; `azd env set AZURE_SUBSCRIPTION_ID <id>`; `azd env set AZURE_LOCATION swedencentral`; `azd env set AZURE_RESOURCE_GROUP rg-northstar-discovery` | **User** |
| 5 | `azd env set DEVELOPER_PRINCIPAL_ID $(az ad signed-in-user show --query id -o tsv)`; `azd env set MIN_REPLICAS 1` | **User** |
| 6 | `azd env set WORKSPACE_CODE_SPECIALIST …`, `WORKSPACE_CODE_ENGINEER …`, `WORKSPACE_TOKEN_SECRET "$(openssl rand -base64 48)"` (values chosen by the user, never pasted into chat or files in the repo) | **User** |
| 7 | `azd provision --preview` (what-if) and review against §3.11 | User runs; agent may read and compare the output |
| 8 | `azd up` | **User** |
| 9 | `azd provision` once more (sets probes now that the app exists, D7) | **User** |
| 10 | `infra/scripts/smoke.sh "$(azd env get-value SERVICE_APP_URI)"` | Agent |
| 11 | `azd pipeline config --provider github` | **User** |
| 12 | GitHub: create environment `demo`, required reviewer = the user, deployment branch `main`; move the three workspace secrets to environment secrets; add variable `AZURE_RESOURCE_GROUP` | **User** |
| 13 | Add a federated credential with subject `repo:<owner>/<repo>:environment:demo` to the app registration azd created (`az ad app federated-credential create …`), because azd only creates the branch and pull-request subjects | **User** |
| 14 | Approve each deploy in GitHub | **User** |
| 15 | After the demo period: `azd env set MIN_REPLICAS 0 && azd provision` | **User** |

### 3.11 Expected what-if (first provision)

| Change | Resources |
|---|---|
| Create | identity, Log Analytics, App Insights, ACR, AcrPull assignment, Cosmos account, database, container, 2 Cosmos data-plane assignments (identity, developer), OpenAI User assignment on the AI account, Container Apps environment, container app |
| Modify | **none** |
| Delete | **none** |
| Ignore / no change | `northstar-discovery-ai` and its deployments `app-chat`, `eval-expert` |

A what-if that shows a modify or delete on the AI account or its deployments stops the deployment.

### 3.12 GitHub Actions

`ci.yml` keeps `checks` and adds:

| Job | Runs when | Steps |
|---|---|---|
| `checks` | every push and PR | unchanged, plus `make infra-lint infra-test` |
| `image` | every push and PR | `make image-check` (no push) |
| `deploy` | push to `main`, after `checks` and `image` | `environment: demo` (manual approval); `permissions: id-token: write, contents: read`; `concurrency: deploy-demo` (no cancel); `Azure/setup-azd`; `azd auth login --federated-credential-provider github --client-id ${{ vars.AZURE_CLIENT_ID }} --tenant-id ${{ vars.AZURE_TENANT_ID }}`; `azd provision --no-prompt`; `azd deploy --no-prompt` with `APP_VERSION=${GITHUB_SHA::7}`; `infra/scripts/smoke.sh` with that version |

Workspace secrets come from the `demo` environment's secrets as job environment variables; no Azure credential is stored in GitHub.

### 3.13 Cost (EUR per month, list-price estimates; assumptions, check with the pricing calculator)

| Item | Demo period (min 1 replica) | After (min 0) |
|---|---|---|
| Container Apps, 0.5 vCPU / 1 GiB, after the monthly free grant | 10–30 | 0–5 |
| Container Registry Basic | ~5 | ~5 |
| Cosmos DB serverless (< 1 GB, low traffic; 7-day continuous backup is free) | 1–5 | < 1 |
| Log Analytics + App Insights (cap 0.5 GB/day; worst case ~€35) | 0–5 | 0–2 |
| Identity, role assignments, Container Apps environment | 0 | 0 |
| **Total without tokens** | **~€16–45** | **~€5–12** |
| Azure OpenAI tokens | Pay per use; capped per day by `DAILY_TOKEN_BUDGET` (2M tokens) | same |

### 3.14 Rollback

| Problem | Action | Who |
|---|---|---|
| New image is broken (smoke fails) | `az containerapp update -n <app> -g rg-northstar-discovery --image <acr>/<repo>:<previous tag>` (tags from `az acr repository show-tags`); or re-run the deploy workflow on the last good commit | User |
| Bad infrastructure change | Revert the commit; `azd provision` (what-if first) | User |
| App unhealthy after a settings change | Fix the azd env value; `azd provision` creates a new revision | User |
| Data damaged | Cosmos point-in-time restore (last 7 days) into a **new** account; point `COSMOS_ENDPOINT` at it | User |
| Leaked workspace code or secret | `azd env set …` new value; `azd provision`; changing the token secret signs every workspace user out | User |
| Cost runaway | `azd env set MIN_REPLICAS 0 && azd provision`; lower `DAILY_TOKEN_BUDGET` | User |
| **Never** | `azd down` (deletes the group with the AI account, D8) | — |

## 4. Interfaces

```bash
make image-check                     # §3.8, local, no Azure
make infra-lint                      # az bicep build --file infra/main.bicep --stdout > /dev/null, linter rules as errors
make infra-test                      # pytest infra/tests (compiled ARM JSON, Dockerfile, azure.yaml, workflow)
make smoke URL=https://… [VERSION=abc1234]   # §3.9
```

```bicep
// main.bicep (signature)
targetScope = 'resourceGroup'
param environmentName string
param location string = resourceGroup().location
param openAiAccountName string = 'northstar-discovery-ai'
param appDeploymentName string = 'app-chat'
param evalDeploymentName string = 'eval-expert'
param openAiApiVersion string = '2025-04-01-preview'
param developerPrincipalId string = ''
@minValue(0) @maxValue(1) param minReplicas int = 1
param logDailyCapGb string = '0.5'
param dailyTokenBudget int = 2000000
param appExists bool = false
@secure() param workspaceCodeSpecialist string
@secure() param workspaceCodeEngineer string
@secure() @minLength(32) param workspaceTokenSecret string
```

## 5. Implications

- **Other components:** spec 15's Cosmos store uses `DefaultAzureCredential`/`ManagedIdentityCredential(client_id=AZURE_CLIENT_ID)` and only item operations (no database or container creation). Spec 16 takes the client IP from the last `X-Forwarded-For` entry. Spec 11 is unchanged (managed identity in `demo`). `/api/health` must stay dependency-free and cheap.
- **Data:** none added. TTL behaviour relies on `defaultTtl: -1` plus the per-item `ttl` of spec 12.
- **Config:** new azd variables `DEVELOPER_PRINCIPAL_ID`, `MIN_REPLICAS`, `APP_VERSION`, the three workspace values. No new app settings.
- **Security and privacy:** no keys anywhere (Cosmos and OpenAI have local auth off); secrets only in the azd env (git-ignored `.azure/`), GitHub environment secrets and Container Apps secrets; non-root image without dev tools; `.work/` and `brief/` excluded from the build context; public ingress and public data endpoints are prototype choices (private endpoints are a production item).
- **Cost and latency:** §3.13. No model calls added (the smoke turn makes at most 3 calls per run).

## 6. Acceptance criteria

| ID | Given / when / then |
|---|---|
| AC-25.1 | Given a clean clone with `frontend/package-lock.json`, when `docker build .` runs, then it succeeds with no network access to Azure and no secret |
| AC-25.2 | Given the built image run with `DEPLOYMENT_STAGE=local` and no Azure variables, when `GET /api/health` is called, then 200 `{"status":"ok","stage":"local","version":"check"}` within 30 s of start |
| AC-25.3 | Given the same container, when `GET /` and `GET /process-discovery/abc` are called, then both return 200 HTML from `frontend/dist`; `GET /api/nope` returns 404 JSON |
| AC-25.4 | Given the image, then the process runs as uid 10001, and `uv`, `node`, `npm`, `gcc` and `backend/tests` are absent |
| AC-25.5 | Given the image run with `DEPLOYMENT_STAGE=demo` and no secrets, then the container exits non-zero within 15 s and the log names each missing demo setting |
| AC-25.6 | Given `.dockerignore`, then `.work`, `brief`, `.azure`, `.env*`, `.git` and `node_modules` are excluded (test builds a context listing and checks none appear) |
| AC-25.7 | The container command is `uvicorn app.main:app --factory` on port 8000 with exactly one worker |
| AC-25.8 | `az bicep build --file infra/main.bicep` exits 0 with no linter warning or error under `infra/bicepconfig.json` |
| AC-25.9 | The compiled template targets resource-group scope and contains no resource of type `Microsoft.CognitiveServices/accounts` or `.../deployments` to create or update (existing reference only) |
| AC-25.10 | The compiled template uses only GA API versions (none ends in `-preview`) |
| AC-25.11 | The Cosmos account has `EnableServerless`, `disableLocalAuth: true`, `Continuous7Days` backup; database `discovery`; container `sessions` with partition key `/ownerId` and `defaultTtl: -1` |
| AC-25.12 | Cosmos data-plane role `…0002` is assigned to the identity, and to `developerPrincipalId` only when it is not empty (two compiled variants checked) |
| AC-25.13 | The identity gets AcrPull on the registry and Cognitive Services OpenAI User on the AI account; no role is assigned to the developer on the AI account |
| AC-25.14 | Every role assignment name is `guid(scope, principalId, roleDefinitionId)` (re-provision is a no-op) |
| AC-25.15 | The registry is Basic with the admin user disabled; the container app pulls with the identity, with no registry password secret |
| AC-25.16 | Log Analytics has a daily cap equal to `logDailyCapGb`; App Insights is workspace-based on it |
| AC-25.17 | The container app has external ingress, `allowInsecure: false`, target port 8000, `maxReplicas: 1`, `minReplicas` from the parameter, 0.5 vCPU / 1 GiB |
| AC-25.18 | With `appExists=true`, startup, liveness and readiness probes call `/api/health` on 8000; with `appExists=false`, the placeholder image is used and no custom probes are set |
| AC-25.19 | The container app sets `DEPLOYMENT_STAGE=demo`, `STORE=cosmos` and every variable of §3.5; `AZURE_CLIENT_ID` comes from the identity resource; `AZURE_OPENAI_API_KEY` and `APP_VERSION` are absent |
| AC-25.20 | Workspace codes, token secret and the App Insights connection string are Container Apps secrets referenced by `secretRef`; the three workspace parameters are `@secure()`; no output contains a secret (linter rule + test) |
| AC-25.21 | `azure.yaml` defines service `app` with `host: containerapp`, Docker path `./Dockerfile`, `APP_VERSION` build argument, and the pipeline secrets of §3.3 |
| AC-25.22 | Given a logged-in user and the azd env of §3.10, when `azd provision --preview` runs, then the result matches §3.11: creates only, and no modify or delete on `northstar-discovery-ai`, `app-chat` or `eval-expert` |
| AC-25.23 | After `azd up` and the second `azd provision`, `smoke.sh` passes: health 200 with `stage` `demo`, the SPA served with CSP and HSTS, HTTP never answers 200 |
| AC-25.24 | After spec 15 is deployed, the smoke turn creates a session and gets an agent question within 60 s (Cosmos and Azure OpenAI reached through the identity, no key) |
| AC-25.25 | Requests to the app appear in App Insights within 10 minutes, and `/api/health` does not |
| AC-25.26 | The `deploy` job runs only on push to `main` after `checks` and `image` pass, uses `environment: demo`, `id-token: write`, OIDC sign-in, and contains no Azure secret |
| AC-25.27 | A deploy waits for the reviewer's approval in the `demo` environment, then `smoke.sh` passes with `version` equal to the commit's short SHA |
| AC-25.28 | Rollback: updating the app to the previous image tag makes `/api/health` report the previous version within 3 minutes |
| AC-25.29 | Re-running `azd provision` with no change keeps the running image and creates no new role assignment (what-if shows no create, modify or delete beyond a possible new revision) |

## 7. Test plan

| Test | Covers | Runs |
|---|---|---|
| `infra/scripts/check-image.sh` (`make image-check`) | AC-25.1–50.5, 50.7 | Agent locally; CI `image` job |
| `infra/tests/test_dockerfile.py` (parses `Dockerfile`, `.dockerignore`; context listing via `docker build` with a listing stage or `tar` of the filtered context) | AC-25.4, 50.6, 50.7 | CI `checks` |
| `make infra-lint` | AC-25.8 | Agent; CI `checks` |
| `infra/tests/test_template.py` (compiles `main.bicep` to ARM JSON, asserts on resources, properties, outputs; builds variants for `appExists` and `developerPrincipalId`) | AC-25.9–50.20, 50.29 (static half) | CI `checks` |
| `infra/tests/test_azd_and_workflow.py` (parses `azure.yaml`, `ci.yml`) | AC-25.21, 50.26 | CI `checks` |
| `azd provision --preview`, reviewed against §3.11 | AC-25.22, 50.29 | User runs; agent compares |
| `infra/scripts/smoke.sh` | AC-25.23, 50.24, 50.27, 50.28 | Agent after the user deploys; CI `deploy` |
| App Insights query (`requests` table, last 10 min) | AC-25.25 | Agent with read-only `az monitor app-insights query` |

## 8. Out of scope

- Custom domain, certificates, Front Door/WAF, private endpoints, VNet (production readiness §3).
- Entra ID sign-in (production readiness §2).
- More than one replica, shared rate-limit store (production readiness §5).
- Alerts and a cost budget resource (a budget can be added by hand; see Q4).
- The evaluation runner's own deployment target (spec 24 runs against the deployed URL).
- Creating or changing the AI account and its model deployments (made by hand; D1).

## 9. Open questions

| # | Question | Default until decided |
|---|---|---|
| Q1 | The repo is private until submission; GitHub environments with required reviewers need a public repo or a paid plan | Until public: `deploy` triggers only on `workflow_dispatch` (a manual run is the approval); switch to push + `environment: demo` when the repo goes public |
| Q2 | *(done)* Model version pinning | Both deployments set to `NoAutoUpgrade` on 2026-11-19, so the model cannot change under the evaluation |
| Q3 | `azd pipeline config` grants its principal broad roles at subscription scope | Accept for the prototype; the user narrows them to the resource group after setup |
| Q4 | Add an Azure cost budget with an e-mail alert (for example €50/month)? | Yes, made by hand on the resource group |
| Q5 | Cosmos serverless can hit regional capacity limits in swedencentral at creation time | Retry; else set Cosmos `location` to another EU region (parameter), accepting cross-region latency |
| Q6 | If ACR pushes from the GitHub runner are slow or blocked, switch to `remoteBuild: true`? | Local Docker build (D4) |
