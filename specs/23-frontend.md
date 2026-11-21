# 23 · Frontend, part 1: the interview side

> **Status:** **amended 2026-11-21 (report v2): the report page and the workspace popup render the six parts of spec 27 (§11.16, AC-23.152 to AC-23.157)** · **amended 2026-11-21 (S14 *Decision criteria* row in the step panel, AC-23.151)** · **amended 2026-11-21 (owner test): progress bar, no Confirm rung, no Roles and systems section (AC-23.147 to AC-23.149)** · **short step walk (S13 row, f/12, agent proposals), approved 2026-11-20** · amended 2026-11-20 (open workspace: `WORKSPACE_OPEN`, product owner decision) · amended 2026-11-20 (§11.7 open-conflict marker, AC-23.146: built) · part 1 approved · §3.13 theme approved · part 2 (§10–§17: documents, report) built · part 3 (§18–§25: workspace) approved 2026-11-20 (Q14 server names win; Q15 cells as display text from the server; Q16–Q20 defaults) · **Implements:** the screens of F-01, F-02, F-03 (honest exit), F-07 (cluster picker), F-08 (step tabs), F-10, F-11, F-21.1–2 (visitor key, resume link), F-23.4 (delete my data) (product); architecture §1 (two sides), §4 (frontend) · **Depends on:** specs 10 (toolchain), 12 (wire models), 13 (field views, *Finish*), 14 (turn), 15 part 2 (routes), 16 (visitor key)
> **Code:** `frontend/src/{main.tsx,App.tsx,pages,components,services,types,utils,hooks,access}` · **Tests:** next to each file (`*.test.ts[x]`), setup `frontend/src/test/setup.ts`
> **Part 2** (§10–§17 of this file): document upload and proposals (✓ / ✎), the report screen. **Part 3** (§18–§25): the workspace: access-code login, session list, read-only session popup, conversation, PDF, delete. Overview, edits, validation and briefs come later.

## 1. Purpose

Give the expert three things in the browser: **My processes** (sessions, ideas, report status, resume link), the **interview page** (chat on the left, "Your process" on the right, phase meter on top), and the small dialogs around them. The screens show only what the server decides: phase, score, field status, *Finish* state. The client stores no profile logic and computes no completeness.

## 2. Where it sits

- **Side:** interview side of architecture §1 (`pages/Home.tsx`, `pages/ProcessDiscovery.tsx`, `components/process-discovery/`, `components/chat/`). The admin side and the report screen are part 2.
- **Exists today:** the spec 10 scaffold (one page calling `GET /api/health`), Vite + React 18 + TypeScript strict + Tailwind 3 + React Router 7 + React Query 5 + lucide-react + react-markdown/remark-gfm, Vitest + Testing Library + jsdom, the Vite proxy `/api` → `:8000`.
- **Changes:** `App.tsx` becomes the router; the scaffold page and its test are replaced. No backend file changes.
- **Look:** a plain neutral template. Title "AI Use Case Discovery Agent" (renamed 2026-11-21; short form "Use Case Discovery" under the `sm` breakpoint; My processes opens with the tagline "Find a workflow worth transforming, map it step by step, and see where AI can help"; the How this works dialog is titled "How the AI Use Case Discovery Agent works"; the frontend strings live in `src/config/product.ts`), no logo, Tailwind colours (slate neutrals, one blue primary, green / amber / red for status), lucide icons, system font. No external UI kit.

## 3. Behaviour

### 3.1 App shell and routes

| Route | Page | Notes |
|---|---|---|
| `/` | `Home` | My processes |
| `/process-discovery` | `ProcessDiscovery` | No id: decides between resume and new (§3.5 boot) |
| `/process-discovery/:sessionId` | `ProcessDiscovery` | Opens that session |
| `/report/:sessionId` | `DiscoveryReport` | Part 1: a placeholder ("Your map is finished. Your discovery report will be shown here.") with a link back to My processes. Part 2 builds the screen |
| anything else | redirect to `/` | |

1. `main.tsx`: consume the resume fragment (§3.2) **before** the first render, then `QueryClientProvider` (retry 1, no refetch on focus) › `BrowserRouter` › `ApiProvider` (§3.10) › `App`.
2. `AppHeader` (`components/layout/`): a 56 px bar with a neutral `Search` icon, an `<h1>` "AI Use Case Discovery Agent", and an actions slot on the right. Same component on every page.
3. Layout is full height (`h-screen flex flex-col`); only the message list and the profile panel scroll.

### 3.2 Visitor key and private resume link (`access/visitorKey.ts`)

| # | Rule |
|---|---|
| 1 | On first use, `getVisitorKey()` creates 16 random bytes with `crypto.getRandomValues`, encodes them as URL-safe base64 without padding (22 characters), stores them in `localStorage` under `discovery_visitor_key` and returns them. Later calls return the stored key |
| 2 | Every call in `services/api.ts` sends `X-Visitor-Key: <key>` except `/api/taxonomy`, `/api/config`, `/api/health` (public, spec 15 routes 14–16) |
| 3 | If `localStorage` throws or is unavailable, the key lives in memory for this tab only, and Home shows: "Your browser does not keep data for this site. Use the resume link below to come back to your processes." |
| 4 | **Resume link** = `${location.origin}/#k=<key>` (spec 16 §3.1.4). The fragment never reaches the server |
| 5 | `consumeResumeFragment()` runs once in `main.tsx`: if the URL fragment is `#k=<value>` and the value matches `^[A-Za-z0-9_-]{22,64}$`, it stores it as the key, removes the fragment with `history.replaceState`, and sets a one-time notice: "You opened a resume link. You now see the processes saved with it." An invalid value is removed and the notice is "This resume link is not valid." |
| 6 | The key never appears in a log line, an error message or a page URL other than the resume link box |

### 3.3 Home: My processes (`pages/Home.tsx`)

```
+--------------------------------------------------------------------------------+
| [Q] AI Use Case Discovery Agent                              [+ Start a new interview] |  AppHeader
+--------------------------------------------------------------------------------+
| (notice: resume link opened / storage unavailable / deletion done)    [x]      |
| My processes                                                                   |
| First name (optional) [ Anna        ]  Used only to greet you.                 |
|                                                                                |
| Sessions                                                                       |
| | Process              | Status                    | Complete | Last activity | |
| | Monthly cost review  | Mapped · Validated by IT  | 86 %     | 2 hours ago   | [Open report] [Delete] |
| | Not named yet        | In progress · Measures    | 31 %     | yesterday     | [Continue]    [Delete] |
| | Booking travel       | Ended · nothing to map    | 12 %     | 3 days ago    |               [Delete] |
|                                                                                |
| Ideas  (processes you mentioned and can map later)                             |
|  Chasing site managers  "I chase the site managers every Friday"  [Map this] [Delete] |
|                                                                                |
| Continue on another device                              [Show resume link]     |
|   https://<host>/#k=Xy...  [Copy]                                              |
|   Anyone with this link sees your processes. Keep it private.                  |
|                                                                                |
| Your data                                               [Delete all my data]   |
+--------------------------------------------------------------------------------+
```

| # | Rule |
|---|---|
| 1 | Data from React Query: `['sessions']` → `GET /api/sessions`, `['ideas']` → `GET /api/ideas`. Each list has its own loading row, error row with **Retry**, and empty state. A failed load never shows an empty list |
| 2 | Sessions are shown as the server sends them (newest first). Name = `processName` or "Not named yet". Completeness = `round(score × 100) %` |
| 3 | Status column: `active` → "In progress · <phase label>"; `finished` → "Mapped" or "Mapped · Validated by IT" (`reportStatus`); `no_candidate` → "Ended · nothing to map". Status is text, with a pill colour as a second cue only |
| 4 | Actions: `active` → **Continue** (navigate to `/process-discovery/:id`); `finished` → **Open report** (`/report/:id`); every row → **Delete** (confirm dialog "Delete this session? This cannot be undone." → `DELETE /api/sessions/{id}` → invalidate `['sessions']`) |
| 5 | **Start a new interview** (header, and the empty-state button): `POST /api/sessions {displayName?}` → navigate to `/process-discovery/:id` |
| 6 | First name: an optional input (max 40 characters), kept in `localStorage` `discovery_display_name`, sent as `displayName` on every create. Empty → omitted |
| 7 | `IdeasList` shows ideas with status `open`: name, the expert's words in quotes, **Map this** (`POST /api/ideas/{id}/start` → navigate to the new session) and **Delete** (`DELETE /api/ideas/{id}`). Started ideas are not listed (their session is) |
| 8 | Resume link box: hidden behind **Show resume link** (spec 16 Q2). Read-only input with the link, **Copy** (Clipboard API; on failure the input text is selected and the label says "Press Ctrl+C to copy"), and the warning sentence |
| 9 | **Delete all my data**: an alert dialog ("This deletes every session and idea saved with this browser. It cannot be undone.") → `DELETE /api/me` → invalidate both lists → notice "Deleted N sessions and M ideas." The key is kept |

### 3.4 Interview page layout (`pages/ProcessDiscovery.tsx`)

```
+--------------------------------------------------------------------------------------+
| [Q] AI Use Case Discovery Agent    [i How this works] [History Past sessions] [+ New] [My processes] |
+--------------------------------------------------------------------------------------+
| About you › Process › Boundaries › Measures › Step count › step 2 of 4 › Confirm › Review › Finished |
|                                                                 40/62 points · 65 %  |
| [=================================-----------------]   (blue < 40 %, amber, green ≥ 80 %) |
+--------------------------------------------------------------------------------------+
| (error banner, dismissible)                                                           |
+-----------------------------------------------------+--------------------------------+
| Conversation  (role=log)                            | Your process         (aside)   |
|   Agent: Welcome ... Which department are you in?   |  > About you          3/3      |
|                                You: Finance control |  > The process        2/2      |
|   Agent: ...                                        |  > Boundaries         4/4      |
|   [spinner] Thinking...                             |  > Measures           4/6      |
|                                                     |  > Number of steps    1/1      |
|                                                     |  v Steps              1/4      |
|                                                     |    [Step 1 (11/11)][Step 2 (5/11)][...] |
|                                                     |    Step 2 · Consolidate        |
|                                                     |     ✓ Step name   Consolidate  |
|                                                     |     ◌ Systems     Not yet described |
|-----------------------------------------------------|  > Roles and systems  0/2      |
| status line ("Kept 2 ideas on My processes.")       |    Roles: [Controller] ...     |
|                [No process to map - end session]    |    [Confirm roles] [Confirm systems] |
| [ textarea ...................................] [>] |  [ Finish and build my report ] (disabled) |
|                                                     |  Some steps are not fully described yet. |
+-----------------------------------------------------+--------------------------------+
```

1. Chat section `flex-[3]` (about 60 %); the aside `flex-[2]`, max 480 px, left border. Below 1024 px wide the aside moves under the chat (one column, the page scrolls).
2. Header actions, in this order: **How this works** (reopens the intro), **Past sessions** (sessions modal, browse mode), **New** (creates a session), **My processes** (link to `/`). Below 640 px they become icon buttons with `aria-label`s.
3. Main area states: **loading** ("Starting your session…" with spinner); **init failed** ("Could not open this session", the error sentence, **Start a new session**); **ready** (chat + panel).

### 3.5 Boot flow (one `useEffect`, fenced by a `didInit` ref per URL so it runs once under StrictMode)

| URL | Steps |
|---|---|
| `/process-discovery/:id` | `GET /api/sessions/{id}` → `SESSION_RECEIVED`. 404 → init failed with "This session could not be found." |
| `/process-discovery` | `GET /api/sessions`. If any session is `active` → sessions modal in **welcome** mode (§3.9). Otherwise, or if the list call fails → create |
| Create (any path) | `POST /api/sessions {displayName?}` (the stored first name, read synchronously, so the very first create carries it) → `navigate('/process-discovery/:id', {replace: true})` → `SESSION_RECEIVED` with the response (no second GET) |

Changing `:sessionId` (Past sessions, New) resets the page state and runs the boot again.

### 3.6 Phase meter (`DiscoveryPhaseMeter`)

| # | Rule |
|---|---|
| 1 | Rungs: the eight phases of spec 12 §3.1 in `PHASE_ORDER`, then **Finished**. Labels: About you, Process, Boundaries, Measures, Step count, Steps, Confirm, Review, Finished |
| 2 | Past and current rungs use the primary colour and a `›` separator; the current rung has `aria-current="step"`; later rungs are muted. On `finished` every rung is past |
| 3 | On `steps` the Steps rung reads `step X of Y`: X = active step (§3.8.6) + 1; Y = P16 when set, else `~max(rows, X)` (the `~` means "not fixed yet") |
| 4 | On `no_candidate` the rungs are muted and a text "Ended: no process to map" replaces the counter |
| 5 | Right side: `<filledPoints>/<totalPoints> points · <pct> %` with `pct = round(score.value × 100)`, all from the server |
| 6 | Bar: `role="progressbar"`, `aria-valuenow={pct}`, `aria-valuemin=0`, `aria-valuemax=100`, `aria-label="Completeness"`. Colour: green at ≥ 80 %, amber at ≥ 40 %, else primary. The percentage text is always shown, so colour is never the only cue |

**Amended 2026-11-21 (owner test), spec 14 §3.20 O4 and O10.**

| # | Rule |
|---|---|
| 7 | The bar and its percentage show `score.progress` (computed by the server along the interview path; the steps carry their real share), `pct = round(score.progress × 100)`, `aria-label="Progress"`. The client computes nothing. The points text is removed; a session sent without `progress` (an old server) falls back to `score.value` |
| 8 | No **Confirm** rung: the strip is About you, Process, Boundaries, Measures, Step count, Steps, Review, Finished. A session still stored in `confirm` lights the Steps rung as past and Review as current |
| 9 | The "Your process" panel has no **Roles and systems** section (`DerivedReviewPanel` removed); the order is `ProcessCard`, Steps, Documents, *Finish*. The *Finish* blocked sentences are only "below 80 %" and "steps not described"; an unknown code is shown as is |
| 10 | Step names appear in the Steps section as soon as the profile holds them (no wait for P16 or for a confirmation) |
| 11 | **Tab labels** (product owner decision 2026-11-21, amends §3.8.9 and AC-23.33): a named step's tab reads `k · <step name> (f/12)`, the name cut to one line with an ellipsis (CSS, about 12 rem), the full name in the tooltip (`title`) and in the tab's `aria-label` ("Step k: <name>, f of 12 answered"); a step without a name yet reads `Step k (f/12)`. " · proposed" stays after the count |
| 12 | **Decision criteria row** (amended 2026-11-21, spec 12 §3.13, spec 14 §3.21 P1; amends §3.8.9): the step panel shows S14 *Decision criteria* after S13 only when the server sends its cell view (`process.substeps[k].decision_criteria`, sent only for a step whose S13 kind is `judgement` or `mix`). It is optional and unscored: marked "(not scored)" like S12, ✓/✎ when proposed, never counted in `f/12` and never keeping a step unsettled. Shown as "Based on: …; set by …; not written down; varies: …" |

| ID | Given / when / then |
|---|---|
| AC-23.147 | `DiscoveryPhaseMeter` with `score {value: 0.83, progress: 0.34}` shows 34 % and `aria-valuenow=34`; without `progress` it shows the value |
| AC-23.148 | The strip has no Confirm rung; `ProcessProfilePanel` renders no "Roles and systems" section and no Confirm roles / Confirm systems button |
| AC-23.149 | A session whose profile has three step names and P16 = 3 shows the three names in the step tabs |
| AC-23.150 | A tab of a named step shows `1 · <name>` with the truncate class, `title` = the full name and an `aria-label` naming the step and the name; an unnamed step's tab shows `Step 2 (f/12)` |
| AC-23.151 | A step with an S14 view shows a 14th row *Decision criteria* after *Rules or judgement*, marked "(not scored)", with ✓/✎ when proposed, and its tab still counts `(f/12)`; a step without an S14 view (S13 `rules` or unknown) shows thirteen rows. The fake API sends S14 views only for judgement or mix steps |

### 3.7 Chat (`components/chat/`)

| Component | Rules |
|---|---|
| `ChatMessageList` | `role="log"`, `aria-live="polite"`, `aria-label="Conversation"`. Scrolls to the bottom on each new message and when sending starts. While a turn is in flight, a last row with a spinner and `role="status"` reads "Thinking…", and after 20 s "Still working on it. This can take up to two minutes." |
| `ChatMessageBubble` | Agent on the left (neutral bubble, `Bot` icon, label "Agent"), expert on the right (primary-tinted, label "You"). Text rendered with `react-markdown` + `remark-gfm`; raw HTML is not rendered; links open in a new tab with `rel="noopener noreferrer"` |
| `ChatInput` | Auto-growing textarea (max 120 px). **Enter** sends, **Shift+Enter** adds a new line. Trimmed empty text cannot be sent. Limit 16,000 characters (spec 15 route 5); a counter appears from 14,400 characters and turns into a warning at the limit, where Send is disabled. Focus returns to the textarea after a send. Props: `onSend`, `disabled`, `value`/`onChange` (controlled, so a failed send can restore the text) |

Above the composer, in order:

1. **Status line** (`role="status"`): `finished` → "Map finished. Your report is ready." with an **Open report** link; `no_candidate` → "Session ended: no process to map. Start a new one whenever you like."; locked by `session_closed` → "This session is closed."; after a turn with `ideasAdded > 0` → "Kept N ideas on My processes." (until the next turn).
2. **Honest exit** (F-03.5), shown only while `status === "active"` and the session is not locked: a tertiary button "No process to map — end session" (disabled while sending). First press shows inline "End this session without a process to map?" with **Keep going** and **Yes, end it**. The second button calls `POST /api/sessions/{id}/close` and reads "Ending…" while in flight; both are disabled then.
3. **Composer**, disabled when loading, sending, locked, or `status !== "active"`.

**Send** (`sendMessage(text)`): ignored if no session or a turn is in flight. Adds the expert's message optimistically (temporary id from `crypto.randomUUID()`), sets sending, calls `POST /messages {text}`. On success the server's session replaces the slice (the server's copy of the expert message replaces the optimistic one). On failure the optimistic message is removed and its text goes back into the composer, then §3.11 decides banner or lock.

### 3.8 "Your process" panel (`ProcessProfilePanel` and children)

1. `<aside aria-label="Your process">` with heading "Your process". Order: `ProcessCard` (five sections), **Steps** section (`SubstepTabs`), **Roles and systems** section (`DerivedReviewPanel`), then the *Finish* block. Part 2 adds the document panel above the *Finish* block.
2. **Sections.** Each section header is a button with a chevron, `aria-expanded`, `aria-controls`, the title and a `complete/total` count (`processFieldScore.ts`: counts field views with status `complete`; it never grades). Sections of `ProcessCard` follow the field view `phase`:

| Section | Field views |
|---|---|
| About you | `context` (P01–P03) |
| The process | `find` (P04–P05) |
| Boundaries | `boundaries` (P06–P09) |
| Measures | `measure` (P10–P15) |
| Number of steps | `step_count` (P16) |

3. **Field row:** a status icon plus status text, the label (from the field view, so configured wording shows), the value (§3.8.8), and chips. Never colour alone:

| `status` | Icon (lucide) | Text shown |
|---|---|---|
| `complete` | `CheckCircle2` | value only (icon has `aria-label="Complete"`) |
| `partial` | `CircleDashed` | value, then the server's `reason` ("Volume still needs: period.") |
| `invalid` | `AlertTriangle` | value, then `reason` |
| `proposed` | `FileText` | value, chip "Proposed" + `ProposalChip` |
| `skipped` | `MinusCircle` | "Skipped" |
| `deferred` | `Clock` | value or "Not yet described", chip "Asked again later" |
| `given_up` | `CircleSlash` | "Left open" |
| `empty` | `Circle` | "Not yet described" |

4. **`ProposalChip`** (read-only in part 1): "from <documentName>" for document values, "from your idea" for an idea's proposed name (source `expert`, status `proposed`), the `quote` in a `<blockquote>`, and the hint "Say yes in the chat to confirm, or give the right answer." Part 2 adds the ✓ / ✎ buttons and the proposal routes.
5. **Source chip** on counted values: `document` → "from <documentName>"; `specialist` → "edited by IT". Expert values have no chip.
6. **Cluster row (P05):** a **Pick cluster** link (or **Change cluster** when set, hidden when the session is not active) opens `ClusterPicker`. When `clusterProposal` is set, the row shows "Suggested: <name> (<code>). Answer in the chat, or pick another."
7. **Automatic open and close** (one map `{[sectionId]: {collapsed, pinned}}` in page state):

| Event | Effect |
|---|---|
| Phase becomes `steps` | The five `ProcessCard` sections collapse unless pinned; Steps opens unless pinned |
| Phase becomes `confirm` | Roles and systems opens unless pinned |
| Phase becomes `review` | Every unpinned section with a field view that is not `complete` opens |
| The expert clicks a section header | It toggles and becomes **pinned** (no automatic change after that) |

8. **Value formatting** (`discoveryFormat.formatValue(profile, key)`), values read from `session.profile` by the field view `key`:

| Kind | Shown as |
|---|---|
| Text, number | as stored |
| List | items joined with ", " |
| None row `[{none: true}]`, owner `none_identified` | "None" (it counts as an answer) |
| Cluster | "<name> (<code>)" |
| Volume | "<count> per <period>", or `raw` |
| Process owner | role |
| Time today | "<value> <unit>" + " (estimated)", or `qualitative` |
| Target | "<value> <unit>" |
| Same way everywhere | "Yes" / "No: <differences>" / "Partly: <differences>" |
| Sensitive data rows | "<item> (<detail>)" per row |
| Roles rows | "<role> – <contribution>" |
| Approval rows | "<approver_role> (<waiting_time>)" |
| Exception rows | "<description> → back to step <n>" |
| Data in and out | "in: … · out: …" |
| Effort | "<duration> · <frequency>" |

9. **`SubstepTabs`**: header "Steps <complete>/<N>" (N = P16, else rows). One tab per row, `Step k (f/12)` (amended 2026-11-21: `k · <name> (f/12)` once the step has a name, §3.6 rule 11) where f counts the scored step views (S01–S11 and S13, amended 2026-11-20, short step walk) of step k with status `complete` (keys `process.substeps[k].<leaf>`, **1-based**). Tabs follow the WAI-ARIA tabs pattern (`role="tablist"`, roving `tabindex`, arrow keys), scroll horizontally, and the active tab scrolls into view. The tab panel shows "Step k · <name>" and the thirteen cell rows in registry order (S13 *Rules or judgement* after S12); S12 shows "(not scored)". A Tier C value proposed by the agent (meta `source: agent`) shows the chip "suggested from your answers" and the same ✓/✎ as a document proposal. No rows yet → "The steps appear here once you start describing them."
   **No further steps** button under the tabs: enabled only when at least one step row exists, `profile.process.substeps_complete` is false, the session is active and no confirm is in flight; otherwise disabled. It calls `POST /confirm {target: "substeps"}`; the server trims the declared count (P16) to the steps already started (spec 13), and the returned session replaces the panel (tabs, Steps count, phase meter). Hint next to it: "Use this if the process has fewer steps than you said."
10. **Active step** (`substepProgress.activeStepIndex(fieldViews, rows)`): the first row that has an S01–S11 view not `complete` and not `skipped` (the walk goes in order, F-08.3); all settled → the last row. The tab follows it until the expert clicks a tab; any phase change hands control back.
11. **`DerivedReviewPanel`** (section header "Roles and systems x/2", x = confirmed lists): two rows, **Roles** (`profile.process.all_roles`) and **Systems** (`all_tools`), each with read-only chips (or "None yet"), a status text "✓ Confirmed" or "Not confirmed yet", and a button **Confirm roles** / **Confirm systems** → `POST /confirm {target: "roles" | "tools"}`. Disabled while any confirm is in flight or the session is not active. Confirming an **empty** list opens an `alertdialog`: "Confirm that no roles are involved?" with **Cancel** and **Yes, confirm** (F-10.2). Footer: "To correct an entry, say it in the chat."
12. **Finish block:**

| State | Shown |
|---|---|
| `status === "active"`, `finish.ready` | Primary button **Finish and build my report**, and "After this, the session is closed." |
| `status === "active"`, not ready | Same button, disabled, with `aria-describedby` → the reason sentence below it |
| finishing | Button reads "Building your report…" with a spinner; disabled |
| `finish.looksLikeTask` | Info note (never blocks): "This looks like a single task rather than a process. You can still finish; the report will say so." |
| `finished` | Link button **Open my report** |
| `no_candidate` | Nothing |

Reason sentences (`FINISH_BLOCKED_MESSAGES` in `types/process-discovery.ts`); an unknown code is shown as is:

| `blockedBy` | Sentence |
|---|---|
| `below_gate` | "Your map is <pct> % complete. It needs 80 % to finish." |
| `substeps_incomplete` | "Some steps are not fully described yet." |
| `roles_not_confirmed` | "Please confirm the list of roles." |
| `tools_not_confirmed` | "Please confirm the list of systems." |

Press → `POST /finish`. 200 → invalidate `['sessions']`, navigate to `/report/:id`. 409 `map_incomplete` → the reason replaces `finish.blockedBy`; no banner.

### 3.9 Dialogs

All dialogs use one `ui/Modal`: rendered in a portal, `role="dialog"` (or `alertdialog`), `aria-modal`, labelled by its heading, focus moves in on open, Tab cycles inside, **Escape** and backdrop click close it unless `dismissible={false}`, focus returns to the trigger on close. When two dialogs are mounted only the top one reacts to Escape.

| Dialog | Rules |
|---|---|
| `DiscoveryIntroModal` | Opens automatically on the first visit to the interview page (flag `discovery_intro_seen` in `localStorage`; if storage throws, it counts as seen: a dialog that never shows beats one that shows every time). Reopened by **How this works**. Content: five stages with the phase rungs each covers (1 About you and your work: About you, Process · 2 Describe the process: Boundaries, Measures, Step count · 3 Walk the steps: Steps · 4 Confirm and finish: Confirm, Review · 5 Your discovery report: Finished), the four *Finish* conditions (80 % complete, every step described, roles confirmed, systems confirmed), and "Documents can be added at any time; nothing from them counts until you confirm it." Button **Got it, let's start** sets the flag |
| `DiscoverySessionsModal` | Two modes. **Welcome** (from boot): heading "Welcome back", not dismissible (no close button, Escape and backdrop ignored), lists the active sessions. **Browse** (from **Past sessions**): heading "Past sessions", closable, lists all sessions. Each card: name or "Not named yet", a pill ("Finished", "Ended", or `<pct> %`), `<phase label>`, relative time ("2 hours ago"). Clicking a card navigates to it (finished → `/report/:id`). Bottom: **Start new session**. The welcome modal is not mounted while the intro is open; it appears when the intro closes |
| `ClusterPicker` | Loads `GET /api/taxonomy` on open (spinner, error with Retry). A list of buttons, one per cluster in file order: "<name> (<code>)" and the plain description; the current cluster has `aria-pressed="true"` and a primary border. Selecting calls `PUT /cluster {code}`; while in flight the dialog stays open, all buttons are disabled and Escape is ignored; success closes it; 422 `unknown_cluster` shows "That cluster is no longer available. Please pick another." inside the dialog |
| Confirm dialogs | Empty roles or systems (§3.8.11), delete session, delete idea, delete all my data (§3.3). `alertdialog`, the safe button gets focus first |

### 3.10 State: one reducer (`hooks/useDiscoveryState.ts`)

The interview page keeps all server-derived state in one `useReducer`; presentation state (section map, chosen tab, two-press exit, intro open) stays in the page. Every write in spec 15 returns the full `SessionOut`, so the rule is: **a response replaces the server slice; it never touches the UI slice.**

| State key | Slice | Meaning |
|---|---|---|
| `sessionId` | UI | The session this page shows |
| `session` | server | Last `SessionOut` (`status`, `phase`, `messages`, `profile`, `fieldViews`, `score`, `finish`, `scope`, `clusterProposal`, `reportStatus`) |
| `optimistic` | UI | The pending expert message, or `null` |
| `pending` | UI | `{sending, confirming: "substeps" \| "roles" \| "tools" \| null, settingCluster, closing, finishing}` |
| `locked` | UI | `true` after 400 `session_closed` |
| `ideasAdded` | UI | From the last `TurnOut` |
| `restoreText` | UI | Text to put back into the composer after a failed send |
| `clusterPickerOpen`, `clusterError` | UI | Picker state |
| `error`, `initFailed`, `loading` | UI | Banner text, failed boot, boot in progress |
| `pastSessions`, `sessionsModalMode` | UI | `null` \| `"welcome"` \| `"browse"` |

| Action | Effect |
|---|---|
| `BOOT_STARTED(sessionId?)` | `loading`, clears everything else |
| `SESSION_RECEIVED(session)` | Replaces `session`; clears `loading`, the matching `pending` flag, `optimistic` |
| `MESSAGE_SENDING(text)` | `optimistic` set, `pending.sending`, `ideasAdded = 0` |
| `TURN_RECEIVED(turnOut)` | Replaces `session`, clears `optimistic` and `sending`, sets `ideasAdded` |
| `TURN_FAILED(text, message, lock)` | Removes `optimistic`, `restoreText = text`; `lock` → `locked = true` and no banner, else `error = message` |
| `ACTION_STARTED(kind)` | Sets the `pending` flag (`confirming`, `settingCluster`, `closing`, `finishing`) |
| `ACTION_FAILED(kind, message)` | Clears that flag, sets `error` (or `clusterError` for the picker) |
| `FINISH_BLOCKED(reason)` | `session.finish = {ready: false, blockedBy: reason, …}`, clears `finishing`; **no** `error` |
| `SESSION_LOCKED(message)` | `locked = true`, clears every `pending` flag |
| `CLUSTER_PICKER_OPENED` / `_CLOSED` | Toggles the picker; closing clears `clusterError` |
| `SESSIONS_SHOWN(list, mode)` / `SESSIONS_HIDDEN` | Sessions modal |
| `ERROR(message)` / `ERROR_CLEARED` / `INIT_FAILED(message)` | Banner and failed boot |

Every async action carries the `sessionId` it was started for; the reducer ignores a result for another session (a slow reply after **New** must not overwrite the new session).

### 3.11 Errors (`utils/discoveryErrors.ts`)

`services/api.ts` throws `ApiError{status, code, message, reason?}` built from the `{code, message}` body; a body that is not JSON gives `code = "http_<status>"`; a network failure gives `status 0, code "network"`. One table turns codes into UI effects:

| Code (HTTP) | UI effect | Text shown |
|---|---|---|
| `session_closed` (400) | Lock composer, clear spinners, no banner | Status line "This session is closed." |
| `unsafe_input` (400) | Banner; message text restored to the composer | The server's sentence |
| `not_found` (404) | Boot: init-failed view. Elsewhere: banner | "This session could not be found." |
| `map_incomplete` (409) | Not an error: `FINISH_BLOCKED(reason)` | Reason sentence (§3.8.12) |
| `conflict` (409) | Reload the session (`GET`) and show a banner | "This session changed in another tab. It has been reloaded; please try again." |
| `unknown_cluster` (422) | Inside the picker | §3.9 |
| other 422 | Banner | "That could not be saved. Please check what you entered." |
| `rate_limited` (429) | Banner | "Too many requests. Please wait a moment and try again." |
| `budget_exhausted` (429) | Banner | "The tool has reached its limit for today. Please try again tomorrow." |
| `model_unavailable` (503) | Banner | "The assistant is not available right now. Please try again later." |
| `visitor_key_required` (401) | Banner | "Your browser key is missing or damaged. Reload the page." |
| `network` (0) | Banner | "Could not reach the server. Check your connection and try again." |
| anything else | Banner | The server's `message`, else "Something went wrong. Please try again." |

The banner (`ui/Alert`, `role="alert"`) sits under the phase meter and has a close button. Error texts never contain the expert's message.

### 3.12 Fake API first, then the real one (`services/api.ts`, `services/fakeApi.ts`)

1. **One interface.** `DiscoveryApi` (in `services/api.ts`) has one method per route used (§4). `createHttpApi()` implements it with `fetch`; `createFakeApi(options?)` (in `services/fakeApi.ts`) implements it in memory. `ApiProvider` / `useApi()` (React context) hand the instance to the hook and pages, so tests inject a fake without module mocks.
2. **Choice:** a typed fake module, not MSW: no extra dependency, the same TypeScript types as the real client (a contract change breaks the build), usable in dev and in tests. The HTTP layer is covered separately by `services/api.test.ts` with a stubbed `fetch`.
3. **Mode:** `VITE_API_MODE=fake` selects the fake (`npm run dev:fake`); default `http`. `vite.config.ts` **fails a production build** when the mode is `fake`; the fake is loaded by dynamic import so it is not in the real bundle.
4. **What the fake does:** keeps sessions and ideas in memory (and `sessionStorage`, so a reload keeps them), plays a scripted interview about the **monthly cost review** (department, role, region, three candidates of which two become ideas, cluster proposal FIN, boundaries, measures, 4 steps, confirm, review), and returns the same `SessionOut` / `TurnOut` shapes with field views and *Finish* state. Only the fake builds field views; real client code never does. Waits 300–800 ms per call to show spinners.
5. **Triggers for manual testing:** a message `/error <code>` makes the next call fail with that code (`/error session_closed`, `/error budget_exhausted`, …); `/finish-ready` jumps to a complete map.
6. **Switch to the real API:** (a) reconcile `types/process-discovery.ts` with spec 15 §3.3–3.4 (done: the calls in §4 are those routes); (b) optional: load the JSON response samples the backend API tests write to `backend/tests/fixtures/api/` (Q1) next to the hand-made fixtures in `src/test/fixtures/`; (c) run the page tests against both the fake and recorded fixtures; (d) `make dev` and walk one interview by hand against the in-memory backend.

### 3.13 Light and dark theme (`theme/`, `AppHeader`)

1. Two themes, **light** and **dark**, for every screen. Tailwind `darkMode: "class"`: the `dark` class on `<html>` switches the theme.
2. **Colours are tokens, not literals:** CSS variables in `index.css` (`--bg`, `--surface`, `--surface-muted`, `--border`, `--text`, `--text-muted`, `--primary`, `--primary-contrast`, `--success`, `--warning`, `--danger`, the expert bubble and the agent bubble), defined once for `:root` and once for `.dark`, and mapped to Tailwind colour names in `tailwind.config.js`. Components use the token names (`bg-surface`, `text-muted`), so a component never needs two colour classes.
3. **Toggle:** an icon button at the right of the header on every page: a moon in light mode ("Switch to dark theme"), a sun in dark mode ("Switch to light theme"). `aria-label` and `title` say what it does; `aria-pressed` reflects dark mode.
4. **Choice remembered:** the toggle stores `"light"` or `"dark"` in `localStorage` (`pd_theme`). With nothing stored, the theme follows the system setting (`prefers-color-scheme`) and follows it live when it changes.
5. **No flash:** a tiny inline script in `index.html` sets the class before React starts (reads `pd_theme`, else the system setting). Storage errors (private mode) fall back to the system setting.
6. **Contrast:** text and controls meet WCAG AA (4.5:1 for text, 3:1 for icons and borders) in both themes; status is never shown by colour alone (unchanged rule).
7. The Mermaid process map (part 2) uses its dark theme when the app is dark.

## 4. Interfaces

**API calls used by part 1** (spec 15 part 2 §3.3; camelCase; `X-Visitor-Key` on all but taxonomy):

| `DiscoveryApi` method | Route | Request | Response |
|---|---|---|---|
| `createSession({displayName?, fromIdeaId?})` | `POST /api/sessions` | `{displayName?, fromIdeaId?}` | 201 `SessionOut` |
| `listSessions()` | `GET /api/sessions` | — | `{sessions: SessionSummary[]}` |
| `getSession(id)` | `GET /api/sessions/{id}` | — | `SessionOut` |
| `deleteSession(id)` | `DELETE /api/sessions/{id}` | — | 204 |
| `sendMessage(id, text)` | `POST /api/sessions/{id}/messages` | `{text}` (1–16,000) | `TurnOut` |
| `confirm(id, target)` | `POST /api/sessions/{id}/confirm` | `{target: "substeps" \| "roles" \| "tools"}` | `SessionOut` |
| `setCluster(id, code)` | `PUT /api/sessions/{id}/cluster` | `{code}` | `SessionOut` |
| `close(id)` | `POST /api/sessions/{id}/close` | — | `SessionOut` |
| `finish(id)` | `POST /api/sessions/{id}/finish` | — | `SessionOut`; 409 `map_incomplete` + `reason` |
| `listIdeas()` | `GET /api/ideas` | — | `{ideas: Idea[]}` |
| `startIdea(id)` | `POST /api/ideas/{id}/start` | — | 201 `SessionOut` |
| `deleteIdea(id)` | `DELETE /api/ideas/{id}` | — | 204 |
| `deleteMyData()` | `DELETE /api/me` | — | `{sessions, ideas}` |
| `getTaxonomy()` | `GET /api/taxonomy` | — | `{clusters: [{code, name, description}]}` |

Not used in part 1: `GET /api/config` (part 1 needs none of its values; the title is fixed), the document, proposal and report routes (part 2).

**Types** (`types/process-discovery.ts`, a mirror of the wire models; spec 12 §3.11, spec 15 §3.4):

```ts
type Phase = 'context' | 'find' | 'boundaries' | 'measure' | 'step_count' | 'steps' | 'confirm' | 'review' | 'finished' | 'no_candidate'
type SessionStatus = 'active' | 'finished' | 'no_candidate'
type FieldStatus = 'complete' | 'partial' | 'invalid' | 'proposed' | 'skipped' | 'empty' | 'deferred' | 'given_up'
type FinishBlock = 'below_gate' | 'substeps_incomplete' | 'roles_not_confirmed' | 'tools_not_confirmed'
interface Message { id: string; role: 'expert' | 'agent'; text: string; at: string }
interface FieldView { key: string; id: string; label: string; phase: Phase; status: FieldStatus; reason: string;
  missing: string[]; source: 'expert' | 'document' | 'specialist' | null; quote: string | null; documentName: string | null; asks: number }
interface FinishState { ready: boolean; blockedBy: FinishBlock | null; looksLikeTask: boolean }
interface Score { value: number; filledPoints: number; totalPoints: number }
interface SessionOut { id: string; status: SessionStatus; phase: Phase; displayName: string | null; createdAt: string;
  updatedAt: string; finishedAt: string | null; messages: Message[]; profile: Profile; fieldViews: FieldView[];
  score: Score; finish: FinishState; scope: { verdict: string; widened: boolean } | null;
  clusterProposal: { code: string; name: string; description: string } | null; reportStatus: 'mapped' | 'validated' | null }
interface TurnOut { reply: Message; session: SessionOut; ideasAdded: number }
interface SessionSummary { id: string; status: SessionStatus; phase: Phase; processName: string | null;
  clusterCode: string | null; score: number; messageCount: number; createdAt: string; updatedAt: string; reportStatus: string | null }
interface Idea { id: string; name: string; words: string; status: 'open' | 'started' | 'dismissed';
  fromSessionId: string; startedSessionId: string | null; createdAt: string }
interface ApiErrorBody { code: string; message: string; reason?: string }
// Profile: the registry keys of spec 12 §3.11 (snake_case inside, as stored), without __meta / __skipped.
// Constants: PHASE_STRIP, PHASE_LABELS, SECTION_OF_PHASE, FINISH_BLOCKED_MESSAGES, MESSAGE_MAX_CHARS = 16000.
```

**Hook:** `useDiscoveryState(sessionId?)` returns `{state, boot, sendMessage, confirm, setCluster, closeSession, finish, showPastSessions, openPicker, closePicker, clearError}`.

**Component tree** (part 1):

```
main.tsx → QueryClientProvider › BrowserRouter › ApiProvider › App (routes)
├── pages/Home.tsx
│   ├── layout/AppHeader                      [Start a new interview]
│   ├── ui/Alert                              notices
│   ├── sessions table (inline)               ui/Pill, ui/Button, ui/Modal (confirm delete)
│   ├── process-discovery/IdeasList
│   ├── resume link box (inline)
│   └── delete all my data (inline)           ui/Modal (alertdialog)
├── pages/ProcessDiscovery.tsx                hooks/useDiscoveryState
│   ├── layout/AppHeader                      How this works · Past sessions · New · My processes
│   ├── process-discovery/DiscoveryPhaseMeter ui/ProgressBar
│   ├── ui/Alert                              error banner
│   ├── <section aria-label="Discovery conversation">
│   │   ├── chat/ChatMessageList → chat/ChatMessageBubble, ui/Spinner
│   │   ├── status line · honest exit (inline two-press)
│   │   └── chat/ChatInput
│   ├── process-discovery/ProcessProfilePanel <aside>
│   │   ├── ProcessCard → field rows, ProposalChip, cluster link
│   │   ├── SubstepTabs (ui/Tabs) + No further steps
│   │   ├── DerivedReviewPanel (ui/Modal alertdialog for empty lists)
│   │   └── Finish block
│   ├── process-discovery/ClusterPicker        ui/Modal
│   ├── process-discovery/DiscoverySessionsModal  ui/Modal
│   └── process-discovery/DiscoveryIntroModal  ui/Modal
└── pages/DiscoveryReport.tsx                 placeholder (part 2)
access/visitorKey.ts · services/api.ts · services/fakeApi.ts · types/process-discovery.ts
utils/{processFieldScore,substepProgress,discoveryErrors,discoveryFormat}.ts
ui/{Modal,Button,Pill,Tabs,ProgressBar,Alert,Spinner}.tsx
```

`ui/Button` variants: primary, secondary, tertiary, danger; `disabled` and `loading`. `ui/Pill` tones: neutral, info, success, warning, danger (always with text).

## 5. Implications

- **Other components:** spec 15 part 2 is the contract; any change there changes §4 and the fake. Part 2 of this spec adds `DocumentPanel`, the ✓ / ✎ buttons on `ProposalChip`, `GradePill`, the report page and the workspace, reusing `Modal`, `Alert`, the reducer and `discoveryErrors`.
- **Data:** browser storage holds only `discovery_visitor_key`, `discovery_display_name`, `discovery_intro_seen` (`localStorage`) and the fake's data (`sessionStorage`, fake mode only).
- **Config:** `VITE_API_MODE` (`http` \| `fake`), build-time; nothing else. Same origin, no API base URL.
- **Security and privacy:** the visitor key is a bearer secret: sent only in the header, shown only in the resume box with a warning, never in logs or errors. Markdown never renders raw HTML. No third-party scripts, fonts or trackers. The client hides actions it cannot use, but the server checks everything (F-21.5).
- **Cost and latency:** no model calls from the client; one request per turn; no polling, streaming or WebSocket.

**Behaviours that must not be lost** (each has an AC):

| # | Behaviour |
|---|---|
| 1 | The *Finish* button state comes only from `finish.ready`; `looksLikeTask` never disables it |
| 2 | 409 `map_incomplete` is not an error (no banner); 409 `conflict` reloads |
| 3 | 400 `session_closed` locks the composer and clears every spinner |
| 4 | The two endings are told apart by `status` (`finished` vs `no_candidate`); "report ready" is never shown for `no_candidate` |
| 5 | A response replaces the server slice only; open dialogs, collapsed sections, the chosen tab and composer text survive it |
| 6 | Step cell keys are 1-based (`process.substeps[1].roles` is step 1) |
| 7 | A none row shows "None" and counts as answered |
| 8 | Confirming an empty roles or systems list needs a second confirmation |
| 9 | The very first create carries the stored first name |
| 10 | The welcome sessions modal cannot be dismissed and waits until the intro is closed; one Escape closes only the top dialog |
| 11 | Boot runs once per URL under StrictMode |
| 12 | The picker stays open and locked while saving and closes only on success |
| 13 | The intro flag fails closed when storage is blocked |
| 14 | An unknown blocked-reason code is shown as is, never hidden |
| 15 | Auto collapse on `steps`, reopen gaps on `review`; a clicked section is pinned; the step tab follows the walk until clicked |
| 16 | Accessibility: `role=log` chat, progressbar with values, status never by colour alone, focus returns after every dialog, real `<table>` with `<th scope>` on Home |
| 17 | **No further steps** is enabled only with at least one step and an open walk, and calls `confirm` with `substeps` |

**Deliberately not in these screens:** generating or viewing an AI prompt, pasting AI output back to fill gaps, an analysis dialog (the discovery report is its own page, part 2), grouped cluster catalogues with long official definitions, client-side scoring of fields, sign-in or an admin link, a documents panel (part 2).

## 6. Acceptance criteria

| ID | Given / when / then |
|---|---|
| AC-23.1 | Given empty storage, when `getVisitorKey()` is called twice, then it returns the same 22-character URL-safe string, stored under `discovery_visitor_key` |
| AC-23.2 | Given `localStorage` throws, when the key is read, then a memory key is used and Home shows the storage notice |
| AC-23.3 | Given the URL `/#k=<valid key>`, when the app starts, then the key is stored, the fragment is removed, and Home shows the resume notice; an invalid value is removed and "This resume link is not valid." is shown |
| AC-23.4 | Every expert call sends `X-Visitor-Key`; `GET /api/taxonomy` does not |
| AC-23.5 | `services/api.ts` uses the method, path and body of §4 for every call, parses `{code, message, reason}` into `ApiError`, gives `network` on a failed fetch and `http_<status>` on a non-JSON body |
| AC-23.6 | Routes: `/`, `/process-discovery`, `/process-discovery/:id`, `/report/:id` render their pages; an unknown path redirects to `/`; every page shows the header "AI Use Case Discovery Agent" and no logo |
| AC-23.7 | Home lists sessions with name (or "Not named yet"), status text by status and `reportStatus`, completeness and relative time, in server order |
| AC-23.8 | Home shows **Continue** for active, **Open report** for finished, and **Delete** for every session; Delete asks first, then calls `DELETE` and refreshes the list |
| AC-23.9 | When a list fails to load, Home shows an error with Retry, not an empty list |
| AC-23.10 | **Start a new interview** sends `displayName` from the stored first name (omitted when empty) and navigates to the new session |
| AC-23.11 | Ideas show name and words; **Map this** calls `POST /ideas/{id}/start` and opens the new session; **Delete** removes the idea |
| AC-23.12 | **Show resume link** reveals `<origin>/#k=<key>` with **Copy** and the warning sentence; Copy writes the link to the clipboard |
| AC-23.13 | **Delete all my data** asks with an alert dialog, calls `DELETE /api/me`, refreshes both lists and shows the counts |
| AC-23.14 | Given `/process-discovery/:id`, when the page boots (StrictMode), then `GET /sessions/{id}` is called once and the session is shown |
| AC-23.15 | Given `/process-discovery` and an active session in the list, then the welcome sessions modal opens and no session is created; with no active session, or a failed list, a session is created and the URL is replaced with its id |
| AC-23.16 | Given a 404 on boot, then "Could not open this session" and **Start a new session** are shown |
| AC-23.17 | The phase meter marks the current phase with `aria-current="step"`, shows "step 2 of 4" on `steps` with P16 = 4 and "step 2 of ~3" with P16 unset, and shows `filledPoints/totalPoints points · pct %` |
| AC-23.18 | The progress bar exposes `aria-valuenow` = the server percentage and is green at ≥ 80 %, amber at ≥ 40 %, primary below |
| AC-23.19 | The chat list has `role="log"` and `aria-live="polite"`; while a turn is in flight it shows "Thinking…" with `role="status"` |
| AC-23.20 | Enter sends, Shift+Enter adds a new line, blank text cannot be sent, Send is disabled above 16,000 characters, and focus returns to the input after a send |
| AC-23.21 | Sending shows the expert's message at once; on success the list equals the server's messages (no duplicate) |
| AC-23.22 | Given a failed send (`unsafe_input`), then the optimistic message is removed, the text is back in the composer, and the server's sentence is in the banner |
| AC-23.23 | Given 400 `session_closed` on any write, then the composer is disabled, every spinner stops, the status line reads "This session is closed." and no banner shows |
| AC-23.24 | Agent text renders Markdown (lists, bold); a `<script>` or `<img onerror>` in the text is not rendered as HTML |
| AC-23.25 | After a turn with `ideasAdded = 2`, the status line reads "Kept 2 ideas on My processes." |
| AC-23.26 | The honest exit needs two presses; **Keep going** cancels; **Yes, end it** calls `close`; afterwards the status line reads the no-process sentence, the composer is disabled and no "report ready" text appears |
| AC-23.27 | The honest exit is hidden for `finished`, `no_candidate` and locked sessions |
| AC-23.28 | `ProcessCard` shows five sections from the field views' phases, each with a `complete/total` count, `aria-expanded` and `aria-controls` |
| AC-23.29 | Each field status shows its icon and its text (table §3.8.3); `partial` and `invalid` show the server's `reason`; no status is shown by colour alone |
| AC-23.30 | Values are formatted per §3.8.8; a none row shows "None"; an owner with `none_identified` shows "None" |
| AC-23.31 | A `proposed` field shows "Proposed", its source ("from <document>" or "from your idea"), the quote, and the confirm-in-chat hint; it is not counted in the section count |
| AC-23.32 | On phase `steps`, unpinned upper sections collapse and Steps opens; on `review`, unpinned sections with gaps open; a clicked section stays as the expert left it through later phase changes |
| AC-23.33 | `SubstepTabs` shows `Step k (f/12)` from the 1-based field views, marks S12 "(not scored)", supports arrow keys between tabs, and the active tab is the first unsettled step until the expert clicks a tab |
| AC-23.34 | `DerivedReviewPanel` lists roles and systems with "✓ Confirmed" or "Not confirmed yet"; **Confirm roles** calls `confirm(id, "roles")`, **Confirm systems** calls `confirm(id, "tools")` |
| AC-23.35 | Confirming an empty list opens an `alertdialog`; **Cancel** makes no call; **Yes, confirm** makes the call |
| AC-23.36 | The cluster link opens `ClusterPicker`, which lists the taxonomy clusters with name, code and description and marks the current one with `aria-pressed="true"` |
| AC-23.37 | While `PUT /cluster` is in flight the picker stays open, its buttons are disabled and Escape is ignored; success closes it and shows the new cluster; 422 `unknown_cluster` shows the message inside the picker |
| AC-23.38 | *Finish* is enabled only when `finish.ready` is true and the session is active; `looksLikeTask` shows the note but does not disable it |
| AC-23.39 | When *Finish* is disabled, the reason sentence for `blockedBy` is shown and linked with `aria-describedby`; an unknown code is shown as is |
| AC-23.40 | *Finish* success navigates to `/report/:id`; 409 `map_incomplete` updates the reason and shows no banner |
| AC-23.41 | 409 `conflict` on any write reloads the session and shows the reload banner |
| AC-23.42 | Each error code of §3.11 maps to its effect and text (`discoveryErrors.test.ts`, one case per row) |
| AC-23.43 | The reducer: a server response replaces `session` and keeps open dialogs, sections, tab and composer text; a result for another `sessionId` is ignored |
| AC-23.44 | The intro opens on the first visit, not on the second; **How this works** reopens it; with storage throwing it does not open by itself |
| AC-23.45 | The welcome sessions modal has no close button and ignores Escape; it is not shown while the intro is open and appears after the intro closes; the browse modal closes with Escape |
| AC-23.46 | Every dialog moves focus inside on open, keeps Tab inside, and returns focus to its trigger on close; with two dialogs, one Escape closes only the top one |
| AC-23.47 | With `VITE_API_MODE=fake`, the fake plays the scripted interview from welcome to a ready *Finish* through the real page, and `/error <code>` makes the next call fail with that code |
| AC-23.48 | A production build with `VITE_API_MODE=fake` fails; a normal build contains no fake module |
| AC-23.49 | Below 1024 px the panel is under the chat and header actions are icon buttons with `aria-label`s |
| AC-23.50 | **No further steps** is enabled only when at least one step row exists, `substeps_complete` is false, the session is active and no confirm is in flight; it is disabled with no rows, with `substeps_complete` true, or on a closed session |
| AC-23.51 | Pressing **No further steps** calls `confirm(id, "substeps")`; the returned session replaces the panel (Steps count, tabs, phase meter) and the button becomes disabled when `substeps_complete` is true |
| AC-23.52 | The header shows a theme toggle on every page; in light mode it shows a moon with label "Switch to dark theme", in dark mode a sun with "Switch to light theme"; `aria-pressed` is true in dark mode |
| AC-23.53 | Pressing the toggle adds or removes the `dark` class on `<html>` and stores `pd_theme` = `"dark"` / `"light"` |
| AC-23.54 | With `pd_theme` stored, the app starts in that theme; with nothing stored, it follows `prefers-color-scheme` and switches when the system setting changes; a stored choice is not overridden by a system change |
| AC-23.55 | If `localStorage` throws, the app still starts and follows the system setting |
| AC-23.56 | The inline script in `index.html` applies the stored or system theme before the app renders (tested by running the script against a fake `localStorage` and `matchMedia`) |
| AC-23.57 | No component uses a raw colour class (e.g. `bg-white`, `text-gray-900`, `bg-blue-600`); colours come from the tokens (checked by a source scan test) |
| AC-23.58 | Token pairs (text on background, text on surface, primary contrast on primary, both bubbles) meet 4.5:1 contrast in both themes (checked from the token values) |

## 7. Test plan

| Test file | Covers |
|---|---|
| `src/access/visitorKey.test.ts` | AC-23.1–23.3 |
| `src/services/api.test.ts` | AC-23.4, 23.5 (stubbed `fetch`) |
| `src/services/fakeApi.test.ts` | AC-23.47 (script reaches ready *Finish*, error triggers) |
| `src/App.test.tsx` | AC-23.6 |
| `src/pages/Home.test.tsx` | AC-23.7–23.13 |
| `src/pages/ProcessDiscovery.test.tsx` | AC-23.14–23.16, 23.21–23.23, 23.25–23.27, 23.32, 23.40, 23.41, 23.44, 23.45, 23.49 (fake API injected through `ApiProvider`) |
| `src/hooks/useDiscoveryState.test.ts` | AC-23.43 and every action of §3.10 |
| `src/utils/discoveryErrors.test.ts` | AC-23.42 |
| `src/utils/discoveryFormat.test.ts` | AC-23.30 and phase labels, relative time |
| `src/utils/processFieldScore.test.ts`, `substepProgress.test.ts` | Section counts, active step (AC-23.28, 23.33) |
| `src/components/process-discovery/DiscoveryPhaseMeter.test.tsx` | AC-23.17, 23.18 |
| `src/components/chat/chat.test.tsx` | AC-23.19, 23.20, 23.24 |
| `src/components/process-discovery/ProcessCard.test.tsx` | AC-23.28–23.31 |
| `src/components/process-discovery/SubstepTabs.test.tsx` | AC-23.33, 23.50, 23.51 |
| `src/components/process-discovery/DerivedReviewPanel.test.tsx` | AC-23.34, 23.35 |
| `src/components/process-discovery/ClusterPicker.test.tsx` | AC-23.36, 23.37 |
| `src/components/process-discovery/ProcessProfilePanel.test.tsx` | AC-23.38, 23.39 |
| `src/components/ui/Modal.test.tsx` | AC-23.46 |
| `frontend/vite.config.test.ts` (or a `make` check) | AC-23.48 |

Tests use Testing Library role and label queries, `user-event` for typing and keys, and fixtures in `src/test/fixtures/` (one `SessionOut` per phase: new, measure, steps, confirm, ready, finished, no_candidate). Optionally they also load the backend's samples from `backend/tests/fixtures/api/` (Q1). `make lint test` covers ESLint (zero warnings), `tsc --noEmit` and Vitest.

## 8. Out of scope

| Item | Where |
|---|---|
| Document upload, document panel, ✓ / ✎ on proposals | Part 2 (spec 17 routes) |
| Report screen and PDF download | Part 2 (spec 20) |
| Workspace: access-code gate, review, overview, briefs | Part 2 (specs 16, 21) |
| "In an implementation brief" status on Home | Part 2, once spec 21 adds it to the summary |
| End-to-end browser tests (Playwright) | Later, if time allows |
| Translations of the interface | Not planned; the interview follows the expert's language on the server |

## 9. Open questions

All decided at the lead review; kept here for the record.

| # | Question | Decision |
|---|---|---|
| Q1 | Should the backend API tests write real response samples for the frontend tests? | Yes, optional (nice-to-have): the backend API tests may write JSON samples to `backend/tests/fixtures/api/`, which the frontend tests can load. Hand-made fixtures remain the baseline |
| Q2 | Opening a resume link while another key is stored: replace silently, or ask first? | Replace, and show the notice; the old key is not kept |
| Q3 | Should Home show the specialist's validation note? `SessionSummary` has no note today | No; part 2 shows it on the report page |
| Q4 | Should *Finish* ask for a second confirmation, since the session then closes? | No: one press, with the sentence "After this, the session is closed." under the button |
| Q5 | Is there a screen for `confirm` with `target: "substeps"`? | Yes: the **No further steps** button in the Steps section (§3.8.9, AC-23.50–23.51) |
| Q6 | Fixed title or the product name from `GET /api/config`? | Fixed title "AI Use Case Discovery Agent" |

---

# Part 2: documents in the interview, and the discovery report

> **Status:** draft · **Implements:** the screens of F-04 (start from your documents), F-05.6 (proposed values, ✓ / ✎), F-16 (discovery report on screen, PDF download), F-26 (step-by-step AI assessment and recommended route, as shown in the report) (product). Hours only: no euro figure anywhere (*parked, R5*) · **Depends on:** part 1 of this spec (shell, reducer, errors, fake/real API, theme), spec 13 §3.6 (confirm and reject proposals), spec 15 (routes), spec 17 §3.2, §3.12, §3.13 (limits, sentences, removal), spec 18 (map model), spec 20 v3 §3.3, §3.5 (report model, routes), spec 26 (ratings, route, catalogue note)
> **Code:** `frontend/src/components/process-discovery/{DocumentPanel,FileDrop,DocumentHint,ProposalActions}.tsx`, `frontend/src/components/report/*`, `frontend/src/pages/DiscoveryReport.tsx`, `frontend/src/utils/{processMap,documentLimits,downloadFile}.ts`, `frontend/src/types/report.ts`, additions to `services/{api,fakeApi,fakeData}.ts`, `hooks/{discoveryReducer,useDiscoveryState}.ts`, `utils/discoveryErrors.ts` · **Tests:** next to each file
> **Part 3** (§18–§25 of this file): the workspace (access-code login, session list, read-only popup, conversation, PDF, delete; spec 21).

## 10. Purpose (part 2)

Two things the expert still cannot do in the browser:

1. **Start from a document.** Add a procedure, a process map or an example output to the interview, see what the AI read from it as **proposals with a quote**, and confirm (✓) or reject (✎) each one. Nothing from a document counts until the expert confirms it (product rule 4).
2. **Read the discovery report.** After *Finish*, a page shows the eleven parts of spec 20 v3 plus the cover, the process map drawn from the stored diagram, and a **Download PDF** button.

The client still decides nothing: proposals, counts, the sentences, every number and every report text come from the server. The client formats no report value.

## 11. Behaviour (part 2)

### 11.1 Where documents appear

| Place | What |
|---|---|
| **Chat input bar** (main entry, product owner decision 2026-11-20) | A round **"+" button on the LEFT of the message box** (`AttachButton`, lucide `Plus` icon, `aria-label="Add a document"`, tooltip "Add a document: a procedure, a process map or an example report"). It opens the same file picker; while an upload runs it shows a spinner and is disabled; disabled when the session is closed, while a turn is sending, or when the document limit is reached (tooltip says why). Files can also be dropped on the chat area. The upload result sentence (§11.4) appears in the chat as a system note under the last message |
| "Your process" panel | A **Documents** section (`DocumentPanel`) between Roles and systems and the *Finish* block (part 1 §3.8.1). Header "Documents n/max" (n = `session.documents.length`, max from config). Open by default; it follows the same toggle and pin rules as the other sections (part 1 §3.8.7), and never closes by itself |
| Chat, under the first agent message | A hint card (`DocumentHint`): "Have a procedure, a process map or an example report? **Add a document**. Nothing from it counts until you confirm it." Shown only while the session is active, not locked, `session.documents` is empty and the phase is `context` or `find`. Its button opens the same file picker as the "+" button |
| Field rows and step tabs | Proposed values with source, quote, ✓ and ✎ (§11.6, §11.7) |

The server's welcome message already mentions documents (F-04.1); the hint card is the clickable part of that mention.

### 11.2 Panel layout

```
| v Documents                                         1/5 |
| +-----------------------------------------------------+ |
| |  [Upload icon]  Add a document                      | |   FileDrop: a button that is also a drop zone
| |  or drop a file here                                | |
| +-----------------------------------------------------+ |
|   PDF, Word, Excel, CSV, text, Markdown or BPMN · up to 10 MB · up to 5 files |
|                                                         |
|   Uploading cost-review.docx     [=========-----] 62 %  |   while bytes are sent
|   Reading cost-review.docx…  (spinner)                  |   after the bytes are sent, until the reply
|                                                         |
|   (i) I read "cost-review.docx" and found 6 values and  |   result sentence, role=status, [x] to dismiss
|       5 steps for your process. Nothing counts until    |
|       you confirm it.                               [x] |
|   (!) This file is larger than 10 MB.               [x] |   inline error, role=alert
|                                                         |
|   cost-review.docx                                      |
|     Word · 6 proposals · 4 waiting for you   [Remove]   |
|   old-map.bpmn                                          |
|     BPMN · read in part · all confirmed      [Remove]   |
|   scan.pdf                                              |
|     PDF · could not be read                  [Remove]   |
```

### 11.3 Limits (`utils/documentLimits.ts`)

1. Limits come from `GET /api/config` → `documents {allowedTypes, maxFiles, maxFileMb}` (React Query key `['config']`, loaded once per app, `staleTime: Infinity`). No limit is typed in a component.
2. The helper line under the drop zone is built from the config: type words from a fixed map of extension → word (`pdf` PDF, `docx` Word, `xlsx` Excel, `csv` CSV, `txt` text, `md` Markdown, `bpmn`/`xml` BPMN; an unknown extension is shown as itself, upper case), then "up to <maxFileMb> MB", "up to <maxFiles> files".
3. The file input's `accept` = the allowed extensions with a dot (`.pdf,.docx,…`).
4. **Client pre-checks**, in this order, before any call (same order as the server, spec 17 §3.2): count (`documents.length >= maxFiles`), size (`file.size > maxFileMb × 1,048,576`; `file.size === 0` counts as unreadable), extension. A failed pre-check shows the spec 17 §3.12 sentence (§11.5) and makes no call.
5. If the config is loading or failed, the control still works: no `accept`, no pre-check, no helper line; the server checks everything. The panel never blocks on the config.
6. When `documents.length >= maxFiles` the button stays enabled (so the expert learns why) but pressing it shows the limit sentence instead of opening the picker.

### 11.4 Upload

| # | Rule |
|---|---|
| 1 | **Open:** the button (Enter or Space) opens a hidden `<input type="file">` (one file). Dropping a file on the zone does the same as choosing it; dropping several takes the first and says "One file at a time: I took <name>." The zone shows a dashed primary border while a file is dragged over it |
| 2 | **Available** only when `status === "active"` and not locked. On `finished` and `no_candidate` the drop zone and Remove buttons are hidden; the list stays visible (read-only) |
| 3 | **One write at a time.** While an upload, a removal or a ✓ / ✎ call is in flight, the composer, the other document actions, every ✓ / ✎, the confirm buttons and *Finish* are disabled; while a turn or a confirm is in flight, the upload button and ✓ / ✎ are disabled. This avoids a 409 `conflict` between two writes on one session |
| 4 | **Progress:** `uploadDocument(id, file, onProgress)` reports bytes sent. The panel shows "Uploading <name>" with a `ui/ProgressBar` (`aria-label="Upload progress"`, `aria-valuenow` = whole percent). When all bytes are sent, it switches to "Reading <name>…" with a spinner and `role="status"`; after 20 s: "Still reading. A long document can take up to a minute." The file name is shown as text, cut to 60 characters with "…" |
| 5 | **Success** (201 `DocumentUploadOut`): `session` replaces the server slice (part 1 rule: never the UI slice); `report.message` becomes the panel's result sentence (`role="status"`, dismissible, replaced by the next upload); the new document appears in the list. The section is not collapsed, the chosen step tab is kept |
| 6 | **Read failed** (`report.outcome === "failed"`): same as success; the sentence is the server's; the list row reads "could not be read" |
| 7 | **Refused** (an error, nothing stored): the sentence of §11.5 appears inside the panel as an inline `ui/Alert` (`role="alert"`, dismissible). No top banner for document codes |
| 8 | **Cancel:** none in the prototype (the model call cannot be stopped). Leaving the page while uploading is allowed; the result is ignored (part 1 rule: a result for another `sessionId` is ignored) |

> **Amendment (2026-11-20; spec 14 §3.16, spec 17 §3.18–§3.19; built 2026-11-20: (a) the chat system note is gone, the reply is a normal agent message from `session.messages`; (b) the pre-check uses `maxImageMb` for png/jpg; (c) matched by document name, see spec 14 §3.16 deviation 5; (d) the client's own `document_type` sentence is built from `allowedTypes`):** (a) the 201 response gains `reply: MessageOut`, which is also the last entry of `session.messages`: the chat shows it as a normal agent message (the agent's question about the file), and the result sentence of rule 5 stays in the panel only, with no system note in the chat; (b) images (`png`, `jpg`, `jpeg`) arrive through `allowedTypes` when configured, and `GET /api/config` adds `maxImageMb` for the pre-check; (c) a proposed value from an image shows "(from an image)" next to *from <document>* (the document's `kind` is `png` or `jpeg`); (d) the `document_type` sentence comes from the server's `message`.

### 11.5 Document errors (additions to `utils/discoveryErrors.ts`)

One new `where` value, `documents`: the message goes to the panel's inline alert, not the top banner. The server's `message` is the spec 17 §3.12 sentence; the client uses it when present, else the fixed sentence below (built with the config values, which is also what the pre-checks show).

| Code (HTTP) | From | UI effect | Text |
|---|---|---|---|
| `document_limit` (409) | upload, pre-check | Panel alert. Not the part 1 `conflict` reload | "You can add up to <max> documents. Remove one to add another." |
| `document_too_large` (413), also `http_413` (a proxy's non-JSON reply) | upload, pre-check | Panel alert | "This file is larger than <max> MB." |
| `document_type` (415) | upload, pre-check | Panel alert | "This file type can't be read. Use PDF, Word, Excel, CSV, text, Markdown or BPMN." |
| `document_unreadable` (422) | upload, pre-check (empty file) | Panel alert | "I couldn't find any text in this file. If it is a scan, try the file it was made from." |
| `unsafe_input` (400) | upload | Panel alert (not the composer restore of part 1) | "This document contains text that looks like instructions to the assistant, so I didn't read it." |
| `invalid_value` (422) | upload (no file part) | Panel alert | "That file could not be sent. Please try again." |
| `rate_limited`, `budget_exhausted` (429), `model_unavailable` (503), `network` (0), anything else | upload | Panel alert, with the part 1 sentence for that code | Part 1 §3.11 |
| `session_closed` (400) | any document or proposal call | Part 1: lock, clear spinners, no banner | "This session is closed." |
| `conflict` (409) | any document or proposal call | Part 1: reload and banner | Part 1 §3.11 |
| `not_found` (404) | remove | Reload the session (`GET`), banner | "That document was already removed." |
| any code | remove, ✓ / ✎ | Part 1 banner rules | Part 1 §3.11 |

`discoveryErrors.describe(error, {call})` gains the `call` argument (`"upload" | "removeDocument" | "proposals" | …`) so `unsafe_input` and 409 codes map by call.

### 11.6 Document list and removal

1. One row per `session.documents` entry, in server order (upload order). Row: the name (one line, cut with "…", full name in `title`), then a muted line: kind word (§11.3.2 map on `kind`; unknown kinds as is), "read in part" when `truncated`, and the counts:

| Case | Count text |
|---|---|
| `outcome === "failed"` | "could not be read" |
| `proposals === 0` | "nothing new for the form" |
| `pending > 0` | "<proposals> proposals · <pending> waiting for you" (singular "1 proposal") |
| `pending === 0` | "<proposals> proposals · all settled" |

2. The list is a `<ul aria-label="Your documents">`. No file text, size in bytes or character count is shown (counts only, product rule 7).
3. **Remove** (secondary button, `aria-label="Remove <name>"`) opens an `alertdialog`: heading "Remove this document?", body "Values you already confirmed from it stay. Its <pending> unconfirmed proposals are removed." (the second sentence only when `pending > 0`), buttons **Cancel** (focused first) and **Remove**. Remove calls `DELETE /api/sessions/{id}/documents/{docId}` → `SessionOut` replaces the slice. The row shows "Removing…" while in flight.
4. After removal, values confirmed from it show the source chip "from a removed document" (field view `documentName` is `null` with `source: "document"`), never "from a document".
5. Empty list: "No documents yet." under the drop zone.

### 11.7 Proposed values in field rows (`FieldRow`, `ProposalChip`, `ProposalActions`)

```
| [FileText] Trigger      Month-end close completed                              |
|            Proposed · from cost-review.docx    [Show quote ▾]    [✓] [✎]      |
|            > "The review starts once month-end close is completed."            |   shown after Show quote
```

| # | Rule |
|---|---|
| 1 | A view with `status === "proposed"` shows the value, then the line "Proposed · from <documentName>" (source `document`), "Proposed · from a removed document" (`documentName` null), or "Proposed · from your idea" (source `expert`). It replaces part 1's read-only chip and hint |
| 2 | **Quote:** a disclosure button "Show quote" / "Hide quote" (`aria-expanded`, `aria-controls`) reveals the `quote` in a `<blockquote>`. Collapsed by default; open state is UI state per key and survives server responses. Quotes are plain text, never Markdown or HTML |
| 3 | **✓** icon button (`Check`), `aria-label="Confirm <label>"`, `title="Confirm: this is right"` → `POST /proposals/confirm {keys: [key]}` |
| 4 | **✎** icon button (`Pencil`), `aria-label="Reject <label>"`, `title="Not right: the agent will ask you"` → `POST /proposals/reject {keys: [key]}` |
| 5 | After ✓: the returned session replaces the slice; the row now shows the field's new status (normally `complete`, with the source chip "from <document>"). Section counts and the phase meter follow the server |
| 6 | After ✎: the value is cleared by the server; the panel status line (the one above the composer, part 1 §3.7) reads "Removed. The agent will ask you about <label>." until the next turn. The client sends no message and starts no turn |
| 7 | ✓ and ✎ show only while the session is active and not locked; disabled per §11.4.3. The pressed button shows a spinner; the keys in flight are kept in `pending.proposals` |
| 8 | ✓ / ✎ appear on process fields (ProcessCard) and step cells (SubstepTabs). Roles and systems are roll-ups and are never proposals |
| 9 | Proposals are never counted by the client (part 1 rule: counts come from `complete` views only) |

**Amended 2026-11-20 (open conflicts on the panel; spec 17 §3.21, §3.22 row 7).** A field view with `conflict === "open"` (a process field in `ProcessCard` or a step cell in `SubstepTabs`, both through `FieldRow`) shows a small warning chip **"Conflict – answer in the chat"** (text, not colour alone; theme tokens only). There are no buttons: the expert settles a conflict by answering the agent's question in the chat (spec 14 §3.17). `conflict: "left"` and `null` show nothing (a left conflict is listed in the report's gaps, spec 20). The chip sits with the row's other chips and never replaces the value, the status or ✓ / ✎.

### 11.8 Batch confirm

| Where | Shown when | Button | Call |
|---|---|---|---|
| Step tab panel (`SubstepTabs`), under "Step k · <name>" | Step k has at least 2 cell views with status `proposed` | "Confirm all <n> proposals in step k" | `confirmProposals(id, keys)` with those keys, in field view order |
| Steps section header area | At least 2 rows have a proposed S01 (step name) | "Confirm the <n> proposed step names" | The S01 keys of those rows, in step order |
| Documents row | — | none: confirming a whole document at once is too coarse | — |

The tab label shows a small "proposed" text after the count when the step has a proposal (`Step 2 (5/11) · proposed`), so the expert can find them; text, not colour. Batch buttons are secondary buttons, disabled per §11.4.3. There is no batch reject (✎ is a per-value decision).

### 11.9 State additions (`hooks/discoveryReducer.ts`)

| State key | Slice | Meaning |
|---|---|---|
| `session.documents` | server | `DocumentOut[]` from `SessionOut` (new field; `[]` when absent) |
| `pending.uploading` | UI | `{name, percent: number \| null, stage: "sending" \| "reading"} \| null` |
| `pending.removingDocument` | UI | Document id or `null` |
| `pending.proposals` | UI | `{keys: string[], kind: "confirm" \| "reject"} \| null` |
| `documentNotice` | UI | The last `report.message`, or `null` |
| `documentError` | UI | The panel's inline error sentence, or `null` |
| `proposalNotice` | UI | "Removed. The agent will ask you about <label>." or `null`; cleared by `MESSAGE_SENDING` |
| `openQuotes` | UI (page) | Set of keys whose quote is shown (page state, like the section map) |

| Action | Effect |
|---|---|
| `UPLOAD_STARTED(forId, name)` | `pending.uploading = {name, percent: 0, stage: "sending"}`; clears `documentNotice`, `documentError` |
| `UPLOAD_PROGRESS(forId, percent)` | Updates `percent`; at 100 sets `stage: "reading"`, `percent: null` |
| `DOCUMENT_UPLOADED(forId, upload)` | Replaces `session` with `upload.session`; `documentNotice = upload.report.message`; clears `pending.uploading` |
| `DOCUMENT_REJECTED(forId, message)` | `documentError = message`; clears `pending.uploading` (also used by the pre-checks, with no call) |
| `DOCUMENT_REMOVING(forId, docId)` | `pending.removingDocument = docId` |
| `PROPOSALS_STARTED(forId, keys, kind)` | `pending.proposals = {keys, kind}` |
| `SESSION_RECEIVED(…, kind)` | Part 1 action; new kinds `removingDocument` and `proposals` clear their flag. After a reject it sets `proposalNotice` |
| `ACTION_FAILED(forId, kind, message, where)` | Part 1 action; `where: "documents"` writes `documentError` |
| `DOCUMENT_NOTICE_CLEARED` / `DOCUMENT_ERROR_CLEARED` | Dismiss buttons |

Every new action carries `forId`; a result for another session is ignored (part 1 §3.10). `PendingKind` gains `uploading`, `removingDocument`, `proposals`; a helper `isWriting(pending)` is true when any write is in flight (§11.4.3).

**Hook additions:** `useDiscoveryState` also returns `uploadDocument(file)`, `removeDocument(docId)`, `confirmProposals(keys)`, `rejectProposals(keys)`, `clearDocumentNotice()`, `clearDocumentError()`. The pre-checks run inside `uploadDocument` (they need the config, passed in from `useQuery(['config'])`).

### 11.10 The report page (`pages/DiscoveryReport.tsx`, route `/report/:sessionId`)

**How the expert gets there:** *Finish* navigates to it (part 1 §3.8.12, unchanged; the built finish route returns `SessionOut`); Home's **Open report** (part 1 §3.3.4); the interview page's **Open my report** and the status line link; a finished card in the sessions modal.

```
+--------------------------------------------------------------------------------------+
| [Q] AI Use Case Discovery Agent          [Download PDF] [Back to My processes] [moon]      |  AppHeader
+--------------------------------------------------------------------------------------+
| Contents          | DISCOVERY REPORT · <product name> · <company name>                |  cover
|  At a glance      | Monthly cost review                                   [Mapped]   |
|  The process      | Department Finance control · Cluster FIN Finance · Region EU     |
|  Volume and ...   | Process owner Head of Controlling · 20 November 2026             |
|  Process map ...  |---------------------------------------------------------------- |
|  Step-by-step ... | 1. At a glance                                                   |
|  Recommended ...  |   About 342 hours a year.                                        |
|  Transformation.. |   Recommended route: Start with step 2 "Consolidate into the     |
|  Hours a year     |   master file" (about 96 h a year) using …                       |
|  Readiness ...    |   Top opportunities                                              |
|  Suggested path   |     Read the site spreadsheets … · steps 1–2 · 168 h             |
|  Gaps and sources |   To prepare: Agree one site template                            |
|  (sticky ≥1024px) | 4. Process map and steps                                         |
|                   |   +----------------------------------------------------------+   |
|                   |   | [Mermaid map: one band per role, steps, gateways, data]  |   |
|                   |   +----------------------------------------------------------+   |
|                   |   [Map as text ▾]   Systems: spreadsheet, e-mail, ERP            |
|                   |   | Field        | Step 1 Collect… | Step 2 Consolidate… | → |   |  scrolls sideways
|                   | 5. Step-by-step AI assessment                                    |
|                   |   (i) Routes come from an assumed tool set …                     |
|                   |   | Step | Hours a year | AI fit | Route | Reason | Evidence |    |
|                   | 7. Transformation assessment                                     |
|                   |   (!) The opportunities could not be generated this time. …      |
+--------------------------------------------------------------------------------------+
```

| # | Rule |
|---|---|
| 1 | **Data:** React Query `['report', sessionId]` → `GET /api/sessions/{id}/report` (no model call on the server, spec 20 §3.5). One call per page open; no polling. Not part of the interview reducer |
| 2 | **Loading:** "Loading your report…" with a spinner, `role="status"`. After 10 s: "Still building your report. This can take up to a minute." |
| 3 | **404:** "This report is not available. A report is ready once the interview is finished." with **Continue the interview** (`/process-discovery/:id`) and **Back to My processes**. The page cannot tell "not finished" from "not yours"; both read the same |
| 4 | **Other errors:** the part 1 §3.11 sentence and **Retry** (refetch). Never an empty report |
| 5 | **Layout:** a single column, max 960 px, with a **Contents** `<nav aria-label="Report contents">` listing the eleven part titles as anchor links (`#part-<key>`). At ≥ 1024 px the contents are a sticky left column; below, a collapsed `<details>` "Contents" above the cover |
| 6 | **Order:** cover, then parts 1–11 exactly as spec 20 §3.3: At a glance, The process, Volume and measures, Process map and steps, Step-by-step AI assessment, Recommended route, Transformation assessment, Hours a year, Readiness checklist, Suggested path, Gaps and sources. Each part is a `<section aria-labelledby>` with an `<h2>` "<number>. <title>" taken from the model (`number`, `title`); the client hard-codes the order of keys, not the titles |
| 7 | **No formatting:** every number, label and sentence is rendered as the server sends it (spec 20 §5: "the client formats nothing"). Text is plain text: no Markdown, no HTML |
| 8 | **Hours only:** the page shows no euro figure, cost, value or saving (R5). The client has no field for them |
| 9 | Header actions: **Download PDF** (§11.13), **Back to My processes**, the theme toggle. Below 640 px they become icon buttons with `aria-label`s (part 1 rule) |

### 11.11 The parts on screen (`components/report/`)

| Part (key) | Component | Shown as |
|---|---|---|
| Cover (`cover`) | `ReportCover` | Eyebrow "Discovery report · <product name> · <company name>", the process name as the main title (an `<h2>`, because the `AppHeader` holds the page's `<h1>`), a `<dl>` with Department, Cluster ("<code> <name>"), Region, Process owner, Date; a `ui/Pill` with the status text ("Mapped" neutral, "Validated by IT" success; text always present) |
| 1 At a glance (`at_a_glance`) | `AtAGlance` | The hours sentence in large text; "Recommended route:" + the headline (left out when absent); "Top opportunities" as a list: title · steps label · hours; "To prepare" as a list. The note "Hours need: <fields>." when sent |
| 2 The process (`process`) | `ReportFields` | A `<dl>`: label → value; a quote (when the field has one) as a small muted line "the expert's words" or "from <document>"; the task or one-off note above the list |
| 3 Volume and measures (`measures`) | `ReportFields` | Same `<dl>`; "Not measured yet" comes from the server |
| 4 Process map and steps (`map`) | `ProcessMap` + `StepTable` | §11.12 map; "Systems used: a, b, c"; the step table: `<table>` with `<caption>` "Steps of the process, one column per step", `<th scope="col">` "Step k · <name>" per step, `<th scope="row">` per leaf label (S01–S13), cells as sent (including "— (skipped)" and "(proposed, not confirmed)"). The table sits in a `role="region"` with `aria-label="Step table"` and `tabindex="0"`, scrolling sideways; the first column is sticky |
| 5 Step-by-step AI assessment (`steps`) | `StepAssessmentTable` | `<table>` with `<caption>` and `<th scope="col">`: Step, Hours a year, AI fit, Route, Why this route, Reason, Evidence. AI fit = an icon (`Bot` automate, `Handshake` assist, `User` human, `HelpCircle` not assessed) plus the server's `fitLabel` text; route = `routeName` ("No route" as sent); evidence in quotes with its label ("the expert's words" / "from <document>"). The catalogue note above the table (§11.11.2) |
| 6 Recommended route (`route`) | `RecommendedRoute` | The headline as a lead sentence; each group sent (Start with, Later, Fix first, Stays with people, No route yet) as an `<h3>` + list "Step k · <name> · <hours> · <route name>" (or the reason for Fix first); "What to have in place" list. Groups are shown in the order and number sent; empty groups are not sent (spec 20) and not invented |
| 7 Transformation assessment (`assessment`) | `OpportunityList` | The summary paragraph; one `<article>` per opportunity: `<h3>` title, a line "<steps label> · <type label> · Impact <word> · Feasibility <word>", then a `<dl>`: What changes, How, Prepare first, Why this impact, Why this feasibility, Evidence (quote + label), and the review status when sent ("Accepted by IT"); then "Steps that stay with people": steps label, reason, evidence |
| 8 Hours a year (`potential`) | `HoursTables` | Table 1 (per step): Step, Hours per run, Runs a year, Hours a year; the total in `<tfoot>` ("—" when incomplete, as sent). Table 2 (per opportunity): Opportunity, Steps, Hours of these steps. Then "How it is calculated" (formula lines in a list), "Assumptions" (list), problem sentences, and the line about euro value not shown yet |
| 9 Readiness checklist (`readiness`) | `ReadinessTable` | Table: Dimension, Question, Level (word, e.g. "Low", plus a level icon; never colour alone), Why, To prepare, Specialist note; footer line "A guide to what would make the change easier. Not a verdict." |
| 10 Suggested path (`path`) | `SuggestedPath` | Three `<h3>` groups in order (Prepare first, Quick wins, Bigger changes); prepare lines, then items "title · steps label · hours"; "Nothing here." as sent |
| 11 Gaps and sources (`gaps`) | `GapsAndSources` | "Still open" list: label, status word, reason; "Documents used": name and outcome words ("read", "could not be read"), never text; the closing note as the last paragraph |

1. **Part notes.** Each part model has `note: {kind, text} | null`. A note is shown under the part heading in a `ReportNote` box: kinds `failed` and `error` use the warning tone and `AlertTriangle`; the others (`missing`, `empty`, `simplified`, `incomplete`, `task`, `one_off`) use the info tone and `Info`. The text is the server's; the icon has a text label ("Warning" / "Note"). A part with a note still shows whatever content it has.
2. **Catalogue note.** Parts 5 and 6 show `catalogueNote` (when not null) as an info `ReportNote` above their content. The text is the server's: today the assumed tool set sentence (spec 26 decision), or the placeholder sentence while a catalogue is a placeholder. The client never writes its own wording.
3. **A part that is missing or breaks.** If a part key is absent or `null` in the JSON, the page shows that part's heading (title from a fixed fallback map of the eleven titles) and the warning note "This part could not be generated." If a part throws while rendering, a per-part error boundary (`ReportPartBoundary`) shows the same heading with "This part could not be shown." and logs the error class to the console (no text). The other parts render in every case (F-16.2).
4. **Cover failure** follows the same rule, with the fallback title "Discovery report".

### 11.12 The process map (`ProcessMap`, `utils/processMap.ts`)

The map is drawn with **Mermaid** (already a dependency) from the stored `ProcessDiagram` of spec 18 (`map.diagram`). The server sends the diagram, not Mermaid text; the client converts it.

`toMermaid(diagram): string` is pure and deterministic:

| Diagram part | Mermaid |
|---|---|
| Direction | `flowchart LR` |
| Lane (role) | `subgraph L<i>["<lane>"]` … `end`, one per lane in diagram order, holding its nodes; a node whose lane is unknown goes in a last "Other" subgraph |
| `start` node | Circle `n<i>(("<label>"))` |
| `end` node | Double circle `n<i>((("<label>")))` |
| `task` node | Rounded box `n<i>("Step <step_index> · <label>")` (no "Step" prefix when `step_index` is null) |
| `gateway` node | Diamond `n<i>{"<label>"}` |
| Flow | `n<a> -->|"<label>"| n<b>` (no label part when empty); `is_default` adds " (default)" to the label |
| Data object, input | Parallelogram `d<i>[/"<label>"/]`, joined `d<i> -.-> n<task>` |
| Data object, output | `n<task> -.-> d<i>` |
| Data store | Cylinder `s<i>[("<label>")]`, joined `n<task> -.- s<i>` for each step it serves |

Rules: node ids are replaced by generated ids (`n0`, `n1`, … in diagram order); raw ids never reach Mermaid. Every label is cleaned: line breaks to spaces, `"` → `#quot;`, `<` → `#lt;`, `>` → `#gt;`, cut to 80 characters with "…". Flows to unknown nodes are skipped. A diagram with no nodes gives `""`.

`ProcessMap` rules:

| # | Rule |
|---|---|
| 1 | Mermaid is loaded with a dynamic `import('mermaid')` on the report page only, so it is not in the interview page bundle |
| 2 | `mermaid.initialize({startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "default", flowchart: {htmlLabels: false}})`; `dark` from `useTheme()`. When the theme changes, the map is drawn again |
| 3 | The SVG returned by `mermaid.render(id, text)` is inserted into a container `role="img"` with `aria-label="Process map: <n> steps across <m> roles"`. Mermaid's strict mode sanitises the SVG |
| 4 | **Text alternative:** a `<details>` "Map as text" with an ordered list of the tasks in step order: "Step k · <label> (<lane>)", then the decisions "<gateway label>: <branch labels>" |
| 5 | Caption from the server (`map.caption`, e.g. the simplified map sentence) under the map |
| 6 | **Failure:** `diagram` null, `toMermaid` empty, or `render` throwing → the note "The process map could not be drawn." (warning tone); the systems line and the step table still show |
| 7 | Wide maps scroll sideways inside a `role="region"` (`aria-label="Process map"`, `tabindex="0"`); the SVG keeps its natural width up to the container and is never squeezed below 600 px |
| 8 | The renderer is a prop (`render?: (id, text, theme) => Promise<string>`, default = the lazy Mermaid call) so tests inject a stub |

### 11.13 Download PDF (`utils/downloadFile.ts`)

1. **Download PDF** (primary button in the header actions, and again at the end of the report). A plain link cannot send `X-Visitor-Key`, so the client fetches: `getReportPdf(id)` → `GET /api/sessions/{id}/report.pdf` → `{blob, filename}`.
2. `filename` from the `Content-Disposition` header (`filename="discovery-report-<slug>.pdf"`); fallback `discovery-report.pdf`.
3. `saveBlob(blob, filename)`: creates an object URL, clicks a temporary `<a download>`, removes it and revokes the URL.
4. While in flight the button reads "Preparing PDF…" with a spinner and is disabled. An error shows an inline alert next to the button with the part 1 sentence for the code (404: "This report is not available."). The rest of the page is not affected.

### 11.14 Print-friendly layout

1. A print stylesheet (`@media print`, Tailwind `print:` variants): hides the app header, the contents nav, every button, the "Map as text" toggle and notes' dismiss buttons; forces the light tokens (the `:root` values) whatever the screen theme; black text on white.
2. Each part starts with its heading kept with its first block (`break-after: avoid` on `h2`/`h3`); table rows do not split (`break-inside: avoid` on `tr`); `<thead>` repeats on each page.
3. Scroll regions (map, step table) print at full width with wrapping, not clipped.
4. When the app is dark, `beforeprint` draws the map again with the light Mermaid theme and `afterprint` restores it.
5. The PDF download stays the recommended way to share; printing is a convenience.

### 11.15 Fake API additions (`services/fakeApi.ts`, `services/fakeData.ts`)

| # | Behaviour |
|---|---|
| 1 | `getConfig()` returns `{productName: "AI Use Case Discovery Agent", regions, languages, documents: {allowedTypes: ["pdf","docx","xlsx","csv","txt","md","bpmn","xml"], maxFiles: 5, maxFileMb: 10}}` |
| 2 | `uploadDocument` checks count, size and type like the server, then calls `onProgress` at 25, 50, 75, 100 % about 150 ms apart, then waits 800 ms ("reading") |
| 3 | **Scripted outcomes by file name** (case-insensitive): a name with `procedure` → 2 process fields (trigger, end result) and, when the step table is empty, 5 proposed step names, each with a quote from a fixed procedure text; `.bpmn` → 5 proposed step names and 2 proposed roles from lanes; `empty` → nothing new; `long` → as `procedure` plus `truncated` and the "read only the first part" sentence; `failed` → `outcome: "failed"` with the model-failure sentence; `scan` → 422 `document_unreadable`; `inject` → 400 `unsafe_input`. Any other name behaves like `procedure`. Sentences are built from the spec 17 §3.12 templates |
| 4 | Proposals follow the fill-only rule: they never overwrite a value the expert gave; they set the field view to `proposed` with `source: "document"`, `documentName`, `quote` |
| 5 | `confirmProposals` / `rejectProposals` change those views to complete / empty and keep the counts of `documents[].pending` right; `removeDocument` drops the document's pending proposals and keeps confirmed values with `documentName: null` |
| 6 | `getReport(id)` returns the fake EU report (the spec 20 cost review: 342 h; step hours 72, 96, 72, 30, 72; assumed tool set note) for a finished fake session, 404 otherwise. `getReportPdf(id)` returns a small valid PDF blob and the file name `discovery-report-monthly-cost-review.pdf` |
| 7 | **Triggers:** `/error <code>` (part 1) also applies to the next document, proposal, report or PDF call; `/report-failed <part key>` makes the next report carry the failed note for that part (for `steps`, also `route`); `/report-missing <part key>` leaves that key out of the next report |
| 8 | Report fixtures in `src/test/fixtures/report.ts`: `euReport` (complete), `euReportStepsFailed`, `euReportSimplifiedMap`, `thinReport` (minimum fields, many "—"); the fake and the tests share them |

### 11.16 Report v2 (amended 2026-11-21 (report v2), spec 27)

Spec 27 replaces the eleven parts with six. The wire model (`DiscoveryReport` in `backend/app/models/process_discovery_wire.py`) is the contract and wins over this text. This amends §11.10 rules 5–6, §11.11 (parts 1 and 5–11), §11.15 (`/report-failed <part>` takes a v2 key) and §19.4 blocks 4–7. Superseded ACs: AC-23.84, AC-23.86, AC-23.93–23.96 (read as AC-23.153–23.156), AC-23.129 (read as AC-23.157), and in AC-23.101 "`steps` and `route`" (now `steps` only).

| Part (key) | Component | Shown as |
|---|---|---|
| 1 Summary (`summary`) | `SummarySentences` | Each server sentence as its own paragraph, in the order sent; nothing invented when the list is short or empty |
| 2–4 (`process`, `measures`, `map`) | unchanged | As §11.11 |
| 5 Step-by-step AI assessment (`steps`) | `StepLevelTable` | Columns: Step, Hours a year, AI fit, Because, Route (route name, the route reason as a small line), Why, The expert's words. AI fit = a signal icon (strong high, partial medium, weak low, otherwise `HelpCircle`) plus the server's `levelLabel`; *Because* is the server's list. Catalogue note above |
| 6 AI readiness and feasibility (`feasibility`) | `Feasibility` | Three blocks with headings one level below the part: **The three questions** (`QuestionsTable`: Question as row header, Level as icon + `levelLabel`, Why + the quote with "the expert's words"); **Readiness** (`ReadinessTable`: Dimension, Level, To prepare; then `readinessFooter`); **Before starting and risks** (the bullets as a list, then `gaps` in small print). The third heading is left out when both are empty |

Levels are always the server's words, never yes / no or go / no-go; the client formats nothing. Anchors are `#part-<key>`. The fallback titles are Summary, The process, Volume and measures, Process map and steps, Step-by-step AI assessment, AI readiness and feasibility.

**Workspace popup (§19.4 blocks 4–7, amended):** Summary (`SummarySentences`), Step-by-step AI assessment (`StepLevelTable`), **The three questions** (`QuestionsTable` from `report.feasibility`; readiness and bullets stay in the report and PDF) and Process map, each an `<h3>` block inside its own `ReportPartBoundary`. `StepAssessmentTable`, `RecommendedRoute`, `OpportunityList`, `AtAGlance`, `HoursTables`, `SuggestedPath` and `GapsAndSources` are removed.

**Samples:** `src/test/fixtures/api/report.json` and the report in `review-session.json` are recorded from the v2 server by `backend/scripts/export_api_samples.py`; the tests read level words and sentences from the sample, so a wording change on the server needs no test change.

## 12. Interfaces (part 2)

**API calls added** (camelCase; `X-Visitor-Key` on all but `/api/config`):

| `DiscoveryApi` method | Route | Request | Response |
|---|---|---|---|
| `getConfig()` | `GET /api/config` | — | `PublicConfig` (part 1 type, now used) |
| `uploadDocument(id, file, onProgress?)` | `POST /api/sessions/{id}/documents` | `multipart/form-data`, one part `file` | 201 `DocumentUploadOut`; 409 `document_limit`, 413 `document_too_large`, 415 `document_type`, 422 `document_unreadable`, 400 `unsafe_input` |
| `removeDocument(id, docId)` | `DELETE /api/sessions/{id}/documents/{docId}` | — | `SessionOut`; 404 `not_found` |
| `confirmProposals(id, keys)` | `POST /api/sessions/{id}/proposals/confirm` | `{keys: string[]}` (1–200 keys, each 1–80 characters) | `SessionOut` (non-proposal keys are ignored) |
| `rejectProposals(id, keys)` | `POST /api/sessions/{id}/proposals/reject` | `{keys: string[]}` | `SessionOut` |
| `getReport(id)` | `GET /api/sessions/{id}/report` | — | `DiscoveryReport`; 404 before *Finish* *(to confirm against the built route)* |
| `getReportPdf(id)` | `GET /api/sessions/{id}/report.pdf` | — | `{blob, filename}` from `application/pdf` + `Content-Disposition` *(to confirm against the built route)* |

`GET /api/sessions/{id}/documents` is not used: `SessionOut.documents` already holds the same list after every write.

**Upload transport:** `createHttpApi().uploadDocument` uses `XMLHttpRequest` (not `fetch`) because only XHR reports upload progress (`xhr.upload.onprogress` → `onProgress(Math.round(loaded / total × 100))`). It sets `X-Visitor-Key`, lets the browser set the multipart boundary, and turns the reply into the same `ApiError` as `request()` (JSON `{code, message}`, `http_<status>` for a non-JSON body, `network` on `onerror`).

**Types added to `types/process-discovery.ts`** (mirror of `backend/app/models/process_discovery_wire.py`):

```ts
interface DocumentOut { id: string; name: string; kind: string; bytes: number; chars: number; truncated: boolean;
  uploadedAt: string; outcome: 'read' | 'failed'; proposals: number; pending: number }
interface Tally { fields: number; steps: number; cells: number }
interface DocumentReportOut { documentId: string; outcome: 'read' | 'failed'; reader: 'model' | 'bpmn';
  truncated: boolean; offered: Tally; kept: Tally; dropped: number;
  skipped: { key: string; reason: string; items: number | null }[]; stepList: number; message: string }
interface DocumentUploadOut { session: SessionOut; document: DocumentOut; report: DocumentReportOut }
// SessionOut gains: documents: DocumentOut[]   (the wire guard defaults a missing list to [])
// Constants: DOCUMENT_KIND_WORDS, DOCUMENT_ERROR_SENTENCES (templates with <max>)
```

`bytes` and `chars` are typed but never shown.

**Types in `types/report.ts`** (from spec 20 §4, camelCase; **to confirm against the built route** — the report route and its wire models are being built now; field names below follow spec 20 and are adjusted to the built model before the report tests are written):

```ts
type NoteKind = 'missing' | 'failed' | 'empty' | 'simplified' | 'incomplete' | 'task' | 'one_off' | 'error'
interface ReportNote { kind: NoteKind; text: string }
interface PartBase { number: number; title: string; note: ReportNote | null }
interface ReportField { key: string; label: string; value: string; status: FieldStatus | null; source: string | null; quote: string | null }
interface ReportCover { productName: string; companyName: string; processName: string; department: string;
  clusterCode: string; clusterName: string; region: string; ownerRole: string; date: string; statusLabel: string; note: ReportNote | null }
interface AtAGlancePart extends PartBase { hours: string; routeHeadline: string | null;
  top: { title: string; stepsLabel: string; hours: string }[]; prepare: string[] }
interface FieldsPart extends PartBase { fields: ReportField[] }
interface StepColumn { number: number; name: string; cells: ReportField[] }
interface MapPart extends PartBase { diagram: ProcessDiagram | null; caption: string | null; systems: string[]; columns: StepColumn[] }
interface StepRow { number: number; name: string; hours: string; fit: 'automate' | 'assist' | 'human' | null; fitLabel: string;
  routeId: string | null; routeName: string; routeReason: string; reason: string; evidence: string; evidenceLabel: string }
interface StepsPart extends PartBase { rows: StepRow[]; catalogueNote: string | null }
interface RouteItem { number: number; name: string; hours: string; routeName: string; reason: string }
interface RoutePart extends PartBase { headline: string; groups: { key: string; title: string; items: RouteItem[] }[];
  prepare: string[]; catalogueNote: string | null }
interface ReportOpportunity { id: string; title: string; stepsLabel: string; typeLabel: string; whatChanges: string; how: string;
  prepareFirst: string; impactLabel: string; impactReason: string; feasibilityLabel: string; feasibilityReason: string;
  evidence: string; evidenceLabel: string; reviewLabel: string | null }
interface AssessmentPart extends PartBase { summary: string; opportunities: ReportOpportunity[];
  stayHuman: { stepsLabel: string; reason: string; evidence: string; evidenceLabel: string }[] }
interface PotentialPart extends PartBase { complete: boolean;
  steps: { number: number; name: string; hoursPerRun: string; runsPerYear: string; hoursPerYear: string }[];
  opportunities: { id: string; title: string; stepsLabel: string; stepHours: string }[];
  totals: { hours: string }; formulas: string[]; assumptions: string[]; problems: string[]; euroLine: string }
interface ReadinessPart extends PartBase { dimensions: { key: string; label: string; question: string; level: string;
  levelLabel: string; reason: string; toPrepare: string; note: string }[]; footer: string }
interface PathPart extends PartBase { groups: { key: string; title: string; prepareLines: string[];
  items: { opportunityId: string; title: string; stepsLabel: string; stepHours: string }[] }[] }
interface GapsPart extends PartBase { fields: ReportField[]; documents: { name: string; outcome: string }[]; closingNote: string }
interface DiscoveryReport { cover: ReportCover; atAGlance: AtAGlancePart; process: FieldsPart; measures: FieldsPart;
  map: MapPart; steps: StepsPart; route: RoutePart; assessment: AssessmentPart; potential: PotentialPart;
  readiness: ReadinessPart; path: PathPart; gaps: GapsPart; generatedAt: string }
interface ProcessDiagram { lanes: string[]; nodes: { id: string; type: string; label: string; lane: string; stepIndex: number | null; marker: string }[];
  flows: { source: string; target: string; label: string; isDefault: boolean }[];
  dataObjects: { id: string; stepIndex: number; direction: 'input' | 'output'; label: string }[];
  dataStores: { id: string; label: string; steps: number[] }[]; simplified: boolean }
```

A `wireGuards.ts` guard `isDiscoveryReport` checks only the top-level keys and `number`/`title` of each part; a part that fails its guard is treated as missing (§11.11.3), never as a page error.

**Component tree additions**

```
pages/ProcessDiscovery.tsx                          hooks/useDiscoveryState (+ upload, remove, proposals)
├── chat/ChatMessageList
│   └── process-discovery/DocumentHint               under the first agent message (§11.1)
└── process-discovery/ProcessProfilePanel
    ├── ProcessCard → FieldRow → ProposalChip → ProposalActions (✓ / ✎, Show quote)
    ├── SubstepTabs → FieldRow … + "Confirm all n proposals in step k", "Confirm the n proposed step names"
    ├── DerivedReviewPanel
    ├── process-discovery/DocumentPanel             (new section, SectionToggle)
    │   ├── FileDrop                                 button + drop zone + hidden file input
    │   ├── ui/ProgressBar, ui/Spinner               upload progress, reading
    │   ├── ui/Alert                                 result sentence (status) / error (alert)
    │   └── document list + ui/Modal (alertdialog)   Remove
    └── Finish block
pages/DiscoveryReport.tsx                            useQuery(['report', id]), getReportPdf
├── layout/AppHeader                                 Download PDF · Back to My processes · theme
├── report/ReportContents                            nav, anchors
├── report/ReportPartBoundary (one per part)         missing / crashed part note
│   ├── report/ReportCover
│   ├── report/AtAGlance
│   ├── report/ReportFields (process, measures)
│   ├── report/ProcessMap + report/StepTable        utils/processMap.toMermaid, lazy mermaid
│   ├── report/StepAssessmentTable
│   ├── report/RecommendedRoute
│   ├── report/OpportunityList
│   ├── report/HoursTables
│   ├── report/ReadinessTable
│   ├── report/SuggestedPath
│   └── report/GapsAndSources
└── report/ReportNote                                notes and catalogue note
utils/{documentLimits,processMap,downloadFile}.ts · types/report.ts
```

## 13. Implications (part 2)

- **Other components:** spec 15 / 17 routes are the contract for documents; the report route of spec 20 §3.5 is the contract for the page. When the report route lands, `types/report.ts`, the guard and `src/test/fixtures/report.ts` are reconciled with its wire model first (optionally from a recorded sample in `backend/tests/fixtures/api/`, part 1 Q1). Spec 20 §3.2 says *Finish* answers with the report; the built finish route returns `SessionOut`: the client keeps navigating to the report page and does not read a report from the finish reply.
- **Data:** no new browser storage. The report is not cached beyond React Query's memory cache.
- **Config:** document limits from `GET /api/config`; branding text (product, company) from the report cover. Nothing new at build time.
- **Security and privacy:** file bytes go only to the upload route; the client never reads the file's content (no `FileReader`). No document text, transcript or display name is shown on the report page. Quotes and report texts render as plain text. Mermaid runs with `securityLevel: "strict"` and gets cleaned labels with generated ids. The PDF is fetched with the visitor key and saved through an object URL that is revoked at once.
- **Cost and latency:** one model call per upload (server side, up to about a minute); none for ✓ / ✎, removal, report or PDF. Mermaid is about 1 MB of script, loaded only on the report page.
- **Accessibility:** tables have captions and header scopes; scroll regions are focusable and labelled; status by text and icon, never colour alone; the map has a text alternative; upload progress is a labelled progressbar and the reading stage a status.

**Behaviours that must not be lost** (each has an AC):

| # | Behaviour |
|---|---|
| 18 | Nothing from a document counts until ✓ or a yes in the chat; the client never counts proposals |
| 19 | Only one write at a time: upload, removal, ✓ / ✎ and a turn never run together on one session |
| 20 | Document errors show inside the panel; `document_limit` (409) is not treated as `conflict` |
| 21 | Removing a document keeps confirmed values, shown "from a removed document" |
| 22 | ✎ starts no turn and sends no message |
| 23 | The report page shows the cover and the eleven parts in spec 20 order; one bad part never blanks the page |
| 24 | No euro figure, cost, value or saving on the report page (R5) |
| 25 | The client formats no report value; it shows the server's strings |
| 26 | The map follows the app theme, and prints in the light theme |
| 27 | The PDF is fetched with the visitor key, not opened as a plain link |

## 14. Acceptance criteria (part 2)

| ID | Given / when / then |
|---|---|
| AC-23.59 | `api.ts`: `uploadDocument` sends `POST /api/sessions/{id}/documents` as multipart with one `file` part and `X-Visitor-Key`, reports progress through `onProgress`, and parses `{code, message}`, non-JSON (`http_<status>`) and network failures into `ApiError`; `removeDocument`, `confirmProposals`, `rejectProposals`, `getReport`, `getReportPdf` use the method, path and body of §12; `getConfig` sends no visitor key |
| AC-23.60 | `getReportPdf` returns the blob and the file name from `Content-Disposition`, and `discovery-report.pdf` when the header is missing |
| AC-23.61 | Given an active session, the Documents section shows "Documents n/max", the **Add a document** button and the helper line built from the config (types, MB, files); the file input `accept` lists the configured extensions with dots |
| AC-23.62 | With the config failing to load, the button still opens the picker, no pre-check runs and the upload call is made |
| AC-23.63 | Pre-checks: a file over `maxFileMb`, an empty file, a disallowed extension, or a session at `maxFiles` documents shows the matching spec 17 §3.12 sentence in the panel and makes no call |
| AC-23.64 | Dropping one file on the zone uploads it; dropping two uploads the first and says "One file at a time: I took <name>."; the zone is operable by keyboard (Enter and Space open the picker) |
| AC-23.65 | During an upload the panel shows a progressbar labelled "Upload progress" with `aria-valuenow` following `onProgress`, then "Reading <name>…" with `role="status"` once 100 % is reached |
| AC-23.66 | While an upload, a removal or a ✓ / ✎ call is in flight, the composer, upload, Remove, ✓ / ✎, batch buttons, confirm buttons and *Finish* are disabled; while a turn is in flight, upload and ✓ / ✎ are disabled |
| AC-23.67 | A successful upload replaces the session (new field views and documents), shows `report.message` as a dismissible status in the panel, and keeps open sections, the chosen step tab and composer text |
| AC-23.68 | Each upload error code of §11.5 (`document_limit`, `document_too_large`, `http_413`, `document_type`, `document_unreadable`, `unsafe_input`, `budget_exhausted`, `network`) shows its sentence inside the panel as `role="alert"` and no top banner; `document_limit` does not reload the session |
| AC-23.69 | `session_closed` on an upload, removal or ✓ / ✎ locks the composer and clears every spinner (part 1 rule); `conflict` reloads the session and shows the reload banner |
| AC-23.70 | The document list shows, per document, name, kind word, "read in part" when truncated, and the count text of §11.6 for failed, nothing new, waiting and all-settled documents; no byte or character count is rendered |
| AC-23.71 | **Remove** opens an `alertdialog` whose text mentions the pending proposals only when `pending > 0`; **Cancel** (focused first) makes no call; **Remove** calls `DELETE …/documents/{docId}` and the returned session replaces the panel |
| AC-23.72 | After a removal, a value confirmed from that document shows "from a removed document"; a 404 on remove reloads the session and shows "That document was already removed." |
| AC-23.73 | The chat hint card with **Add a document** shows on an active session in phase `context` or `find` with no documents, opens the same picker, and is gone once a document exists, in later phases, or when the session is closed |
| AC-23.74 | On `finished` and `no_candidate` sessions the drop zone, Remove, ✓ and ✎ are hidden and the document list is still shown |
| AC-23.75 | A `proposed` field row shows "Proposed · from <documentName>" (or "from a removed document", or "from your idea"), a "Show quote" button with `aria-expanded` that reveals the quote, and ✓ / ✎ buttons labelled "Confirm <label>" / "Reject <label>"; the quote's open state survives a server response |
| AC-23.76 | ✓ calls `confirmProposals(id, [key])` and the row then shows the server's new status; ✎ calls `rejectProposals(id, [key])`, sends no message, and the status line reads "Removed. The agent will ask you about <label>." until the next send |
| AC-23.77 | ✓ / ✎ also work on step cells inside `SubstepTabs`, with the 1-based cell key (`process.substeps[2].data`) |
| AC-23.78 | A step with two or more proposed cells shows "Confirm all <n> proposals in step k", which calls `confirmProposals` with exactly those keys in field view order; with fewer than two it is not shown; the tab label reads "· proposed" while the step has a proposal |
| AC-23.79 | Two or more rows with a proposed step name show "Confirm the <n> proposed step names", which sends the S01 keys in step order; the returned session (P16 set by the server) updates the Steps count and the phase meter |
| AC-23.80 | Reducer: `UPLOAD_STARTED` / `UPLOAD_PROGRESS` / `DOCUMENT_UPLOADED` / `DOCUMENT_REJECTED` / `DOCUMENT_REMOVING` / `PROPOSALS_STARTED` set and clear their flags as in §11.9, replace only the server slice, and ignore results for another `sessionId` |
| AC-23.81 | Fake API: a `procedure` file on an empty session gives proposed trigger, end result and 5 step names with quotes and the "found 2 values and 5 steps" sentence; `.bpmn`, `empty`, `long`, `failed`, `scan`, `inject` give their scripted outcomes; confirm, reject and remove update the views and `pending` counts; progress reaches 100 % |
| AC-23.82 | Given `/report/:id` and a report, the page calls `GET …/report` once (StrictMode), shows "Loading your report…" with `role="status"` while loading, then the report |
| AC-23.83 | A 404 shows "This report is not available. …" with **Continue the interview** and **Back to My processes**; any other error shows its part 1 sentence and **Retry**, which refetches |
| AC-23.84 | The page renders the cover and then eleven `<section>`s whose `<h2>` read "1. At a glance" … "11. Gaps and sources" from the model, in spec 20 order; the contents nav links to each `#part-<key>` |
| AC-23.85 | The cover shows product and company name, process name, department, cluster, region, process owner, date and the status pill text ("Mapped" or "Validated by IT") |
| AC-23.86 | With the EU fixture the rendered page contains "About 342 hours a year.", the route headline, three top opportunities with their hours, and nowhere "€", "cost today", "freed" or "saving" (text scan of the whole page) **Aligned:** the one exception is the server's `parkedLine` ("Euro value and savings are not shown yet…"), shown as given. |
| AC-23.87 | Parts 2 and 3 render `<dl>` pairs from `fields` with the server's values ("Not measured yet", "None"); the task note shows when sent |
| AC-23.88 | `toMermaid` on the EU diagram gives `flowchart LR`, one subgraph per lane, the right shape per node type, labelled flows with "(default)" on default flows, data objects as parallelograms with dotted links on the correct side, data stores as cylinders; the same diagram always gives the same text; empty diagram gives `""` |
| AC-23.89 | `toMermaid` never passes a raw id, and a label with `"`, `<script>`, `]`, `}`, a line break or 200 characters comes out escaped and cut to 80 characters |
| AC-23.90 | `ProcessMap` calls the injected renderer with theme `default` in light mode and `dark` when the `dark` class is on `<html>`, draws again when the theme toggles, and exposes `role="img"` with the step and role counts in `aria-label`; "Map as text" lists the steps in order with their lanes |
| AC-23.91 | When the diagram is null or the renderer throws, the map area shows "The process map could not be drawn." and the systems line and step table still render; a simplified map shows the server's caption |
| AC-23.92 | The step table is a `<table>` with a `<caption>`, one `<th scope="col">` per step, one `<th scope="row">` per leaf, cells as sent ("— (skipped)", "(proposed, not confirmed)"), inside a focusable labelled region |
| AC-23.93 | Part 5 renders a table with columns Step, Hours a year, AI fit, Route, Why this route, Reason, Evidence; AI fit shows an icon and the server's word ("AI can do it", "Not assessed"); "No route" and evidence labels show as sent; the catalogue note shows above Parts 5 and 6 when not null and is absent when null |
| AC-23.94 | Part 6 shows the headline, the groups in the order sent with their items, and "What to have in place"; Part 10 shows its three groups in order with "Nothing here." as sent |
| AC-23.95 | Part 7 shows each opportunity with title, steps label, type, impact and feasibility words, what changes, how, prepare first, evidence with its label, and the stay-with-people list; with the failed note fixture it shows the warning note and the rest of the page |
| AC-23.96 | Part 8 renders the per-step and per-opportunity tables, the total in `<tfoot>` ("—" as sent when incomplete), formulas, assumptions and the euro-not-shown line; Part 9 renders six rows with level words and the "Not a verdict" footer; Part 11 lists open fields, documents with outcome words (no text) and the closing note |
| AC-23.97 | A part with `note.kind` `failed` or `error` shows a warning note with the server's text; other kinds show an info note; a part missing from the JSON shows its fallback heading and "This part could not be generated."; a part whose component throws shows "This part could not be shown." and every other part still renders |
| AC-23.98 | Report text containing `<img src=x onerror=alert(1)>` or Markdown is shown as literal text; no element is created from it |
| AC-23.99 | **Download PDF** calls `getReportPdf` once, shows "Preparing PDF…" while in flight, saves the blob under the returned file name through a temporary link, and revokes the object URL; an error shows inline next to the button and leaves the report visible |
| AC-23.100 | Print: the header, contents nav and buttons carry the print-hidden class; with the app dark, a `beforeprint` event draws the map with the light theme and `afterprint` draws it dark again |
| AC-23.101 | Fake API: a finished fake session returns `euReport`; an active one gives 404; `/report-failed steps` makes the next report carry failed notes on `steps` and `route`; `/report-missing map` leaves the map part out; the PDF call returns a blob starting with `%PDF` **Aligned:** before *Finish* the server answers 409 `report_not_ready`; the page shows "not available yet" for 409 and 404 alike. |
| AC-23.102 | New components use theme tokens only (the AC-23.57 source scan covers `components/report/` and the new process-discovery files); the report page and the panel pass the token contrast check in both themes |
| AC-23.103 | The chat input bar shows a "+" button to the LEFT of the message box with `aria-label="Add a document"`; pressing it (or Enter/Space on it) opens the file picker; choosing a file uploads it exactly like the panel's control |
| AC-23.104 | The "+" button is disabled while a turn is sending, while an upload runs (spinner shown), when the session is closed, and when the document limit is reached; the tooltip states the reason |
| AC-23.105 | Dropping a file on the chat area uploads it; the upload result sentence appears in the chat as a system note, and the Documents section in the panel updates from the returned session |
| AC-23.146 | *(amended 2026-11-20)* A process field or a step cell whose view has `conflict: "open"` shows the text "Conflict – answer in the chat" in its row and no extra button; with `conflict: "left"` or `null` the text is absent |
| AC-23.152 | *(amended 2026-11-21 (report v2))* `types/report.ts` and `checkDiscoveryReport` / `loadReport` mirror the v2 wire model: `summary`, `process`, `measures`, `map`, `steps` (rows with `level`, `levelLabel`, `because`), `feasibility` (`questions` keyed q1–q3, `readiness`, `readinessFooter`, `bullets`, `gaps`); the recorded sample passes, numbered 1–6; a v1 report fails with `summary` and `feasibility` missing |
| AC-23.153 | *(amended 2026-11-21 (report v2))* The summary shows each server sentence as one paragraph in order and nothing when the list is empty |
| AC-23.154 | *(amended 2026-11-21 (report v2))* Part 5 has columns Step, Hours a year, AI fit, Because, Route, Why, The expert's words; AI fit is a signal icon plus the server's level words ("Strong fit", "Not assessed"), never yes / no; the catalogue note shows when sent |
| AC-23.155 | *(amended 2026-11-21 (report v2))* The three questions table has one row per question with the question as row header, the level words with an icon, and why with the quote labelled "the expert's words" |
| AC-23.156 | *(amended 2026-11-21 (report v2))* Part 6 shows, in order, The three questions, Readiness (six rows: Dimension, Level, To prepare; then the footer) and Before starting and risks (the bullets, then the gaps line in small print); its block headings sit one level below the part heading |
| AC-23.157 | *(amended 2026-11-21 (report v2))* The report page renders the cover and six sections "1. Summary" … "6. AI readiness and feasibility" linked from the contents nav, with no euro, saving, yes or no-go; the workspace popup of a finished session renders Summary, Step-by-step AI assessment, The three questions and Process map as `<h3>` blocks, and none of the old route or opportunity blocks |

## 15. Test plan (part 2)

| Test file | Covers |
|---|---|
| `src/services/api.test.ts` | AC-23.59, 23.60 (stubbed `fetch`; a fake `XMLHttpRequest` for upload progress and errors) |
| `src/services/fakeApi.test.ts` | AC-23.81, 23.101 |
| `src/utils/documentLimits.test.ts` | AC-23.61 (helper line, `accept`), 23.63 (pre-check order and sentences) |
| `src/utils/discoveryErrors.test.ts` | AC-23.68, 23.69, 23.72 (one case per new row of §11.5) |
| `src/hooks/useDiscoveryState.test.ts` | AC-23.66 (`isWriting`), 23.80 |
| `src/components/process-discovery/DocumentPanel.test.tsx` | AC-23.61–23.65, 23.67, 23.70, 23.71, 23.74 |
| `src/components/process-discovery/FileDrop.test.tsx` | AC-23.64 (drop events, keyboard) |
| `src/components/process-discovery/FieldRow.test.tsx`, `SubstepTabs.test.tsx` | AC-23.146 |
| `src/components/process-discovery/ProcessCard.test.tsx` | AC-23.75, 23.76 (✓ / ✎ on process fields; replaces part 1's read-only chip case of AC-23.31 for the hint text) |
| `src/components/process-discovery/SubstepTabs.test.tsx` | AC-23.77–23.79 |
| `src/pages/ProcessDiscovery.test.tsx` | AC-23.66, 23.67, 23.69, 23.72, 23.73 (fake API through `ApiProvider`: upload a `procedure` file, confirm a step batch, remove the document) |
| `src/utils/processMap.test.ts` | AC-23.88, 23.89 |
| `src/components/report/ProcessMap.test.tsx` | AC-23.90, 23.91, 23.100 (stub renderer; `dark` class toggled; `beforeprint` / `afterprint` dispatched) |
| `src/components/report/report-parts.test.tsx` | AC-23.85, 23.87, 23.92–23.96, 23.98 (each part component on the fixtures) |
| `src/pages/DiscoveryReport.test.tsx` | AC-23.82–23.84, 23.86, 23.97, 23.99, 23.100 (header hidden in print class) |
| `src/utils/downloadFile.test.ts` | AC-23.99 (`URL.createObjectURL` / `revokeObjectURL` stubbed) |
| Existing token scan and contrast tests | AC-23.102 (paths extended) |

Fixtures: `src/test/fixtures/sessions.ts` gains `withProposals` (process fields and a step with proposed cells, two documents) and `afterRemoval`; `src/test/fixtures/report.ts` holds the report fixtures of §11.15.8. Tests use role and label queries and `user-event` (including `upload` for the file input). Mermaid itself is never run in jsdom; the renderer is stubbed. Manual check before marking built: `npm run dev:fake` (upload each scripted file, ✓ / ✎, batch, remove, finish, report, PDF, print preview in both themes), then `make dev` against the backend with a real `.docx` and `.bpmn`.

## 16. Out of scope (part 2)

| Item | Where |
|---|---|
| Workspace: access-code gate, review screen, overview, briefs, the specialist's validation note | Part 3 (spec 21) |
| Cancelling an upload in flight, re-reading a failed document in place | Not in the prototype (remove and upload again) |
| Several files in one upload, images of diagrams | Not in the prototype (F-04: images are *Could*) |
| Editing the report on screen, regenerate | Part 3 (specialists only) |
| Euro values, cost today, hours freed, saving shares | Parked (R5) |
| BPMN XML and Excel downloads | Spec 22 |
| Sharing a report link with someone without the visitor key | Not planned; the PDF is the way to share |

## 17. Open questions (part 2)

| # | Question | Default until decided |
|---|---|---|
| Q7 | The report wire model is being built now. Field names in `types/report.ts` (cover fields, `PotentialPart.steps` columns, opportunity labels, the euro line) follow spec 20 §4 where it is explicit and are assumptions where it says only a type name | Reconcile with the built model before writing the report tests; the server's names win |
| Q8 | Are report numbers (`hours`, `stepHours`, `hoursPerYear`) formatted strings ("96 h") as spec 20 implies ("the PDF writer receives already formatted strings"), or numbers? | Strings; if the route sends numbers, one `formatHours` helper is added on the client, with the spec 20 rule (whole hours, "h") |
| Q9 | *(decided)* Turn after ✎? | No: the next turn asks; the status line says so |
| Q10 | Spec 20 §3.2 says *Finish* returns the report; the built route returns `SessionOut` | Keep navigating to `/report/:id` and loading the report there; no change asked of the backend |
| Q11 | Should the report page show the specialist's validation note (part 1 Q3)? | Only when the report model carries it; not in the spec 20 model today. Part 3 decides |
| Q12 | *(decided)* ✓ / ✎ on a proposal from an idea? | Yes, labelled "from your idea" |
| Q13 | *(decided)* Batch confirm per section? | Not now: per step and step names only |

---

# Part 3: the workspace (admin screens)

> **Status:** draft · **Implements:** the screens of F-17.1, F-17.6, F-17.7 (read-only part), F-21.3 (workspace code), F-23.5 (delete a session) (product); architecture §1 (admin side) · **Depends on:** part 1 (shell, `AppHeader`, theme §3.13, `ui/*`, errors, fake/real API), part 2 (report components, `ProcessMap`, `saveBlob`), spec 16 §3.2 (login, token), spec 21 (workspace routes and wire models; **draft**, names marked *to confirm against spec 21*)
> **Code:** `frontend/src/pages/Workspace.tsx`, `frontend/src/components/workspace/*`, `frontend/src/access/workspaceToken.ts`, `frontend/src/types/workspace.ts`, `frontend/src/utils/workspaceFormat.ts`, additions to `services/{api,fakeApi,fakeData,loadApi}.ts`, `utils/discoveryErrors.ts`, `App.tsx`, `components/chat/ChatMessageBubble.tsx` · **Tests:** next to each file
> **Scope in one line:** log in, see every session in one list, open one read-only, read its conversation, download its PDF, delete it. Nothing else.

## 18. Purpose (part 3)

Give the IT and transformation specialist one page, `/workspace`, behind the access code and a name. It shows a **list** of all discovery sessions with simple filters. A click opens a **read-only popup**: summary cards, the step grid (now, or as the expert first told it), the step-by-step AI assessment and the opportunities, the process map, and a **Conversation** tab with the full chat. From the popup the specialist can **download the report PDF** and **delete** the session. No edits, no validation, no overview, no briefs.

## 19. Behaviour (part 3)

### 19.1 Route and page states

| Route | Page | Notes |
|---|---|---|
| `/workspace` | `Workspace` | Login form when no valid token; the session list otherwise. The popup is page state, not a route |

No link to `/workspace` from the expert's screens (unchanged part 1 rule: no admin link). The specialist types the address.

| State | When | Shown |
|---|---|---|
| **Login** | No token, token expired, or after a 401 / 403 | `WorkspaceLogin` (§19.2) |
| **Loading** | List query pending (first load) | "Loading sessions…" with `Spinner`, `role="status"` |
| **List** | List loaded, at least one row | Counts line, filters, `SessionTable` |
| **Empty, no sessions** | `counts.total = 0` | "No discovery sessions yet." |
| **Empty, filtered** | `counts.total > 0`, `matching = 0` | "No sessions match these filters." and **Clear filters** |
| **Error** | List call fails (not 401 / 403) | `ui/Alert` with the part 1 §3.11 sentence and **Retry**. Never an empty list or zero counts |
| **Session ended** | Any workspace call returns 401 `workspace_code_required` | Token cleared, popup closed, login shown with the notice "Your workspace session has ended. Enter the access code again." |

Header (`AppHeader`, title "AI Use Case Discovery Agent · Workspace"): when logged in, the typed name as text ("Signed in as <name>"), **Refresh** (refetches the list), **Log out** (clears the token, shows login), then the theme toggle (part 1 §3.13, unchanged). Below 640 px the buttons become icon buttons with `aria-label`s.

### 19.2 Login (`components/workspace/WorkspaceLogin.tsx`, `access/workspaceToken.ts`)

| # | Rule |
|---|---|
| 1 | A centred card (max 400 px): `<h2>` "Workspace", the line "For the IT and transformation team.", fields **Access code** (`type="password"`, `autocomplete="off"`) and **Your name** (1–40 characters, `maxLength=40`, helper "Shown in the log next to what you open."), button **Open workspace** |
| 2 | **Open workspace** is disabled while either field is blank (after trim) or a login is in flight ("Opening…" with spinner) |
| 3 | `workspaceLogin(code, name)` → `POST /api/workspace/login` (spec 16, built). Success with `role: "specialist"` stores `{token, role, name, expiresAt}` as JSON in `sessionStorage` under `pd_workspace` and shows the list. The code is never stored |
| 4 | Success with `role: "engineer"`: nothing stored; the form shows "This code is for engineers. Their screens are not available yet." |
| 5 | 401 `workspace_code_invalid` → "The access code is not valid." under the form (`role="alert"`), code field cleared and focused, name kept. 429 `rate_limited` → the server's sentence. Other errors → part 1 §3.11 sentence |
| 6 | `readWorkspaceToken()` returns the stored value only when it parses, has role `specialist` and `expiresAt` is in the future; otherwise it removes it and returns `null`. Called on page load and before every workspace call |
| 7 | If `sessionStorage` throws, the token lives in memory for this tab only; login still works |
| 8 | **Log out** and every 401 / 403 call `clearWorkspaceToken()`. 403 `forbidden` shows "This access code does not open the workspace." on the login form |
| 9 | The visitor key (part 1 §3.2) is not touched and not sent on workspace calls; the token is not sent on expert calls |
| 10 | *(Amended 2026-11-20 (open workspace).)* The page reads `GET /api/config` (React Query `['config']`, shared with part 2). When `workspaceOpen` is `true`, the card has no **Access code** field; it shows the line "Open demo workspace: anyone with the link can read sessions. Deleting is switched off." under the intro, and **Open workspace** is disabled only while the name is blank or a login is in flight; it calls `workspaceLogin('', name)`. While the config loads, or if it fails, the card behaves as closed (code field shown); `WorkspaceLogin` gets this as an `open` prop from the page. When `workspaceOpen` is `false`: rules 1–9 unchanged |

### 19.3 Session list (`components/workspace/SessionFilters.tsx`, `SessionTable.tsx`)

**Data:** React Query `['workspace', 'sessions', filters]` → `GET /api/review/sessions?status&cluster&q`. Previous rows stay on screen while a new filter loads (`placeholderData: keepPreviousData`), with the table `aria-busy="true"`. Sorting is the server's (newest `updatedAt` first); the client never re-sorts.

**Counts line** (above the filters, `role="status"`, `aria-live="polite"`): "<total> sessions · <active> in progress · <finished> mapped · <noCandidate> ended with nothing to map". With a filter set, a second part: "<matching> match the filters". With `truncated: true`: "Showing the 1,000 most recently updated sessions."

**Filters** (`<section aria-label="Session filters">`, server-side, combined with AND):

| Filter | Control | Values | Sent as |
|---|---|---|---|
| Status | `<select>` labelled "Status" | All statuses, In progress, Mapped, Ended · nothing to map | `status=active / finished / no_candidate`; omitted for All |
| Cluster | `<select>` labelled "Cluster" | All clusters, then "<code> · <name>" from `GET /api/taxonomy` (public, part 1) | `cluster=<code>`; omitted for All. If the taxonomy fails, the select shows only "All clusters" and is disabled |
| Text | `<input type="search">` labelled "Search" | Placeholder "Process, department or session id"; `maxLength=100` | `q=<trimmed text>` after 300 ms without typing; omitted when blank |
| **Clear filters** | Button, shown only when a filter is set | Resets all three | — |

Filters live in component state only (not the URL, not storage).

**Table** (`<table>` with `<caption>` "Discovery sessions, newest update first", `<th scope="col">`, inside a focusable `role="region"` `aria-label="Session list"` that scrolls sideways; the Process column is sticky):

| Column | Shows | Source (spec 21 §3.2) |
|---|---|---|
| Process | A button with the process name, or "Not named yet" (muted); `aria-label="Open session <name or id>"` | `processName`, `id` |
| Status | `ui/Pill` with the status text (§19.8) and, for active sessions, the phase label under it. Text always present, never colour alone | `status`, `phase` |
| Department | Text or "—" | `department` |
| Cluster | "<code> · <name>" or "—" | `clusterCode`, `clusterName` |
| Region | Text or "—" | `region` |
| Fields | "<filled> / <total>" | `fieldsFilled`, `fieldsTotal` |
| Steps | Number | `steps` |
| Messages | Number | `messageCount` |
| Documents | Number | `documentCount` |
| Updated | Relative time (`formatRelativeTime`, part 1) inside `<time dateTime>` with the full date and time as `title` | `updatedAt` |
| Created | Date "20 Nov 2026" in `<time dateTime>` | `createdAt` |

1. **Opening a row:** the Process button opens the popup (Enter / Space, since it is a button). A click anywhere else on the row does the same (mouse convenience only; the row itself is not focusable and has no role).
2. Zebra rows and a hover tint come from tokens (`bg-surface-muted`, `bg-primary-soft`). No paging: all rows returned are rendered (at most 1,000, spec 21).
3. After the popup closes, focus returns to the Process button of that row (or to the table caption's region when the row was deleted).

### 19.4 Session popup (`components/workspace/SessionDialog.tsx`)

A large `ui/Modal` (new size `xl`: `max-w-6xl`, `w-[96vw]`, `max-h-[90vh]`, body scrolls). Title: the process name or "Not named yet"; description line: "Session <id> · Updated <relative time>". Close with the × button, Escape, or **Close** in the footer.

**Data:** React Query `['workspace', 'session', id]` → `GET /api/review/sessions/{id}`. Loading: "Loading the session…" (`role="status"`). 404: "This session no longer exists." with **Close**; closing refreshes the list. Other errors: part 1 sentence and **Retry**.

**Two tabs** (`ui/Tabs`, `label="Session views"`): **Session** (default) and **Conversation** (§19.5). The tab choice resets to Session each time a popup opens.

```
+-------------------------------------------------------------------------------------------+
| Monthly supplier invoice check                                                        [×] |
| Session s1 · Updated 2 hours ago                                                          |
| [ Session ] [ Conversation ]                                                              |
|-------------------------------------------------------------------------------------------|
| +- Context ----------+ +- Process ----------+ +- Scope ------------+ +- Measures -------+ |
| | Department Finance | | Name Monthly …     | | Fields 52 / 64     | | Completeness 81 %| |
| | Function  Controll.| | Cluster FIN · Fin. | | Steps  4 / 4       | | Points 41 / 50   | |
| | Region    Europe   | | Status Mapped      | |                    | | Messages 52      | |
| +--------------------+ | Phase  Finished    | +--------------------+ | Documents 1      | |
|                        +--------------------+                        +------------------+ |
| Steps                         [ Now ] [ As first told ]                                   |
| | Field        | Step 1 · Collect … | Step 2 · Consolidate … | …  → (scrolls sideways)   |
| Documents   invoice-procedure.pdf · PDF · 18 Nov 2026 · read                              |
| Step-by-step AI assessment    (report StepAssessmentTable)                                |
| Opportunities                 (report OpportunityList)                                    |
| Process map                   (report ProcessMap, "Map as text")                          |
|-------------------------------------------------------------------------------------------|
| [Delete session]                                      [Download report (PDF)]  [Close]    |
+-------------------------------------------------------------------------------------------+
```

**Session tab, in this order:**

| # | Block | Content and rules |
|---|---|---|
| 1 | **Summary cards** (`SummaryCards`) | Four cards in a responsive grid (4 columns ≥ 1024 px, 2 ≥ 640 px, else 1). Each card is a `<section aria-labelledby>` with an `<h3>` and a `<dl>`. *Context:* Department, Function, Region. *Process:* Name, Cluster ("<name>"), Status (status text, §19.8), Phase (phase label). *Scope:* Fields filled "<n> / <total>", Steps "<started> / <expected>". *Measures:* Completeness "<pct> %" (`completenessPct`, part 1), Points "<filled> / <total>", Messages, Documents. Empty values show "—" |
| 2 | **Step grid** (`StepGrid`) | `<h3>` "Steps" and a two-button toggle group (`role="group"`, `aria-label="Step version"`): **Now** and **As first told**, each with `aria-pressed`. **As first told** is disabled when `rawSteps` is `null`, with the reason visible next to it: "The expert's first version was not kept, because nothing changed it." The table follows the part 2 `StepTable` pattern: `<caption>` ("Steps now, one column per step" / "Steps as the expert first told them, one column per step"), `<th scope="col">` "Step k · <name>", `<th scope="row">` per field label, sticky first column, focusable `role="region"` `aria-label="Step grid"`. Each cell: the value (§19.6), and a small muted line with the source word ("expert", "from a document", "specialist") and status word ("Complete", "Partly answered", "Proposed", "Not answered"; part 1 §3.8.3 icons + text). No step rows: "No steps yet." |
| 3 | **Documents** | One line per document: name · kind word · upload date · outcome word ("read" / "could not be read"). Never size, never text. None: block hidden |
| 4 | **Step-by-step AI assessment** | Reuses part 2 `StepAssessmentTable` with `report.steps` (catalogue note included) |
| 5 | **Recommended route** | Reuses part 2 `RecommendedRoute` with `report.route` |
| 6 | **Opportunities** | Reuses part 2 `OpportunityList` with `report.assessment` |
| 7 | **Process map** | Reuses part 2 `ProcessMap` with `report.map.diagram` and `report.map.caption` (lazy Mermaid, theme-aware, "Map as text", failure note). The step table of the map part is **not** repeated (the grid above shows the steps) |

1. Blocks 4–7 need `report`. When `report` is `null` (session not finished), they are replaced by one info `ReportNoteBox`: "The assessment and the map are ready once the expert finishes the interview."
2. Each of blocks 4–7 sits in a part 2 `ReportPartBoundary` and keeps its part note behaviour (failed / missing → warning note); one bad block never blanks the popup.
3. Headings inside the popup start at `<h3>` (the modal title is the `<h2>`); the reused report components are given a `headingLevel` prop (default `2` on the report page, `3` here) so the outline stays correct. This is the only change to the part 2 components.
4. Nothing in the popup is editable: no inputs, no edit buttons; cells are plain text, not disabled fields, so they are not in the tab order.

### 19.5 Conversation tab (`components/workspace/ConversationView.tsx`)

| # | Rule |
|---|---|
| 1 | The conversation is fetched **only when the tab is first opened** (React Query `['workspace', 'conversation', id]`, `enabled` after first selection): `GET /api/review/sessions/{id}/conversation`. Each fetch is one audit line on the server (spec 21 §3.4), so no prefetch, no refetch on focus, `staleTime: Infinity` while the popup is open |
| 2 | A one-line notice on top: "The expert was told that the team may read this conversation. Opening it is logged." |
| 3 | Messages in server order, rendered with part 1 `ChatMessageBubble` and a new prop `speaker` labels: expert → "Expert", agent → "Agent" (the interview page keeps "You"). The time line shows date and time ("20 Nov 2026, 14:05") when the prop `showDate` is set. Agent text keeps the part 1 safe Markdown; expert text is plain |
| 4 | The list is an `<ol aria-label="Conversation, <n> messages">` (not `role="log"`: it does not change). It scrolls inside the tab; the popup opens it at the top |
| 5 | Loading: "Loading the conversation…" (`role="status"`). No messages: "No messages in this session." Error: part 1 sentence and **Retry** |
| 6 | No copy-all, no export, no search: out of scope |

### 19.6 Cell values (`utils/workspaceFormat.ts`)

The grid cell value is `Any` in spec 21 (*to confirm against spec 21*: a server-formatted string is preferred). Until then, `formatCell(value)` is the only formatter:

| Value | Shown |
|---|---|
| `null`, `""`, `[]` | "—" |
| string, number | As is (plain text, `whitespace-pre-wrap`) |
| list of strings | One item per line |
| object | "<key>: <value>" per line, keys in received order, nested values via the same rule |
| list of objects | Numbered entries "1.", "2.", each formatted as an object |

No Markdown, no HTML. If spec 21 sends a string, `formatCell` returns it unchanged and the other rows become dead code to remove.

### 19.7 Download and delete (popup footer)

**Download report (PDF)** (secondary button with `Download` icon):

| # | Rule |
|---|---|
| 1 | Enabled only when `summary.status` is `finished`; otherwise disabled with the visible reason "The report is ready once the interview is finished." linked by `aria-describedby` |
| 2 | `getReviewReportPdf(id)` → `GET /api/review/sessions/{id}/report.pdf` with `Authorization: Bearer <token>` (fetch, never a plain link), returns `{blob, filename}`; file name from `Content-Disposition`, fallback `discovery-report.pdf`; saved with part 2 `saveBlob` |
| 3 | In flight: "Preparing PDF…" with spinner, button disabled. Errors show inline next to the button (`role="alert"`): 409 `report_not_ready` → the rule 1 sentence; others → part 1 sentence. 401 → session ended (§19.1) |

**Delete session** (danger button, left side of the footer):

| # | Rule |
|---|---|
| 1 | Opens an `alertdialog` (`ui/Modal role="alertdialog"`, stacked on the popup): title "Delete this session?", text "This removes the session, its map and its report for everyone, including the expert. The expert's ideas stay. This cannot be undone." Buttons **Cancel** (focused first) and **Delete session** (danger) |
| 2 | **Delete session** → `deleteReviewSession(id, etag)` → `DELETE /api/review/sessions/{id}` with `If-Match: <etag>` from the loaded session view. Both dialogs' buttons are disabled while in flight ("Deleting…") and Escape is ignored |
| 3 | 204 → both dialogs close, the list refetches, the page shows a dismissible status "Session deleted." (`role="status"`) above the table |
| 4 | 409 `conflict` → the confirm closes, the session view refetches, and the popup shows "This session changed while you were looking. It has been reloaded; check it and try again." The etag is taken from the new view |
| 5 | 404 → both close, the list refetches, status "This session was already deleted." |
| 6 | 428 `etag_required` cannot happen from this client (the etag is always sent); if it does, the part 1 fallback sentence |
| 7 | Delete is shown for every status. There is no delete button in the list rows |
| 8 | *(Amended 2026-11-20 (open workspace).)* When `GET /api/config` says `workspaceOpen: true` (or has not loaded), the **Delete session** button is not rendered (the server refuses delete there anyway, spec 21 §3.6 item 4); a failed config counts as closed. `SessionDialog` gets this as a `canDelete` prop from the page (default `true`). Download and Close are unchanged |

### 19.8 Words (`utils/workspaceFormat.ts`)

| Item | Words |
|---|---|
| Status `active` / `finished` / `no_candidate` | "In progress" / "Mapped" / "Ended · nothing to map" (same words as Home, part 1 §3.3) |
| Status pill tone | info / success / neutral; the text is always present |
| Phase | `phaseLabel` (part 1) |
| Cell source `expert` / `document` / `specialist` / `null` | "expert" / "from a document" / "specialist" / nothing |
| Cell status | part 1 §3.8.3 table (icon + word) |
| Document outcome `read` / `failed` | "read" / "could not be read" |
| Dates | `formatRelativeTime` (part 1) and `Intl.DateTimeFormat('en-GB', {day: 'numeric', month: 'short', year: 'numeric'})` |

### 19.9 Errors (additions to `utils/discoveryErrors.ts`)

| Code | Effect | Text |
|---|---|---|
| `workspace_code_invalid` (401, login only) | Login form alert | "The access code is not valid." |
| `workspace_code_required` (401) | Token cleared, login shown | "Your workspace session has ended. Enter the access code again." |
| `forbidden` (403) | Token cleared, login shown | "This access code does not open the workspace." |
| `report_not_ready` (409) | Inline at the PDF button | "The report is ready once the interview is finished." |
| `conflict` (409, delete) | Popup alert, view refetched | §19.7 delete rule 4 |
| `not_found` (404) | Popup or status | §19.4, §19.7 delete rule 5 |
| `invalid_value` (422, filters) | List alert | "That filter could not be used. Clear the filters and try again." |
| others | As part 1 §3.11 | — |

One helper `isSessionEnded(error)` (401 `workspace_code_required` or 403) is checked first by every workspace query and mutation (`onError`), so the rule lives in one place.

### 19.10 Fake API additions (`services/fakeApi.ts`, `services/fakeData.ts`)

| # | Behaviour |
|---|---|
| 1 | `workspaceLogin(code, name)`: code `demo-specialist` → specialist token `fake.specialist`, `demo-engineer` → engineer token, anything else → 401 `workspace_code_invalid`; `expiresAt` 8 h ahead. Name checked 1–40 characters (422 `invalid_value`) |
| 2 | Workspace calls check the token like the server: none or unknown → 401 `workspace_code_required`, engineer → 403 `forbidden` |
| 3 | **Seeded sessions** (`fakeData.WORKSPACE_SEED`), added to the fake's own interview sessions: (a) finished "Monthly cost review", FIN, Europe, 5 steps, with `euReport`, documents, and a `rawSteps` grid that differs in step 2's name and one cell; (b) finished "Supplier invoice check", another cluster, `rawSteps: null`; (c) active, phase `steps`, no report; (d) active, no process name yet, 4 messages; (e) `no_candidate`. Each has a short scripted conversation (6–12 messages, (a) about 30) |
| 4 | `reviewList(filters)` applies status, cluster and `q` (case-insensitive on process name, department, id) like spec 21 §3.2, sorts by `updatedAt` newest first, returns counts before filters, `matching`, `truncated: false`; `q` over 100 characters → 422 `invalid_value` |
| 5 | `reviewSession(id)` builds the summary, grids and documents from the fake session; `report` = the fake report for finished sessions, else `null`; returns an `etag` that changes on every write |
| 6 | `reviewConversation(id)` returns the stored messages; `getReviewReportPdf(id)` returns `FAKE_PDF` for finished sessions, else 409 `report_not_ready`; `deleteReviewSession(id, etag)` checks the etag (stale → 409 `conflict`), removes the session (so Home no longer lists it) and keeps ideas |
| 7 | **Manual triggers** through the search box (the text is not sent as a filter): `/error <code>` fails the next workspace call with that code; `/expire` makes the next call 401 `workspace_code_required`; `/touch <id>` changes that session's etag (to try the delete conflict) |
| 8 | Tests construct the fake with `createFakeApi({workspaceSeed, delayMs: [0, 0]})`; fixtures in `src/test/fixtures/workspace.ts` are shared by the fake and the tests |
| 9 | *(Amended 2026-11-20 (open workspace).)* `createFakeApi({workspaceOpen: true})`: `getConfig` returns `workspaceOpen: true`, `workspaceLogin` ignores the code and gives a specialist token for any valid name, `deleteReviewSession` returns 403 `forbidden` "Deleting is switched off on this open demo.". Default `false` |

## 20. Interfaces (part 3)

**API calls added** (camelCase; `Authorization: Bearer <token>` on all but login; never `X-Visitor-Key`):

| `DiscoveryApi` method | Route | Request | Response |
|---|---|---|---|
| `workspaceLogin(code, name)` | `POST /api/workspace/login` | `{code, name}` | `LoginOut {token, role, name, expiresAt}` (spec 16, built) |
| `reviewList(filters)` | `GET /api/review/sessions?status&cluster&q` | empty filters omitted | `ReviewListOut` |
| `reviewSession(id)` | `GET /api/review/sessions/{id}` | — | `ReviewSessionOut` (`etag` in the body; the `ETag` header is not read) |
| `reviewConversation(id)` | `GET /api/review/sessions/{id}/conversation` | — | `ConversationOut` |
| `getReviewReportPdf(id)` | `GET /api/review/sessions/{id}/report.pdf` | — | `{blob, filename}` |
| `deleteReviewSession(id, etag)` | `DELETE /api/review/sessions/{id}` | header `If-Match: <etag>` | 204 |

`createHttpApi(getKey, getToken)` gains the second getter (`readWorkspaceToken()?.token`), read per request like the visitor key. A workspace call made without a token fails locally with `ApiError(401, 'workspace_code_required')` and sends nothing. `request()` gains an `auth` option (bearer) and an `ifMatch` option; the PDF fetch shares one `fetchBlob(path, headers)` helper with part 2's `getReportPdf`.

**Types in `types/workspace.ts`** (mirror of spec 21 §4.2; *to confirm against spec 21* — reconcile with `backend/app/models/workspace_wire.py` once built; the server's names win):

```ts
type ReviewStatusFilter = 'active' | 'finished' | 'no_candidate'
interface ReviewFilters { status: ReviewStatusFilter | null; cluster: string | null; q: string }
interface ReviewRow { id: string; createdAt: string; updatedAt: string; processName: string | null;
  department: string | null; clusterCode: string | null; clusterName: string | null; region: string | null;
  status: SessionStatus; phase: Phase; fieldsFilled: number; fieldsTotal: number;
  steps: number; messageCount: number; documentCount: number }
interface ReviewCounts { total: number; active: number; finished: number; noCandidate: number }
interface ReviewListOut { counts: ReviewCounts; rows: ReviewRow[]; matching: number; truncated: boolean }
interface ReviewSummary { department: string | null; function: string | null; region: string | null;
  processName: string | null; clusterName: string | null; status: SessionStatus; phase: Phase;
  fieldsFilled: number; fieldsTotal: number; stepsStarted: number; stepsExpected: number;
  completeness: number; filledPoints: number; totalPoints: number; messageCount: number; documentCount: number }
interface GridCell { value: unknown; source: 'expert' | 'document' | 'specialist' | null; status: FieldStatus | null }
interface GridRow { key: string; id: string; label: string; cells: GridCell[] }   // one cell per step
interface StepGrid { stepNames: string[]; rows: GridRow[] }
interface DocumentMeta { name: string; kind: string; bytes: number; uploadedAt: string; outcome: 'read' | 'failed' }
interface ReviewSessionOut { id: string; etag: string; summary: ReviewSummary; steps: StepGrid;
  rawSteps: StepGrid | null; documents: DocumentMeta[]; report: DiscoveryReport | null }
interface ConversationOut { sessionId: string; messages: Message[] }
interface WorkspaceLogin { token: string; role: 'specialist' | 'engineer'; name: string; expiresAt: string }
```

`bytes` is typed but never shown. `wireGuards.ts` gains `isReviewListOut` and `isReviewSessionOut` (top-level keys only); a failed guard is a page error with the fallback sentence; `report` is checked with the part 2 `isDiscoveryReport`, and a bad report is treated as `null` plus a warning note.

**Component tree**

```
pages/Workspace.tsx                               readWorkspaceToken, useQuery(['workspace','sessions',filters])
├── layout/AppHeader                              "Signed in as …" · Refresh · Log out · theme
├── workspace/WorkspaceLogin                      code + name form
├── workspace/SessionFilters                      status, cluster (taxonomy), search
├── workspace/SessionTable                        counts line, table, empty states
└── workspace/SessionDialog (ui/Modal size xl)    useQuery(['workspace','session',id])
    ├── ui/Tabs                                   Session · Conversation
    ├── workspace/SummaryCards
    ├── workspace/StepGrid                        Now / As first told toggle, utils/workspaceFormat
    ├── report/ReportPartBoundary ×4              reused (part 2)
    │   ├── report/StepAssessmentTable            reused
    │   ├── report/RecommendedRoute               reused
    │   ├── report/OpportunityList                reused
    │   └── report/ProcessMap                     reused (lazy Mermaid)
    ├── report/ReportNoteBox                      reused ("ready once finished")
    ├── workspace/ConversationView                chat/ChatMessageBubble reused (speaker, showDate props)
    └── footer: Delete (ui/Modal alertdialog) · Download (utils/downloadFile.saveBlob) · Close
access/workspaceToken.ts · types/workspace.ts · utils/workspaceFormat.ts
```

## 21. Implications (part 3)

- **Other components:** spec 21 routes and wire models are the contract; when they are built, `types/workspace.ts`, the guards and `src/test/fixtures/workspace.ts` are reconciled first (optionally from recorded samples in `backend/tests/fixtures/api/`, part 1 Q1). Part 2 report components gain one optional prop (`headingLevel`); `ChatMessageBubble` gains two optional props (`speaker`, `showDate`); `ui/Modal` gains size `xl`. Defaults keep the existing screens unchanged.
- **Data:** one new browser key, `pd_workspace` in `sessionStorage` (cleared when the tab closes, on log out, on 401 / 403). No other storage.
- **Config:** none. The access codes live on the server (spec 16); the fake's codes are fake-only.
- **Security and privacy:** the token is never put in a URL, a log or `localStorage`; the code is never stored. The conversation is fetched only on demand (each fetch is audited server-side). Document text is never requested or shown; bytes are not shown. Messages, quotes and report texts render as plain text (agent Markdown keeps part 1's safe renderer). The PDF is fetched with the bearer token and saved through a revoked object URL. Delete always sends the etag.
- **Cost and latency:** no model call from any workspace screen. The list is one call per filter change (debounced); the popup one call per open; Mermaid loads only when a finished session's popup opens.
- **Accessibility:** the table has a caption and header scopes and scrolls in a labelled focusable region; the row opener is a real button; the popup and the confirm follow part 1 dialog rules (focus in, Tab trapped, focus back to the trigger, one Escape closes only the top dialog); the version toggle uses `aria-pressed` and a visible disabled reason; status and cell status are text plus icon, never colour alone; both themes meet the part 1 contrast checks.

**Behaviours that must not be lost** (each has an AC):

| # | Behaviour |
|---|---|
| 28 | Nothing in the workspace edits a session; delete is the only write |
| 29 | Any 401 / 403 on a workspace call clears the token and returns to login |
| 30 | The conversation is fetched only when its tab is opened, once per popup |
| 31 | The PDF is fetched with the bearer token; delete sends `If-Match` |
| 32 | The list shows the server's order and counts; an error never reads as an empty list |
| 33 | The popup works for active sessions (no report) and the toggle is disabled without a first version |

## 22. Acceptance criteria (part 3)

| ID | Given / when / then |
|---|---|
| AC-23.106 | `/workspace` with no stored token shows the login form; with a valid stored specialist token it shows the list without asking again; with an expired or malformed stored token it removes it and shows the login |
| AC-23.107 | **Open workspace** is disabled with a blank code or name; a name over 40 characters cannot be typed |
| AC-23.108 | A specialist login stores `{token, role, name, expiresAt}` under `pd_workspace` in `sessionStorage` (never the code, never `localStorage`) and shows the list; the header shows "Signed in as <name>", **Refresh**, **Log out** and the theme toggle |
| AC-23.109 | An engineer login stores nothing and shows the engineer sentence; a 401 `workspace_code_invalid` shows "The access code is not valid.", clears and focuses the code field and keeps the name |
| AC-23.110 | With `sessionStorage` throwing, login still works for the tab (memory token) |
| AC-23.111 | `api.ts`: workspace methods use the method, path, query and headers of §20; they send `Authorization: Bearer <token>` and no `X-Visitor-Key`; expert calls send no `Authorization`; empty filters are omitted from the query; `deleteReviewSession` sends `If-Match`; a workspace call without a token fails with 401 `workspace_code_required` and makes no request |
| AC-23.112 | `getReviewReportPdf` returns the blob and the `Content-Disposition` file name, and `discovery-report.pdf` without the header |
| AC-23.113 | Given a 401 `workspace_code_required` or 403 `forbidden` on any workspace call (list, view, conversation, PDF, delete), the token is removed, the popup closes and the login shows the matching sentence |
| AC-23.114 | **Log out** removes the token and shows the login; the visitor key in `localStorage` is unchanged |
| AC-23.115 | While the list loads, "Loading sessions…" with `role="status"` shows; a failed list shows an alert with **Retry** (which refetches) and no table and no zero counts |
| AC-23.116 | With `counts.total = 0` the page shows "No discovery sessions yet."; with rows filtered to none it shows "No sessions match these filters." and **Clear filters** |
| AC-23.117 | The counts line shows total, in progress, mapped and ended from `counts`, adds "<matching> match the filters" only with a filter set, and the truncated sentence only with `truncated: true` |
| AC-23.118 | The table has the caption and the eleven columns of §19.3 in order, rows in server order, "Not named yet" for a null name, "—" for empty department, cluster and region, "<filled> / <total>" for fields |
| AC-23.119 | The status cell shows the status text (and the phase label for active rows) as text; no status is shown by colour alone |
| AC-23.120 | Choosing a status or cluster refetches with `status=` / `cluster=`; typing in Search refetches once 300 ms after the last key with the trimmed `q`; **Clear filters** removes all three; the cluster select lists the taxonomy as "<code> · <name>" and is disabled with only "All clusters" when the taxonomy fails |
| AC-23.121 | The Process button of a row opens the popup with Enter, Space and click; a mouse click elsewhere on the row also opens it; closing the popup returns focus to that button |
| AC-23.122 | The popup is a `dialog` labelled by the process name (or "Not named yet"), shows "Session <id> · Updated …", has the tabs Session and Conversation with Session selected, and closes with ×, **Close** and Escape |
| AC-23.123 | The popup calls `GET /api/review/sessions/{id}` once per open (StrictMode), shows "Loading the session…" while loading, "This session no longer exists." on 404, and the part 1 sentence with **Retry** on other errors |
| AC-23.124 | The summary shows four cards Context, Process, Scope, Measures, each an `<h3>` with a `<dl>` holding the values of §19.4 block 1, completeness as a whole percent, "—" for empty values |
| AC-23.125 | The step grid shows **Now** by default (`aria-pressed="true"`); **As first told** switches the table to `rawSteps` (caption and cells change) and back; with `rawSteps: null` it is disabled and the reason sentence is visible |
| AC-23.126 | Grid cells show the value formatted by `formatCell` and a muted line with the source and status words; a session with no steps shows "No steps yet."; the grid is a table with caption, header scopes and a focusable labelled scroll region; no cell is an input |
| AC-23.127 | `formatCell`: null, empty string and empty list give "—"; a string list gives one line per item; an object gives "key: value" lines; a list of objects gives numbered entries; `<img src=x onerror=alert(1)>` in a value is shown as text |
| AC-23.128 | The documents block lists name, kind word, upload date and outcome word, and renders no byte count and no document text; with no documents it is absent |
| AC-23.129 | For a finished session the popup renders the part 2 `StepAssessmentTable`, `RecommendedRoute`, `OpportunityList` and `ProcessMap` from `report` with `<h3>` headings; for an active session it shows only the "ready once the expert finishes" note instead |
| AC-23.130 | A report block whose part carries a failed note shows the warning note; a block that throws shows "This part could not be shown." and the rest of the popup still renders |
| AC-23.131 | Opening the Conversation tab calls `GET …/conversation` exactly once; switching tabs back and forth does not call it again; never opening the tab makes no call |
| AC-23.132 | The conversation shows the logged-notice line and every message in order as an `<ol>` labelled with the count, speakers "Expert" / "Agent" with date and time; agent Markdown renders safely, a `<script>` in a message is not executed or rendered as HTML; the interview page still labels the expert "You" |
| AC-23.133 | **Download report (PDF)** is disabled with the visible reason for active and ended sessions; for a finished session it calls `getReviewReportPdf` once, shows "Preparing PDF…", saves through `saveBlob` with the returned name, and shows errors inline (409 → the not-ready sentence) leaving the popup open |
| AC-23.134 | **Delete session** opens an `alertdialog` with the §19.7 text and **Cancel** focused; **Cancel** makes no call; one Escape closes only the confirm |
| AC-23.135 | Confirming calls `deleteReviewSession(id, etag)` with the loaded etag; on 204 both dialogs close, the list refetches, the deleted row is gone and "Session deleted." shows |
| AC-23.136 | On 409 `conflict` the confirm closes, the view refetches and the conflict sentence shows; a second delete sends the new etag. On 404 both close, the list refetches and "This session was already deleted." shows |
| AC-23.137 | While delete is in flight, its buttons are disabled, "Deleting…" shows and Escape is ignored |
| AC-23.138 | No workspace screen renders an input, button or action that changes a session other than delete (source scan of `components/workspace/` for `PUT`, `POST` and `PATCH` calls other than login: none) |
| AC-23.139 | Fake API: `demo-specialist` logs in, `demo-engineer` gives the engineer role, another code gives 401; the seed gives five sessions in `updatedAt` order with the counts of §19.10.3; filters behave as spec 21 §3.2; the finished seed has a report and a different `rawSteps`; PDF before finish is 409; delete with a stale etag is 409, with the right etag removes the session from both the workspace and Home |
| AC-23.140 | Fake triggers: `/error <code>` in Search fails the next workspace call with that code and is not sent as `q`; `/expire` makes the next call 401 and the page returns to login; `/touch <id>` makes the next delete of that session 409 |
| AC-23.141 | New components use theme tokens only (the AC-23.57 scan covers `components/workspace/` and `pages/Workspace.tsx`); the login, list and popup render in both themes, and the map in the popup follows the theme (part 2 rule) |
| AC-23.142 | Below 1024 px the summary cards stack (2 then 1 column), the list and the grid scroll sideways inside their regions with no page-wide horizontal scroll, and the header actions are icon buttons with `aria-label`s below 640 px |
| AC-23.143 | *(amended 2026-11-20 (open workspace))* With `workspaceOpen: true`, the login has no access-code field, shows "Open demo workspace: anyone with the link can read sessions. Deleting is switched off.", enables **Open workspace** with a name alone, and logs in (stores the specialist token, shows the list); with `workspaceOpen: false` the code field is there and AC-23.107 holds |
| AC-23.144 | *(amended 2026-11-20 (open workspace))* With `workspaceOpen: true`, the session popup renders no **Delete session** button (Download and Close remain); with `false` it does |
| AC-23.145 | *(amended 2026-11-20 (open workspace))* Fake API with `workspaceOpen: true`: config says so, any valid name logs in as specialist whatever the code, delete is 403 `forbidden`; `checkPublicConfig` requires `workspaceOpen` (boolean) |

## 23. Test plan (part 3)

| Test file | Covers |
|---|---|
| `src/access/workspaceToken.test.ts` | AC-23.106 (read, expiry, malformed), 23.108 (storage key, no code), 23.110 |
| `src/services/api.test.ts` | AC-23.111, 23.112 (stubbed `fetch`) |
| `src/services/fakeApi.test.ts` | AC-23.139, 23.140; `fakeApi.workspace.test.ts` and `contract.test.ts`: AC-23.145 |
| `src/utils/workspaceFormat.test.ts` | AC-23.127 and the words of §19.8 |
| `src/utils/discoveryErrors.test.ts` | §19.9 rows, `isSessionEnded` |
| `src/components/workspace/WorkspaceLogin.test.tsx` | AC-23.107, 23.109, 23.143 |
| `src/components/workspace/SessionTable.test.tsx` | AC-23.116–23.119, 23.121 (row opener) |
| `src/components/workspace/SessionFilters.test.tsx` | AC-23.120 (fake timers for the 300 ms debounce) |
| `src/components/workspace/StepGrid.test.tsx` | AC-23.125, 23.126 |
| `src/components/workspace/SessionDialog.test.tsx` | AC-23.122–23.124, 23.128–23.137, 23.144 (fake API through `ApiProvider`; Mermaid renderer stubbed; `saveBlob` stubbed) |
| `src/components/workspace/ConversationView.test.tsx` | AC-23.131, 23.132 |
| `src/pages/Workspace.test.tsx` | AC-23.106, 23.108, 23.113–23.115, 23.142 (login → list → popup → delete → list, against the fake) |
| `src/components/chat/chat.test.tsx` | AC-23.132 (interview page still shows "You") |
| `src/App.test.tsx` | `/workspace` renders the workspace page |
| Existing token scan and contrast tests | AC-23.138 (extra scan), 23.141 (paths extended) |

Fixtures: `src/test/fixtures/workspace.ts` holds `reviewList` (the five seed rows), `reviewSessionFinished` (with `euReport` and a differing `rawSteps`), `reviewSessionActive` (`report: null`, `rawSteps: null`), `conversationShort`, and a session view with structured cell values for `formatCell`. Tests use role and label queries and `user-event`. Manual check before marking built: `npm run dev:fake` (log in with both codes, filter, open each seed session in both themes, toggle the grid, open the conversation, download, delete, `/expire`, `/touch`), then `make dev` against the backend once spec 21 is built.

## 24. Out of scope (part 3)

| Item | Note |
|---|---|
| Editing fields or steps, provenance marks, re-running the assessment | Later (spec 21 §8) |
| Opportunity review, readiness notes, validation and the note to the expert | Later |
| Process overview across sessions (F-18), field coverage bars, KPI tiles beyond the counts line | Later |
| Implementation briefs and any engineer screen | Later; an engineer login only gets the "not available yet" sentence |
| Paging, column sorting, date / department / region filters, filters in the URL | Later |
| A deep link to one session's popup (`/workspace?session=<id>`) | Later (Q16) |
| Conversation search, copy or export; BPMN and Excel downloads | Not planned / spec 22 |
| Bulk delete | Not planned |
| Named sign-in (Entra ID) | Production readiness (spec 16 §8) |

## 25. Open questions (part 3)

| # | Question | Default until decided |
|---|---|---|
| Q14 | Spec 21 is a draft. Are the wire names of §20 (`fieldsFilled`, `stepsStarted`, `rawSteps`, `GridCell.source` values, `etag` in the body) final? | Follow spec 21 §4.2 as written; reconcile `types/workspace.ts` and fixtures with the built `workspace_wire.py` before the workspace tests are written; the server's names win |
| Q15 | Grid cell `value` is `Any` in spec 21. Should the server send a display string? | Ask spec 21 for a formatted string (code formats values, product rule 3 spirit); until then the client's `formatCell` (§19.6) |
| Q16 | Should the open popup be in the URL so the back button and a shared link work? | No: page state only. Revisit with the overview |
| Q17 | Should delete also be offered in each list row? | No: only in the popup, after the specialist has seen the session |
| Q18 | Should the counts line become tiles? | No: one text line; tiles come with the overview |
| Q19 | Should the conversation be opened from a separate route instead of a tab? | No: a tab in the popup, fetched on demand (one audit line per popup open) |
| Q20 | Part 2 Q11: show the specialist's validation note? | Not in part 3: validation is out of scope |
