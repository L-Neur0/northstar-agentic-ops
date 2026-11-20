# 21 · Admin: the workspace backend (session list, read-only session view, conversation, PDF, delete)

> **Status:** amended 2026-11-20 (open workspace: `WORKSPACE_OPEN`, product owner decision) · built 2026-11-20 (approved 2026-11-20: log only conversation, download, delete; first name shown; ideas kept on delete; step-grid cells sent as display text by the server; deviations in §10) · **Implements:** F-17.1, F-17.6, F-17.7 (read-only part), F-21.3, F-23.5 (product); §3.4 workspace routes, §3.5 workspace token, §3.7 audit log, §5 workspace reads (architecture) · **Depends on:** specs 12 (models), 13 (field views), 15 (store, errors, etag), 16 (workspace login and token, built), 20 (report model and PDF, built)
> **Code:** `backend/app/services/process_discovery/admin/{listing,view}.py`; use cases in `service.py`; routes in `backend/app/api/workspace_routes.py`; wire models in `backend/app/models/workspace_wire.py`; store methods in `backend/app/services/store/`
> **Tests:** `backend/tests/unit/process_discovery/admin/`, `backend/tests/unit/store/test_workspace_queries.py`, `backend/tests/api/test_workspace_routes.py`

## 1. Purpose

The workspace lets an IT and transformation specialist see every discovery session: a list with simple filters, a **read-only** view of one session (summary, the step grid now and as the expert first told it, the assessment, the map), the full conversation, the report as PDF, and delete. Nothing is edited here. Edits, validation, the overview and briefs come later (§8).

## 2. Where it sits

- **Layer:** `admin` is an engine peer (architecture §3). It imports `domain`, `profile` and the models, never `artifacts`, `documents`, `export` or `overview`. `service.py` builds the report (spec 20) and passes it in; routes import only the façade.
- **Exists today:** workspace login, token and `require_role("specialist")` (spec 16, built); `field_views` (spec 13); `build_report` and `report_pdf` (spec 20, built); `raw_substeps` on the session (spec 12); the `app.audit` logger and `log_event` (spec 10).
- **What it changes:**

| Where | Change |
|---|---|
| `SessionRepository` (spec 15) | Adds `find_session(session_id)` and `scan_sessions(limit)` (§4.3) |
| Error handlers (spec 15) | Adds 428 `etag_required` |
| `workspace_routes.py` | Adds the routes of §4.1 next to the login |

No change to the storage models.

## 3. Behaviour

### 3.1 Common rules

1. **Role.** Every route needs `Authorization: Bearer <token>` with role `specialist` (spec 16). No or bad token → 401 `workspace_code_required`; an engineer token → 403 `forbidden`. The engineer role stays as built in spec 16 but no admin route uses it (briefs are out of scope).
2. **Read-only**, except delete. No route here changes the profile, the assessment or the report state, and none calls the model.
3. **Never shown** in any workspace response:

   | Item | Rule |
   |---|---|
   | Uploaded files' text | Only the name, kind, size, upload time and outcome. `documents[].text` never leaves the store layer |
   | `ownerId`, visitor key | Never |
   | Messages | Only from the conversation route (§3.4); never in the list or the session view |
   | Expert's first name | Not in the list or the session view; the conversation is shown as stored |

4. **Errors:** `{code, message}` as in spec 15. Unknown session → 404 `not_found`.

### 3.2 Session list (`GET /api/review/sessions`)

1. **All sessions**, every status (`active`, `finished`, `no_candidate`), newest `updatedAt` first. The store returns at most the 1,000 newest; beyond that `truncated: true`.
2. **One row per session:**

   | Column | Source |
   |---|---|
   | `createdAt`, `updatedAt` | Session |
   | `processName` | P04 (empty → `null`) |
   | `department` | P01 |
   | `clusterCode`, `clusterName` | P05 |
   | `region` | P03 |
   | `status`, `phase` | Session |
   | `fieldsFilled`, `fieldsTotal` | From `field_views` (spec 13): views with status `complete` / all views |
   | `steps` | Number of rows in `process.substeps` |
   | `messageCount` | `len(messages)` |
   | `documentCount` | `len(documents)` |

3. **Filters** (server-side, optional, combined with AND): `status` (one of the three), `cluster` (P05 code), `q` (1–100 characters, case-insensitive substring of process name, department or session id). Anything else invalid → 422 `invalid_value`.
4. **Sort:** always `updatedAt`, newest first. Ties by id.
5. **Counts** (from the same scan, before filters): `{total, active, finished, noCandidate}`. `matching` = rows after filters. With no sessions all counts are 0.
6. No paging: the filtered rows are returned in full (at most 1,000).

### 3.3 Session view (`GET /api/review/sessions/{id}`)

A read-only body for the popup, for any status:

| Part | Content |
|---|---|
| **Summary cards** | *Context:* department, function (P02), region. *Process:* name, cluster, status, phase. *Scope:* fields filled `n / total`, steps with content `n / expected`. *Measures:* completeness (score value as %), points `filledPoints / totalPoints`, message count, document count |
| **Step grid (current)** | One column per step, one row per step field (S01–S12): label, and per cell its **display text** (built by the server with the report's cell rules, spec 20 §3.3: lists joined, "—" when empty, "— (skipped)", "(proposed, not confirmed)"; the screen never formats a value), its source (`expert`, `document`, `specialist`) and status from the field views |
| **Step grid (as first told)** | Same shape built from `raw_substeps` (display text too; `source` and `status` are `null`, since the snapshot holds only the expert's words); `rawSteps: null` when nothing froze them (the screen then disables the toggle) |
| **Documents** | Name, kind, bytes, upload time, outcome. Never text |
| **Assessment and map** | For a finished session: `report` = the `DiscoveryReport` from `build_report` (spec 20), which holds the map part, the step-by-step AI assessment, the recommended route and the opportunities. `null` before *Finish* |
| **etag** | The session etag, also in the `ETag` header (needed for delete) |

### 3.4 Conversation (`GET /api/review/sessions/{id}/conversation`)

1. Returns `{sessionId, messages[{id, role, text, at}]}` in stored order, for any status. The expert is told in the welcome message that the team may read it (product rule 7).
2. Each call writes one audit line `view_conversation` (§3.7).

### 3.5 Report PDF (`GET /api/review/sessions/{id}/report.pdf`)

1. The same PDF as the expert's route (spec 20, `report_pdf`), with the workspace token instead of the visitor key. Same file name. No model call.
2. Not finished → 409 `report_not_ready`.
3. Each call writes one audit line `download_report`.

### 3.6 Delete (`DELETE /api/review/sessions/{id}`)

1. Needs `If-Match` with the session etag. Missing → 428 `etag_required`; stale → 409 `conflict`; nothing deleted.
2. Hard-deletes the session document. The expert's ideas stay (they belong to the expert).
3. Returns 204 and writes one audit line `delete_session`.
4. *(Amended 2026-11-20 (open workspace).)* When the workspace is open (`WORKSPACE_OPEN=true`, spec 16 §3.2 item 5), delete is switched off: the route returns 403 `forbidden` with "Deleting is switched off on this open demo." before any store call (no read, no etag check, nothing deleted) and writes the `delete_session` audit line with outcome `refused`. The check is in the route, because it is an access rule of the shell, like the role check.

### 3.7 Audit log

One `workspace_action` line on the `app.audit` logger (the server log, exported to App Insights) for `view_conversation`, `download_report` and `delete_session`, with `role`, `user_name` (the name typed at login), `action`, `session_id`, `outcome` (`ok` or the error code). The log record carries the time. Never a message, a document text or a profile value. Nothing is stored in the database.

### 3.8 Worked example

Two sessions. `s1`: finished, "Monthly supplier invoice check", department "Finance", cluster FIN, region Europe, 4 steps, 52 messages, 1 document. `s2`: active, no process name yet, 6 messages.

1. `GET /api/review/sessions` → counts `{total: 2, active: 1, finished: 1, noCandidate: 0}`, `matching: 2`; `s1` row: `fieldsFilled 52, fieldsTotal 64 (16 process fields + 4 × 12 step cells), steps 4, messageCount 52, documentCount 1`.
2. `GET /api/review/sessions?status=finished&q=invoice` → only `s1`.
3. `GET /api/review/sessions/s1` → summary cards, the current grid, the raw grid (the expert confirmed a document proposal, so the steps were frozen), the document name "invoice-procedure.pdf" without text, and the report with its map.
4. `GET .../s1/conversation` as "Maria (IT)" → 52 messages; the log gets `workspace_action action=view_conversation user_name="Maria (IT)" session_id=s1 outcome=ok`.
5. `GET .../s2/report.pdf` → 409 `report_not_ready`, logged with `outcome=report_not_ready`.
6. `DELETE .../s1` with `If-Match: "e7"` → 204; `GET .../s1` → 404; the expert's ideas from `s1` are still listed for the expert.

## 4. Interfaces

### 4.1 Routes (`app/api/workspace_routes.py`, role `specialist`)

| Method and path | Response |
|---|---|
| `POST /api/workspace/login` | As built (spec 16) |
| `GET /api/review/sessions?status&cluster&q` | `ReviewListOut` |
| `GET /api/review/sessions/{id}` | `ReviewSessionOut` + `ETag` |
| `GET /api/review/sessions/{id}/conversation` | `ConversationOut` |
| `GET /api/review/sessions/{id}/report.pdf` | `application/pdf` attachment |
| `DELETE /api/review/sessions/{id}` (`If-Match`) | 204 |

### 4.2 Wire models (`app/models/workspace_wire.py`, camelCase via `WireModel`)

```python
class ReviewRowOut(WireModel):
    id: str; created_at: str; updated_at: str; process_name: str | None; department: str | None
    cluster_code: str | None; cluster_name: str | None; region: str | None
    status: SessionStatus; phase: Phase; fields_filled: int; fields_total: int
    steps: int; message_count: int; document_count: int
class ReviewCountsOut(WireModel): total: int; active: int; finished: int; no_candidate: int
class ReviewListOut(WireModel):
    counts: ReviewCountsOut; rows: list[ReviewRowOut]; matching: int; truncated: bool

class SummaryOut(WireModel):
    department: str | None; function: str | None; region: str | None
    process_name: str | None; cluster_name: str | None; status: SessionStatus; phase: Phase
    fields_filled: int; fields_total: int; steps_started: int; steps_expected: int
    completeness: float; filled_points: int; total_points: int; message_count: int; document_count: int
class GridCellOut(WireModel): value: str; source: str | None; status: str | None   # value = display text built by the server
class GridRowOut(WireModel): key: str; id: str; label: str; cells: list[GridCellOut]   # one cell per step
class StepGridOut(WireModel): step_names: list[str]; rows: list[GridRowOut]
class DocumentMetaOut(WireModel): name: str; kind: str; bytes: int; uploaded_at: str; outcome: str
class ReviewSessionOut(WireModel):
    id: str; etag: str; summary: SummaryOut; steps: StepGridOut; raw_steps: StepGridOut | None
    documents: list[DocumentMetaOut]; report: DiscoveryReport | None

class ConversationOut(WireModel): session_id: str; messages: list[MessageOut]
```

### 4.3 Store additions (`SessionRepository`, memory and Cosmos)

```python
async def find_session(self, session_id: str) -> Session | None            # cross-partition, with etag
async def scan_sessions(self, limit: int = 1000) -> tuple[list[Session], bool]
    # newest updatedAt first; documents[].text blanked; truncated flag. Read-only results.
```

Delete uses `delete_session(owner_id, session_id, etag)` (conditional, see §10 D4) with the owner and etag from `find_session`, after the `If-Match` check.

### 4.4 Engine (`admin/`, pure: no I/O, no clock)

```python
def review_rows(sessions, *, status, cluster, q, vocab) -> tuple[list[ReviewRow], Counts, int]
def session_view(session, report, *, vocab) -> ReviewSessionView   # report built by the service
def step_grid(steps, field_views) -> StepGrid
```

Service use cases: `review_list`, `review_session`, `review_conversation`, `review_report_pdf`, `review_delete`, each taking the `WorkspaceUser`.

## 5. Implications

- **Other components:** spec 23 part 3 builds the workspace page on these routes: count tiles, filters, session table, the read-only popup (summary cards, grid with a current / as-first-told toggle, assessment, map), the conversation view, PDF download and delete. **Dark and light theme** is a frontend concern there.
- **Data:** none added.
- **Config:** none.
- **Security and privacy:** the specialist role is checked on every route; the conversation is reachable only from its own route and every opening is logged; document text never leaves the store; delete needs the etag. The typed name is not an identity (named sign-in is a production item).
- **Cost and latency:** no model call. The list scans at most 1,000 sessions in memory (enough for the prototype).

## 6. Acceptance criteria

| ID | Given / when / then |
|---|---|
| AC-21.1 | Given no token or a bad token, every route of §4.1 (except login) returns 401 `workspace_code_required`; an engineer token returns 403 `forbidden` |
| AC-21.2 | The list returns every session of every status, newest `updatedAt` first, one row with the columns of §3.2 |
| AC-21.3 | `fieldsFilled` / `fieldsTotal` equal the complete field views / all field views of that session; `steps`, `messageCount`, `documentCount` equal the stored counts |
| AC-21.4 | `status`, `cluster` and `q` (case-insensitive, on process name, department or id) filter on the server and combine with AND; `matching` is the filtered count |
| AC-21.5 | An unknown `status`, or `q` longer than 100 characters, returns 422 `invalid_value` |
| AC-21.6 | `counts` are taken before filters and are all 0 with no sessions |
| AC-21.7 | With more than 1,000 sessions the list returns the 1,000 newest and `truncated: true` |
| AC-21.8 | The session view of a finished session has the four summary cards, the current step grid with source and status per cell, the document metadata and the `DiscoveryReport` including the map part |
| AC-21.9 | The session view of an active session works, with `report: null` |
| AC-21.10 | `rawSteps` is built from `raw_substeps` when they were frozen and differs from the current grid after a later change; it is `null` when nothing froze them |
| AC-21.11 | No response of the list or the session view contains a message text, `documents[].text`, `ownerId` or `displayName` (checked with marker strings) |
| AC-21.12 | The conversation route returns every stored message in order with role, text and time, for any status |
| AC-21.13 | The PDF route returns `application/pdf` with the same bytes and file name as the expert's PDF route for the same session |
| AC-21.14 | The PDF route on a session that is not finished returns 409 `report_not_ready` |
| AC-21.15 | Delete with the current etag returns 204; the session is then 404 for the workspace and the expert; the expert's ideas from it remain |
| AC-21.16 | Delete without `If-Match` returns 428 `etag_required`, with a stale etag 409 `conflict`; in both cases the session still exists |
| AC-21.17 | Viewing the conversation, downloading the PDF and deleting each write exactly one `workspace_action` audit line with role, typed name, action, session id and outcome, also when refused; the line holds no message, document or profile text |
| AC-21.18 | No route here changes a stored session (except delete) or calls the model (FakeLLM records no call) |
| AC-21.19 | Every wire model serialises camelCase keys only |
| AC-21.20 | `find_session` and `scan_sessions` behave the same on the memory store and the fake Cosmos container; `scan_sessions` never returns document text |
| AC-21.21 | *(amended 2026-11-20 (open workspace))* With `WORKSPACE_OPEN=true`, `DELETE /api/review/sessions/{id}` with a valid specialist token returns 403 `forbidden` with "Deleting is switched off on this open demo." for an existing session (with or without `If-Match`) and an unknown id alike; the session still exists, the store is not called, and one `delete_session` audit line with outcome `refused` is written |

## 7. Test plan

| Test file | Covers |
|---|---|
| `tests/unit/process_discovery/admin/test_listing.py` | AC-21.2–21.7 |
| `tests/unit/process_discovery/admin/test_view.py` | AC-21.8–21.10 |
| `tests/unit/store/test_workspace_queries.py` | AC-21.20 |
| `tests/api/test_workspace_routes.py` | AC-21.1, 21.11–21.19 |
| `tests/api/test_open_workspace.py` | AC-21.21 (amended 2026-11-20 (open workspace)) |
| `tests/unit/process_discovery/test_architecture.py` | `admin` imports no peer; routes import only the façade |

## 8. Out of scope (later)

| Item | Note |
|---|---|
| Field and step edits with provenance, and the edit fixes (confirmations reset, out-of-date assessment, coverage from the current registry) | Later |
| Re-running the assessment ("update analysis") | Later |
| Opportunity review, readiness notes, validation and its note to the expert | Later |
| Process overview across sessions (F-18) | Later |
| Implementation briefs and the engineer role's screens (F-19) | Later; the engineer login stays as built in spec 16 |
| KPI tiles beyond the status counts; date, department, region filters; other sorts; paging | Later |
| Audit history stored in the database | Later; the server log is enough now |
| BPMN and Excel exports | Spec 22 |
| The screens, including dark and light theme | Spec 23 part 3 |

## 9. Open questions

| # | Question | Default until decided |
|---|---|---|
| Q1 | Should opening a session (not only its conversation) be audited? | No: only conversation, PDF and delete |
| Q2 | Should the conversation hide the expert's first name in the greeting? | No: shown as stored; the expert is told the team may read it |
| Q3 | Should deleting a session also delete the expert's ideas from it? | No: ideas belong to the expert |

## 10. As built: deviations

| # | Spec said | Built | Why |
|---|---|---|---|
| D1 | `admin` returns its own `ReviewRow` / `ReviewSessionView` types | `review_rows` and `session_view` return the wire models of §4.2 directly; `session_view` also takes `cell_text` (the report's cell rule) and `etag` | Minimum code; `admin` may not import `artifacts`, so the service hands the cell rule in |
| D2 | A stored document that fails validation raises (spec 15) | `scan_sessions` logs it by id (`store_corrupt_document`) and leaves it out of the list; `find_session` still raises | One old document must not take the whole workspace list down |
| D3 | `etag` in body and `ETag` header | Both carry the quoted form (`"00004100-…"`); `If-Match` is compared ignoring quotes and a `W/` prefix | Cosmos etags already contain quotes; the memory store's do not |
| D4 | `delete_session(owner_id, session_id)` (§4.3) | `delete_session(owner_id, session_id, etag=None)`: with an etag, a conditional delete (Cosmos `delete_item` with `etag` + `IfNotModified`; memory compares) that raises `ConflictError` (409) on a mismatch; the workspace always passes it | Lead decision 2026-11-20: no write between the check and the delete can be lost |
| D5 | `completeness` "as %" | The score value, 0 to 1, as `SessionOut.score.value`; the screen shows it as a percent | One number format on the wire |
| D6 | `cluster` filter | 1–8 characters (else 422), matched case-insensitively | Same limit as the cluster picker |
| D7 | PDF "same bytes" (AC-21.13) | Same bytes except the creation time and document id reportlab stamps on every render; the test masks those | Two renders of one report always differ there |
| D8 | — | An unknown session is 404 on every route; delete of one is audited `outcome=not_found`; any other failure `outcome=error` | Completes §3.7 |
| D9 | — | The fake Cosmos container accepts queries without `partition_key` (cross-partition, as the async SDK does) and records each query's partition; a test checks only the two workspace reads cross partitions | The expert's reads stay scoped |
| D10 | Architecture names `workspace_schemas.py` | `app/models/workspace_wire.py`, as this spec says | Spec 21 is the more specific level |

