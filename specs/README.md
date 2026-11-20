# Specifications

> How the Discovery Agent is specified and built. **Spec first, then tests, then code.**

## Hierarchy: where each kind of fact lives

| Level | Document | Answers | Changes when |
|---|---|---|---|
| 1 | [Use case](../docs/01-use-case/use-case.md) | **Why:** problem, users, value, numbers, assumptions | The business case changes |
| 2 | [01 · Product](01-product.md) | **What:** concepts, the profile, features F-01…F-26, lifecycles, quality targets | A behaviour is added or changed |
| 3 | [02 · Architecture](02-architecture.md) | **How, overall:** layers, data model, AI calls, API shape, security, deployment, decisions | A structural choice changes |
| 3b | [03 · Implementation plan](03-implementation-plan.md) | **In what order, by whom:** contracts, parallel workstreams, waves, cut line | The plan changes |
| 4 | Component specs (below) | **How, in detail:** behaviour rules, interfaces, acceptance criteria, tests | Before each piece of work |
| 5 | Code and tests | The implementation | Only after its spec |

**Rule:** a change starts at the highest level it affects and flows down. A component spec never contradicts the product or the architecture; if it must, those change first.

## Component specs

| # | Spec | Implements | Status |
|---|---|---|---|
| 10 | [`10-foundation.md`](10-foundation.md): repo, tooling, settings, company config, logging, architecture test | F-22 | built |
| 11 | [`11-llm-client.md`](11-llm-client.md): Azure OpenAI client, schemas, retries, cache, fake, safety | arch §6 | built |
| 12 | [`12-registry-and-models.md`](12-registry-and-models.md): field registry, Verdicts, sources and proposals, taxonomy, rubric, Pydantic models | F-05, arch §3.2, §5 | built |
| 13 | [`13-profile.md`](13-profile.md): applying changes, completeness, roll-ups, snapshot, proposals | F-05, F-08, F-10, F-11 | built |
| 14 | [`14-interview.md`](14-interview.md): phases, limits, reply reading, prompts, the model calls, the turn, turn log; §3.15 steering amendment | F-02, F-03, F-06, F-07, F-08, F-09, F-10, F-24 | built · §3.15 approved |
| 15 | [`15-api-and-store.md`](15-api-and-store.md): store (part 1), service and routes (part 2) | F-01, F-11, F-23 | built (part 1 + part 2) |
| 16 | [`16-access.md`](16-access.md): visitor key, resume link, workspace codes, rate limits, daily budget | F-21 | built |
| 17 | [`17-documents.md`](17-documents.md): upload, text extraction, BPMN reading, READ_DOCUMENT, proposals and confirmation | F-04 | built (routes in block 4) |
| 18 | [`18-opportunities-and-map.md`](18-opportunities-and-map.md) | F-12, F-13 | approved |
| 19 | [`19-value-and-readiness.md`](19-value-and-readiness.md): hours (euro parts parked, R5), labels, readiness, path | F-14, F-15 | approved · hours-only amendment approved |
| 20 | [`20-report.md`](20-report.md): report assembly, screen model, PDF | F-16 | approved (v3: 11 parts) |
| 21 | [`21-admin.md`](21-admin.md): workspace backend: session list, read-only session view, conversation, report PDF, delete, audit line | F-17 (read-only) | draft |
| 22 | `22-exports.md`: BPMN XML, Excel | F-20 | to write |
| 23 | [`23-frontend.md`](23-frontend.md): app shell, home, interview (part 1); report, documents (part 2); admin (part 3) | screens of all features | part 1 + part 2 built · part 3 draft |
| 24 | `24-evaluation.md`: simulated experts, runner, metrics, seed data | F-25 | to write |
| 25 | [`25-deployment.md`](25-deployment.md): Dockerfile, Bicep/azd, CI, stages | arch §7 | approved |
| 26 | [`26-step-assessment.md`](26-step-assessment.md): ASSESS_STEPS, solution catalogue, recommended route | F-26 | approved |

**Build order** (see [architecture §8](02-architecture.md#8-what-builds-on-what)): 10 → 12 → 13 → 11 → 14 → 15/16 (25 in parallel from the start) → 17 and 18/19/26 (in parallel) → 20 → 23 (UI-1: home, interview) → 21 → 23 (UI-2: report, workspace) → 24 → 22.

## How every piece of work runs

1. **Inspect.** Read `CLAUDE.md`, the product spec, the architecture, the specs this one depends on, and the code that exists today. Note what the new work touches and what it must not break.
2. **Specify.** Write or update the component spec from [`_template.md`](_template.md): behaviour, interfaces, implications, acceptance criteria. Clear, concrete, short. **Review before any code.**
3. **Test first.** Turn each acceptance criterion into at least one failing test whose name or docstring cites its ID (for example `AC-13.4`).
4. **Implement.** Write the smallest code that makes the tests pass; refactor with the tests green.
5. **Verify.** `make lint test` green; run the feature for real where it applies; update the spec's status and any decision that changed.
6. **Review and commit.** One reviewed step at a time.

## Status values

`to write` → `draft` (written, under review) → `approved` (ready to build) → `built` (tests green) → `verified` (checked by hand or by the evaluation set).
