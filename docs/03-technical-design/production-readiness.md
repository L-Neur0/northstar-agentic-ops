# Production readiness: from prototype to a company-wide tool

> **Status:** final, November 2026 (brief task 3). Effort and cost figures are *assumptions*, marked as such, to confirm with NIG's platform team and in the pilot.
> The prototype is deliberately open (anyone with the link) and small (one container, one replica, read-only workspace, English). This page lists what changes for production at NIG across teams, projects and countries, why, how much work it is and who owns it.

## 1. The honest estimate

**This needs about two quarters and these three things:**

1. **A data-protection and works-council agreement in the first region**, started on day one. It is the critical path, not the code: no real employee should be interviewed before it exists.
2. **Two engineers' worth of work for one quarter (26 engineer-weeks, about €100k with language testing and a security review)**, spread over the two quarters: Entra ID sign-in before the pilot, then hardening (private network, replicas, *Finish* as a background job, evaluation gate, Microsoft 365 evidence, specialist edits).
3. **Named owners**: a product owner in the AI transformation team, an engineering owner in IT's platform team, and a champion in each cluster who launches the tool with their teams.

| When | What | Who |
|---|---|---|
| Weeks 1–3 | Entra ID sign-in, consent text, impact assessment started | 1 engineer; data protection officer, HR |
| Weeks 4–11 | **8-week pilot**: one cluster in one region, about 20 processes, on the current build. Three kill tests: share of employees who finish (stop below 50 %), share of reports a specialist accepts without major edits (stop below 50 %), specialist review time (stop above 3 h) | Product owner, 1–2 specialists, 1 engineer for fixes and prompt tuning on pilot data |
| Quarter 2 | **Production hardening** (sections 3–7), then the first cluster-region goes live in production | 2 engineers |
| After that | **Rollout by configuration**, cluster by cluster and region by region (section 10) | Product owner, champions; no new code per region |

This is the €100k build and €35k a year run of the use case: the build is one quarter of two engineers' work, and it takes two calendar quarters because the pilot and the agreements set the pace.

## 2. Summary

| Area | Prototype | Production | Effort |
|---|---|---|---|
| Identity and access | Open link, visitor key, workspace access code with a typed name | **Entra ID single sign-on**, roles from app roles, named attribution of every action, per-user quotas | M |
| Network and secrets | Public ingress, managed identity | Private endpoints, VNet integration, WAF in front, Key Vault for anything not covered by managed identity | M |
| Data access and protection | Interview and uploaded documents; one EU region; no files stored | Microsoft 365 evidence with consent; impact assessment, works-council agreement, residency and retention per country, tested restore | M–L (mostly people, not code) |
| Reliability | One replica, *Finish* in one long request | 2+ replicas, shared rate-limit store, *Finish* and document reading as background jobs, alerts and runbook | M |
| AI quality and cost | gpt-5.6-sol (EU Data Zone), version pinned (no auto-upgrade), six-persona evaluation, daily budget | Planned version upgrades, evaluation gate before every model or prompt change, evaluation set from pilot sessions, cost dashboard | S–M |
| Languages | English; yes/no words in English and German | Tested interviews and reports in each NIG language | M per language |
| Workspace | Read-only: sessions, conversations, report v2 and PDF | Specialist edits and validation, overview across sessions, implementation briefs | M |
| Integrations | None with NIG systems | Launch from Teams and the intranet; report export to NIG's BPM tool; briefs to the engineering backlog | S each |
| Operations | The author | Product owner, engineering owner, support within IT's platform team | People |

*S = days, M = 2–4 weeks, L = a quarter, for one engineer.*

## 3. Identity and permissions: Entra ID

**Why not in the prototype:** reviewers outside NIG's tenant must be able to open the demo. **Why it is required in production:** reports describe how real teams work; access must follow the company's identity, leavers must lose access, and every action must be attributable.

| Piece | Design |
|---|---|
| App registration | One registration: SPA platform (redirect URIs per environment), API scope `access_as_user`, app roles `Discovery.Specialist` and `Discovery.Engineer`; employees need no role, roles are assigned through groups |
| Frontend | MSAL (authorization code flow with PKCE); a token for the API scope on every request; the visitor key disappears |
| Backend | Validate every bearer token: signature against the tenant's signing keys (cached, refreshed when an unknown key id appears), issuer, audience, expiry. The signed-in user replaces the visitor key and the workspace code; the owner id becomes the Entra object id |
| Roles | Checked on the server for every workspace route (the screen only hides) |
| Dev and test | A signed dev token accepted **only** when the deployment stage is explicitly `local` or `test`, a setting never guessed from the environment |
| Migration | Sessions made with a visitor key can be claimed once by a signed-in user through the resume link |
| Quotas | Per-user token quota over a rolling window, on top of the global daily budget |

## 4. Network and secrets

- Private endpoints for Cosmos DB and Azure OpenAI; key authentication stays disabled.
- Container Apps environment in a VNet; public entry only through Front Door with WAF, or internal only if the tool is intranet-only.
- Key Vault for any secret not covered by managed identity; read by the container app, never in code or CI.
- CI deploys with OIDC federation (already the case) and a **manual approval** before production.

## 5. Data: access, protection and jurisdictions

**Access across fragmented systems.** The tool does not need to connect NIG's ERP, HR or ticketing systems to do discovery, and that is deliberate: each region runs its own systems, and connecting them would take longer than the whole programme. The evidence comes from the employee who uses those systems and from documents they already hold. The report names the systems and data of every step, so the fragmentation itself becomes visible and comparable. The one connection worth building is **Microsoft 365** (Microsoft Graph, Work IQ): with the employee's consent and **only with the employee's own permissions**, Teams meeting transcripts and SharePoint process documents pre-fill the map before the interview, so the employee confirms instead of describing, and the specialists get independent evidence. The rule stays as for uploads: everything read is a proposal with a quote until the employee confirms it.

**Protection.**
- **Processes, not people** is a product rule; in production it needs a written agreement with HR and works councils, Europe first, before rollout in each country that has one.
- Data protection impact assessment: what the conversation and documents may contain, who sees what, retention. Specialists read full conversations to improve the interview; production needs explicit consent text, a purpose limit and access logging (the workspace already logs every opened conversation).
- Retention per country (default 90 days for unfinished sessions); "delete my data" already exists; uploaded files are never stored.
- Backups: Cosmos continuous backup; restore tested once per quarter.

**Jurisdictions and residency.** The model runs in an EU Data Zone deployment in Sweden Central, and the database in the same region, which covers Europe. For North America, the Middle East and Asia-Pacific, legal must confirm per country whether a central EU deployment is allowed. Where it is not, the same container, configuration and model are deployed in a second region with its own database: a deployment, not a rebuild (about one engineer-week each, *assumption*).

## 6. Languages

The model works in many languages and the profile keeps the employee's own words. Two parts need work per language: the code's word lists (yes, no, "the ones you listed", "the same everywhere") in the company configuration, and the wording of questions and reports. Each language is released only after the evaluation personas, translated, pass the same targets as in English. Order follows the rollout (section 10), so a language is tested when its first region starts, not all at once.

## 7. Reliability and scale

- **More than one replica** needs shared state for rate limits (Redis or Cosmos-based counters).
- **Long calls:** *Finish* (34–48 s in the evaluation) and document reading move to submit-and-poll (202 + status), so no request depends on the ingress timeout.
- **Alerts:** 5xx rate, model error rate, turns that hit the fallback question, daily budget at 80 %.
- **Runbook:** a stuck session is diagnosed from the turn log (focus field, ask count, still missing); the limits make a true loop impossible, so most incidents are model or quota errors.
- **Scale:** a few thousand sessions a year is small for Cosmos DB and one model deployment. Cross-partition workspace queries are fine at that size; beyond it, a daily overview export replaces them.

## 8. AI quality

- The model version is already pinned (deployment set to no auto-upgrade); any model upgrade or prompt change must pass the **evaluation set** (field quality, employee time, loops, cost) before release, as a CI gate.
- Grow the evaluation set from real, anonymised pilot sessions, with the specialist's corrections as the truth, and run each persona two or three times before reading a change.
- Tune on pilot data first where the evaluation shows the gaps: employee time (above 20 minutes) and *Finish* speed (above 30 s).
- Cost dashboard per session and per cluster from the turn log.

## 9. Cost at scale

| Cost a year | Low (200 processes) | Mid (400, base case) | High (800) | Basis |
|---|---|---|---|---|
| Model calls | about €150 | about €300 | about €600 | **Measured** €0.34–0.50 per interview in the evaluation (at assumed list prices), × 1.5 interviews per profiled process (*assumption*: restarts and unfinished sessions) |
| Container Apps (2+ replicas), Cosmos DB serverless, private networking, monitoring | about €6k | about €6k | about €7k | *Assumption* from the use case; the prototype runs for about €15–40 a month |
| Support and upkeep | about €25k | about €25k | about €25k | About 0.2 of an engineer (*assumption*) |
| Evaluation runs, language testing, margin | about €4k | about €4k | about €4k | *Assumption* |
| **Total** | **about €35k** | **about €35k** | **about €37k** | The use case's €35k a year |

The model is the smallest line: even at High it stays under €1k a year, and the daily token budget caps abuse. The run cost is people, not compute, so it barely moves with volume.

## 10. Trust and rollout

**Trust of users who did not ask for the tool.** Most employees did not ask for an AI interview, and some will fear it measures them. Adoption rests on four things:
- **Something back for them:** the employee keeps their own report, with their workflow mapped and where AI could save them time, which they can take to their manager. It is a way to raise their own idea, not a survey.
- **Processes, not people:** no individual's time or performance is reported, agreed in writing with HR and the works council, and said in the first message.
- **Consent and control:** the welcome says who reads the conversation and why; nothing from a document or Microsoft 365 counts until the employee confirms it; "delete my data" works.
- **Launched by people they know:** the link comes from Teams and the intranet through a **champion in each cluster** (a cluster lead or specialist), with a short campaign, not a mandate.

**Rollout across teams, projects and countries.**

| Phase | Scope | Gate to the next |
|---|---|---|
| Pilot (8 weeks) | One cluster in one European region, about 20 processes | The three kill tests pass (section 1) |
| Production hardening (one quarter) | Sections 3–8; the pilot cluster moves to production | Security review, evaluation gate green, agreement signed |
| Cluster by cluster | The other clusters of the first region, through their champions | Completion and acceptance rates hold per cluster |
| Region by region | One region at a time, each with its language tested and its residency and works-council position settled | Same, per region |

Each new cluster or region is **configuration, not code**: process areas, solution catalogue, wording, language words and retention live in the company configuration.

## 11. Ownership, support and on-call

| Role | Owns |
|---|---|
| Product owner (AI transformation team) | Field wording, process areas, solution catalogue, readiness thresholds, rates: the company configuration; the pilot measures |
| Engineering owner (IT platform) | Code, deployment, model versions, the evaluation set and its gate |
| Cluster champions | Launch, campaigns and first-line questions in their cluster |
| Support | IT's platform team in office hours, through the normal service desk. **No 24/7 on-call:** no system of record depends on the tool, and an interview can resume later. Model or quota incidents follow the runbook (section 7) |
