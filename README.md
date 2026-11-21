# NorthStar Agentic Ops · AI Use Case Discovery Agent

*Find a workflow worth transforming, map it step by step, and see where AI can help.*

AI prototype for **NorthStar Infrastructure Group (NIG)**, a fictional 50,000-person engineering, construction and operations company that wants to become an agentic enterprise.

The **AI Use Case Discovery Agent** *(renamed 2026-11-21 from "Discovery Agent")* answers the programme's first question: **which processes should AI take over first?** Any employee finds a process in their own work in a 20–30 minute guided interview, maps it step by step, and gets a **discovery report**: a summary, three questions (*good AI use case? own tool or Copilot? worth it?*), the mapped process, how AI helps each step, and feasibility (what to prepare first). Documents the expert already has can be uploaded; the AI reads them and the expert confirms. Specialists review instead of interviewing (about 1 hour per process). Next release: specialist validation, one overview of all processes, and a hand-over brief to the AI engineers. The tool guides; it never says go or no-go.

**It is not a chatbot.** It is a guided interview with a fixed form behind it. Code decides what counts as answered, when the map is complete, and every number; the model reads answers and phrases questions.

> Status: the first working version is live on Azure and passed six simulated interviews end to end. Next release: overview, hand-over brief, specialist validation.

## Repository map

| Folder | What's inside |
|---|---|
| [`docs/01-use-case/`](docs/01-use-case/use-case.md) | ★ **The use case:** problem, users, value, assumptions |
| [`specs/`](specs/README.md) | [Product specification](specs/01-product.md), [architecture](specs/02-architecture.md), one spec per component |
| [`docs/05-how-we-worked/`](docs/05-how-we-worked/pipeline.md) | How we build (spec → test → code), and the framework used to choose the use case |
| `docs/02-processes/` | As-is and to-be processes, user journey *(to come)* |
| [`docs/03-technical-design/`](docs/03-technical-design/technical-design.md) | Technical design document and production readiness |
| [`docs/04-executive-summary/`](docs/04-executive-summary/executive-summary.md) | Executive summary (the one-pager) and deck |
| `backend/` · `frontend/` · `config/` · `eval/` · `infra/` | The app, company configuration, evaluation set, Azure infrastructure |

## Deliverables

- [x] Working prototype (hosted on Azure)
- [ ] Demo video (5–10 min)
- [x] Technical design document → `docs/03-technical-design/`
- [x] Executive summary → `docs/04-executive-summary/`
