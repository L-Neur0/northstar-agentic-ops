# 10 · Foundation: repo, tooling, settings, company config, app shell

> **Status:** amended 2026-11-20 (open workspace: `WORKSPACE_OPEN`, product owner decision) · built (CI on GitHub Actions) · **Implements:** F-22 (product), architecture §2, §3.1, §3.6–3.9, §4.3 · **Depends on:** — (first spec) · **Used by:** every other spec
> **Code:** `backend/pyproject.toml`, `backend/app/main.py`, `backend/app/core/*`, `config/nig/*`, `frontend/` (scaffold), `Makefile`, `.github/workflows/ci.yml` · **Tests:** `backend/tests/unit/core/`, `backend/tests/unit/process_discovery/test_architecture.py`, `backend/tests/test_smoke.py`

## 1. Purpose

Give every workstream the same ground to build on: one repo layout, pinned dependencies, one command to test and lint, typed settings, the company configuration loaded and checked at start-up, JSON logs, an app factory with a health route, the layer guard, and an empty frontend that builds. Nothing here knows about interviews yet.

## 2. Where it sits

- **Layer:** the shell around the engine (`app/core`, `app/main.py`) and the repo itself. It imports nothing from `app/services/process_discovery` except the façade (for the layer test it only reads files).
- **Exists today:** only `docs/`, `specs/` and `config/` is empty.
- **Creates:** the folders of architecture §2; empty packages with `__init__.py` and a module docstring that says what belongs there.

## 3. Behaviour

### 3.1 Repository layout

Exactly architecture §2. Every Python package directory has an `__init__.py`; the engine packages exist from day one (empty), so the layer test and the workstreams have their homes:

```
backend/app/services/process_discovery/{domain,profile,interview,interview/prompts,documents,artifacts,admin,export,overview}/
backend/tests/unit/process_discovery/{domain,profile,interview,documents,artifacts,admin,export,overview}/
backend/tests/{unit/core,unit/models,unit/utils,api,fixtures}/
```

### 3.2 Backend toolchain

| Item | Choice |
|---|---|
| Python | 3.12, managed with `uv`; `backend/pyproject.toml` + `uv.lock` committed |
| Runtime dependencies (exact pins in the lock file) | fastapi 0.138.x, langgraph 1.2.x, uvicorn[standard] 0.32.x, pydantic 2.14.x, pydantic-settings 2.x, openai 2.54.x, azure-identity 1.26.x, azure-cosmos 4.x, httpx 0.28.x, python-multipart, PyYAML, reportlab 4.4.x, openpyxl 3.1.x, pypdf, python-docx, defusedxml, slowapi 0.1.10, azure-monitor-opentelemetry 1.8.x |
| Dev dependencies | pytest, pytest-asyncio, ruff, pyright |
| Package import root | `backend/` (so imports read `from app.core.settings import Settings`) |
| pytest | `asyncio_mode = "auto"`; markers `live` (real model, skipped unless `RUN_LIVE=1`) and `slow`; tests never need Azure variables to import |
| ruff | `line-length = 120`; rules `E`, `F`, `B`, `I`, `UP`, ignoring `B008` (FastAPI's `Depends()` idiom) and `E501`; **blocking** in CI |
| pyright | `basic` for the app; `strict` for `domain/` and `profile/` (the pure core) |

### 3.3 Frontend toolchain

| Item | Choice |
|---|---|
| Stack | Node 22+, Vite 7, React 18, TypeScript 5 (`strict`), Tailwind 3, React Router 7, React Query 5, lucide-react, react-markdown + remark-gfm, mermaid |
| Tests | Vitest + Testing Library + jsdom; `src/test/setup.ts` |
| Lint | ESLint with zero warnings |
| Dev server | Vite on 5173, proxy `/api` → `http://localhost:8000` |
| Build | `npm run build` → `frontend/dist`, served by FastAPI in the container |

The scaffold renders one page ("Discovery Agent") that calls `GET /api/health` and shows the result. Screens come in spec 23.

### 3.4 Make targets

| Target | Does |
|---|---|
| `make setup` | `uv sync` in `backend/`, `npm ci` in `frontend/` |
| `make dev` | Backend with reload on :8000 (stage `local`, in-memory store) and Vite on :5173 |
| `make test` | `pytest` (backend) and `vitest run` (frontend) |
| `make lint` | `ruff check`, `pyright`, `eslint`, `tsc --noEmit` |
| `make build` | Docker image (spec 25) |
| `make chat`, `make eval` | Placeholders that print "added in spec 14 / 40" |

### 3.5 Settings (`app/core/settings.py`)

One `Settings` class (pydantic-settings), read from the environment (and `backend/.env` in local runs). Created once in the app lifespan and passed by dependency injection; **never** created at import time.

| Key | Default | Rule |
|---|---|---|
| `DEPLOYMENT_STAGE` | `local` | One of `local`, `test`, `demo`. Never guessed from the environment |
| `COMPANY_CONFIG_DIR` | `../config/nig` | Must exist and load (§3.6) |
| `STORE` | `memory` | `memory` or `cosmos`; `demo` requires `cosmos` |
| `COSMOS_ENDPOINT`, `COSMOS_DATABASE`, `COSMOS_CONTAINER` | —, `discovery`, `sessions` | Required when `STORE=cosmos` |
| `WORKSPACE_CODE_SPECIALIST`, `WORKSPACE_CODE_ENGINEER`, `WORKSPACE_TOKEN_SECRET` | dev values in `local`/`test` only | Required and non-default in `demo`; *(amended 2026-11-20 (open workspace))* with `WORKSPACE_OPEN=true` the two codes are not required (they are not used), the token secret still is |
| `WORKSPACE_OPEN` *(amended 2026-11-20 (open workspace))* | `false` | `true` opens the workspace with a name only and switches delete off (spec 16 §3.2 item 5, spec 21 §3.6 item 4) |
| `RATE_LIMIT_PER_VISITOR`, `RATE_LIMIT_PER_IP` | `30/minute`, `120/minute` | slowapi syntax |
| `DAILY_TOKEN_BUDGET` | `2000000` | Whole app, per UTC day |
| `LOG_LEVEL` | `INFO` | |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | — | Telemetry on only when set |
| `FRONTEND_DIST` | `../frontend/dist` | Served if it exists |
| LLM keys | see spec 11 | |

Invalid settings stop the app at start-up with one message per problem.

### 3.6 Company configuration (`app/core/config.py`, `config/nig/*.yaml`)

`load_company_config(path) -> CompanyConfig` reads the YAML files below, validates each with a Pydantic model, runs cross-checks, and returns one frozen object. Any error raises `ConfigError` listing **every** problem (file, key, reason); the app does not start.

| File | Model | Content (NIG) | Cross-checks |
|---|---|---|---|
| `organisation.yaml` | `Organisation` | product name "AI Use Case Discovery Agent" (renamed 2026-11-21), company "NorthStar Infrastructure Group", regions (North America, Europe, Middle East, Asia-Pacific), languages (`en`, `de`), report branding (primary and accent colours, optional logo path) | Regions non-empty and unique; colours are hex |
| `taxonomy.yaml` | defined in spec 12 | the 9 clusters | spec 12 |
| `rates.yaml` | `Rates` | default hourly rate 90 (EUR), realisation `conservative: 0.5`, `expected: 0.75`, saving share per opportunity type (8 types) | Shares in [0, 0.9]; all 8 types present |
| `readiness.yaml` | `ReadinessConfig` | per dimension: thresholds and "to prepare" wording; application list (system name, aliases, export/API yes/no) | 6 dimensions present; thresholds ordered |
| `documents.yaml` | `DocumentsConfig` | allowed types, max 5 files, 10 MB each, text budget 60,000 characters | Positive limits |
| `language.yaml` | `LanguageConfig` | per language: yes words, no words, cue words for roles and systems | "ok", "okay", "sure", "fine" are **not** allowed in yes words (rejected at load) |
| `wording.yaml` | `WordingOverrides` | optional label and question overrides by field ID | Every ID exists in the registry (checked when spec 12 lands) |

*The models for taxonomy, readiness detail and wording belong to their specs; this spec owns the loader, the file set and the failure behaviour. Until a spec lands, its model accepts the documented keys and rejects unknown ones.*

### 3.7 Logging and telemetry (`app/core/logging.py`, `app/core/telemetry.py`)

- JSON lines on stdout: `ts`, `level`, `logger`, `msg`, `correlationId`, plus the call's own fields.
- A middleware assigns a correlation id per request (from `X-Correlation-Id` if present, else new) and stores it in a context variable.
- Only loggers under `app.` log at `LOG_LEVEL`; library loggers at `WARNING`.
- **Never log message, document or profile text.** A helper `log_event(logger, name, **fields)` is the only way modules log structured events.
- Telemetry: if the App Insights connection string is set, configure Azure Monitor OpenTelemetry once in the lifespan, excluding `/api/health`; otherwise do nothing.

### 3.8 App factory (`app/main.py`)

`create_app(settings: Settings | None = None) -> FastAPI`:

1. Load settings (if not given) and the company config; fail fast.
2. Configure logging, then telemetry.
3. Lifespan: build the shared objects once and put them on `app.state` (`settings`, `company`, and, from later specs, `store`, `llm`). Nothing is created at import time.
4. Middleware order (outermost first): correlation id → security headers → rate limit (spec 16) → CORS **only** in `local` (Vite on another port).
5. Routers: `meta_routes` (`GET /api/health` → `{"status":"ok","stage":..., "version":...}`); others added by their specs.
6. If `FRONTEND_DIST` exists: serve its files, and return `index.html` for any non-`/api` path (SPA fallback).

Security headers on every response: `Content-Security-Policy` (self; `img-src 'self' data:`; `style-src 'self' 'unsafe-inline'` for Tailwind; no external script sources), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Strict-Transport-Security` when not `local`.

### 3.9 The layer guard (`tests/unit/process_discovery/test_architecture.py`)

Parses every module of `app/services/process_discovery` with `ast` (relative **and** absolute imports) and fails on a forbidden import. Read a row as "a module under X must not import Y":

| Layer | Must not import |
|---|---|
| `llm.py`, `json_schema.py`, `fake_llm.py`, `llm_cache.py` | anything inside the engine except each other |
| `domain` | `profile`, `interview`, `documents`, `artifacts`, `admin`, `export`, `overview`, `service` |
| `profile` | `interview`, `documents`, `artifacts`, `admin`, `export`, `overview`, `service` |
| `interview` | `documents`, `artifacts`, `admin`, `export`, `overview`, `service` |
| `documents`, `artifacts`, `admin`, `export`, `overview` | each other, `interview` (except listed exceptions), `service` |

**Allowed exceptions** (each with a reason in the test): `artifacts` and `documents` may import `interview.prompts.common.render_profile`, so every model call sees the profile rendered the same way.

A second test checks the shell: modules under `app/api/` import from `app.services.process_discovery` only through the package itself (`from app.services.process_discovery import X`), never a deeper path. The tests run on empty packages from day one.

### 3.10 CI (`.github/workflows/ci.yml`)

On every push and pull request: set up Python 3.12 + uv and Node 22; `make setup`; `make lint`; `make test`. Deploy jobs come in spec 25.

## 4. Interfaces

```python
# app/core/settings.py
class Settings(BaseSettings): ...                 # keys of §3.5
def get_settings(request: Request) -> Settings     # FastAPI dependency: app.state.settings

# app/core/config.py
class CompanyConfig(BaseModel):                    # frozen
    organisation: Organisation; taxonomy: Taxonomy; rates: Rates; readiness: ReadinessConfig
    documents: DocumentsConfig; language: LanguageConfig; wording: WordingOverrides
class ConfigError(Exception): problems: list[str]
def load_company_config(path: Path) -> CompanyConfig
def get_company(request: Request) -> CompanyConfig  # dependency

# app/core/logging.py
def configure_logging(level: str) -> None
def log_event(logger: logging.Logger, event: str, **fields: object) -> None
correlation_id: ContextVar[str]

# app/main.py
def create_app(settings: Settings | None = None) -> FastAPI
app = create_app  # factory for `uvicorn app.main:app --factory`
```

## 5. Implications

- **Other workstreams** put their code only in the folders created here and add settings keys and config models through their own specs.
- **Data:** none.
- **Config:** `config/nig/*.yaml` created with the NIG values above; `backend/.env.example` lists every key.
- **Security:** no secrets in the repo; dev workspace codes are refused in `demo`; CSP set from day one.
- **Cost and latency:** none.

## 6. Acceptance criteria

| ID | Given / when / then |
|---|---|
| AC-10.1 | Given a fresh clone, when `make setup && make lint test` runs, then it exits 0 with no Azure variables set |
| AC-10.2 | When `create_app()` is called with default settings, then `GET /api/health` returns 200 `{"status":"ok","stage":"local",...}` |
| AC-10.3 | Importing any module under `app/` creates no client, no settings object and reads no environment variable at import time (checked by importing every module with an empty environment) |
| AC-10.4 | `DEPLOYMENT_STAGE` outside `local`/`test`/`demo` stops start-up with a clear message |
| AC-10.5 | `STORE=cosmos` without `COSMOS_ENDPOINT` stops start-up |
| AC-10.6 | `DEPLOYMENT_STAGE=demo` with default workspace codes or secret stops start-up |
| AC-10.7 | `load_company_config(config/nig)` returns a frozen object with 4 regions, 2 languages, rate 90, realisation 0.5/0.75 and 8 saving shares |
| AC-10.8 | A config with several errors (missing file, bad colour, share 1.2) raises `ConfigError` listing all of them, each with file and key |
| AC-10.9 | A language file whose yes words include "ok" is rejected |
| AC-10.10 | An unknown key in any config file is rejected (no silent typos) |
| AC-10.11 | Every request gets a correlation id; a given `X-Correlation-Id` is reused and appears in the log line |
| AC-10.12 | `log_event` writes one JSON line with the event name and fields; a field named `text`, `message` or `content` is refused (raises in tests) |
| AC-10.13 | Every response carries the security headers of §3.8; HSTS only outside `local` |
| AC-10.14 | With `FRONTEND_DIST` present, `GET /` and `GET /process-discovery/abc` return `index.html`; `GET /api/unknown` returns a JSON 404, not the page |
| AC-10.15 | CORS headers are present only in stage `local` |
| AC-10.16 | The layer test fails when a module in `domain/` imports `profile` (checked with a temporary module in a test fixture) and when `api/` imports a deep engine path |
| AC-10.17 | The layer test passes on the empty scaffold |
| AC-10.18 | `npm run build` produces `frontend/dist`; `npm test` passes the scaffold test (the page renders the health result from a mocked fetch) |
| AC-10.19 | CI runs lint and tests on push and fails on a ruff, pyright, eslint or test error |
| AC-10.20 | Every Python module under `app/` and `tests/` starts with a docstring of at least three sentences (why it exists, what it does, which spec it implements); a test fails on a file without one |
| AC-10.21 | *(amended 2026-11-20 (open workspace))* `WORKSPACE_OPEN` defaults to `false`; `DEPLOYMENT_STAGE=demo` with `WORKSPACE_OPEN=true` and the default codes starts, but with the default or a short token secret it still stops start-up |

## 7. Test plan

| Test file | Covers |
|---|---|
| `tests/unit/core/test_settings.py` | AC-10.4–10.6, 10.21 |
| `tests/unit/core/test_config.py` | AC-10.7–10.10 |
| `tests/unit/core/test_logging.py` | AC-10.11, 10.12 |
| `tests/unit/test_import_side_effects.py` | AC-10.3 |
| `tests/test_smoke.py` | AC-10.2, 10.13–10.15 |
| `tests/unit/process_discovery/test_architecture.py` | AC-10.16, 10.17 |
| `frontend/src/App.test.tsx` | AC-10.18 |
| `tests/unit/test_module_headers.py` | AC-10.20 |
| CI run | AC-10.1, 10.19 |

## 8. Out of scope

Routes other than health (spec 15), access and rate limits (spec 16), the LLM client (spec 11), the registry and taxonomy models (spec 12), the Docker image, Bicep and deploy jobs (spec 25), screens (spec 23).

## 9. Open questions

| # | Question | Default until decided |
|---|---|---|
| Q1 | GitHub repository name and visibility during development | Private until submission, then public |
| Q2 | Daily token budget for the demo | 2,000,000 tokens (about €1–2 a day with a small model) |
