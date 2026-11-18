# Implementation specs

> One spec per component, each with acceptance criteria that become tests (spec-driven, test-driven development).
> Source: [the use case](../docs/01-use-case/use-case.md), §2.2 and §4. Start with [00 · Architecture overview](00-architecture.md).

| # | Spec | Covers | Status |
|---|---|---|---|
| 00 | [`00-architecture.md`](00-architecture.md) | The app on one page: frontend, backend, core, AI, database, Azure | draft |
| 01 | `01-data-dictionary.md` | The fixed variables, shared by tenders and past projects; outcomes and overrun reasons | to write |
| 02 | `02-analysis-recipe.md` | The 7 fixed steps: profile → comparables → scale → ranges → flags → reasons → price view | to write |
| 03 | `03-synthetic-data.md` | The fictional data generator: past projects, past tenders, new tenders, Millbrook plan, ground truth | to write |
| 04 | `04-tender-reader.md` | The AI runner and playbook: tender PDF → bid profile with pages and quotes | to write |
| 05 | `05-comparables-and-plan-check.md` | Similar-project finder and phase-by-phase plan check | to write |
| 06 | `06-price-view.md` | Margin, chance of a loss, competitor panel, expected score | to write |
| 07 | `07-bid-workspace.md` | The four tabs, approval pack, Excel export, audit log | to write |
| 08 | `08-evaluation.md` | Reading accuracy against ground truth; backtest | to write |
| 09 | `09-deployment.md` | Docker, Azure Container Apps, CI, secrets, logs | to write |
