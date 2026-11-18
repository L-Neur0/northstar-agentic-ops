# As-is process: planning and pricing a bid today

> The current process, step by step, on one example. Summary and context: [the use case](../01-use-case/use-case.md) §1 and §2.1. Future process: [to-be.md](to-be.md).
> Labels: **[model]** = public filings of the listed engineering company NIG is modelled on · **[industry]** = industry sources · **[assumption]** = ours, to validate.

## 1. The example: the Millbrook tender

> **Millbrook** (40,000 people) publishes a tender: *"Design a new drinking-water treatment plant, 20 million litres a day. The old plant must keep supplying the town until the new one is ready. Estimated value: up to €700k. Offers scored 70% on quality, 30% on price. Due in 6 weeks."*

- **NIG's job if it wins:** design the plant (drawings, calculations, specifications), get it approved, support the builder during construction.
- **Contract:** fixed price — if the project needs more hours than planned, NIG pays for them.

## 2. Who is involved

| Role | Who | Job in this process |
|---|---|---|
| **Client director** | Business development | Spots the tender; pushes to bid |
| **Bid manager** | Professional organiser of offers | Runs the plan and deadline; builds the approval pack; submits |
| **Technical lead** | Senior engineer, future project manager | Reads the tender; plans the work; owns the hours |
| **Discipline leads** (3–4) | Process, civil/structural, mechanical, electrical | Estimate the hours for their part |
| **Finance analyst** | Project controls, shared-services hub | Pulls hours of past projects, **when asked** |
| **Commercial manager** | Pricing specialist | Turns hours into a price; checks contract risks |
| **Approvers** | Regional director + finance director | Approve price and margin |

## 3. The process at a glance

| # | Step | Main owner | Output | Skilled time |
|---|---|---|---|---|
| 1 | Tender | Technical lead | Key facts (in someone's head) | 3–4 h |
| 2 | Go / no-go | Client director | Decision: bid | 1–2 h |
| 3 | Plan | Technical lead + discipline leads | **6,000 hours** per phase and role | 15–20 h |
| 4 | Price | Commercial manager | Offer: **€550k** (hours cut to 5,000) | 2–3 h |
| 5 | Approve | Approvers | Approved, at a "27% margin" | 4–6 h |
| 6 | Submit | Bid manager | Offer sent; if won, 5,000 h become the budget | ~1 h |
| | **Total** | **6–10 people, 1–3 weeks** | | **~25–35 h** |

## 4. Sub-steps

### Step 1 — Tender

| # | Sub-step | Who | Input / data | Tool | Output | Time | Pain / manual work |
|---|---|---|---|---|---|---|---|
| 1.1 | Spot the tender, share it with the team | Client director | Public tender portal | Portal, email | Tender documents (~200 pages) | 0.5 h | — |
| 1.2 | Read the tender: scope, contract, scoring rules, budget | Technical lead | Tender documents | PDF | Notes | 2–3 h | Long reading; the sentences that drive the work (e.g. *"the old plant must keep supplying the town"*, p. 47) are easy to miss |
| 1.3 | Send clarification questions to the client | Technical lead + bid manager | Notes | Portal | Questions and answers | 0.5 h | — |

### Step 2 — Go / no-go

| # | Sub-step | Who | Input / data | Tool | Output | Time | Pain / manual work |
|---|---|---|---|---|---|---|---|
| 2.1 | Decide whether to bid: chance of winning, available people, risk | Client director + bid manager (+ a senior leader) | Notes, client relationship, team availability | Meeting | Decision: **bid** | 1–2 h | A business judgement — out of scope for the tool |

### Step 3 — Plan

| # | Sub-step | Who | Input / data | Tool | Output | Time | Pain / manual work |
|---|---|---|---|---|---|---|---|
| 3.1 | Set up the phases in the estimate template | Technical lead | Tender notes | Excel template | Empty plan: phases × roles | 1 h | — |
| 3.2 | Count the deliverables and estimate their hours | Discipline leads | Tender notes, experience | Excel, email | ~120 drawings, ~30 calculations → design hours | 6–10 h (all leads) | Done reasonably well |
| 3.3 | Look for similar past projects | Technical lead | Memory, colleagues | Email, Teams | 1–2 projects he remembers (e.g. *Oakridge*) | 1–2 h | Only finds projects he knows; Oakridge was built on an empty site — not similar |
| 3.4 | Ask finance for the real hours of similar projects | Finance analyst | Project system: 140 projects of type *"Water – treatment"* | Project system, Excel | Hours of the 1–2 named projects — if time allows | 0–6 h | To know which projects are really similar, she must open their proposals; to compare hours, regroup each project's own task codes by hand. Days of work, so usually skipped |
| 3.5 | Estimate the work around the drawings: town reviews, permits, keeping the old plant running, construction support | Technical lead | Experience, the remembered project | Excel | % or allowance per phase | 1–2 h | **Guessed** — this is where overruns happen |
| 3.6 | Add up hours per phase and role | Technical lead | All of the above | Excel | **6,000 hours** | 2 h | Manual consolidation of several spreadsheets |

### Step 4 — Price

| # | Sub-step | Who | Input / data | Tool | Output | Time | Pain / manual work |
|---|---|---|---|---|---|---|---|
| 4.1 | Apply hourly rates per role, add a 10% buffer | Commercial manager | Plan (6,000 h), rate card | Excel | **€660k** | 0.5 h | — |
| 4.2 | Compare with the market: client budget €700k; "Riverton will bid ~€550k" | Commercial manager + client director | Budget, hearsay about competitors | Meeting | Target price: €550k | 0.5 h | Competitors known only by rumour; nobody checks who really won similar tenders, at what price, or how they were scored |
| 4.3 | Cut hours to reach the target | Commercial manager + technical lead | Plan | Excel | **5,000 hours → €550k** | 1–2 h | Hours are cut to fit a price, with no way to see which cuts are risky; every change means editing spreadsheets by hand |

### Step 5 — Approve

| # | Sub-step | Who | Input / data | Tool | Output | Time | Pain / manual work |
|---|---|---|---|---|---|---|---|
| 5.1 | Build the approval pack: scope, plan, price, margin, risks | Bid manager | Spreadsheets, notes | PowerPoint | Approval pack | 3–4 h | Assembled by hand |
| 5.2 | Review and approve | Approvers | Pack: cost 5,000 h × €80 = €400k → margin **27%** | Meeting | **Approved** | 1–2 h | No evidence to challenge the hours — the margin looks healthy because it is calculated on the cut hours |

### Step 6 — Submit, and afterwards

| # | Sub-step | Who | Input / data | Tool | Output | Time | Pain / manual work |
|---|---|---|---|---|---|---|---|
| 6.1 | Submit the offer (technical + price) | Bid manager | Final offer | Tender portal | Offer sent | ~1 h | — |
| 6.2 | If won: the plan becomes the project budget | Project manager | 5,000 h plan | Project system | Budget, task codes set up for this project | — | Each project sets up its own task codes, so it can't be compared with others later |
| 6.3 | When the project ends: book the real hours, write a close-out report | Project manager | Timesheets | Project system, Word | Real hours, close-out report | — | Nobody feeds them back into the next estimate |

## 5. The numbers

**The plan, by phase**

| Phase | Planned | After the cut | Really needed |
|---|---|---|---|
| Study & concept | 800 h | 800 h | 900 h |
| Detailed design | 3,000 h | 2,600 h | 3,100 h |
| Town reviews & permits | 400 h | 300 h | 700 h |
| Keeping the old plant running | 200 h | 100 h | 500 h |
| Construction support | 1,600 h | 1,200 h | 1,600 h |
| **Total** | **6,000 h** | **5,000 h** | **6,800 h** |

The countable work (drawings, calculations) was close; the work around it — reviews, permits, keeping the old plant running — was underestimated by more than half.

**The planned hours, by role** (price per hour = what the client pays; cost per hour = what it costs NIG)

| Role | Hours | Price per hour | Amount |
|---|---|---|---|
| Project director | 200 | €180 | €36,000 |
| Project manager | 500 | €140 | €70,000 |
| Senior engineer | 1,200 | €120 | €144,000 |
| Engineer | 2,300 | €95 | €218,500 |
| Drafter (CAD) | 1,800 | €75 | €135,000 |
| **Total** | **6,000 h** | **~€100 average** | **~€600k** + 10% buffer ≈ **€660k** |

Average cost to NIG: **~€80 per hour** (salary + overheads). [assumption]

**What the directors approved vs what really happened**

| | Approved | Real |
|---|---|---|
| Price (fixed) | €550k | €550k |
| Hours | 5,000 | 6,800 |
| Cost (× €80/h) | €400k | €544k |
| **Margin** | **€150k (27%)** | **€6k (1%)** |

NIG had already done **10 similar projects** — water plants where the old plant had to keep running — and they needed **6,200–7,600 hours**. The answer was in NIG's history; nobody had time to find it.

## 6. Pain points, in short

1. **Reading the tender (1.2):** hours of reading; key sentences easy to miss.
2. **Finding and comparing past projects (3.3–3.4):** the biggest manual job — days of searching, reading and regrouping — so it's skipped.
3. **Guessing the work around the drawings (3.5):** where overruns happen.
4. **Pricing blind (4.2–4.3):** hours cut by hand to match a rumoured competitor price, with no view of which cuts are risky or what really won similar tenders.
5. **Building the approval pack (5.1):** by hand, with no evidence behind the numbers.
6. **No learning loop (6.2–6.3):** real hours and tender results never come back; each project's own task codes make comparison hard.

## 7. NIG-wide figures

| Figure | Value | Basis |
|---|---|---|
| Net service revenue | ~€7B / year | [model] |
| Contract mix: fixed price / cost-reimbursable with ceiling / guaranteed maximum price | 25% / 38% / 37% | [model] |
| Win rate on bids | ~45% | [industry] |
| Significant bids (fee > €250k) per year | ~5,000 | [assumption] |
| Skilled time per bid | ~25–35 h, 6–10 people | [assumption] |
| Weight of price in UK/EU public tender scores | 25–40% | [industry] |
| Margin lost to underestimated hours | ~€55M / year (~40% of €7B where NIG pays for overruns × ~2%) | [assumption] |

## Sources

- How fees are built: [AIA – Setting fees](https://www.aia.org/sites/default/files/2025-12/AIA_BestPractices_Settingfees-Whattoconsider.pdf) · [Monograph – fee estimating](https://monograph.com/blog/architectural-engineering-fee-estimating-guidelines) · [Factor – cost estimation for A/E](https://factorapp.com/blog/project-cost-estimation-ae-firms) · [Total Synergy – fee proposals](https://totalsynergy.com/?p=13285)
- Win rates and proposal effort: [Unanet – AEC firms win ~50% of bids](https://unanet.com/blog/half-the-battle-why-aec-firms-are-only-winning-50-of-bids) · [OpenAsset – State of Proposals 2024](https://openasset.com/wp-content/uploads/2024/10/OpenAsset-The-2024-State-of-Proposals-in-AEC-Marketing.pdf) · [Deltek Clarity 2025](https://www.deltek.com/en/about/media-center/press-releases/2025/what-the-46th-annual-deltek-clarity-ae-study-reveals-about-the-industry)
- US public negotiation of hours: [FHWA – consultant agreement costs](https://www.fhwa.dot.gov/construction/reviews/revag1.cfm) · [Wisconsin DOT – hours by task](https://www.wisconsindot.gov/rdwy/fdm/fd-08-10.pdf)
- UK public tenders (price/quality weights): [75/25 framework](https://www.find-tender.service.gov.uk/Notice/004771-2021/PDF) · [70/30 framework](https://www.find-tender.service.gov.uk/Notice/031035-2021/PDF) · [60/40 Scotland Excel](https://www.find-tender.service.gov.uk/Notice/001602-2024/PDF)
- Brownfield upgrades ("staying online"): [WSP](https://www.wsp.com/en-nz/insights/making-ageing-wastewater-infrastructure-fit-for-the-future)
