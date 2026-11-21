# 24 · Evaluation: simulated experts, runner, scoring, seed data

> **Status:** built 2026-11-20 with deviations (§10); approved 2026-11-20 (judge app-chat at default temperature; efficiency metrics; seeded sessions tagged Simulated; Q8 offer-never-force) · **amended 2026-11-20** (product owner: headline metrics are the employee's time and the detail burden, §3.9b; messages are no longer a target; safety net 80) · **amended 2026-11-20, review** (product owner: steps matched by content, A1; busy-person answer length, A2; plus the review fixes of §11: the persona presses *Finish*, own role implied, judge-v2) — **built 2026-11-20** (AC-24.44 to AC-24.50; `make test-eval` 160 passed; live quick run `20261120-212950`, §10) · **Implements:** F-25 and the quality targets of §8 (product), §3.9 and §6.6 (architecture) · **Depends on:** specs 11, 12, 13, 14, 15, 16, 17, 20, 26
> **Code:** `eval/run.py`, `eval/evalkit/` · **Data:** `eval/personas/`, `eval/documents/`, `eval/judge_calibration.yaml`, `eval/prices.yaml`, `eval/employee_time.yaml`, `eval/tiers.yaml` · **Tests:** `eval/tests/`

## 1. Purpose

Prove, with numbers, that the interview works end to end. Simulated experts (personas) are played by a model through the **real API**; each one has a hidden true process. A small runner plays them, presses *Finish*, and scores what the product captured against the hidden truth and against the product quality targets (product §8). One scorecard per run, compared with the last one, so a prompt or code change shows its effect. Finished runs can also seed the demo overview.

**Two main dimensions, always shown together:** **report quality** (how much of the hidden truth the report got right) and **efficiency** (how many expert messages it took). A long chat that gets everything right is not a success: the product owner wants short interviews, never endless chats.

**Amended 2026-11-20 (product owner).** The problem is not the number of messages but the **employee's time** and being asked **low-value details**. The headline is now four numbers (§3.9b): estimated **employee time** per session, **detail burden** (share of questions that ask only for low-value fields), report quality on the **Tier A** fields, and the **assessment match** (fit and route). Messages to *Finish* are still reported but have no target; the hard cap becomes a safety net at 80 messages.

## 2. Where it sits

- **Outside the backend.** `eval/` is its own package. It calls the app only through HTTP (the API of specs 15, 17, 20); it may import the backend for four things only: `create_app` and the in-memory store (in-process mode), `llm.py` (`create_llm`, `CallType`, for the EXPERT and JUDGE calls), the field registry (to validate persona keys), and `domain/value_parse.py` (to read numbers the same way the product does). It never imports `interview`, `profile` internals or prompts, and never writes to a session except through the API.
- **What exists today:** `CallType.EXPERT` and the `eval-expert` deployment setting (`azure_openai_eval_deployment`, spec 11); the disk cache (`llm_cache.py`, on in stage `local`); `FakeLLM`; the turn log (`interview_turn`, spec 14 §3.11) and the call log (`llm_call`, spec 11 §3.8); `fieldViews[].asks` on `SessionOut` (spec 13 §3.11); the report and PDF routes (spec 20 §3.5); the solution catalogue (`config/nig/solutions.yaml`, spec 26). `make eval` is a placeholder.
- **What it changes:** spec 11 gains `CallType.JUDGE` and a judge deployment setting (§5); the Makefile gains the real `eval` and `test-eval` targets; `.gitignore` gains `eval/runs/` and `eval/.cache/`.

### 2.1 Options considered

| Option | Good | Against | Taken |
|---|---|---|---|
| DeepEval | Ready metrics (G-Eval, answer relevancy), test-runner style | Built for single question-and-answer pairs and RAG; our unit is a 40-turn form-filling session with code-owned state. Its LLM metrics would judge things our code already decides exactly (counts, cluster, routes). Extra dependency and its own model wiring outside `llm.py` | No |
| Ragas | Good for retrieval quality | We have no retrieval step to measure. Same wiring problem | No |
| **Own small runner** | Plays multi-turn personas through our own API; scores by code first and uses one narrow judge; reuses `llm.py` (budgets, cache, logging); about 800 lines | We write and test it ourselves | **Yes** |

## 3. Behaviour

### 3.1 Folder layout

| Path | Content | In git |
|---|---|---|
| `eval/run.py` | CLI entry (`python -m eval.run`) | yes |
| `eval/evalkit/persona.py` | Persona models (Pydantic) and loader | yes |
| `eval/evalkit/expert.py` | The simulated expert: prompt and EXPERT call | yes |
| `eval/evalkit/driver.py` | API client: in-process app or a URL | yes |
| `eval/evalkit/play.py` | Plays one persona: turns, uploads, *Finish*, artefacts | yes |
| `eval/evalkit/score_fields.py`, `score_behaviour.py`, `score_labels.py` | Scoring by code | yes |
| `eval/evalkit/judge.py`, `calibrate.py` | The judge and its calibration | yes |
| `eval/evalkit/scorecard.py` | Totals, targets, deltas, Markdown and JSON | yes |
| `eval/evalkit/seed.py` | Optional seeding of finished sessions into Cosmos | yes |
| `eval/personas/*.yaml` | One file per persona (§3.2) | yes |
| `eval/documents/` | Files personas upload | yes |
| `eval/judge_calibration.yaml` | Hand-labelled judge pairs (§3.8) | yes |
| `eval/prices.yaml` | € per million tokens, per deployment (§3.10) | yes |
| `eval/employee_time.yaml` | Reading and typing speeds, think and upload times (§3.9b; assumptions) | yes |
| `eval/tiers.yaml` | Field value tiers A / B / C, process core and low-value fields (§3.9b) | yes |
| `eval/evalkit/score_employee.py` | Employee time, detail burden, quality split (§3.9b) | yes |
| `eval/reports/latest.json`, `latest.md` | The scorecard of the last full run: the baseline for deltas | yes |
| `eval/runs/<YYYYMMDD-HHMMSS>/` | Every run's artefacts (§3.6) | **no** |
| `eval/tests/` | Unit tests and the tiny end-to-end test | yes |

### 3.2 The persona file

One YAML per persona, validated by `Persona` (Pydantic, `extra="forbid"`). A bad file stops the run before any model call (exit 2).

| Key | Content | Rule |
|---|---|---|
| `id`, `version` | `p01-cooperative`, `1` | `id` slug, unique; bump `version` when the truth or behaviour changes (deltas are only shown for the same version) |
| `quick` | `true` / `false` | In the `QUICK=1` set |
| `seed` | `true` / `false` | May seed the demo overview (§3.12) |
| `kind` | `cooperative` or `difficult` | Picks the message target and whether the quality target applies (§3.9a) |
| `profile` | Who the person is: role in their words, region, team, how they talk, language | Free text, shown to the simulated expert |
| `behaviour` | 2–10 rules for how they answer ("never gives a number; says it depends") | Each one short sentence |
| `truth.fields` | The hidden true process: registry keys `department` … `process.substep_count` (P01–P16), registry shapes | Every key must exist in the registry; P05 is a taxonomy code |
| `truth.steps` | One entry per step, every scored registry leaf (S01–S11 and S13 `decision_type` `{kind: rules | judgement | mix, evidence}`, since the 2026-11-20 short step walk; S12 optional) | Count = `truth.fields["process.substep_count"]` |
| `truth.aliases` | Other ways to say a role or system (`"site managers": ["site manager", "SMs"]`) | Used by code matching (§3.7) |
| `truth.disclose` | Per field key or `steps[*].<leaf>`: `always` (default), `vague` (says it only in rough words), `never` (refuses) | `never` fields are scored by the "no invention" rule (§3.7 item 6) |
| `truth.week` | Other work in their week: `{name, runs, time, people, inputs}` in their words | Gives the steering signals; may be empty |
| `documents` | `[{file, at, stale}]`: `file` under `eval/documents/`; `at` one of `{start: true}`, `{turn: n}`, `{phase: <phase>}` (first response in that phase); `stale`: `[{key, doc_value}]`, the out-of-date values the file holds | File type allowed by `documents.yaml`; at most 3 per persona |
| `expected.cluster` | Taxonomy code | Must exist in `taxonomy.yaml` |
| `expected.scope` | `process` or `task` (the verdict at *Finish*) | — |
| `expected.steering` | `null` (steering must not run) or `{recommended, chosen, ideas}`: candidate names | Names must appear in `truth.week` or be `truth.fields["process.name"]` |
| `expected.routes` | Per step number: `{fit: [..], route: [..]}`, the acceptable AI fits and catalogue ids | Ids must exist in `solutions.yaml` and each id must allow at least one of the listed fits |
| `expected.min_conflicts` | Conflicts the documents should raise | Default 0 |

### 3.3 The four first personas

Designed so that the four later ones (13 steps, switches language, contradicts self, gives a screenshot) are new files only: no runner change.

`kind`: p01 and p04 are `cooperative` (p04 starts from a document, which should make it shorter, not longer); p02 and p03 are `difficult`.

| ID | Who | Process (truth) | Behaviour | Documents | Expected |
|---|---|---|---|---|---|
| `p01-cooperative` (quick, seed) | Cost controller, North America, Finance | Monthly cost review, 5 steps, every month, 5 working days today, target 2 | Answers what is asked, gives numbers, one process in mind | — | Cluster `FIN`; steering `null`; scope `process`; routes e.g. step 2 *Consolidate* `{fit: [automate], route: [custom-ai-app, low-code-flow]}`, step 1 *Collect* `{fit: [assist, automate], route: [fix-first]}` |
| `p02-vague` (quick) | Service desk team lead, Asia-Pacific, IT | Incident ticket triage, 4 steps | Vague; refuses every number ("it depends", "I don't track that"); `disclose: never` on P10, P12, P13 and every S08 | — | Cluster `IT`; steering `null`; no invented number (§3.7 item 6); still finishes |
| `p03-task-mixed-week` | Site office coordinator, Middle East, HR | Onboarding new site staff, 4 steps | Opens with "mostly I file my timesheet" (a task); then names a mixed week; answers steering questions in rough words; says yes to the recommendation | — | Cluster `HR`; steering `{recommended: "onboarding new site staff", chosen: same, ideas: [timesheet, safety training records, ordering PPE]}`; scope `process` |
| `p04-stale-document` | Security analyst, Europe, IT | Quarterly user access review, 5 steps | Cooperative; answers context, boundaries and measures first, then uploads the team procedure; corrects what is out of date ("we moved that to the access tool last year") | `access_review_procedure_2023.md` at `{phase: steps}`; `stale`: volume "twice a year", step 3 systems "Excel", step 4 approvals "line manager by e-mail" | Cluster `IT`; `min_conflicts: 1`; no stale value kept (§3.9) |
| `p05-cv-screening` (seed; added 2026-11-21) | Talent acquisition specialist, Europe, HR | Screening applications for an open role, 3 steps (download and organise the packages; rough first screening; detailed screening against the hiring manager's must-haves and shortlist handoff), 6 roles a month, 3 working days today, target 1 | Cooperative; explains the selection criteria (each hiring manager sets different must-haves, often incomplete) **only when asked**, so the run shows whether the agent asks for them | — (CV, cover letter and certificates named in words only) | Cluster `HR`; steering `null`; scope `process`; steps 2–3 routes include the internal `cv-screening` tool; P14 variation `partly` |

**p03 steering, worked out by the product's own rule** (spec 14 §3.15, weights 0.5 / 0.2 / 0.3, 500 h, 5 people). Only the first three candidates in mention order are steered:

| Candidate (mention order) | Their words (runs · time · people · inputs) | Hours a year | People | Data | Score |
|---|---|---|---|---|---|
| filing my timesheet | every week · about 15 minutes · just me · the time system | 50 × 0.25 = 12.5 | 1 | 1.0 | 0.0125 + 0 + 0.3 = 0.3125 |
| onboarding new site staff | every week · about 4 hours · 5 of us · forms in the HR system | 50 × 4 = 200 | 5 | 1.0 | 0.2 + 0.2 + 0.3 = **0.700** |
| safety training records | every month · about 2 days · 3 of us · paper sign-in sheets | 12 × 16 = 192 | 3 | 0.0 | 0.192 + 0.1 + 0 = 0.292 |
| ordering PPE | not steered (4th) | — | — | — | idea, no signals |

Expected recommendation: *onboarding new site staff*. The gap to rank 2 (0.39) is wide on purpose, so rough wording does not flip it.

### 3.4 The simulated expert (`expert.py`)

| # | Rule |
|---|---|
| E1 | Played by `CallType.EXPERT` through `llm.py`, so it uses the `eval-expert` deployment (gpt-5.4-mini) with the client's budgets, retries, cache and log line |
| E2 | **Sees:** `profile`, `behaviour`, the hidden truth rendered as plain facts ("your process starts when…"), the `disclose` rules, `truth.week`, which documents it has uploaded so far, and the conversation (agent and own messages, fenced as data) |
| E3 | **Never sees:** the profile panel (`profile`, `fieldViews`, `score`, `finish` of `SessionOut`), the report, `expected`, `stale`, scores, or anything the runner computes |
| E4 | Prompt rules: reply as this person in one short chat message; **like a busy person: one to three short sentences, about 15 to 45 words, even to an open "walk me through" question** (A2, review 2026-11-20); a question that asks several things gets **the main parts in a few words each**, the rest is left for the agent to ask again; a `cooperative` persona may cover several parts of an open question briefly, a `difficult` one answers only one or two parts and never volunteers; only facts from the persona file; for a yes/no confirmation reply with a plain "yes" or "no" plus the correction; for a document conflict reply "mine", "the document's", "both" or own words, following the truth; never mention being simulated |
| E5 | Output: plain text, 1–600 characters and at most 60 words (`MAX_WORDS`; code keeps whole sentences up to 60 words, A2). Empty or failed after the client's retries → the persona run ends as `error` (not a product failure) |
| E6 | **Answered by code, no EXPERT call:** a cluster proposal (`clusterProposal` not null) → `"yes"` when its code equals `expected.cluster`, else `"no"`. Everything else goes to the model |
| E7 | Capped: at most `HARD_CAP` = 80 expert messages per persona (§3.9a safety net; was 60 before the 2026-11-20 amendment) |
| E8 | *(review 2026-11-20)* **The persona presses *Finish*.** Prompt: when the agent says the map is ready and *Finish* can be pressed, and nothing it said is wrong or missing, reply the single word `FINISH`. The runner then presses *Finish* (not a message). `FINISH` while `finish.ready` is false is sent as "yes". A real employee presses the button when invited; before this rule the runner kept answering review summaries |

### 3.5 The runner (`play.py`, `driver.py`, `run.py`)

**Modes.**

| Mode | How | Measures |
|---|---|---|
| In-process (default) | `create_app(settings)` with `STORE=memory`, stage `local`, wired as `tests/api/conftest.py` does; lifespan run; calls through `httpx.AsyncClient(ASGITransport(app))`. Settings for the run: `RATE_LIMIT_PER_VISITOR` and `RATE_LIMIT_PER_IP` `10000/minute`, `DAILY_TOKEN_BUDGET` 0 | Everything (§3.7–§3.10); stored session read from the memory store; `llm_call` and `interview_turn` log lines captured by a logging handler |
| URL (`--url https://…`) | Real HTTP against a running app | Fields, routes, behaviour from the wire; **cost and steering shown as n/a** (not on the wire) |

**One persona, step by step.**

1. New visitor key per persona run (22 random URL-safe characters); `POST /api/sessions` with `displayName = persona.id`.
2. Loop until *Finish* or `HARD_CAP`: upload any document now due (`POST …/documents`, the reply is the agent's next message); else get the expert's reply (§3.4) and `POST …/messages`. Record per turn: wall time, phase, `finish`, focus key and its `asks`, which app calls hit the cache.
3. **Snapshot after every step.** After every expert message and every upload the runner calls `GET /api/sessions/{id}` (in-process: also the stored session) and keeps a **snapshot**: `{n (expert messages so far), event (message | upload), phase, score.value, filledPoints, totalPoints, finish, profile, fieldViews}`. The snapshot is taken after the response, so it is the state the next question was built from. Snapshots feed the progress curve, wasted turns and plateaus (§3.9a). The GET is not an expert call and is not counted as a message.
4. **When to press *Finish*:** `finish.ready` is true and either the persona replies `FINISH` (E8), or the phase is `review` and the expert has given 3 **short** review answers (≤ 6 words; a correction does not count, review 2026-11-20), or the agent's last message has no question, or the next message would pass `HARD_CAP`. `POST …/finish`; a 409 `map_incomplete` is recorded and the loop goes on.
5. After *Finish*: `GET …/report` and `GET …/report.pdf`.
6. Write the artefacts (§3.6), then score (§3.7–§3.10).

**Run.** Personas run in parallel, at most `--parallel` (default 2) at once. One persona failing (error, timeout) never stops the others.

**Rate limits and budget (spec 16) are never hit:**

| Mode | Rule |
|---|---|
| In-process | Limits raised as above; nothing to pace |
| URL | Each persona has its own key; at most 20 calls a minute per key and 60 a minute in total (a pacer waits); on a 429 the runner waits `retry-after` (else 30 s) once, then ends that persona as `rate_limited`. A run that would need more tokens than `--max-tokens` (default 3 M) stops before the next persona starts |

**Caches.** The app and EXPERT calls use the disk cache as in any local run (`--fresh` turns it off for them). The JUDGE always uses it. A turn counts for timing only when none of its app calls was a cache hit.

**Commands.**

| Command | Does |
|---|---|
| `make eval` | All personas, in-process, calibration first; writes the run and updates `eval/reports/latest.*` |
| `make eval QUICK=1` | Personas with `quick: true` (2); never updates `latest.*` |
| `make eval FRESH=1` | No cache for app and EXPERT calls (timing runs) |
| `make eval URL=https://…` | URL mode |
| `make eval SEED=1` | After the run, seed Cosmos (§3.12). Only with this flag |
| `make test-eval` | `eval/tests` (no model); part of `make test` |

**Exit code:** 0 every target met; 1 a target missed, a session failed (§3.9a hard cap) or the judge failed calibration; 2 the run could not start (bad persona, bad config, no model endpoint).

### 3.6 Artefacts per run

Under `eval/runs/<YYYYMMDD-HHMMSS>/` (git-ignored, may hold model text):

| File | Content |
|---|---|
| `run.json` | Git commit, settings (deployments, cache on/off, mode), persona ids and versions, start and end time |
| `calibration.json` | Judge agreement, per pair result (§3.8) |
| `<persona>/transcript.md` and `.json` | Every message, in order, with turn number and phase |
| `<persona>/turns.jsonl` | One line per turn: wall ms, phase, focus, asks, finish state, cache hits, tokens |
| `<persona>/snapshots.jsonl` | One snapshot per expert message and upload (§3.5 item 3) |
| `<persona>/curve.json` | The progress curve: per expert message, report quality and the product score (§3.9a) |
| `<persona>/session.json` | Final `SessionOut` (both modes) and the stored session (in-process) |
| `<persona>/report.json`, `report.pdf` | The report and the PDF after *Finish* (absent if never finished) |
| `<persona>/score.json` | Every scored field with hidden value, captured value, method (`code` / `judge`), result and reason |
| `scorecard.md`, `scorecard.json` | §3.11 |

### 3.7 Report quality: field scoring (code first)

1. **What is scored:** the profile at *Finish* (or at the last turn if never finished): P01–P16 and every scored step leaf of every true step (S01–S11, S13; read from the registry, weight > 0). S12 (weight 0) is not scored. A value counts as captured whatever its status (complete, proposed); values still `proposed` are also counted in `proposed_at_finish`.
2. **Step matching by content** *(A1, product owner, review 2026-11-20; was: by position, else by shared name words)*. A step's content is the normalised words (length > 2, no stop words) of its name, activities and data in / out, plus its systems (aliases folded to one name). A true step's **distinctive content** is the part no other true step has (all of it when nothing is distinctive). **Match** (true *i*, captured *j*) = share of true step *i*'s distinctive content found in captured step *j*. Rule, all code: (a) one to one, the pairing with the highest total match where each pair has match ≥ **0.25** (`MIN_STEP_MATCH`, assumption); ties go to the pairing closest in position; (b) equal counts: a true step still unpaired takes the captured step at its own position when that one is free; (c) **merge:** a true step still unpaired joins the captured step that covers it best (match ≥ 0.25), so one product step may cover several true steps; (d) anything left is **missing**. The judge is not used: on the real runs code alone gave clear matches (0.7–1.0 against 0–0.17); a judge tiebreak is added only if a run shows a tie code cannot break.
   - **Merged step:** each covered true step is scored against the merged step's cells (fair partial credit); list cells (systems, roles, approvals) do not count the merged step's extra items against it.
   - **Missing step:** every scored cell is wrong, **including `disclose: never` cells** (no honesty credit for a step the product never captured; before the review a missing step's never-disclosed effort counted as correct).
   - The same matching is used for step fit and route (§3.9): the report's row *k* is the profile's step *k*.
3. **Normalise** (code): lower case, trim, collapse spaces, drop end punctuation, drop a leading "the", a trailing plural "s".
4. **Method per field:**

| Field | Method | Correct when |
|---|---|---|
| P03 region, P05 cluster, P16 step count | Code | Equal (P05 by code; P16 as a number) |
| P10 volume | Code | Runs a year (`value_parse.runs_per_year`) within ±10 % of the truth |
| P12 time today, P13 target, S08 effort | Code, then judge | Both parse (`parse_duration`, `parse_frequency`): within ±25 % (duration) and ±10 % (frequency), same unit family. Either side does not parse: judge |
| P14 same way everywhere | Code + judge | `same` equal; `differences` (if the truth has one) by judge |
| P11 owner, S05 step owner, S04 roles, S10 approver roles | Code, then judge | Normalised equal or an alias; for lists every true item matched and at most one extra. Unmatched pairs go to the judge one item at a time |
| S06 systems | Code only | As roles; aliases are the only fuzziness (a system name is a name) |
| S13 rules or judgement *(amended 2026-11-20)* | Code | `kind` equal (`rules`, `judgement`, `mix`); the evidence words are not scored |
| P15, S04, S10, S11 "none" | Code | Truth none ⇔ captured none row |
| Text (P01, P02, P04, P06–P09, S01–S03, S07, S09, S11 descriptions) | Judge | `same_meaning: true` (§3.8). Lists are judged as one joined value: does the captured list cover the main points of the hidden one |
| Missing captured value | — | Wrong (no judge call) |

5. **Report quality (the headline number)** = correct fields ÷ **all fields in the hidden truth** (P01–P16 plus every scored step leaf of every true step). A missing value is wrong; a true step the product never captured counts every scored cell (12) wrong; nothing is left out. Per persona and pooled (sum of correct ÷ sum of truth fields). Example: p01, 5 steps → 16 + 5 × 12 = **76 truth fields** (71 before S13). *Amended 2026-11-20:* report only; the target moved to Tier A + core (§3.9b).
6. **No invention** (fields with `disclose: never`): such a field is **correct** when the captured value is empty, "none identified", or words without a number (the honest answer to a refusal), and **wrong** when it holds a digit or a parsed number; each wrong one is also counted as an `invented_value`. Target 0.
7. **The expert's own role** *(review 2026-11-20)*: in S04 roles, the expert's own role (P02, its aliases, "I", "me") is implied on both sides. The step walk asks "who besides you is involved", so "nobody else" (the none row) is the right answer for a step only the expert does; other roles must still all be captured.

**Worked example (p01, from a real-shaped run).**

| Field | Hidden | Captured | Method | Result |
|---|---|---|---|---|
| P10 volume | `{count: 1, period: month}` | `{raw: "once a month"}` | code: 12 = 12 | ✓ |
| P12 time today | `{value: 5, unit: working days}` | `{qualitative: "most of the first week"}` | judge: same meaning? | ✓ "about five working days" |
| P16 steps | 5 | 5 | code | ✓ |
| S06 systems, step 2 | `[Excel, ledger system]` | `[excel, "the ledger"]` | code: alias `the ledger` → ledger system | ✓ |
| S08 effort, step 4 | `{duration: 2 hours, frequency: monthly}` | `{duration: "half a day", frequency: "monthly"}` | code: 4 h vs 2 h, outside ±25 % | ✗ |
| S09 pain, step 4 | `[some site managers answer only after three reminders]` | `[waiting for site managers]` | judge | ✓ |

### 3.8 The judge (`judge.py`, `calibrate.py`)

| # | Rule |
|---|---|
| J1 | **Narrow:** one pair at a time: field label, the field's rule (registry), hidden value, captured value. It **never sees** the conversation, the persona file, the report or other fields |
| J2 | Output (strict schema, Pydantic): `{same_meaning: bool, reason: str ≤ 200}`. Invalid twice → the field is `judge_error`, counted as wrong and listed |
| J3 | `CallType.JUDGE` through `llm.py`, deployment `azure_openai_judge_deployment` = `app-chat` (gpt-5.6-sol; **decided**). The runner refuses to start (exit 2) when it equals the EXPERT deployment |
| J4 | **Fixed prompt**, versioned (`JUDGE_PROMPT_VERSION`, `judge-v2` since the review of 2026-11-20), stored in the run's `run.json`. Rules in the prompt: same facts and numbers = same meaning; different wording is fine; a qualifier word dropped or added that names the same thing is fine (v2); a missing or extra key fact, a different number, or a negation = not the same |
| J5 | **Deterministic as far as the client allows:** the model's default temperature; `llm.py` sends none (spec 11; **decided**). Repeatability comes from the fixed prompt, the strict schema and the **disk cache**, always on for JUDGE: the same pair is never judged twice |
| J6 | **Calibration first:** `eval/judge_calibration.yaml` holds about 30 hand-labelled pairs `{field, hidden, captured, label, note}`: at least 12 true, 12 false, including hard cases (a number off by one, a negation, a partial list, a synonym, a different unit). The judge is run on all of them before scoring |
| J7 | **Agreement** = pairs where the judge equals the label ÷ all pairs. Below 90 %: the judge **fails**; the scorecard marks every judged result "not trusted", shows code-only report quality beside the total, and the run exits 1 |

### 3.9 Labels and behaviour (code)

| Metric | How | Target |
|---|---|---|
| Cluster | `profile.process.cluster.code == expected.cluster` | 100 % of personas |
| Scope | `session.scope.verdict == expected.scope` at *Finish* | 100 % |
| Steering | In-process: `session.steering.recommended_id` names `expected.steering.recommended` (normalised containment, either way); P04 names `chosen`; `GET /api/ideas` holds every name in `ideas`. `expected.steering: null` → `steering.status` is `off` | 100 % (assumption) |
| Step fit | Aligned step's `fit` ∈ expected `fit` | ≥ 70 % of steps (assumption, eval-only) |
| Step route | Aligned step's `route_id` ∈ expected `route` | ≥ 70 % of steps (assumption, eval-only) |
| Loops hit | Any process field with `asks` > 5, any cell with `asks` > 3 (max over all turns, from `fieldViews`), or the same normalised agent message 3 times in a row | **0** (product §8) |
| Repeated questions | Agent messages equal (normalised) to an earlier agent message | ≤ 2 per session (assumption) |
| Never finished | *Finish* not reached within `HARD_CAP`, or never `ready` (a failed session, §3.9a) | **0** |
| Turn time | Wall time of `POST …/messages` on uncached turns: median and max | Median < 10 s, max < 150 s |
| *Finish* time | Wall time of `POST …/finish` (uncached) | < 30 s |
| Fallback questions | `fallback_used` in the turn log | Report only |
| Document proposals | Confirmed vs rejected (turn log `proposals_confirmed`, `proposals_rejected`) and `proposed_at_finish` | Report only |
| Conflicts | `DocumentReport.conflicts` summed | ≥ `expected.min_conflicts` |
| Stale kept | A `stale` entry whose `doc_value` equals the captured value at *Finish* (normalised; judge for text) | **0** |
| Invented values | §3.7 item 6 | **0** |

A target with no data in this run (for example time in a fully cached run, steering in URL mode) shows `n/a` and does not fail the run.

### 3.9a Efficiency: quality weighed against messages (code)

An **expert message** is one `POST …/messages` (code-answered replies of E6 included; uploads, *Finish*, snapshots and confirm buttons are not messages).

| Metric | Definition | Target |
|---|---|---|
| Expert messages to *Finish* | Expert messages sent before *Finish* succeeded | **Report only** (amended 2026-11-20; was ≤ 30 / ≤ 40) |
| **Hard cap (safety net)** | `HARD_CAP` = 80 (amended 2026-11-20; was 60). The runner sends no 81st message. More than 80 needed, or *Finish* never reached → the session is **failed** and the **run fails** (exit 1), whatever the other numbers | 0 failed sessions |
| Efficiency | Correct fields at *Finish* ÷ expert messages to *Finish* (for p01: 61 correct in 28 messages = 2.18). Failed sessions show `n/a` | No target; tracked run over run with deltas |
| Wasted turns | Expert messages after which **no field changed** (no field in the snapshot's `profile`/`fieldViews` differs in value or status from the snapshot before) **and the phase did not move**. Not counted: confirmation answers (the message is a code-answered reply of E6, or, after normalising, ≤ 6 words that are all in the yes / no / conflict word lists of `language.yaml`) | ≤ 3 per session |
| Plateau | 5 expert messages in a row with no increase in the product score (`score.value`) between their snapshots. Each plateau is flagged with its message numbers | 0 (flag) |
| Progress curve | Per expert message *n*: report quality (§3.7 item 5, scored on snapshot *n*'s profile) and the product score `score.value` (completeness, spec 13) | Shown, no target |

**Progress curve in the scorecard.** JSON: `curve: [{n, quality, score, phase}]` per persona. Markdown: one line per persona with two ASCII sparklines (`▁▂▃▄▅▆▇█`, one character per message, scaled 0–100 %) and the values at messages 10, 20, 30 and at *Finish*:

```
p01-cooperative  quality ▁▁▂▂▃▄▄▅▅▆▆▆▇▇▇▇▇▇▇▇▇██████  10: 28%  20: 61%  28 (Finish): 86%
                 score   ▁▁▁▂▂▃▃▄▄▅▅▆▆▆▇▇▇▇▇▇▇▇█████  10: 22%  20: 63%  28 (Finish): 92%
```

Scoring every snapshot calls the judge only for (field, captured value) pairs not judged before; the judge cache (J5) makes a value that stays the same free on later snapshots.

### 3.9b Employee time, detail burden and the quality split (amended 2026-11-20)

Approved by the product owner on 2026-11-20: what costs the employee is **time** and being asked for **details that add little**, not the count of messages. All four numbers are computed by code from the run's transcript, turn log and field scores; none calls a model.

**1. Employee time per session (the headline).** An estimate of the minutes a real employee would spend, from the words on the screen:

| Part | Formula | Constant (`eval/employee_time.yaml`, all **assumptions**) |
|---|---|---|
| Reading | Σ over agent messages: words ÷ reading speed | 230 words a minute |
| Typing | Σ over expert messages: words ÷ typing speed | 40 words a minute |
| Thinking | Per expert message: a fixed think time; a short answer (≤ 3 words, "yes", "no", "mine") gets the short think time | 8 s; 3 s for ≤ 3 words |
| Uploads | Per uploaded document | 20 s |

Words = whitespace-separated tokens. Code-answered replies (E6) count as expert messages. Target **≤ 20 min per session** (product: a 20–30 minute interview; the estimate counts reading, typing and thinking only), all personas. The scorecard shows minutes per persona (with reading, typing, thinking and upload parts), the **average answer length in words** (expert words ÷ expert messages; A2, report only) and the delta to the last full run.

*Example:* 30 agent messages of 46 words (1 380 words → 6.0 min), 28 expert messages of 12 words (336 words → 8.4 min), 28 × 8 s thinking (3.7 min), no upload → **18.1 min** ✓.

**2. Field value tiers (`eval/tiers.yaml`).** From the approved short step walk (spec 14, being changed in parallel):

| Tier | Step fields | Meaning |
|---|---|---|
| A | S01 name, S03 activities, S06 systems, S07 data in/out, S08 effort, S09 pain points, S11 exceptions, S13 rules or judgement (`decision_type`) | What the assessment needs |
| B | S04 roles, S10 approvals | Useful |
| C | S02 goal, S05 step owner, S12 hand-over | **Low value** |

Process fields: P13 target is **low value**; the others are normal. **Process core** (scored with Tier A, an assumption): P04 name, P05 cluster, P06 trigger, P07 end result, P09 business pain, P10 volume, P12 time today, P16 step count. The tier file maps registry leaf keys, so the S13 key is changed in one place; a test fails when a registry step leaf has no tier.

**3. Detail burden.** A **question** is an agent turn whose turn log (`interview_turn.focus`, the same keys the product stores in `last_question.focus`) names at least one field; turns with an empty focus (document proposals, conflicts, widening) are not counted. A question is **low-value** when every key in its focus is low value (Tier C cell or P13). Detail burden = low-value questions ÷ questions. Target **≤ 15 %**. `n/a` when the turn log is not available (URL mode). The fixed opening question (P01) is not in the turn log and is not counted.

**4. Quality split.** The §3.7 field results split in two: **Tier A + process core** (target **≥ 85 %**, `cooperative` personas; reported for `difficult`) and **the rest** (report only). The overall report quality (§3.7 item 5) is still shown, now **report only**: the short walk does not ask Tier C on purpose.

**5. Assessment match.** Step fit and step route vs `expected.routes` (§3.9), each ≥ 70 %, now shown in the headline.

**Scorecard order:** employee time, detail burden, Tier A + core quality, assessment match, then overall quality, messages to *Finish*, efficiency and the rest, each with its delta.

### 3.10 Tokens and cost

1. Tokens per call type and deployment come from the captured `llm_call` lines (in-process), split into **app** (every call type but EXPERT and JUDGE), **expert** and **judge**. Cache hits cost 0 and are counted apart.
2. € = tokens × `eval/prices.yaml` (`{deployment: {in: €/M, out: €/M}}`). The prices are an **assumption** to fill from the price list; a deployment missing from the file shows tokens only.
3. Target: app cost per finished session < €0.50 (product §8). The product target assumes a small model; `app-chat` is gpt-5.6-sol, so the scorecard prints the deployment beside the number.

### 3.11 The scorecard (`scorecard.py`)

`scorecard.json` (schema `Scorecard`, Pydantic) and `scorecard.md` (rendered from it, no extra facts).

| Section | Content |
|---|---|
| Header | Run id, commit, mode, cache, deployments, judge agreement, **PASS / FAIL** with the reason (target missed, failed session, judge) |
| Headline (amended 2026-11-20) | Per persona and pooled: **employee time (min)**, **detail burden**, **Tier A + core quality**, **assessment match** (fit, route), each with its delta; failed sessions in bold |
| Also reported | Overall report quality, the rest's quality, messages to *Finish*, efficiency, wasted turns, plateaus, with deltas |
| Targets | One row per §8, §3.9, §3.9a and §3.9b target, headline targets first: value, target, ✓ / ✗ / n/a, delta |
| Per persona | Report quality (code / judged / total), cluster, scope, steering, fit, route, messages, wasted turns, plateaus, loops, repeats, finished, median and max turn time, *Finish* time, tokens, € |
| Progress curves | §3.9a sparklines |
| Total | Pooled report quality, counts summed, times over all uncached turns, € per finished session (mean) |
| Worst fields | The 10 wrong fields with hidden vs captured (from `score.json`) |
| Deltas | Against `eval/reports/latest.json`: each number with `+/-`; a persona with another `version` shows "new" |

Only a full run (not `QUICK`, not `URL`) replaces `eval/reports/latest.*`.

### 3.12 Seeding the demo data (`seed.py`)

1. Only with `--seed-cosmos` (`make eval SEED=1`), only in-process, only after the run.
2. Seeds personas with `seed: true` that finished (not failed) with report quality ≥ 85 % and no loop.
3. Writes the stored session to Cosmos (`STORE=cosmos` settings from the environment) under the owner `sha256(EVAL_SEED_VISITOR_KEY)` with the fixed id `eval-<persona id>`; an existing one is replaced, so seeding twice gives one copy. Ideas are not seeded.
4. **Marked as simulated.** The seeded session has `simulated: true`. Why a field and not a name prefix: the workspace never shows `displayName` (spec 21 AC-21.11), and a prefix on the process name would leak into the report and the PDF. The field is the least invasive mark that the specialist actually sees. Contract change (lead to apply): spec 12 `Session.simulated: bool = False` (storage only, never settable through any expert route; old documents load as `false`); spec 21 session list and session view carry `simulated`; spec 23 part 3 shows a "Simulated" tag on that row and on the session view. The overview (F-18) shows the same tag when built.
5. Prints what it wrote (ids and counts); nothing else in Cosmos is touched.

### 3.13 Cost and time estimate (assumption)

| Item | Per persona | Full run (4) | Quick (2) |
|---|---|---|---|
| Expert messages | about 35 (targets 30 / 40; cap 60) | 140 | 70 |
| App tokens (2–3 calls a turn, 4 on *Finish*, 1 per document) | about 0.6 M in, 0.1 M out | 2.4 M in, 0.4 M out | 1.2 M in, 0.2 M out |
| EXPERT tokens (mini) | about 0.25 M in, 0.02 M out | 1 M, 0.08 M | 0.5 M, 0.04 M |
| JUDGE tokens (final profile and every snapshot, distinct pairs only) | about 80 k in, 12 k out (≈ 0 on re-runs) | 0.32 M, 0.05 M | 0.16 M, 0.02 M |
| € at assumed prices (app €1.25 / €10 per M) | about €1.9 | **about €8** | about €4 |
| Wall time (≈ 12 s app + 3 s expert a turn, *Finish* 30 s) | about 10 min | **about 20 min** at `--parallel 2` | about 10 min |

Re-runs with no prompt change are mostly cache hits: near €0 and a few minutes.

## 4. Interfaces

```python
# eval/evalkit/persona.py
HARD_CAP = 80   # safety net (amended 2026-11-20)
class Persona(BaseModel): id: str; version: int; quick: bool; seed: bool; kind: Literal["cooperative", "difficult"]
    profile: str; behaviour: list[str]; truth: Truth; documents: list[PersonaDocument]; expected: Expected
def load_personas(folder: Path, *, quick: bool, registry, taxonomy, catalogue) -> list[Persona]   # raises PersonaError

# eval/evalkit/expert.py
async def expert_reply(persona: Persona, transcript: Sequence[Turn], uploaded: Sequence[str], llm: LLM) -> str
def code_reply(persona: Persona, session_out: Mapping[str, Any]) -> str | None     # E6; None = ask the model

# eval/evalkit/driver.py
class Driver(Protocol):
    async def create(self, display_name: str) -> dict: ...
    async def send(self, session_id: str, text: str) -> tuple[dict, float]: ...      # (TurnOut, seconds)
    async def upload(self, session_id: str, path: Path) -> tuple[dict, float]: ...
    async def finish(self, session_id: str) -> tuple[int, dict, float]: ...          # (status, body, seconds)
    async def report(self, session_id: str) -> tuple[dict, bytes]: ...
    async def stored(self, session_id: str) -> dict | None: ...                      # in-process only
def in_process_driver(settings: Settings, llm: LLM) -> Driver
def url_driver(base_url: str, *, pacer: Pacer) -> Driver

# eval/evalkit/play.py
async def play(persona: Persona, driver: Driver, expert_llm: LLM, out_dir: Path) -> PersonaRun

# eval/evalkit/score_fields.py, score_labels.py, score_behaviour.py (pure)
def align_steps(truth_steps, captured_steps, groups=()) -> list[tuple[int, int | None]]   # by content (§3.7 item 2); a captured step may repeat (merge)
def score_fields(persona: Persona, profile: Mapping[str, Any], judge: Judge) -> FieldScores   # judge called only for §3.7 judge rows
def score_labels(persona: Persona, run: PersonaRun) -> LabelScores
def score_behaviour(run: PersonaRun, prices: Prices) -> BehaviourScores

# eval/evalkit/score_efficiency.py (pure)
def score_efficiency(persona: Persona, snapshots: Sequence[Snapshot], correct_at_finish: int | None,
                     words: YesNoWords) -> EfficiencyScores   # messages, efficiency, wasted, plateaus, failed
def progress_curve(persona: Persona, snapshots: Sequence[Snapshot], judge: Judge) -> list[CurvePoint]   # {n, quality, score, phase}
def sparkline(values: Sequence[float]) -> str

# eval/evalkit/score_employee.py (pure; amended 2026-11-20)
def load_time_model(path: Path) -> TimeModel; def load_tiers(path: Path) -> Tiers
def employee_time(transcript: Sequence[Mapping], uploads: int, model: TimeModel) -> EmployeeTime   # minutes and parts
def detail_burden(turns: Sequence[Mapping], tiers: Tiers) -> DetailBurden | None                   # None = no turn log
def quality_split(results: Sequence[FieldResult], tiers: Tiers) -> QualitySplit                    # Tier A + core vs rest

# eval/evalkit/judge.py
JUDGE_PROMPT_VERSION = "judge-v2"
class JudgeOut(BaseModel): same_meaning: bool; reason: str = Field(max_length=200)
class Judge: async def same(self, label: str, rule: str, hidden: str, captured: str) -> JudgeOut
def calibrate(judge: Judge, pairs: list[CalibrationPair]) -> Calibration   # agreement, passed (≥ 0.90)

# eval/evalkit/scorecard.py
def build_scorecard(runs: list[PersonaScore], calibration: Calibration, previous: Scorecard | None) -> Scorecard
def render_markdown(card: Scorecard) -> str

# eval/run.py
# python -m eval.run [--quick] [--fresh] [--url URL] [--parallel N] [--persona ID]... [--seed-cosmos] [--calibrate-only]
```

## 5. Implications

- **Spec 11 / `llm.py` (lead to apply):** `CallType.JUDGE`; settings `azure_openai_judge_deployment` (default `app-chat`) and `llm_max_tokens_judge` (default 2 000); `deployment_for` maps EXPERT → eval deployment, JUDGE → judge deployment, the rest → app deployment. Architecture §6.2 gains a JUDGE row ("evaluation only; on failure the field is `judge_error`").
- **Spec 10 / Makefile:** `eval` and `test-eval` targets (§3.5); `make test` runs `test-eval`; ruff and pyright cover `eval/`; `.gitignore` adds `eval/runs/`, `eval/.cache/`.
- **Other components:** none change behaviour. The runner relies on the wire shapes of specs 15, 17, 20 and on the log fields of specs 11 and 14; renaming one of those breaks the eval tests, which is intended.
- **Data:** one new optional storage field, `Session.simulated` (§3.12 item 4; contract change for specs 12, 21, 23). Nothing else.
- **Config:** none in `config/nig/`. `eval/prices.yaml` is evaluation data, not company config.
- **Security and privacy:** personas and documents are synthetic; no real names, no real companies. Run folders hold model text and stay out of git. The URL mode uses only expert routes with fresh visitor keys; it never uses a workspace code. The EXPERT reply goes through the same injection screen as any expert message (spec 15).
- **Cost and latency:** §3.13. A URL run spends the demo's daily token budget; `--max-tokens` guards it.

## 6. Acceptance criteria

| ID | Given / when / then |
|---|---|
| AC-24.1 | Given a persona file with an unknown registry key, a step count that differs from `truth.steps`, an unknown cluster, or a route id not in `solutions.yaml` (or not allowing any listed fit), when personas load, then the run stops with exit 2 and names the file and key, before any model call |
| AC-24.2 | The four personas of §3.3 load; `QUICK=1` selects exactly `p01-cooperative` and `p02-vague` |
| AC-24.3 | The EXPERT prompt holds the profile, behaviour, truth, disclose rules and the fenced conversation, and holds none of: `expected`, `stale`, `fieldViews`, `score`, `finish`, a profile key name (sentinel test) |
| AC-24.4 | With `clusterProposal.code` equal to `expected.cluster` the reply is `"yes"` with no EXPERT call; with another code it is `"no"` |
| AC-24.5 | A document with `at: {phase: steps}` is uploaded exactly once, on the first response whose phase is `steps`, before the next expert message; `{turn: n}` uploads before expert message n; `{start: true}` before the first |
| AC-24.6 | *Finish* is pressed only when `finish.ready` is true, after at most 3 review answers, or before the message that would pass `HARD_CAP`; a 409 is recorded and the loop continues; no *Finish* within `HARD_CAP` → `never_finished` |
| AC-24.7 | In-process runs use `STORE=memory`, raised rate limits and no daily budget; no request in a full fake run gets a 429 |
| AC-24.8 | URL mode sends at most 20 calls a minute per visitor key and 60 in total (pacer test with a fake clock); a 429 waits once, then ends that persona as `rate_limited` without stopping the others |
| AC-24.9 | Each persona run writes `transcript.md`, `transcript.json`, `turns.jsonl`, `session.json`, `score.json`, and, when finished, `report.json` and `report.pdf`, under `eval/runs/<timestamp>/<persona>/` |
| AC-24.10 | *(amended, review 2026-11-20)* `align_steps`: equal counts with no content signal pair by position; an unpaired true step scores every scored cell wrong (12 since S13) |
| AC-24.11 | Code scoring holds for the §3.7 worked example rows that use code: volume "once a month" vs `{1, month}` correct; effort "half a day" vs "2 hours" wrong; systems matched by alias; a list with two extra items wrong |
| AC-24.12 | The judge is called only for §3.7 judge rows and code non-matches; a missing captured value is wrong with no judge call |
| AC-24.13 | Report quality = correct ÷ all truth fields (76 for p01 since S13): a missing value and every cell of an uncaptured true step count wrong; a `disclose: never` field is correct when empty or words without a number, wrong (and one `invented_value`) when it holds a digit |
| AC-24.14 | The JUDGE request holds label, rule, hidden and captured value only (no transcript text: sentinel test); its output is validated by `JudgeOut`; two invalid replies → `judge_error`, counted wrong |
| AC-24.15 | The run refuses to start (exit 2) when the judge deployment equals the EXPERT deployment |
| AC-24.16 | The same pair judged twice makes one model call (cache); `JUDGE_PROMPT_VERSION` is in `run.json` |
| AC-24.17 | Calibration with a fake judge agreeing on 27 of 30 pairs passes (90 %); 26 of 30 fails, marks judged results "not trusted", shows code-only report quality and exits 1 |
| AC-24.18 | `judge_calibration.yaml` has 25–40 pairs, at least 12 labelled true and 12 false |
| AC-24.19 | Labels: cluster, scope, steering (recommended, chosen, ideas), fit and route are scored by code as §3.9; for p03 a stored `recommended_id` naming "onboarding new site staff" is a hit; for `expected.steering: null` a status other than `off` is a miss |
| AC-24.20 | Behaviour: a field with `asks` 6 is one loop; three equal agent messages in a row is one loop; turn times count only uncached turns; a run with no uncached turn shows time as `n/a` and does not fail |
| AC-24.21 | Cost: tokens from captured `llm_call` lines split into app, expert and judge; cache hits count 0 €; a deployment missing from `prices.yaml` shows tokens and `n/a` € |
| AC-24.22 | Stale check: for p04 a captured volume "twice a year" counts one `stale_kept` |
| AC-24.23 | The scorecard JSON validates against `Scorecard`; the Markdown is rendered from it; each target shows value, target, ✓/✗/n/a and the delta to `latest.json`; a persona with a new `version` shows "new" |
| AC-24.24 | Only a full in-process run replaces `eval/reports/latest.*`; `QUICK` and `URL` runs never do |
| AC-24.25 | Exit codes: 0 all targets met, 1 a target missed or calibration failed, 2 the run could not start |
| AC-24.26 | Seeding happens only with `--seed-cosmos`, only for `seed: true` personas that finished with report quality ≥ 85 % and no loop, under id `eval-<persona id>`, with `simulated: true`; ideas are not seeded; seeding twice leaves one copy (fake repository test) |
| AC-24.27 | One persona failing (EXPERT error, timeout) is marked `error` and the others still run and are scored |
| AC-24.28 | End to end with `FakeLLM` (scripted app calls, EXPERT and JUDGE): a 2-step tiny persona is played in-process, finishes, writes all artefacts and a scorecard with report quality 100 %, 0 loops, 0 wasted turns and a progress curve |
| AC-24.29 | `eval/` imports from the backend only `app.main`, `app.core.settings`, `app.services.store.memory`, `app.services.store.cosmos` (seed only), `process_discovery.llm`, `process_discovery.fake_llm`, `process_discovery.domain` (registry, `value_parse`) (ast test) |
| AC-24.30 | After every expert message and every upload the runner calls `GET /api/sessions/{id}` and writes one snapshot (`n`, event, phase, score, finish, profile, fieldViews) to `snapshots.jsonl`; the GET is not counted as a message |
| AC-24.31 | Messages to *Finish* count `POST …/messages` only (code-answered replies included; uploads, *Finish*, snapshots excluded); *amended 2026-11-20:* shown with their delta, no target row |
| AC-24.32 | Hard cap (*amended 2026-11-20:* 80, a safety net): the runner never sends an 81st message; a persona that needs more, or never reaches *Finish*, is `failed`, the scorecard says FAIL with that reason and the run exits 1 even when every other target is met |
| AC-24.33 | Efficiency = correct fields at *Finish* ÷ messages to *Finish* (61 and 28 → 2.18); `n/a` for a failed session; shown with its delta to `latest.json` |
| AC-24.34 | Wasted turns: a message whose next snapshot has the same profile values, the same field statuses and the same phase counts 1; a short "yes", "no", "mine" or a code-answered cluster reply never counts; 4 wasted turns in a session is ✗ |
| AC-24.35 | Plateau: scores 0.40, 0.40, 0.40, 0.40, 0.40, 0.40 over six messages (five without a gain) is one plateau flagged with its message numbers; any gain inside the window resets it |
| AC-24.36 | Progress curve: `curve.json` holds one point per message with report quality and `score.value`; the Markdown shows two sparklines per persona and the values at 10, 20, 30 and *Finish*; a value judged on an earlier snapshot is not sent to the judge again |
| AC-24.37 | *(amended 2026-11-20)* Employee time from a fixed transcript: 2 agent messages of 230 words (2 min reading), 2 expert messages of 40 words (2 min typing) and 1 of "yes" (1 word: 1.5 s typing, 3 s think), 2 × 8 s think and 1 upload (20 s) → 4 min + (1.5 + 19 + 20) s = 4.675 min; the constants come from `eval/employee_time.yaml` |
| AC-24.38 | *(amended)* Time target: ≤ 20 min is ✓, 20.1 min is ✗ and fails the run; the scorecard shows minutes per persona with the delta to `latest.json` |
| AC-24.39 | *(amended)* Detail burden from a fixed turn log: focus `[…substeps[1].owner]` and `[process.target_metric]` are low-value, `[…substeps[1].goal, …substeps[1].systems]` and `[…substeps[2].name]` are not, an empty focus is not a question; 2 of 4 questions → 50 % ✗; ≤ 15 % ✓; no turn log → `n/a` |
| AC-24.40 | *(amended)* `eval/tiers.yaml` gives every registry step leaf a tier, and holds no other step key (S13 is `decision_type`) |
| AC-24.41 | *(amended)* Quality split from fixed field results: Tier A cells and process core count in the first share, Tier B / C cells and other process fields in the rest; first share ≥ 85 % is ✓ for `cooperative`, reported only for `difficult`; overall quality has no target row |
| AC-24.42 | *(amended)* The scorecard headline lists employee time, detail burden, Tier A + core quality and fit / route before overall quality and messages; target rows come in the same order |
| AC-24.43 | *(amended; review 2026-11-20)* The EXPERT prompt tells the persona to answer the main parts of a grouped question; a `cooperative` persona's prompt allows covering several parts of an open question briefly, a `difficult` one's forbids volunteering |
| AC-24.44 | *(A1)* Steps are matched by content: for the four triage steps, a captured "First pass" (open the ticket, read the description, ticketing system) pairs with true step 1 "Read the new ticket" although no name word is shared; "Check the unassigned ones" pairs with step 4; steps 2 and 3 are missing. Renamed and reordered captured steps pair with their content |
| AC-24.45 | *(A1)* A captured step holding the content of true steps 2 and 3 covers both; each is scored against its cells, and its extra list items are not held against either |
| AC-24.46 | A true step covered by no captured step is wrong in every cell, including `disclose: never` cells |
| AC-24.47 | In S04 roles the expert's own role ("Cost controller", "I", "me") is implied: a none row matches a true list of only the expert; another true role still has to be captured |
| AC-24.48 | *(A2)* The EXPERT prompt asks for one to three short sentences, about 15 to 45 words; a reply over 60 words is cut to whole sentences within 60 (a first sentence over 60 words is cut at 60); `EmployeeTime.avg_expert_words` is in the scorecard JSON and the headline shows "Avg answer words"; in the fake end-to-end run every expert message is ≤ 45 words |
| AC-24.49 | The EXPERT prompt holds the `FINISH` rule (E8); a `FINISH` reply with `finish.ready` presses *Finish* and sends no message; before ready it is sent as "yes"; review corrections (> 6 words) do not count towards the 3 review answers |
| AC-24.50 | Fit and route use the content match on the profile's steps; a report row of a product step that merges true steps 1 and 2 counts its fit and route for both |

## 7. Test plan

All in `eval/tests/`, no model, run by `make test-eval`. Fixed inputs: small hand-written profiles and persona files in `eval/tests/fixtures/`.

| Test file | Covers |
|---|---|
| `test_persona.py` | AC-24.1, 24.2, 24.18 (loader, validation against registry, taxonomy, catalogue; calibration file shape) |
| `test_expert.py` | AC-24.3, 24.4 (prompt sentinels, code replies) |
| `test_play.py` | AC-24.5, 24.6, 24.9, 24.27, 24.30 (fake driver: document timing, *Finish* rule, snapshots, artefacts, isolation of failures) |
| `test_driver.py` | AC-24.7, 24.8 (in-process limits; URL pacer with a fake clock and a fake transport returning 429) |
| `test_score_fields.py` | AC-24.10–24.13 (alignment, code rows, judge routing, report quality, invented values) |
| `test_judge.py` | AC-24.14–24.17 (request contents, schema, cache, deployment check, calibration threshold) |
| `test_score_labels.py`, `test_score_behaviour.py` | AC-24.19–24.22 |
| `test_scorecard.py` | AC-24.23–24.25 (schema, render, deltas, `latest` rule, exit codes) |
| `test_seed.py` | AC-24.26 (fake repository) |
| `test_score_efficiency.py` | AC-24.30–24.36 (fixed snapshot series: message counts, hard cap, efficiency, wasted turns, plateaus, curve, sparkline) |
| `test_e2e_fake.py` | AC-24.28 (tiny persona, `FakeLLM`, in-process app) |
| `test_imports.py` | AC-24.29 |
| `test_score_employee.py` | AC-24.37–24.41 (fixed transcripts and turn logs: time, burden, tiers file, quality split) |
| `test_scorecard.py`, `test_expert.py` | AC-24.42, AC-24.43 |
| `test_score_fields.py`, `test_score_labels.py` | AC-24.44 to AC-24.47, AC-24.50 (review 2026-11-20) |
| `test_expert.py`, `test_play.py`, `test_score_employee.py`, `test_scorecard.py`, `test_e2e_fake.py` | AC-24.48, AC-24.49 |

The first real run (`make eval QUICK=1`, then `make eval`) is the verification step; its scorecard goes into `eval/reports/` and the technical design.

## 8. Out of scope

- The four later personas (13 steps, switches language, contradicts self, gives a screenshot): new YAML files later, no runner change.
- Scoring the wording of questions, the opportunities text, the map or the readiness labels (beyond fit and route).
- Human ratings of the interview experience; A/B runs of two prompt versions in one run.
- Running in CI against a real model (CI runs `make test-eval` only).
- A web screen for scorecards (Markdown only).
- Measuring interview time in minutes for a human by the clock (product §8 row 1): the simulated expert's speed says nothing about it. *Amended 2026-11-20:* the estimate from words on the screen (§3.9b) replaces it; it is an estimate with assumed speeds, not a measurement.

## 9. Open questions

| # | Question | Decision or default |
|---|---|---|
| Q1 | Judge deployment | **Decided:** `app-chat` (gpt-5.6-sol), guarded by the calibration (≥ 90 %) |
| Q2 | Temperature for the judge | **Decided:** the model's default; `llm.py` sends none. Repeatability from the fixed prompt, strict schema and cache (J5) |
| Q3 | Prices per deployment for `prices.yaml` | Default: assumed €1.25 / €10 per M (app), €0.25 / €2 per M (mini), marked as assumption in the scorecard |
| Q4 | Eval-only targets: fit and route ≥ 70 %, repeated questions ≤ 2, steering 100 % | **Decided** as stated; tuned after the first full run |
| Q5 | Are seeded sessions marked as simulated? | **Decided:** yes, `Session.simulated: true`, shown as a "Simulated" tag in the workspace (§3.12 item 4) |
| Q6 | Press *Finish* as soon as ready, or let the review phase run? | **Decided:** up to 3 review answers, then *Finish* |
| Q7 | Persona documents as `.md` or `.docx`? | **Decided:** `.md`; one `.docx` comes with the later personas |
| Q8 | *(decided 2026-11-20, product owner)* Session-wide length | **Offer, never force:** at 40 expert messages the agent offers *Finish* and lists what is missing, and offers again every 10 messages; the employee may keep going. Product change recorded in spec 14 §3.18 (to build). The eval keeps its own hard cap, a safety net of 80 expert messages since 2026-11-20 (session counted as failed) |

## 10. Built: deviations and first run

| # | Deviation | Why |
|---|---|---|
| D1 | `score_fields`, `progress_curve` and `calibrate` are `async` | The judge is an async model call |
| D2 | `load_personas(folder, *, quick, company, documents_dir, only)`: one `Company` (codes, routes, regions, file types, yes / no words) read from `config/<company>/*.yaml` | `app.core.config` is not on the AC-24.29 import list |
| D3 | Judge rows whose two values are equal after normalising are decided by code (no judge call) | Code first; saves calls, same result |
| D4 | Stale check by code only (normalised equality or containment), no judge for text | Every `stale` value in the four personas is a short name or phrase |
| D5 | *Finish* rule: in the review phase, *Finish* after 3 review answers, or earlier when the agent's last message holds no question mark | Reading of Q6 "up to 3 review answers": the review may end before 3 |
| D6 | `create_app(settings, *, llm=None)` gains an optional client (shell change in `app/main.py`) | The scripted end-to-end test (AC-24.28) needs a fake model without importing the engine |
| D7 | `snapshots.jsonl` starts with one `start` snapshot (n = 0) | The first message's wasted-turn and plateau checks need a "before" state |
| D8 | `Driver` also has `get`, `ideas` and `last_call`; the in-process driver has `stored_model` (seeding) | Snapshots, the ideas check and per-call log lines |
| D9 | URL mode's `--max-tokens` guard uses an estimate of 1 M tokens per persona (§3.13) | App tokens are not on the wire |
| D10 | `run.json` commit comes from `GIT_COMMIT` (empty when unset) | The runner does not shell out to git |
| D11 | Plateaus show as "flag" and never fail the run | §3.9a: target "0 (flag)" |
| D12 | Scope, fit and route are `n/a` (not ✗) for a session that never reached *Finish* | There is no verdict or report to score; the failed session already fails the run |
| D13 | EXPERT and JUDGE replies are cached in `eval/.cache/llm` (git-ignored); the app's cache stays `backend/.cache/llm` | Keeps evaluation text out of the app cache |
| D14 | The "Simulated" tag is also shown inside the workspace session popup (Session tab) | §3.12 item 4: "on that row and on the session view" |
| D15 | *(review 2026-11-20)* `transcript.md` / `.json` label an expert message with the phase of the question it answered (snapshot *n − 1*), not the phase after it | The old label put each answer one phase late |
| D16 | *(review 2026-11-20)* D5 is kept and widened by E8: the persona's `FINISH` reply; only short review answers count towards the 3 | In the 16:50 run p02 named two missing steps in the review and the runner pressed *Finish* while the agent was asking about them |
| D17 | *(review 2026-11-20)* Persona files are version 3 (A2 changes how every persona answers, so deltas against version 2 show "new"); p01 step 1 also accepts `low-code-agent` | Catalogue: low-code-agent is chosen when "inputs are digital documents in a varying layout", which is p01's step 1 pain ("site cost reports arrive … in different formats") |
| D18 | *(review 2026-11-20)* Six calibration pairs added (36: 19 true, 17 false), taken from wording seen in the real runs | The 30 pairs did not hold a dropped qualifier ("site report" for "site cost report"), which the judge marked wrong in the 16:50 run |

**First run** (`make eval QUICK=1`, in process, real Azure, 2026-11-20, `eval/reports/quick-20261120-151619.*`): judge agreement 100 % (30/30). Both personas hit the hard cap of 60 messages without *Finish* (FAIL): the interview asks one step cell per message (about 11 messages per step), so a 5-step process needs more than 60. p01 report quality 76 % at message 60 (54/71), 2 wasted turns, 0 plateaus; p02 95 % (57/60), 3 wasted turns, 1 plateau, 0 invented values. Median turn 2.4-2.6 s, max 12 s; app cost about €0.38-0.40 per persona at the assumed prices. That run's scorecard was written before D12, so it shows scope, fit and route as ✗ for the unfinished sessions; a cached re-run gives the same numbers with them as n/a.


**Amendment built** (2026-11-20, §3.9b, AC-24.37 to AC-24.43): `eval/evalkit/score_employee.py`, `eval/employee_time.yaml`, `eval/tiers.yaml`; scorecard headline reordered; hard cap 80; expert prompt rules for grouped and open questions. `make test-eval` green; no live run yet (waits for the short step walk in the product). S13 landed as `decision_type`: the four personas carry it (version 2) and `eval/tiers.yaml` now matches the registry exactly (AC-24.40). Cell counts are read from the registry (`STEP_LEAVES`), not hard-coded.

**Second quick run, short step walk** (2026-11-20, in process, real Azure, `eval/runs/20261120-165033`; FAIL). Both personas reached *Finish* (p01 31 messages, p02 26). p01: 24.8 min (typing 16.3 of it), burden 7 %, Tier A + core 92 %, overall 83 %, fit 1/5, route 0/5, *Finish* 46.5 s. p02: 16.3 min, burden 13 %, Tier A + core 40 % (the product kept 2 steps for 4 true ones and no name word matched, so every cell of the true steps scored missing), fit / route 0/2. The report filled fit and route for step 1 only. Before (60-message run): p01 23.8 min, burden 18 %, Tier A 77 %; p02 31.3 min, burden 22 %, Tier A 94 %; neither reached *Finish*.

**Third quick run, after the review** (2026-11-20 21:29, in process, real Azure, `eval/runs/20261120-212950`; FAIL on employee time and *Finish* time, both product). Judge-v2 agreement 100 % (36/36). Both personas pressed *Finish* themselves (E8). Answers 19.1 / 16.3 words on average (max 48 / 39; before 81 / 51). p02 this time captured all 4 steps.

| Persona | Run | Employee min | Detail burden | Tier A + core | Overall | Avg answer words | Messages | *Finish* reached | Fit / route | *Finish* s | App € |
|---|---|---|---|---|---|---|---|---|---|---|---|
| p01 | 16:50 | 24.8 | 7 % (2/28) | 92 % (44/48) | 83 % (63/76) | 21.0 | 31 | yes | 1/5 · 0/5 | 46.5 | 0.35 |
| p01 | 21:29 | 27.1 | 10 % (3/31) | 88 % (42/48) | 87 % (66/76) | 19.1 | 35 | yes | 5/5 · 5/5 | 57.0 | 0.40 |
| p02 | 16:50 | 16.3 | 13 % (3/23) | 40 % (16/40) | 42 % (27/64) | 14.5 | 26 | yes (mid-correction) | 0/2 · 0/2 | 29.2 | 0.26 |
| p02 | 21:29 | 21.7 | 10 % (3/29) | 85 % (34/40) | 86 % (55/64) | 16.3 | 31 | yes | 2/2 · 1/2 | 49.4 | 0.34 |

Reading: with busy-person answers the product needs more questions (follow-ups), so typing stays about 16.7 min for p01 although each answer is shorter: the remaining gap to 20 min is the **number of questions**, not the answer length (R20). p02 step 3 got `fix-first` (the night shift routes differently), not in its expected list (R21). Numbers of a single run vary with the model: p02's step list differed between the two runs.

## 11. Review 2026-11-20

An independent review of the evaluation (concept in this spec, product goals in product §8, the short step walk of spec 14 §3.19 and spec 12) against the code in `eval/` and the runs `20261120-152212` (old walk) and `20261120-165033` (short walk). Severity: **High** = a headline number is wrong or misleading; **Medium** = a metric is unfair to correct product behaviour; **Low** = small or cosmetic. "Fixed" items are built and tested (AC-24.44 to AC-24.50); "Open" items wait for the product owner.

| # | Finding | Severity | Fix |
|---|---|---|---|
| R1 | **Steps matched only by name.** In 16:50 p02's captured "First pass" (open the ticket, read the description, ticketing system) is true step 1 "Read the new ticket", but shares no name word: 12 cells scored missing, Tier A + core 40 % understated | High | **Fixed (A1):** content matching, merge and missing rules (§3.7 item 2; AC-24.44, AC-24.45) |
| R2 | **A missing step earned honesty credit.** `disclose: never` cells (p02's step effort) were scored "correct, no number" even for steps the product never captured | Medium | **Fixed:** a missing step is wrong in every cell (AC-24.46) |
| R3 | **The runner pressed *Finish* during a correction.** p02, message 26: the persona said steps 2 and 3 were missing, the agent started asking about them, and the runner pressed *Finish* because 3 review answers had been given. The map stayed at 2 of 4 steps | High | **Fixed:** E8 (the persona presses *Finish*) and only short review answers count (AC-24.49) |
| R4 | **The runner kept chatting after the agent offered *Finish*.** p01 messages 29-31 answer three "press Finish?" summaries: three messages and about a minute no real employee spends | Medium | **Fixed:** E8 |
| R5 | **Simulated answers too long.** p01's "walk me through" answers were 70-90 words (typing 16.3 of 24.8 min), because E4 told the persona to answer every part of a grouped question. The time metric measured the persona, not the product, and long complete answers flattered quality | High | **Fixed (A2):** 15-45 words in the prompt, 60-word cap in code, average answer words in the scorecard (AC-24.48) |
| R6 | **The expert's own role was required in step roles.** The walk asks "who besides you is involved"; the truth listed the expert in every step, so "nobody else" scored wrong (p01: 5 role cells; p02: "I") | Medium | **Fixed:** own role implied (§3.7 item 7; AC-24.47) |
| R7 | **p01 step 1 expected route too narrow.** The catalogue picks `low-code-agent` when "inputs are digital documents in a varying layout", exactly p01's pain; the expected list left it out | Medium | **Fixed:** p01 v3 accepts it (D17) |
| R8 | **Judge calibration not representative.** 30 clean pairs, none like the real failures: the judge marked "a site report is still missing" ≠ "a site cost report is still missing" | Medium | **Fixed:** judge-v2 (dropped qualifier), 6 pairs from real runs (D18). Open: the product owner confirms the 6 new labels |
| R9 | **Fit and route 1/5 and 0/2 are a product result, not an eval bug.** The report assessed only step 1 (others "Not assessed"; the step assessment kept one entry per run, spec 26 grounding). The eval scores "not assessed" as a miss, which is right | High (product) | Open: look at the step assessment drops (spec 26); backend not changed |
| R10 | **p02: the product never asked the steps question** (spec 14 W3); it took two step names from the open "what recurs in your week" answer and kept 2 of 4 steps | High (product) | Open: product, spec 14 W3 (a count from an open answer should still be confirmed) |
| R11 | Transcript phase labels were one phase late (an answer carried the phase after it) | Low | **Fixed:** D15 |
| R12 | App cost ignores cached app calls (p01 had 4 cache hits from earlier runs), so a cached run shows a slightly low € | Low | Open: mark cost "partial" when app cache hits > 0, or read cost from `FRESH=1` runs only |
| R13 | Quick runs never show deltas: they compare with `latest.json`, which only a full run writes (none exists yet) | Low | Open: compare a quick run with the last quick run |
| R14 | Detail burden counts questions, not their size; the one bulk Tier C confirmation in review counts as a low-value question although it costs one "yes" | Low | Open: weight by agent words, or leave (it is ≤ 1 question a session) |
| R15 | Employee time: think time is 8 s whatever the question; a six-part walk question takes longer to think about. Constants are assumptions | Low | Open: think time per question part (assumption to agree) |
| R16 | The persona sometimes says more than its sheet ("if something goes wrong it would just delay the report" where the sheet says no exception; extra inputs for p02 step 4), and the product is scored wrong for capturing it | Medium | Partly fixed by A2. Open: prompt rule "if your sheet says none, say there is none" |
| R17 | Honest refusals earn points: p02 gets every `never` cell of captured steps right, so overall quality of a difficult persona is not comparable with a cooperative one | Low | Open: report never-cells apart (they are already excluded from no target) |
| R18 | *Finish* took 46.5 s for p01 (target < 30 s) | Medium (product) | Open: product, report generation time |
| R19 | §3.13 cost and time estimate still assumes cap 60 and about 35 messages | Low | Open: refresh after the next full run |
| R20 | After A2 the time target is missed by message count: p01 35 messages × 19 words = 16.7 min typing. Fewer, better-grouped questions (or proposals the expert only confirms) are the lever | High (product) | Open: product, spec 14 (e.g. ask Tier B with Tier A, propose roles and approvals) |
| R21 | p02 step 3 routed to `fix-first` because "the night shift in Manila routes by a simpler list" matches its choose_when ("teams do the step differently"); expected lists only ticket-routing and low-code-flow | Low | Open: product owner decides whether `fix-first` is acceptable for step 3 (do not widen to pass) |
| R22 | One run per persona: p02 got 2 steps in one run and 4 in the next. A single quick run cannot show a small change | Medium | Open: run each quick persona 2-3 times (cache off) before reading a delta |

**Checked and found sound:** turn records carry the focus of the question that followed each answer (the right one for the detail burden); the hard cap, `n/a` handling (an `n/a` never fails) and the cluster code reply (E6) behave as specified; tiers match the registry (AC-24.40); the denominator is every truth field.


## 12. Amendment (built 2026-11-21): what the p05 run adds to the evaluation

> **Status:** approved 2026-11-21 · **built 2026-11-21** (AC-24.51 to AC-24.56; `make test-eval` 167 passed). As built: S14 truth adds one scored field per step that has it (`truth_field_count`); `written` must match when the truth has it, `set_by` is compared only when captured. Product changes: spec 14 §3.21. Goal: measure the fixes in general, not for one persona.

| # | Change |
|---|---|
| V1 | **Tiers:** `eval/tiers.yaml` gets `decision_criteria: B` (S14) |
| V2 | **Persona truth:** `truth.steps[*].decision_criteria` (optional; only for a `judgement` or `mix` step), registry shape. Scored by §3.7: `basis` and `varies` by the judge, `written` and `set_by` by code (exact, or an alias). A step whose truth has no S14 is not scored for it |
| V3 | **New behaviour metric, criteria asked:** judgement or mix truth steps whose S14 cell was asked (`asks` ≥ 1 in any snapshot) ÷ all such steps. Target **100 %** (assumption). n/a when the persona has none |
| V4 | **New behaviour metric, hours computed:** steps with a number in the report's hours a year ÷ the report's steps; n/a when there is no report or the persona's effort is `disclose: never`. Target **100 %**. Catches a parser gap like row 2 of spec 14 §3.21 |
| V5 | **Judge v3** (`JUDGE_PROMPT_VERSION = "judge-v3"`): added rule "a qualifier that only repeats what one run of the process is (for example 'per role' when the process runs once per role) does not change the meaning". Two new calibration pairs: true "3 working days" / "3 working days per role" (field P12, volume counted per role); false "3 hours" / "3 hours per week". Agreement still ≥ 90 % |
| V6 | **p05 v2:** truth step 3 gets `decision_criteria: {basis: the hiring manager's must-haves and the job ad, set_by: Hiring manager, written: partly, varies: every hiring manager wants something different}`; behaviour unchanged (criteria only when asked) |
| V7 | **New persona `p06-work-order-priority`** (cooperative, not quick, seed): a maintenance planner, Knowledge & Ops (`KNW`), "Prioritising corrective maintenance work orders", 4 steps, one `judgement` step whose criteria are partly written (an old priority matrix) and change by site manager; discloses the criteria only when asked. A second domain, so a fix that works only for hiring shows up. Routes set from the catalogue when the file is written |
| V8 | **How we read the result:** run all six personas (cache off for app calls) before and after the fixes; a fix is accepted only when p05 and p06 improve on criteria asked, hours computed and Tier A quality **and** p01–p04 do not get worse on employee time, detail burden or Tier A quality by more than their run-to-run noise (R22: run each twice) |

| ID | Given / when / then |
|---|---|
| AC-24.51 | A registry step leaf without a tier still fails the tiers test; with `decision_criteria: B` it passes |
| AC-24.52 | A persona with S14 truth on a `rules` step fails to load (exit 2) with a clear reason |
| AC-24.53 | Criteria asked: a fixture run where step 3 (mix) has S14 `asks` 1 scores 100 %; with `asks` 0 it scores 0 % and fails the target; a persona with no judgement step shows n/a |
| AC-24.54 | Hours computed: a report with "—" in a step's hours a year scores below 100 % and fails the target; a step whose effort is `disclose: never` is not counted |
| AC-24.55 | `JUDGE_PROMPT_VERSION == "judge-v3"`; the calibration file holds the two new pairs and stays within the shape rules (25–40 pairs, ≥ 12 true, ≥ 12 false) |
| AC-24.56 | All six personas load; `quick` still selects p01 and p02 |

## 13. Amendment (approved 2026-11-21, product owner): a ready-to-finish demo session

> **Status:** approved 2026-11-21 (product owner: "open the frontend with that conversation, as if I had just done it, and the only missing thing is the final report") · built 2026-11-21.

| # | Rule |
|---|---|
| D1 | `python -m eval.demo_session --run <run id> --persona <id> [--name <display name>]` reads `eval/runs/<run>/<persona>/session.json` (the stored session) and writes one **ready-to-finish copy** to Cosmos (settings from `backend/.env`) |
| D2 | The copy: id `demo-<persona id>`; owner `sha256(EVAL_SEED_VISITOR_KEY)`; `simulated: true` (tagged *Simulated*, as every seeded session, §3.12); `status: active`, `phase: review`; no assessment, report, briefs or `finishedAt`; `ttl: null` (never expires); conversation, profile, documents, score and counters as stored. An existing copy is replaced (delete, then create) |
| D3 | Refused (exit 2, nothing written) when the stored session cannot press *Finish* (its stored score is below the gate) or the key is missing or shorter than 22 characters |
| D5 | Allow-list (§2, AC-24.29): `eval/` may also import the storage model `app.models.process_discovery_schemas`, only to build the copy D2 writes |
| D4 | To see it, the browser uses the same key once: `localStorage.setItem('discovery_visitor_key', '<EVAL_SEED_VISITOR_KEY>')` in the app's console, then reload; the app must run with `STORE=cosmos` |

| ID | Given / when / then |
|---|---|
| AC-24.57 | `demo_copy(stored, key)` gives the D2 fields and keeps the messages, profile and score unchanged; the input is not changed |
| AC-24.58 | `demo_copy` of a stored session whose score is below 0.8 raises; `write_demo` deletes then creates `demo-<persona>` under the key's owner |
