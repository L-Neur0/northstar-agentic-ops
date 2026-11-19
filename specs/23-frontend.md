# 23 · Frontend, part 1: the interview side

> **Status:** part 1 approved · §3.13 theme approved · **Implements:** the screens of F-01, F-02, F-03 (honest exit), F-07 (cluster picker), F-08 (step tabs), F-10, F-11, F-21.1–2 (visitor key, resume link), F-23.4 (delete my data) (product); architecture §1 (two sides), §4 (frontend) · **Depends on:** specs 10 (toolchain), 12 (wire models), 13 (field views, *Finish*), 14 (turn), 15 part 2 (routes), 16 (visitor key)
> **Code:** `frontend/src/{main.tsx,App.tsx,pages,components,services,types,utils,hooks,access}` · **Tests:** next to each file (`*.test.ts[x]`), setup `frontend/src/test/setup.ts`
> **Part 2** (later in this file): document upload and proposals (✓ / ✎), the report screen, the workspace (review, overview, briefs).

## 1. Purpose

Give the expert three things in the browser: **My processes** (sessions, ideas, report status, resume link), the **interview page** (chat on the left, "Your process" on the right, phase meter on top), and the small dialogs around them. The screens show only what the server decides: phase, score, field status, *Finish* state. The client stores no profile logic and computes no completeness.

## 2. Where it sits

- **Side:** interview side of architecture §1 (`pages/Home.tsx`, `pages/ProcessDiscovery.tsx`, `components/process-discovery/`, `components/chat/`). The admin side and the report screen are part 2.
- **Exists today:** the spec 10 scaffold (one page calling `GET /api/health`), Vite + React 18 + TypeScript strict + Tailwind 3 + React Router 7 + React Query 5 + lucide-react + react-markdown/remark-gfm, Vitest + Testing Library + jsdom, the Vite proxy `/api` → `:8000`.
- **Changes:** `App.tsx` becomes the router; the scaffold page and its test are replaced. No backend file changes.
- **Look:** a plain neutral template. Title "Process Discovery", no logo, Tailwind colours (slate neutrals, one blue primary, green / amber / red for status), lucide icons, system font. No external UI kit.

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
2. `AppHeader` (`components/layout/`): a 56 px bar with a neutral `Search` icon, an `<h1>` "Process Discovery", and an actions slot on the right. Same component on every page.
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
| [Q] Process Discovery                                  [+ Start a new interview] |  AppHeader
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
| [Q] Process Discovery        [i How this works] [History Past sessions] [+ New] [My processes] |
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

9. **`SubstepTabs`**: header "Steps <complete>/<N>" (N = P16, else rows). One tab per row, `Step k (f/11)` where f counts S01–S11 views of step k with status `complete` (keys `process.substeps[k].<leaf>`, **1-based**). Tabs follow the WAI-ARIA tabs pattern (`role="tablist"`, roving `tabindex`, arrow keys), scroll horizontally, and the active tab scrolls into view. The tab panel shows "Step k · <name>" and the twelve cell rows; S12 shows "(not scored)". No rows yet → "The steps appear here once you start describing them."
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
| AC-23.6 | Routes: `/`, `/process-discovery`, `/process-discovery/:id`, `/report/:id` render their pages; an unknown path redirects to `/`; every page shows the header "Process Discovery" and no logo |
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
| AC-23.33 | `SubstepTabs` shows `Step k (f/11)` from the 1-based field views, marks S12 "(not scored)", supports arrow keys between tabs, and the active tab is the first unsettled step until the expert clicks a tab |
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
| Q6 | Fixed title or the product name from `GET /api/config`? | Fixed title "Process Discovery" |
