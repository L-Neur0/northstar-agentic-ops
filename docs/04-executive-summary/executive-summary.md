# AI Use Case Discovery Agent · Executive summary

> NIG (fictional) · **IT & Security** · November 2026 · *Figures are assumptions, to be confirmed in a pilot.* Detail: [use case](../01-use-case/use-case.md) · [deck](deck.pdf)

**In one line:** a 15–20 minute guided interview shows NIG **which processes AI should transform first, without weeks of workshops.**

## 1. Context

NIG has 50,000 people in 36 teams (9 clusters × 4 regions), each with its own systems, and earlier AI programmes stalled on fragmented data and processes. Before anything is built, someone has to find the workflows worth transforming, map, assess and select them: this is **AI use case discovery**, the workflow we chose. It is IT's own work and serves all nine clusters.

## 2. Problem

Today two AI specialists map each process in a workshop with two employees and write it up by hand: about **24 person-hours and 2–3 weeks per process**, one process at a time.

| What happens today | Why it hurts |
|---|---|
| Specialists interview people one by one | At most 150–200 processes a year |
| Each specialist asks and writes differently | Reports cannot be compared |
| Nobody checks whether a workflow is ready | AI builds stall after weeks |
| Detail is lost at the hand-over | Engineers re-ask people: **~60 h per build** |

## 3. Solution

The employee opens a link and has a **guided chat** with the agent, which helps them share what they know and then select and map a workflow of their own that is worth transforming with AI; they can also upload documents. A fixed form behind the chat makes every result comparable: the AI asks and follows up, code checks every answer and computes every number, and the employee confirms. Because it runs **for every employee at the same time**, specialists review the best candidates instead of collecting them.

```mermaid
flowchart LR
  E["Employee<br/>15–20 min"] --> I["Guided interview"]
  D["Own documents"] --> I
  I --> R["Discovery report"]
  R --> S["Specialist review<br/>~4 h"]
  S --> O["Overview of<br/>all processes"]
  O --> B["Brief to engineers"]
  classDef next stroke-dasharray:5 5
  class O,B next
```

*Solid: built. Dashed: next release.* The report answers three questions (*good AI use case? own tool or Copilot? worth it?*), then shows AI fit and route per step, readiness and what to prepare. Every claim quotes the employee, and the decision stays with people.

## 4. Business value: it pays back twice (base case: 400 processes a year)

| | Today | With the tool |
|---|---|---|
| Person-hours per process | 24 | **5** |
| Engineer hours per build | 60 | **20** |

- **For the AI team (counted): €387k–581k a year**, from 400 processes × 19 h plus 25 builds × 40 h saved, at €90/h and 50–75 % adoption. With a €100k build and €35k a year to run, it **pays back in about 3.5 months**.
- **For the whole company (not counted, and larger):** NIG compares 400+ processes instead of 150–200, picks the best and most ready, and builds more AI, **each build paying back again in the business**.

## 5. Risks: three things must be true

| Must be true | Pilot check | Stop if |
|---|---|---|
| Employees finish on their own | Share who complete | Below 50 % |
| Reports are good enough | Specialist: major edits? | Below 50 % clean |
| The hours saved are real | Time 5 manual mappings | Above 10 h review |

At 18 manual hours instead of 24 it still pays (€279k a year); works councils, invented facts and languages are handled by design.

## 6. Status and the ask

The MVP is built and tested on Azure OpenAI and Cosmos DB. **The ask:** an **8-week pilot in one cluster and one region (~20 processes)**, then production, Microsoft 365 evidence with consent (Graph, Work IQ) and roll-out **by configuration**.
