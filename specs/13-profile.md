# 13 · Profile: applying changes, proposals, completeness, *Finish*

> **Status:** approved · **§3.13 amendment (conflicts, a source per item): approved and built 2026-11-20** (deviations: spec 17 §3.22, spec 14 §3.17 build notes) · **Implements:** F-05, F-08, F-10, F-11 (product); the write side of F-04 (proposals) and F-09 (skipped cells, assumed step count); architecture §3.2 (`profile`), §5 (session document) · **Depends on:** specs 10, 12
> **Code:** `backend/app/services/process_discovery/profile/{constants,shapes,coercion,verdicts,mutate,proposals,scoring,views,raw_snapshot}.py`
> **Tests:** `backend/tests/unit/process_discovery/profile/`

## 1. Purpose

The profile layer is **the only writer of the profile**. Every change, from the expert (through the interview), from a document (as a proposal) or from a specialist, goes through one of its functions. Those functions coerce the value to the field's kind, merge it by the field's rules, record who wrote it (`__meta`), keep the step table in shape, rebuild the roles and systems lists, and grade every field they touched. On top of that the layer answers the two questions everyone else asks: *how complete is the map?* and *may the expert press Finish, and if not, why?*

One rule above all: **a bad change can never corrupt or wipe the profile.** Unknown keys, wrong shapes and empty values are dropped (and reported), never stored.

## 2. Where it sits

- **Layer.** `profile` imports only `domain` (spec 12), the standard library and `pydantic`. It never imports `interview`, `documents`, `artifacts`, `admin`, `export`, `overview` or `service` (layer test, spec 10). LangGraph is not used here.
- **Pure.** No I/O, no clock, no randomness. The time of a write (`at`, ISO 8601 UTC) is passed in. Same input, same output. Inputs are never mutated: every function deep-copies and returns a new profile.
- **Data shape.** Functions take and return plain dicts shaped exactly like `Profile().model_dump(by_alias=True)` (spec 12 §3.11): registry keys, `__meta` and `__skipped` sidecars, none rows `{"none": true}`, optional row sub-fields always present. Any profile this layer returns validates as `Profile` and round-trips unchanged.
- **Uses from spec 12:** the registry (`PROFILE_SPECS`, `STEP_SPECS`, `DERIVED_SPECS`), `evaluate_field`, `has_any_answer`, `counts`, `is_proposed`, `field_status`, `resolve_address`, `step_cell_key`, `required_subfield`, `lenient_object_rows`, `recompute_derived`, the whitelists (`extract_keys`, `proposal_keys`, `specialist_keys`), the constants (`MIN_STEPS`, `MAX_STEPS`, `COMPLETENESS_GATE`, `total_points_for`, the ask limits) and `Vocabulary`. Nothing is restated here.
- **Exists today:** the empty `profile/` package (spec 10). **Changes to existing code:** none.

## 3. Behaviour

### 3.1 Shapes (`shapes.py`)

1. `empty_profile()` returns the JSON skeleton of spec 12 §3.11. `empty_step()` returns the one empty step (every leaf at its empty value, `__meta: {}`, `__skipped: []`).
2. `normalized_profile(p)` deep-copies `p` and **seeds** every missing key (top-level fields, process fields, object sub-fields, step leaves, sidecars, flags) with its empty value. It never rebuilds from scratch, so nothing present is lost. A `process` that is not a dict, or a `substeps` that is not a list, is replaced by the empty value. `None` gives `empty_profile()`.
3. `value_for(profile, key)` reads a process field by registry key; `stored_value(profile, key)` reads any address form (dotted, step cell, bare leaf; spec 12 §3.4). An address to a step that does not exist returns `None`, never an error.
4. `parse_step_key("process.substeps[3].roles")` → `(3, "roles")`; the index stays **1-based**. Storage index = index − 1.

### 3.2 Coercion (`coercion.py`)

Each function either returns a clean value of the declared kind or `None`, meaning "this change adds nothing; leave the field alone".

| Function | Accepts | Returns `None` for |
|---|---|---|
| `coerce_text` | non-blank string (trimmed); int or float → its string | blank, bool, anything else |
| `coerce_number` | int; finite float → `int()`; numeric string → `int(float(s))` | bool, `inf`, `nan`, `1e400`, non-numeric text, **negative numbers** (the models forbid them) |
| `coerce_bool` | bool; `"true"/"yes"/"y"/"1"` and `"false"/"no"/"n"/"0"` (any case) | anything else |
| `coerce_count` | a stored counter: non-negative int | — (returns `0` for anything odd, never `None`) |
| `merged_list(existing, value)` | a list of strings, or one string | nothing new after de-duplication |
| `filtered_object(spec, value)` | a mapping; keeps declared sub-fields only, each coerced by its sub-kind | — (returns `{}` when nothing survives) |
| `filtered_rows(spec, value, *, own_step, step_count)` | anything `lenient_object_rows` reads (spec 12 §3.7) | no usable row |

Field-specific normalisation on write (so validators see a clean value):

| Field | Rule | Example |
|---|---|---|
| P03 region | If `vocab.region(text)` matches, store the canonical spelling; else store the text as typed (the Verdict then says it is not a region) | `"europe"` → `"Europe"`; `"Germany"` stays `"Germany"` (invalid) |
| P14 `same` | Trimmed and lower-cased | `"Partly"` → `"partly"` |
| Row sub-fields | Optional sub-fields missing from a row are written with their defaults (`contribution: ""`, `waiting_time: ""`, `detail: ""`, `loops_back_to: null`) | `{"role": "Controller"}` → `{"role": "Controller", "contribution": ""}` |
| S11 `loops_back_to` | Dropped (the row is kept) when outside `1..step_count` or equal to the row's own step. `step_count` = declared P16, else `MAX_STEPS` | Step 3, `loops_back_to: 3` → `null`; `loops_back_to: 9` → `null` |
| Rows | A row without its required sub-field (`role`, `approver_role`, `description`, `item`) is dropped; a malformed entry is skipped and the rest kept | `[{"contribution": "signs"}]` → no row |

### 3.3 Merge rules by kind (expert changes)

| Kind | Rule | Example (stored → change → result) |
|---|---|---|
| `text` | Replace (trimmed) | `"month end"` → `"Month-end close in the ledger"` → replaced |
| `list` | **Accumulate.** Case-insensitive de-duplication; the first spelling wins. A string is one item. `max_items` is soft: never truncated | `["SAP"]` → `["sap", "Excel"]` → `["SAP", "Excel"]` |
| `number` | Replace with the coerced number | — |
| `object` | **Merge sub-field by sub-field**; a later sub-field overwrites an earlier one; unknown sub-fields dropped | volume `{count: 400}` → `{period: "year"}` → `{count: 400, period: "year", raw: ""}` |
| `object_list` | **Merge rows on the required sub-field** (case-insensitive). A new row is appended. A row matching a stored one fills only the stored row's **empty** sub-fields. The none row lands only on an **empty** cell; it never erases rows. A real row replaces a stored none row. Nothing new → no change | see example 1 |

**None answers.**

| Field | "None" is | Rules |
|---|---|---|
| P15, S04, S10, S11 (object_list) | `[{"none": true}]` | Written only on an empty cell. On a cell with rows: no change (not counted as an edit: no reopen, no flag reset). Any real row later replaces it |
| P11 process owner | `none_identified: true` | A real `role` arriving later clears the flag. A role and the flag in the same change: the role is kept and the flag cleared. A flag-only change on an empty owner sets the flag. A flag-only change on a stored role is ignored (same rule as the none row: "none" never erases). A blank role does not clear the flag |

**Example 1 (roles merge).** Step 2 holds `[{"role": "Controller", "contribution": ""}]`. The change `process.substeps[2].roles = ["Site manager", {"role": "controller", "contribution": "checks variances"}]` gives `[{"role": "Controller", "contribution": "checks variances"}, {"role": "Site manager", "contribution": ""}]`. Then `[{"none": true}]` ("no more roles") changes nothing. `roles_confirmed` becomes `false` after the first change only.

### 3.4 Applying expert changes (`mutate.apply_changes`)

`apply_changes(profile, changes, *, vocab, at) -> ChangeResult` is the expert path (the interview's EXTRACT output, already whitelisted). It runs in this order; the order matters.

| # | Step | Rule |
|---|---|---|
| 1 | Normalise | `normalized_profile(profile)`. A non-mapping `changes` returns the profile unchanged |
| 2 | Per key | Accepted address forms: top-level `department`, `user_function`, `region`; `process.<leaf>`; `process.substeps[i].<leaf>` (1-based); and, leniently, a nested `{"process": {...}}` object. Anything else is refused `unknown_key` |
| 3 | Writability | Refused `not_writable`: `process.cluster` (code sets it, §3.7), flags, `substep_count_rejected`, `all_roles`, `all_tools`, sidecars |
| 4 | Ownership | A field whose meta has `source: specialist` is refused `specialist_owned`; the value is unchanged |
| 5 | Proposals | A field whose meta is `proposed` is **cleared to its empty value first**, then the expert's value is written by kind. So an expert value replaces a proposal; a list does not accumulate onto a proposal |
| 6 | Step index | `i` must be in `1..min(P16, MAX_STEPS)` when P16 is set, else `1..MAX_STEPS`. Outside: refused `index_out_of_range`. A write to step `i` beyond the table pads it with empty steps (a gapped table is allowed) |
| 7 | Write by kind | §3.3. A value that coerces to nothing is refused `shape` (empty values are not refused, just ignored) |
| 8 | Step count | P16 outside `2..6`: not written; stored as `substep_count_rejected` (the expert's number, kept so the agent can refer to it). An in-range P16 clears `substep_count_rejected` |
| 9 | Meta | Every landed write sets that field's meta to `{source: expert, status: confirmed, documentId: null, quote: null, by: null, at}`. Process fields: `profile.__meta[<registry key>]`; step cells: `row.__meta[<leaf>]` |
| 10 | Un-skip | A landed step write removes that leaf from the row's `__skipped` |
| 11 | Invalidate | If any step write landed while `substeps_complete` was true, the loop **reopens**: `substeps_complete`, `roles_confirmed`, `tools_confirmed` all become `false`. A landed write to any `roles` cell sets `roles_confirmed = false`; to any `systems` cell, `tools_confirmed = false` |
| 12 | Resize | §3.5 |
| 13 | Close test | §3.5 |
| 14 | Roll-ups | `all_roles`, `all_tools` rebuilt from scratch (`recompute_derived`). If a roll-up changed, its confirmation flag becomes `false` (§3.8) |
| 15 | Grade | Every written key is graded **after** the whole batch (P13 reads P12's unit; two sub-fields can arrive together; the resize may drop a row). Keys whose row was dropped are not graded |

Every refusal of a non-empty value is logged (`profile_write_refused`, key, reason, value type, never the value) and listed in `ChangeResult.refused`.

`ChangeResult` carries: the new `profile`; `written` (canonical keys that changed, in order); `refused` (`(key, reason)` pairs); `verdicts` (Verdict per written key); `touched_steps` (any step cell written).

**Example 2 (partial write).** Volume is empty; the change is `{"process.volume": {"count": 400}}`. It lands; `verdicts["process.volume"]` is `partial`, missing `("period",)`, reason `Volume still needs: period.` The interview logs it as *written but incomplete* and the next question asks only for the period.

### 3.5 The step table

**Rows and positions.**

| Term | Definition |
|---|---|
| Cell counts | `counts(evaluate_field(spec, value, …), row.__meta[leaf])`: complete **and** not proposed |
| Row started | Any cell of the row has an answer that grades `complete`, proposed or not (so rows that hold only proposals are never trimmed) |
| Row complete | Every **scored** cell (S01–S11) counts or is in `__skipped`. S12 never blocks |
| Last started row | The **position** (1-based) of the last started row, 0 if none. A position, not a count: with a gap, a count would cut off content past the gap |
| Declared count | P16 when it grades complete, else 0 |
| Expected steps | 0 when P16 is not complete; else `min(MAX_STEPS, max(declared, last started))`. This is the denominator's step count and the walk's length |

**Resize** (after every batch of writes):

1. If P16 is set: `P16 = clamp(max(P16, last started), MIN_STEPS, MAX_STEPS)`. A request for fewer steps than there is content for raises P16 back up; content is never deleted.
2. Target rows = `min(MAX_STEPS, max(P16 or 0, last started))`. Grow with empty steps; shrink by dropping **trailing empty** rows only.

**Close** (`substeps_complete`):

1. When `expected > 0`, the table has at least `expected` rows, and rows `1..expected` are all complete → close: `substeps_complete = true`; P16 is **trimmed** to the last started row (never below `MIN_STEPS`); rows after it are deleted. This is the only path that lowers P16 (an expert who said 6 and described 4 has a 4-step process).
2. The model can never close the loop: `substeps_complete` is not writable (§3.4 step 3).

**Example 3 (count).** The expert says "about 13 steps": P16 stays `null`, `substep_count_rejected = 13`, P16 grades `invalid` ("13 steps is outside 2–6…"). Then "let's say 5": P16 = 5, `substep_count_rejected = null`, the table grows to 5 empty steps.

**Skipped cells** (`mark_cells_skipped(profile, keys, *, vocab)`): each canonical step key is added to its row's `__skipped`. The cell is left as it is (empty, or holding an unconfirmed proposal): **settled for the walk, missing for the score.** Ignored: unknown leaves, rows that do not exist, cells that already count. Then the close test and roll-ups run, because the skipped cell may be the one holding the loop open.

**Assumed step count** (`assume_substep_count(profile, *, vocab, at)`): used by the interview when P16 is deferred (F-09). Fill-only: a P16 that counts is never touched. Otherwise P16 = `clamp(last started, 2, 6)`, `substep_count_rejected` cleared, meta expert/confirmed, resize and roll-ups run.

### 3.6 Proposals (`proposals.py`)

A **proposal** is a value read from a document (or, for P04 only, an idea's name). It is stored like any value but its meta says `status: proposed`. It **never counts** (score, row completeness, *Finish*) until the expert confirms it. The rules below are the fill-only rules for machine-found data: a proposal may fill a gap, never overrule a person.

`Proposal = {key, value, document_id, quote}` (a `TypedDict`; `key` in any address form, step cells 1-based).

**`apply_proposals(profile, proposals, *, vocab, at) -> ProposalResult`**

| # | Rule | Refusal reason |
|---|---|---|
| 1 | The key must resolve and be on `proposal_keys()` (P04, P06–P15, every step leaf). P01–P03, P05, P16, flags, roll-ups and sidecars are refused | `not_proposable` |
| 2 | `document_id` and a non-blank `quote` are required. (Whether the quote is really in the document is checked by spec 17 before this call.) | `no_quote` |
| 3 | Target meta `specialist` | `specialist_owned` |
| 4 | Target already has an answer with `status: confirmed` (expert, or a confirmed document value) | `confirmed` |
| 5 | Target empty, or holding another proposal → the proposal **replaces** it (the newer reading wins) | — |
| 6 | **New rows only on an empty table.** If no row was started before this batch, step proposals may create rows `1..MAX_STEPS` (and only up to P16 if P16 is set). Otherwise a step proposal may only fill cells of rows that exist | `table_not_empty`, `index_out_of_range` |
| 7 | Numbers must be in `0..1,000,000`; outside is a parse artefact | `out_of_bounds` |
| 8 | The value is coerced by kind (§3.2) and written **whole** (no merge: the target is empty or a proposal) | `shape` |
| 9 | Meta: `{source: document, status: proposed, documentId, quote, by: null, at}` | — |
| 10 | A proposal on a skipped cell lifts the skip mark (there is now something to confirm) | — |

After the batch: resize (§3.5, P16 is not set by proposals), reopen the loop if a step cell landed while it was closed, rebuild roll-ups and reset a confirmation whose roll-up changed (§3.8). **The score does not move** (proposals do not count). `ProposalResult` = `{profile, applied: [keys], refused: [(key, reason)]}`.

**`confirm_proposals(profile, keys, *, vocab, at) -> ChangeResult`**

1. For each key whose meta is `proposed`: `status` becomes `confirmed`, `at` is updated; `source`, `documentId` and `quote` are kept. The value is not changed. Keys that are not proposals are ignored (never an error).
2. **The step count follows the confirmed steps.** If P16 is empty, the table has 2–6 rows, and every row's S01 now counts, then P16 = number of rows (meta expert/confirmed: the expert confirmed the list). With one row, P16 stays empty and the interview asks for it.
3. Then the close test and roll-ups. The score now includes the confirmed fields.

**`reject_proposals(profile, keys, *, vocab, at) -> ChangeResult`**: each proposed key is cleared to its empty value and its meta entry removed. Then resize (trailing rows left empty are dropped), roll-ups, flag resets.

**`remove_document_proposals(profile, document_id, *, vocab, at)`**: rejects every proposal whose `documentId` matches. Values confirmed from that document stay (the expert confirmed them).

**`propose_from_idea(profile, name, words, *, at)`**: when a session starts from an idea (F-01), P04 gets the name as `{source: expert, status: proposed, quote: words}`. Only on an empty P04.

**`proposed_keys(profile) -> list[str]`**: every proposed field, canonical keys, in ask order: process fields (P04, P06…P15), then step 1 cells S01…S12, step 2, and so on.

**Example 4 (a procedure, then a yes).** Empty table. `apply_proposals` with the trigger ("The review starts once month-end close is completed") and five step names, each with a quote from document `d1`. Result: five rows, six proposed fields, P16 still `null`, score unchanged at 3/18 (P01–P03 only). The expert says yes to the step list; `confirm_proposals` on the five S01 keys → P16 = 5 (expert/confirmed), total points 18 + 55 = 73, filled points 3 + 1 (P16) + 5 (names) = 9.

### 3.7 Code-set values (`mutate.py`)

| Function | Writes | Rules |
|---|---|---|
| `set_cluster(profile, code, *, decided_by, vocab, at, by=None)` | P05 `{code, name, decided_by}` | `code` resolved with `vocab.taxonomy.by_code`; unknown → `UnknownClusterError(code)`. `decided_by` ∈ `proposal`, `named`, `picker`, `specialist`. Meta expert/confirmed, or specialist with `by` when `decided_by == "specialist"`. The only writer of P05 |
| `confirm_rollup(profile, target, *, vocab)` | `roles_confirmed` or `tools_confirmed` | `target` ∈ `roles`, `systems` (else `ValueError`). Roll-ups are rebuilt **before** the flag is raised, so what is confirmed is what the panel shows. Confirming an empty list is allowed here (the second click of F-10.2 is the screen's job) |
| `set_field(profile, key, value, *, by, vocab, at)` | any key on `specialist_keys()` | Specialist edit (spec 21): the value **replaces** the stored one (no accumulate, no merge), coerced by kind; meta `{source: specialist, status: confirmed, by, at}`; same resize, reopen, roll-up and flag rules |

### 3.8 Roll-ups and confirmations

1. `all_roles` and `all_tools` are rebuilt from scratch after **every** write of any kind (`recompute_derived`, spec 12 D01–D02): case-insensitive de-duplication, first spelling wins, none rows contribute nothing.
2. A confirmation survives only while what it confirmed is unchanged:

| Event | Effect |
|---|---|
| A step write lands while `substeps_complete` is true | All three flags `false` (the walk reopens) |
| An expert or specialist write lands on a `roles` cell | `roles_confirmed = false` |
| ... on a `systems` cell | `tools_confirmed = false` |
| Any write (proposal applied, confirmed or rejected, document removed, specialist edit) changes `all_roles` | `roles_confirmed = false` |
| ... changes `all_tools` | `tools_confirmed = false` |
| A write that changes nothing (none row on a filled cell, a duplicate list item) | Nothing |

### 3.9 Completeness (`scoring.py`)

`score(profile, *, vocab) -> Score(value, filled_points, total_points)`

- `filled_points` = Σ weights of P fields that **count** + Σ weights of step cells that count in rows `1..expected`.
- `total_points` = `total_points_for(expected)` (18 + 11 × expected).
- `value` = `filled_points / total_points`, rounded to 4 decimals.
- Proposed values, skipped cells, partial and invalid answers add 0. A given-up field stays missing and lowers the score.

| Situation | Filled / total | Value |
|---|---|---|
| New session | 0 / 18 | 0.0 |
| Context answered, P16 not yet | 3 / 18 | 0.1667 |
| All 18 process points, P16 = 4, nothing in the steps | 18 / 62 | 0.2903 |
| 4 steps: steps 1–3 complete (33), step 4 has 6 cells (6) | 57 / 62 | 0.9194 |
| 6 steps declared: needs `ceil(0.8 × 84)` = 68 | 68 / 84 | 0.8095 |

Declaring more steps lowers the percentage (the denominator grows). That is correct, not a bug.

### 3.10 *Finish* (`scoring.finish_check`)

`finish_check(profile, *, vocab, scope=None) -> FinishCheck(ready, blocked_by, looks_like_task)`. One function, used by the guide prompt, the API and the screen, so they cannot disagree. The checks run **in this order**; the first that fails is `blocked_by` (spec 12 `FinishBlock`):

| Order | Condition | `blocked_by` |
|---|---|---|
| 1 | `score.value < COMPLETENESS_GATE` (0.80; exactly 0.80 passes) | `below_gate` |
| 2 | `substeps_complete` is false | `substeps_incomplete` |
| 3 | `roles_confirmed` is false | `roles_not_confirmed` |
| 4 | `tools_confirmed` is false | `tools_not_confirmed` |
| — | All hold | `ready = true`, `blocked_by = null` |

`looks_like_task` is **advisory and never blocks** (F-06.4). It reads the interview's scope state (`ScopeState` dumped as a mapping, spec 12), live verdict first:

| Scope state | `looks_like_task` |
|---|---|
| verdict `process` | false (a later widening into a real process retires an old override) |
| verdict `task` | true |
| verdict `borderline`, `widening_asked` true | true (asked, and it stayed borderline) |
| verdict `borderline`, not yet asked | false (an open question, not a finding) |
| no verdict, `overridden` true | true |
| no verdict | false |

`rejected_substep_count(profile)` returns the parked out-of-range count or `None`.

### 3.11 Field views for the screens (`views.py`)

`field_views(profile, *, counters, vocab, documents=()) -> list[dict]` builds one `FieldView` (spec 12) per process field and per step cell of every row (S01–S12). The client never computes a status.

| `FieldView` key | Value |
|---|---|
| `key`, `id`, `label`, `phase` | Canonical key, registry ID, `vocab.label(spec)`, the phase (`steps` for cells) |
| `status` | First match: `proposed` (meta proposed and an answer present) → `complete` → `skipped` (cell in `__skipped`) → `given_up` (P field, asks ≥ `FIELD_ASK_LIMIT + REVIEW_ASK_LIMIT`) → `deferred` (P field, asks ≥ `FIELD_ASK_LIMIT`, or the field's own `max_asks`) → `empty` → `invalid` → `partial` |
| `reason`, `missing` | From the Verdict ("" and `[]` when complete) |
| `source`, `quote` | From meta; `quote` only for document and idea values |
| `document_name` | Name of the document whose id is in meta, from `documents` (`[{id, name}]`) |
| `asks` | `counters.field_asks[key]` or `counters.cell_asks[key]`, 0 when absent |

### 3.12 Raw snapshot (`raw_snapshot.py`)

`freeze_raw_substeps(raw, profile) -> list` returns the session's `raw_substeps` (spec 12): if `raw` is non-empty it is returned unchanged (frozen once, forever); otherwise a deep copy of `profile.process.substeps` (possibly `[]`, which the next call may retake). **Every non-expert writer calls it immediately before writing**: `apply_proposals` callers (spec 17) and specialist edits (spec 21). The interview never calls it (it writes only the expert's words). The snapshot never contains a word the expert did not say.

### 3.13 Amendment: conflicts and a source per item

> **Status:** approved 2026-11-20. Write side of spec 17 §3.21 and spec 14 §3.17. Where it differs from §3.6, this section wins.

**1. `apply_proposals` changes.** Rules 3–5 of §3.6 are re-checked as spec 17 §3.21 C1–C8 at write time. A `ConflictOffer` that still meets C3, C5 or C8 is stored in the `__conflicts` sidecar (process fields: `profile.__conflicts[<registry key>]`; step cells: `row.__conflicts[<leaf>]`, so it moves with the row), as a list of the records of spec 17 §3.21 item 4, at most one per `sub`. One that no longer does is dropped (`same_value`, `specialist_owned`, or it became a C1 proposal when the unit was emptied). A C4 merge writes `parts` (spec 12 §3.6). `ProposalResult` gains `conflicts: list[str]` (conflict keys stored).

**2. New functions** (`proposals.py`, pure).

| Function | Does |
|---|---|
| `open_conflicts(profile) -> list[ConflictView]` | Every stored conflict, ask order; `ConflictView{key, sub, conflict_key, kind, status, list, offered, current, document_id, holder_document_id, from_image}`; `current` is read live from the stored unit |
| `resolve_conflicts(profile, conflict_keys, choice, *, vocab, at) -> ChangeResult` | Table below, then the §3.4 steps 10–15 (un-skip, invalidate, resize, close test, roll-ups, grade) |
| `mark_conflicts_left(profile, conflict_keys) -> profile` | `status: "left"`; value untouched |
| `close_conflicts(profile, key, how) -> profile` | Removes the field's conflicts; used by `apply_changes` (item 3) and the ✓ shortcut (spec 14 §3.17 R3) |

**What a choice writes.**

| Choice | Unit after | Source of the written items |
|---|---|---|
| `current` | Unchanged | Unchanged |
| `offered` | The offered value replaces the unit (a sub-field: only that sub-field) | `document`, the offering `documentId`, `quote`, `fromImage` (a part when the field now mixes sources) |
| `both` (expert kind, list-like, union fits `max_items`) | Stored items first, then the offered items not already present | One part per item |

| Then | Rule |
|---|---|
| Status | The field is `confirmed` (the expert decided), **unless** it was `proposed` and other proposed sub-values or items remain: then it stays `proposed` and comes back in a proposals question |
| `replaces` | When the field is proposed with `replaces` (spec 17 §3.1 item 5), the choice is written into `replaces.value` too, so a later "no" to the proposal keeps the expert's choice |
| Conflict | Removed. A conflict key whose record no longer exists is ignored (never an error) |

**3. `apply_changes` addition** (§3.4, after step 9): a landed expert write on a field removes that field's conflicts (closed `own_words`); `ChangeResult` gains `conflicts_closed: list[str]`.

**4. `remove_document_proposals` change**: per item (spec 17 §3.21 P5, P6): only the removed document's items and sub-values leave a proposed field; its conflicts are removed; a document conflict whose holder proposal was cleared becomes the offering document's proposal.

**5. Views** (§3.11): a field view gains `conflict: "open" | "left" | None` and, for a value with `parts`, `items: [{sub, item, source, documentId, fromImage}]` so the panel can name a file per item.

| ID | Given / when / then |
|---|---|
| AC-13.57 | `apply_proposals` with a `ConflictOffer` on an expert unit stores the record in the right sidecar (process / row); on a now-specialist unit stores nothing (`specialist_owned`); on a unit emptied since the reading writes a proposal instead |
| AC-13.58 | Inserting a step before row 3 moves row 3's `__conflicts` with the row; the conflict key in `open_conflicts` follows the new index |
| AC-13.59 | `resolve_conflicts` for `current`, `offered` and `both` writes exactly the table above, with parts per item for `both`; a sub-field choice on a field proposed with `replaces` stays `proposed` and is also written into `replaces.value`, so `reject_proposals` afterwards restores the chosen sub-value |
| AC-13.60 | An expert write through `apply_changes` on a field with an open conflict closes it (`conflicts_closed`); `mark_conflicts_left` changes only `status` |
| AC-13.61 | Neither an open nor a left conflict changes the score, the counting rule or the *Finish* check |

## 4. Interfaces

```python
# profile/constants.py
FLAG_SUBSTEPS_COMPLETE, FLAG_ROLES_CONFIRMED, FLAG_TOOLS_CONFIRMED = "substeps_complete", "roles_confirmed", "tools_confirmed"
FLAG_SUBSTEP_COUNT_REJECTED = "substep_count_rejected"
ROLLUP_TARGETS = ("roles", "systems")            # = LastQuestion.confirm values for the lists (spec 12)
ROLLUP_KEYS = {"roles": "process.all_roles", "systems": "process.all_tools"}
NUMBER_BOUNDS_PROPOSAL = (0, 1_000_000)
Refusal = Literal["unknown_key", "not_writable", "specialist_owned", "index_out_of_range", "shape",
                  "not_proposable", "no_quote", "confirmed", "table_not_empty", "out_of_bounds"]

# profile/shapes.py
def empty_profile() -> dict: ...
def empty_step() -> dict: ...
def normalized_profile(profile: Mapping[str, Any] | None) -> dict: ...
def value_for(profile: Mapping[str, Any], key: str) -> Any: ...
def stored_value(profile: Mapping[str, Any], key: str) -> Any: ...
def parse_step_key(key: str) -> tuple[int, str] | None: ...      # 1-based

# profile/coercion.py   (§3.2)
def coerce_text(v: Any) -> str | None: ...
def coerce_number(v: Any) -> int | None: ...
def coerce_bool(v: Any) -> bool | None: ...
def coerce_count(v: Any) -> int: ...
def merged_list(existing: Any, value: Any) -> list[str] | None: ...
def filtered_object(spec: FieldSpec, value: Any) -> dict[str, Any]: ...
def merged_object(existing: Any, patch: Mapping[str, Any]) -> dict[str, Any]: ...
def filtered_rows(spec: FieldSpec, value: Any, *, own_step: int | None = None,
                  step_count: int | None = None) -> list[dict[str, Any]] | None: ...
def merged_rows(spec: FieldSpec, existing: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]] | None: ...

# profile/verdicts.py
def grade(profile: Mapping[str, Any], key: str, *, vocab: Vocabulary) -> Verdict: ...   # any address form
def field_counts(profile: Mapping[str, Any], key: str, *, vocab: Vocabulary) -> bool: ...
def answer_started(profile: Mapping[str, Any], key: str) -> bool: ...
def cell_counts(row: Mapping[str, Any], leaf: str, *, vocab: Vocabulary) -> bool: ...
def cell_skipped(row: Mapping[str, Any], leaf: str) -> bool: ...
def step_is_started(row: Mapping[str, Any], *, vocab: Vocabulary) -> bool: ...
def step_is_complete(row: Mapping[str, Any], *, vocab: Vocabulary) -> bool: ...
def last_started_row(rows: Any, *, vocab: Vocabulary) -> int: ...
def declared_step_count(profile: Mapping[str, Any], *, vocab: Vocabulary) -> int: ...
def expected_steps(profile: Mapping[str, Any], *, vocab: Vocabulary) -> int: ...
def current_step_index(profile: Mapping[str, Any], *, vocab: Vocabulary) -> int | None: ...  # first incomplete row, 1-based

# profile/mutate.py
class ChangeResult(NamedTuple):
    profile: dict; written: list[str]; refused: list[tuple[str, str]]
    verdicts: dict[str, Verdict]; touched_steps: bool
class UnknownClusterError(ValueError): code: str
def allowed_changes(changes: Any) -> dict[str, Any]: ...           # keeps only extract_keys() (+ nested process form)
def unknown_change_keys(changes: Any) -> list[str]: ...            # shape misses, for the turn log
def apply_changes(profile: Mapping[str, Any] | None, changes: Mapping[str, Any], *,
                  vocab: Vocabulary, at: str) -> ChangeResult: ...
def mark_cells_skipped(profile: Mapping[str, Any], keys: Sequence[str], *, vocab: Vocabulary) -> dict: ...
def assume_substep_count(profile: Mapping[str, Any], *, vocab: Vocabulary, at: str) -> dict: ...
def set_cluster(profile: Mapping[str, Any], code: str, *, decided_by: str, vocab: Vocabulary,
                at: str, by: str | None = None) -> dict: ...
def confirm_rollup(profile: Mapping[str, Any], target: str, *, vocab: Vocabulary) -> dict: ...
def set_field(profile: Mapping[str, Any], key: str, value: Any, *, by: str, vocab: Vocabulary,
              at: str) -> ChangeResult: ...

# profile/proposals.py
# The hand-over types are shared with documents/ (spec 17 §3.11) and declared here exactly:
@dataclass(frozen=True) class FieldProposal: key: str; value: Any; quote: str
@dataclass(frozen=True) class StepProposal: cells: tuple[FieldProposal, ...]      # "name" first
@dataclass(frozen=True) class ProposalDiff: document_id: str; fields: tuple[FieldProposal, ...];
    steps: tuple[StepProposal, ...]; step_cells: tuple[FieldProposal, ...]   # steps and step_cells never both set
class ProposalResult(NamedTuple): profile: dict; applied: list[str]; refused: list[tuple[str, str]]  # (key, reason)
def apply_proposals(profile, diff: ProposalDiff, *, vocab, at) -> ProposalResult: ...
def confirm_proposals(profile, keys: Sequence[str], *, vocab, at) -> ChangeResult: ...
def reject_proposals(profile, keys: Sequence[str], *, vocab, at) -> ChangeResult: ...
def remove_document_proposals(profile, document_id: str, *, vocab, at) -> ChangeResult: ...
def propose_from_idea(profile, name: str, words: str, *, at: str) -> dict: ...
def proposed_keys(profile: Mapping[str, Any]) -> list[str]: ...    # ask order, canonical

# profile/scoring.py
class Score(NamedTuple): value: float; filled_points: int; total_points: int
class FinishCheck(NamedTuple): ready: bool; blocked_by: str | None; looks_like_task: bool
def score(profile: Mapping[str, Any], *, vocab: Vocabulary) -> Score: ...
def finish_check(profile: Mapping[str, Any], *, vocab: Vocabulary,
                 scope: Mapping[str, Any] | None = None) -> FinishCheck: ...
def rejected_substep_count(profile: Mapping[str, Any]) -> int | None: ...

# profile/views.py
def field_views(profile: Mapping[str, Any], *, counters: Mapping[str, Any], vocab: Vocabulary,
                documents: Sequence[Mapping[str, str]] = ()) -> list[dict[str, Any]]: ...

# profile/raw_snapshot.py
def freeze_raw_substeps(raw: Sequence[Mapping[str, Any]], profile: Mapping[str, Any]) -> list[dict]: ...
```

`Score` and `FinishCheck` map 1:1 onto the stored `Score` and the wire `FinishState` (spec 12); the service converts them.

## 5. Implications

- **Interview (spec 14):** writes expert answers only through `allowed_changes` + `apply_changes`; uses `mark_cells_skipped`, `assume_substep_count`, `set_cluster`, `confirm_rollup`, `confirm_proposals`, `reject_proposals`; reads `grade`, `field_counts`, `expected_steps`, `current_step_index`, `score`, `finish_check`. It owns the counters; this layer only reads them (views).
- **Documents (spec 17):** calls `freeze_raw_substeps`, then `apply_proposals` with quote-checked proposals; `remove_document_proposals` on delete; reports `ProposalResult.refused` in its log.
- **Service (spec 15):** stores `Score` and `FinishCheck` on the session and in responses; the ✓/✎ routes call `confirm_proposals` / `reject_proposals`; the cluster route calls `set_cluster(decided_by="picker")`; the confirm route calls `confirm_rollup`; then the interview's `after_action` (spec 14) recomputes the phase. A new session from an idea calls `propose_from_idea`. `UnknownClusterError` → 422 `invalid_value`.
- **Workspace (spec 21):** edits through `set_field` (after `freeze_raw_substeps`). The stored score is **not** recomputed after a specialist edit (completeness measures the interview, F-17.5).
- **Assessment (specs 18, 19):** read the profile; treat a field as answered only if `field_counts` / `cell_counts` says so; unconfirmed proposals are shown as proposals.
- **Data:** no new session fields. The profile's `__meta`, `__skipped`, `substep_count_rejected` and flags (spec 12) are written here.
- **Config:** none. Regions and the taxonomy arrive through `Vocabulary`.
- **Security and privacy:** values are stored as typed; nothing is executed. Logs carry keys, reasons and value types only, never values. Quotes are the only document text in the profile.
- **Cost and latency:** none (pure code).

## 6. Acceptance criteria

| ID | Given / when / then |
|---|---|
| AC-13.1 | `empty_profile()` equals `Profile().model_dump(by_alias=True)`; `empty_step()` equals one empty `Step` dump |
| AC-13.2 | `normalized_profile` seeds a profile missing `process.volume.raw`, a step leaf and the flags; keeps `__meta`, `__skipped` and present values; replaces a non-dict `process`; never mutates its input |
| AC-13.3 | `coerce_number`: `"12"`→12, `3.7`→3, `"inf"`, `nan`, `"1e400"`, `True`, `-4` → `None`; `coerce_text(42)` → `"42"`, blank → `None`; `coerce_count("x")` → 0 |
| AC-13.4 | Lists accumulate with case-insensitive de-duplication, first spelling kept; a string becomes one item; a change adding nothing is not in `written` |
| AC-13.5 | Text replaces (trimmed); region `"europe"` is stored as `"Europe"`, `"Germany"` is stored as typed and grades invalid; P14 `same: "Partly"` is stored as `"partly"` |
| AC-13.6 | An object change keeps only declared sub-fields, coerces them, and merges into the stored object (a later sub-field overwrites); volume `{count: -3}` is refused `shape` |
| AC-13.7 | P11: a role after `none_identified` clears the flag; role + flag in one change keeps the role and clears the flag; a flag-only change on an empty owner keeps the flag; a flag-only change on a stored role changes nothing; a blank role does not clear the flag |
| AC-13.8 | Each lenient roles input of spec 12 §3.7 lands as rows with `contribution: ""` written; a row without its required sub-field is dropped; a malformed entry is skipped and the rest kept |
| AC-13.9 | Example 1 holds: a later role is appended, a matching role (other case) gains only its empty sub-field, stored non-empty sub-fields are never overwritten |
| AC-13.10 | The none row lands on an empty S04/S10/S11/P15; on a cell with rows it changes nothing, is not in `written`, does not reopen the loop and does not reset a flag; a later real row replaces the none row |
| AC-13.11 | `loops_back_to` equal to the row's own step or outside `1..P16` is set to `null` and the description kept |
| AC-13.12 | Step writes are 1-based (`substeps[1]` is storage row 0); with P16 = 4, `substeps[5]` is refused `index_out_of_range` and logged without the value; before P16, `substeps[6]` is accepted and `substeps[7]` refused |
| AC-13.13 | A write to `substeps[3]` on an empty table pads rows 1–2; the gapped table scores against every declared step; closing keeps the step past the gap |
| AC-13.14 | P16 = 13 is not stored, `substep_count_rejected = 13`, P16 grades invalid and earns 0 points; a later P16 = 5 is stored and clears it; every value of 0, 1, 7, 8, 13 is parked |
| AC-13.15 | Resize: grows to the declared count; drops trailing empty rows when P16 falls; raises P16 back to the last started row instead of deleting content; never exceeds 6; lifts a stored P16 below 2 to 2 |
| AC-13.16 | When rows `1..expected` are complete, `substeps_complete` becomes true and P16 is trimmed to the last started row (6 declared, 4 described → 4) and never below 2 |
| AC-13.17 | A step write on a closed loop reopens it: `substeps_complete`, `roles_confirmed`, `tools_confirmed` all false; a write that changes nothing does not |
| AC-13.18 | A landed write to a roles cell clears only `roles_confirmed`; to a systems cell, only `tools_confirmed` |
| AC-13.19 | `allowed_changes` keeps base fields, process keys and step templates of `extract_keys()`, and the nested `{"process": {...}}` form; it drops `process.cluster`, every flag, `substep_count_rejected`, `all_roles`, `all_tools`, `__meta`, `__skipped` and invented keys; a non-mapping gives `{}` |
| AC-13.20 | `apply_changes` refuses `process.cluster` and the flags even when called without `allowed_changes`; `unknown_change_keys` names a misrouted key (`"volume"` at top level) and is shape-only |
| AC-13.21 | Example 2: volume `{count: 400}` lands and its verdict is `partial`, missing `("period",)`; a target in "days" against a baseline in "hours" grades `invalid` in the same batch; refused keys and flags have no verdict |
| AC-13.22 | Every landed write sets meta `{source: expert, status: confirmed, at}` on the right container (profile `__meta` by registry key, row `__meta` by leaf); untouched fields keep their meta |
| AC-13.23 | A field with specialist meta is refused `specialist_owned` and keeps its value and meta |
| AC-13.24 | An expert write to a proposed list `["Excel"]` with `["SAP"]` stores `["SAP"]` (no accumulation onto the proposal) with expert/confirmed meta and no quote |
| AC-13.25 | `apply_changes` never mutates its input; a non-mapping change set returns the profile unchanged |
| AC-13.26 | `all_roles` and `all_tools` are rebuilt after every write: a role removed (by rejection) disappears; "SAP" then "sap" keeps "SAP"; none rows contribute nothing |
| AC-13.27 | `mark_cells_skipped` leaves the cell as it was but settled; a skipped cell earns no points; a cell that counts is never marked; unknown leaves and missing rows are ignored |
| AC-13.28 | A later expert answer to a skipped cell removes it from `__skipped`; skipping every unanswered scored cell completes the row and can close the loop |
| AC-13.29 | `assume_substep_count` takes the last started row, at least 2 and at most 6; leaves a counting P16 alone; clears `substep_count_rejected`; does not mutate its input |
| AC-13.30 | `set_cluster("FIN", decided_by="picker")` writes `{code: "FIN", name: "Finance", decided_by: "picker"}` with expert/confirmed meta; `"XYZ"` raises `UnknownClusterError`; `decided_by="specialist"` writes specialist meta with `by` |
| AC-13.31 | `confirm_rollup` rebuilds the roll-ups before raising the flag; `"steps"` or any unknown target raises `ValueError` |
| AC-13.32 | A row whose S01–S11 count is complete whatever S12 holds; a row with a proposed cell is not complete; a row with that cell skipped is |
| AC-13.33 | `apply_proposals` writes the value with `{source: document, status: proposed, documentId, quote, at}`; the score before and after is identical |
| AC-13.34 | Proposals are refused `not_proposable` for P01–P03, P05, P16, flags and roll-ups, and `no_quote` without a quote or document id |
| AC-13.35 | Fill-only: a proposal on an expert-confirmed or document-confirmed field is refused `confirmed`; on a specialist field `specialist_owned`; on a proposed field it replaces the older proposal |
| AC-13.36 | On an empty table, step proposals create rows (up to 6, and up to P16 when set) and P16 stays `null`; on a table with a started row, a proposal for a new row is refused `table_not_empty` and one for an existing row's empty cell lands |
| AC-13.37 | A proposed volume count of 5,000,000 or −1 is refused `out_of_bounds`; a proposal on a skipped cell lifts the skip mark |
| AC-13.38 | A proposal that adds a role to a confirmed roles list clears `roles_confirmed`; one that changes neither roll-up leaves both flags |
| AC-13.39 | `confirm_proposals` sets `status: confirmed`, keeps source, document id and quote, leaves the value, and the field now counts; non-proposed keys are ignored |
| AC-13.40 | Example 4: confirming the five proposed step names on an empty P16 sets P16 = 5 and total points 73; confirming the only name of a one-row table leaves P16 empty |
| AC-13.41 | `reject_proposals` clears each value to its empty value and removes its meta entry; a trailing row left empty is dropped; roll-ups and flags follow |
| AC-13.42 | `remove_document_proposals("d1")` removes only `d1`'s unconfirmed proposals; values confirmed from `d1` and proposals from `d2` stay |
| AC-13.43 | `proposed_keys` lists process fields in ask order, then step cells by step and leaf order, as canonical 1-based keys |
| AC-13.44 | `propose_from_idea` writes P04 with `{source: expert, status: proposed, quote: <words>}` only when P04 is empty |
| AC-13.45 | `score`: new session 0/18; the rows of the §3.9 table give exactly those numbers; P12 and P13 weigh 2; proposed, skipped, partial and invalid values add 0 |
| AC-13.46 | `expected_steps` is 0 while P16 does not count (even with rows present), else `min(6, max(P16, last started))` |
| AC-13.47 | `finish_check` at 50/62 with all flags is ready; at 49/62 it is `below_gate`; a score of exactly 0.80 passes |
| AC-13.48 | With the score met, removing `substeps_complete`, then `roles_confirmed`, then `tools_confirmed` yields `substeps_incomplete`, `roles_not_confirmed`, `tools_not_confirmed` in turn; a lower score always reports `below_gate` first |
| AC-13.49 | `looks_like_task` follows the §3.10 table for each row, and never changes `ready` or `blocked_by` |
| AC-13.50 | `field_views` returns one view per P field and per step cell; each status of the §3.11 order is produced by a fixture built with the real writers; `reason`, `source`, `quote`, `document_name` and `asks` are filled as specified |
| AC-13.51 | `freeze_raw_substeps` copies the table when `raw` is empty, returns a non-empty `raw` unchanged, and a later expert edit does not change a frozen snapshot |
| AC-13.52 | Round trip: every profile produced in this test suite validates as `Profile` and dumps back unchanged; the score is the same before and after; a none row stays distinct from `[]`; sidecars and meta survive |
| AC-13.53 | Purity: the same inputs (including `at`) give equal outputs; no module in `profile/` imports `datetime.now`, `time`, `random`, file or network modules (AST check) |
| AC-13.54 | No log record written by this layer contains a stored or offered value (sentinel string test across the suite) |
| AC-13.55 | `close_steps` ("No further steps") raises `substeps_complete`, lowers the count to the last started row and drops the empty rows after it; the input is not mutated |
| AC-13.56 | `close_steps` never lowers the count below 2 and never deletes a started (even partly described) step |

## 7. Test plan

All tests use the `nig_vocabulary` fixture (spec 12) and build profiles with the real writers (`empty_profile`, `apply_changes`, `apply_proposals`), never hand-typed keys where a producer exists. A fixture `cost_review_profile(steps=4)` builds the monthly cost review used in the examples.

| Test file | Covers |
|---|---|
| `backend/tests/unit/process_discovery/profile/test_shapes.py` | AC-13.1, 13.2 |
| `backend/tests/unit/process_discovery/profile/test_coercion.py` | AC-13.3–13.11 |
| `backend/tests/unit/process_discovery/profile/test_mutate.py` | AC-13.17–13.26 |
| `backend/tests/unit/process_discovery/profile/test_step_table.py` | AC-13.12–13.16, 13.27–13.29, 13.32 |
| `backend/tests/unit/process_discovery/profile/test_code_set_values.py` | AC-13.30, 13.31 |
| `backend/tests/unit/process_discovery/profile/test_proposals.py` | AC-13.33–13.44 |
| `backend/tests/unit/process_discovery/profile/test_scoring.py` | AC-13.45–13.49 |
| `backend/tests/unit/process_discovery/profile/test_views.py` | AC-13.50 |
| `backend/tests/unit/process_discovery/profile/test_raw_snapshot.py` | AC-13.51 |
| `backend/tests/unit/process_discovery/profile/test_state_integrity.py` | AC-13.52–13.54 (round trips through the Pydantic models; purity AST check; log sentinel) |
| `backend/tests/unit/process_discovery/profile/test_conflicts.py` | AC-13.57–13.61 (amendment §3.13) |

## 8. Out of scope

| What | Where |
|---|---|
| Field definitions, Verdict rules, meta model, whitelists, constants | Spec 12 |
| Ask counters, deferral, phases, reading yes/no in chat, prompts, the turn | Spec 14 |
| Reading documents, checking quotes against the text, BPMN reading | Spec 17 |
| Routes, saving, concurrency, idea documents | Spec 15 |
| Which fields a specialist may edit through which route; audit log | Spec 21 |

## 9. Open questions

| # | Question | Default until decided |
|---|---|---|
| Q1 | Should a document fill the empty sub-fields of a partly answered expert object (volume count given, period missing)? Spec 12 refuses any proposal on a confirmed field | Refused (spec 12 rule); the interview asks for the period |
| Q2 | A reply like "yes, and also SAP" to a proposed systems list: the expert's words replace the proposal, so "Excel" is lost | Accepted for now (the expert's words win); the evaluation set measures how often it happens |
| Q3 | Should the expert be able to lower the number of steps below the content already given ("only 3, not 5")? | No: content is never deleted by a count; the specialist can remove a step (spec 21) |
| Q4 | Should code-settled values (none row after the cell limit, assumed step count) carry their own meta source? | No new source: `expert`/`confirmed`, and the turn log records that code settled them |
