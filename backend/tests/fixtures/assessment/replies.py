"""Scripted model replies for the cost-review fixture: the OPPORTUNITIES and MAP examples of spec 18.

Why: the grounding tests, the call tests and the orchestrator tests (spec 20) all need the same
worked replies, and a copy in each file would drift from the spec's examples. Each function returns a
fresh dict, so a test can damage its own copy without touching another test's.
What: `opportunities_reply()` is the §3.5 reply (six opportunities: four grounded, one citing step 7,
one quoting words nobody said; one stay-human entry); `map_reply()` is the §3.8 reply (a "Totals
match SAP?" gateway after step 2 that loops back to step 1, plus an invented "Finance Bot" lane).
Must not: be edited to make a failing test pass; the spec examples are the contract.
"""

from __future__ import annotations

from typing import Any


def _opportunity(
    title: str, steps: list[int], kind: str, impact: str, feasibility: str, evidence: str
) -> dict[str, Any]:
    return {
        "title": title,
        "steps": steps,
        "type": kind,
        "what_changes": f"{title}: the step runs with less manual work.",
        "how": "A generic tool category grounded in the systems the profile names.",
        "prepare_first": "Agree one template across sites.",
        "impact": impact,
        "impact_reason": "The pain the expert describes.",
        "feasibility": feasibility,
        "feasibility_reason": "The systems are already in use.",
        "evidence": evidence,
    }


def opportunities_reply() -> dict[str, Any]:
    """Spec 18 §3.5: o1–o4 survive; one `step` drop and one `quote` drop."""
    return {
        "summary": "Most of the time goes into copying site numbers by hand; reading the files is the biggest lever.",
        "opportunities": [
            _opportunity(
                "Read the site spreadsheets into the master file",
                [1, 2],
                "document_ai",
                "high",
                "medium",
                "I copy the numbers into the master file by hand",
            ),
            _opportunity(
                "Draft the variance summary",
                [5],
                "ai_assistant",
                "medium",
                "high",
                "I write the commentary from scratch every month",
            ),
            _opportunity(
                "Chase variance explanations automatically",
                [4],
                "workflow",
                "medium",
                "high",
                "some site managers answer only after three reminders",
            ),
            _opportunity(
                "Link SAP to the reporting tool",
                [7],
                "integration",
                "high",
                "high",
                "I copy the numbers into the master file by hand",
            ),
            _opportunity(
                "Agree one site template",
                [1],
                "standardise",
                "medium",
                "high",
                "each site sends its own spreadsheet layout",
            ),
            _opportunity(
                "Restart the crashing system with a bot", [2], "rpa", "high", "high", "the system crashes every day"
            ),
        ],
        "stay_human": [
            {
                "steps": [5],
                "reason": "The commentary to the CFO is the controller's judgement; a person decides what to say",
                "evidence": "write the commentary",
            }
        ],
    }


def _node(node_id: str, node_type: str, label: str, lane: int, step: int | None, marker: str) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "label": label, "lane": lane, "step_index": step, "marker": marker}


def _flow(source: str, target: str, label: str = "", is_default: bool = False) -> dict[str, Any]:
    return {"source": source, "target": target, "label": label, "is_default": is_default}


def map_reply() -> dict[str, Any]:
    """Spec 18 §3.8: a loop from a gateway after step 2 back to step 1, and an invented lane."""
    return {
        "lanes": ["Cost controller", "Finance Bot"],
        "nodes": [
            _node("start", "start", "Month-end close completed", 0, None, "timer"),
            _node("t1", "task", "Collect", 1, 1, "user"),
            _node("t2", "task", "Consolidate", 0, 2, "user"),
            _node("g1", "gateway", "Totals match SAP?", 0, None, "exclusive"),
            _node("t3", "task", "Analyse", 0, 3, "user"),
            _node("t4", "task", "Chase", 0, 4, "send"),
            _node("t5", "task", "Write", 0, 5, "user"),
            _node("end", "end", "Cost report sent", 0, None, "message"),
        ],
        "flows": [
            _flow("start", "t1"),
            _flow("t1", "t2"),
            _flow("t2", "g1"),
            _flow("g1", "t3", "yes"),
            _flow("g1", "t1", "no"),
            _flow("t3", "t4"),
            _flow("t4", "t5"),
            _flow("t5", "end"),
        ],
    }
