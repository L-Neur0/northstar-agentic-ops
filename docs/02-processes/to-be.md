# To-be process: planning and pricing a bid with BidCheck

> The future process, step by step, on the same example as [as-is.md](as-is.md). Summary and motivation: [the use case](../01-use-case/use-case.md) §2.2. The story version: [user-journey.md](user-journey.md).
> **Done by:** **AI** = the language model reads or labels text · **Code** = plain, tested code · a role name = a person.
> **Level:** 0 people only · 1 tool suggests · 2 tool does it, a person approves · 3 fully automated.

## 1. What changes, in one table

| # | Step | Today | With BidCheck | Skilled time: today → with BidCheck |
|---|---|---|---|---|
| 0 | Keep the history *(new, background)* | Not done | Past projects and past tenders kept in one standard format, labelled by AI, checked by people | — → ~1 h/month |
| 1 | Tender | Read 200 pages by hand | BidCheck lists the key facts, with pages; the bid manager confirms | 2–3 h → 15 min |
| 2 | Go / no-go | Meeting | **Unchanged** | 1–2 h → 1–2 h |
| 3 | Plan | Engineers plan; the work around the drawings is guessed | Engineers plan; **BidCheck checks the plan** against ~10 truly similar projects; every gap is fixed or explained | 15–20 h → 8–12 h |
| 4 | Price | Hours cut to match a rumoured competitor price | **Price view**: margin, chance of a loss, past winners and expected score at each price | 2–3 h → 1 h |
| 5 | Approve | Pack built by hand, no evidence | Pack generated with evidence | 4–6 h → ~1 h |
| 6 | Submit, and afterwards | Real hours and tender results never come back | They flow back to step 0 | unchanged |
| | **Estimating work per bid** | | | **~25–35 h → ~10–14 h** |

## 2. Sub-steps

### Step 0 — Keep the history (monthly, in the background)

Everything ends in **one standard format**: *projects* (type, size, conditions, contract, original estimate) · *hours* (project × phase × role) · *tenders* (NIG's price, result, winner, winning price, scores, weights) · *evidence* (source document and quote for every label).

| # | Sub-step | Done by | Input / data | Output | Level | Time |
|---|---|---|---|---|---|---|
| 0.1 | **Path A** — region has a clean project database: read it through a fixed mapping | Code | Clean database | Projects, hours on standard phases | 3 | — |
| 0.2 | **Path B** — region has only exports: load finished projects and their documents | Code | Timesheet exports (hours per task code and role), proposals, final reports | Raw records | 3 | — |
| 0.3 | Map each project's task codes to the standard phases (*"DD-PROC"* → *Detailed design*) | AI | Task codes and their descriptions | Mapping + confidence | 2 | — |
| 0.4 | Label each project's conditions (*old plant kept running*, *empty site*, *strict regulator*) | AI | Proposal / scope text | Labels + source quote + confidence | 2 | — |
| 0.5 | Extract the reasons for overruns | AI | Final reports | Reasons + quotes | 2 | — |
| 0.6 | Load past tenders: read award notices and feedback letters (winner, winning price, quality and price scores, reasons) | Code + AI | Bid register, award notices, feedback letters | Tender records + quotes | 2 | — |
| 0.7 | Validate: schema, every quote exists in its document, confidence above threshold | Code | All of the above | Accepted records / review queue | 3 | — |
| 0.8 | Review the uncertain items | Finance analyst (projects) · bid manager (tenders) | Review queue | Approved labels and mappings, saved and reused | 0 | ~1 h/month |

### Step 1 — Tender

| # | Sub-step | Done by | Input / data | Output | Level | Time |
|---|---|---|---|---|---|---|
| 1.1 | Spot the tender, share it | Client director | Tender portal | Tender documents | 0 | 0.5 h |
| 1.2 | Create the bid in BidCheck; upload the tender; add client, region, contract type | Bid manager | Tender PDF | New bid workspace | 0 | 5 min |
| 1.3 | Pull out the key facts: size (*20 million litres/day*), conditions (*old plant must keep running*, *town reviews each design stage*), budget (*up to €700k*), scoring rules (*quality 70%, price 30%; lowest price ÷ your price × 30*), deadlines | AI | Tender PDF | Key facts, each with page and quote | 2 | ~1 min |
| 1.4 | Check every quote really exists on its page | Code | Key facts + tender | Checked facts | 3 | seconds |
| 1.5 | Confirm or correct the facts | Bid manager + technical lead | Checked facts | **Confirmed key facts** | 0 | 10–15 min |
| 1.6 | Send clarification questions to the client | Technical lead + bid manager | Key facts | Questions and answers | 0 | 0.5 h |

### Step 2 — Go / no-go (unchanged)

| # | Sub-step | Done by | Input / data | Output | Level | Time |
|---|---|---|---|---|---|---|
| 2.1 | Decide whether to bid | Client director + bid manager | Confirmed key facts, client relationship, team availability | Decision: **bid** | 0 | 1–2 h |

BidCheck gives no bid/no-bid advice: that would be lead qualification, which the brief excludes. The workspace's plan and price tabs open only after this decision.

### Step 3 — Plan

| # | Sub-step | Done by | Input / data | Output | Level | Time |
|---|---|---|---|---|---|---|
| 3.1 | Make the plan as today: phases, deliverables, hours per phase and role | Technical lead + discipline leads | Key facts, experience | **Team's plan: 6,000 h** (Excel) | 0 | 6–10 h |
| 3.2 | Load the plan into BidCheck | Technical lead | Excel file (phase, role, hours) or typed in the grid | Plan in the workspace | 0 | 5 min |
| 3.3 | Find similar projects: filter on type, size band, conditions, region; rank; say why each one matches (minimum 5) | Code | Confirmed key facts + project history | **10 similar projects** of 140 (Eastbrook in; Oakridge out: *"new plant on an empty site"*) | 2 | seconds |
| 3.4 | Check the list; remove or add projects | Technical lead | Similar projects + reasons | Final list | 0 | 15 min |
| 3.5 | Compare the plan with the similar projects, phase by phase: their real hours per size unit → low / typical / high, scaled to Millbrook; flag every phase below the range | Code | Team's plan + final list | **Plan check**: 2 flags (town reviews 400 h vs 650–850 h; keeping the old plant running 200 h vs 400–650 h); total 6,000 h vs 6,200–7,600 h | 3 | seconds |
| 3.6 | Explain each flag: why similar projects needed more, quoting their final reports (quotes checked) | AI + code | Evidence from step 0 | Reasons per flag | 2 | seconds |
| 3.7 | Close every flag: fix the hours, or write why this project is different | Technical lead + discipline leads | Plan check + reasons | **Checked plan: 6,600 h** (both flags fixed) | 0 | 1–2 h |

### Step 4 — Price

| # | Sub-step | Done by | Input / data | Output | Level | Time |
|---|---|---|---|---|---|---|
| 4.1 | Calculate the cost if the project goes like similar ones: typical and high | Code | Similar projects' hours + rate card | Cost: €544k typical (6,800 h) · €608k high (7,600 h) | 3 | seconds |
| 4.2 | Add the prices to compare: client budget, rumoured competitor price, NIG's target margin | Commercial manager | Budget (from step 1), market knowledge | Candidate prices: €550k · €600k · €640k · €700k | 0 | 10 min |
| 4.3 | For each price: margin (typical and high) and **chance of a loss** (share of similar projects that would have lost money at that price) | Code | Costs + candidate prices | Margin table (€550k → 1%, 4 in 10 lose money; €640k → 15%, 0 in 10) | 3 | seconds |
| 4.4 | **Competitor panel**: who won similar tenders, how often, at what price, under which scoring weights | Code | Tender history | NIG 6 wins (€610–650k), Riverton 4 (€560–600k, when price weighs 40%+), BlueLine 3 (€620–660k) | 3 | seconds |
| 4.5 | **Expected score** at each price, using the tender's formula and typical quality scores from past feedback letters | Code | Scoring rules + competitor panel | Score per price (€640k → 88.3, best expected score) | 3 | seconds |
| 4.6 | Choose the price and record why | Commercial manager + client director | Price view | **€640k** — *"we win on quality, 70% of the score"* | 0 | 0.5 h |

### Step 5 — Approve

| # | Sub-step | Done by | Input / data | Output | Level | Time |
|---|---|---|---|---|---|---|
| 5.1 | Generate the approval pack: key facts, similar projects, plan and every flag with its fix or reason, price view at the chosen price, competitor panel | Code (+ AI for a one-paragraph summary written from the numbers) | Everything above + audit log | Approval pack (PDF) | 3 | seconds |
| 5.2 | Review with evidence and decide | Directors | Approval pack | **Approved** | 0 | ~1 h |

### Step 6 — Submit, and afterwards

| # | Sub-step | Done by | Input / data | Output | Level | Time |
|---|---|---|---|---|---|---|
| 6.1 | Export the plan to NIG's estimate template; submit | Code + bid manager | Approved offer | Offer sent | 2 | 0.5 h |
| 6.2 | Record the tender result when it is published (won or lost, winner, price, scores) | Code + bid manager | Award notice, feedback letter | Updated tender history | 2 | — |
| 6.3 | If won: the plan becomes the budget, set up on the **standard phases** | Project manager | Checked plan | Budget comparable with other projects | 2 | — |
| 6.4 | When the project ends: real hours and final report flow back to step 0 | Code | Project system | Updated project history | 3 | — |

## 3. Rules BidCheck enforces

1. **The AI never produces a number.** It reads and labels; every number comes from code and past data.
2. **Every fact, label and reason shows its source**, and code checks the quote exists.
3. **No evidence, no comparison:** fewer than 5 similar projects → the tool says "not enough evidence" instead of guessing.
4. **People own the plan and the price.** Every flag is closed with a fix or a written reason.
5. **Only after go/no-go; no contract-clause review; history, not predictions** of competitors' prices.
6. **Everything is logged:** every edit, who made it, and why.

## 4. Data: what the process uses, and what we generate for the prototype

NIG's real data is not available, so the prototype runs on **fictional data from a seeded generator**, realistic enough to **expose the hard parts**. Formats and generator design: [the use case](../01-use-case/use-case.md) §4.5.

| Data | In production, comes from | In the prototype (generated) | Hard parts built in |
|---|---|---|---|
| **Project history — Path A** | A clean regional database | ~250 projects on the standard phases (SQLite/CSV) | Outliers; missing phases |
| **Project history — Path B** | Timesheet exports + documents | ~350 projects, each with **its own task codes** and local role names (CSV) + proposal and final report per project | Messy codes; conditions only in text; vague or silent reports |
| **Tender history** | Bid register, award notices, feedback letters | ~300 past tenders (CSV) with 3 invented competitors + short notices and letters | Missing prices or scores; varied letter formats |
| **Built-in patterns** | — | *Old plant kept running* → more hours on reviews, phasing and site support; low bidders win when price weighs more; original estimates too low on the work around the drawings | Makes the backtest meaningful: the check should catch what people missed |
| **New tenders** | Tender portals | Millbrook + 4 others (one with too little history) as ~15-page PDFs | Key sentence buried deep; a case where the tool must say "not enough evidence" |
| **Team's plan** | Excel | Millbrook plan, 6,000 h (`.xlsx`) | Low exactly where similar projects ran over |
| **Rate card, standard phases** | Finance, estimating standard | CSV, YAML | — |
| **Ground truth** (evaluation only) | — | The generator's hidden facts (JSON), kept apart | Measures reading accuracy, mapping accuracy and the backtest |
