# AI Use-Case Assessment Framework

A simple, repeatable way to decide **which process to automate with AI, and why**. Copy [`assessment-template.md`](assessment-template.md) into `docs/ideas/<cluster>-<idea>.md` for each idea.

**Context:** NIG is a global engineering & infrastructure consultancy (~50k staff) with a group HQ and regional companies grown through acquisitions, each with its own systems. Solutions that scale across regions beat solutions for one HQ team.

## Rules of thumb

- **Process first, not technology.** Start from a painful, frequent workflow.
- **Code where possible, AI where necessary.** Maths and rules are code; AI handles messy inputs, investigation and drafting.
- **Be conservative.** Every number is marked *measured*, *benchmark* or *assumption*. Freed hours are not cash unless we say how they become money.
- **A human stays accountable.** Read-only access to systems of record; a human approves anything consequential.

## Step 1 — Gates (any "no" = drop)

1. **Allowed** — not invoice processing, CV screening, contract review, ticket routing, knowledge chatbot or lead qualification.
2. **Real, frequent pain** — at least ~5,000 hours/yr across the company.
3. **No off-the-shelf tool** already does it well.
4. **Data exists today** — no six-month data project before it shows value.
5. **Measurable** — we can measure the baseline and check whether the AI output is right.

## Step 2 — Score (1–5, one-line reason each)

| | 1 | 3 | 5 |
|---|---|---|---|
| **ROI** — conservative net €/yr, incl. how hours become money | < €100k | €0.5–2M | > €5M |
| **Scalability** — cost to add one more region/team | One HQ team only | Several regions, some custom work each | Any region via config, near-zero extra cost |
| **Adoption** — fits how users already work; they want it | New tool nobody asked for | Some habit change | Lives in their workflow; users asked for it |
| **Feasibility** — data and systems | Data missing or locked in legacy | 3–4 systems, some messy data | One clean, read-only source |
| **Build & run cost** — time, €, upkeep | > 2 quarters, > €1M, heavy upkeep | ~1 quarter, €150–400k | < 1 month, < €50k, little upkeep |
| **Risk** — cost of a wrong output | Safety, legal or irreversible | Costs money but caught by review | Harmless and obvious |

*2 and 4 sit between the anchors. On the right three rows, higher = easier/safer.*

```
Value = (2 × ROI + Scalability + Adoption) / 4      ← ROI counts double
Ease  = (Feasibility + Build & run cost + Risk) / 3

GO     = all gates pass, Value ≥ 3.5, Ease ≥ 3
MAYBE  = gates pass, one threshold missed
NO-GO  = otherwise
```

## Step 3 — Deep dive (top 3 only)

1. **Step table** — each step today vs. after: who, tool, minutes, automation level (*0 human · 1 AI suggests · 2 AI does, human approves · 3 automated*).
2. **ROI** — conservative / expected / upside, pilot vs. scale:
   ```
   Hours saved/yr = (min before − min after) × cases/yr ÷ 60 × adoption
   Value/yr       = hours saved × €/h  (+ risk avoided, shown separately)
   Net/yr         = value − run cost (LLM + infra + support)
   Payback        = build cost ÷ (net/yr ÷ 12) months
   ```
   Defaults: €90/h professional · €3k per engineer-week · adoption 30/50/75%.
3. **Non-AI alternative and build vs. buy** for each main component.
4. **Kill test** — 3 critical assumptions (how to validate, what if false) and 3 kill metrics (quality, adoption, value) with window and threshold.

The deep dive feeds two outputs: a **one-page leadership summary** (value, cost, payback, risk, kill criteria) and **platform notes** (architecture, owner, run cost per case, monitoring, security).
