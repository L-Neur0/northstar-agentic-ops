# Executive summary deck: outline

> **Status:** v7, built as `deck.html` / `deck.pdf`, 2026-11-21 (slide 3 renamed "AI use case discovery"; why it scales on slides 4–5; report v2 on slides 5–6; Microsoft 365 evidence and honest status on slide 9) · **Numbers from:** [`docs/01-use-case/use-case.md`](../01-use-case/use-case.md) · **Output:** one HTML deck (16:9) → PDF
> **Reader:** an NIG executive with five minutes, who has seen nothing else and has been burned by AI hype. It must stand alone and cover **business value, ROI, risks, costs and rollout** (brief, task 4).
> **Rules:** max **10 slides** · one idea per slide · the title is the conclusion · the goal and the value are impossible to miss · concrete numbers, every assumption marked.
> **Name:** AI Use Case Discovery Agent (renamed 2026-11-21 from "Discovery Agent"; "the Discovery Agent" is fine as a short form in titles).

---

## 1. The story in six lines

1. **Context:** NIG wants AI across its operations but can't do everything; past programmes failed on fragmented data and processes that differ everywhere.
2. **Task:** pick one specific, painful workflow from one of the nine clusters and prove it with working software.
3. **How I chose:** a fixed set of criteria: pain, business value, scalability, no tool on the market, no data project, low risk.
4. **The pick (IT cluster): AI use case discovery.** How IT finds, maps, assesses and selects the workflows worth transforming with AI: the AI transformation team's own workflow. Manual, painful, done hundreds of times a year, and every AI build depends on it.
5. **Why it scales:** today specialists interview people one by one, so discovery is capped by the AI team's size. The agent interviews every employee at the same time; specialists review the best candidates instead of collecting them.
6. **The result:** it pays back twice. The AI team: 24 → 1.5 person-hours per process, €0.45–0.68M a year for a €100k build *(updated 2026-11-21 (estimated effort: ~1.5 h per process, an assumption))*. NIG: a fast funnel, so more and better-chosen processes get automated, each with its own return. An 8-week pilot decides whether it lives.

---

## 2. The ten slides (as built in `deck.html`, v5)

| # | Title | Main visual |
|---|---|---|
| 0 | **AI Use Case Discovery Agent** · *Know which processes AI should take over, without weeks of workshops* | Title and problem only; animated process-map motif |
| 1 | NIG wants AI across its operations, but it has to start with one workflow | 9 × 4 cluster-region grid, why past programmes stalled, the task and its limits |
| 2 | To choose one workflow, I ask seven questions | Two groups. **The process:** ① manual and painful ② worth it (ROI) ③ scales ④ data ready. **The AI:** ⑤ AI or plain software ⑥ already solved (product, ChatGPT, Copilot) ⑦ the risk. Each tile: number left, icon right, one ✓ and one ✕ example. A connector runs under all seven into "Seven yeses? Then it's worth building" |
| 3 | The winner: AI use case discovery. *How IT finds, maps, assesses and selects the workflows worth transforming with AI.* (footer: seven questions, seven yeses) | Intro row first: *I know this work* · *Built for real use*. Then the workflow in 5 steps (find → map → measure baseline → assess AI potential and readiness → select the best and hand them to AI engineers). Then seven green tiles, each with ✓: the question, one big answer, a one-line unit and a short plain explanation (ROI tile shows the formula and the payback maths: €0.45M+, 22.5 h saved per process, paid back in ~3 months; *updated 2026-11-21 (estimated effort: ~1.5 h per process, an assumption)*). No "all yes" box; framework score in the footer |
| 4 | Today, mapping one process for AI takes 24 person-hours and 2–3 weeks | One-sentence lead on what happens; as-is swimlane with plain step names and hours (= 24 h: one 4-hour workshop with 2 AI specialists and 2 employees = 16 h, plus about a day of desk work = 8 h), week axis; four pain points, each a short headline and one plain sentence; the lead and pain 1 say discovery is capped by the AI team's size (one by one) |
| 5 | The AI Use Case Discovery Agent turns what employees know into a baseline the AI team can act on | Lead: the agent interviews every employee at the same time, specialists review instead of collect, from a few workshops to the whole company. In (employee, documents) → *a guided interview with a fixed form behind it* ("like a good consultant"), with one plain sentence: through a guided chat, the agent helps an employee share what they know, then select and map a workflow of their own worth transforming with AI → Out: the discovery report (report v2, spec 27): summary and three questions (good AI use case, own tool or Copilot, worth it); map; baseline; AI fit per step with route; feasibility (readiness, what to prepare, gaps); every claim with the expert's words. One compact strip: what it changes: about 1.5 h instead of 24 h per process *(updated 2026-11-21 (estimated effort: ~1.5 h per process, an assumption))* · every process comparable · specialists review instead of collect |
| 6 | The new process: 20–30 minutes for the employee, a comparable baseline for the team | To-be swimlane (specialist reviews the report in ~1 h; *updated 2026-11-21 (estimated effort: ~1.5 h per process, an assumption)*) (overview and brief dashed: next release), example report (FIN cost review, fictional: map, hours, AI fit per step, three questions), before/after bars |
| 7 | It pays back twice: €0.45–0.68M a year for the AI team, and more, better AI builds for NIG | Left, **return 1** (counted): value, build, run, payback tiles; where the money comes from (~4 → ~0.25 specialists); the formula (400 × 22.5 h + 25 × 40 h, × €90 × 50–75 % = €450–675k; payback ~3 months, ~2 at expected; *updated 2026-11-21 (estimated effort: ~1.5 h per process, an assumption)*). Right, **return 2** (not counted, the bigger prize): a funnel, find 400+ → compare → choose → build, fanning out to € coins: each build pays back in the business. No euro figure on return 2 (product owner, 2026-11-21). Not-counted note on failed builds avoided |
| 8 | Three things must be true. Three numbers would make us stop | Assumption cards (at 18 h by hand: €342k a year, payback ~4 months), kill-metric gauges (specialist hours per process: target 1 h, stop above 3 h), the pilot window *(updated 2026-11-21 (estimated effort: ~1.5 h per process, an assumption))* |
| 9 | The MVP is live. Next: a pilot in one region, then production, then scale | Roadmap: MVP live on Azure, link on the slide (interview, documents, report, workspace, evaluation) → pilot → gate → production (Entra ID, works council, languages, Microsoft 365 evidence via Graph and Work IQ with consent: Teams transcripts, SharePoint files pre-fill the map) → scale; the ask; links |

## 3. Appendix (live session only, not in the PDF)

Architecture · build vs buy · how we know it works (evaluation and failure cases) · how we built it · production readiness.

---

## 4. Design

| Item | Choice |
|---|---|
| Look | Black background, white text, one accent colour (to choose), grey for secondary text; green for "passes", red only for pain and kill thresholds |
| Type | One modern sans-serif; large one-sentence titles |
| Diagrams | Inline SVG: swimlanes, tiles, number rows, roadmap |
| Icons | One line-icon set |
| Motion | Subtle entrances in HTML; the PDF shows each slide's final state |
| Format | One HTML file, 16:9, keyboard navigation; PDF by headless Chromium, one slide per page |

---

## 5. Open questions

1. **Slide 2:** these six questions? Better "fails" examples from your experience?
2. **Slide 2–3:** which other candidates did you consider? (Optional: without them the slide still works.)
3. **Slide 8:** these three kill metrics? Windows and thresholds to set.
4. **Accent colour:** later. (Name settled: AI Use Case Discovery Agent.)
