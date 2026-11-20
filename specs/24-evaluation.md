# 24 · Evaluation: simulated experts, runner, scoring, seed data

> **Status:** built 2026-11-20 with deviations (§10); approved 2026-11-20 (judge app-chat at default temperature; efficiency metrics; seeded sessions tagged Simulated; Q8 offer-never-force) · **Implements:** F-25 and the quality targets of §8 (product), §3.9 and §6.6 (architecture) · **Depends on:** specs 11, 12, 13, 14, 15, 16, 17, 20, 26
> **Code:** `eval/run.py`, `eval/evalkit/` · **Data:** `eval/personas/`, `eval/documents/`, `eval/judge_calibration.yaml`, `eval/prices.yaml` · **Tests:** `eval/tests/`

## 1. Purpose

Prove, with numbers, that the interview works end to end. Simulated experts (personas) are played by a model through the **real API**; each one has a hidden true process. A small runner plays them, presses *Finish*, and scores what the product captured against the hidden truth and against the product quality targets (product §8). One scorecard per run, compared with the last one, so a prompt or code change shows its effect. Finished runs can also seed the demo overview.

**Two main dimensions, always shown together:** **report quality** (how much of the hidden truth the report got right) and **efficiency** (how many expert messages it took). A long chat that gets everything right is not a success: the product owner wants short interviews, never endless chats.

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
| `truth.steps` | One entry per step, registry leaves `name` … `exceptions` (S01–S11; S12 optional) | Count = `truth.fields["process.substep_count"]` |
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
| E4 | Prompt rules: reply as this person in one short chat message; only facts from the persona file; for a yes/no confirmation reply with a plain "yes" or "no" plus the correction; for a document conflict reply "mine", "the document's", "both" or own words, following the truth; never mention being simulated |
| E5 | Output: plain text, 1–600 characters. Empty or failed after the client's retries → the persona run ends as `error` (not a product failure) |
| E6 | **Answered by code, no EXPERT call:** a cluster proposal (`clusterProposal` not null) → `"yes"` when its code equals `expected.cluster`, else `"no"`. Everything else goes to the model |
| E7 | Capped: at most `HARD_CAP` = 60 expert messages per persona (§3.9a) |

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
4. **When to press *Finish*:** `finish.ready` is true and either the phase is `review` and the expert has answered at most 3 review questions since entering it, or the next message would pass `HARD_CAP`. `POST …/finish`; a 409 `map_incomplete` is recorded and the loop goes on.
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

1. **What is scored:** the profile at *Finish* (or at the last turn if never finished): P01–P16 and S01–S11 of every true step. S12 (weight 0) is not scored. A value counts as captured whatever its status (complete, proposed); values still `proposed` are also counted in `proposed_at_finish`.
2. **Step alignment:** captured step *i* pairs with true step *i* when the counts are equal. When they differ, each true step pairs with the captured step whose name shares the most normalised words (ties: lower number); a true step with no pair (or no shared word) has every cell wrong.
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
| P15, S04, S10, S11 "none" | Code | Truth none ⇔ captured none row |
| Text (P01, P02, P04, P06–P09, S01–S03, S07, S09, S11 descriptions) | Judge | `same_meaning: true` (§3.8). Lists are judged as one joined value: does the captured list cover the main points of the hidden one |
| Missing captured value | — | Wrong (no judge call) |

5. **Report quality (the headline number)** = correct fields ÷ **all fields in the hidden truth** (P01–P16 plus S01–S11 of every true step). A missing value is wrong; a true step the product never captured counts all 11 cells wrong; nothing is left out. Per persona and pooled (sum of correct ÷ sum of truth fields). Example: p01, 5 steps → 16 + 5 × 11 = **71 truth fields**; the target 85 % needs 61 correct. Target ≥ 85 % for `cooperative` personas; reported (no target) for `difficult` ones.
6. **No invention** (fields with `disclose: never`): such a field is **correct** when the captured value is empty, "none identified", or words without a number (the honest answer to a refusal), and **wrong** when it holds a digit or a parsed number; each wrong one is also counted as an `invented_value`. Target 0.

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
| J4 | **Fixed prompt**, versioned (`JUDGE_PROMPT_VERSION`), stored in the run's `run.json`. Rules in the prompt: same facts and numbers = same meaning; different wording is fine; a missing or extra key fact, a different number, or a negation = not the same |
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
| Expert messages to *Finish* | Expert messages sent before *Finish* succeeded | ≤ 30 `cooperative`, ≤ 40 `difficult` |
| **Hard cap** | `HARD_CAP` = 60. The runner sends no 61st message. More than 60 needed, or *Finish* never reached → the session is **failed** and the **run fails** (exit 1), whatever the other numbers | 0 failed sessions |
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

### 3.10 Tokens and cost

1. Tokens per call type and deployment come from the captured `llm_call` lines (in-process), split into **app** (every call type but EXPERT and JUDGE), **expert** and **judge**. Cache hits cost 0 and are counted apart.
2. € = tokens × `eval/prices.yaml` (`{deployment: {in: €/M, out: €/M}}`). The prices are an **assumption** to fill from the price list; a deployment missing from the file shows tokens only.
3. Target: app cost per finished session < €0.50 (product §8). The product target assumes a small model; `app-chat` is gpt-5.6-sol, so the scorecard prints the deployment beside the number.

### 3.11 The scorecard (`scorecard.py`)

`scorecard.json` (schema `Scorecard`, Pydantic) and `scorecard.md` (rendered from it, no extra facts).

| Section | Content |
|---|---|
| Header | Run id, commit, mode, cache, deployments, judge agreement, **PASS / FAIL** with the reason (target missed, failed session, judge) |
| Headline | Per persona and pooled: **report quality**, **expert messages to *Finish***, **efficiency**, each with its delta; failed sessions in bold |
| Targets | One row per §8, §3.9 and §3.9a target: value, target, ✓ / ✗ / n/a, delta |
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
HARD_CAP = 60
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
def align_steps(truth_steps: list[dict], captured_steps: list[dict]) -> list[tuple[int, int | None]]
def score_fields(persona: Persona, profile: Mapping[str, Any], judge: Judge) -> FieldScores   # judge called only for §3.7 judge rows
def score_labels(persona: Persona, run: PersonaRun) -> LabelScores
def score_behaviour(run: PersonaRun, prices: Prices) -> BehaviourScores

# eval/evalkit/score_efficiency.py (pure)
def score_efficiency(persona: Persona, snapshots: Sequence[Snapshot], correct_at_finish: int | None,
                     words: YesNoWords) -> EfficiencyScores   # messages, efficiency, wasted, plateaus, failed
def progress_curve(persona: Persona, snapshots: Sequence[Snapshot], judge: Judge) -> list[CurvePoint]   # {n, quality, score, phase}
def sparkline(values: Sequence[float]) -> str

# eval/evalkit/judge.py
JUDGE_PROMPT_VERSION = "judge-v1"
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
| AC-24.10 | `align_steps`: equal counts pair by position; with 4 true and 5 captured steps, pairing follows shared name words, and an unpaired true step scores all 11 cells wrong |
| AC-24.11 | Code scoring holds for the §3.7 worked example rows that use code: volume "once a month" vs `{1, month}` correct; effort "half a day" vs "2 hours" wrong; systems matched by alias; a list with two extra items wrong |
| AC-24.12 | The judge is called only for §3.7 judge rows and code non-matches; a missing captured value is wrong with no judge call |
| AC-24.13 | Report quality = correct ÷ all truth fields (71 for p01): a missing value and every cell of an uncaptured true step count wrong; a `disclose: never` field is correct when empty or words without a number, wrong (and one `invented_value`) when it holds a digit |
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
| AC-24.31 | Messages to *Finish* count `POST …/messages` only (code-answered replies included; uploads, *Finish*, snapshots excluded); targets ≤ 30 for `cooperative`, ≤ 40 for `difficult` show ✓/✗ |
| AC-24.32 | Hard cap: the runner never sends a 61st message; a persona that needs more, or never reaches *Finish*, is `failed`, the scorecard says FAIL with that reason and the run exits 1 even when every other target is met |
| AC-24.33 | Efficiency = correct fields at *Finish* ÷ messages to *Finish* (61 and 28 → 2.18); `n/a` for a failed session; shown with its delta to `latest.json` |
| AC-24.34 | Wasted turns: a message whose next snapshot has the same profile values, the same field statuses and the same phase counts 1; a short "yes", "no", "mine" or a code-answered cluster reply never counts; 4 wasted turns in a session is ✗ |
| AC-24.35 | Plateau: scores 0.40, 0.40, 0.40, 0.40, 0.40, 0.40 over six messages (five without a gain) is one plateau flagged with its message numbers; any gain inside the window resets it |
| AC-24.36 | Progress curve: `curve.json` holds one point per message with report quality and `score.value`; the Markdown shows two sparklines per persona and the values at 10, 20, 30 and *Finish*; a value judged on an earlier snapshot is not sent to the judge again |

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

The first real run (`make eval QUICK=1`, then `make eval`) is the verification step; its scorecard goes into `eval/reports/` and the technical design.

## 8. Out of scope

- The four later personas (13 steps, switches language, contradicts self, gives a screenshot): new YAML files later, no runner change.
- Scoring the wording of questions, the opportunities text, the map or the readiness labels (beyond fit and route).
- Human ratings of the interview experience; A/B runs of two prompt versions in one run.
- Running in CI against a real model (CI runs `make test-eval` only).
- A web screen for scorecards (Markdown only).
- Measuring interview time in minutes for a human (product §8 row 1): the simulated expert's speed says nothing about it.

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
| Q8 | *(decided 2026-11-20, product owner)* Session-wide length | **Offer, never force:** at 40 expert messages the agent offers *Finish* and lists what is missing, and offers again every 10 messages; the employee may keep going. Product change recorded in spec 14 §3.18 (to build). The eval keeps its own hard cap of 60 expert messages (session counted as failed) |

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

**First run** (`make eval QUICK=1`, in process, real Azure, 2026-11-20, `eval/reports/quick-20261120-151619.*`): judge agreement 100 % (30/30). Both personas hit the hard cap of 60 messages without *Finish* (FAIL): the interview asks one step cell per message (about 11 messages per step), so a 5-step process needs more than 60. p01 report quality 76 % at message 60 (54/71), 2 wasted turns, 0 plateaus; p02 95 % (57/60), 3 wasted turns, 1 plateau, 0 invented values. Median turn 2.4-2.6 s, max 12 s; app cost about €0.38-0.40 per persona at the assumed prices. That run's scorecard was written before D12, so it shows scope, fit and route as ✗ for the unfinished sessions; a cached re-run gives the same numbers with them as n/a.

