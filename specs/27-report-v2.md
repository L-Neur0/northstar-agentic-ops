# 27 · Report v2: a summary first, three guiding questions, no separate opportunities call

> **Status:** **approved and built 2026-11-21** (backend: AC-27.1 to AC-27.11; frontend by the screens owner, spec 23 §11.16; `make lint test` green). As built: questions in the PDF are paragraphs, not a table (long answers must break across pages); `readiness.yaml` applications gain `general_tool` for Q2; the old opportunity and path code stays for stored sessions but is not called or shown. Approved by the product owner ("then is ok… build tests and code"), after two amendments the same day (parts 6–9 condensed into one; no "where to start" block). Open questions Q1–Q3 take their defaults (thresholds as written; the summary names the internal tool; no "where else AI could help" list) · **Implements:** F-16 (report), F-26 (step assessment), replaces F-12 (opportunities) inside the report (product) · **Depends on:** specs 18, 19, 20, 26
> **Code:** `backend/app/services/process_discovery/artifacts/` (`step_assessment/`, `questions.py` new, `summary.py` new, `report.py`, `path.py`, `value.py`, `assess.py`), `export/report_pdf.py`; screen: `frontend/src/pages/DiscoveryReport.tsx` (spec 23, coordinated with the frontend owner) · **Tests:** `backend/tests/unit/process_discovery/artifacts/test_questions.py`, `test_summary.py`, `test_report_v2.py`

## 1. Purpose

The product owner read the first real report (p05, CV screening) and asked for a different story. **First** a plain summary: what was mapped, how well AI fits, which solution, which steps, from how long to how long. **Then** the process in detail. **Then** a transformation assessment that answers three questions a manager asks:

1. Is this a good AI use case?
2. A dedicated AI solution, or a general assistant (Copilot, ChatGPT)?
3. Is it worth it?

**No go / no-go** (product rule, unchanged, decided 2026-11-21). Each question gets a **level**, *strong / partial / weak* fit or leaning, with reasons and the expert's words. Never a yes or no. Code decides each level from grounded signals (product rules 2, 3, 6). The model reads the profile and writes words; code checks every quote. *(Amended 2026-11-21, product owner: the former parts 6–9, assessment, route, readiness and gaps, "are doing the same thing in the end", so they are **one part: AI readiness and feasibility**.)*

## 2. Where it sits

- **Layer:** `artifacts/` (peers: no import from `interview/`, `admin/`, `documents/`, `export/`, `overview/`).
- **What exists today:** four calls at *Finish*: OPPORTUNITIES (spec 18), MAP (spec 18), LABEL (spec 19) and ASSESS_STEPS (spec 26). The code parts are hours (`value.py`), readiness (`readiness.py`), the path over opportunities (`path.py`) and the route (`step_assessment/route.py`). The report has 11 parts (`report.py`, spec 20).
- **What it changes:**
  - OPPORTUNITIES is no longer called at *Finish*. Its job moves into an extended ASSESS_STEPS (signals per step plus three motivation sentences).
  - The report becomes 6 parts.
  - The suggested path orders **steps**, not opportunities, and merges with the recommended route.
  - Stored sessions that already hold opportunities still load. Their report shows the v2 parts and ignores the old list.

## 3. Behaviour

### 3.1 The report parts (v2)

| # | Title | Built by | Content |
|---|---|---|---|
| 1 | **Summary** | Code template (§3.5) | The context, the three answers in one line each, the solution, the steps, from-to, hours |
| 2 | The process | Profile (as spec 20) | Name, cluster, trigger, end result, owner, pain |
| 3 | Volume and measures | Profile (as spec 20) | Volume, time today, target, same everywhere, sensitive data |
| 4 | Process map and steps | MAP + step table (as spec 20) | Diagram and the step table |
| 5 | Step-by-step AI assessment | ASSESS_STEPS (§3.2) + code | Per step: AI fit, the signals behind it (in words), route, why, hours a year, the expert's words |
| 6 | **AI readiness and feasibility** | Code (§3.3, §3.4) + model motivations | One part, three short blocks, in this order (layout below) |

**Part 6, layout** (everything code-built except the motivation lines, which are checked quotes):

| Block | Shape | Content |
|---|---|---|
| **A. The three questions** | One table, 3 rows: *Question · Level · Why* | Q1 good AI use case, Q2 dedicated or general assistant, Q3 worth it. *Why* is one or two lines: the code reason, then the motivation with its quote |
| **B. Readiness** | One table, 6 rows: *Dimension · Level · To prepare* | The spec 19 checklist, one line each. *To prepare* is empty for high |
| **C. Before starting and risks** | At most 5 bullets in total | Prepare items first (§3.4), then risks (§3.3 Q3). Last line, in small print: *Gaps: <fields missing or given up>; sources: <documents used>* |

Hours a year are not a part of their own. They appear in the summary, in each step row (part 5) and in Q3. The former "Gaps and sources" part becomes the last line of block C. *(Amended 2026-11-21, product owner: no separate "where to start" block; the route shows per step in part 5 and as sentence 3 of the summary.)*

### 3.2 ASSESS_STEPS, extended (one call replaces OPPORTUNITIES)

Each step entry keeps `fit`, `reason`, `evidence`, `route` and `route_reason` (spec 26). It gains **signals**. Each signal is `true` only with the expert's words as evidence from that step; code drops a signal whose quote it cannot find (a dropped signal counts as `false`).

| Signal | Means (rule given to the model) | AI is… |
|---|---|---|
| `reads_unstructured` | The step reads documents or free text whose layout or wording varies (CVs, e-mails, free-layout files) | good at this |
| `compares_to_criteria` | The step checks items against requirements, criteria or a policy written in words | good at this |
| `finds_patterns` | The step looks across many items for patterns, outliers or duplicates | good at this |
| `drafts_text` | The step writes, summarises or explains in words | good at this |
| `must_be_exact` | The result must be exactly right every time (an amount, a legal or safety decision), with no room for a reviewed draft | not the right tool alone |
| `fixed_rules` | The same written rule gives the same answer every time; a script or a rules engine could do it | not needed: a script is enough |

The reply also gains three process-level texts, each 1–2 sentences, each with evidence copied from the profile: `fit_motivation` (Q1), `assistant_motivation` (Q2) and `worth_motivation` (Q3). They are motivations only; levels come from code. A text whose evidence fails the check is replaced by the code reason.

The prompt gets a short **guideline block**, from the 2026-11-21 research. AI (LLMs) is strong at reading varied documents, comparing text with criteria, finding patterns in language, and summarising and drafting. It is weak where the same input must always give the same output, at strict maths or rule logic, and where an unchecked mistake is costly. In those cases rules or a script come first, and a hybrid (rules check, AI reads and drafts, a person approves) is common.

### 3.3 The three questions (code, `questions.py`, pure)

**Q1. Is this a good AI use case?** First per step, then for the process.

| Step level | When (code) |
|---|---|
| **strong** | At least one of `reads_unstructured`, `compares_to_criteria`, `finds_patterns`, `drafts_text`, and not `must_be_exact` |
| **partial** | Such a signal **and** `must_be_exact` (AI drafts, a person or a rule checks), or the step's S13 is `judgement` with no such signal |
| **weak** (a script or rules fit better) | `fixed_rules`, or every input is `structured` (LABEL) and every decision is `fixed_rule`, with none of the four language signals |

**Process level:** **strong** when strong steps hold at least 50 % of the hours a year (if hours are unknown, at least half of the steps). **Partial** when any step is strong or partial. **Weak** otherwise. Reason (code): *"Steps 2 and 3 (1,152 of 1,944 hours) read CVs that vary in layout and compare them with the hiring manager's must-haves; step 1 is admin a script can do."* The step names and hours come from code; the "because" parts are the step signals in fixed wording.

**Q2. A dedicated AI solution, or a general assistant?** Code counts four facts:

| Fact | From |
|---|---|
| **Sensitive data** | P15 has a real row: the data should stay in a controlled, company tool |
| **Needs a connector** | A strong or partial step uses a system that is not an office tool (from the readiness application list and the step's systems), so the AI must reach it |
| **Repeats with the same instructions** | The process runs at least 50 times a year (P10) **and** a strong or partial step has decision criteria (S14) or fixed rules: each run would mean uploading the files and retyping the instructions into a chat |
| **An internal tool already fits** | The route of a strong or partial step is an `existing_internal` catalogue entry |

Level: **leans to a dedicated solution** with 2 or more facts (or an internal tool fits). **Either can work** with exactly 1. **A general assistant is enough** with 0. Reasons list each fact in plain words. Example for p05: *"Candidate CVs are personal data; it runs about 72 times a year with the same must-haves each time; NIG CV screening already does this."*

**Q3. Is it worth it?**

| Level | When |
|---|---|
| **strong** | Hours a year ≥ `min_hours_per_year_high` (500) |
| **partial** | ≥ `min_hours_per_year_medium` (100) |
| **weak** | Below |
| **not rated** | Hours not computed (names the field to fix) |

Reasons: hours and runs a year. *To prepare first* lists the readiness dimensions that are `low`, plus, for strong or partial steps, criteria not written down (S14 `written: no`). *Risks* (each only when present): sensitive data; judgement that varies from person to person (S14 `varies`); steps with pure-judgement decisions (LABEL); exceptions in more than half the steps.

### 3.4 Route and prepare list (part 5, summary sentence 3, part 6 block C)

`route_summary` (spec 26 §3.6) stays. The path no longer orders opportunities. It adds a **prepare** list to the route: the Q3 *to prepare first* items, then the catalogue prerequisites of the start-with routes, at most 5. `path.py` and the opportunity hours in `value.py` are removed. Stored opportunities are kept on old sessions but not shown.

### 3.5 The summary (part 1, `summary.py`, pure)

Fixed sentences, each one left out when its data is missing:

1. *"We mapped **{process name}** in {department} ({cluster name}): {n} steps, about {volume in words}, {time today} each time today."*
2. *"AI fit: **{Q1 level}**. {Q1 reason}."*
3. *"Suggested route: {route headline}."* (the route's code headline)
4. *"{Q2 level sentence}: {Q2 reasons, shortest first}."*
5. *"The expert's target is {target} instead of {time today}."* Only when P13 counts and is in the same unit as P12.
6. *"About {hours} hours a year go into this process today. {Q3 level sentence}."*
7. *"Before starting: {first prepare item}."*

**Worked example (p05, after the live correction):** *"We mapped **Screening applications for an open role** in HR (People & HR): 4 steps, about 6 a month, 3 working days per role each time today. AI fit: **strong**. Steps 2 and 3 (1,152 of 1,944 hours) read CVs that vary in layout and compare them with the hiring manager's must-haves; step 1 is admin a script can do. Suggested route: start with steps 2 and 3 on NIG CV screening. Leans to a dedicated solution: candidate CVs are personal data; it runs about 72 times a year with the same must-haves; NIG CV screening already does this. The expert's target is 1 working day per role instead of 3 working days per role. About 1,944 hours a year go into this process today, a large process. Before starting: write down the must-haves with the hiring managers."*

### 3.6 Small fixes found in the same review

| # | Fix | Where |
|---|---|---|
| R1 | Units match regardless of singular or plural and a "per <unit of work>" tail: "1 working day per role" and "3 working days per role" are the same unit (today P13 is wrongly given up) | `domain/field_spec._validate_target` (spec 12) |

## 4. Interfaces

```python
# artifacts/questions.py
Level = Literal["strong", "partial", "weak", "not_rated"]
class StepFit(BaseModel): step: int; level: Level; because: list[str]
class Answer(BaseModel): level: Level; reasons: list[str]; motivation: str; evidence: str
class Questions(BaseModel): steps: list[StepFit]; q1: Answer; q2: Answer; q3: Answer; prepare: list[str]; risks: list[str]
def answer_questions(profile, ratings: Sequence[StepRating], labels, labels_ok: bool, value: ValueResult,
                     readiness: Readiness, catalogue: SolutionCatalogue, cfg: ReadinessConfig) -> Questions: ...

# artifacts/summary.py
def build_summary(profile, questions: Questions, route: RouteSummary, value: ValueResult, *, vocab) -> list[str]: ...
```

`StepRating` gains `signals: dict[str, bool]` and `signal_evidence: dict[str, str]`. `Assessment` gains `questions: Questions | None`. The `DiscoveryReport` wire model gains the `summary` and `feasibility` parts (`feasibility` = blocks A–C) and loses `at_a_glance`, `steps`-level `route`, `assessment` (opportunities), `potential`, `readiness`, `path` and `gaps` as separate parts (the version bumps to `report-v2`).

## 5. Implications

- **Cost and latency:** 3 calls at *Finish* instead of 4. ASSESS_STEPS grows (about +30 % output); *Finish* should get a little faster.
- **Frontend and PDF:** the report screen and the PDF render 6 parts. The frontend owner (other session) changes `DiscoveryReport.tsx`; the wire model is the contract.
- **Specialist review:** the opportunity review controls go. Specialists keep notes on readiness and can re-run the assessment.
- **Old sessions:** load unchanged. The report is rebuilt from the stored assessment; without `questions`, part 6 shows "Not assessed with this version; re-run the assessment".
- **Product spec:** F-12 is rewritten as "Transformation assessment: three guiding questions" (no verdict, unchanged rule); F-16 lists the 6 parts.

## 6. Acceptance criteria

| ID | Given / when / then |
|---|---|
| AC-27.1 | A step with `reads_unstructured` and `compares_to_criteria` (both grounded) and not `must_be_exact` is **strong**; with `must_be_exact` it is **partial**; a step with only `fixed_rules` is **weak** |
| AC-27.2 | A signal whose evidence is not in that step's words is dropped (counts as false), and the drop is counted |
| AC-27.3 | Process Q1: strong steps holding 1,152 of 1,944 hours → strong; holding 400 of 1,944 → partial; none → weak; hours unknown → by step count |
| AC-27.4 | Q2 on the p05 profile (personal data, 72 runs, S14 on step 3, route `cv-screening` existing internal) → leans to a dedicated solution with those three reasons; a profile with none of the four facts → a general assistant is enough |
| AC-27.5 | Q3: 1,944 h → strong; 120 h → partial; 50 h → weak; hours not computed → not rated naming the field; prepare lists low readiness dimensions and unwritten criteria |
| AC-27.6 | No level is ever "yes", "no", "go" or "no-go"; every motivation shown has a grounded quote or is the code reason |
| AC-27.7 | `build_summary` on the p05 profile gives the §3.5 example sentence by sentence; a missing P13 drops sentence 5; a missing route drops sentence 3 |
| AC-27.8 | `assess` makes MAP, LABEL and ASSESS_STEPS only (no OPPORTUNITIES call) |
| AC-27.9 | The report has the 6 parts of §3.1 in order; part 6 has blocks A–C in order, A with 3 rows, B with 6 rows, C with at most 5 bullets plus the gaps-and-sources line, and no route block; an old stored assessment with opportunities and no `questions` builds a report with the part 6 note and no error |
| AC-27.10 | The ASSESS_STEPS prompt holds the six signal definitions, the guideline block and the three motivation fields; the schema requires them |
| AC-27.11 | R1: "1 working day per role" counts as a target when the time today is "3 working days per role"; "2 hours" against "3 days" is still invalid |

## 7. Test plan

| Test file | Covers |
|---|---|
| `artifacts/test_questions.py` | AC-27.1, 27.3–27.6 |
| `artifacts/step_assessment/test_steps_signals.py` | AC-27.2, 27.10 |
| `artifacts/test_summary.py` | AC-27.7 |
| `artifacts/test_assess.py`, `test_report_v2.py` | AC-27.8, 27.9 |
| `domain/test_evaluate_field.py` | AC-27.11 |
| Live check | p05 demo: *Finish* and read the report against §3.5 |

## 8. Out of scope

- Money and savings (parked, R5). "From-to" uses only the expert's own target.
- A yes / no or go / no-go anywhere (product rule).
- New screens beyond rendering the 6 parts.

## 9. Open questions

| # | Question | Default until decided |
|---|---|---|
| Q1 | Thresholds: 50 % of hours for a strong process fit; 50 runs a year for "repeats"; 2 facts for "leans to dedicated" | As written, tuned with the evaluation set |
| Q2 | Should the summary name the internal tool ("NIG CV screening") or only the kind of solution? | Name it: it comes from configuration |
| Q3 | Keep a short "where else AI could help" list (former opportunities that are not a step), for example "remove the duplicate hand-over"? | No; revisit after the demo |
