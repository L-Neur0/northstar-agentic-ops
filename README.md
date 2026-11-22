# AI Use Case Discovery Agent

*Find a workflow worth transforming, map it step by step, and see where AI can help.*

Large companies want to use AI in their daily work, but they first have to decide **which processes AI should take over first**. Today a small AI team answers that question through workshops and interviews, one process at a time, so the work grows slowly. This project turns those interviews into a tool that every employee can use on their own.

The **AI Use Case Discovery Agent** runs a guided interview that takes about 20 to 30 minutes. The employee who knows a process describes it step by step: what starts it, who takes part, which systems they use, how long it takes and what is painful. If they already have documents about the process, they can upload them; the AI reads them and the employee confirms what it found. At the end, the employee gets a **discovery report**:

| Part | What it says |
|---|---|
| Summary | What was mapped, how well AI fits, where to start, and how many hours a year are spent |
| The process, volume and map | The process as a BPMN diagram, together with a table of its steps |
| Step-by-step AI assessment | For each step: how AI can help, which tool fits, and why, quoting the employee's own words |
| AI readiness and feasibility | Three guiding questions (*is this a good AI use case? does it need a dedicated tool or a general assistant? is it worth it?*), a readiness checklist and what to prepare first |

AI specialists then review these reports in a shared workspace, so they no longer need to run every interview themselves.

The project is built for **NorthStar Infrastructure Group (NIG)**, a **fictional** engineering and infrastructure company with 50,000 employees. All company data is simulated.

## How it works

**It is not a free chatbot.** Behind the conversation there is a fixed form, with 16 fields about the process and up to 14 fields for each step. Three rules keep the results trustworthy:

1. **Code decides, and the model writes.** Code decides when a question has been answered, which question comes next and when the map is complete. The language model only reads the answers and phrases the questions.
2. **Code computes every number.** Hours, levels and the order of the steps always come from code, never from the model.
3. **No quote, no claim.** Every AI assessment must include the employee's exact words, and code checks that the quote really exists before the assessment is shown.

The tool guides the decision, but it never says go or no-go.

## Tech stack

Python 3.12 · FastAPI · Pydantic v2 · Azure OpenAI · Cosmos DB · React + TypeScript + Tailwind · Azure Container Apps (Bicep, `azd`) · GitHub Actions

## Run it locally

You need Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 and `make`.

```bash
make setup                                 # install the backend and frontend dependencies
cp backend/.env.example backend/.env       # then set AZURE_OPENAI_ENDPOINT to your own resource
make dev                                   # starts the backend on :8000 and the frontend on :5173
make test                                  # runs the backend, evaluation and frontend tests
```

If you do not have an Azure account, run `cd frontend && npm run dev:fake`, which shows the screens with a built-in fake API.

## How the repository is organised

The repository has three layers, and it is easiest to read them in this order. The **documents** explain why the tool exists and what it is worth. The **specs** describe exactly what the code must do. The **code** then implements the specs, and every test cites the spec rule it checks.

### 1. Documents: why, and for whom

| Where | What you find there |
|---|---|
| [`docs/01-use-case/`](docs/01-use-case/use-case.md) | **Start here.** The problem, the users, the value, the numbers and the assumptions |
| [`docs/03-technical-design/`](docs/03-technical-design/technical-design.md) | How the tool is built and why, together with [production readiness](docs/03-technical-design/production-readiness.md): security, cost at scale and rollout |
| [`docs/04-executive-summary/`](docs/04-executive-summary/executive-summary.md) | The one-page executive summary and the [deck](docs/04-executive-summary/deck.pdf) |
| [`docs/05-how-we-worked/`](docs/05-how-we-worked/pipeline.md) | The way of working, and the framework that was used to choose the use case |

### 2. Specs: what the code must do

| Where | What you find there |
|---|---|
| [`specs/01-product.md`](specs/01-product.md) | The product: concepts, the form, the features and the quality targets |
| [`specs/02-architecture.md`](specs/02-architecture.md) | The overall design: layers, data model, AI calls, API, security and deployment |
| [`specs/10-…` to `27-…`](specs/README.md) | One spec for each component, with its rules and acceptance criteria. The [specs README](specs/README.md) lists them all with their status |

### 3. Code: the tool itself

| Where | What you find there |
|---|---|
| [`backend/`](backend/README.md) | The API and the interview engine (Python, FastAPI) |
| [`frontend/`](frontend/README.md) | The interview, report and workspace screens (React, TypeScript) |
| [`config/`](config/README.md) | Everything that is specific to the company (NIG), such as clusters, tools and readiness rules, so that the code stays the same for any company |
| [`eval/`](eval/README.md) | Simulated employees who play the interview, and the code that scores the result |
| [`infra/`](infra/README.md) | The Azure infrastructure, written as code (Bicep, `azd`) |

The files at the top level tie these parts together: the `Makefile` holds the everyday commands, the `Dockerfile` builds the single container that serves both the API and the screens, `azure.yaml` tells `azd` how to deploy it, and `.github/workflows/ci.yml` runs the lint, the tests and an image check on every push, and deploys from `main` only after a person approves it.

## How it was built

Every change followed the same order: spec, then tests, then code. First we wrote a short spec with acceptance criteria, then failing tests that refer to those criteria, and finally the smallest code that makes the tests pass. You can read more in [`docs/05-how-we-worked/`](docs/05-how-we-worked/pipeline.md).

## Licence

[MIT](LICENSE)
