# 20 · Finish, the discovery report and the PDF

> **Status:** **short step walk (S13 row in the step table), approved 2026-11-20** · approved · **built 2026-11-20** · **Implements:** F-11.4, F-16 (product); §3.3 finish, §3.2 `artifacts/report.py` and `export/{report_pdf,bpmn,substeps,branding}.py`, §6.2 "three in parallel on Finish" (architecture) · **Depends on:** specs 10 (`Organisation`, settings), 11 (LLM errors), 12 (models), 13 (field views, finish state), 15 (finish route, repository), 16 (daily budget), 20, 21
> **Amendment v3, 2026-11-19 (draft):** a fourth parallel call, ASSESS_STEPS (spec 26); two new report parts, *Step-by-step AI assessment* and *Recommended route* (the report now has eleven parts); **hours only**: cost today, hours freed, euro values and saving shares are *parked until the value method is decided (refinement R5)*, their text kept and struck through.
> **Code:** `backend/app/services/process_discovery/artifacts/{assess,report}.py`, `export/{report_pdf,bpmn,substeps,branding}.py`; the finish use case in `service.py` (built by WS6 to this spec)
> **Tests:** `backend/tests/unit/process_discovery/artifacts/test_assess.py`, `test_report_model.py`; `backend/tests/unit/process_discovery/export/`

## 1. Purpose

*Finish* turns a complete map into the **discovery report**. Four model calls (OPPORTUNITIES, MAP, LABEL, ASSESS_STEPS) run at the same time, each with its own timeout and its own fallback; code then computes hours, readiness, the path and the recommended route, and the session is saved **once**. The report itself is built by code from the profile and the stored assessment, in eleven parts plus a cover, the same for every process; each part fails on its own. The same report model feeds the screen (JSON) and the PDF.

## 2. Where it sits

- **Layer:** `artifacts/assess.py` and `artifacts/report.py` in `artifacts`; the PDF in `export` (a peer: it receives the report model and the diagram as data, it never imports `artifacts`). `service.py` owns loading, the budget check and the single save.
- **Builds on:** `run_opportunities`, `run_map`, `linear_process_diagram`, `carry_reviews`, the fingerprints (spec 18); `run_labels`, `compute_code_parts` (spec 19); `field_views` and `finish_state` (spec 13); `rank_nodes` (spec 12); `Organisation` with `branding` (spec 10).
- **Changes:** adds the setting `ASSESSMENT_CALL_TIMEOUT_SECONDS` (spec 10 settings). The report has no stored copy: it is built on each request from the session.

## 3. Behaviour

### 3.1 The assessment run (`assess`)

`assess(profile, previous, llm, rates, readiness_cfg, now, *, refresh=False, timeout)` returns a new `Assessment` and a list of per-part outcomes. It never raises.

1. **Which AI parts to run** (a part is *reused* when its fingerprint matches and `refresh` is false):

   | Part | Reused when | Else |
   |---|---|---|
   | opportunities + stay human + summary | `previous.steps_hash == ai_input_fingerprint(profile)` and `previous.outcomes["opportunities"] == "generated"` | OPPORTUNITIES runs |
   | labels | same hash and `previous.outcomes["labels"] == "generated"` | LABEL runs |
| step assessment | `previous.step_assessment.inputs_hash` equals the profile and catalogue fingerprint (spec 26 §3.7) and `previous.outcomes["steps"] == "generated"` | ASSESS_STEPS runs |
   | diagram | `previous.diagram.steps_hash == map_fingerprint(profile)` and not simplified because of a failed call | MAP runs |

   At *Finish* `previous` is `None`: all four run.
2. **Parallel, each bounded.** The parts to run start together (`asyncio.gather(..., return_exceptions=True)`), each wrapped in `asyncio.wait_for(…, timeout)`; `timeout` = `ASSESSMENT_CALL_TIMEOUT_SECONDS` (default 60, range 10–150).
3. **Outcomes** (stored values fixed by spec 12; the log value is richer):

   | Part | What happened | Stored result | `outcomes[...]` | Log `outcome` |
   |---|---|---|---|---|
   | opportunities | Reply grounded (list may be empty) | New list, `carry_reviews(previous, new)` | `generated` | `generated` |
   | opportunities | `OpportunitiesFailedError` or timeout, nothing stored before | Empty list, summary "" | `failed` | `failed` / `timeout` |
   | opportunities | Same, but a previous list exists (refresh or re-run) | The previous list, kept | unchanged | `refresh_failed` / `refresh_timeout` |
   | diagram | Grounded reply | Model map | `generated` | `generated` |
   | diagram | Unrepairable reply | Linear map, `simplified: true` | `fallback` | `fallback` |
   | diagram | `MapCallFailedError` or timeout | Previous map if any, else linear map | `fallback` | `failed_linear` / `timeout_linear` |
   | labels | Grounded reply | New labels | `generated` | `generated` |
   | labels | `LabelsFailedError` or timeout | Previous labels if any, else `[]` | `failed` (or unchanged when kept) | `failed` / `timeout` / `refresh_*` |
| steps | Grounded reply | New `StepAssessment` (ratings; route built in step 4) | `generated` | `generated` |
| steps | `StepAssessmentFailedError` or timeout | Previous step assessment if any, else `None` | `failed` (or unchanged when kept) | `failed` / `timeout` / `refresh_*` |
   | any | Unexpected exception | As the failed row | as failed | `error` (class name only) |

4. **Then code, always:** `compute_code_parts` (spec 19 §3.7) → `value` (hours only while R5 is parked), `readiness` (notes carried over from `previous`), opportunities with `blocked_by`, `path`, and the recommended route stored on `step_assessment.route` (spec 26 §3.6). `steps_hash = ai_input_fingerprint(profile)`, `generated_at = now`.
5. One `assessment_run` log line: parts run, reused, outcomes, total duration. No text.

**Example.** *Finish* on the EU cost review: the four calls run together; OPPORTUNITIES returns after 14 s, LABEL after 6 s, MAP after 9 s, ASSESS_STEPS after 8 s. Outcomes `{opportunities: generated, diagram: generated, labels: generated, steps: generated}`. If MAP had timed out at 60 s, the report would show the simplified map and the outcome `fallback`; the other parts are unaffected.

### 3.2 *Finish* (service use case, called by `POST /api/sessions/{id}/finish`)

| # | Step | Rule |
|---|---|---|
| 1 | Load | Session and etag; owner check (spec 15) |
| 2 | Already finished | Return the stored report (idempotent; a double click costs nothing) |
| 3 | Gate | `finish_state(session).ready` (spec 13), else 409 `map_incomplete` with the reason. `status` must be `active` |
| 4 | Budget | If the daily budget cannot cover four calls (spec 16), 429 `budget_exhausted`; nothing changes |
| 5 | Assess | `assess(profile, None, …)` (§3.1) |
| 6 | Close | `status = finished`, `phase = finished`, `finished_at = now`, `ttl = None`, `assessment = …`, `report = {status: "mapped"}` |
| 7 | Save once | Replace with `If-Match`. On conflict: reload once; if the reloaded session is already finished → return its report; if it is still active, still ready and `ai_input_fingerprint` and `map_fingerprint` equal the run's → apply step 6 to it and save; otherwise 409 `conflict`. Never a second set of model calls |
| 8 | Answer | 200 with the report model (§3.3) |

Specialist edits (spec 21) call `assess(profile, previous=session.assessment, …)` and save the same way; `refresh=True` is the workspace "regenerate" action.

### 3.3 The report model (`artifacts/report.py`, F-16)

`build_report(session, org, vocab) -> DiscoveryReport` is pure, never raises, and reads only the profile, the counters, `documents[]` names, `scope`, `report` state and the stored `assessment`. It never computes a number: figures come from `ValueResult`, levels from `Readiness`. Each part is built inside its own `try`; a part that fails to build becomes that part with the note "This part could not be built." (logged with the exception class), and the rest of the report still works (F-16.2). Missing answers show as "—"; never invented text.

| # | Part (key) | Content | Source | Notes shown when |
|---|---|---|---|---|
| — | Cover (`cover`) | Product and company name; process name ("Untitled process" if empty); department; cluster code and name; region; owner role ("No process owner identified" for `none_identified`); date of `finished_at` (UTC, "20 November 2026"); status "Mapped" or "Validated by IT" | Profile, report state, organisation | — |
| 1 | At a glance (`at_a_glance`) | Hours a year; the recommended route headline; the **top three** opportunities (path order key of spec 19 §3.6 across all groups, `standardise` left out because it shows under "to prepare"), each with its step hours; up to three things to prepare (low dimensions' lines first, then `standardise` titles, then medium lines). *~~Cost today; hours that could be freed; value conservative–expected~~: parked (R5)* | `value`, `step_assessment.route`, `path`, `readiness` | Hours incomplete: "Hours need: <fields>." · no route: the route line is left out |
| 2 | The process (`process`) | Trigger, end result, who uses the result, business pain, process owner, cluster (name and description) | Profile | Scope verdict `task`: "This looks like one person's task rather than a process shared by several people." · one-off: "This looks like a one-off project, not recurring work." |
| 3 | Volume and measures (`measures`) | Volume ("1 per month", or the raw words), time today ("5 days (estimated) — qualitative"), target, same way everywhere ("No — each site sends its own spreadsheet layout"), sensitive data ("None" for the none row) | Profile | A missing value reads "Not measured yet" |
| 4 | Process map and steps (`map`) | The map (`ProcessDiagram`, with its data objects and stores); all systems (D02); the step table: one column per step, rows S01–S13 in registry order (amended 2026-11-20, short step walk: the row *Rules or judgement*) | `diagram`, profile | `simplified`: "Simplified map built from the steps (order and owners only): the AI-drawn map was not available." · no diagram: "The process map could not be drawn." |
| 5 | Step-by-step AI assessment (`steps`) | One row per step: number and name; hours a year; AI fit as words ("AI can do it" / "AI assists a person" / "Stays with people" / "Not assessed"); route = the catalogue entry's name ("No route" when `None`) and route reason; reason; evidence in quotes with "the expert's words" or "from <document name>" | `step_assessment`, `value`, catalogue names | Outcome `failed`: "The step-by-step assessment could not be generated this time. A specialist can run it again." · placeholder catalogue (`catalogue_note`): "Routes come from a placeholder solution list, not the company's real tools." |
| 6 | Recommended route (`route`) | The headline; groups in order **Start with** (step, name, hours, route name), **Later**, **Fix first** (step, name, route reason), **Stays with people**, **No route yet**; **What to have in place** (the prerequisites) | `step_assessment.route`, catalogue names | Outcome `failed` or no route: "No recommended route: the step-by-step assessment is not available." · placeholder note as Part 5 · an empty group is left out |
| 7 | Transformation assessment (`assessment`) | AI summary; each opportunity (not rejected): title, steps ("Steps 1–2: Collect site spreadsheets, Consolidate into the master file" or "Whole process"), type label, what changes, how, prepare first, impact and reason, feasibility and reason, evidence in quotes with "the expert's words" or "from <document name>", review status when not pending; steps that stay with people with reason and evidence | `assessment` | Outcome `failed`: "The opportunities could not be generated this time. A specialist can run them again." · empty list: "No opportunity was found. The analysis looked for steps to remove or standardise, routing and reminders, re-typing between systems, reading or writing documents, drafting or summarising, multi-step work an AI agent could do, and screen automation." |
| 8 | Hours a year (`potential`) | Per step: hours per run, runs a year, hours a year; per opportunity: the hours of the steps it touches; total; formula lines; assumptions; the line "Euro value and savings are not shown yet: the method is still being agreed." *~~Combined share, hours freed, value conservative and expected~~: parked (R5)* | `value` | Incomplete: the problem sentences and "Total needs: <fields>" |
| 9 | Readiness checklist (`readiness`) | Six rows: label, the question (F-15 table), level as a word, reason, to prepare, specialist note; the line "A guide to what would make the change easier. Not a verdict." | `readiness` | — (unknown is a level with its reason) |
| 10 | Suggested path (`path`) | Three groups in order: **Prepare first** (the low dimensions' to-prepare lines, then its opportunities), **Quick wins**, **Bigger changes**; each opportunity with its steps and step hours (*~~expected value~~: parked, R5*) | `path`, `value` | An empty group reads "Nothing here." |
| 11 | Gaps and sources (`gaps`) | Every field whose view status (spec 13) is partial, invalid, empty, proposed, deferred, given up or skipped, with its reason; documents used (names and outcome, never text); the closing note: "This is a first assessment from one expert's account in a short interview{, with N documents}. Numbers are hours estimated from the expert's answers; the specialist review checks them." | Field views, `documents[]` | — |

**Display formats** (one module, `report.py`, used by screen and PDF):

| Value | Format | EU example |
|---|---|---|
| Hours (totals, per step, per opportunity) | Whole hours, "h" | 342 h · 147 h · 94 h |
| Hours in formulas | 2 decimals, trailing zeros dropped | 48.96 h |
| ~~Euros~~ | *Parked (R5): no euro figure is formatted or shown.* Was: currency symbol from `rates.currency`, rounded to the nearest 100 for totals, nearest 10 per opportunity | — |
| AI fit | AI can do it · AI assists a person · Stays with people · Not assessed | — |
| Shares | Whole percent | 68% |
| Grades and levels | Capitalised word, never colour alone | High · Low · Unknown |
| Type | Eliminate, Standardise, Workflow, Integration, Document AI, AI assistant, AI agent, RPA | — |

**At a glance, EU:** "About 342 hours a year." Route: *Start with step 2 "Consolidate into the master file" (about 96 h a year) using Custom AI app or agent built by the AI engineering team (placeholder). Fix first: step 1 "Collect site spreadsheets".* Top three: Read the site spreadsheets into the master file (steps 1–2, 168 h) · Draft the variance summary (step 5, 72 h) · Chase variance explanations automatically (step 4, 30 h). *(Parked, R5: the former line "cost today €30,800 · about 147 hours could be freed · worth €6,600 to €9,900 a year".)* To prepare: "Agree one way of working (one template) across teams and regions. What differs today: "each site sends its own spreadsheet layout"." · "Agree one site template".

**Step table cells** (`substeps.cell_text`, one formatter for screen, PDF and the Excel export of spec 22):

| Leaf | Format |
|---|---|
| Text, list | Text; list items joined by "; " |
| `roles` | "Site controller (sends the file)"; rows joined by "; " |
| `approvals` | "Head of Controlling (waits 1 day)" |
| `exceptions` | "totals do not match SAP → back to step 1" |
| `data` | "In: a; b. Out: c" |
| `effort` | "1 day, each time" |
| `decision_type` *(approved 2026-11-20, short step walk)* | "Mix: mostly fixed rules, I judge the outliers" (the kind capitalised, then the expert's words) |
| None row | "None" |
| Empty | "—" · skipped cell: "— (skipped)" · proposed value: the value + " (proposed, not confirmed)" |
| Any cell | Capped at 1,500 characters with "…" |

`__meta`, `__skipped` and flags are never shown. The expert's display name is never in the report.

### 3.4 The PDF (`export/report_pdf.py`, `bpmn.py`, `substeps.py`, `branding.py`)

`write_pdf(report, brand) -> bytes`, run in a worker thread by the route. Light theme, branding from configuration.

| Item | Rule |
|---|---|
| Page | A4 portrait, 1-inch margins; a **landscape** page template for Part 4's map and step table (`NextPageTemplate`), then back to portrait |
| Cover | Banner (primary colour band with the product name and company name; the logo when configured), a card "Discovery report · Generated on <date>", the process name as title, a meta card (department, cluster, region, process owner, status), vertically centred by measuring each block. Cover fields capped at 1,000 characters |
| Flow | Parts follow each other without forced page breaks (except after the cover and around the landscape pages). A section heading is kept with its first block (`KeepTogether`) |
| Parts 5–6 | Part 5 as a table with a repeated header row (step, hours, AI fit, route, reason, evidence), wrapped cells; Part 6 as short labelled lists |
| Part 4 | Portrait: title, systems. Landscape: the map page (heading, drawing scaled into the space left, never below 40 mm high, caption when simplified), then the step table pages |
| Step table | At most 4 steps per page; fonts 9 → 8 → 7 → 6 pt until a chunk fits one page; if not, narrower chunks (4, 2, 1 steps); if still not, rows split across pages. With more than one page, a caption "Step table — steps 1–4 of 5 (page 1 of 2)" |
| Opportunities | One block per opportunity (title line with type, impact and feasibility as words; then labelled lines), so long text splits across pages naturally |
| Tables | Potential and readiness as tables with a repeated header row; cells as wrapped paragraphs |
| Footer | Every page: "<product name> · Discovery report · <process name, capped at 60>" left, "Page N" right; a thin primary-colour rule |
| Text | Every session-derived string escaped for reportlab (`&`, `<`, `>`). Helvetica: characters outside cp1252 print as "?" in the PDF only (the screen shows them) |
| Map drawing fails | Any error while building or test-rendering the drawing → the note "The process map could not be drawn." on that page; the PDF still renders |
| Layout fails | A reportlab `LayoutError` anywhere → a one-page document: process name and "This report could not be laid out in full: one or more answers are too long to fit on a page. A specialist can shorten them." Never a 500 |
| Metadata | PDF title = process name; no author field |

**Branding** (`branding.py`): `Brand.from_config(org)` holds product name, company name, primary and accent colours, optional logo path (resolved against the config folder; a missing or unreadable file means a text-only banner, logged once). Fixed neutral palette for the light theme: page white, text `#1F2933`, muted `#5B6573`, borders `#D5DAE1`, cards `#F4F6F8`. Headings and accent bars use the primary colour; table rules the accent colour. No company name, colour or text is a constant in code.

**Map drawing** (`bpmn.py`): normalises whatever it gets (bad ids, unknown types, lanes out of range → lane 0, non-int steps, illegal markers → type default, unknown or self flows dropped, one default per gateway); columns by `rank_nodes` (back edges are loops, drawn through a loop channel above the higher lane); two nodes of the same rank and lane side by side, never on one spot; one pool (process name read vertically) with one lane per role; start thin circle, end thick circle, trigger icons; tasks as rounded boxes numbered "Step n" with task-type icons; gateway diamonds with ×, +, ○ or pentagon; orthogonal arrows with labels; default flows with a slash; data objects (inputs left, outputs right) and data stores under the tasks, joined by dotted associations, taken from `diagram.data_objects` and `diagram.data_stores` (spec 18). Drawn at natural size, then scaled to fit the box (never above 1.25×). Text cleaned, capped at 80 characters, wrapped with long words hard-cut. Known limit: a map past about 12 steps is hard to read on one page (the product caps steps at 6).

### 3.5 Routes using this spec (contract for spec 15)

| Route | Behaviour |
|---|---|
| `POST /api/sessions/{id}/finish` | §3.2; 200 report JSON |
| `GET /api/sessions/{id}/report` | `build_report` of the stored session; no model call; 404 before *Finish* |
| `GET /api/sessions/{id}/report.pdf` | `write_pdf` in a worker thread; `Content-Type: application/pdf`, `Content-Disposition: attachment; filename="discovery-report-<slug>.pdf"`; no model call |
| Workspace review (spec 21) | The same model plus field views; regenerate = `assess(…, refresh=True)` |

## 4. Interfaces

```python
# artifacts/assess.py
PartName = Literal["opportunities", "diagram", "labels", "steps"]
@dataclass(frozen=True)
class PartOutcome: part: PartName; outcome: str; duration_ms: int; reused: bool
async def assess(profile: Mapping[str, Any], previous: Assessment | None, llm: LLM, rates: Rates,
                 readiness_cfg: ReadinessConfig, now: str, *, refresh: bool = False,
                 timeout: float = 60.0) -> tuple[Assessment, list[PartOutcome]]   # never raises

# artifacts/report.py  (pure)
class DiscoveryReport(WireModel):
    cover: ReportCover; at_a_glance: AtAGlancePart; process: FieldsPart; measures: FieldsPart
    map: MapPart; steps: StepsPart; route: RoutePart; assessment: AssessmentPart; potential: PotentialPart
    readiness: ReadinessPart; path: PathPart; gaps: GapsPart; generated_at: str
# every part model has: number: int, title: str, note: ReportNote | None
class ReportNote(WireModel): kind: Literal["missing", "failed", "empty", "simplified", "incomplete", "task", "one_off", "error"]; text: str
class ReportField(WireModel): key: str; label: str; value: str; status: FieldStatus | None; source: str | None; quote: str | None
class MapPart(...): diagram: ProcessDiagram | None; caption: str | None; systems: list[str]; columns: list[StepColumn{number, name, cells: list[ReportField]}]
class StepsPart(...): rows: list[StepRow{number, name, hours, fit, fit_label, route_id, route_name, route_reason, reason, evidence, evidence_label}]; catalogue_note: str | None
class RoutePart(...): headline: str; groups: list[RouteGroup{key, title, items: list[RouteItem{number, name, hours, route_name, reason}]}]; prepare: list[str]; catalogue_note: str | None
class AssessmentPart(...): summary: str; opportunities: list[ReportOpportunity]; stay_human: list[ReportStayHuman]
class PotentialPart(...): complete: bool; steps: list[StepValueRow]; opportunities: list[OpportunityValueRow{id, title, steps_label, step_hours}]; totals: TotalsRow{hours}; formulas: list[str]; assumptions: list[str]; problems: list[str]
class ReadinessPart(...): dimensions: list[ReadinessRow{key, label, question, level, level_label, reason, to_prepare, note}]; footer: str
class PathPart(...): groups: list[PathGroup{key, title, prepare_lines: list[str], items: list[PathItem{opportunity_id, title, steps_label, step_hours}]}]   # hours_freed, value_expected parked (R5)
class GapsPart(...): fields: list[ReportField]; documents: list[DocumentRow{name, outcome}]; closing_note: str
def build_report(session: Session, org: Organisation, vocab: Vocabulary) -> DiscoveryReport

# export/substeps.py
EMPTY_CELL = "—"; MAX_CELL_CHARS = 1500
def truncate_cell(text: str, limit: int = MAX_CELL_CHARS) -> str
def escape_for_pdf(text: Any) -> str
def cell_text(leaf: str, value: Any, *, skipped: bool, proposed: bool) -> str
def build_table_flowable(columns: Sequence[StepColumn], width: float, brand: Brand, *,
                         column_offset: int, font_size: int) -> Flowable

# export/bpmn.py
def layout(diagram: Any) -> dict[str, dict[str, Any]]                  # node id → {column, lane, type}
def build_drawing(diagram: Any, width: float, height: float, brand: Brand, process_name: str = "") -> Drawing

# export/branding.py
@dataclass(frozen=True)
class Brand: product_name: str; company_name: str; primary: Color; accent: Color; logo: Path | None
    @classmethod
    def from_config(cls, org: Organisation, config_dir: Path) -> "Brand": ...

# export/report_pdf.py
def write_pdf(report: DiscoveryReport, brand: Brand) -> bytes          # never raises on layout problems
```

`format_hours` and `format_share` live in `report.py` (`format_money` parked, R5); the PDF writer receives already formatted strings in the report model (it formats nothing).

## 5. Implications

- **Other components:** spec 15 implements §3.2 and §3.5 in `service.py` and the routes, with the error codes listed; spec 16 provides the budget check for four calls; spec 21 reuses `assess` and `build_report`; spec 23 renders `DiscoveryReport` as returned (the client formats nothing); spec 22 reuses `cell_text`.
- **Data:** at *Finish*: `status`, `phase`, `finished_at`, `ttl`, `assessment`, `report` written in one replace. No stored report body.
- **Config:** reads `organisation.yaml` (`product_name`, `company_name`, `branding`) and `solutions.yaml` (entry names for Parts 5–6, `placeholder`). New setting `ASSESSMENT_CALL_TIMEOUT_SECONDS` (default 60, 10–150).
- **Security and privacy:** the report shows roles, never the expert's display name; no transcript and no document text (only document names and the quotes already in the profile). Every free text is escaped before reportlab sees it.
- **Cost and latency:** four calls in parallel per *Finish*, about 10–20 s typical; worst case one timeout (60 s) plus code. Report and PDF requests make no model call. The PDF renders off the event loop.

## 6. Acceptance criteria

| ID | Given / when / then |
|---|---|
| AC-20.1 | At *Finish* (`previous=None`) with a `FakeLLM` scripted for all four, `assess` makes exactly one OPPORTUNITIES, one MAP, one LABEL and one ASSESS_STEPS call and returns outcomes all `generated` |
| AC-20.2 | The four calls really run concurrently: with a test double where each call waits on a shared barrier of 4, `assess` completes (it would deadlock if run one after another) |
| AC-20.3 | Given a previous assessment whose fingerprints match, `assess` makes no model call, keeps the AI parts and recomputes value, readiness and path |
| AC-20.4 | Given a profile whose map fingerprint changed but not the AI fingerprint, only MAP runs; given an AI fingerprint change, OPPORTUNITIES, LABEL and ASSESS_STEPS run and MAP does not; given only a catalogue change, only ASSESS_STEPS runs |
| AC-20.5 | `refresh=True` runs all four even when fingerprints match |
| AC-20.6 | OPPORTUNITIES failing (scripted `LLMUnavailableError`) does not stop MAP or LABEL: their parts are `generated`, opportunities `failed`, the opportunity list empty, hours complete |
| AC-20.7 | MAP returning an unusable reply → stored map `simplified: true`, outcome `fallback`; MAP raising `LLMUnavailableError` → linear map, outcome `fallback`, log `failed_linear` |
| AC-20.8 | LABEL failing → labels `[]`, outcome `failed`, Data and Rules `unknown`, the other parts unaffected |
| AC-20.9 | A call slower than the timeout (0.05 s in the test) is cancelled; its part degrades as failed (`timeout` / `timeout_linear` in the log) and `assess` returns |
| AC-20.10 | A refresh that fails keeps the previous opportunities, labels or map and their outcomes (`refresh_failed` in the log) |
| AC-20.11 | An unexpected exception inside a part is caught; `assess` never raises (fuzzed with exceptions from each part) |
| AC-20.12 | Review decisions survive a re-run through `carry_reviews`; specialist readiness notes survive |
| AC-20.13 | Finish: one repository write with `If-Match`, holding status `finished`, phase `finished`, `finishedAt`, no TTL, the assessment and `report.status == "mapped"` |
| AC-20.14 | Finish on a session that is not ready → 409 `map_incomplete` with the reason; no model call is made |
| AC-20.15 | Finish on an already finished session returns the stored report with no model call and no write |
| AC-20.16 | Finish with the budget exhausted → 429 `budget_exhausted`, no model call, session unchanged |
| AC-20.17 | A save conflict where the reloaded session is still active and unchanged → saved on the second try with no new model call; where it changed → 409 `conflict`; where it is already finished → its report |
| AC-20.18 | `build_report` of the finished EU fixture has the cover and the eleven parts with numbers 1–11 in order and titles as in §3.3 |
| AC-20.19 | Every figure in the report equals the `ValueResult` it came from (formatted per §3.3): 342 h total; 168 h, 72 h, 30 h for o1–o3; no euro sign, "cost", "freed" or "saving" figure anywhere in the report JSON or PDF text while R5 is parked |
| AC-20.20 | At a glance lists the top three as o1, o2, o3 (not the `standardise` o4) with their step hours, the route headline of spec 26 §3.2, and the Standard to-prepare line first |
| AC-20.21 | Part 2 shows the cluster name and description; a `task` scope verdict adds the task note; a one-off process adds the one-off note |
| AC-20.22 | Part 3 shows "Not measured yet" for an empty target, "None" for the none row, "No — each site sends its own spreadsheet layout" for P14 |
| AC-20.23 | Part 4 has one column per step with the S01–S12 rows formatted per the cell table (roles with contribution, exception pointer, "In: … Out: …", "— (skipped)", "(proposed, not confirmed)") and no `__meta` or `__skipped` text |
| AC-20.24 | A simplified map carries the simplified caption; a missing diagram carries the "could not be drawn" note |
| AC-20.25 | Part 7 hides rejected opportunities, shows "Whole process" for `steps == []`, labels evidence from a proposed value as "from <document name>", and shows the failed and the empty notes in their cases |
| AC-20.26 | Part 8 with incomplete hours lists the problem sentences and the fields, and shows "—" for the total, never 0; it always carries the "not shown yet" line about euro value |
| AC-20.27 | Part 9 has six rows with level words (including "Unknown") and the "Not a verdict" line; the model has no overall score or verdict field |
| AC-20.28 | Part 10 shows the EU groups Prepare first (Standard line, o4, o1), Quick wins (o2 72 h, o3 30 h), Bigger changes ("Nothing here.") |
| AC-20.29 | Part 11 lists deferred, given-up, skipped and unconfirmed fields with reasons, the document names (no text) and the closing note with the document count |
| AC-20.30 | A part whose builder raises becomes that part with the "could not be built" note; the other parts are complete |
| AC-20.31 | The expert's display name and any message text never appear in the report JSON or the PDF text (sentinel test) |
| AC-20.32 | `write_pdf` of the EU report returns bytes starting with `%PDF`; extracted text contains the process name, every part title (including "Step-by-step AI assessment" and "Recommended route"), "342 h" and the Standard to-prepare line, and no "€" |
| AC-20.33 | The cover, footer and banner use `product_name`, `company_name` and colours from the organisation config; changing the config changes the PDF; no company string is in the code (grep test) |
| AC-20.34 | Free text with `&`, `<`, `>`, emoji and Chinese characters renders without error |
| AC-20.35 | The step table splits oversized content instead of cutting rows: it narrows the chunk before splitting rows, and returns one table when it already fits  |
| AC-20.36 | Many long opportunities (12 × 1,500 characters) flow across pages and render |
| AC-20.37 | A runaway cover field (10,000 characters) renders the full report, not the fallback document |
| AC-20.38 | A forced `LayoutError` yields the one-page note document, not an exception |
| AC-20.39 | A malformed stored diagram, or a drawing that raises, yields the "could not be drawn" note and the PDF still renders; the map page never asks for a non-positive height |
| AC-20.40 | `build_drawing` fits the box and renders for linear, branching, looping and 12-column diagrams; every task, event and gateway marker draws; data objects and stores are drawn from the diagram and add height only to lanes that need them |
| AC-20.41 | **Drawing fuzz:** 300 seeded random broken diagrams (ids, types, lanes, steps, markers, flows, `is_default`, lane lists, data objects) always draw within the given box and render |
| AC-20.42 | `layout` places a linear flow left to right in its lanes, puts branches in the same column in different lanes, never stacks two nodes on one spot, and clamps bad lane values |
| AC-20.43 | A thin session (finished with the minimum fields) builds a report and a PDF without error |
| AC-20.44 | `GET .../report` and `GET .../report.pdf` make no model call (FakeLLM with no scripted replies) |
| AC-20.45 | ASSESS_STEPS failing (scripted `LLMUnavailableError`) leaves the other three parts `generated`, stores `step_assessment = None`, outcome `steps: failed`; Parts 5 and 6 show their failed notes and the rest of the report is complete |
| AC-20.46 | Part 5 on the EU fixture has 5 rows with hours 72, 96, 72, 30, 72, fit words, route names from the catalogue (not ids), and evidence labels; a step with `route_id = None` shows "No route"; a step with `fit = None` shows "Not assessed" |
| AC-20.47 | Part 6 on the EU fixture: headline as spec 26 §3.2; Start with steps 2, 3; Later 5, 4; Fix first 1; the empty "Stays with people" and "No route yet" groups are left out; "What to have in place" lists the prerequisites |
| AC-20.48 | With `placeholder: true` in `solutions.yaml`, Parts 5 and 6 carry the placeholder note; with `false` they do not |
| AC-20.49 | The `steps` part reuses its stored result when the profile and catalogue fingerprints match, and a refresh that fails keeps the previous step assessment (`refresh_failed`) |

## 7. Test plan

| Test file | Covers |
|---|---|
| `tests/unit/process_discovery/artifacts/test_assess.py` | AC-20.1–20.12, 20.45, 20.49 (`FakeLLM`, a barrier double for concurrency, a slow double for timeouts) |
| `tests/unit/process_discovery/artifacts/test_report_model.py` | AC-20.18–20.31, 20.43, 20.46–20.48 |
| `tests/unit/process_discovery/export/test_report_pdf.py` | AC-20.32–22.39 (with `pypdf` text extraction) |
| `tests/unit/process_discovery/export/test_bpmn.py` | AC-20.40–22.42 (fuzz with `random.Random(1234)`) |
| `tests/unit/process_discovery/export/test_substeps.py` | Cell formats of §3.3, truncation, escaping |
| `tests/unit/process_discovery/export/test_branding.py` | AC-20.33 (config-driven brand, missing logo) |
| `tests/api/test_process_discovery_finish.py` (written with WS6) | AC-20.13–22.17, 22.44 |

## 8. Out of scope

| What | Where |
|---|---|
| The calls' prompts, grounding and fallbacks | Specs 18, 19 |
| Routes' access checks, error envelope, repository | Specs 15, 16 |
| Review screen, validation, regenerate button, overview, briefs | Spec 21 |
| BPMN XML and Excel exports | Spec 22 |
| Screen layout of the report | Spec 23 |
| A closing call-to-action card, a steering-group pack, translated reports | Not in the prototype |

## 9. Open questions

| # | Question | Default until decided |
|---|---|---|
| Q1 | The product target is a report within about 30 s; a 60 s per-call timeout can exceed it in the worst case. Lower it? | 60 s; typical runs are 10–20 s; measure in evaluation |
| Q2 | When MAP failed as a *call*, the linear map is stored. Retry automatically on the next report view? | No: report views never call the model; the specialist can regenerate (spec 21) |
| Q3 | Show rejected opportunities to the expert, struck through? | No: hidden from the expert's report, visible on the review screen |
| Q4 | Store a rendered report snapshot at validation, so the validated version is frozen? | No: built on request; the report status records validation |
| Q5 | Fonts for non-Latin text in the PDF (CJK, Cyrillic)? | Helvetica, "?" for unsupported characters; a TTF font is a production item |
| Q6 | Part 6 *Recommended route* (per step) and Part 10 *Suggested path* (per opportunity) overlap. Merge them later? | Keep both: different units (steps vs opportunities) |
| Q7 | Should the expert see the routes before NIG's real catalogue exists? | Yes, with the placeholder note |
