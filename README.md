# AI Use Case Discovery Agent

*Find a workflow worth transforming, map it step by step, and see where AI can help.*

Large companies want to use AI in their daily operations, but the first question is always the same: **which processes should AI take over first?** Today the answer comes from workshops and interviews run by a small AI team, one process at a time. This project turns that into a tool every employee can use on their own.

The **AI Use Case Discovery Agent** runs a 20–30 minute guided interview. The employee who knows a process describes it step by step: what starts it, who is involved, which systems, how long it takes, what hurts. They can upload documents they already have; the AI reads them and the employee confirms. At the end they get a **discovery report**:

| Part | What it says |
|---|---|
| Summary | What was mapped, how well AI fits, where to start, hours a year |
| The process, volume and map | The mapped process as a BPMN diagram and a step table |
| Step-by-step AI assessment | Per step: how AI can help, which tool, why (with the employee's own words) |
| AI readiness and feasibility | Three questions: *is this a good AI use case? a dedicated tool or a general assistant? is it worth it?* plus a readiness checklist and what to prepare first |

Specialists then review the reports in a workspace instead of running every interview themselves.

The case is built for **NorthStar Infrastructure Group (NIG)**, a **fictional** 50,000-person engineering and infrastructure company. All company data is simulated.

## How it works

**It is not a chatbot.** Behind the conversation is a fixed form (16 process fields, up to 14 fields per step). Three rules keep it trustworthy:

1. **Code decides, the model writes.** Code decides what counts as answered, which question comes next and when the map is complete. The language model only reads answers and phrases questions.
2. **Code makes every number.** Hours, levels and the order of steps come from code, never from the model.
3. **No quote, no claim.** Every AI assessment must carry the employee's exact words; code checks the quote exists before it is shown.

The tool guides; it never says go or no-go.

## Tech stack

Python 3.12 · FastAPI · Pydantic v2 · Azure OpenAI · Cosmos DB · React + TypeScript + Tailwind · Azure Container Apps (Bicep, `azd`) · GitHub Actions

## Run it locally

You need Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22, and `make`.

```bash
make setup                                 # install backend and frontend dependencies
cp backend/.env.example backend/.env       # then set AZURE_OPENAI_ENDPOINT to your own resource
make dev                                   # backend on :8000, frontend on :5173
make test                                  # backend, evaluation and frontend tests
```

No Azure account? `cd frontend && npm run dev:fake` runs the screens against a built-in fake API.

## Repository map

| Folder | What's inside |
|---|---|
| [`docs/`](docs/README.md) | The use case, technical design, executive summary, how we worked |
| [`specs/`](specs/README.md) | Product spec, architecture and one spec per component (the source of truth for the code) |
| [`backend/`](backend/README.md) | The API and the interview engine |
| [`frontend/`](frontend/README.md) | The interview, report and workspace screens |
| [`config/`](config/README.md) | Everything company-specific (NIG): taxonomy, tools, readiness rules |
| [`eval/`](eval/README.md) | Simulated employees that play the interview and score the result |
| [`infra/`](infra/README.md) | Azure infrastructure as code |

## How it was built

Every change went spec → tests → code: a short spec with acceptance criteria, failing tests that cite them, then the smallest code to make them pass. See [`docs/05-how-we-worked/`](docs/05-how-we-worked/pipeline.md).

## Licence

[MIT](LICENSE)
