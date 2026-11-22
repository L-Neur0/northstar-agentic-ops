# Specifications

> This folder is part of the [AI Use Case Discovery Agent](../README.md). The specs describe what the tool does and how each part is built, and they are the source of truth for the code. The rule is always the same: **spec first, then tests, then code.**

## Where each kind of fact lives

| Level | Document | Answers | Changes when |
|---|---|---|---|
| 1 | [Use case](../docs/01-use-case/use-case.md) | **Why:** the problem, the users, the value, the numbers and the assumptions | The business case changes |
| 2 | [01 · Product](01-product.md) | **What:** the concepts, the form, features F-01 to F-26, the lifecycles and the quality targets | A behaviour is added or changed |
| 3 | [02 · Architecture](02-architecture.md) | **How, overall:** the layers, the data model, the AI calls, the API, security, deployment and the main decisions | A structural choice changes |
| 4 | Component specs (below) | **How, in detail:** the behaviour rules, the interfaces, the acceptance criteria and the tests | Before each piece of work starts |
| 5 | Code and tests | The implementation | Only after its spec has changed |

**Rule:** a change starts at the highest level that it affects, and then it flows down. A component spec never contradicts the product or the architecture; if it has to, those documents are changed first.

## Component specs

| # | Spec | Implements | Status |
|---|---|---|---|
| 10 | [`10-foundation.md`](10-foundation.md): repository, tooling, settings, company config, logging, architecture test | F-22 | built |
| 11 | [`11-llm-client.md`](11-llm-client.md): Azure OpenAI client, schemas, retries, cache, fake model, safety | arch §6 | built |
| 12 | [`12-registry-and-models.md`](12-registry-and-models.md): field registry, verdicts, sources and proposals, taxonomy, rubric, Pydantic models | F-05, arch §3.2, §5 | built |
| 13 | [`13-profile.md`](13-profile.md): applying changes, completeness, roll-ups, snapshot, proposals | F-05, F-08, F-10, F-11 | built |
| 14 | [`14-interview.md`](14-interview.md): phases, limits, reading replies, prompts, model calls, the turn, the turn log; steering in §3.15 | F-02, F-03, F-06, F-07, F-08, F-09, F-10, F-24 | built (including steering, documents in chat, conflicts, finish offer and the short step walk) |
| 15 | [`15-api-and-store.md`](15-api-and-store.md): the store (part 1), the service and the routes (part 2) | F-01, F-11, F-23 | built (both parts) |
| 16 | [`16-access.md`](16-access.md): visitor key, resume link, workspace codes, rate limits, daily budget | F-21 | built |
| 17 | [`17-documents.md`](17-documents.md): upload, text extraction, BPMN reading, READ_DOCUMENT, proposals and confirmation | F-04 | built (in context, images, .pptx and .eml, conflicts) |
| 18 | [`18-opportunities-and-map.md`](18-opportunities-and-map.md): the process map, and the opportunities call | F-12, F-13 | built; the opportunities call is no longer used since report v2 (spec 27) |
| 19 | [`19-value-and-readiness.md`](19-value-and-readiness.md): hours, labels, readiness, path | F-14, F-15 | built (hours only; the euro value is parked) |
| 20 | [`20-report.md`](20-report.md): report assembly, screen model, PDF | F-16 | built |
| 21 | [`21-admin.md`](21-admin.md): workspace backend: session list, read-only session view, conversation, report PDF, delete, audit line | F-17 (read-only) | built (read-only, open demo) |
| 22 | `22-exports.md`: BPMN XML and Excel export | F-20 | to write |
| 23 | [`23-frontend.md`](23-frontend.md): app shell and home, interview (part 1); report and documents (part 2); workspace (part 3) | the screens of all features | built (parts 1 to 3) |
| 24 | [`24-evaluation.md`](24-evaluation.md): simulated employees, runner, scoring, judge, scorecard, seed data | F-25 | built (review of 2026-11-20 in §11) |
| 25 | [`25-deployment.md`](25-deployment.md): Dockerfile, Bicep and azd, CI, stages | arch §7 | built and deployed on Azure |
| 26 | [`26-step-assessment.md`](26-step-assessment.md): ASSESS_STEPS, solution catalogue, recommended route | F-26 | built |
| 27 | [`27-report-v2.md`](27-report-v2.md): report v2: summary, three guiding questions, AI fit for each step, feasibility | F-16 | built |

**Build order** (see [architecture §8](02-architecture.md#8-what-builds-on-what)): 10 → 12 → 13 → 11 → 14 → 15/16 (with 25 in parallel from the start) → 17 and 18/19/26 (in parallel) → 20 → 23 (home, interview) → 21 → 23 (report, workspace) → 24 → 22.

## How each piece of work runs

1. **Inspect.** Read the product spec, the architecture, the specs that this one depends on, and the code that exists today. Note what the new work touches and what it must not break.
2. **Specify.** Write or update the component spec, starting from [`_template.md`](_template.md), so that it covers the behaviour, the interfaces, the effects on other parts and the acceptance criteria. Keep it clear, concrete and short, and **have it reviewed before any code is written.**
3. **Test first.** Turn each acceptance criterion into at least one failing test, whose name or docstring cites the criterion's ID (for example `AC-13.4`).
4. **Implement.** Write the smallest code that makes the tests pass, and then refactor while the tests stay green.
5. **Verify.** Check that `make lint test` is green, run the feature for real when that makes sense, and update the spec's status and any decision that changed.
6. **Review and commit.** Move one reviewed step at a time.

## Status values

`to write` → `draft` (written and under review) → `approved` (ready to build) → `built` (tests are green) → `verified` (checked by hand or by the evaluation).
