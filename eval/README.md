# Evaluation

This folder is part of the [AI Use Case Discovery Agent](../README.md). In the evaluation, simulated employees play the real interview through the API. Each one is given a hidden "true" process, and code then scores what the product captured against that truth.

| Path | What it is |
|---|---|
| `personas/` | Six simulated employees: a cooperative cost controller, a vague service-desk lead, a coordinator with a mixed week, an analyst with an outdated document, a recruiter who screens CVs, and a maintenance planner |
| `evalkit/` | The runner, the simulated employee, the scoring code, a narrow judge model for free text, and the scorecard |
| `reports/latest.md` | The most recent full scorecard. An older quick run is kept next to it because spec 24 refers to it |
| `demo_session.py` | Turns a finished run into a demo session that is ready for *Finish* |

**What is scored:** how much of the hidden truth the report got right, how much of the employee's time the interview took, how many low-value questions were asked, the AI fit and route for each step, loops, invented values, whether the hours could be computed, and the cost of each session. Before every run, the judge is checked against pairs that were labelled by hand.

The latest scorecard does not meet every target yet. It is kept as it is, because it shows honestly where the interview still needs work.

```bash
make eval            # all personas (needs Azure OpenAI)
make eval QUICK=1    # only the two quick personas
make test-eval       # tests for the evaluation code itself, which make no model calls
```
