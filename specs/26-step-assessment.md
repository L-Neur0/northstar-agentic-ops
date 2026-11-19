# 26 · Step-by-step AI assessment and the recommended route

> **Status:** approved · **Implements:** F-26 (product); §6.2 ASSESS_STEPS, §6.4 grounding (architecture) · **Depends on:** specs 10 (config loader), 11 (LLM client, strict schema, fences), 12 (models), 18 (profile fence, evidence check, fingerprint), 19 (hours a year per step, readiness), 20 (`assess`, report)
> **Code:** `backend/app/services/process_discovery/artifacts/steps/{schemas,prompts,steps,route}.py`, the `SolutionCatalogue` model in `backend/app/core/config.py`
> **Tests:** `backend/tests/unit/process_discovery/artifacts/test_steps_*.py`, `backend/tests/unit/core/test_solution_catalogue.py`

## 1. Purpose

After *Finish*, one model call (**ASSESS_STEPS**) rates **each step** of the mapped process: can AI do it (`automate`), help a person do it (`assist`), or should it stay with people (`human`), with a reason and the expert's own words as evidence. For each step it also picks a **route**: the kind of solution that fits, chosen only from the company's **solution catalogue** (`config/<company>/solutions.yaml`). Code checks every step number, every quote and every route id, then builds a short **recommended route** (which steps first, with which route, what to fix first) from the checked ratings and the step hours. This runs **alongside** OPPORTUNITIES (spec 18), which stays unchanged.

## 2. Where it sits

- **Layer:** `artifacts/steps/`. May import what spec 18 §2 allows; uses `artifacts/profile_fence.py`, `artifacts/evidence.py`, `artifacts/fingerprint.py`. Never imports `analysis/`, `diagram/` or `labels/` (and they never import it; the layer test checks it). `route.py` is **pure**.
- **Builds on:** `LLM.generate_structured`, a new `CallType.ASSESS_STEPS` (spec 11); `fence_profile`, `find_evidence`, `profile_values`, `ai_input_fingerprint` (spec 18); `ValueResult.steps[].hours_per_year` (spec 19); `assess()` and the report (spec 20).
- **Changes to other contracts** (amendments listed in §5): spec 11 adds a call type and a budget; spec 12 adds `Assessment.step_assessment` and the outcome key `steps`; spec 10 loads `solutions.yaml`; spec 18 `evidence.py` gains one helper; spec 19 `compute_code_parts` also builds the route summary; spec 20 runs four calls in parallel and gets two new report parts.

## 3. Behaviour

### 3.1 The solution catalogue (`solutions.yaml`, F-22)

Company configuration. The model may choose only these ids; the report shows their names. **The NIG file is a placeholder** until the product owner provides NIG's tool list (`placeholder: true`).

| Key | Rule |
|---|---|
| `placeholder` | Bool. While true, report Parts 5 and 6 carry the note "Routes come from a placeholder solution list, not the company's real tools." |
| `version` | Free text; part of the catalogue fingerprint |
| `solutions` | 2–30 entries |
| `id` | Slug `^[a-z][a-z0-9-]{1,39}$`, unique |
| `category` | One of the six below |
| `name`, `good_for` | Non-empty, ≤ 200 / ≤ 400 characters |
| `choose_when` | 1–5 items; `avoid_when`, `prerequisites` 0–5 items; each ≤ 200 characters |
| `fits` | Non-empty subset of `automate`, `assist`, `human`. At least one entry in the file fits `human` |

| Category | Meaning | NIG entry (assumed setup) |
|---|---|---|
| `existing_internal` | An AI tool the company has **already built and runs**: reuse it before buying or building | `invoice-processing`, `cv-screening`, `contract-review`, `ticket-routing`, `knowledge-assistant`, `lead-qualification` |
| `off_the_shelf` | A licensed assistant the company already has | `m365-copilot` |
| `low_code` | Low-code workflow or agent built by a trained business user | `low-code-flow`, `low-code-agent` |
| `custom_build` | Custom AI app or agent built by the AI engineering team | `custom-ai-app` |
| `integration` | IT integration (API, export) or screen automation (RPA) | `it-integration-rpa` |
| `fix_first` | Standardise, digitise or clean data before any tool | `fix-first` |
| `none` | No tool: stays with people | `stays-with-people` |

The categories are product concepts (fixed in code); the entries are company configuration. Invalid catalogue stops the app at start-up (F-22).

### 3.2 Worked example

The EU monthly cost review (spec 18 §3.1), step hours from spec 19 §3.2: 72, 96, 72, 30, 72. The model returns:

| Step | Fit | Route | Evidence (hit) |
|---|---|---|---|
| 1 Collect site spreadsheets | assist | `fix-first` | "sites send late and in different layouts" (`process.substeps[1].pain_points`) |
| 2 Consolidate into the master file | automate | `custom-ai-app` | "I copy the numbers into the master file by hand" (`process.substeps[2].pain_points`) |
| 3 Analyse variances | automate | `low-code-flow` | "the threshold check is done by eye" (`process.substeps[3].pain_points`) |
| 4 Chase explanations | automate | `low-code-flow` | "some site managers answer only after three reminders" (`process.substeps[4].pain_points`) |
| 5 Write the variance summary | assist | `office-assistant` | "I write the commentary from scratch every month" (`process.substeps[5].pain_points`) |

Variants: an extra entry for step 7 is dropped (`step`); a route `acme-copilot` on step 3 is not in the catalogue, so step 3 keeps its fit and reason with **no route** (`route`); `stays-with-people` on step 2 (fit `automate`) is not a fit of that entry, so the route is removed (`route`).

**Recommended route** (code, §3.6): start with step 2 (96 h, `custom-ai-app`) and step 3 (72 h, automate, `low-code-flow`); later step 5 (72 h, assist) and step 4 (30 h); fix first step 1; nothing stays with people. Headline: *Start with step 2 "Consolidate into the master file" (about 96 h a year) using Custom AI app or agent built by the AI engineering team (placeholder). Fix first: step 1 "Collect site spreadsheets".*

### 3.3 ASSESS_STEPS: the call (`steps/steps.py`)

1. **One call**, `generate_structured(AssessStepsOut, CallType.ASSESS_STEPS, messages)`. System = `ASSESS_STEPS_SYSTEM` + the rendered catalogue (§3.4). User = "Rate each step of this process profile:" + `fence_profile(profile)`.
2. **Wire schema** (strict; all fields required):

   ```python
   class StepRatingOut(BaseModel):           # extra="forbid"
       step: int                              # 1-based --- STEP n --- number
       fit: Literal["automate", "assist", "human"]
       reason: str
       evidence: str
       route: str                             # a catalogue id, or "" for none
       route_reason: str
   class AssessStepsOut(BaseModel): steps: list[StepRatingOut]
   ```

3. **Failure.** Any `LLMError` (empty, refused, truncated, invalid twice, unavailable, budget) raises `StepAssessmentFailedError` (chained). No fallback content: the orchestrator stores no ratings and outcome `failed` (spec 20); Parts 5 and 6 show a note. The other assessment parts are not affected.

### 3.4 Prompt (`steps/prompts.py`)

`ASSESS_STEPS_SYSTEM` is one literal string (no `str.format`); `render_catalogue(catalogue)` appends a `SOLUTION CATALOGUE` block, one entry per line: `- <id>: <name> [<category>; fits: <fits>] good for: …; choose when: …; avoid when: …; needs: …` (each text through `single_line(…, 300)`). The catalogue is trusted configuration and is not fenced; the profile is.

| # | Rule given to the model |
|---|---|
| 1 | You are a senior process and AI analyst. Rate only what the profile states; never invent a system, input, role or pain |
| 2 | Return exactly one entry per `--- STEP n ---`, with that number |
| 3 | `fit`: `automate` = AI or automation can do the step, a person checks samples or exceptions; `assist` = AI drafts, reads, checks or suggests, a person decides or finishes; `human` = judgement, relationships, accountability or physical work that stays with people |
| 4 | `reason`: one or two sentences naming the step's inputs, systems, decisions or pain behind the fit |
| 5 | `evidence`: the expert's words copied exactly from **that step** or from the process fields, at least three words or a whole short answer; no paraphrase, no joining of passages |
| 6 | `route`: one `id` from the SOLUTION CATALOGUE whose `fits` include the step's fit, chosen by its "choose when" and "avoid when"; `""` if none fits. Never invent an id, never name a vendor or product |
| 7 | When the step's inputs are paper or verbal, or teams do it differently, prefer a `fix_first` entry |
| 8 | `route_reason`: one sentence on why this route fits better than the next best |
| 9 | Never give hours, money, savings or scores; code computes them |
| — | The PROFILE fence sentence; "Return only JSON matching the schema." |

### 3.5 Grounding (`ground_step_ratings`, pure)

Each entry is checked on its own; a bad entry is dropped and counted, never fatal.

| # | Check | On failure |
|---|---|---|
| A1 | Only the first 50 raw entries are read | Rest ignored (`cap`) |
| A2 | `step` is an int (not a bool) in `1..N`; the first entry per step wins | Entry dropped (`step`) |
| A3 | `fit` is one of the three values | Entry dropped (`invalid`) |
| A4 | `reason` cleaned to one paragraph, non-empty, capped at 600 with "…" | Entry dropped (`invalid`) |
| A5 | `evidence` passes the quote check (spec 18 §3.3) on the values of **that step, then the process fields** (`restrict_to_step_or_process`: the step's values first, so a quote that is in both hits the step); a quote found only in another step fails | Entry dropped (`quote`) |
| A6 | `route` (stripped) is `""` or an `id` in the catalogue (exact match) | Unknown id → route `None`, entry kept (`route`) |
| A7 | The entry's `fits` include the step's `fit` | Route `None`, entry kept (`route`) |
| A8 | `route_reason` cleaned, capped at 400; set to "" when the route is `None` | — |
| A9 | Code sets `name` (the real step name), `evidence_key`, `evidence_source` from the hit | — |
| A10 | Output: one `StepRating` per step 1..N in order; a step with no kept entry gets `fit = None` (*not assessed*) | — |

### 3.6 The recommended route (`steps/route.py`, pure)

`route_summary(ratings, value, catalogue) -> RouteSummary`. Step hours come from `value.steps[k].hours_per_year` (`None` when not computable).

| Group | Who | Order |
|---|---|---|
| `start_with` | Fit `automate` or `assist`, route category not `fix_first` or `none`: the first `ROUTE_START_MAX` (2) | Step hours (high first, `None` last), then `automate` before `assist`, then step number |
| `later` | The rest of the same set | Same |
| `fix_first` | Route category `fix_first` | Step number |
| `stay_with_people` | Fit `human` | Step number |
| `not_routed` | Fit `automate` or `assist` with route `None`, and steps not assessed | Step number |

- `prepare`: the `prerequisites` of the routes used in `start_with`, de-duplicated (case-insensitive), in catalogue order, at most 5.
- `headline`, one code template: *Start with step k "<name>" (about H h a year) using <route name>.* (hours part left out when `None`) + *Fix first: step j "<name>"[, step …].* when `fix_first` is not empty. With no `start_with`: *No step has an AI route yet.* + the fix-first sentence if any. No other text.
- The summary is rebuilt by code on every recompute (spec 19 §3.7); no model call.

### 3.7 Re-running

1. `StepAssessment.inputs_hash = ai_input_fingerprint(profile) + ":" + catalogue_fingerprint(catalogue)`. `catalogue_fingerprint` = SHA-256 of the catalogue's canonical JSON (sorted keys).
2. `assess()` (spec 20) reuses the stored ratings when `inputs_hash` matches and `outcomes["steps"] == "generated"` and `refresh` is false; otherwise ASSESS_STEPS runs. Changing the catalogue (for example replacing the placeholder) re-runs it on the next assessment.

### 3.8 Logging (F-24)

One `assessment_call` line: `call = ASSESS_STEPS`, `outcome`, `duration_ms`, `kept`, `dropped` by reason (`step`, `quote`, `invalid`, `cap`, `route`), `placeholder_catalogue: true|false`. Never any text.

## 4. Interfaces

### 4.1 Steps

```python
# artifacts/steps/steps.py
class StepAssessmentFailedError(Exception): ...
async def run_step_assessment(profile: Mapping[str, Any], llm: LLM,
                              catalogue: SolutionCatalogue) -> tuple[list[StepRating], dict[str, int]]
def ground_step_ratings(reply: AssessStepsOut | Mapping[str, Any], profile: Mapping[str, Any],
                        catalogue: SolutionCatalogue) -> tuple[list[StepRating], dict[str, int]]   # pure

# artifacts/steps/prompts.py
ASSESS_STEPS_SYSTEM: str
def render_catalogue(catalogue: SolutionCatalogue) -> str

# artifacts/steps/route.py  (pure)
ROUTE_START_MAX = 2
def route_summary(ratings: Sequence[StepRating], value: ValueResult | None,
                  catalogue: SolutionCatalogue) -> RouteSummary
def catalogue_fingerprint(catalogue: SolutionCatalogue) -> str

# artifacts/evidence.py  (added)
def restrict_to_step_or_process(values, step: int) -> list[tuple[str, str, str]]   # step n's values, then process fields; never other steps
```

### 4.2 Stored models (added to spec 12 §3.11)

```python
class StepRating(StorageModel):
    step: int; name: str
    fit: Literal["automate", "assist", "human"] | None      # None = not assessed
    reason: str; evidence: str; evidence_key: str; evidence_source: Literal["expert", "document", "specialist"] | None
    route_id: str | None; route_reason: str
class RouteSummary(StorageModel):
    headline: str; start_with: list[int]; later: list[int]; fix_first: list[int]
    stay_with_people: list[int]; not_routed: list[int]; prepare: list[str]
class StepAssessment(StorageModel):
    steps: list[StepRating]; route: RouteSummary | None; inputs_hash: str; placeholder_catalogue: bool
# Assessment: + step_assessment: StepAssessment | None; outcomes gains the key "steps"
```

### 4.3 `SolutionCatalogue` (`app/core/config.py`, this spec owns it)

```python
SolutionCategory = Literal["existing_internal", "off_the_shelf", "low_code", "custom_build", "integration", "fix_first", "none"]
AIFit = Literal["automate", "assist", "human"]
class Solution(BaseModel):            # extra="forbid", frozen
    id: str; category: SolutionCategory; name: str; good_for: str
    choose_when: list[str]; avoid_when: list[str] = []; prerequisites: list[str] = []; fits: list[AIFit]
class SolutionCatalogue(BaseModel):   # extra="forbid", frozen
    placeholder: bool; version: str; solutions: list[Solution]
    def get(self, id: str) -> Solution | None: ...
```

`CompanyConfig` (spec 10) gains `solutions: SolutionCatalogue`, loaded from `solutions.yaml`.

## 5. Implications

- **Spec 11:** `CallType.ASSESS_STEPS`, setting `LLM_MAX_TOKENS_ASSESS_STEPS` (default 32000).
- **Spec 12:** the models of §4.2; `Assessment.outcomes` keys become `opportunities | diagram | labels | steps`.
- **Spec 10:** loads and validates `solutions.yaml`; a missing file stops the app like any other config file.
- **Spec 18:** `evidence.py` gains `restrict_to_step_or_process`. Nothing else changes; OPPORTUNITIES stays as it is.
- **Spec 19:** `compute_code_parts` also takes the ratings and the catalogue and returns the `RouteSummary`.
- **Spec 20:** `assess` runs four calls in parallel (part name `steps`); the budget check at *Finish* covers four calls; report Parts 5 *Step-by-step AI assessment* and 6 *Recommended route*.
- **Spec 21 (to write):** the specialist sees the ratings and may later override a fit or route (not in this spec); the implementation brief may carry the route of the covered steps.
- **Data:** `assessment.stepAssessment`. No migration (no finished sessions stored yet).
- **Security and privacy:** the profile is fenced; the model output is never trusted (steps, quotes, ids checked); logs carry counts only.
- **Cost and latency:** one more call per *Finish*, in parallel with the other three; repeated only when the profile or the catalogue changes.

## 6. Acceptance criteria

| ID | Given / when / then |
|---|---|
| AC-26.1 | `SolutionCatalogue` loads `config/nig/solutions.yaml` (7 entries, `placeholder: true`); it rejects a duplicate id, a bad slug, an unknown category, an empty `fits`, an unknown fit, an empty `choose_when`, more than 30 entries, and a file with no entry fitting `human` |
| AC-26.2 | `strict_json_schema(AssessStepsOut)` builds; the `fit` literal equals `AIFit` (pinned in a test) |
| AC-26.3 | `run_step_assessment` makes one `generate_structured` call with `CallType.ASSESS_STEPS`; the system prompt holds every rule of §3.4 (by phrase), the PROFILE fence instruction and one catalogue line per entry with its id; the profile travels fenced |
| AC-26.4 | Given the §3.2 reply on the EU fixture, `ground_step_ratings` returns 5 ratings with the fits, routes and evidence keys shown and `dropped` all zero |
| AC-26.5 | An entry for step 0, step 7, a bool or a string step is dropped (`step`); a second entry for the same step is dropped; the first wins |
| AC-26.6 | An entry whose evidence is not in the profile, or is found only in another step's values, is dropped (`quote`); evidence from a process field (P09) is accepted |
| AC-26.7 | A route id not in the catalogue (`acme-copilot`) gives `route_id = None` with the fit and reason kept, counted `route`; `""` gives `None` and is not counted |
| AC-26.8 | A route whose `fits` do not include the step's fit (`stays-with-people` on an `automate` step; `office-assistant` on a `human` step) gives `route_id = None`, counted `route` |
| AC-26.9 | An unknown fit or an empty reason drops the entry (`invalid`); reason and route reason are capped at 600 / 400 with "…"; only the first 50 raw entries are read |
| AC-26.10 | The output always has one rating per step 1..N in order; a step the model skipped has `fit = None`; names are the real step names |
| AC-26.11 | Each `LLMError` subclass (empty, invalid, unavailable, budget) makes `run_step_assessment` raise `StepAssessmentFailedError` |
| AC-26.12 | `route_summary` on the §3.2 ratings and EU hours gives `start_with [2, 3]`, `later [5, 4]`, `fix_first [1]`, `stay_with_people []`, `not_routed []`, and the headline of §3.2 exactly |
| AC-26.13 | Order ties: equal hours → `automate` before `assist` → step number; `None` hours sort last and the headline omits the hours part |
| AC-26.14 | `prepare` holds the prerequisites of the `start_with` routes, de-duplicated case-insensitively, in catalogue order, at most 5 |
| AC-26.15 | No routed step → headline starts "No step has an AI route yet."; a fit-`human` step appears only in `stay_with_people`; an unrouted `automate` step appears only in `not_routed` |
| AC-26.16 | `catalogue_fingerprint` changes when any entry or `version` changes and not when YAML key order changes; `inputs_hash` combines it with `ai_input_fingerprint` |
| AC-26.17 | `route_summary`, `ground_step_ratings` and `render_catalogue` are pure (no I/O, no clock, no model; import check) and give the same output for the same input |
| AC-26.18 | One `assessment_call` log line per call with outcome, kept, drop counts by reason and `placeholder_catalogue`; no profile or reply text in any log record (sentinel test) |
| AC-26.19 | The layer test fails if `artifacts/steps` imports `analysis`, `diagram` or `labels`, or the other way round |
| AC-26.20 | No company tool name appears in code: the catalogue entries reach the prompt and the report only from configuration (grep test on a sentinel entry name) |

## 7. Test plan

| Test file | Covers |
|---|---|
| `tests/unit/core/test_solution_catalogue.py` | AC-26.1 |
| `tests/unit/process_discovery/artifacts/test_steps_schemas.py` | AC-26.2 |
| `tests/unit/process_discovery/artifacts/test_steps_prompts.py` | AC-26.3 (prompt half), 26.20 |
| `tests/unit/process_discovery/artifacts/test_steps_grounding.py` | AC-26.4–26.10 |
| `tests/unit/process_discovery/artifacts/test_steps_call.py` | AC-26.3 (call half), 26.11, 26.18 (`FakeLLM`) |
| `tests/unit/process_discovery/artifacts/test_steps_route.py` | AC-26.12–26.17 |
| `tests/unit/process_discovery/test_architecture.py` | AC-26.19 |

## 8. Out of scope

| What | Where |
|---|---|
| Opportunities, the map, the evidence check itself | Spec 18 |
| Hours per step, readiness, the opportunities path | Spec 19 |
| Running the call in parallel, timeouts, outcomes, the report parts and the PDF | Spec 20 |
| Specialist override of a fit or route; route in the implementation brief | Spec 21 |
| NIG's real tool list | Product owner (replaces the placeholder catalogue) |
| Euros or savings per route | Parked until the value method is decided (refinement R5) |

## 9. Open questions

| # | Question | Default until decided |
|---|---|---|
| Q1 | NIG's real catalogue: which tools, and are they available to all staff or per region? | Placeholder catalogue, vendor-neutral, `placeholder: true` |
| Q2 | Should a step that depends on a fix-first step (its input comes from it) move from `start_with` to `later`? | No: code does not read dependencies; the headline names the fix-first steps |
| Q3 | `ROUTE_START_MAX` = 2: constant or configuration? | Constant |
| Q4 | Should readiness (spec 19) also cap a step's route (for example *Data: low* → `fix_first`)? | No: the model sees the same profile; readiness stays a separate guide |


> **Decision (2026-11-19):** NIG's catalogue = Microsoft 365 Copilot + the six AI tools NIG has already built internally (invoice processing, CV screening, contract review, ticket routing, knowledge assistant, lead qualification) + generic low-code, custom-build, integration, fix-first and stays-with-people routes. It is an *assumed* setup for the fictional company (`placeholder: false`, `assumed: true`); the report says "assumed tool set" instead of "placeholder". The prompt tells the model to prefer an `existing_internal` tool whenever its `choose_when` matches (reuse before build).
