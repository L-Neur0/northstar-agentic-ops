# Production readiness: from prototype to a company-wide tool

> **Status:** working notes for the technical design (brief task 3) and the interview discussion. Effort estimates are *assumptions*.
> The prototype is deliberately open (anyone with the link) and small (one container, one replica). This page lists what changes for production at NIG, why, and roughly how much work it is.

## 1. Summary

| Area | Prototype | Production | Effort |
|---|---|---|---|
| Identity and access | Open link, visitor key, workspace access codes with a typed name | **Entra ID single sign-on**, roles from app roles, named attribution of every edit and action, per-user quotas | M |
| Network and secrets | Public ingress, managed identity | Private endpoints, VNet integration, WAF in front, Key Vault for anything not covered by managed identity | M |
| Data protection | One region, TTL, no files stored | Data protection impact assessment, works-council agreement, retention per country, backup and restore tested | M–L (mostly people, not code) |
| Reliability | One replica, synchronous turns | 2+ replicas, shared rate-limit store, asynchronous long calls, alerts and runbook | M |
| AI quality and cost | Small model, evaluation set, daily budget | Model-version pinning, evaluation check before release on every model or prompt change, per-user token quota, cost dashboard | S–M |
| Languages | English demo, yes/no words in EN/DE | Tested interviews in each NIG language, translated reports | M per language |
| Operations | The author | A named product owner (AI transformation team), an engineering owner, on-call within IT's platform team | People |
| Integrations | None | Launch from Teams/intranet; export reports to NIG's BPM tool; push briefs to the engineering backlog | S each |

*S = days, M = 2–4 weeks, L = a quarter, for one engineer.* Rough total: **about one quarter with two engineers** (the €100k build in the use case, §2.1.6), with language testing and a security review; the data-protection agreements run in parallel and are the real critical path, not the code.

## 2. Identity and access: Entra ID

**Why not in the prototype:** reviewers and pilot users outside NIG's tenant must be able to open the demo. **Why it is required in production:** reports describe how real teams work; access must follow the company's identity, leavers must lose access, and every action must be attributable.

| Piece | Design |
|---|---|
| App registration | One registration: SPA platform (redirect URIs per environment), exposed API scope `access_as_user`, app roles `Discovery.Specialist` and `Discovery.Engineer`; experts need no role. "Assignment required" off for experts, roles assigned through groups |
| Frontend | MSAL (authorization code flow with PKCE); token for the API scope attached to every request; the visitor key disappears |
| Backend | Validate every bearer token: signature against the tenant's signing keys (cached, **refreshed when an unknown key id appears**), issuer, audience, expiry. `CurrentUser {oid, name, roles}` replaces the visitor key and the workspace code; the owner id becomes the Entra object id |
| Roles | Specialist and engineer from the `roles` claim; checked on the server for every workspace route (the screen only hides) |
| Dev and test | A signed dev token accepted **only** when the deployment stage is explicitly `local` or `test`. The stage is a setting, never guessed from the environment (guessing it is how a test bypass ends up accepted in production) |
| Migration | Sessions made with a visitor key can be claimed once by a signed-in user through the resume link |
| Quotas | Per-user token quota over a rolling window, on top of the global daily budget |

## 3. Network and secrets

- Private endpoints for Cosmos DB and Azure OpenAI; local (key) authentication stays disabled.
- Container Apps environment in a VNet; public entry only through Front Door with WAF, or internal only if the tool is intranet-only.
- Key Vault for any secret not covered by managed identity (for example the monitoring connection string); referenced by the container app, never in code or CI.
- CI deploys with OIDC federation (already the case) and a **manual approval** before production.

## 4. Data protection

- **Processes, not people** is a product rule; in production it needs a written agreement with HR and works councils (Europe first) before rollout.
- Data protection impact assessment: what the conversation and documents may contain, who sees what, retention. The prototype lets specialists read full conversations to improve the interview; production needs explicit consent text, a purpose limit, access logging and a retention rule for that access.
- Region: an EU region that hosts the chosen model; data residency per country checked.
- Retention per country (default 90 days for unfinished sessions); "delete my data" already exists.
- Backups: Cosmos continuous backup; restore tested once per quarter.

## 5. Reliability and scale

- **More than one replica** needs shared state for rate limits and caches (Redis or Cosmos-based counters).
- **Long calls:** the *Finish* assessment and document reading move to submit-and-poll (202 + status), so no request depends on the ingress timeout.
- **Alerts:** 5xx rate, model error rate, turns that hit the fallback question, daily budget at 80%.
- **Runbook:** a stuck session is diagnosed from the turn log (focus field, ask count, still missing); the limits make a true loop impossible, so most incidents are model or quota errors.
- Cross-partition workspace queries are fine for thousands of sessions; beyond that, a read model (for example a daily overview export) replaces them.

## 6. AI quality and cost

- Pin the model version; any model or prompt change must pass the **evaluation set** (field accuracy, loops, cost) before release.
- Grow the evaluation set from real, anonymised pilot sessions, with the specialist's corrections as the truth.
- Cost dashboard per session and per cluster from the turn and artefact logs.
- Re-check that the small model is still enough per language.

## 7. Ownership

| Role | Owns |
|---|---|
| Product owner (AI transformation team) | Field wording, taxonomy, readiness thresholds, rates: the company configuration |
| Engineering owner (IT platform) | Code, deployment, model versions, the evaluation set |
| Support | IT's platform team, office hours; no 24/7 need (no system of record depends on it) |
