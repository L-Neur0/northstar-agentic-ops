# NorthStar Agentic Ops · Discovery Agent

AI prototype for **NorthStar Infrastructure Group (NIG)**, a fictional 50,000-person engineering, construction and operations company that wants to become an agentic enterprise.

**Discovery Agent** *(working name)* answers the programme's first question: **which processes should AI take over first?** Any employee finds a process in their own work in a 15–20 minute guided interview, maps it step by step, and gets a **discovery report**: the mapped process and its transformation assessment (hours a year, where automation or AI fits and how, what to prepare first). Documents the expert already has can be uploaded; the AI reads them and the expert confirms. Specialists review instead of interviewing, every report joins one process overview, and the opportunities chosen for a build go to the AI engineers as an implementation brief. The tool guides; it never says go or no-go.

**It is not a chatbot.** It is a guided interview with a fixed form behind it. Code decides what counts as answered, when the map is complete, and every number; the model reads answers and phrases questions.

> Status: 🚧 work in progress (specification)

## Repository map

| Folder | What's inside |
|---|---|
| [`docs/01-use-case/`](docs/01-use-case/use-case.md) | ★ **The use case:** problem, users, value, assumptions |
| [`specs/`](specs/README.md) | [Product specification](specs/01-product.md), [architecture](specs/02-architecture.md), one spec per component |
| [`docs/05-how-we-worked/`](docs/05-how-we-worked/pipeline.md) | How we build (spec → test → code), and the framework used to choose the use case |
| `docs/02-processes/` | As-is and to-be processes, user journey *(to come)* |
| `docs/03-technical-design/` | Technical design document *(to come)* |
| `docs/04-executive-summary/` | Executive summary and demo script *(to come)* |
| `backend/` · `frontend/` · `config/` · `eval/` · `infra/` | The app, company configuration, evaluation set, Azure infrastructure *(to come)* |

## Deliverables

- [ ] Working prototype (hosted on Azure)
- [ ] Demo video (5–10 min)
- [ ] Technical design document → `docs/03-technical-design/`
- [ ] Executive summary → `docs/04-executive-summary/`
