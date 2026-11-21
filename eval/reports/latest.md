# Evaluation scorecard 20261121-094609

**FAIL**: p01-cooperative: employee time (min) 24.4 (target ≤ 20); p01-cooperative: Finish time (s) 43.69 (target < 30); p02-vague: employee time (min) 22.7 (target ≤ 20); p02-vague: invented values 4 (target 0); p02-vague: Finish time (s) 36.94 (target < 30); p03-task-mixed-week: wasted turns 4 (target ≤ 3); p03-task-mixed-week: Finish time (s) 34.09 (target < 30); p03-task-mixed-week: steering False (target hit); p04-stale-document: employee time (min) 24.1 (target ≤ 20); p04-stale-document: Tier A + core quality 54% (target ≥ 85%); p04-stale-document: step fit 67% (target ≥ 70%); p04-stale-document: step route 67% (target ≥ 70%); p04-stale-document: conflicts 0 (target ≥ 1); p04-stale-document: Finish time (s) 47.82 (target < 30); p05-cv-screening: employee time (min) 23.3 (target ≤ 20); p05-cv-screening: Tier A + core quality 72% (target ≥ 85%); p05-cv-screening: step fit 67% (target ≥ 70%); p05-cv-screening: step route 67% (target ≥ 70%); p05-cv-screening: criteria asked 0% (target 100%); p05-cv-screening: hours computed 50% (target 100%); p05-cv-screening: Finish time (s) 33.94 (target < 30); p06-work-order-priority: employee time (min) 21.1 (target ≤ 20); p06-work-order-priority: Tier A + core quality 75% (target ≥ 85%); p06-work-order-priority: Finish time (s) 43.86 (target < 30)

| Run | Value |
|---|---|
| Commit | n/a |
| Mode / cache | in-process / off (app, expert) |
| Deployments | app: app-chat, expert: eval-expert, judge: app-chat |
| Judge | judge-v3, agreement 97% (37/38) |

## Headline: employee time, detail burden, Tier A quality, assessment

| Persona | Employee time (min) | Δ | Read / type / think / upload (min) | Avg answer words | Detail burden | Δ | Tier A + core quality | Δ | Fit | Route |
|---|---|---|---|---|---|---|---|---|---|---|
| p01-cooperative | 24.4 (target 20) |  | 5.5 / 16.0 / 2.9 / 0.0 | 23.7 | 12% (3/26) |  | 94% (45/48) |  | 5/5 | 5/5 |
| p02-vague | 22.7 (target 20) |  | 5.8 / 13.2 / 3.6 / 0.0 | 17.7 | 10% (3/29) |  | 78% (31/40) |  | 2/2 | 2/2 |
| p03-task-mixed-week | 19.6 (target 20) |  | 5.7 / 10.6 / 3.4 / 0.0 | 13.2 | 6% (2/31) |  | 75% (30/40) |  | 2/2 | 2/2 |
| p04-stale-document | 24.1 (target 20) |  | 5.8 / 14.8 / 3.1 / 0.3 | 19.8 | 7% (2/29) |  | 54% (26/48) |  | 2/3 | 2/3 |
| p05-cv-screening | 23.3 (target 20) |  | 5.4 / 14.8 / 3.1 / 0.0 | 21.9 | 12% (3/26) |  | 72% (23/32) |  | 2/3 | 2/3 |
| p06-work-order-priority | 21.1 (target 20) |  | 5.2 / 13.1 / 2.8 / 0.0 | 20.1 | 8% (2/25) |  | 75% (30/40) |  | 4/4 | 4/4 |
| **Pooled** | 22.5 mean | | | | 9% | | 75% | | | |

Employee time is an estimate from the words on the screen; speeds and think times are assumptions (`eval/employee_time.yaml`). Tiers: `eval/tiers.yaml`.

## Also reported

| Persona | Report quality | Δ | Code-only | Rest quality | Messages to Finish | Δ | Efficiency | Δ | Wasted | Plateaus |
|---|---|---|---|---|---|---|---|---|---|---|
| p01-cooperative | 92% (70/76) |  | 70% | 89% | 27 |  | 2.59 |  | 0 | 0 |
| p02-vague | 80% (51/64) |  | 52% | 83% | 30 |  | 1.70 |  | 1 | 0 |
| p03-task-mixed-week | 72% (46/64) |  | 58% | 67% | 32 |  | 1.44 |  | 4 | 1 |
| p04-stale-document | 61% (46/76) |  | 47% | 71% | 30 |  | 1.53 |  | 1 | 0 |
| p05-cv-screening | 70% (37/53) |  | 53% | 67% | 27 |  | 1.37 |  | 0 | 0 |
| p06-work-order-priority | 72% (47/65) |  | 54% | 68% | 26 |  | 1.81 |  | 0 | 0 |
| **Pooled** | 75% | | 56% | | 172 messages | | | | | |

## Targets

| Persona | Target | Value | Goal | Result | Δ |
|---|---|---|---|---|---|
| p01-cooperative | employee time (min) | 24.4 | ≤ 20 | ✗ |  |
| p01-cooperative | detail burden | 12% | ≤ 15% | ✓ |  |
| p01-cooperative | Tier A + core quality | 94% | ≥ 85% | ✓ |  |
| p01-cooperative | step fit | 100% | ≥ 70% | ✓ |  |
| p01-cooperative | step route | 100% | ≥ 70% | ✓ |  |
| p01-cooperative | session finished (safety net 80) | finished | finished | ✓ |  |
| p01-cooperative | wasted turns | 0 | ≤ 3 | ✓ |  |
| p01-cooperative | plateaus | 0 | 0 (flag) | ✓ |  |
| p01-cooperative | loops | 0 | 0 | ✓ |  |
| p01-cooperative | repeated questions | 0 | ≤ 2 | ✓ |  |
| p01-cooperative | invented values | 0 | 0 | ✓ |  |
| p01-cooperative | stale kept | 0 | 0 | ✓ |  |
| p01-cooperative | criteria asked | 100% | 100% | ✓ |  |
| p01-cooperative | hours computed | 100% | 100% | ✓ |  |
| p01-cooperative | conflicts | 0 | ≥ 0 | ✓ |  |
| p01-cooperative | turn time median (s) | 4.23 | < 10 | ✓ |  |
| p01-cooperative | turn time max (s) | 7.92 | < 150 | ✓ |  |
| p01-cooperative | Finish time (s) | 43.69 | < 30 | ✗ |  |
| p01-cooperative | app cost per session (€) | 0.3893 | < 0.50 | ✓ |  |
| p01-cooperative | cluster | True | hit | ✓ |  |
| p01-cooperative | scope | True | hit | ✓ |  |
| p01-cooperative | steering | True | hit | ✓ |  |
| p02-vague | employee time (min) | 22.7 | ≤ 20 | ✗ |  |
| p02-vague | detail burden | 10% | ≤ 15% | ✓ |  |
| p02-vague | step fit | 100% | ≥ 70% | ✓ |  |
| p02-vague | step route | 100% | ≥ 70% | ✓ |  |
| p02-vague | session finished (safety net 80) | finished | finished | ✓ |  |
| p02-vague | wasted turns | 1 | ≤ 3 | ✓ |  |
| p02-vague | plateaus | 0 | 0 (flag) | ✓ |  |
| p02-vague | loops | 0 | 0 | ✓ |  |
| p02-vague | repeated questions | 0 | ≤ 2 | ✓ |  |
| p02-vague | invented values | 4 | 0 | ✗ |  |
| p02-vague | stale kept | 0 | 0 | ✓ |  |
| p02-vague | criteria asked | 100% | 100% | ✓ |  |
| p02-vague | hours computed | n/a | 100% | n/a |  |
| p02-vague | conflicts | 0 | ≥ 0 | ✓ |  |
| p02-vague | turn time median (s) | 3.92 | < 10 | ✓ |  |
| p02-vague | turn time max (s) | 6.45 | < 150 | ✓ |  |
| p02-vague | Finish time (s) | 36.94 | < 30 | ✗ |  |
| p02-vague | app cost per session (€) | 0.3656 | < 0.50 | ✓ |  |
| p02-vague | cluster | True | hit | ✓ |  |
| p02-vague | scope | True | hit | ✓ |  |
| p02-vague | steering | True | hit | ✓ |  |
| p03-task-mixed-week | employee time (min) | 19.6 | ≤ 20 | ✓ |  |
| p03-task-mixed-week | detail burden | 6% | ≤ 15% | ✓ |  |
| p03-task-mixed-week | step fit | 100% | ≥ 70% | ✓ |  |
| p03-task-mixed-week | step route | 100% | ≥ 70% | ✓ |  |
| p03-task-mixed-week | session finished (safety net 80) | finished | finished | ✓ |  |
| p03-task-mixed-week | wasted turns | 4 | ≤ 3 | ✗ |  |
| p03-task-mixed-week | plateaus | 1 | 0 (flag) | flag |  |
| p03-task-mixed-week | loops | 0 | 0 | ✓ |  |
| p03-task-mixed-week | repeated questions | 0 | ≤ 2 | ✓ |  |
| p03-task-mixed-week | invented values | 0 | 0 | ✓ |  |
| p03-task-mixed-week | stale kept | 0 | 0 | ✓ |  |
| p03-task-mixed-week | criteria asked | n/a | 100% | n/a |  |
| p03-task-mixed-week | hours computed | 100% | 100% | ✓ |  |
| p03-task-mixed-week | conflicts | 0 | ≥ 0 | ✓ |  |
| p03-task-mixed-week | turn time median (s) | 3.86 | < 10 | ✓ |  |
| p03-task-mixed-week | turn time max (s) | 5.87 | < 150 | ✓ |  |
| p03-task-mixed-week | Finish time (s) | 34.09 | < 30 | ✗ |  |
| p03-task-mixed-week | app cost per session (€) | 0.3438 | < 0.50 | ✓ |  |
| p03-task-mixed-week | cluster | True | hit | ✓ |  |
| p03-task-mixed-week | scope | True | hit | ✓ |  |
| p03-task-mixed-week | steering | False | hit | ✗ |  |
| p04-stale-document | employee time (min) | 24.1 | ≤ 20 | ✗ |  |
| p04-stale-document | detail burden | 7% | ≤ 15% | ✓ |  |
| p04-stale-document | Tier A + core quality | 54% | ≥ 85% | ✗ |  |
| p04-stale-document | step fit | 67% | ≥ 70% | ✗ |  |
| p04-stale-document | step route | 67% | ≥ 70% | ✗ |  |
| p04-stale-document | session finished (safety net 80) | finished | finished | ✓ |  |
| p04-stale-document | wasted turns | 1 | ≤ 3 | ✓ |  |
| p04-stale-document | plateaus | 0 | 0 (flag) | ✓ |  |
| p04-stale-document | loops | 0 | 0 | ✓ |  |
| p04-stale-document | repeated questions | 0 | ≤ 2 | ✓ |  |
| p04-stale-document | invented values | 0 | 0 | ✓ |  |
| p04-stale-document | stale kept | 0 | 0 | ✓ |  |
| p04-stale-document | criteria asked | 100% | 100% | ✓ |  |
| p04-stale-document | hours computed | 100% | 100% | ✓ |  |
| p04-stale-document | conflicts | 0 | ≥ 1 | ✗ |  |
| p04-stale-document | turn time median (s) | 4.13 | < 10 | ✓ |  |
| p04-stale-document | turn time max (s) | 17.12 | < 150 | ✓ |  |
| p04-stale-document | Finish time (s) | 47.82 | < 30 | ✗ |  |
| p04-stale-document | app cost per session (€) | 0.4967 | < 0.50 | ✓ |  |
| p04-stale-document | cluster | True | hit | ✓ |  |
| p04-stale-document | scope | True | hit | ✓ |  |
| p04-stale-document | steering | True | hit | ✓ |  |
| p05-cv-screening | employee time (min) | 23.3 | ≤ 20 | ✗ |  |
| p05-cv-screening | detail burden | 12% | ≤ 15% | ✓ |  |
| p05-cv-screening | Tier A + core quality | 72% | ≥ 85% | ✗ |  |
| p05-cv-screening | step fit | 67% | ≥ 70% | ✗ |  |
| p05-cv-screening | step route | 67% | ≥ 70% | ✗ |  |
| p05-cv-screening | session finished (safety net 80) | finished | finished | ✓ |  |
| p05-cv-screening | wasted turns | 0 | ≤ 3 | ✓ |  |
| p05-cv-screening | plateaus | 0 | 0 (flag) | ✓ |  |
| p05-cv-screening | loops | 0 | 0 | ✓ |  |
| p05-cv-screening | repeated questions | 0 | ≤ 2 | ✓ |  |
| p05-cv-screening | invented values | 0 | 0 | ✓ |  |
| p05-cv-screening | stale kept | 0 | 0 | ✓ |  |
| p05-cv-screening | criteria asked | 0% | 100% | ✗ |  |
| p05-cv-screening | hours computed | 50% | 100% | ✗ |  |
| p05-cv-screening | conflicts | 0 | ≥ 0 | ✓ |  |
| p05-cv-screening | turn time median (s) | 4.6 | < 10 | ✓ |  |
| p05-cv-screening | turn time max (s) | 8.85 | < 150 | ✓ |  |
| p05-cv-screening | Finish time (s) | 33.94 | < 30 | ✗ |  |
| p05-cv-screening | app cost per session (€) | 0.3653 | < 0.50 | ✓ |  |
| p05-cv-screening | cluster | True | hit | ✓ |  |
| p05-cv-screening | scope | True | hit | ✓ |  |
| p05-cv-screening | steering | True | hit | ✓ |  |
| p06-work-order-priority | employee time (min) | 21.1 | ≤ 20 | ✗ |  |
| p06-work-order-priority | detail burden | 8% | ≤ 15% | ✓ |  |
| p06-work-order-priority | Tier A + core quality | 75% | ≥ 85% | ✗ |  |
| p06-work-order-priority | step fit | 100% | ≥ 70% | ✓ |  |
| p06-work-order-priority | step route | 100% | ≥ 70% | ✓ |  |
| p06-work-order-priority | session finished (safety net 80) | finished | finished | ✓ |  |
| p06-work-order-priority | wasted turns | 0 | ≤ 3 | ✓ |  |
| p06-work-order-priority | plateaus | 0 | 0 (flag) | ✓ |  |
| p06-work-order-priority | loops | 0 | 0 | ✓ |  |
| p06-work-order-priority | repeated questions | 0 | ≤ 2 | ✓ |  |
| p06-work-order-priority | invented values | 0 | 0 | ✓ |  |
| p06-work-order-priority | stale kept | 0 | 0 | ✓ |  |
| p06-work-order-priority | criteria asked | 100% | 100% | ✓ |  |
| p06-work-order-priority | hours computed | 100% | 100% | ✓ |  |
| p06-work-order-priority | conflicts | 0 | ≥ 0 | ✓ |  |
| p06-work-order-priority | turn time median (s) | 4.19 | < 10 | ✓ |  |
| p06-work-order-priority | turn time max (s) | 8.63 | < 150 | ✓ |  |
| p06-work-order-priority | Finish time (s) | 43.86 | < 30 | ✗ |  |
| p06-work-order-priority | app cost per session (€) | 0.3461 | < 0.50 | ✓ |  |
| p06-work-order-priority | cluster | True | hit | ✓ |  |
| p06-work-order-priority | scope | True | hit | ✓ |  |
| p06-work-order-priority | steering | True | hit | ✓ |  |

## Per persona

| Persona | Cluster | Scope | Steering | Fit | Route | Loops | Repeats | Turn median / max (s) | Finish (s) | Proposals ✓/✎ | App tokens in/out | App € | Expert € | Judge € |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| p01-cooperative | ✓ | ✓ | ✓ | 5/5 | 5/5 | 0 | 0 | 4.23 / 7.92 | 43.69 | 7/0 | 156551/19357 | 0.389 (app-chat) | 0.021 | 0.026 |
| p02-vague | ✓ | ✓ | ✓ | 2/2 | 2/2 | 0 | 0 | 3.92 / 6.45 | 36.94 | 0/0 | 162032/16308 | 0.366 (app-chat) | 0.022 | 0.035 |
| p03-task-mixed-week | ✓ | ✓ | ✗ | 2/2 | 2/2 | 0 | 0 | 3.86 / 5.87 | 34.09 | 8/0 | 163017/13998 | 0.344 (app-chat) | 0.023 | 0.021 |
| p04-stale-document | ✓ | ✓ | ✓ | 2/3 | 2/3 | 0 | 0 | 4.13 / 17.12 | 47.82 | 7/0 | 192303/25630 | 0.497 (app-chat) | 0.024 | 0.049 |
| p05-cv-screening | ✓ | ✓ | ✓ | 2/3 | 2/3 | 0 | 0 | 4.6 / 8.85 | 33.94 | 7/0 | 157873/16800 | 0.365 (app-chat) | 0.020 | 0.028 |
| p06-work-order-priority | ✓ | ✓ | ✓ | 4/4 | 4/4 | 0 | 0 | 4.19 / 8.63 | 43.86 | 8/0 | 143980/16613 | 0.346 (app-chat) | 0.019 | 0.027 |

## Progress curves

```
p01-cooperative        quality  ▁▁▁▂▂▂▂▂▂▂▂▃▃▄▄▄▅▅▅▆▆▇▇▇▇▇▇  10: 18%  20: 68%  27 (Finish): 92%
                       score    ▁▂▂▃▄▅▆▆▇▇█▃▄▄▄▄▅▅▅▆▆▆▇▇▇▇█  10: 89%  20: 68%  27 (Finish): 100%
p02-vague              quality  ▁▂▂▂▂▂▂▂▂▂▂▂▂▃▄▄▄▅▅▅▅▅▆▆▆▆▇▆▇▇  10: 19%  20: 56%  30 (Finish): 80%
                       score    ▁▂▂▃▃▄▄▅▅▅▅▆▆▇▃▄▄▄▅▅▅▅▅▆▆▆▇▇▇█  10: 56%  20: 52%  30 (Finish): 97%
p03-task-mixed-week    quality  ▁▁▁▁▁▁▁▁▁▁▁▁▂▂▂▂▂▂▃▃▃▄▄▄▅▅▅▆▆▆▆▆  10: 6%  20: 30%  30: 70%  32 (Finish): 72%
                       score    ▁▂▂▃▃▃▃▃▃▃▄▄▅▆▆▆▆▃▄▄▄▅▅▅▅▅▆▆▆▇██  10: 28%  20: 38%  30: 83%  32 (Finish): 97%
p04-stale-document     quality  ▁▁▁▂▂▂▂▂▂▂▃▄▄▄▄▄▃▃▄▄▄▄▄▄▅▅▅▅▅▅  10: 20%  20: 38%  30 (Finish): 61%
                       score    ▁▂▂▄▅▅▆▆▆▇▃▃▃▄▄▄▄▄▄▄▄▄▅▅▆▆▆▆▇▇  10: 83%  20: 44%  30 (Finish): 82%
p05-cv-screening       quality  ▁▁▁▂▂▂▂▂▃▃▃▃▄▄▄▄▅▅▅▅▅▅▅▅▆▆▆  10: 25%  20: 62%  27 (Finish): 70%
                       score    ▁▂▂▃▃▃▄▆▆▆▇▃▄▄▄▅▅▅▅▅▆▆▆▇▇▇█  10: 72%  20: 64%  27 (Finish): 97%
p06-work-order-priority quality  ▁▁▁▂▂▂▂▂▂▂▂▂▃▃▄▄▄▄▅▅▅▅▆▆▆▆  10: 17%  20: 57%  26 (Finish): 72%
                       score    ▁▂▂▄▄▅▅▆▆▇▇█▃▄▄▄▅▅▅▆▆▆▆▇▇█  10: 83%  20: 65%  26 (Finish): 100%
```

## Total

Pooled report quality 75% (code-only 56%); 172 expert messages; app € per finished session: 0.385 (prices are an assumption, see `eval/prices.yaml`).

## Worst fields

| Persona | Field | Hidden | Captured | Method | Reason |
|---|---|---|---|---|---|
| p01-cooperative | process.substeps[1].systems | Ledger system; E-mail | ledger system; Excel | code | 'E-mail' not captured |
| p01-cooperative | process.substeps[2].goal | One workbook with every cost centre on the same structure | consolidated cost workbook ready | judge | “Consolidated cost workbook” does not specify that every cost centre is included |
| p01-cooperative | process.substeps[3].goal | Every cost centre variance above the threshold is flagged | variances above 5 percent; draft questions for the sites ready | judge | CAPTURED does not state that every cost centre variance is flagged and adds a se |
| p01-cooperative | process.substeps[3].data | in: consolidated cost workbook; budget; out: variance list with questions | in: actuals; budget file; out: variances above 5 percent; draft questions for th | judge | CAPTURED changes the input to actuals rather than a consolidated cost workbook a |
| p01-cooperative | process.substeps[3].exceptions | none | If codes mismatch, I correct them in Excel. | code | none row on one side only |
| p01-cooperative | process.substeps[4].systems | E-mail; Excel | Excel | code | 'E-mail' not captured |
| p02-vague | process.substeps[1].effort | 3 minutes, each time | it depends. I don’t track step times., each time | never | a number was invented |
| p02-vague | process.substeps[1].decision_type | judgement - you have to read it and get a feel for what the user really means | mix - a mix of judgement and a bit of reading between the lines | code | kind mix vs judgement |
| p02-vague | process.substeps[2].goal | The ticket has the right category and priority | categorised ticket | judge | CAPTURED includes ticket categorisation but omits the required correct priority. |
| p02-vague | process.substeps[2].activities | pick the category; set the priority from the priority matrix | picking the category; picking the priority | judge | Both include category and priority selection, but CAPTURED omits the key require |
