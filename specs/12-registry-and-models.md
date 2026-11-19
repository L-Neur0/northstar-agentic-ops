# 12 · Field registry, Verdicts, taxonomy, rubric and models

> **Status:** built · **Implements:** F-05 (product); the vocabulary behind F-04, F-06, F-07, F-08, F-09, F-10, F-11, F-22; architecture §3.2, §5 · **Depends on:** spec 10
> **Contract:** C1 of the [implementation plan](03-implementation-plan.md). Every other workstream codes against this spec. A change here goes through the lead.
> **Code:** `backend/app/services/process_discovery/domain/{field_spec,taxonomy,scope,node_order}.py`, `backend/app/models/process_discovery_schemas.py`, `config/nig/taxonomy.yaml`
> **Tests:** `backend/tests/unit/process_discovery/domain/`, `backend/tests/unit/models/`

## 1. Purpose

This spec defines, once, what a field is and when it counts. It holds the field registry (P01–P16, S01–S12, D01–D02), the Verdict that grades a field, the provenance of every written value (who wrote it, and whether it is only a proposal), the company's cluster taxonomy, the process-or-task rubric, and the Pydantic models that store and send the session. Everything else (completeness, phases, prompts, whitelists, the review screen) is derived from these definitions. Nothing restates them.

## 2. Where it sits

- **Layer.** `domain` is the bottom of the engine. It imports only the standard library and `pydantic`, never another engine package and never `app.*`. It does no I/O and reads no clock: YAML is read by `app/core/config.py` (spec 10), and times are passed in.
- **Models.** `app/models/process_discovery_schemas.py` sits outside the engine. It may import `domain.field_spec`, `domain.taxonomy` and `domain.scope` (constants, enums). The domain never imports the models.
- **No import cycle.** `app/core/config.py` and the models import domain modules. So the engine package `app/services/process_discovery/__init__.py` (the façade, spec 15) must load `service.py` lazily (module `__getattr__`). Importing `app.services.process_discovery.domain.field_spec` must never import `service.py`. AC-12.44 checks this.
- **Exists today:** the scaffold, `Settings` and `load_company_config` (spec 10). `CompanyConfig.taxonomy` is the `Taxonomy` model defined here; `CompanyConfig.wording` is the `WordingOverrides` model defined here.
- **Changes to existing code:** none. Spec 10's placeholder models for taxonomy and wording are replaced by the ones here.

## 3. Behaviour

### 3.1 Phases

| Value | Meaning | Collects |
|---|---|---|
| `context` | Who the expert is | P01–P03 |
| `find` | Find a process in the routine; name it; place it | P04–P05 |
| `boundaries` | Start, end, who uses it, pain | P06–P09 |
| `measure` | Volume, owner, time, target, variation, sensitive data | P10–P15 |
| `step_count` | How many main steps | P16 |
| `steps` | The step walk (a loop, not a stage) | S01–S12 per step |
| `confirm` | Confirm the lists of roles and systems | flags |
| `review` | Ask deferred fields again | deferred P fields |
| `finished` | *Finish* pressed. Terminal | — |
| `no_candidate` | Closed by the expert: nothing worth mapping. Terminal | — |

1. `COLLECTING_PHASES = (context, find, boundaries, measure, step_count)`. `PHASE_ORDER` is the eight non-terminal phases in the order above. The two terminal values are not in `PHASE_ORDER`.
2. In `field_spec.py` phases are plain strings. The `Phase` enum lives in the models. A test checks that they match (AC-12.4).

### 3.2 Field kinds, sub-fields and Verdicts

**Kinds.** `text` · `list` (of strings) · `number` (whole number) · `object` (fixed sub-fields) · `object_list` (rows with fixed sub-fields). Sub-field kinds: `text`, `list`, `number`, `bool`.

**Empty values.** `text` → `""`; `list`, `object_list` → `[]`; `number` → `null`; `bool` → `false`; `object` → every sub-field at its empty value.

**A value is present** when: text has non-blank characters; a list or object_list is non-empty; a number is not null (and not a bool); a bool is literally `true`. **A stored `false` is never an answer.**

**Verdict.** `Verdict(status, missing, reason)`.

| Status | Means | Counts? |
|---|---|---|
| `complete` | Answered | Yes, if confirmed (§3.6) |
| `partial` | Empty, or part of the answer is there. `missing` names what is still needed | No |
| `invalid` | Answered wrongly (out of range, wrong unit, not in the configured list). `reason` says why | No |

`reason` is always one finished sentence a person can read. It goes unchanged to the question (F-02), the review screen (F-17) and the turn log (F-24). It is empty only when the status is `complete`.

**How `evaluate_field` grades** (one function, the single definition of "answered"):

1. If the field has a `validator`, the validator decides. It may read other fields of the profile and the company vocabulary.
2. `object`: the field has `complete_when` groups, an OR of ANDs. It is complete when **any one** group has all members present. Without groups, the single group is "every required sub-field".
3. If no group is satisfied, the field is `partial`, and `missing` is the group **closest to satisfied**: the one with the **most members already present**. A tie goes to the **first declared** group. So an empty volume asks for "count, period", not for "raw".
4. `object_list`: complete if one row is the none sentinel, or one row satisfies its groups. Otherwise `partial`, with the missing part of the best row (or the first group if there are no rows), and the extra sentence `"There are none" is also an answer.`
5. `text`, `list`, `number`: complete when present, else `partial` with `"<Label> has not been answered yet."`
6. No field declares both `complete_when` and a `validator` (AC-12.3).

**Reason sentences** (the label is the field label, or its wording override, §3.10):

| Case | Sentence |
|---|---|
| Not answered | `Trigger has not been answered yet.` |
| Part of a group missing | `Volume still needs: period.` (sub-field labels, comma-separated) |
| object_list, no usable row | `Approvals still needs: approver role. "There are none" is also an answer.` |
| Validator | The validator's own sentence (table in §3.4) |

**Worked examples.**

| Field | Stored value | Verdict |
|---|---|---|
| P10 volume | `{"count": 400, "period": "", "raw": ""}` | `partial`, missing `("period",)`, "Volume still needs: period." |
| P10 volume | `{"count": null, "period": "", "raw": "a few hundred a month"}` | `complete` (second group) |
| P10 volume | all empty | `partial`, missing `("count", "period")` |
| P11 owner | `{"role": "", "none_identified": false}` | `partial`, missing `("role",)` |
| P11 owner | `{"role": "", "none_identified": true}` | `complete` ("nobody owns it") |
| P12 time today | `{"value": "", "unit": "", "qualitative": "takes most of the first week", "estimated": false}` | `complete` |
| S10 approvals | `[{"none": true}]` | `complete` |
| S10 approvals | `[]` | `partial`, "Approvals still needs: approver role. "There are none" is also an answer." |

### 3.3 Sentinels and sidecars

| Name | Shape | Where | Meaning |
|---|---|---|---|
| None row | `[{"none": true}]` | Any `object_list` (P15, S04, S10, S11) | "Asked, and the answer is none." Counts as complete. Written only on an empty field; any real row replaces it (spec 13) |
| None flag | `"none_identified": true` | P11 process owner | Same meaning for an object. A later real `role` clears it (spec 13) |
| Skipped cells | `"__skipped": ["goal", …]` | On a step row | Cells given up after the cell limit: settled for the walk, missing for the score. A later real answer removes the leaf (spec 13) |
| Provenance | `"__meta": {…}` | On the profile (context and process fields) and on each step row (cells) | Who wrote each field and whether it is confirmed (§3.6) |
| Rejected step count | `"substep_count_rejected": 13` | `process` | The last out-of-range number of steps, kept so the agent can refer to it. Cleared by an in-range count |

Sidecar keys start with `__`. They are never fields: never scored, never offered to a model, never graded.

### 3.4 The registry

`FieldSpec` attributes: `id`, `key`, `label`, `kind`, `phase`, `weight`, `question`, `rule`, `subfields`, `complete_when`, `validator`, `extract` (the EXTRACT call may write it), `propose` (a document or an idea may propose it), `max_items` (soft, never truncates), `max_asks` (override of the ask limit).

**Address forms.** Every caller can name a field in three ways, and all three resolve (`resolve_address`):

| Form | Example | Resolves to |
|---|---|---|
| Dotted key | `department`, `process.volume` | The process-level spec |
| Step cell (index **1-based**) | `process.substeps[2].systems` | Spec S06, step 2 (storage index 1) |
| Bare leaf | `volume`, `trigger`, `name` | The process-level spec with that leaf. Bare leaves never resolve to step specs: `name` is P04, not S01 |

Context fields (P01–P03) are top-level keys. All other process fields live under `process`. Step specs use the bare leaf as their key; their wire form is `process.substeps[i].<leaf>`.

#### Process fields (declaration order = ask order)

| ID | Key | Label | Kind and sub-fields | W | Phase | Complete when | Extract | Propose |
|---|---|---|---|---|---|---|---|---|
| P01 | `department` | Department | text | 1 | context | Present | ✓ | — |
| P02 | `user_function` | Role | text | 1 | context | Present | ✓ | — |
| P03 | `region` | Region | text | 1 | context | Validator: one of the configured regions (case-insensitive) | ✓ | — |
| P04 | `process.name` | Process name | text | 1 | find | Present | ✓ | ✓ |
| P05 | `process.cluster` | Cluster | object `{code, name, decided_by}` | 1 | find | Validator: `code` is a taxonomy code | — | — |
| P06 | `process.trigger` | Trigger | text | 1 | boundaries | Present | ✓ | ✓ |
| P07 | `process.end_result` | End result | text | 1 | boundaries | Present | ✓ | ✓ |
| P08 | `process.value_at_end` | Who uses the result | text | 1 | boundaries | Present | ✓ | ✓ |
| P09 | `process.business_pain` | Business pain | text | 1 | boundaries | Present | ✓ | ✓ |
| P10 | `process.volume` | Volume | object `{count: number, period: text, raw: text?}` | 1 | measure | `(count, period)` or `(raw)` | ✓ | ✓ |
| P11 | `process.process_owner` | Process owner | object `{role: text, none_identified: bool?}` | 1 | measure | `(role)` or `(none_identified)` | ✓ | ✓ |
| P12 | `process.baseline_metric` | Time today | object `{value: text, unit: text, qualitative: text?, estimated: bool?}` | **2** | measure | `(value, unit)` or `(qualitative)` | ✓ | ✓ |
| P13 | `process.target_metric` | Target | object `{value: text, unit: text}` | **2** | measure | Validator: value and unit, same unit as P12 | ✓ | ✓ |
| P14 | `process.variation` | Same way everywhere | object `{same: text, differences: text?}` | 1 | measure | Validator: `same` is `yes`; or `no`/`partly` with `differences` | ✓ | ✓ |
| P15 | `process.sensitive_data` | Sensitive data or regulation | object_list `{item: text, detail: text?}` | 1 | measure | One row, or the none row | ✓ | ✓ |
| P16 | `process.substep_count` | Number of main steps | number | 1 | step_count | Validator: whole number 2–6 | ✓ | — |

`?` marks an optional sub-field. **Process points: 18** (14 × 1 + 2 × 2).

Questions are the default wording of [product §5.1](01-product.md#51-process-fields-asked-in-this-order), copied verbatim. P05 has no question (`""`): the agent proposes a cluster and the expert confirms it (F-07). Each spec's `rule` is one or two plain sentences for the prompts. Rules that carry product behaviour:

| ID | Rule (summary) |
|---|---|
| P01 | A unit name, not a job title |
| P02 | The expert's own role, never a person's name |
| P04 | A process (five signals, F-06), named in the expert's words; written only once they agree |
| P05 | Set only by code from a confirmed proposal, a named cluster or the picker. Never from a model or a document |
| P09 | If the real pain is in another process, offer to switch before measuring |
| P11 | A role, never a name. "Nobody owns it" is an answer (`none_identified`) |
| P12 | A value with a unit if they have one, else their description. Mark estimates as estimated |
| P13 | Same unit as the time today |
| P14 | `same` is `yes`, `no` or `partly`; for `no`/`partly`, say what differs |
| P15 | Personal or sensitive data, or a named regulation. "None" is an answer (none row) |
| P16 | 2 to 6. Outside the range, help the expert group the steps |

**Validator sentences.**

| ID | Value | Status | Sentence |
|---|---|---|---|
| P03 | `""` | partial | `Region has not been answered yet.` |
| P03 | `"Germany"` | invalid | `"Germany" is not one of the regions: North America, Europe, Middle East, Asia-Pacific.` |
| P05 | `code: ""` | partial | `Cluster has not been confirmed yet.` |
| P05 | `code: "XYZ"` | invalid | `"XYZ" is not one of the clusters.` |
| P13 | value or unit empty | partial | `Target still needs: unit.` |
| P13 | `{"value": "2", "unit": "days"}`, P12 unit `hours` | invalid | `The target is in "days" but the time today is in "hours"; both need the same unit.` |
| P13 | P12 has no unit (qualitative) | complete | — |
| P14 | `same: ""` | partial | `Same way everywhere has not been answered yet.` |
| P14 | `same: "no"`, no `differences` | partial | `Same way everywhere still needs: differences.` |
| P14 | `same: "maybe"` | invalid | `Same way everywhere must be yes, no or partly.` |
| P16 | `null`, no rejected count | partial | `Number of main steps has not been answered yet.` |
| P16 | `null`, `substep_count_rejected: 13` | invalid | `13 steps is outside 2–6: group them into at most 6 main steps.` |
| P16 | `7` or `1` (only reachable in tests; storage never holds it, §3.11) | invalid | Same sentence with that number |
| P16 | `true`, `"4"` | partial | Not a whole number |

Unit comparison is case-insensitive after trimming. P05 `decided_by` is one of `proposal` (the expert said yes to a proposal), `named` (the expert named a cluster), `picker` (UI picker), `specialist` (review edit). It is written by code and not graded.

#### Step fields (per step, in this order)

| ID | Leaf | Label | Kind and sub-fields | W | Complete when | Extract | Propose |
|---|---|---|---|---|---|---|---|
| S01 | `name` | Step name | text | 1 | Present | ✓ | ✓ |
| S02 | `goal` | Goal | text | 1 | Present | ✓ | ✓ |
| S03 | `activities` | Activities | list, `max_items` 5 | 1 | At least one item | ✓ | ✓ |
| S04 | `roles` | Roles involved | object_list `{role, contribution?}` | 1 | One row, or none row | ✓ | ✓ |
| S05 | `owner` | Step owner | text | 1 | Present | ✓ | ✓ |
| S06 | `systems` | Systems | list | 1 | At least one item | ✓ | ✓ |
| S07 | `data` | Data in and out | object `{inputs: list, outputs: list}` | 1 | Both | ✓ | ✓ |
| S08 | `effort` | Effort | object `{duration, frequency}` | 1 | Both | ✓ | ✓ |
| S09 | `pain_points` | Pain points | list | 1 | At least one item | ✓ | ✓ |
| S10 | `approvals` | Approvals | object_list `{approver_role, waiting_time?}` | 1 | One row, or none row | ✓ | ✓ |
| S11 | `exceptions` | Exceptions | object_list `{description, loops_back_to: number?}` | 1 | One row, or none row | ✓ | ✓ |
| S12 | `handover` | Hand-over | text, `max_asks` 1 | **0** | Present (never blocks) | ✓ | ✓ |

**Points per step: 11.** S12 is unscored: a step is complete when S01–S11 are complete or skipped, whatever S12 holds. `loops_back_to` is a 1-based step number. Pointers outside `1..substep_count` or to the step itself are dropped (spec 13). Questions are the default wording of [product §5.2](01-product.md#52-step-fields-asked-for-each-step-one-at-a-time).

The required sub-field of a row (`role`, `approver_role`, `description`, `item`) identifies the row. `required_subfield(spec)` returns it.

#### Derived fields (built by code, never asked, never written by a model or a document)

| ID | Key | Built from | Rule |
|---|---|---|---|
| D01 | `process.all_roles` | every `substeps[*].roles[*].role` | Full rebuild after every change. Case-insensitive de-duplication; the first spelling wins ("SAP" stays "SAP" when a later step says "sap"). None rows contribute nothing |
| D02 | `process.all_tools` | every `substeps[*].systems[*]` | Same |

#### Flags (on `process`, never fields, never scored)

`substeps_complete`, `roles_confirmed`, `tools_confirmed` (all `bool`, default `false`), and `substep_count_rejected` (`int | null`). Only code sets them (spec 13, 14). They are on no whitelist.

### 3.5 Points, limits and other constants

All numbers below are defined once in `field_spec.py`. Totals are computed from the specs, never typed.

| Constant | Value | Source |
|---|---|---|
| `PROCESS_POINTS` | 18 | Σ weights of P01–P16 |
| `STEP_POINTS` | 11 | Σ weights of S01–S12 |
| `MIN_STEPS`, `MAX_STEPS` | 2, 6 | Product Q1 |
| `total_points_for(n)` | `18 + 11 × clamp(n, 0, 6)`; `None` → 18 | 0 → 18 · 2 → 40 · 4 → 62 · 5 → 73 · 6 → 84 · 9 → 84 |
| `COMPLETENESS_GATE` | 0.80 | F-11. Needs `ceil(0.8 × total)` points: 50 of 62 for 4 steps, 68 of 84 for 6 |
| `FIELD_ASK_LIMIT` | 3 | F-09: a process field is **deferred** after 3 asks without becoming complete |
| `REVIEW_ASK_LIMIT` | 2 | F-09: a deferred field is **given up** after 2 more asks (5 in total) |
| `CELL_ASK_LIMIT` | 3 | F-09: a step cell gets the none row or is skipped after 3 asks |
| `WIDENING_LIMIT` | 2 | F-06: widening questions per session |
| `CONFIRM_TURN_LIMIT` | 6 | F-09: turns in `confirm` before the agent asks for one yes for both lists |
| `FIND_FOCUS_TURN`, `FIND_DIRECT_TURN` | 4, 6 | F-03: find-phase turns where the agent narrows, then proposes one candidate and offers the exit |
| `ACTIVITIES_SOFT_MAX` | 5 | S03 `max_items` |

The interview (spec 14) and the profile (spec 13) read these; they never restate them.

### 3.6 Provenance and proposals (`__meta`)

Every written field carries one meta entry. Context and process fields keep theirs in `profile.__meta`, keyed by registry key (`"department"`, `"process.volume"`). Step cells keep theirs in the row's `__meta`, keyed by leaf (`"systems"`), so the entry moves with the row when steps are inserted or removed. Meta is per **field**, not per sub-field. Derived fields and flags have no meta.

| Key (JSON) | Type | Rule |
|---|---|---|
| `source` | `expert` · `document` · `specialist` | Who wrote the value |
| `status` | `proposed` · `confirmed` | `proposed` is allowed only for `document` and `expert` (a name carried over from an idea, F-01) |
| `documentId` | string or null | Required when `source` is `document` |
| `quote` | string or null | Required when `status` is `proposed`, and for every `document` value: the words behind it (document text, or the idea's words) |
| `by` | string or null | Required when `source` is `specialist`: the name typed at the workspace prompt |
| `at` | ISO 8601 UTC string | When it was written. Passed in; the domain reads no clock |

**The counting rule (F-05.6).** A field **counts** toward the score and towards *Finish* only if its Verdict is `complete` **and** its meta is not `proposed`. A field with a value and no meta entry counts as `expert`/`confirmed` (fixtures, older test data). `counts(verdict, meta) -> bool` is the only implementation.

**Display status** (`field_status`, used by the live panel and the review screen):

| Order | Condition | Status |
|---|---|---|
| 1 | meta `proposed` and any answer present | `proposed` |
| 2 | Verdict `complete` | `complete` |
| 3 | Step cell in `__skipped` | `skipped` |
| 4 | No answer at all (`has_any_answer` false) | `empty` |
| 5 | Verdict `invalid` | `invalid` |
| 6 | Otherwise | `partial` |

`deferred` and `given_up` come from the ask counters (spec 14) and are added by the snapshot (spec 13); the domain does not know counters.

**Transitions.** Spec 13 applies them; they are listed here because every writer depends on them.

| Event | Value | Meta after |
|---|---|---|
| Expert answer (EXTRACT) on an empty or confirmed field | Written by kind (spec 13) | `expert` / `confirmed` |
| Expert answer on a `proposed` field | The proposal is dropped, then the expert's value is written | `expert` / `confirmed` |
| Document proposal on an empty or `proposed` field | Replaced by the proposal | `document` / `proposed`, `documentId`, `quote` |
| Document proposal on a `confirmed` field | Refused (logged) | Unchanged |
| Expert confirms (plain yes to the question naming it, or ✓) | Unchanged | `status: confirmed`; `source`, `documentId`, `quote` kept |
| Expert rejects (✎ or "no") | Cleared to the empty value | Entry removed |
| Specialist edit | Written | `specialist` / `confirmed`, `by`, `at` |
| Any automated write on a `specialist` field | Refused (logged) | Unchanged |
| Document removed | Its proposals cleared; values confirmed from it stay | Proposals' entries removed |

**Example.** A procedure proposes the trigger. Stored:

```json
"process": { "trigger": "Month-end close is completed in the ledger" },
"__meta": { "process.trigger": { "source": "document", "status": "proposed",
            "documentId": "d1", "quote": "The review starts once month-end close is completed",
            "by": null, "at": "2026-11-20T09:14:03Z" } }
```

The Verdict is `complete`, the display status is `proposed`, and it adds 0 points. After the expert says "yes, that's right", `status` becomes `confirmed` and P06 adds 1 point.

### 3.7 Whitelists

Derived from the `extract` and `propose` flags; never hand-written lists.

| Function | Keys | Never on it |
|---|---|---|
| `extract_keys()` | Every P key with `extract` (all except `process.cluster`), then every S template `process.substeps[i].<leaf>` | `process.cluster`, flags, `substep_count_rejected`, D01/D02, `__meta`, `__skipped`. There is **no** assent key: a yes or no is read by code (F-02.2) |
| `proposal_keys()` | P04, P06–P15, then every S template | P01–P03 (about the expert, not the document), P05, P16 (code sets the count from the proposed rows, spec 13), flags, derived, sidecars |
| `specialist_keys()` | Every P key and every S template | Flags, derived, sidecars. P05 is edited through its own route (cluster code, spec 15) |

`step_key_template(leaf)` gives `process.substeps[i].<leaf>` (the form shown to the model). `step_cell_key(index, leaf)` gives `process.substeps[2].systems` (1-based). `object_list_shape_hints()` renders one line per `object_list` spec (P15, S04, S10, S11) with its row shape, for the EXTRACT and READ_DOCUMENT prompts. `lenient_object_rows(spec, value)` folds the shapes a model actually emits onto rows:

| Input | Rows |
|---|---|
| `"AP clerk"` | `[{"role": "AP clerk"}]` |
| `["AP clerk", "Site manager"]` | `[{"role": "AP clerk"}, {"role": "Site manager"}]` |
| `{"role": "AP clerk"}` | `[{"role": "AP clerk"}]` |
| `[{"name": "AP clerk"}]` (one unknown key with text) | `[{"role": "AP clerk"}]` |
| `[{"none": true}]` | Passed through |
| `42`, `None` | `None` (not row-like) |

### 3.8 Taxonomy (`domain/taxonomy.py`, `config/nig/taxonomy.yaml`)

The clusters are company configuration (F-22). For NIG they are the nine operational clusters named by the company, with the same codes and names. The file is one list of clusters, in display order:

| Key | Rule |
|---|---|
| `clusters[].code` | Unique, 2–4 capital letters, not `UNKNOWN` (reserved) |
| `clusters[].name` | Unique (case-insensitive), not equal to another cluster's code |
| `clusters[].description` | Plain words the agent says out loud; at most 25 words; not equal to the name; does not contain another cluster's name as a whole phrase |
| `clusters[].keywords` | At least one; lowercase and trimmed; no keyword in two clusters; no keyword in `GENERIC_TERMS`; no keyword fires inside another cluster's keyword (checked with the same matcher) |

`GENERIC_TERMS` (code constant, too vague to place anything): `process`, `report`, `review`, `approval`, `data`, `system`, `email`, `meeting`, `document`, `request`, `team`, `manager`, `plan`, `update`, `check`, `project`.

Invalid taxonomy raises a validation error naming the cluster and the rule; `load_company_config` (spec 10) turns it into a `ConfigError` and the app does not start. Order in the file is display order.

**Keyword matcher.** A keyword hits a text when it appears case-insensitively with a word boundary on the left. Keywords of 3 characters or fewer also need a word boundary on the right. So `nda` matches "sign an NDA" but not "standard"; `invoice` matches "invoices" but not "reinvoice".

**Lookups.**

| Method | Behaviour |
|---|---|
| `by_code(code)` | Case-insensitive; `None` when unknown |
| `by_spoken(text)` | Reads what a person typed. Whole text, lowercased, letters and digits only, equal to a cluster's code or name ("it and security", "IT", "Finance"). Also `I confirm <name> (<CODE>)`. Never matches inside running prose ("we use it every day" → `None`) |
| `match_keywords(text)` | Every cluster with a keyword hit, in file order |
| `single_match(text)` | The cluster when exactly one matches, else `None`. F-07.1: one match places the process without a model call |
| `codes()` | Codes in file order |
| `prompt_block()` | One line `CODE · name: description` per cluster, for CLASSIFY |

**NIG content** (`config/nig/taxonomy.yaml`, proposed):

```yaml
clusters:
  - code: FIN
    name: Finance
    description: Planning, recording and reporting money - budgets, invoices, costs and the monthly close.
    keywords: [invoice, accounts payable, accounts receivable, month-end close, cost review,
               budget, cost forecast, general ledger, expense claim, variance, audit]
  - code: HR
    name: People & HR
    description: Hiring, paying and developing employees, from the first offer to the last working day.
    keywords: [hiring, recruiting, new hire, employee onboarding, offboarding, payroll,
               performance review, leave request, training plan, job offer, headcount]
  - code: LEG
    name: Legal
    description: Contracts, legal advice, disputes and keeping the company within the law.
    keywords: [contract review, nda, legal opinion, litigation, compliance check,
               data protection, gdpr, trademark, power of attorney]
  - code: IT
    name: IT & Security
    description: Running laptops, accounts, software and networks, and keeping them safe from attack.
    keywords: [access request, password reset, service desk, incident ticket, laptop,
               software licence, patch, vulnerability, backup, user account]
  - code: PRO
    name: Procurement
    description: Buying goods and services - choosing suppliers, ordering and receiving what was bought.
    keywords: [purchase order, purchase requisition, supplier onboarding, supplier contract,
               tender, rfq, vendor, sourcing, goods receipt]
  - code: COM
    name: Comms & Growth
    description: Telling the company's story inside and outside - press, internal news, the brand and the website.
    keywords: [press release, newsletter, internal communication, intranet, social media,
               brand guideline, website update, town hall]
  - code: KNW
    name: Knowledge & Ops
    description: Running day-to-day operations and keeping procedures, project records and lessons learned usable.
    keywords: [procedure update, knowledge base, lessons learned, site report, shift handover,
               maintenance plan, project documentation, work instruction, inspection]
  - code: ANL
    name: Analytics & Strategy
    description: Turning data into decisions - dashboards, analyses, business cases and the strategy plan.
    keywords: [dashboard, kpi, data analysis, market analysis, business case, board pack,
               benchmark, strategy plan]
  - code: GWT
    name: Sales and Marketing
    description: Finding and winning customers - leads, offers, bids, campaigns and the customer relationship.
    keywords: [sales lead, sales pipeline, quotation, bid, customer proposal, crm,
               marketing campaign, client onboarding, pricing]
```

Example: "the monthly cost review" → `match_keywords` = [FIN] → `single_match` = FIN. "approving vendor invoices" → [FIN, PRO] → no single match → CLASSIFY decides.

### 3.9 Process-or-task rubric and placement (`domain/scope.py`)

**Signals** (F-06), in this order, each with the test the model applies and one plain question the agent can ask:

| Key | Test | Question |
|---|---|---|
| `multi_role` | More than one person or role takes part | "Who else gets pulled in when this comes round?" |
| `multi_system` | More than one system, tool or document is involved | "Which tools, systems or documents do you touch to get it done?" |
| `trigger_and_outcome` | A recognisable trigger and a recognisable outcome | "What sets this off, and how do you know it is finished?" |
| `recurring` | It recurs as normal work, not a one-off | "How often does this come round?" |
| `external_consumer` | Someone outside the expert's own work depends on the output | "Who is waiting on the result once you are done?" |

1. Only a literal `true` counts as a signal. Missing, `null`, `"true"`, `1` all read as false.
2. `verdict_for(score, external_consumer)`: score ≥ 4 → `process` if `external_consumer`, else `borderline`; score 3 → `borderline`; 0–2 → `task`. `external_consumer` is a cap, not a fifth vote.
3. `build_scope_verdict(raw)` → `{verdict, score, signals, reasoning}`. `neutral_scope_verdict()` (failed CLASSIFY) → `borderline`, score 0: not knowing earns one more question. It is the only verdict where `verdict != verdict_for(score, …)`; never recompute a verdict from a stored score.
4. `failed_signals(verdict)` names the missing signals, in order. `is_one_off(verdict)`: `process` with `recurring` false (F-06.5).

**Calibration rows** (shown to CLASSIFY as examples; the scorer must agree):

| Description | Signals (R1–R5) | Verdict |
|---|---|---|
| "I book my flight for a site visit" | T T T T F | borderline |
| "I file my weekly timesheet" | F F T T F | task |
| "I export a report from the ERP every Monday" | F F F T F | task |
| "Approving supplier invoices over €10k" | T T T T T | process |
| "Onboarding a new engineer" | T T T T T | process |
| "The monthly cost review" | T T T T T | process |
| "We migrated the CRM last year" | T T T F T | process (one-off) |
| "The quarterly access review" | T T T T T | process |

**Placement** (F-07). `build_placement(raw, taxonomy, *, min_confidence=MIN_CONFIDENCE, min_margin=MIN_MARGIN)` → `{code, confidence, raw_confidence, runner_up, runner_up_confidence, rationale, ambiguous, source: "model"}`.

| Rule | Value |
|---|---|
| `MIN_CONFIDENCE` | 0.60. Below it: `code = UNKNOWN`, `confidence = 0`, `raw_confidence` keeps the model's number |
| `MIN_MARGIN` | 0.15. `ambiguous` when `confidence − runner_up_confidence < 0.15` (strict) |
| Unknown or non-string code | `UNKNOWN` |
| Confidence | Clamped to [0, 1]; non-numbers (and bools) → 0 |
| No runner-up code | Runner-up confidence 0, so not ambiguous |
| Thresholds passed in | Must be in [0, 1], else `ValueError` (never clamped) |

`keyword_placement(code)` → confidence 1.0, no runner-up, `source: "keyword"`. `unknown_placement()` → the complete empty shape. `proposable_code(placement)` → the code the agent may put to the expert, or `""` when `UNKNOWN` or ambiguous.

### 3.10 Company vocabulary

Validators need the regions and the taxonomy, and reason sentences use wording overrides. They receive one object:

`Vocabulary(taxonomy: Taxonomy, regions: tuple[str, ...], wording: WordingOverrides)` (frozen). Built once in the app lifespan from `CompanyConfig` and passed down. Tests use a fixture built from `config/nig`.

`WordingOverrides` (`config/nig/wording.yaml`): `{fields: {<ID>: {label?: str, question?: str}}}`. Unknown IDs are a config error. IDs, keys, kinds and weights never change. `Vocabulary.label(spec)` and `Vocabulary.question(spec)` return the override or the default. NIG ships the file empty.

### 3.11 Pydantic models (`app/models/process_discovery_schemas.py`)

**Three bases.**

| Base | Config | Used for |
|---|---|---|
| `ProfileModel` | `extra="forbid"`, `populate_by_name=True`, no alias generator | The profile and its parts. Keys are registry keys (`end_result`, `substep_count`), the same in storage and on the wire, because they are field addresses |
| `StorageModel` | `alias_generator=to_camel`, `populate_by_name=True`, `extra="forbid"` | The session and idea documents in Cosmos and everything inside them except the profile content |
| `WireModel` | `alias_generator=to_camel`, `populate_by_name=True`, `extra="ignore"` | API requests and responses (spec 15 adds route models) |

Python attributes are snake_case. Every dump uses `by_alias=True, mode="json"` (repository and routes). `extra="forbid"` on stored models means a key the model does not declare fails loudly in tests instead of disappearing on the next save. Sidecars are declared fields with aliases: `meta` ↔ `"__meta"`, `skipped` ↔ `"__skipped"`.

**Profile models** (mirror the registry 1:1).

```python
class NoneRow(ProfileModel):        none: Literal[True]
class RoleRow(ProfileModel):        role: str = Field(min_length=1); contribution: str = ""
class ApprovalRow(ProfileModel):    approver_role: str = Field(min_length=1); waiting_time: str = ""
class ExceptionRow(ProfileModel):   description: str = Field(min_length=1); loops_back_to: int | None = Field(None, ge=1)
class SensitiveRow(ProfileModel):   item: str = Field(min_length=1); detail: str = ""

class FieldMeta(StorageModel):      # JSON keys: source, status, documentId, quote, by, at
    source: Literal["expert", "document", "specialist"]
    status: Literal["proposed", "confirmed"]
    document_id: str | None = None; quote: str | None = None; by: str | None = None; at: str
    # validator: the rules of §3.6 (document needs documentId and quote; proposed needs quote;
    # specialist needs by; specialist is never proposed)

class ClusterRef(ProfileModel):     code: str = ""; name: str = ""; decided_by: str = ""
class Volume(ProfileModel):         count: int | None = Field(None, ge=0); period: str = ""; raw: str = ""
class ProcessOwner(ProfileModel):   role: str = ""; none_identified: bool = False
class Baseline(ProfileModel):       value: str = ""; unit: str = ""; qualitative: str = ""; estimated: bool = False
class Target(ProfileModel):         value: str = ""; unit: str = ""
class Variation(ProfileModel):      same: str = ""; differences: str = ""
class StepData(ProfileModel):       inputs: list[str] = []; outputs: list[str] = []
class StepEffort(ProfileModel):     duration: str = ""; frequency: str = ""

class Step(ProfileModel):
    name: str = ""; goal: str = ""; activities: list[str] = []
    roles: list[NoneRow | RoleRow] = []; owner: str = ""; systems: list[str] = []
    data: StepData = StepData(); effort: StepEffort = StepEffort(); pain_points: list[str] = []
    approvals: list[NoneRow | ApprovalRow] = []; exceptions: list[NoneRow | ExceptionRow] = []
    handover: str = ""
    meta: dict[str, FieldMeta] = Field({}, alias="__meta")       # keyed by leaf
    skipped: list[str] = Field([], alias="__skipped")            # leaves

class Process(ProfileModel):
    name: str = ""; cluster: ClusterRef = ClusterRef()
    trigger: str = ""; end_result: str = ""; value_at_end: str = ""; business_pain: str = ""
    volume: Volume = Volume(); process_owner: ProcessOwner = ProcessOwner()
    baseline_metric: Baseline = Baseline(); target_metric: Target = Target(); variation: Variation = Variation()
    sensitive_data: list[NoneRow | SensitiveRow] = []
    substep_count: int | None = None; substep_count_rejected: int | None = None
    substeps: list[Step] = Field([], max_length=MAX_STEPS)
    all_roles: list[str] = []; all_tools: list[str] = []
    substeps_complete: bool = False; roles_confirmed: bool = False; tools_confirmed: bool = False

class Profile(ProfileModel):
    department: str = ""; user_function: str = ""; region: str = ""
    process: Process = Process()
    meta: dict[str, FieldMeta] = Field({}, alias="__meta")       # keyed by registry key
```

(Mutable defaults are written as `default_factory` in code.) Rules on the models:

1. A row is either the none row or a real row with its required sub-field. `{"none": true}` validates only as `NoneRow`; `{"role": "x"}` only as `RoleRow`. The none row is never turned into an empty row.
2. `Process` has a before-validator: a `substep_count` outside 2–6 moves to `substep_count_rejected` and `substep_count` becomes `null`. It never raises, so a bad number can never make a session unloadable, and storage never holds an out-of-range count.
3. More than 6 steps is a validation error (a bug in a writer, caught in tests).
4. `empty_profile()` (spec 13) must equal `Profile().model_dump(by_alias=True)`. Optional row sub-fields are always written (with their defaults) so a round trip changes nothing.

**Empty profile, as JSON** (the skeleton every writer starts from):

```json
{
  "department": "", "user_function": "", "region": "",
  "process": {
    "name": "", "cluster": {"code": "", "name": "", "decided_by": ""},
    "trigger": "", "end_result": "", "value_at_end": "", "business_pain": "",
    "volume": {"count": null, "period": "", "raw": ""},
    "process_owner": {"role": "", "none_identified": false},
    "baseline_metric": {"value": "", "unit": "", "qualitative": "", "estimated": false},
    "target_metric": {"value": "", "unit": ""},
    "variation": {"same": "", "differences": ""},
    "sensitive_data": [],
    "substep_count": null, "substep_count_rejected": null,
    "substeps": [],
    "all_roles": [], "all_tools": [],
    "substeps_complete": false, "roles_confirmed": false, "tools_confirmed": false
  },
  "__meta": {}
}
```

One empty step: `{"name": "", "goal": "", "activities": [], "roles": [], "owner": "", "systems": [], "data": {"inputs": [], "outputs": []}, "effort": {"duration": "", "frequency": ""}, "pain_points": [], "approvals": [], "exceptions": [], "handover": "", "__meta": {}, "__skipped": []}`.

**Enums** (`StrEnum`): `Phase` (§3.1), `SessionStatus` (`active`, `finished`, `no_candidate`), `MessageRole` (`expert`, `agent`), `FieldStatus` (`complete`, `partial`, `invalid`, `proposed`, `skipped`, `empty`, `deferred`, `given_up`), `FinishBlock` (`below_gate`, `substeps_incomplete`, `roles_not_confirmed`, `tools_not_confirmed`, checked in this order by spec 13), `OpportunityType` (`eliminate`, `standardise`, `workflow`, `integration`, `document_ai`, `ai_assistant`, `ai_agent`, `rpa`; `rates.yaml` uses the same keys), `Grade` (`high`, `medium`, `low`).

**Session document** (storage; JSON keys camelCase except inside `profile` and `rawSubsteps`):

| Field | Type | Default / rule |
|---|---|---|
| `id` | str | uuid4 |
| `owner_id` | str | SHA-256 of the visitor key (spec 16). Partition key |
| `type` | `Literal["session"]` | `"session"` |
| `display_name` | str \| None | Optional first name, ≤ 40 chars, greeting only |
| `created_at`, `updated_at` | str | ISO 8601 UTC, set by the service |
| `finished_at` | str \| None | Set on *Finish* or close |
| `ttl` | int \| None | Seconds; `None` once finished (spec 15) |
| `status` | `SessionStatus` | `active` |
| `phase` | `Phase` | `context` |
| `messages` | list[`Message{id, role, text, at}`] | `[]` |
| `profile` | `Profile` | empty |
| `score` | `Score{value: float 0–1, filled_points: int, total_points: int}` | `0, 0, 18`. Confirmed values only |
| `counters` | `Counters` | below |
| `scope` | `ScopeState{verdict: ScopeVerdict \| None, scoped_for: str, awaiting_widening: bool, widening_asked: bool, overridden: bool}` | empty |
| `placement` | `PlacementState{proposal: Placement \| None, placed_for: str, rejected: bool}` | empty |
| `last_question` | `LastQuestion{focus: list[str], proposals: list[str], confirm: Literal["cluster", "roles", "systems"] \| None}` | empty. Field keys the last question asked about, proposals it presented, and the list or cluster it asked to confirm. Lets code read a plain yes (spec 14) |
| `documents` | list[`DocumentRecord{id, name, kind, bytes, chars, truncated, text, uploaded_at, outcome: "read" \| "failed", proposals: int, step_list: list[{name, quote}]}`] | `[]`. `kind` ∈ pdf, docx, xlsx, csv, txt, md, bpmn. `text` is capped (spec 17) and never sent to the workspace |
| `raw_substeps` | list[`Step`] | `[]`. The steps as the expert gave them, frozen before the first non-expert change (spec 13) |
| `assessment` | `Assessment \| None` | `None` until *Finish* |
| `report` | `ReportState{status: "mapped" \| "validated", validated_at, validated_by, note}` \| None | `None` until *Finish* |
| `briefs` | list[`Brief`] | `[]` |
| `cost` | `Cost{tokens_in: int, tokens_out: int, euros: float}` | zeros |
| `etag` | str \| None | Read from Cosmos `_etag`; `exclude=True`, never written |

`Counters{field_asks: dict[str, int], cell_asks: dict[str, int], find_turns: int, widening_count: int, confirm_turns: int}`. `field_asks` is keyed by registry key (`"process.volume"`); `cell_asks` by step cell key (`"process.substeps[2].systems"`). Deferred = `field_asks ≥ FIELD_ASK_LIMIT`; given up = `field_asks ≥ FIELD_ASK_LIMIT + REVIEW_ASK_LIMIT` (spec 14).

`ScopeVerdict{verdict, score, signals: dict[str, bool], reasoning}` and `Placement{code, confidence, raw_confidence, runner_up, runner_up_confidence, rationale, ambiguous, source}` have exactly the shapes `scope.py` returns.

**Assessment containers.** Specs 18 and 19 own the detail and may add fields to the sub-models. They may not rename or remove the fields below.

| Model | Fields fixed here |
|---|---|
| `Assessment` | `summary: str`, `opportunities: list[Opportunity]`, `stay_human: list[StayHuman]`, `diagram: ProcessDiagram \| None`, `labels: list[StepLabels]`, `value: ValueResult \| None`, `readiness: Readiness \| None`, `path: Path \| None`, `steps_hash: str`, `generated_at: str`, `outcomes: dict["opportunities" \| "diagram" \| "labels", "generated" \| "fallback" \| "failed"]` |
| `Opportunity` | `id`, `title`, `substeps: list[int]` (1-based; empty = whole process), `type: OpportunityType`, `what_changes`, `how`, `prepare_first`, `impact: Grade`, `impact_reason`, `feasibility: Grade`, `feasibility_reason`, `evidence` (the quote), `saving_share: float` (0–0.9), `review: "pending" \| "accepted" \| "adjusted" \| "rejected"`, `review_note: str` |
| `StayHuman` | `substeps: list[int]`, `reason`, `evidence` |
| `ProcessDiagram` | `lanes: list[str]`, `nodes: list[DiagramNode{id, type, label, lane, step_index, marker}]`, `flows: list[DiagramFlow{source, target, label, is_default}]`, `simplified: bool`, `steps_hash` |
| `StepLabels` | `step: int`, `inputs: list[{name, format, evidence}]`, `decisions: list[{text, kind, evidence}]` |
| `ValueResult` | `complete: bool`, `missing: list[str]` (field keys to fix), `hours_per_year`, `cost_today`, `hours_freed`, `value_conservative`, `value_expected` (floats or `None`) |
| `Readiness` | `dimensions: list[ReadinessDimension{key, level: "high" \| "medium" \| "low" \| "unknown", reason, to_prepare, note}]` |
| `Path` | `prepare_first`, `quick_wins`, `bigger_changes`: lists of opportunity ids |
| `Brief` | `id`, `opportunity_ids`, `content: BriefContent` (spec 21), `status: "draft" \| "sent" \| "accepted" \| "returned"`, `questions: str`, `history: list[{status, by, at, note}]`, `created_at`, `created_by` |

*In an implementation brief* is derived from `briefs[]`; it is not a report status.

> **Amendment 2026-11-19 (draft, contract changes requested by specs 14 §3.15, 19 and 26):** `Assessment` gains `step_assessment: StepAssessment | None` (spec 26 §4.2) and the outcome key `steps`; `Session` gains `steering: SteeringState` (spec 14 §3.15 item 1); `LastQuestion.confirm` gains `"recommendation"`; `Idea` gains optional `signals`, `hours_per_year`, `people`, `data_score`, `score`, `rank`, `recommended`. `ValueResult.cost_today`, `hours_freed`, `value_conservative`, `value_expected` and `Opportunity.saving_share` stay in the model but are *parked until the value method is decided (refinement R5)*: `None` / not read.

**Idea document** (storage): `id`, `owner_id`, `type: Literal["idea"]`, `name`, `words` (the expert's own words), `from_session_id`, `started_session_id: str | None`, `status: "open" | "started" | "dismissed"` (default `open`), `created_at`, `ttl`.

**Shared wire models** (spec 15 builds route models from them).

| Model | Fields |
|---|---|
| `FieldView` | `key`, `id`, `label`, `phase`, `status: FieldStatus`, `reason`, `missing`, `source`, `quote`, `document_name`, `asks`. Built by the snapshot (spec 13); the client never computes a status |
| `FinishState` | `ready: bool`, `blocked_by: FinishBlock \| None`, `looks_like_task: bool` (advisory, never blocks) |
| `ClusterOut` / `TaxonomyOut` | `{code, name, description}` / `{clusters: [ClusterOut]}` for `GET /api/taxonomy` |

Every route response that carries the profile carries it as stored (registry keys, `__meta` included). `owner_id`, `documents[].text` and `etag` are never in a response; workspace responses never contain `messages` or document text (spec 15).

### 3.12 Node order (`domain/node_order.py`)

`rank_nodes(node_ids, edges) -> (rank: dict[str, int], back_edges: set[tuple[str, str]])`. Longest-path rank, 0 = leftmost. A depth-first search from the nodes nobody flows into (in the given order), then from any node not yet visited, finds the back edges (loops); they are left out of the ranking, so every node gets a rank whatever the graph. Edges touching unknown nodes and self-loops are ignored; duplicate ids and edges count once. Used by the map grounding (spec 18) and the BPMN drawing (spec 22).

## 4. Interfaces

```python
# domain/field_spec.py  (stdlib + pydantic only)
Kind = Literal["text", "list", "number", "object", "object_list"]
STATUS_COMPLETE, STATUS_PARTIAL, STATUS_INVALID = "complete", "partial", "invalid"
SOURCE_EXPERT, SOURCE_DOCUMENT, SOURCE_SPECIALIST = "expert", "document", "specialist"
META_KEY, SKIPPED_KEY, NONE_KEY, NONE_FLAG = "__meta", "__skipped", "none", "none_identified"

class Verdict(NamedTuple):
    status: str; missing: tuple[str, ...] = (); reason: str = ""
    @property
    def is_complete(self) -> bool: ...

@dataclass(frozen=True)
class SubFieldSpec: key: str; kind: str; required: bool = True; label: str = ""   # label defaults to key with spaces
@dataclass(frozen=True)
class FieldSpec:
    id: str; key: str; label: str; kind: Kind; phase: str; weight: int; question: str; rule: str
    subfields: tuple[SubFieldSpec, ...] = (); complete_when: tuple[tuple[str, ...], ...] = ()
    validator: Callable[[Any, Mapping[str, Any], "Vocabulary"], Verdict] | None = None
    extract: bool = True; propose: bool = True; max_items: int | None = None; max_asks: int | None = None
    @property
    def leaf(self) -> str: ...; @property
    def is_process(self) -> bool: ...
@dataclass(frozen=True)
class DerivedSpec: id: str; key: str; label: str; source: str; reducer: Callable[[Mapping[str, Any]], list[str]]

PROFILE_SPECS: tuple[FieldSpec, ...]      # P01–P16, ask order
STEP_SPECS: tuple[FieldSpec, ...]         # S01–S12
DERIVED_SPECS: tuple[DerivedSpec, ...]    # D01–D02
PHASE_ORDER, COLLECTING_PHASES: tuple[str, ...]
# constants of §3.5

def evaluate_field(spec: FieldSpec, value: Any, profile: Mapping[str, Any], vocab: Vocabulary) -> Verdict
def has_any_answer(spec: FieldSpec, value: Any) -> bool
def is_none_row(entry: Any) -> bool
def counts(verdict: Verdict, meta: Mapping[str, Any] | None) -> bool
def is_proposed(meta: Mapping[str, Any] | None) -> bool
def field_status(verdict: Verdict, meta: Mapping[str, Any] | None, *, answered: bool, skipped: bool = False) -> str
def total_points_for(substep_count: int | None) -> int

def spec_by_id(field_id: str) -> FieldSpec | None
def resolve_address(key: str) -> tuple[FieldSpec, int | None] | None   # (spec, 1-based step index or None)
def step_spec_by_leaf(leaf: str) -> FieldSpec | None
def step_cell_key(index: int, leaf: str) -> str                        # 1-based
def step_key_template(leaf: str) -> str                                # "process.substeps[i].<leaf>"
def specs_for_phase(phase: str) -> list[FieldSpec]
def scored_step_specs() -> list[FieldSpec]                              # weight > 0

def extract_keys() -> list[str]
def proposal_keys() -> list[str]
def specialist_keys() -> list[str]
def required_subfield(spec: FieldSpec) -> str | None
def lenient_object_rows(spec: FieldSpec, value: Any) -> list[Any] | None
def object_list_shape_hints() -> list[str]
def recompute_derived(profile: Mapping[str, Any]) -> dict[str, list[str]]   # {"process.all_roles": [...], ...}

class WordingOverrides(BaseModel): fields: dict[str, FieldWording] = {}   # validator: IDs exist
@dataclass(frozen=True)
class Vocabulary:
    taxonomy: Taxonomy; regions: tuple[str, ...]; wording: WordingOverrides
    def label(self, spec: FieldSpec) -> str: ...
    def question(self, spec: FieldSpec) -> str: ...
    def region(self, text: str) -> str | None: ...       # canonical spelling, case-insensitive

# domain/taxonomy.py  (stdlib + pydantic only)
UNKNOWN_CODE = "UNKNOWN"; GENERIC_TERMS: frozenset[str]
class Cluster(BaseModel): code: str; name: str; description: str; keywords: tuple[str, ...]
class Taxonomy(BaseModel):   # frozen; validators of §3.8; = CompanyConfig.taxonomy
    clusters: tuple[Cluster, ...]
    def codes(self) -> list[str]: ...
    def by_code(self, code: str | None) -> Cluster | None: ...
    def by_spoken(self, text: str | None) -> Cluster | None: ...
    def match_keywords(self, text: str | None) -> list[Cluster]: ...
    def single_match(self, text: str | None) -> Cluster | None: ...
    def prompt_block(self) -> str: ...
def keyword_hit(keyword: str, text: str) -> bool

# domain/scope.py  (pure)
SIGNALS: tuple[tuple[str, str], ...]; SIGNAL_KEYS: tuple[str, ...]; SIGNAL_QUESTIONS: dict[str, str]
VERDICT_PROCESS, VERDICT_BORDERLINE, VERDICT_TASK = "process", "borderline", "task"
PROCESS_FLOOR, BORDERLINE_FLOOR, MIN_CONFIDENCE, MIN_MARGIN = 4, 3, 0.60, 0.15
CALIBRATION: tuple[tuple[str, dict[str, bool], str], ...]
def normalise_signals(raw: Any) -> dict[str, bool]
def score_scope(signals: Mapping[str, Any]) -> int
def verdict_for(score: int, external_consumer: bool) -> str
def build_scope_verdict(raw: Any) -> dict[str, Any]
def neutral_scope_verdict() -> dict[str, Any]
def failed_signals(verdict: Mapping[str, Any]) -> tuple[str, ...]
def is_one_off(verdict: Mapping[str, Any]) -> bool
def build_placement(raw: Any, taxonomy: Taxonomy, *, min_confidence: float = MIN_CONFIDENCE,
                    min_margin: float = MIN_MARGIN) -> dict[str, Any]
def keyword_placement(code: str) -> dict[str, Any]
def unknown_placement() -> dict[str, Any]
def proposable_code(placement: Mapping[str, Any] | None) -> str

# domain/node_order.py  (pure)
def rank_nodes(node_ids: Iterable[str], edges: Iterable[tuple[str, str]]) -> tuple[dict[str, int], set[tuple[str, str]]]

# app/models/process_discovery_schemas.py: bases, enums, profile, session, idea, assessment and shared wire models of §3.11
```

## 5. Implications

- **Profile (spec 13):** works on plain dicts shaped exactly like `Profile` dumps; grades with `evaluate_field`; counts with `counts`; applies the meta transitions of §3.6; owns coercion, merging, resize, skipping, roll-up rebuild, `expected_steps` and the score. It never restates a weight, a total or a limit.
- **Interview (spec 14):** reads phases, limits, whitelists, questions, rules, shape hints, the rubric and placement from here; stores its cross-turn state only in the declared session fields (`counters`, `scope`, `placement`, `last_question`). Placement thresholds may be overridden from settings by passing them to `build_placement`.
- **Documents (spec 17):** proposes only `proposal_keys()`; every proposal carries `documentId` and a quote.
- **Service and API (spec 15):** the façade imports `service.py` lazily (§2); dumps always `by_alias=True`; route models extend `WireModel`; never return `owner_id`, `etag` or document text.
- **Workspace (spec 21):** edits use `specialist_keys()` and write `specialist` meta with `by`.
- **Assessment (specs 18, 19):** fill the containers of §3.11; may add fields to the sub-models, not rename them.
- **Frontend (spec 23):** mirrors the wire models in `types/`; the profile keeps registry keys; field status comes from `FieldView`, never computed.
- **Config:** `config/nig/taxonomy.yaml` (§3.8), `config/nig/wording.yaml` (empty). `rates.yaml` uses the `OpportunityType` keys. `CompanyConfig.taxonomy` is `Taxonomy`, `CompanyConfig.wording` is `WordingOverrides`.
- **Data:** this spec defines the whole session and idea documents. No migration: there is no stored data yet.
- **Security and privacy:** roles, never names (P02, P11, S04, S05 rules). Quotes are the only document text inside the profile. `owner_id` is a hash. No model call in this spec.
- **Cost and latency:** none. Pure code.

## 6. Acceptance criteria

| ID | Given / when / then |
|---|---|
| AC-12.1 | The registry lists exactly P01–P16, S01–S12 and D01–D02 with unique IDs, in that declaration order, with the keys, kinds, weights and phases of §3.4 |
| AC-12.2 | Keys are unique per series; P01–P03 are top-level keys, P04–P16 start with `process.`; S keys are bare leaves |
| AC-12.3 | Every `object`/`object_list` spec declares sub-fields; `object_list` sub-fields are scalar; every `complete_when` group names real sub-fields; no spec has both groups and a validator |
| AC-12.4 | Every phase string in `field_spec` equals a `Phase` value; every collecting phase has at least one field; `finished` and `no_candidate` are not in `PHASE_ORDER` |
| AC-12.5 | `PROCESS_POINTS == 18`, `STEP_POINTS == 11`; `total_points_for` gives 18, 18, 40, 84, 84 for `None`, 0, 2, 6, 9 |
| AC-12.6 | Every spec has a rule; every spec except P05 has a question equal to the product's default wording; S12 has weight 0 and `max_asks == 1` |
| AC-12.7 | Volume `{"count": 400}` → `partial`, missing `("period",)`, reason exactly `Volume still needs: period.` |
| AC-12.8 | Volume `{"raw": "a few hundred a month"}` → `complete`; an empty volume → missing `("count", "period")` |
| AC-12.9 | Owner with `none_identified: false` and no role → `partial`; with `none_identified: true` → `complete` |
| AC-12.10 | A baseline with only `qualitative` → `complete` |
| AC-12.11 | Target `{"value": "2", "unit": "days"}` with baseline unit `hours` → `invalid`, reason names both units; with baseline unit `Days` → `complete`; with a qualitative-only baseline → `complete` |
| AC-12.12 | For each `object_list` spec: `[{"none": true}]` → `complete`; `[]` → `partial` with the "There are none" sentence; a row without its required sub-field → `partial` |
| AC-12.13 | Step count 4 → `complete`; `null` → `partial`; `null` with `substep_count_rejected: 13` → `invalid` with "13 steps is outside 2–6…"; `True` and `"4"` → `partial` |
| AC-12.14 | Region "europe" → `complete`; "Germany" → `invalid` listing the four configured regions; `""` → `partial` |
| AC-12.15 | Cluster code `FIN` → `complete`; `XYZ` → `invalid`; empty → `partial` |
| AC-12.16 | Variation `same: "yes"` → `complete`; `"no"` without differences → `partial` naming differences; `"partly"` with differences → `complete`; `"maybe"` → `invalid` |
| AC-12.17 | `has_any_answer` is false for every field of `empty_profile()` and true after one sub-field is set |
| AC-12.18 | `resolve_address` resolves `department`, `process.volume`, `volume`, `process.substeps[2].systems` (index 2) and `name` (to P04); it returns `None` for `process.substeps[0].name`, `process.substeps[2].unknown`, `process.all_roles`, `substeps_complete` and `__meta`; `step_cell_key(1, "roles") == "process.substeps[1].roles"` |
| AC-12.19 | `extract_keys()` is every P key except `process.cluster`, then the 12 step templates; it contains no flag, derived key, sidecar or assent key |
| AC-12.20 | `proposal_keys()` is P04, P06–P15 and the 12 step templates; it excludes P01–P03, P05 and P16 |
| AC-12.21 | Each whitelist equals the filter of the registry by its flag (flipping `extract` on a copied spec removes it) |
| AC-12.22 | `lenient_object_rows` maps each input of the §3.7 table to its rows, and returns `None` for `42` and `None` |
| AC-12.23 | `object_list_shape_hints()` has one line for each of P15, S04, S10, S11, naming every sub-field and marking optional ones |
| AC-12.24 | `recompute_derived` rebuilds both roll-ups from scratch: de-duplicated case-insensitively, first spelling kept, none rows ignored, and a role removed from its step disappears |
| AC-12.25 | `FieldMeta` rejects: `document` without `documentId` or quote; `proposed` without quote; `specialist` without `by`; `specialist` + `proposed`; an unknown source or status |
| AC-12.26 | `counts` is true for `complete` + `confirmed` and for `complete` with no meta; false for `complete` + `proposed`, and for any `partial` or `invalid` |
| AC-12.27 | `field_status` follows the order of §3.6: a proposed partial value is `proposed`; a skipped cell is `skipped`; an untouched field is `empty` |
| AC-12.28 | `__meta` and `__skipped` survive `Profile.model_validate(d).model_dump(by_alias=True)` with keys `__meta`, `__skipped`, `documentId` |
| AC-12.29 | `config/nig/taxonomy.yaml` loads into `Taxonomy` with the 9 clusters of the company brief, codes and names exactly: FIN Finance, HR People & HR, LEG Legal, IT IT & Security, PRO Procurement, COM Comms & Growth, KNW Knowledge & Ops, ANL Analytics & Strategy, GWT Sales & Marketing, in that order |
| AC-12.30 | A taxonomy with any one of these faults is rejected with a message naming the cluster: duplicate code, duplicate name, code `UNKNOWN`, no keywords, a keyword in two clusters, a generic term, a keyword firing inside another's, an uppercase keyword, a description over 25 words or naming another cluster |
| AC-12.31 | `by_code("fin")` → FIN; `by_spoken` resolves "it and security", "IT", "I confirm Finance (FIN)"; returns `None` for "we use it every day" |
| AC-12.32 | `keyword_hit("nda", "the standard applies")` is false and `("nda", "sign an NDA")` true; `single_match("the monthly cost review")` → FIN; `match_keywords("approving vendor invoices")` → [FIN, PRO]; generic text → [] |
| AC-12.33 | All 32 signal combinations band as §3.9 rule 2; four signals without `external_consumer` → `borderline` |
| AC-12.34 | Only a literal `true` counts; `normalise_signals` returns exactly the five keys; `neutral_scope_verdict()` is `borderline` with score 0 and five false signals |
| AC-12.35 | Every calibration row scores to its verdict; "We migrated the CRM last year" is a process and `is_one_off` |
| AC-12.36 | `build_placement`: confidence 0.55 → `UNKNOWN`, confidence 0, raw 0.55; 0.60 survives; margin 0.14 → ambiguous, 0.15 → not; no runner-up → not ambiguous; code "Finance" or "XYZ" → `UNKNOWN`; thresholds outside [0, 1] → `ValueError` |
| AC-12.37 | `proposable_code` is `""` for `UNKNOWN`, ambiguous, `None` and garbage; `keyword_placement("FIN")` has confidence 1.0, no runner-up, `source: "keyword"` |
| AC-12.38 | `rank_nodes`: a linear flow ranks 0..n; a loop yields one back edge and still ranks every node; a pure cycle and isolated nodes all get ranks; edges to unknown nodes and self-loops are ignored |
| AC-12.39 | Parity: every P spec key, S leaf, sub-field, derived key and flag has exactly one model field, and the models have no field the registry does not know (except the sidecars); kinds map to types (text→str, list→list[str], number→int \| None, object→sub-model, object_list→list[NoneRow \| Row]) |
| AC-12.40 | `Profile().model_dump(by_alias=True)` equals the JSON skeleton of §3.11; a profile with sentinels, meta, skipped cells and 6 full steps round-trips unchanged |
| AC-12.41 | A stored `substep_count` of 13 loads as `substep_count: null, substep_count_rejected: 13` without raising; 7 steps raise a validation error; an undeclared key on `Profile`, `Step` or `Session` raises |
| AC-12.42 | `Session(...).model_dump(by_alias=True)` has `ownerId`, `rawSubsteps`, `score.filledPoints`, `counters.fieldAsks`, no `etag`; the profile inside keeps `end_result`; snake_case and camelCase input both validate |
| AC-12.43 | A new `Session` has status `active`, phase `context`, score `0/0/18`, zero counters, no assessment, report or briefs; a new `Idea` has status `open` |
| AC-12.44 | In a fresh interpreter, importing `app.models.process_discovery_schemas`, then separately `app.core.config`, then separately `app.services.process_discovery.domain.field_spec`, succeeds, and none of them imports `app.services.process_discovery.service` |
| AC-12.45 | `WordingOverrides` with an unknown ID is rejected; with `P06: {label: "Starting point"}`, `Vocabulary.label` returns it and the P06 partial sentence starts with "Starting point" |
| AC-12.46 | `DocumentRecord.step_list` defaults to `[]` and holds `{name, quote}` items (spec 17 change request) |
| AC-12.47 | `DocumentRecord.outcome` accepts only `read` and `failed`; a refused upload is never stored |

## 7. Test plan

| Test file | Covers |
|---|---|
| `tests/unit/process_discovery/domain/test_field_spec.py` | AC-12.1–12.6, 12.17–12.24 |
| `tests/unit/process_discovery/domain/test_evaluate_field.py` | AC-12.7–12.16, 12.45 |
| `tests/unit/process_discovery/domain/test_provenance.py` | AC-12.25–12.28 |
| `tests/unit/process_discovery/domain/test_taxonomy.py` | AC-12.29–12.32 (bad taxonomies parametrised) |
| `tests/unit/process_discovery/domain/test_scope.py` | AC-12.33–12.37 |
| `tests/unit/process_discovery/domain/test_node_order.py` | AC-12.38 |
| `tests/unit/models/test_registry_parity.py` | AC-12.39, 12.40 |
| `tests/unit/models/test_process_discovery_schemas.py` | AC-12.41–12.43 |
| `tests/unit/models/test_import_order.py` | AC-12.44 (subprocess per import) |

A shared fixture `nig_vocabulary` (in `tests/conftest.py`) builds the `Vocabulary` from `config/nig`. Tests feed real producer output (`empty_profile()`, `extract_keys()`, `resolve_address` of real keys), never hand-typed keys.

## 8. Out of scope

| What | Where |
|---|---|
| Writing values: coercion, merging, none-row and none-flag handling, resize, skipping, roll-up rebuild timing, score, *Finish* check, snapshot | Spec 13 |
| Ask counting, deferring, phases, reading yes/no, prompts | Spec 14 |
| Route request and response models, error codes | Spec 15 |
| Reading YAML, `ConfigError`, organisation and other config files | Spec 10 |
| The detail of opportunities, map, labels, value, readiness, path, brief content | Specs 18, 19, 21 |

## 9. Open questions

| # | Question | Default until decided |
|---|---|---|
| Q1 | *(decided)* Clusters | Exactly the nine clusters of the company brief, no grouping |
| Q2 | Should a plain "no" to P14 (without what differs) count? | No: partial until the expert says what differs, because readiness (F-15 Standard) needs it |
| Q3 | Should the placement thresholds be settings (tunable without a deploy)? | Constants here; spec 14 may pass settings values to `build_placement` |
| Q4 | Store the interview language on the session for the yes/no word lists? | Not stored; spec 14 decides per turn |
| Q5 | Volume count as a whole number only ("1.5 a day")? | Whole number; the expert's wording stays in `raw` |
