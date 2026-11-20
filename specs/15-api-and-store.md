# 15 · Store and API

> **Status:** part 1 (store) built and verified live on Azure · part 2 (service and interview API) built and verified live
> **Implements:** architecture §5 (database), F-01 (my processes), F-23 (delete my data, retention) · **Depends on:** specs 10, 12 (built)
> **Code:** `backend/app/services/store/` · **Tests:** `backend/tests/unit/store/`, `backend/tests/live/test_cosmos_store.py`
> Part 2 (routes, service use cases, error codes) is added to this file in block 2.

# Part 1 · The store

## 1. Purpose

Keep every session and every idea as **one document**, written whole, with optimistic concurrency, so an interview turn, an upload or an admin edit never silently overwrites another. The engine depends only on a small repository protocol; Cosmos DB backs it in Azure, an in-memory implementation backs tests and local runs, and both behave the same.

## 2. Where it sits

- **Layer:** `app/services/store/`, outside the engine. The engine's `service.py` (block 2) receives a repository by dependency injection; nothing else imports the store.
- **Exists today:** the storage models `Session` and `Idea` (spec 12): camelCase keys, `owner_id` → `ownerId`, `etag` excluded from dumps; settings `STORE`, `COSMOS_ENDPOINT`, `COSMOS_DATABASE`, `COSMOS_CONTAINER` (spec 10).
- **Adds:** the protocol, two implementations, a factory used by the app lifespan, one settings key (`SESSION_RETENTION_DAYS`), and the Cosmos resources in Bicep (§3.7).

## 3. Behaviour

### 3.1 One container, two document types


| Item                 | Value                                                     |
| -------------------- | --------------------------------------------------------- |
| Database / container | `discovery` / `sessions` (settings)                       |
| Partition key        | `/ownerId` (the hashed visitor key, spec 16)              |
| Document types       | `type: "session"` (`Session`) and `type: "idea"` (`Idea`) |
| `id`                 | The model's`id` (uuid4)                                   |
| Writes               | Whole document; never a partial patch                     |

### 3.2 Concurrency

1. Every read returns the model with `etag` set from the stored `_etag`.
2. `replace_session` / `replace_idea` send `If-Match: <etag>`. If the document changed since it was read, raise `ConflictError`; nothing is written. The API maps it to 409 `conflict` (part 2).
3. A replace without an `etag` is a programming error (`ValueError`), never a blind overwrite.
4. Create fails with `ConflictError` if the `id` already exists.

### 3.3 Retention (item TTL)


| Document                                      | `ttl` written by the store                          |
| --------------------------------------------- | --------------------------------------------------- |
| Session with status`active` or `no_candidate` | `SESSION_RETENTION_DAYS × 86400` (default 90 days) |
| Session with status`finished`                 | none (field removed): kept until deleted            |
| Idea with status`open` or `dismissed`         | retention                                           |
| Idea with status`started`                     | none                                                |

The container has `defaultTtl = -1` (TTL on, no default), so only items with `ttl` expire. The model's own `ttl` field is overwritten by this rule on every write.

### 3.4 Loading a stored document

Cosmos adds `_rid`, `_self`, `_etag`, `_attachments`, `_ts`. On load the store removes them all, keeps `_etag` as the model's `etag`, and validates with the strict model (unknown keys are an error, spec 12). A document that fails validation raises `CorruptDocumentError` with the id (never the content) and is logged; it is not silently skipped.

### 3.5 The protocol

```python
class SessionRepository(Protocol):
    async def create_session(self, session: Session) -> Session          # returns it with etag
    async def get_session(self, owner_id: str, session_id: str) -> Session | None
    async def replace_session(self, session: Session) -> Session         # If-Match; returns new etag
    async def delete_session(self, owner_id: str, session_id: str) -> bool
    async def list_sessions(self, owner_id: str) -> list[SessionSummary] # newest first
    async def create_idea(self, idea: Idea) -> Idea
    async def get_idea(self, owner_id: str, idea_id: str) -> Idea | None
    async def replace_idea(self, idea: Idea) -> Idea
    async def delete_idea(self, owner_id: str, idea_id: str) -> bool
    async def list_ideas(self, owner_id: str) -> list[Idea]              # newest first
    async def delete_owner_data(self, owner_id: str) -> DeletedCounts    # sessions + ideas
    async def check(self) -> StoreHealth                                 # reachable, container TTL on
    async def close(self) -> None

class SessionSummary(StorageModel):   # what "My processes" lists; no messages, no profile body
    id: str; status: SessionStatus; phase: Phase; process_name: str | None
    cluster_code: str | None; score: float; message_count: int
    created_at: str; updated_at: str; report_status: str | None

class DeletedCounts(StorageModel): sessions: int; ideas: int
class StoreHealth(StorageModel): ok: bool; ttl_enabled: bool | None; detail: str

class StoreError(Exception)            # base
class ConflictError(StoreError)        # etag mismatch or id exists
class CorruptDocumentError(StoreError) # stored document no longer validates
class StoreUnavailableError(StoreError)# network, auth, throttling after the SDK's own retries
```

Rules for every method:

- **Owner scoping.** Every read, delete and list is scoped to `owner_id` (the partition). A session of another owner is "not found" (`None` / `False`), never an error that reveals it exists. On read the store also checks `ownerId` in the document equals the requested owner (defence in depth).
- **Reads never return another type**: `get_session` on an idea id returns `None`.
- **`list_sessions`** reads only the summary fields with a projection (`ARRAY_LENGTH(c.messages)` for the count; process name and cluster from the profile), so the transcript and profile body never travel. Sorted by `updatedAt` descending.
- **Inputs are not mutated**; returned models are new objects.

Admin (cross-owner) reads (`find_session(session_id)`, filtered lists, counts) are added by spec 21 to this protocol in block 5; nothing here prevents them.

### 3.6 Implementations


|                    | `MemoryRepository`                                                                                       | `CosmosRepository`                                                                                                                                                                                     |
| ------------------ | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Used when          | `STORE=memory` (local, tests)                                                                            | `STORE=cosmos` (demo)                                                                                                                                                                                  |
| Storage            | dict keyed by`(ownerId, id)` holding JSON dumps (so a stored document is serialised exactly like Cosmos) | `azure.cosmos.aio` container client                                                                                                                                                                    |
| `etag`             | a new random string on every write                                                                       | Cosmos`_etag`                                                                                                                                                                                          |
| TTL                | applied as a field; expiry is not simulated                                                              | applied by Cosmos                                                                                                                                                                                      |
| Auth               | —                                                                                                       | `DefaultAzureCredential` (your `az login` locally; the managed identity in Azure, `AZURE_CLIENT_ID`). **No keys**                                                                                      |
| Lifecycle          | —                                                                                                       | Created in the app lifespan by`create_repository(settings)`, closed on shutdown. Never at import time                                                                                                  |
| Container creation | —                                                                                                       | **Never at runtime.** Bicep creates the database and container. `check()` reports a missing container or TTL off; the lifespan logs it as an error (start-up continues so `/api/health` can report it) |

Both implementations run the **same contract test suite** (§7): the memory one always, the Cosmos one against a fake container client in unit tests and against the real account in an opt-in live test.

### 3.7 Azure resources (Bicep, part of spec 25)

Created in block 1 so the store can be tried on Azure:


| Resource          | Setting                                                                                                                                                     |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Cosmos DB account | Serverless,`disableLocalAuth: true`, region `swedencentral`, in `rg-northstar-discovery`                                                                    |
| Database          | `discovery`                                                                                                                                                 |
| Container         | `sessions`, partition key `/ownerId`, `defaultTtl: -1`                                                                                                      |
| Data-plane role   | "Cosmos DB Built-in Data Contributor" for the developer (you, for local runs). The app's managed identity gets it when the container app is added (spec 25) |

You run `azd provision` (after a `--preview`). The endpoint goes into `backend/.env` as `COSMOS_ENDPOINT`.

## 4. Interfaces

- `app/services/store/repository.py`: the protocol, `SessionSummary`, `DeletedCounts`, `StoreHealth`, the errors.
- `app/services/store/memory.py`: `MemoryRepository`.
- `app/services/store/cosmos.py`: `CosmosRepository(container_client, *, retention_days)` plus `async def open_cosmos(settings) -> CosmosRepository`.
- `app/services/store/__init__.py`: `async def create_repository(settings) -> SessionRepository`.
- `app/main.py` lifespan: `app.state.store = await create_repository(settings)`; `await store.close()` on shutdown; `get_store(request)` dependency.
- Settings: `SESSION_RETENTION_DAYS` (default 90, range 1–365).

## 5. Implications

- **Service (block 2):** loads, changes and replaces whole sessions; on `ConflictError` returns 409 and the client reloads. It never touches `_etag` or `ttl` itself.
- **Security and privacy:** no keys; owner scoping on every call; logs carry ids, owner hash prefix (8 characters) and counts, never content; `delete_owner_data` removes every session and idea of an owner (F-23).
- **Cost:** serverless; one read + one replace per turn.

## 6. Acceptance criteria


| ID       | Given / when / then                                                                                                                                                                      |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AC-15.1  | `create_session` then `get_session` returns an equal session (all fields) with a non-empty `etag`                                                                                        |
| AC-15.2  | The stored document uses camelCase keys,`id` = session id, `ownerId` set, `type: "session"`, and no `etag` key                                                                           |
| AC-15.3  | `get_session` with another owner's id returns `None`, even when the session id exists                                                                                                    |
| AC-15.4  | `get_session` with an idea's id returns `None`                                                                                                                                           |
| AC-15.5  | `replace_session` with the current etag succeeds and returns a new, different etag                                                                                                       |
| AC-15.6  | Two replaces from the same read: the first succeeds, the second raises`ConflictError` and the stored document is the first one                                                           |
| AC-15.7  | `replace_session` on a session with `etag=None` raises `ValueError`                                                                                                                      |
| AC-15.8  | `create_session` with an existing id raises `ConflictError`                                                                                                                              |
| AC-15.9  | An`active` or `no_candidate` session is stored with `ttl = retention days × 86400`; a `finished` session is stored without `ttl`                                                        |
| AC-15.10 | An`open` idea has the retention `ttl`; a `started` idea has none                                                                                                                         |
| AC-15.11 | A stored document with Cosmos system fields (`_rid`, `_self`, `_etag`, `_attachments`, `_ts`) loads; `_etag` becomes `etag`; the others are gone                                         |
| AC-15.12 | A stored document with an unknown key raises`CorruptDocumentError` naming the id, not the content                                                                                        |
| AC-15.13 | `list_sessions` returns only the owner's sessions (no ideas), newest `updatedAt` first, with process name, cluster code, score, message count and report status                          |
| AC-15.14 | The Cosmos`list_sessions` query projects summary fields only: it does not select `c.messages` or `c.profile` whole (checked on the query text)                                           |
| AC-15.15 | `delete_session` returns `True` once, then `False`; another owner's session is not deleted                                                                                               |
| AC-15.16 | Ideas: create, get, replace (with etag), delete and list behave like sessions (AC-15.1, 15.3, 15.5, 15.6, 15.15)                                                                         |
| AC-15.17 | `delete_owner_data` deletes every session and idea of that owner and none of another owner, and returns the counts                                                                       |
| AC-15.18 | Inputs are not mutated by any method; returned models are new objects                                                                                                                    |
| AC-15.19 | Cosmos errors map: not found →`None`/`False`; precondition failed → `ConflictError`; conflict on create → `ConflictError`; other HTTP or connection errors → `StoreUnavailableError` |
| AC-15.20 | `create_repository` returns `MemoryRepository` for `STORE=memory` and a `CosmosRepository` for `STORE=cosmos`, built with `DefaultAzureCredential` and no key                            |
| AC-15.21 | Importing the store creates no client (import side-effect test)                                                                                                                          |
| AC-15.22 | The app lifespan opens the store once, puts it on`app.state.store`, and closes it on shutdown; `get_store` returns it                                                                    |
| AC-15.23 | `check()` reports `ok` and `ttl_enabled`; with a missing container the lifespan logs an error and `/api/health` still answers                                                            |
| AC-15.24 | Log lines from the store carry the event, the session or idea id, an 8-character owner prefix and counts; never message, profile or document text                                        |
| AC-15.25 | The same contract suite (AC-15.1–15.19) passes for`MemoryRepository` and for `CosmosRepository` on the fake container client                                                            |
| AC-15.26 | Live (opt-in`RUN_LIVE=1`, `COSMOS_ENDPOINT` set): create → get → replace → conflict → list → delete against the real container, with `az login` and no key                          |

## 7. Test plan


| Test file                          | Covers                                                                                                                          |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `tests/unit/store/contract.py`     | The shared contract (parametrised over both implementations)                                                                    |
| `tests/unit/store/test_memory.py`  | Runs the contract on`MemoryRepository`; AC-15.9–15.10                                                                          |
| `tests/unit/store/fake_cosmos.py`  | A fake`azure.cosmos.aio` container: read/create/replace (etag, If-Match)/delete/query, system fields, the SDK's exception types |
| `tests/unit/store/test_cosmos.py`  | Runs the contract on`CosmosRepository` + fake; AC-15.11, 15.12, 15.14, 15.19, 15.24                                             |
| `tests/unit/store/test_factory.py` | AC-15.20–15.23                                                                                                                 |
| `tests/live/test_cosmos_store.py`  | AC-15.26                                                                                                                        |

## 8. Out of scope

Routes and service use cases (part 2, block 2); admin cross-owner queries (spec 21, block 5); the container app and its identity (spec 25); backups (production readiness).

## 9. Open questions


| #  | Question                                                   | Default                                      |
| -- | ---------------------------------------------------------- | -------------------------------------------- |
| Q1 | Should`no_candidate` sessions expire like unfinished ones? | Yes (retention): there is no process to keep |
| Q2 | Retention length                                           | 90 days, setting                             |

---

# Part 2 · The service and the interview API

## 1. Purpose

Expose the interview side over HTTP: a user creates a session, talks to the agent turn by turn, confirms roles and systems, picks a cluster, finishes or closes, keeps ideas, and deletes their data. Each route is a thin layer over one service use case; the service loads the session, runs the engine, and saves the whole document once.

## 2. Where it sits

- **Service:** `app/services/process_discovery/service.py`, the composition root of the engine (same role and shape as the earlier design's `service.py`): builds the interview state from a session, runs the graph, writes the session back. Exported by the facade (`process_discovery/__init__.py`, loaded lazily, spec 12 AC-12.44).
- **Routes:** `app/api/process_discovery_routes.py` (expert) and `app/api/meta_routes.py` (health, config, taxonomy). They import only the facade, the wire models and the access dependencies (spec 16).
- **Uses:** the store (part 1), `interview.turn` (`welcome`, `run_turn`, `after_action`, spec 14), `profile` (`set_cluster`, `confirm_rollup`, `finish_check`, `field_views`, spec 13), the LLM client (spec 11), access (spec 16).
- **Later blocks add:** documents and proposals routes (block 4, spec 17), the assessment on *Finish* and the report routes (block 4, specs 18–20), admin routes (block 5, spec 21).

## 3. Behaviour

### 3.1 The pattern of every write

1. Resolve the caller (`owner_id`, spec 16). 2. Load the session with `get_session(owner_id, id)`; missing → 404 `not_found`. 3. Refuse if the session is not `active` (400 `session_closed`), except `GET` and `DELETE`. 4. Run the use case on a **new** session object (inputs are never mutated). 5. Set `updated_at = now` (the service owns time). 6. `replace_session` once, with the etag from step 2; `ConflictError` → 409 `conflict`, nothing else is retried. 7. Return the session view.

### 3.2 Use cases (`DiscoveryService`)


| Method                                                                  | Model calls     | What it does                                                                                                                                                                                                                                                               |
| ----------------------------------------------------------------------- | --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `create_session(owner, display_name, from_idea_id=None)`                | none            | New`Session`; first agent message and `last_question` from `welcome()`; from an idea: the idea's name becomes a proposed P04 (`propose_from_idea`) and the idea is marked `started`                                                                                        |
| `list_sessions(owner)`                                                  | none            | Store summaries, newest first                                                                                                                                                                                                                                              |
| `get_session(owner, id)`                                                | none            | The session view                                                                                                                                                                                                                                                           |
| `delete_session(owner, id)`                                             | none            | Hard delete; 404 if not found                                                                                                                                                                                                                                              |
| `process_turn(owner, id, text)`                                         | 2–3            | Screen`text` with `contains_injection_pattern` → 400 `unsafe_input` (nothing stored, a security log line without text). Append the expert message; `run_turn(...)`; append the agent reply; store new ideas (`TurnResult.ideas`, de-duplicated by name per session); save |
| `confirm(owner, id, target)`                                            | none            | `target` ∈ `substeps`, `roles`, `tools`: `confirm_rollup`, then `after_action`                                                                                                                                                                                            |
| `set_cluster(owner, id, code)`                                          | none            | `profile.set_cluster(decided_by="picker")`, then `after_action`; unknown code → 422 `unknown_cluster`                                                                                                                                                                     |
| `close_without_candidate(owner, id)`                                    | none            | `status = no_candidate`, phase `no_candidate`, `finished_at = now`. Never done by the agent                                                                                                                                                                                |
| `finish(owner, id)`                                                     | none in block 2 | `finish_check`; not ready → 409 `map_incomplete` with `reason` = `blocked_by` (not an error for the client). Ready → `status = finished`, phase `finished`, `finished_at`, `report.status = mapped`. **Block 4** adds the assessment (three calls in parallel) here      |
| `list_ideas(owner)`, `dismiss_idea(owner, id)`, `start_idea(owner, id)` | none            | Ideas of the caller; start =`create_session(from_idea_id=id)`                                                                                                                                                                                                              |
| `delete_owner_data(owner)`                                              | none            | Every session and idea of the caller (F-23)                                                                                                                                                                                                                                |

**Model failures** never break a turn: `run_turn` already falls back to a code-built question (spec 14). Only `LLMBudgetExceededError` (daily budget, spec 16) becomes 429 `budget_exhausted`; `LLMConfigError` (no endpoint configured) becomes 503 `model_unavailable`.

### 3.3 Routes (prefix `/api`, camelCase JSON)


| #  | Method + path                  | Body                                          | Response                                                                            | Errors                                                                   |
| -- | ------------------------------ | --------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| 1  | `POST /sessions`               | `{displayName?: str ≤ 40, fromIdeaId?: str}` | 201`SessionOut`                                                                     | 404 idea                                                                 |
| 2  | `GET /sessions`                | —                                            | `{sessions: SessionSummaryOut[]}`                                                   | —                                                                       |
| 3  | `GET /sessions/{id}`           | —                                            | `SessionOut`                                                                        | 404                                                                      |
| 4  | `DELETE /sessions/{id}`        | —                                            | 204                                                                                 | 404                                                                      |
| 5  | `POST /sessions/{id}/messages` | `{text: 1..16000 chars}`                      | `TurnOut`                                                                           | 400`session_closed` / `unsafe_input`, 404, 409 `conflict`, 422, 429, 503 |
| 6  | `POST /sessions/{id}/confirm`  | `{target: "substeps" | "roles" | "tools"}`    | `SessionOut`                                                                        | 400, 404, 409, 422                                                       |
| 7  | `PUT /sessions/{id}/cluster`   | `{code: str ≤ 8}`                            | `SessionOut`                                                                        | 400, 404, 409, 422`unknown_cluster`                                      |
| 8  | `POST /sessions/{id}/close`    | —                                            | `SessionOut`                                                                        | 400, 404, 409                                                            |
| 9  | `POST /sessions/{id}/finish`   | —                                            | `SessionOut`                                                                        | 400, 404, 409`map_incomplete` (+`reason`) / `conflict`                   |
| 10 | `GET /ideas`                   | —                                            | `{ideas: IdeaOut[]}`                                                                | —                                                                       |
| 11 | `DELETE /ideas/{id}`           | —                                            | 204                                                                                 | 404                                                                      |
| 12 | `POST /ideas/{id}/start`       | —                                            | 201`SessionOut`                                                                     | 404, 409 already started                                                 |
| 13 | `DELETE /me`                   | —                                            | `{sessions: int, ideas: int}`                                                       | —                                                                       |
| 14 | `GET /taxonomy`                | —                                            | `TaxonomyOut` (spec 12)                                                             | —                                                                       |
| 15 | `GET /config`                  | —                                            | `{productName, regions, languages, documents: {allowedTypes, maxFiles, maxFileMb}}` | —                                                                       |
| 16 | `GET /health`                  | —                                            | `{status, stage, version, store: {ok, ttlEnabled}}`                                 | —                                                                       |

Routes 1–13 need a visitor key (spec 16); 14–16 are public. Every error body is `{"code", "message"}`; 409 `map_incomplete` adds `"reason"`.

### 3.4 Wire models (`app/models/process_discovery_wire.py`)


| Model               | Fields                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SessionOut`        | `id, status, phase, displayName, createdAt, updatedAt, finishedAt, messages: [{id, role, text, at}], profile` (registry keys, no `__meta`/`__skipped` internals), `fieldViews: FieldView[]` (spec 13 `field_views`), `score: {value, filledPoints, totalPoints}`, `finish: FinishState`, `scope: {verdict, widened} | null`, `clusterProposal: {code, name, description} | null` (only while the agent is asking about it), `reportStatus: "mapped" | "validated" | null`, `documents: DocumentOut[]` (spec 17 routes; counts and pending, never the text) |
| `TurnOut`           | `reply: {id, role, text, at}` + `session: SessionOut` + `ideasAdded: int`                                                                                                                                                                                                                                                                                                                                                                                                 |
| `SessionSummaryOut` | the store's`SessionSummary` (part 1)                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `IdeaOut`           | `id, name, words, status, fromSessionId, startedSessionId, createdAt`                                                                                                                                                                                                                                                                                                                                                                                                     |

The client replaces its state with `SessionOut` on every response (no partial merges needed); `TurnOut.reply` is also the last message.

### 3.5 Logs and audit

One `turn` line per message (from spec 14) plus the service line: route, session id, owner prefix (8 characters), outcome (`ok`, `conflict`, `unsafe_input`, `budget`), duration. Never the text.

## 4. Interfaces

```python
# process_discovery/service.py
class DiscoveryService:
    def __init__(self, repo: SessionRepository, llm: LLM, ctx: InterviewContext, graph, *, clock: Callable[[], str]): ...
    async def create_session(self, owner: str, *, display_name: str | None = None, from_idea_id: str | None = None) -> Session
    async def process_turn(self, owner: str, session_id: str, text: str) -> TurnResult
    ...  # the methods of §3.2
class SessionNotFound(Exception); class SessionClosed(Exception); class UnsafeInput(Exception)
class MapIncomplete(Exception): reason: str
class UnknownCluster(Exception); class IdeaAlreadyStarted(Exception)

# app/api/process_discovery_routes.py
router = APIRouter(prefix="/api", tags=["process-discovery"])
def get_service(request) -> DiscoveryService      # built once in the lifespan
```

The lifespan builds, once: settings → company config → store → LLM (`create_llm`, with spec 16's budget guard and usage hook) → `InterviewContext` → graph → `DiscoveryService`. Tests override `get_service` with one built on `MemoryRepository` and `FakeLLM`.

## 5. Implications

- **Frontend (spec 23):** the calls and shapes above are the contract; spec 23's assumed calls are reconciled to these.
- **Data:** nothing new on the session.
- **Security:** owner scoping on every route; text screened before the model; errors never echo the expert's text.

## 6. Acceptance criteria (part 2)


| ID       | Given / when / then                                                                                                                                              |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AC-15.27 | `POST /sessions` returns 201 with status `active`, phase `context`, one agent message (the welcome), score 0, Finish blocked `below_gate`; no model call is made |
| AC-15.28 | `POST /sessions` with `fromIdeaId` proposes the idea's name for P04 and marks the idea `started`                                                                 |
| AC-15.29 | `GET /sessions` lists only the caller's sessions, newest first, summary fields only                                                                              |
| AC-15.30 | `GET`/`DELETE /sessions/{id}` of another visitor's session returns 404                                                                                           |
| AC-15.31 | `POST /messages` appends the expert message and the agent reply, saves once, and returns `TurnOut` with the new phase, field views and Finish state              |
| AC-15.32 | A message matching the injection screen returns 400`unsafe_input`; the session is unchanged and the model was not called                                         |
| AC-15.33 | A message to a`finished` or `no_candidate` session returns 400 `session_closed`                                                                                  |
| AC-15.34 | A message longer than 16,000 characters, or empty, returns 422                                                                                                   |
| AC-15.35 | Two concurrent writes from the same read: one succeeds, the other returns 409`conflict` and nothing of it is stored                                              |
| AC-15.36 | A turn whose model calls fail still returns 200 with the code-built fallback question (spec 14)                                                                  |
| AC-15.37 | A daily budget refusal returns 429`budget_exhausted`; no endpoint configured returns 503 `model_unavailable`                                                     |
| AC-15.38 | Ideas returned by a turn are stored once per name per session;`GET /ideas` lists them                                                                            |
| AC-15.39 | `POST /confirm` with `roles` sets `roles_confirmed`, recomputes the phase (`after_action`) and returns the session; an unknown target is 422                     |
| AC-15.40 | `PUT /cluster` with a known code sets the cluster `decided_by: picker` and moves the phase; an unknown code is 422 `unknown_cluster`                             |
| AC-15.41 | `POST /close` sets `no_candidate`, `finished_at`, and later messages get `session_closed`                                                                        |
| AC-15.42 | `POST /finish` on an incomplete map returns 409 `map_incomplete` with `reason` equal to the first blocker; nothing is stored                                     |
| AC-15.43 | `POST /finish` on a complete map sets `finished`, `finished_at`, `reportStatus: mapped`; the stored session has no `ttl` (part 1)                                |
| AC-15.44 | `DELETE /ideas/{id}` and `POST /ideas/{id}/start` behave as in §3.3; starting twice is 409                                                                      |
| AC-15.45 | `DELETE /me` removes every session and idea of the caller and none of another visitor                                                                            |
| AC-15.46 | `GET /taxonomy` returns the nine clusters in order; `GET /config` returns the product name, regions, languages and upload limits; neither needs a visitor key    |
| AC-15.47 | `GET /health` includes the store check                                                                                                                           |
| AC-15.48 | Every response is camelCase;`SessionOut.profile` never contains `__meta` or `__skipped`; no response contains `lastQuestion` or counters                         |
| AC-15.49 | Every error body is`{code, message}`; no error message contains the expert's text                                                                                |
| AC-15.50 | Routes import only the engine facade (layer test)                                                                                                                |
| AC-15.51 | A scripted interview through the API with`FakeLLM` (12+ turns) reaches `review`, confirms roles and tools, finishes, and is listed as finished                   |
| AC-15.52 | Live (opt-in, after the prompt review): one short interview through the API against Azure OpenAI and Cosmos reaches Finish                                       |

## 7. Test plan (part 2)


| Test file                                      | Covers                                          |
| ---------------------------------------------- | ----------------------------------------------- |
| `tests/unit/process_discovery/test_service.py` | §3.1, §3.2 with`MemoryRepository` + `FakeLLM` |
| `tests/api/test_sessions_routes.py`            | AC-15.27–15.37, 15.48–15.50                   |
| `tests/api/test_actions_routes.py`             | AC-15.39–15.43                                 |
| `tests/api/test_ideas_and_data_routes.py`      | AC-15.38, 15.44, 15.45                          |
| `tests/api/test_meta_routes.py`                | AC-15.46, 15.47                                 |
| `tests/api/test_interview_flow.py`             | AC-15.51                                        |
| `tests/live/test_api_interview.py`             | AC-15.52                                        |
