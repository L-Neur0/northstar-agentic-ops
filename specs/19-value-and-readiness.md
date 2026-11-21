# 19 · Value, labels, readiness and the suggested path

> **Status:** approved · **built 2026-11-20** · **Implements:** F-12 (item 4, the path), F-14, F-15 (product); §6.2 LABEL, §6.4 grounding, §5 assessment fields (architecture) · **Depends on:** specs 10 (`Rates`, config loader), 11 (LLM client), 12 (models, `counts`), 13 (profile dicts), 20 (opportunities, evidence check, profile fence, fingerprint)
> **Amendment 2026-11-19 (draft): hours only.** Cost today, hours that could be freed, euro values and saving shares are **parked until the value method is decided (refinement R5)**. Their text stays below, marked *parked (R5)*, so it can come back; code does not compute or show them while R5 is open. `value_parse.py` moves to `domain/` so the interview's steering (spec 14 §3.15) uses the same grammar.
> **Code:** `backend/app/services/process_discovery/domain/value_parse.py`, `artifacts/{value,readiness,path}.py`, `artifacts/labels/{schemas,prompts,labels}.py`, the `ReadinessConfig` model in `backend/app/core/config.py`
> **Tests:** `backend/tests/unit/process_discovery/artifacts/`

## 1. Purpose

Code puts numbers on the process, each step and each opportunity (**hours a year** only; cost and value are parked, R5), rates six readiness dimensions with a reason and a "to prepare" line, and orders the opportunities into a suggested path. The model's only part is **LABEL**: it tags each step's inputs with a format and each decision with a kind, with the expert's words as evidence, checked by code. The same profile always gives the same numbers, every number shows its formula, and nothing is guessed: what code cannot read is shown as incomplete or unknown, with the field to fix.

## 2. Where it sits

- **Layer:** `artifacts`, except `value_parse.py`, which lives in `domain` (pure; used by `artifacts` and by `interview` for steering). `value_parse.py`, `value.py`, `readiness.py` and `path.py` are **pure** (no I/O, no clock, no model). `labels/` makes one model call and grounds it. Imports as spec 18 §2; `labels/` uses `artifacts/profile_fence.py` and `artifacts/evidence.py`, never `analysis/` or `diagram/`.
- **Builds on:** `Rates` (spec 10: `currency`, `default_hourly_rate`, `role_group_rates`, `realisation`, `saving_share`), `config/nig/readiness.yaml` (model defined here, §4.4), `counts()` and `is_none_row()` (spec 12), the kept `Opportunity` list (spec 18).
- **Changes:** adds fields to `ValueResult`, `ReadinessDimension`, `Path` and `StepLabels` (allowed by spec 12 §3.11). Defines `ReadinessConfig`, which spec 10 left to this spec.

## 3. Behaviour

### 3.1 Reading durations and frequencies (`domain/value_parse.py`)

Code reads the expert's words with a small fixed grammar. Anything outside it is **unreadable**: the value becomes incomplete and the report names the field. Code never guesses.

**Step 1, clean.** Lower case; trim; whitespace collapsed; "–", "—" and " to " between two numbers become "-"; a leading filler word is removed: `about`, `around`, `roughly`, `approximately`, `approx`, `approx.`, `ca`, `ca.`, `circa`, `~`, `usually`, `typically`, `at least`. A trailing full stop is removed.

**Step 2, quantities.**

| Form | Value | Example |
|---|---|---|
| Number, `.` or `,` as decimal mark | As written | `6`, `1.5`, `1,5` |
| Number words | one…twelve = 1…12; `a`, `an`, `once` = 1; `twice` = 2 | `two hours`, `an hour` |
| `half a` / `half an` | 0.5 of the unit | `half a day` = 4 h |
| Range `N-M`, `between N and M` | Midpoint (assumption, shown in the formula) | `2-3 hours` = 2.5 h |

**Step 3, durations** (S08 `effort.duration`): `QTY UNIT`, optionally a second `QTY UNIT` ("1 hour 30 minutes", "1h30"), optionally followed by a per-run tail (`each`, `each time`, `every time`, `per run`, `per cycle`).

| Unit words | Hours |
|---|---|
| `minute(s)`, `min`, `mins` | 1/60 |
| `hour(s)`, `h`, `hr`, `hrs` | 1 |
| `day(s)`, `working day(s)`, `business day(s)` | 8 (`HOURS_PER_DAY`) |
| `week(s)`, `working week(s)` | 40 |

**Step 4, frequencies** (S08 `effort.frequency`, and P10 `raw` when `count` is empty).

| Kind | Forms | Runs a year |
|---|---|---|
| **Per run** (same rhythm as the process) | `each time`, `every time`, `per run`, `each run`, `every run`, `each cycle`, `every cycle`, `once`, `once per run`, `same as the process`; `N times per run`, `N times each time`, `twice each time` | N × the process's runs a year (N = 1 by default) |
| **Periodic** | `QTY [times] (a|per|every|each|/) PERIOD`; `every [QTY] PERIOD(s)`; `daily`, `weekly`, `fortnightly`, `biweekly`, `monthly`, `quarterly`, `half-yearly`, `yearly`, `annually`; `every <weekday>`; `month end`, `month-end`, `every month end` | QTY × periods a year (÷ QTY for "every QTY periods") |

| Period words | Periods a year (`WORKING_YEAR`) |
|---|---|
| `day`, `working day`, `business day`, `daily` | 250 |
| `week`, weekday names, `weekly` | 50 |
| `fortnight`, `fortnightly`, `biweekly` | 25 |
| `month`, `month end`, `month-end`, `monthly` | 12 |
| `quarter`, `quarterly` | 4 |
| `half year`, `half-year`, `half-yearly` | 2 |
| `year`, `annum`, `yearly`, `annually` | 1 |

*Assumption:* a working year has 50 weeks of 5 days, a day 8 hours. These constants live in `value_parse.py` (Q1).

**Examples.**

| Text | Read as |
|---|---|
| `6 hours` | 6 h |
| `1 day` | 8 h |
| `15 minutes` | 0.25 h |
| `about 2-3 hours each time` | 2.5 h |
| `half an hour` | 0.5 h |
| `a while`, `depends`, `6 hours a month`, `up to 6 hours` | unreadable |
| `every month`, `monthly`, `once a month` | periodic, 12 |
| `10 times a month` | periodic, 120 |
| `every 2 weeks` | periodic, 25 |
| `each time` | per run, × 1 |
| `twice each time` | per run, × 2 |
| `when needed` | unreadable |

**Process runs a year** (P10): `count` and `period` both present → `count × periods(period)` (period read with the period table, with or without `a`/`per`/`every` in front); else `raw` read as a periodic frequency; else unreadable. A volume that is still only proposed (not confirmed) is not used.

### 3.2 Value (`value.py`, F-14)

| Quantity | Formula |
|---|---|
| Step runs a year | Periodic frequency → its runs a year. Per-run frequency → N × process runs a year |
| Step hours a year | duration (h) × step runs a year |
| Hours a year | Σ step hours |
| Opportunity step hours | Σ hours a year of the steps it touches (de-duplicated); `steps == []` → hours a year. `None` if any of its steps has no hours |

*Parked until the value method is decided (refinement R5); not computed while parked; the stored fields are `None`:*

| ~~Quantity~~ | ~~Formula~~ |
|---|---|
| ~~Step rate~~ | ~~`role_group_rates[owner]` (case-insensitive) if present, else `default_hourly_rate`~~ |
| ~~Cost today~~ | ~~Σ step hours × step rate~~ |
| ~~Opportunities used~~ | ~~Every kept opportunity whose `review` is not `rejected`, with its stored `saving_share`. An opportunity with `steps == []` covers every step~~ |
| ~~Step combined share~~ | ~~`min(0.9, 1 − Π(1 − share))` over the opportunities covering the step (`MAX_STEP_SHARE`)~~ |
| ~~Step hours freed~~ | ~~step hours × combined share~~ |
| ~~Opportunity hours freed~~ | ~~Σ over its steps of: step hours freed × its share ÷ Σ shares on that step~~ |
| ~~Hours freed~~ | ~~Σ step hours freed~~ |
| ~~Value~~ | ~~hours freed × rate × realisation: conservative (0.5), expected (0.75)~~ |

1. **Incomplete.** A step whose duration or frequency is unreadable, or a per-run step when the process runs a year are unreadable, gets no hours. Then `complete = false`, `hours_per_year` is `None`, and `missing` lists each field to fix (`process.substeps[4].effort`, `process.volume`), each with a sentence in `problems` ("Effort of step 4 ("a while") could not be read as a duration."). Readable steps still show their own hours.
2. **Rounding.** Stored numbers are rounded to 2 decimals at the end (never in between). Display rules are in spec 20.
3. **Formulas** (`formulas`): one plain line per hours number, built from the inputs, with the expert's words in quotes where text was read. **Assumptions** (`assumptions`): the working-year constants and the midpoint rule if a range was read. No rate, currency, realisation or saving share appears while R5 is parked.
4. **Parked fields** (`cost_today`, `hours_freed`, `value_conservative`, `value_expected`, and per step `rate`, `share`, `hours_freed`, `value_*`, per opportunity `hours_freed`, `value_*`) are always `None` while R5 is parked. `rates.yaml` is still loaded and validated (spec 10) but not read here.

**Worked example (EU fixture, opportunities o1–o4 of spec 18).** Process runs a year: 1 per month × 12 = 12.

| Step | Duration | Frequency | Runs a year | Hours a year |
|---|---|---|---|---|
| 1 Collect site spreadsheets | "6 hours" = 6 | "every month" periodic | 12 | 72 |
| 2 Consolidate into the master file | "1 day" = 8 | "each time" per run | 12 | 96 |
| 3 Analyse variances | "6 hours" = 6 | "monthly" | 12 | 72 |
| 4 Chase explanations | "15 minutes" = 0.25 | "10 times a month" | 120 | 30 |
| 5 Write the variance summary | "6 hours" = 6 | "every month" | 12 | 72 |
| **Total** | | | | **342** |

| Opportunity | Steps | Step hours |
|---|---|---|
| o1 Read the site spreadsheets | 1, 2 | 168 |
| o2 Draft the variance summary | 5 | 72 |
| o3 Chase explanations | 4 | 30 |
| o4 Agree one site template | 1 | 72 |

Example formula line: `Step 4 Chase explanations: 0.25 h ("15 minutes") × 120 runs a year ("10 times a month") = 30 h`.

*Parked (R5), kept for when the value method is decided:* with the configured shares (0.6, 0.4, 0.4, 0.2), the previous method gave cost today €30,780, hours freed 147.36 (step 1 combined 68%, freed 48.96; step 2 57.60; step 4 12.00; step 5 28.80), conservative €6,631.20, expected €9,946.80; per opportunity o1 94.32 h, o2 28.80 h, o3 12.00 h, o4 12.24 h.

If step 4's effort read "a while": step 4 has no hours, `complete = false`, `hours_per_year` `None`, o3's step hours `None`, `missing = ["process.substeps[4].effort"]`.

### 3.3 LABEL: the call (`labels/`)

1. **One call**, `generate_structured(LabelsOut, CallType.LABEL, messages)`; user message: "Label the inputs and decisions of each step in this process profile:" + the fenced profile (spec 18 §3.2).
2. **Wire schema** (strict):

   ```python
   class InputLabelOut(BaseModel):    name: str; format: Literal["structured", "digital_document", "paper", "verbal"]; evidence: str
   class DecisionLabelOut(BaseModel): text: str; kind: Literal["fixed_rule", "explainable_judgement", "pure_judgement"]; evidence: str
   class StepLabelsOut(BaseModel):    step: int; inputs: list[InputLabelOut]; decisions: list[DecisionLabelOut]
   class LabelsOut(BaseModel):        steps: list[StepLabelsOut]
   ```

3. **Prompt rules** (`LABEL_SYSTEM`):

   | # | Rule |
   |---|---|
   | 1 | For every `--- STEP n ---`, label **each input** listed under "Data in and out", using its exact name |
   | 2 | Formats: `structured` = fields a system can read without a person (a system record, a database export, a form or spreadsheet with a fixed layout); `digital_document` = a digital file or message a person reads (PDF, Word, e-mail, a spreadsheet with a free layout); `paper` = printed or handwritten; `verbal` = said in a call or meeting, or known from memory |
   | 3 | List the **decisions** taken in the step (from its activities, approvals, exceptions and goal), each in at most 15 words. Kinds: `fixed_rule` = a written rule or threshold decides, anyone applying it gets the same answer; `explainable_judgement` = a person decides but can name the criteria and give examples; `pure_judgement` = experience or relationships decide, hard to write down |
   | 4 | `evidence`: the expert's words from **that step**, copied exactly, at least three words or a whole short answer |
   | 5 | Never invent inputs or decisions; a step with no decision has an empty list. Never give scores or numbers |
   | — | PROFILE fence sentence; "Return only JSON matching the schema." |

4. **Failure.** Any `LLMError` raises `LabelsFailedError`; the orchestrator stores `labels = []` with outcome `failed` (spec 20), and Data and Rules become **unknown** (F-15.4).

### 3.4 LABEL: grounding (`ground_labels`, pure)

| # | Check | On failure |
|---|---|---|
| L1 | `step` is an int (not a bool) in `1..N`; the first entry per step wins | Entry dropped (`step`) |
| L2 | An input `name` equals (after `normalise_quote`) one of the step's `data.inputs`; it is replaced by the stored spelling; one label per input (first wins) | Label dropped (`input`) |
| L3 | Every evidence passes the quote check restricted to **that step's** values (spec 18 §3.3, `restrict_to_step`) | Label dropped (`quote`) |
| L4 | Decision `text` cleaned to one line, capped at 200, non-empty; at most 5 decisions per step | Dropped (`invalid` / `cap`) |
| L5 | Format and kind are in their literals (guaranteed by the schema, re-checked for mapping input) | Dropped (`invalid`) |
| L6 | Output: one `StepLabels` per step 1..N, in order, even when empty | — |

Inputs that end up without a label are **unlabelled**; they are left out of the Data share and named in its reason.

**Example (EU).**

| Step | Inputs (format) | Decisions (kind) — evidence |
|---|---|---|
| 1 | site cost spreadsheets (digital_document) | — |
| 2 | set of site files (digital_document), SAP cost centre report (structured) | Do the totals match SAP? (fixed_rule) — "reconcile totals with SAP" |
| 3 | consolidated cost file (structured), budget (structured) | Which variances need an explanation (fixed_rule) — "flag variances over 5% or €10k" |
| 4 | list of variances (structured), explanations from site managers (digital_document) | Escalate when there is no answer (fixed_rule) — "no answer by day 3; escalate to the Head of Controlling" |
| 5 | variance list with explanations (digital_document) | What the commentary says (pure_judgement) — "write the commentary"; whether to approve the report (explainable_judgement) — "Head of Controlling" |

A label "invoice scans (paper)" on step 1 is dropped (`input`: not one of step 1's inputs).

### 3.5 Readiness checklist (`readiness.py`, F-15)

Six dimensions, in this order. Each gets a **level** (`high`, `medium`, `low`, `unknown`), a **reason** (one sentence built by code), a **to-prepare** line (only for medium and low), the **steps** it concerns (used by the path), and the specialist's **note** (kept across recomputes). Thresholds come from `readiness.yaml`. **There is no overall verdict.** "Present" below means the field counts (spec 12 `counts`: complete and confirmed).

| Key | Label | Inputs | high | medium | low | unknown | Steps concerned |
|---|---|---|---|---|---|---|---|
| `defined` | Defined | P06, P07, P11 role, S02 per step | Trigger, end result and owner role present, and every step has a goal | Otherwise | 2 or more of {trigger, end result, owner role} missing, or fewer than half the steps have a goal | — | Steps without a goal; all steps if a process part is missing |
| `standard` | Standard | P14, S11 | `same` = yes and exception share ≤ `exception_share_medium` | `same` = partly, or exception share above it | `same` = no | P14 not present | All steps |
| `data` | Data | S07 inputs + input labels | digital share ≥ `digital_share_high` | ≥ `digital_share_medium` | below | Labels failed, or no input labelled | Steps with a paper or verbal input |
| `systems` | Systems | All systems (D02) + application list | known share ≥ `known_system_share_high` | ≥ `known_system_share_medium` | below, or no system named | — | Steps using a system not known |
| `rules` | Rules | Decision labels | rule share ≥ `rule_share_high`, or no decision found | ≥ `rule_share_medium` | below | Labels failed | Steps with a pure-judgement decision |
| `risk_size` | Risk and size | F-14 hours, P10, P15 | Hours ≥ `min_hours_per_year_medium` and no sensitive data | Sensitive data or regulation named (and hours ≥ the minimum) | Hours below `min_hours_per_year_medium` | Hours a year not computed | All steps |

Definitions:

| Term | Definition |
|---|---|
| Exception share | Steps with at least one real exception row ÷ steps |
| Digital share | Labelled inputs whose format is `structured` or `digital_document` ÷ labelled inputs |
| Known system | A distinct system (case-insensitive) that matches an application by name or alias (equal, or the alias as a whole word inside the system name) **and** that application has `export_or_api: true`. The first matching application in list order decides |
| Known share | Known systems ÷ distinct systems |
| Rule share | Decisions of kind `fixed_rule` or `explainable_judgement` ÷ all decisions |
| Sensitive data present | P15 has at least one real row (not the none row) |

**To-prepare line.** The configured line for the dimension and level. For `standard`, when P14 has `differences`, code appends ` What differs today: "<differences>".` (the expert's words, capped at 200). Unknown and high levels have no line.

**Reasons** name the counts, for example: "2 of 3 systems have a known export or API (SAP S/4HANA, Outlook); not: Excel." · "Teams do it differently: "each site sends its own spreadsheet layout"." · "Not rated: the input labels could not be produced." · "About 342 hours a year and no sensitive data." (with " — a large process" added at or above `min_hours_per_year_high`).

**Worked example.**

| Dimension | EU level | Reason (short) | To prepare | NA level |
|---|---|---|---|---|
| Defined | high | Trigger, end result and owner known; 5 of 5 steps have a goal | — | high |
| Standard | **low** | `same` = no: "each site sends its own spreadsheet layout" | Agree one way of working (one template) across teams and regions. What differs today: "each site sends its own spreadsheet layout". | **high** (`same` = yes, exceptions in 2 of 5 steps) |
| Data | high | 8 of 8 inputs are digital | — | high |
| Systems | medium | 2 of 3 systems have a known export or API; not: Excel | Confirm with IT how each system can be reached. | medium |
| Rules | high | 4 of 5 decisions are fixed rules or explainable | — | high |
| Risk and size | high | About 342 hours a year and no sensitive data | — | high |

If LABEL failed: Data and Rules are `unknown`, "Not rated: the input labels could not be produced.", no to-prepare line.

### 3.6 The suggested path (`path.py`, F-12.4)

1. **Blocked by.** For each opportunity, `blocked_by` = the dimensions that are **low**, whose blocked types include the opportunity's type, and whose concerned steps overlap the opportunity's steps (`[]` = all steps). Medium never blocks (F-15.3).

   | Low dimension | Blocks these types |
   |---|---|
   | `defined` | all except `eliminate` and `standardise` |
   | `standard` | `integration`, `document_ai`, `ai_agent`, `rpa` |
   | `data` | `integration`, `ai_agent`, `rpa` |
   | `systems` | `integration`, `ai_agent`, `rpa` |
   | `rules` | `ai_agent`, `workflow` |
   | `risk_size` | none |

2. **Groups** (opportunities with `review == "rejected"` are left out):

   | Group | Who |
   |---|---|
   | `prepare_first` | `type == standardise`, or `blocked_by` not empty |
   | `quick_wins` | The rest with `feasibility == high` |
   | `bigger_changes` | The rest |

3. **Order inside a group**, fully deterministic: opportunity step hours (high first; `None` counts as equal) — *was hours freed, parked (R5)* — then impact (high > medium > low), then feasibility, then the model's order (`o1` before `o2`). In `prepare_first`, `standardise` opportunities come before the blocked ones (the template comes before what needs it).
4. `prepare_items` = the keys of the **low** dimensions, in dimension order (their to-prepare lines lead the *prepare first* group in the report).

**Example.** EU: `blocked_by(o1) = ["standard"]`. Path: prepare first `[o4, o1]` (items `["standard"]`); quick wins `[o2 (72 h), o3 (30 h)]`; bigger changes `[]`. NA (Standard high, no `standardise` opportunity): prepare first `[]`; quick wins `[o2, o3]`; bigger changes `[o1]` (feasibility medium).

### 3.7 Recompute

`compute_code_parts(profile, opportunities, labels, step_ratings, outcomes, rates, readiness_cfg, catalogue, previous_readiness)` runs value (hours) → readiness → blocked_by → path → recommended route (`route_summary`, spec 26 §3.6), with no model call. It runs at *Finish* (spec 20) and after any specialist change to the profile or a review (spec 21). Specialist notes on dimensions are carried over by key.

### 3.8 Amendment (built 2026-11-21): per-run phrases, two-part answers, decision criteria

> **Status:** approved 2026-11-21 · **built 2026-11-21** (AC-19.44 to AC-19.49). As built: `weekday`, `weekend` and `shift` are also not units of work. Why: in evaluation run `20261121-084902` every step's frequency was "once per role, about 6 times a month", which §3.1 cannot read, so the report had **no hours a year at all** (spec 14 §3.21 row 2). Where this section differs from §3.1, §3.3 or §3.5, it wins.

**Parsing (§3.1 steps 3 and 4).** A *unit-of-work noun* is 1–3 words whose first word is not a period word (§3.1 period table, weekday names) and not `run`, `time` or `cycle`; examples: `role`, `candidate`, `request`, `new starter`, `site visit`.

| # | Rule | Example → result |
|---|---|---|
| F1 | **Per run, new forms:** `once per N`, `once for each N`, `once for every N`, `per N`, `each N`, `for each N`, `for every N` (N a unit-of-work noun), and `every time` followed by any words | "once per role", "for every request", "every time we hire" → per run, 1 |
| F2 | `QTY times per N`, `QTY times each N`, `twice per N` | "twice per candidate" → per run, 2 |
| F3 | **Two-part answers:** when the whole text does not parse, it is split on `,` and `;` and each part is read; the first part that is **per run** wins, else the first part that parses; none parses → unreadable as today | "once per role, about 6 times a month" → per run, 1 |
| F4 | **Durations:** the per-run tail of step 3 also takes `per N`, `each N`, `for each N` (N a unit-of-work noun). A period word after `per` stays unreadable (a rate is not a duration per run) | "3 working days per role" → 24 h; "3 hours per week" → unreadable |

**LABEL (§3.3, rule 3).** The fenced profile renders S14 under its step as "Decision criteria: based on: …; set by: …; written: …; varies: …". Added sentence: "When the step's decision criteria say what a decision is based on, that decision is `explainable_judgement` unless the expert's words say it rests on experience or feel."

**Readiness, Rules (§3.5).** Level and reason are unchanged (LABEL decides them). The to-prepare line of `rules` (medium or low) gets, for at most 2 steps with S14 present, in step order: ` Step <n> today: based on "<basis>"` + `, set by <set_by>` (when present) + `, not written down` / `, partly written down` (when `written` is `no` / `partly`) + `, varies: "<varies>"` (when present) + `.` (each value capped at 120). When `rules` is high and a step's S14 has `written: no`, the level stays high and the reason gets ` Criteria for step <n> are not written down.`

| ID | Given / when / then |
|---|---|
| AC-19.44 | `parse_frequency` reads "once per role", "per candidate", "for every request", "every time we hire" as per run 1 and "twice per candidate" as per run 2; "once per month" stays periodic 12; "per weekday" is not per run |
| AC-19.45 | `parse_frequency("once per role, about 6 times a month")` is per run 1; `"about 6 times a month; sometimes more"` is periodic 72; `"it depends, really"` is `None` |
| AC-19.46 | `parse_duration("3 working days per role")` = 24 h; `parse_duration("about 3 hours each candidate")` = 3 h; `parse_duration("3 hours per week")` is `None` |
| AC-19.47 | Regression: the p05 stored profile (effort "about 3 hours" / "about 1 day" × 2, frequency "once per role, about 6 times a month", P10 6 a month) gives 19 h a run and 1,368 h a year (19 × 72), and Risk and size is rated |
| AC-19.48 | The LABEL prompt holds the S14 rendering and the added sentence |
| AC-19.49 | Rules medium with step 3 S14 `{basis: "the hiring manager's must-haves", set_by: "Hiring manager", written: "no", varies: "every manager wants something different"}` → the to-prepare line ends with ` Step 3 today: based on "the hiring manager's must-haves", set by Hiring manager, not written down, varies: "every manager wants something different".`; with no S14 the line is unchanged |

## 4. Interfaces

### 4.1 Parsing and value

```python
# domain/value_parse.py  (pure; used by artifacts and interview)
HOURS_PER_DAY = 8; HOURS_PER_WEEK = 40; WORKING_YEAR: dict[str, float]   # §3.1 tables
@dataclass(frozen=True)
class Duration: hours: float; text: str; midpoint: bool
@dataclass(frozen=True)
class Frequency: kind: Literal["per_run", "periodic"]; value: float; text: str; midpoint: bool
    # per_run: value = multiplier; periodic: value = runs a year
def parse_duration(text: str) -> Duration | None
def parse_frequency(text: str) -> Frequency | None
def runs_per_year(volume: Mapping[str, Any]) -> float | None

# artifacts/value.py  (pure)
MAX_STEP_SHARE = 0.9
def compute_value(profile: Mapping[str, Any], opportunities: Sequence[Opportunity], rates: Rates) -> ValueResult   # rates unused while R5 is parked
```

### 4.2 Labels, readiness, path

```python
# artifacts/labels/labels.py
class LabelsFailedError(Exception): ...
async def run_labels(profile: Mapping[str, Any], llm: LLM) -> tuple[list[StepLabels], dict[str, int]]   # labels, dropped
def ground_labels(reply: LabelsOut | Mapping[str, Any], profile: Mapping[str, Any]) -> tuple[list[StepLabels], dict[str, int]]

# artifacts/readiness.py  (pure)
DIMENSIONS = ("defined", "standard", "data", "systems", "rules", "risk_size")
def compute_readiness(profile: Mapping[str, Any], labels: Sequence[StepLabels], labels_ok: bool,
                      value: ValueResult, cfg: ReadinessConfig,
                      previous: Readiness | None = None) -> Readiness
def match_application(system: str, cfg: ReadinessConfig) -> Application | None

# artifacts/path.py  (pure)
BLOCKS: dict[str, frozenset[str]]                       # table §3.6
def blocked_by(opportunity: Opportunity, readiness: Readiness) -> list[str]
def compute_path(opportunities: Sequence[Opportunity], value: ValueResult, readiness: Readiness) -> Path

# artifacts/assessment_code.py  (pure)
def compute_code_parts(...) -> tuple[ValueResult, Readiness, list[Opportunity], Path, RouteSummary | None]   # §3.7
```

### 4.3 Fields added to the spec 12 models

| Model | Added fields |
|---|---|
| `ValueResult` | `currency: str`, `runs_per_year: float \| None`, `steps: list[StepValue{step, name, duration_hours, runs_per_year, hours_per_year, rate, share, hours_freed, value_conservative, value_expected, problem}]`, `opportunities: list[OpportunityValue{id, step_hours, hours_freed, value_conservative, value_expected}]`, `problems: list[str]`, `formulas: list[str]`, `assumptions: list[str]` (step and opportunity numbers `None` when not computable; parked fields always `None`, R5) |
| `ReadinessDimension` | `label: str`, `steps: list[int]` |
| `Path` | `prepare_items: list[str]` |
| `StepLabels` | (fields fixed by spec 12 suffice) |

### 4.4 `ReadinessConfig` (`app/core/config.py`, this spec owns it)

```python
class DimensionWording(BaseModel):  to_prepare: dict[Literal["low", "medium"], str]       # both required, non-empty
class Thresholds(BaseModel):
    min_hours_per_year_medium: float; min_hours_per_year_high: float     # medium < high
    digital_share_high: float; digital_share_medium: float               # 0 ≤ medium < high ≤ 1
    rule_share_high: float; rule_share_medium: float
    known_system_share_high: float; known_system_share_medium: float
    exception_share_medium: float = 0.5                                   # new, optional
class Application(BaseModel): name: str; aliases: list[str] = []; export_or_api: bool
class ReadinessConfig(BaseModel):   # extra="forbid", frozen
    dimensions: dict[str, DimensionWording]     # exactly the six DIMENSIONS keys
    thresholds: Thresholds
    applications: list[Application]             # names and aliases unique case-insensitively
```

The current `config/nig/readiness.yaml` loads unchanged.

## 5. Implications

- **Other components:** spec 20 calls `run_labels` in parallel with the spec 18 calls and then `compute_code_parts`; the report reads `ValueResult`, `Readiness` and `Path` only and never recomputes. Spec 21 calls `compute_code_parts` after edits and shows the dimension notes. The overview (F-18, spec 21) uses `hours_per_year` and the count of high dimensions (`value_expected` parked, R5).
- **Data:** `assessment.labels`, `assessment.value`, `assessment.readiness`, `assessment.path` and the fields of §4.3.
- **Config:** `ReadinessConfig` model; new optional key `thresholds.exception_share_medium` (default 0.5; add it to `readiness.yaml` when the file is next edited). `rates.yaml` stays loaded but is not read while R5 is parked.
- **Security and privacy:** LABEL sees the fenced profile only; its evidence is checked per step. Hours are per **process step**, never per person (F-23.1).
- **Cost and latency:** one LABEL call per *Finish* (parallel with OPPORTUNITIES and MAP); everything else is pure code in milliseconds.

## 6. Acceptance criteria

| ID | Given / when / then |
|---|---|
| AC-19.1 | `parse_duration` reads every "read as" row of §3.1 (6 hours, 1 day, 15 minutes, about 2-3 hours each time, half an hour, 1 hour 30 minutes, 1h30, 1,5 hours) to the stated hours |
| AC-19.2 | `parse_duration` returns `None` for "a while", "depends", "6 hours a month", "up to 6 hours", "", and a number with no unit |
| AC-19.3 | `parse_frequency` reads every periodic and per-run row of §3.1 (every month, monthly, once a month, 10 times a month, every 2 weeks, every Monday, month-end, quarterly, each time, twice each time) and returns `None` for "when needed" |
| AC-19.4 | A range is read as its midpoint and `midpoint` is true; the assumptions list then says so |
| AC-19.5 | `runs_per_year`: `{count: 1, period: "month"}` → 12; `{count: 400, period: "a month"}` → 4800; `{raw: "twice a week"}` → 100; `{raw: "a few hundred a month"}` → `None`; a proposed volume → `None` |
| AC-19.6 | On the EU fixture with o1–o4, `compute_value` gives hours 342, step hours 72, 96, 72, 30, 72, opportunity step hours o1 168, o2 72, o3 30, o4 72, and `cost_today`, `hours_freed`, `value_conservative`, `value_expected` all `None` *(amended: hours only, R5)* |
| AC-19.7 | *Parked (R5): not tested while the value method is open.* Per-opportunity hours freed always add up to the total hours freed (property test over random shares and step sets) |
| AC-19.8 | *Parked (R5): not tested while the value method is open.* Combined share is `1 − Π(1 − s)` and never above 0.9: two `eliminate` opportunities (0.9 each) on one step free 90% of it |
| AC-19.9 | *Parked (R5): not tested while the value method is open.* A rejected opportunity frees nothing; a whole-process opportunity (`steps == []`) covers every step; an adjusted share is used as stored |
| AC-19.10 | A step frequency "10 times a month" uses 120 runs a year whatever the process volume; "each time" uses the process runs a year |
| AC-19.11 | An unreadable duration on step 4 → `complete == false`, totals `None`, `missing == ["process.substeps[4].effort"]`, a problem sentence quoting the words, and steps 1–3 and 5 still have hours |
| AC-19.12 | An unreadable volume with a per-run step → `missing` contains `process.volume`; with only periodic steps the value is complete |
| AC-19.13 | *Parked (R5): not tested while the value method is open.* With no opportunities, hours freed and value are 0 and `complete` is true |
| AC-19.14 | *Parked (R5): not tested while the value method is open.* `role_group_rates: {"cost controller": 100}` changes the cost of the steps owned by "Cost controller" only |
| AC-19.15 | Every number has a formula line; the line for step 4 is exactly `Step 4 Chase explanations: 0.25 h ("15 minutes") × 120 runs a year ("10 times a month") = 30 h` |
| AC-19.16 | The same profile and opportunities always give the same `ValueResult` (called twice, compared) |
| AC-19.17 | `strict_json_schema(LabelsOut)` builds; the format and kind literals are pinned in a test |
| AC-19.18 | `run_labels` makes one `generate_structured` call with `CallType.LABEL` and the fenced profile; any `LLMError` raises `LabelsFailedError` |
| AC-19.19 | Given the §3.4 reply, `ground_labels` returns 5 `StepLabels` with the inputs and decisions shown and drops "invoice scans" (`input`) |
| AC-19.20 | A label for step 0, 6, a bool or a repeated step is dropped (`step`); an input name is replaced by the stored spelling; a second label for the same input is dropped |
| AC-19.21 | Evidence found only in **another** step is rejected (`quote`); evidence in the step's own cells is accepted |
| AC-19.22 | More than 5 decisions on a step keep the first 5; empty or over-long decision text is cleaned, capped or dropped |
| AC-19.23 | EU fixture with the §3.4 labels → the six levels of §3.5 (EU column); NA fixture → Standard high and the others as shown |
| AC-19.24 | The Standard to-prepare line for EU is the configured low line followed by ` What differs today: "each site sends its own spreadsheet layout".` |
| AC-19.25 | Standard: `partly` → medium; `yes` with exceptions in 3 of 5 steps → medium; `yes` with 2 of 5 → high; P14 missing or only proposed → unknown, no to-prepare line |
| AC-19.26 | Defined: owner `none_identified` counts as missing; two process parts missing → low; 2 of 5 steps without goal → medium; 3 of 5 → low |
| AC-19.27 | Data: shares 0.8 → high, 0.5 → medium, 0.49 → low (thresholds inclusive); no labelled input → unknown |
| AC-19.28 | Systems: "Excel master file" matches Excel (`export_or_api` false); "SAP S/4HANA" matches SAP; an unlisted system is not known; no system at all → low |
| AC-19.29 | Rules: 0.7 → high, 0.4 → medium, below → low; no decision → high with the "no decision" reason |
| AC-19.30 | Labels failed → Data and Rules `unknown` with the "Not rated" reason and no to-prepare line; the other four still rated |
| AC-19.31 | Risk and size: 99 h → low; 342 h and a P15 row "personal data of employees" → medium; 342 h and the none row → high; value incomplete → unknown |
| AC-19.32 | Every medium and low dimension has a to-prepare line from configuration; high and unknown have none; the result has no overall level or score field |
| AC-19.33 | A specialist note on a dimension survives `compute_readiness(..., previous=...)` |
| AC-19.34 | `blocked_by`: EU o1 (document_ai, steps 1–2) → `["standard"]`; o3 (workflow) → `[]`; a medium dimension never blocks |
| AC-19.35 | EU path = prepare first `[o4, o1]`, quick wins `[o2, o3]`, bigger changes `[]`, `prepare_items == ["standard"]`; NA path = `[]`, `[o2, o3]`, `[o1]` |
| AC-19.36 | Order ties are broken by impact, then feasibility, then model order; with an incomplete value the order uses impact, feasibility and model order only; a rejected opportunity appears in no group |
| AC-19.37 | `ReadinessConfig` loads `config/nig/readiness.yaml`; it rejects a missing dimension, an unknown key, `medium ≥ high` thresholds, a share outside [0, 1], an empty to-prepare line and a duplicate alias |
| AC-19.38 | `value_parse`, `value`, `readiness` and `path` import nothing that does I/O, and contain no model call (layer test + import check) |
| AC-19.39 | While R5 is parked, `ValueResult` and every `StepValue` / `OpportunityValue` have `None` for every parked field, and no formula or assumption line contains a currency symbol, "rate", "realisation" or "saving share" |
| AC-19.40 | Opportunity step hours: steps de-duplicated (`[1, 1, 2]` → 168 on EU); `steps == []` → 342; any covered step without hours → `None` |
| AC-19.41 | The path orders inside a group by opportunity step hours: EU quick wins `[o2 (72 h), o3 (30 h)]`; equal or `None` step hours fall back to impact, feasibility, model order |
| AC-19.42 | `value_parse` lives in `domain/` and is importable from `interview` and `artifacts` without breaking the layer test |
| AC-19.43 | `compute_code_parts` with step ratings returns the `RouteSummary` of spec 26 §3.6 built from the same `ValueResult` hours; with no ratings it returns `None` |

## 7. Test plan

| Test file | Covers |
|---|---|
| `tests/unit/process_discovery/domain/test_value_parse.py` | AC-19.1–19.5 (parametrised tables), 19.42 |
| `tests/unit/process_discovery/artifacts/test_value.py` | AC-19.6, 19.10–19.12, 19.15, 19.16, 19.39, 19.40 (19.7–19.9, 19.13, 19.14 parked) |
| `tests/unit/process_discovery/artifacts/test_labels_schemas.py` | AC-19.17 |
| `tests/unit/process_discovery/artifacts/test_labels.py` | AC-19.18–21.22 (`FakeLLM`) |
| `tests/unit/process_discovery/artifacts/test_readiness.py` | AC-19.23–21.33 |
| `tests/unit/process_discovery/artifacts/test_path.py` | AC-19.34–19.36, 19.41, 19.43 |
| `tests/unit/core/test_readiness_config.py` | AC-19.37 |
| `tests/unit/process_discovery/test_architecture.py` | AC-19.38 |

## 8. Out of scope

| What | Where |
|---|---|
| Opportunities, the map, the evidence check | Spec 18 |
| Running LABEL in parallel, timeouts, saving, showing numbers and formulas | Spec 20 |
| Specialist share changes, dimension notes, the overview chart | Spec 21 |
| Per-person time of any kind | Never (F-23.1) |

## 9. Open questions

| # | Question | Default until decided |
|---|---|---|
| Q1 | Move the working-year constants (8 h day, 5-day week, 50 weeks) to `rates.yaml`? | Constants in `value_parse.py`, shown as an assumption in every report |
| Q2 | A range: midpoint or lower bound? | Midpoint, stated in the formula |
| Q3 | Should 100–500 hours without sensitive data be *medium* for Risk and size? That needs a medium to-prepare line about size, which `readiness.yaml` does not have today | No: high; `min_hours_per_year_high` only shapes the reason |
| Q4 | The blocking table (§3.6) refines product F-12.4 ("a low readiness dimension in their steps") by type, so a low Standard does not block a reminder workflow. Accept? | Yes; product F-12.4 to be updated with the table |
| Q5 | Should "partly" with very few exceptions still be medium? | Yes: the expert said it differs |
| Q6 | Add `exception_share_medium: 0.5` to `readiness.yaml` explicitly? | Optional key with default 0.5 until the lead edits the file |
| Q7 | R5: the value method (rate, realisation, saving shares, or another method) | Hours only; the parked text of §3.2 is the starting point when it is decided |
