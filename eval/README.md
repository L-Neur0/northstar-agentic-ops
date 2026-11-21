# Evaluation

Simulated employees play the real interview through the API, and code scores what the product captured against the truth they were given.

| Path | What it is |
|---|---|
| `personas/` | Six simulated employees, each with a hidden true process: a cooperative cost controller, a vague service-desk lead, a coordinator with a mixed week, an analyst with an outdated document, a recruiter screening CVs, a maintenance planner |
| `evalkit/` | The runner, the simulated expert, scoring by code, a narrow judge model for free text, the scorecard |
| `reports/latest.md` | The last full scorecard |
| `demo_session.py` | Turns a finished run into a ready-to-finish demo session |

**What is scored:** how much of the hidden truth the report got right, the employee's time, how many low-value questions were asked, the AI fit and route per step, loops, invented values, whether hours could be computed, and cost per session. The judge is checked against hand-labelled pairs before every run.

```bash
make eval            # all personas (needs Azure OpenAI)
make eval QUICK=1    # the two quick personas
make test-eval       # the evaluation code's own tests, no model calls
```
