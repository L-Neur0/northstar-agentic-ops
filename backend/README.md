# Backend

This folder is part of the [AI Use Case Discovery Agent](../README.md), and it holds the API and the interview engine. It is written in Python 3.12 with FastAPI and Pydantic v2.

## Layout

| Path | What it does |
|---|---|
| `app/api/` | The HTTP routes for sessions, messages, documents, *Finish*, the report and the workspace |
| `app/core/` | Settings, loading the company configuration, access, and rate limits |
| `app/models/` | The Pydantic models, both for storage and for the JSON sent to the browser (camelCase) |
| `app/services/store/` | Session storage, either in Cosmos DB or in memory for tests and local runs |
| `app/services/process_discovery/` | **The engine**, described below |
| `scripts/` | `chat.py` runs the interview in the terminal (`make chat`); `export_api_samples.py` writes the API samples that the frontend tests use |

The engine is split into layers. Imports only point downwards, and a test checks that this stays true.

| Layer | Role |
|---|---|
| `llm.py` | The only way to call a model. It handles timeouts, retries, strict JSON schemas and budgets |
| `domain/` | The field registry, where every field is defined once, plus the parsing of hours and frequencies and the scope rules. It is pure: no I/O and no clock |
| `profile/` | Writes answers into the form, scores it, and decides what counts as complete |
| `interview/` | Runs one turn: it reads the answer, decides the next question and phrases it |
| `documents/` | Reads uploaded files and proposes values, each with a quote, which the employee then confirms |
| `artifacts/` | Builds the assessment when the employee presses *Finish*: the process map, the step ratings, the hours, the readiness and the report |
| `export/` · `admin/` | The PDF report and the specialists' workspace. `overview/` is an empty placeholder for a later overview across processes |
| `service.py` | Ties the layers together for the routes |

## Run and test

```bash
uv sync
cp .env.example .env     # set AZURE_OPENAI_ENDPOINT, then sign in with `az login` (Azure uses a managed identity)
DEPLOYMENT_STAGE=local uv run uvicorn app.main:app --factory --reload --port 8000
uv run pytest -q         # unit and API tests; they use a scripted fake model, so no real model is called
```

By default `STORE=memory`, which keeps sessions in memory. If you set `STORE=cosmos` together with `COSMOS_ENDPOINT`, sessions are stored in Cosmos DB.

The tests in `tests/live/` call the real Azure services, so they are skipped unless you set `RUN_LIVE=1`.
