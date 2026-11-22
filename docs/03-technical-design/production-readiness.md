# Production readiness: from prototype to a company-wide tool

> **Status:** final, November 2026 (brief task 3). Effort and cost figures are *assumptions*, marked as such, to confirm with NIG's platform team and in the pilot.
> The prototype is deliberately open (anyone with the link) and small (one container, one replica, read-only workspace, English). This page lists what changes for production at NIG across teams, projects and countries, why, how much work it is and who owns it.

## 1. The honest estimate

**This needs about four months and these three things:**

1. **A data-protection sign-off and a works-council agreement in the first region**, both started on day one. The sign-off comes before the pilot, which interviews volunteers only; the agreement is prepared in parallel and gates the rollout beyond the pilot cluster, not the pilot: it is the critical path, not the code.
2. **One engineer for about two months of work (6.5 engineer-weeks, about €20k)**, spread over the four months: Entra ID sign-in before the pilot, fixes during it, then hardening (private network, two replicas, *Finish* as a background job, monitoring, evaluation gate, one more language). The prototype is already built, tested and live, so this is the remaining production work only; Microsoft 365 evidence and specialist edits are later releases.
3. **Named owners**: a product owner in the AI transformation team, an engineering owner in IT's platform team, and a champion in each cluster who launches the tool with their teams.

| When | What | Who |
|---|---|---|
| Weeks 1–2 | Entra ID sign-in, consent text, data-protection sign-off for a volunteer pilot, works-council talks started | 1 engineer; data protection officer, HR |
| Weeks 3–10 | **8-week pilot**: one cluster in one region, about 20 processes, with volunteers, on the current build plus sign-in. Three kill tests: share of employees who finish (stop below 50 %), share of reports a specialist accepts without major edits (stop below 50 %), specialist review time (stop above 3 h) | Product owner, 1–2 specialists, 1 engineer part-time for fixes and prompt tuning on pilot data |
| Weeks 11–18 | **Production hardening, about two months** (sections 3–8: private network, reliability, monitoring, one more language), then the first cluster-region goes live in production; the works-council agreement is prepared in parallel | 1 engineer (about 3–4 weeks of work); NIG's security team reviews |
| After that | **Rollout by configuration**, cluster by cluster and region by region (section 10) | Product owner, champions; no new code per region |

**Build cost, bottom-up** (*assumptions*, updated 2026-11-21; the €20k is the product owner's decision, the lines show what it buys):

| Work item (remaining production work only) | Engineer-weeks |
|---|---|
| Entra ID sign-in: app registration, MSAL, token validation, roles on the server, claiming visitor sessions, per-user quota (section 3) | 1.5 |
| Private network and secrets: VNet, private endpoints, Front Door with WAF, Key Vault, approval before production (section 4) | 1 |
| Reliability: two replicas, shared rate-limit counters, *Finish* and document reading as background jobs (section 7) | 1 |
| Monitoring: alerts, cost dashboard, runbook, one restore test (sections 5, 7) | 0.5 |
| Evaluation gate in CI and one more language tested with translated personas (sections 6, 8) | 0.5 |
| Pilot support: fixes and prompt tuning on pilot data, part-time over the 8 weeks | 1 |
| Buffer, about 20 % | 1 |
| **Total** | **6.5 × €3k ≈ €20k** |

Not in the €20k: the security review (by NIG's security team, *assumption*), the data-protection and works-council work (people, not code: data protection officer, HR), and later releases (Microsoft 365 evidence, specialist edits, integrations). The €3k per engineer-week is the use case's build rate (about €75 an hour); valued at the €90 an hour used for the savings, the same 6.5 weeks cost about €23k, and the payback stays under a month.

**Full first-year cost, NIG's people included** (*assumptions*, at €90 an hour; these people exist already, so this is time, not new spend):

| Item | Hours | Cost |
|---|---|---|
| Build (above) and run for a year (section 9) | | €26k |
| Security review by NIG's security team | about 40 | about €4k |
| Data-protection impact assessment and works-council agreement, first region (data protection officer, HR, legal) | about 120 | about €11k |
| Pilot: product owner, specialists' reviews and training, volunteers' interviews, the cluster champion | about 120 | about €11k |
| Product owner's configuration and follow-up for the rest of the year (about 0.1 of a role) | about 160 | about €14k |
| **Total, year one** | | **about €66k** |

Against €450k of conservative value this is a payback of about two months and about €7 back per €1 in year one (€17 with the build and run cost alone).

This is the €20k build and the about €6k a year run (section 9) of the use case: about two months of one engineer's work, spread over about four calendar months (two weeks of set-up, the 8-week pilot, about two months of hardening) because the pilot sets the pace, not the code. The works-council agreement runs in parallel and gates the rollout to further clusters and regions.

## 2. Summary

| Area | Prototype | Production | Effort |
|---|---|---|---|
| Identity and access | Open link, visitor key, workspace access code with a typed name | **Entra ID single sign-on**, roles from app roles, named attribution of every action, per-user quotas | S–M |
| Network and secrets | Public ingress, managed identity | Private endpoints, VNet integration, WAF in front, Key Vault for anything not covered by managed identity | S |
| Data access and protection | Interview and uploaded documents; one EU region; no files stored | Microsoft 365 evidence with consent; impact assessment, works-council agreement, residency and retention per country, tested restore | M–L (mostly people, not code) |
| Reliability | One replica, *Finish* in one long request | 2+ replicas, shared rate-limit store, *Finish* and document reading as background jobs, alerts and runbook | S–M |
| AI quality and cost | gpt-5.6-sol (EU Data Zone), version pinned (no auto-upgrade), six-persona evaluation, daily budget | Planned version upgrades, evaluation gate before every model or prompt change, evaluation set from pilot sessions, cost dashboard | S–M |
| Languages | English; yes/no words in English and German | Tested interviews and reports in each NIG language | S per language |
| Workspace | Read-only: sessions, conversations, report v2 and PDF | Specialist edits and validation, overview across sessions, implementation briefs | M (later release) |
| Integrations | None with NIG systems | Launch from Teams and the intranet; report export to NIG's BPM tool; briefs to the engineering backlog | S each (later release) |
| Operations | The author | Product owner, engineering owner, support within IT's platform team | People |

*S = days, M = 2–4 weeks, L = a quarter, for one engineer. The rows the €20k build covers are itemised in section 1.*

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

*Updated 2026-11-21 (bottom-up cost).* The run cost is what NIG pays Azure: hosting and the AI. All lines are *assumptions* at Azure list prices (EUR ≈ USD) unless marked measured.

| Cost a year | Low (200 processes) | Mid (400, base case) | High (800) | Basis |
|---|---|---|---|---|
| **AI:** model calls | about €120 | about €240 | about €480 | **Measured** €0.34–0.50 per interview in the evaluation; €0.40 × 1.5 interviews per profiled process (*assumption*: restarts and unfinished sessions), so 600 interviews at Mid |
| **Hosting:** Container Apps, 2 replicas always on | about €0.9k | about €0.9k | about €0.9k | 0.5 vCPU and 1 GiB each: about €70 a month after the monthly free grant |
| Cosmos DB serverless, continuous backup (7 days) | about €0.1k | about €0.1k | about €0.2k | A few thousand small documents a year: under €10 a month in request units and storage |
| Application Insights and Log Analytics | about €0.2k | about €0.2k | about €0.3k | A few GB of logs a month at about €2.3 per GB after the free 5 GB; capped at 0.5 GB a day (spec 25) |
| Front Door Premium with WAF | about €4k | about €4k | about €4k | About €330 a month base fee; Premium is needed for a private origin and managed WAF rules. The largest line |
| Private endpoints (Cosmos DB, Azure OpenAI, Key Vault), Key Vault, Container Registry | about €0.3k | about €0.3k | about €0.3k | About €7 a month per private endpoint, about €5 a month for the registry |
| **Total** | **about €5.6k** | **about €5.8k** | **about €6.1k** | The use case's run cost: **about €6k a year** |

Support and upkeep are done by IT's existing platform team (section 11) and are not counted, nor is the product owner's configuration time or language testing for each new region (paid at rollout).

The AI is the smallest line: about €240 a year at Mid, under €0.5k even at High, and the daily token budget caps abuse. The run cost is mostly the WAF in front, so it barely moves with volume.

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
| Production hardening (about two months) | Sections 3–8; the pilot cluster moves to production | Security review, evaluation gate green, agreement signed |
| Cluster by cluster | The other clusters of the first region, through their champions | Completion and acceptance rates hold per cluster |
| Region by region | One region at a time, each with its language tested and its residency and works-council position settled | Same, per region |

Each new cluster or region is **configuration, not code**: process areas, solution catalogue, wording, language words and retention live in the company configuration.

**Rough cost to reach all 36 teams** (*assumption*): after the first cluster-region, the other clusters of that region are configuration and champions' time only. Each further region needs about **1.5 engineer-weeks** (its language tested with translated personas, a regional deployment if residency requires it) and its own works-council and data-protection work (about 120 hours of people time). For the three further regions: about **4.5 engineer-weeks (€14k) and about €33k of people time**, at one region a quarter, so **all 36 teams in about 12–15 months** from the start. The run cost grows by about €5k a year for each extra regional deployment, mostly the WAF.

## 11. Ownership, support and on-call

| Role | Owns |
|---|---|
| Product owner (AI transformation team) | Field wording, process areas, solution catalogue, readiness thresholds, rates: the company configuration; the pilot measures |
| Engineering owner (IT platform) | Code, deployment, model versions, the evaluation set and its gate |
| Cluster champions | Launch, campaigns and first-line questions in their cluster |
| Support | IT's platform team in office hours, through the normal service desk. **No 24/7 on-call:** no system of record depends on the tool, and an interview can resume later. Model or quota incidents follow the runbook (section 7) |
