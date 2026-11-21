# 18 · Opportunities and process map

> **Status:** approved · **built 2026-11-20** · **Implements:** F-12 (items 1–3, 5, 6), F-13 (product); §3.3 finish, §6.2 OPPORTUNITIES and MAP, §6.4 grounding (architecture) · **Depends on:** specs 11 (LLM client, strict schema, fences), 12 (models, `OpportunityType`, `Grade`, `rank_nodes`), 13 (profile dicts), 14 (`render_profile`)
> **Code:** `backend/app/services/process_discovery/artifacts/{profile_fence,evidence,fingerprint}.py`, `artifacts/analysis/{schemas,prompts,analysis}.py`, `artifacts/diagram/{schemas,prompts,grounding,diagram}.py`
> **Tests:** `backend/tests/unit/process_discovery/artifacts/`

## 1. Purpose

After *Finish*, two model calls read the finished profile. **OPPORTUNITIES** proposes where automation or AI fits, what each change would look like and what to prepare, and names the steps that should stay with people. **MAP** proposes a BPMN-style process map. The model's shape is fixed by a strict schema; its content is trusted for nothing: code checks every step number, every quote, every lane and every flow, drops what it cannot ground, and replaces an unrepairable map with a simple one drawn by code. No quote, no opportunity. No real step, no task.

> **Amendment 2026-11-19 (draft).** A fourth *Finish* call, **ASSESS_STEPS** (per-step AI fit and route from the solution catalogue), is specified in [spec 26](26-step-assessment.md); OPPORTUNITIES and MAP are unchanged. Saving shares are *parked until the value method is decided (refinement R5)*: O9 still stores the configured default, but nothing reads or shows it.

## 2. Where it sits

- **Layer:** `artifacts` (architecture §3.1). May import `llm.py`, `json_schema.py`, `domain`, `profile`, `interview.prompts.common` (for `render_profile` only), `app.models`, `app.utils.prompt_safety`. Never imports `documents`, `export`, `admin`, `overview` or `service.py`. `analysis/` and `diagram/` never import each other; what they share lives in `profile_fence.py`, `evidence.py` and `fingerprint.py` (so either package can be deleted on its own; the layer test checks it).
- **Builds on:** `LLM.generate_structured` and `CallType.OPPORTUNITIES` / `CallType.MAP` (spec 11); `Opportunity`, `StayHuman`, `ProcessDiagram`, `DiagramNode`, `DiagramFlow`, `OpportunityType`, `Grade` (spec 12 §3.11); `rank_nodes` (spec 12 §3.12); `normalize_for_matching`, `fence_untrusted`, `fence_instruction` (spec 11 §3.10).
- **Changes to existing code:** adds fields to the spec 12 sub-models (allowed by spec 12 §3.11; nothing renamed or removed). See §4.4.
- **Who calls it:** the assessment orchestrator `assess()` (spec 20) at *Finish* and when a specialist edit changes the steps (spec 21).

## 3. Behaviour

### 3.1 Worked example used in all three specs (20, 21, 22)

The **monthly cost review**, Europe (fixture `tests/fixtures/profiles/monthly_cost_review_eu.json`). Process fields: trigger "Month-end close is completed in SAP"; end result "A cost report with variance explanations"; who uses it "The CFO uses it to steer the site budgets"; pain "Every site sends its own spreadsheet and I copy the numbers into the master file by hand"; volume `{count: 1, period: "month"}`; owner "Head of Controlling"; same way everywhere `{same: "no", differences: "each site sends its own spreadsheet layout"}`; sensitive data: none row.

| # | Step (S01) | Owner | Roles involved | Systems | Inputs → outputs | Effort (duration, frequency) | Pain point | Approvals / exceptions |
|---|---|---|---|---|---|---|---|---|
| 1 | Collect site spreadsheets | Cost controller | Site controller | Outlook, Excel | site cost spreadsheets → set of site files | 6 hours, every month | sites send late and in different layouts | — / a site sends no file; I chase it by phone |
| 2 | Consolidate into the master file | Cost controller | none | Excel, SAP S/4HANA | set of site files, SAP cost centre report → consolidated cost file | 1 day, each time | I copy the numbers into the master file by hand | — / totals do not match SAP (back to step 1) |
| 3 | Analyse variances | Cost controller | none | Excel | consolidated cost file, budget → list of variances | 6 hours, monthly | the threshold check is done by eye | — / none |
| 4 | Chase explanations | Cost controller | Site manager | Outlook | list of variances, explanations from site managers → variance list with explanations | 15 minutes, 10 times a month | some site managers answer only after three reminders | — / no answer by day 3; escalate to the Head of Controlling |
| 5 | Write the variance summary | Cost controller | CFO | Excel, Outlook | variance list with explanations → cost report with variance summary | 6 hours, every month | I write the commentary from scratch every month | Head of Controlling, 1 day / none |

A second fixture, `monthly_cost_review_na.json`, is the North American version: same steps, `same: "yes"`, one template, exceptions only in steps 2 and 4.

### 3.2 The profile as the model sees it (`profile_fence.py`)

1. Both calls (and LABEL, spec 19, and ASSESS_STEPS, spec 26) get the same user payload: a lead-in line, then `fence_untrusted(render_profile(profile), "PROFILE")`. The system prompt carries `fence_instruction("PROFILE", "The process profile")`.
2. `render_profile` is owned by spec 14. This spec needs from it: one `Label: value` line per process field in registry order; then one block per step headed `--- STEP n: <name> ---` (n 1-based) with one line per S02–S12; none rows as `none`; empty as `(none)`; a proposed value followed by `(proposed from a document, not confirmed)`; `__meta` and `__skipped` never rendered (a skipped cell renders as `(none)`).
3. A profile value that contains `PROFILE>>>` cannot close the fence (spec 11 AC-11.31).

### 3.3 Evidence: the quote check (`evidence.py`)

Used by OPPORTUNITIES, stay-human steps and LABEL (spec 19). One rule: **the quote must be the expert's words, copied, from one stored value.**

1. **Values searched** (`profile_values(profile)`): every text in the profile, each as a separate value with its address and source:

   | Field | Values |
   |---|---|
   | P04, P06–P09 | The text |
   | P10–P14 | Each non-empty text sub-field (`raw`, `period`, `role`, `value`, `unit`, `qualitative`, `same`, `differences`) |
   | P15 | Each row's `item` and `detail` |
   | Each step | `name`, `goal`, `owner`, `handover`; each item of `activities`, `systems`, `pain_points`, `data.inputs`, `data.outputs`; `effort.duration`, `effort.frequency`; each row's `role`, `contribution`, `approver_role`, `waiting_time`, `description`; `decision_type.evidence` (S13, the expert's rules-or-judgement words; not the `kind`) *(as built 2026-11-20, short step walk)* |

   Address: the registry key (`process.business_pain`) or the step cell key (`process.substeps[2].pain_points`). Source: the field's `__meta.source` (`expert` when there is no meta). Proposed values are searched too; their source is `document`.
2. **Normalising** (both sides): `normalize_for_matching` (spec 11: NFKC, invisibles removed, look-alikes folded, lower case, whitespace collapsed); typographic quotes and apostrophes folded to `"` and `'`; en and em dashes to `-`. From the quote only: surrounding whitespace, quote marks and the punctuation `. , ; : ! ?` stripped.
3. **A quote is accepted** when its normalised form is a substring of one normalised value **and** it has at least 3 words, **or** it equals a whole value (any length). It may not contain `...` or `…` (no stitched quotes). Longer than 400 characters → rejected.
4. The first value that matches (in the order of the table) wins. The result is `EvidenceHit(key, source, quote)` where `quote` is the model's text with only rule-2 stripping applied.
5. `restrict_to_step(n)` limits the search to the values of step n (used by LABEL).
6. `restrict_to_step_or_process(n)` returns step n's values, then the process-field values, never another step's (used by ASSESS_STEPS, spec 26 §3.5).

| Quote from the model | Result |
|---|---|
| `"I copy the numbers into the master file by hand"` | Hit: `process.business_pain` (first in order), source expert |
| `copy the numbers into the master file` | Hit (substring, 7 words) |
| `“some site managers answer only after three reminders.”` | Hit: `process.substeps[4].pain_points` (curly quotes and full stop stripped) |
| `Outlook` | Hit: equals the whole value `process.substeps[1].systems` |
| `by hand` | Rejected: 2 words and not a whole value |
| `sites send late … by hand` | Rejected: stitched |
| `the system crashes every day` | Rejected: not in the profile |

### 3.4 OPPORTUNITIES: the call (`analysis/`)

1. **One call**, `generate_structured(OpportunitiesOut, CallType.OPPORTUNITIES, messages)`, budget from settings (spec 11 §3.2). Messages: system = `OPPORTUNITIES_SYSTEM`; user = "Find where automation or AI could help in this process profile:" + the fenced profile.
2. **Wire schema** (strict; every field required, no defaults, no numeric bounds):

   ```python
   class OpportunityOut(BaseModel):            # extra="forbid"
       title: str
       steps: list[int]                         # 1-based STEP numbers; [] = the whole process
       type: Literal["eliminate", "standardise", "workflow", "integration",
                     "document_ai", "ai_assistant", "ai_agent", "rpa"]   # pinned to OpportunityType
       what_changes: str; how: str; prepare_first: str
       impact: Literal["high", "medium", "low"]; impact_reason: str
       feasibility: Literal["high", "medium", "low"]; feasibility_reason: str
       evidence: str
   class StayHumanOut(BaseModel):  steps: list[int]; reason: str; evidence: str
   class OpportunitiesOut(BaseModel): summary: str; opportunities: list[OpportunityOut]; stay_human: list[StayHumanOut]
   ```

3. **System prompt** (`OPPORTUNITIES_SYSTEM`, one literal string, no `str.format`). Rules:

   | # | Rule given to the model |
   |---|---|
   | 1 | You are a senior process and automation analyst. Analyse only what the profile states. Never invent a system, volume, role, step or pain. A thin profile gives fewer opportunities, not imagined ones |
   | 2 | `steps` lists the `--- STEP n ---` numbers the change touches; `[]` only when it is about the whole process (for example a hand-over between all steps) |
   | 3 | `type` is one of the eight types, with their meanings (the table of product F-12.2, copied) |
   | 4 | Prefer `eliminate` and `standardise` over automating a broken step. When teams or sites do the process differently, propose `standardise` first |
   | 5 | `what_changes`: the step as it would run after the change, one or two sentences, present tense |
   | 6 | `how`: what the solution would do and the kind of tooling as a generic category ("a document-extraction service", "a workflow tool", "an integration between SAP S/4HANA and SharePoint"). Name a system only if the profile names it. Never a vendor or product the profile does not name |
   | 7 | `prepare_first`: what must be true before building it (a template, clean data, a written rule, access to a system) |
   | 8 | `impact` and `feasibility`: high, medium or low; each reason quotes the pain, effort, volume or system behind the grade |
   | 9 | `evidence`: the expert's words that support the opportunity, copied exactly from one field of the profile, at least three words or a whole short answer. No paraphrase, no joining of passages |
   | 10 | Do not estimate hours, savings or money; code computes them |
   | 11 | Order `opportunities` best first. At most 10 |
   | 12 | `stay_human`: steps that should stay with people, why, and the words that show it |
   | 13 | `summary`: two or three sentences on where the largest benefit is and what the single biggest lever is |
   | 14 | If nothing in the profile supports an opportunity, return an empty list and say so in `summary` |
   | — | The PROFILE fence sentence; "Return only JSON matching the schema." |

4. **Failure.** Any `LLMError` (empty, refused, truncated, invalid twice, unavailable, budget) raises `OpportunitiesFailedError` (chained). There is no fallback content: the report part shows a note (spec 20). An empty `opportunities` list is a valid result, not a failure.

### 3.5 OPPORTUNITIES: grounding (`ground_opportunities`, pure)

Each entry is checked on its own; a bad entry is dropped and counted, never fatal.

| # | Check | On failure |
|---|---|---|
| O1 | Only the first 50 raw entries are read | Rest ignored (`cap`) |
| O2 | `steps`: every number is an int (not a bool) in `1..N`, where N = number of steps. Duplicates removed, sorted | **Drop** the opportunity (`step`). *An invented step is an invented claim, so the whole opportunity goes* |
| O3 | `type` is an `OpportunityType` value | Drop (`invalid`) |
| O4 | `title` cleaned to one line (control characters to spaces, whitespace collapsed), capped at 200 characters with "…"; must be non-empty | Drop (`invalid`) |
| O5 | `what_changes` and `how` non-empty after cleaning; these, `prepare_first` and both reasons capped at 1,500 characters | Drop (`invalid`) |
| O6 | `impact`, `feasibility` are grades | Drop (`invalid`) |
| O7 | `evidence` passes the quote check (§3.3) | Drop (`quote`) |
| O8 | At most 12 opportunities are kept, in model order | Rest dropped (`cap`) |
| O9 | Code sets: `id` = `o1`, `o2`, … in kept order; `saving_share` = the configured default for the type (`rates.yaml`; *parked, R5: stored, read by nothing*); `review` = `pending`; `review_note` = ""; `evidence_key`, `evidence_source` from the hit; `blocked_by` = [] (filled by the path, spec 19) | — |

Stay-human entries: `steps` must be non-empty and all real (else drop, `step`); `reason` non-empty, capped at 600 (else drop); evidence passes §3.3 (else drop, `quote`); at most 6 kept. `summary` is cleaned and capped at 1,500 characters; a non-string or missing summary becomes "".

**Example.** The model returns six opportunities for the cost review. Kept, in order:

| id | Type | Steps | Title | Impact / feasibility | Evidence (hit) |
|---|---|---|---|---|---|
| o1 | document_ai | 1, 2 | Read the site spreadsheets into the master file | high / medium | "I copy the numbers into the master file by hand" (`process.business_pain`) |
| o2 | ai_assistant | 5 | Draft the variance summary | medium / high | "I write the commentary from scratch every month" (`process.substeps[5].pain_points`) |
| o3 | workflow | 4 | Chase variance explanations automatically | medium / high | "some site managers answer only after three reminders" (`process.substeps[4].pain_points`) |
| o4 | standardise | 1 | Agree one site template | medium / high | "each site sends its own spreadsheet layout" (`process.variation`) |

Dropped: an `integration` opportunity citing step 7 (`step`); an `rpa` opportunity quoting "the system crashes every day" (`quote`). Stay human: steps [5], "The commentary to the CFO is the controller's judgement; a person decides what to say", evidence "write the commentary". Saving shares from configuration (*parked, R5*): 0.6, 0.4, 0.4, 0.2.

### 3.6 Re-running and review carry-over

1. The assessment stores `steps_hash = ai_input_fingerprint(profile)` (§3.10). When a later assessment run (spec 20) finds a different hash, OPPORTUNITIES runs again.
2. `carry_reviews(old, new)`: for each new opportunity, the first unused old opportunity with the **same type and the same steps** gives it its `review`, `review_note` and, if the review is `adjusted`, its `saving_share`. Others start `pending`. Used by spec 21 after specialist edits.

### 3.7 MAP: the call (`diagram/`)

1. **One call**, `generate_structured(ProcessDiagramOut, CallType.MAP, messages)`. User message: "Draw the BPMN process diagram for this process profile:" + the fenced profile.
2. **Wire schema** (strict): `lanes: list[str]`; `nodes: list[{id: str, type: "start"|"task"|"gateway"|"end", label: str, lane: int, step_index: int|null, marker: <flat marker union>}]`; `flows: list[{source: str, target: str, label: str, is_default: bool}]`. Marker union: `none, message, timer, conditional, signal, user, manual, service, send, receive, script, business_rule, exclusive, parallel, inclusive, event_based, terminate, error`.
3. **Legal markers per type** (`DIAGRAM_MARKERS_BY_TYPE`, on the storage model; a test pins the wire union to it):

   | Type | Markers | Default |
   |---|---|---|
   | start | none, message, timer, conditional, signal | none |
   | task | none, user, manual, service, send, receive, script, business_rule | none |
   | gateway | exclusive, parallel, inclusive, event_based | exclusive |
   | end | none, message, terminate, error | none |

4. **System prompt** (`MAP_SYSTEM`): one literal string with nine requirements: only what the profile states; lanes = role names as written, step owners first, never a person; exactly one task per step in order, `step_index` = step number, lane = owner's lane, label = step name; task marker from the step's systems (`manual` with no system, `user` with one, others only when the profile is explicit); gateways only where the profile states a decision, approval or exception, labelled as a question of at most six words, with a gateway marker, labelled branches and at most one default; one start and at least one end with markers and 2–6 word state labels built from the trigger and end result; flows in work order, everything reachable; short unique ids; valid BPMN (one flow in and out per task, merge gateways where paths join, a gateway either splits or merges).
5. **Failure.** `LLMEmptyResponseError` and `LLMInvalidOutputError` are a bad *reply*: grounding gets `None` and returns the linear map. `LLMUnavailableError`, `LLMBudgetExceededError` and a timeout are a failed *call*: `run_map` raises `MapCallFailedError`; the orchestrator then stores the linear map (spec 20). Either way a finished profile always has a map (F-13.2).

### 3.8 MAP: grounding (`grounding.py`, pure, never mutates its input)

Constants: label 60 chars, flow label 20, id 40, event label 40 chars and 6 words, at most 40 nodes, at most 8 lanes (the rest share `Other`), at most 200 raw entries read per list.

**Cleaning.** `_clean(value, limit)`: non-strings → ""; control characters → space; whitespace collapsed; longer than `limit` → cut to `limit − 1` + "…".

**Known roles.** Each step's owner and its roles-involved rows (none rows add nothing), then the process owner's role; compared case-insensitively; the first spelling wins.

| # | Rule | Result |
|---|---|---|
| G1 | The reply is not a mapping | Linear map |
| G2 | A reply lane counts only if its cleaned name is a known role; lane indexes pointing elsewhere mean "no lane" | — |
| G3 | A node is skipped if not a mapping, its cleaned id is empty or already used, or its type is unknown | Skipped |
| G4 | A **task** is skipped unless `step_index` is a real int (not a bool, not "3") in `1..N` and no task drew that step yet (first wins) | Skipped |
| G5 | A task's lane is kept only if it is a role **of that step** (owner or roles involved); otherwise the step owner's lane; with no owner, `Other` | — |
| G6 | A task's label is always the real step name (capped), or "Step n" when the name is empty | — |
| G7 | Every marker must be legal for its type (table §3.7), else the type's default. A task marker that claims a system (`user`, `service`, `script`, `business_rule`, `send`, `receive`) becomes `manual` when the step lists no system | — |
| G8 | After nodes: some step has no task, or more than 40 nodes | Linear map |
| G9 | A flow is dropped if not a mapping, its source or target is unknown, it is a self-loop or a duplicate pair, it enters a start or leaves an end. Labels capped at 20 | Dropped |
| G10 | `is_default` holds only if literally `true`, the source is a gateway, and that gateway has no default yet. Flows added by repairs are never default | — |
| G11 | One start: extra starts are removed with their flows; none → a start is added. A start with no outgoing flow gets one to step 1's task. No end → an end is added | — |
| G12 | Orphans, repeated until stable (at most nodes + 1 rounds): a gateway or end with no incoming flow is removed (but the only end is kept and wired). A task with no incoming flow is wired from the previous step's task (step 1: from the start). A non-end node with no outgoing flow is wired to the next step's task, else to the first end | — |
| G13 | Every node is reachable from the start and can reach an end | Else linear map |
| G14 | Ranks of the model's own graph (`rank_nodes`, before merges are added): the tasks' ranks never decrease from step 1 to step N | Else linear map |
| G15 | BPMN rule 4: a gateway with one flow in and one out is removed; the surviving flow takes the removed flow's label and default if it had none. If removal would create a self-loop or a duplicate flow | Else linear map |
| G16 | BPMN rule 3: a task or the start with more than one outgoing flow hides a decision code cannot name | Linear map |
| G17 | BPMN rule 6: a splitting `exclusive`, `inclusive` or `event_based` gateway with an unlabelled, non-default branch | Linear map |
| G18 | BPMN rule 5: a gateway that both merges and splits gets a merge gateway in front | — |
| G19 | BPMN rule 2: a task or end with several incoming flows gets a merge gateway in front. Merge ids `merge`, `merge2`, … | — |
| G20 | Merge marker: `exclusive` if a flow arriving is a back edge (a loop); else the marker of the nearest (highest-rank) splitting gateway that reaches at least two of the arriving flows' sources by forward edges; else `exclusive` | — |
| G21 | More than 40 nodes after repairs (rule 9) | Linear map |
| G22 | Lanes for gateways and events: a neighbour's lane, repeated; else step 1's lane. Lanes are ordered by the tasks' lanes in step order, then any others; past 8, `Other` | — |
| G23 | Start label: the model's own if at most 40 characters and 6 words, else `short_event_label(trigger)`; end label likewise from the end result. A start or end left without a label loses a trigger marker (`message`, `timer`, `conditional`, `signal` → `none`) | — |
| G24 | Any exception inside grounding | Logged; linear map |

**`short_event_label(text)`:** whitespace collapsed; a leading "when", "if", "once" or "after" dropped; first letter capitalised. If ≤ 40 characters, kept whole. Else the first clause (break at `, ; : .` followed by a space or the end, at "(", at " - ", or before " and | when | because | which | that "), if it has at least 3 words and fits. Else cut at the last space before 40 and "…" appended. So "1,000" and "10:30" are never cut inside.

**`linear_diagram(profile)`:** `None` with no steps. Otherwise start (label from the trigger, lane of step 1's owner) → one task per step (owner's lane, or `Other`; marker `user` if the step lists a system, else `manual`; label = step name) → end (label from the end result, lane of the last owner); lanes in owner order with the 8-lane cap; `simplified = True`.

**Data objects and data stores (by code, never by the model).** After grounding or the linear map, `to_process_diagram` adds from the profile:

| Element | One per | Label | Id |
|---|---|---|---|
| Data object, input | task whose step has inputs | `short_list(inputs)`: cleaned, de-duplicated, at most 3 joined by "; ", then " +N" | `do<n>i` |
| Data object, output | task whose step has outputs | same, from outputs | `do<n>o` |
| Data store | distinct system across all steps (case-insensitive, first spelling) | the system name (capped 60) | `ds1`, `ds2`, … in first-use order, with the list of steps using it |

**Example.** For the cost review the model draws a gateway "Totals match SAP?" after step 2 with "no" back to step 1. Grounding keeps it, adds an exclusive merge in front of step 1 (a loop arrives), keeps lanes `Cost controller` (and drops an invented lane "Finance Bot"), relabels every task with the real step names and adds data objects for 5 tasks and data stores `Outlook`, `Excel`, `SAP S/4HANA`. A reply that left out step 4 gives the linear map, `simplified: true`.

### 3.9 Logging (F-24)

One `assessment_call` log line per call: `call` (`OPPORTUNITIES` or `MAP`), `outcome`, `duration_ms`, `kept`, `dropped` (counts by reason: `step`, `quote`, `invalid`, `cap`; for MAP: `simplified` true/false and the fallback rule, for example `G14`). Never any text from the profile or the reply.

### 3.10 Fingerprints (`fingerprint.py`)

| Function | Hashes (SHA-256 of canonical JSON, sorted keys) | Stored on | When it differs |
|---|---|---|---|
| `ai_input_fingerprint(profile)` | P04, P06–P15, `substep_count` and every step's S01–S12 leaves. Not `__meta`, `__skipped`, flags, roll-ups, P01–P03, P05 | `Assessment.steps_hash` (and part of `StepAssessment.inputs_hash`, spec 26) | OPPORTUNITIES, LABEL and ASSESS_STEPS run again |
| `map_fingerprint(profile)` | Per step: name, owner, role names, systems, inputs, outputs, approver roles, exception descriptions and pointers; plus trigger, end result, owner role | `ProcessDiagram.steps_hash` | MAP runs again |

Confirming a proposal changes only `__meta`, so neither hash changes. Both hash the full `Profile` dump, so absent and empty values hash the same.

## 4. Interfaces

### 4.1 Shared

```python
# artifacts/profile_fence.py
PROFILE_FENCE_INSTRUCTION: str
def fence_profile(profile: Mapping[str, Any]) -> str

# artifacts/evidence.py
@dataclass(frozen=True)
class EvidenceHit: key: str; source: Literal["expert", "document", "specialist"]; quote: str
def profile_values(profile: Mapping[str, Any]) -> list[tuple[str, str, str]]   # (key, text, source)
def normalise_quote(text: str) -> str
def find_evidence(quote: Any, values: Sequence[tuple[str, str, str]]) -> EvidenceHit | None
def restrict_to_step(values: Sequence[tuple[str, str, str]], step: int) -> list[tuple[str, str, str]]

# artifacts/fingerprint.py
def ai_input_fingerprint(profile: Mapping[str, Any]) -> str
def map_fingerprint(profile: Mapping[str, Any]) -> str
```

### 4.2 Opportunities

```python
# artifacts/analysis/analysis.py
class OpportunitiesFailedError(Exception): ...
@dataclass(frozen=True)
class OpportunitiesResult:
    summary: str; opportunities: list[Opportunity]; stay_human: list[StayHuman]
    dropped: dict[str, int]            # {"step": 1, "quote": 1, "invalid": 0, "cap": 0}
async def run_opportunities(profile: Mapping[str, Any], llm: LLM, rates: Rates) -> OpportunitiesResult
def ground_opportunities(reply: OpportunitiesOut | Mapping[str, Any], profile: Mapping[str, Any],
                         rates: Rates) -> OpportunitiesResult            # pure
def carry_reviews(old: Sequence[Opportunity], new: Sequence[Opportunity]) -> list[Opportunity]
```

### 4.3 Map

```python
# artifacts/diagram/grounding.py  (pure)
@dataclass
class GroundedDiagram: lanes: list[str]; nodes: list[DiagramNode]; flows: list[DiagramFlow]; simplified: bool
def ground_diagram(reply: Any, profile: Mapping[str, Any]) -> GroundedDiagram | None   # None only without steps
def linear_diagram(profile: Mapping[str, Any]) -> GroundedDiagram | None
def short_event_label(text: str) -> str

# artifacts/diagram/diagram.py
class MapCallFailedError(Exception): ...
async def run_map(profile: Mapping[str, Any], llm: LLM) -> ProcessDiagram   # bad reply → simplified map
def linear_process_diagram(profile: Mapping[str, Any]) -> ProcessDiagram | None
def to_process_diagram(grounded: GroundedDiagram, profile: Mapping[str, Any]) -> ProcessDiagram
```

### 4.4 Fields added to the spec 12 models

| Model | Added | Meaning |
|---|---|---|
| `Opportunity` | `evidence_key: str`, `evidence_source: "expert" \| "document" \| "specialist"` | Where the quote was found |
| `Opportunity` | `blocked_by: list[str]` | Readiness dimension keys that put it in *prepare first* (spec 19) |
| `StayHuman` | `evidence_key: str` | As above |
| `ProcessDiagram` | `data_objects: list[DataObject{id, step_index, direction: "input" \| "output", label}]`, `data_stores: list[DataStore{id, label, steps: list[int]}]` | Built by code from the profile |
| storage module | `DIAGRAM_MARKERS_BY_TYPE: dict[str, tuple[str, ...]]` | Table §3.7 |

## 5. Implications

- **Other components:** spec 20's `assess()` calls `run_opportunities` and `run_map` in parallel with timeouts; spec 19 fills `blocked_by` and computes value from the kept opportunities; spec 20 draws the map from `ProcessDiagram` alone (data objects and stores included); spec 21 uses `carry_reviews`; spec 22 writes BPMN XML from the same model.
- **Data:** fields of §4.4 on `assessment.opportunities[]`, `assessment.stay_human[]`, `assessment.diagram`. No migration (no stored data yet).
- **Config:** reads `rates.saving_share` (spec 10 `Rates`). No new keys.
- **Security and privacy:** the whole profile is untrusted text inside the PROFILE fence. Model output is never trusted: every step, quote, lane, flow and marker is checked here. Logs carry counts only. The map shows roles, never names (prompt rule; lanes are only roles that exist in the profile).
- **Cost and latency:** two calls per *Finish* (plus LABEL, spec 19), run in parallel; repeated only when a fingerprint changes.

## 6. Acceptance criteria

| ID | Given / when / then |
|---|---|
| AC-18.1 | `fence_profile` wraps `render_profile` output in exactly one `<<<PROFILE` / `PROFILE>>>` pair; a value containing `PROFILE>>>` does not close it; both system prompts contain `PROFILE_FENCE_INSTRUCTION` |
| AC-18.2 | `strict_json_schema(OpportunitiesOut)` and `strict_json_schema(ProcessDiagramOut)` build without error (strict, closed objects, no `$defs`) |
| AC-18.3 | The wire `type` literal equals the values of `OpportunityType`; the grade literal equals `Grade`; the wire marker union equals the union of `DIAGRAM_MARKERS_BY_TYPE`; the wire node types equal the storage node types |
| AC-18.4 | `run_opportunities` makes one `generate_structured` call with `CallType.OPPORTUNITIES`, the system prompt and the fenced profile (checked on `FakeLLM.calls`) |
| AC-18.5 | Given the §3.5 reply on the EU fixture, the result keeps o1–o4 with the shown steps, types and evidence keys, and `dropped == {"step": 1, "quote": 1, "invalid": 0, "cap": 0}` |
| AC-18.6 | An opportunity with any step number outside `1..N`, a bool, or a non-int is dropped (`step`); `[]` is kept as whole-process; `[2, 1, 2]` becomes `[1, 2]` |
| AC-18.7 | An opportunity whose evidence is not in the profile is dropped (`quote`), whatever its grades |
| AC-18.8 | Quote check: substring of one value with ≥ 3 words → hit; a whole short value ("Outlook") → hit; 2-word fragment → miss; text with "…" or "..." → miss; > 400 characters → miss; a passage spanning two values → miss |
| AC-18.9 | Quote check ignores case, whitespace runs, curly quotes, dash style, zero-width characters and trailing punctuation; it reports the key and the source (`document` for a proposed value) |
| AC-18.10 | An entry with an unknown type, empty title, empty `what_changes` or `how`, or a non-grade is dropped (`invalid`); one bad entry never drops the others |
| AC-18.11 | Title capped at 200, long texts at 1,500, summary at 1,500, each ending in "…" when cut; a non-string summary becomes "" |
| AC-18.12 | More than 12 grounded opportunities → the first 12 kept, `cap` counted; only the first 50 raw entries are read |
| AC-18.13 | Kept opportunities get ids `o1…`, `review == "pending"`, `saving_share` = `rates.saving_share[type]`, `blocked_by == []` |
| AC-18.14 | Stay-human entries with no steps, an unknown step, an empty reason or an unverified quote are dropped; at most 6 kept |
| AC-18.15 | An empty `opportunities` list with a summary is a valid result (no error) |
| AC-18.16 | Each `LLMError` subclass raised by the fake (empty, invalid, unavailable, budget) makes `run_opportunities` raise `OpportunitiesFailedError` |
| AC-18.17 | `carry_reviews` copies review, note and (for `adjusted`) share from an old opportunity with the same type and steps; each old one is used once; others are `pending` |
| AC-18.18 | `ai_input_fingerprint` changes when a pain point, an effort or P14 changes, and not when only `__meta`, a flag or P01 changes; `map_fingerprint` changes with a step name, owner, role, system, input, output, approval or exception, not with a pain point |
| AC-18.19 | `run_map` makes one `generate_structured` call with `CallType.MAP` and the fenced profile; a good reply becomes a `ProcessDiagram` with `simplified: false` and `steps_hash == map_fingerprint(profile)` |
| AC-18.20 | A good reply with a gateway and a loop is kept: every task labelled with the real step name, the loop's merge gateway is `exclusive` |
| AC-18.21 | Invented, missing, non-int, bool, string ("3") and repeated `step_index` tasks are dropped; a reply that leaves a step undrawn falls back to the linear map |
| AC-18.22 | A lane naming no real role is dropped; a task in a lane not of its step moves to its owner's lane; a task may sit in the lane of a role involved in that step; lane names collapse case-insensitively; more than 8 lanes fold into `Other` |
| AC-18.23 | Markers: an illegal marker becomes the type default; a gateway never has `none` (defaults to `exclusive`); `user`/`service`/`script`/`business_rule`/`send`/`receive` on a step without systems become `manual`; `manual` is always legal; an end-only marker on a start becomes `none` |
| AC-18.24 | Flows to unknown ids, self-loops, duplicates, flows into a start or out of an end are dropped; a non-boolean `is_default` is false; only one default survives per gateway; a default not leaving a gateway is rejected; repair flows are never default |
| AC-18.25 | Missing start and end are added; extra starts are removed; a dead-end task is wired onward; an orphan task is wired from the previous step; an unreachable gateway is dropped |
| AC-18.26 | Steps met out of order (ranked on the model's graph) fall back; a merge added on one branch does not break the order check |
| AC-18.27 | Merges: a loop back into a task gets an exclusive merge; a skip path gets a merge of the split's type; parallel branches meet in a parallel merge before the end; a merging-and-splitting gateway gets a merge in front; an outer decision's merge stays exclusive with a nested parallel fork |
| AC-18.28 | A pass-through gateway is removed and hands its label to the surviving flow; one that would create a self-loop falls back |
| AC-18.29 | A task with two outgoing flows falls back; an unlabelled decision branch falls back; an unlabelled default branch is allowed |
| AC-18.30 | More than 40 nodes (in the reply or after repairs) falls back |
| AC-18.31 | Start and end labels: a short model label is kept; a missing one uses the profile text when it fits; a long one, or one over six words, is replaced by `short_event_label` of the profile text; a trigger marker on an unlabelled event becomes `none` |
| AC-18.32 | `short_event_label` keeps text that fits; cuts at the first clause; never inside "1,000" or "10:30"; drops a leading "When"; never keeps a two-word fragment as the clause; cuts a single huge word with "…" |
| AC-18.33 | Labels are capped and control characters stripped; wrong value types anywhere in the reply never raise |
| AC-18.34 | `ground_diagram` does not mutate its input (deep copy compared); with no steps it returns `None` |
| AC-18.35 | `linear_diagram`: start → each step → end; owners' lanes, `Other` for a step without an owner, 8-lane cap; marker `user` with a system, `manual` without; `simplified: true` |
| AC-18.36 | Data objects and stores come from the profile only: one input and one output object per task with data, one store per distinct system with its steps; labels de-duplicated, at most 3 items then "+N" |
| AC-18.37 | `LLMEmptyResponseError` or `LLMInvalidOutputError` from MAP → `run_map` returns the linear map, `simplified: true`; `LLMUnavailableError` or `LLMBudgetExceededError` → `MapCallFailedError` |
| AC-18.38 | **Grounding fuzz:** 300 seeded random replies (random ids including duplicates and `None`, random types including bogus, lanes in and out of range, random step indexes including strings and bools, random markers, random flows including ghosts and self-loops, random lane lists, random `is_default` values) on the EU fixture: `ground_diagram` never raises and always returns a diagram where each step 1..5 has exactly one task with its real name, every lane is a known role or `Other`, every marker is legal for its type, every node is reachable from the start and reaches an end, and there are at most 40 nodes |
| AC-18.39 | One `assessment_call` log line per call with outcome and drop counts; no profile or reply text appears in any log record (sentinel string test) |
| AC-18.40 | The layer test fails if `artifacts/analysis` imports `artifacts/diagram` or the other way round, or if either imports `export` |

## 7. Test plan

| Test file | Covers |
|---|---|
| `tests/unit/process_discovery/artifacts/test_profile_fence.py` | AC-18.1 |
| `tests/unit/process_discovery/artifacts/test_evidence.py` | AC-18.8, 20.9 |
| `tests/unit/process_discovery/artifacts/test_fingerprint.py` | AC-18.18 |
| `tests/unit/process_discovery/artifacts/test_analysis_schemas.py` | AC-18.2, 20.3 (opportunity half) |
| `tests/unit/process_discovery/artifacts/test_analysis_prompts.py` | Every rule of §3.4 table present; fence instruction; no `str.format` placeholders left |
| `tests/unit/process_discovery/artifacts/test_analysis_grounding.py` | AC-18.5–20.15, 20.17 |
| `tests/unit/process_discovery/artifacts/test_analysis_call.py` | AC-18.4, 20.16, 20.39 (with `FakeLLM`) |
| `tests/unit/process_discovery/artifacts/test_diagram_schemas.py` | AC-18.2, 20.3 (map half) |
| `tests/unit/process_discovery/artifacts/test_diagram_prompts.py` | The nine requirements present; fence instruction |
| `tests/unit/process_discovery/artifacts/test_diagram_grounding.py` | AC-18.20–20.36 (one test per rule, with adversarial replies) |
| `tests/unit/process_discovery/artifacts/test_diagram_fuzz.py` | AC-18.38 (`random.Random(1234)`, 300 cases) |
| `tests/unit/process_discovery/artifacts/test_diagram_call.py` | AC-18.19, 20.37, 20.39 |
| `tests/unit/process_discovery/test_architecture.py` (spec 10) | AC-18.40 |

Fixtures `tests/fixtures/profiles/monthly_cost_review_{eu,na}.json` are full `Profile` dumps (spec 12) shared by specs 18–20. Tests use real producer output (`profile_values`, the fixtures), never hand-typed keys.

## 8. Out of scope

| What | Where |
|---|---|
| LABEL, value, readiness, `blocked_by` and the path | Spec 19 |
| Running the calls in parallel, timeouts, outcomes, saving, the report and the PDF drawing of the map | Spec 20 |
| Specialist review of opportunities and shares; re-running after edits | Spec 21 |
| BPMN 2.0 XML export | Spec 22 |
| `render_profile` | Spec 14 |

## 9. Open questions

| # | Question | Default until decided |
|---|---|---|
| Q1 | Drop an opportunity that cites one invalid step, or keep it as process-wide? | Drop: an invented step is an invented claim (F-12.3) |
| Q2 | Is "at least 3 words or a whole value" the right floor for a quote? | Yes; tune with the evaluation set |
| Q3 | Should code also check that `how` names no system outside the profile and the application list? | No; prompt rule only, spot-checked in evaluation |
| Q4 | If spec 14 does not render proposed values with the "(proposed …)" marker, who adds it? | Spec 14 owns `render_profile`; WS2 raises it with the lead |
| Q5 | Store data objects and stores on the diagram (here) or compute them at draw time? | Store them: the screen, the PDF and the BPMN export then show the same thing, and `map_fingerprint` keeps them current |
