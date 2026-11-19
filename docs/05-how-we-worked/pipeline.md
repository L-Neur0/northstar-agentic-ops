# How we worked: our pipeline

> How this project went from a brief to a running prototype. The method used to choose the use case is in [framework/](framework/assessment-framework.md).

## 1. From brief to use case

1. **Candidates.** We listed workflows across NIG's nine clusters and scored them with our [assessment framework](framework/assessment-framework.md): six gates (allowed, real pain, no off-the-shelf tool, data exists, measurable, one-sentence hook) and six scores (ROI, scalability, adoption, feasibility, cost, risk).
2. **Choice.** We kept the one that is NIG's first stated need and serves every other cluster: finding, mapping and assessing processes for AI ([use case](../01-use-case/use-case.md)).
3. **Attack.** We reviewed our own case for weak points before building (use case §2.1.8).

## 2. From use case to code

Every fact has one home, and changes flow downward:

```
use case (why) → product spec (what) → architecture (how, overall) → component spec (how, in detail) → tests → code
```

Each piece of work follows the same loop:

| Step | What happens | Output |
|---|---|---|
| 1 · Inspect | Read the product spec, the architecture, the specs it depends on, and the code it touches | Notes on what changes and what must not break |
| 2 · Specify | Write the component spec: behaviour, interfaces, implications, acceptance criteria | `specs/NN-*.md`, reviewed before any code |
| 3 · Test first | Each acceptance criterion becomes a failing test that cites its ID | Red tests |
| 4 · Implement | Smallest code that passes, then refactor | Green tests |
| 5 · Verify | Lint, types, tests, a real run; the evaluation set for AI behaviour | Evidence, spec status updated |
| 6 · Review | A person checks the result before it is committed | One commit per reviewed step |

## 3. How we know it works

- **Unit tests** on the pure core: the field rules, the interview phases and limits, the calculators.
- **Scripted conversations** that prove no interview can loop forever.
- **An evaluation set** of simulated experts with hidden true processes, run through the real API: field accuracy, turns to *Finish*, loops, cost. Results go into the technical design.

## 4. Tools

Modern AI tooling is part of the method: an AI coding assistant writes specs and code with us, under the same loop. A person reviews every spec before it is built and every step before it is committed.
