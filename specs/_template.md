# NN · Title

> **Status:** draft · **Implements:** F-xx, F-yy (product), §n (architecture) · **Depends on:** specs NN, NN
> **Code:** `backend/app/services/process_discovery/<layer>/...` · **Tests:** `backend/tests/unit/process_discovery/<layer>/...`

## 1. Purpose

Two or three sentences: what this component does and why it exists.

## 2. Where it sits

- **Layer** and what it may import (architecture §3).
- **What exists today** that this builds on (modules, models, config).
- **What it changes** in existing code, if anything.

## 3. Behaviour

Numbered, concrete rules. Use tables for mappings and limits. Give at least one worked example with real values.

1. …
2. …

## 4. Interfaces

Public functions, Pydantic models, routes or config keys, with signatures and short descriptions. Only what other components use.

```python
def example(arg: Type) -> Result: ...
```

## 5. Implications

- **Other components:** what they must do or may assume.
- **Data:** fields added or changed on the session document.
- **Config:** keys added.
- **Security and privacy:** anything that touches untrusted text, roles or personal data.
- **Cost and latency:** model calls added, if any.

## 6. Acceptance criteria

| ID | Given / when / then |
|---|---|
| AC-NN.1 | Given …, when …, then … |
| AC-NN.2 | … |

## 7. Test plan

| Test file | Covers |
|---|---|
| `tests/unit/.../test_x.py` | AC-NN.1–NN.3 |

## 8. Out of scope

What this spec deliberately does not do, and where it is handled.

## 9. Open questions

| # | Question | Default until decided |
|---|---|---|
