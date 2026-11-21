# Backend

The API and the interview engine. Python 3.12, FastAPI, Pydantic v2.

## Layout

| Path | What it does |
|---|---|
| `app/api/` | HTTP routes: sessions, messages, documents, *Finish*, report, workspace |
| `app/core/` | Settings, company configuration loading, access, rate limits |
| `app/models/` | Pydantic models for storage and for the wire (camelCase JSON) |
| `app/services/store/` | Session storage: Cosmos DB, or in memory for tests and local runs |
| `app/services/process_discovery/` | **The engine** (below) |

The engine is layered; imports only point down, and a test enforces it:

| Layer | Role |
|---|---|
| `llm.py` | The only way to call a model: timeouts, retries, strict JSON schemas, budgets |
| `domain/` | The field registry (every field defined once), parsing of hours and frequencies, scope rules. Pure: no I/O, no clock |
| `profile/` | Writing answers into the form, scoring, what counts as complete |
| `interview/` | One turn: read the answer, decide the next question, phrase it |
| `documents/` | Read uploaded files and propose values (with quotes) for the expert to confirm |
| `artifacts/` | The assessment at *Finish*: process map, step ratings, hours, readiness, the report |
| `export/` · `admin/` · `overview/` | PDF report, specialist workspace, overview |
| `service.py` | Ties it together for the routes |

## Run and test

```bash
uv sync
cp .env.example .env     # set AZURE_OPENAI_ENDPOINT; sign in with `az login` (managed identity in Azure)
DEPLOYMENT_STAGE=local uv run uvicorn app.main:app --factory --reload --port 8000
uv run pytest -q         # unit and API tests, no model calls (a fake model is scripted)
```

`STORE=memory` (the default) keeps sessions in memory; `STORE=cosmos` with `COSMOS_ENDPOINT` uses Cosmos DB.
