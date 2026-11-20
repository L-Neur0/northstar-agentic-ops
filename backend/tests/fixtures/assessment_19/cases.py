"""The worked-example data of specs 19 and 26 that is not a profile: opportunities, labels, model replies.

Why: the hours, readiness, path, label and step-assessment tests all check the same example (the
monthly cost review, Europe and North America). The profiles are the shared spec 18 fixtures
(`tests/fixtures/assessment/`); what those specs add on top (o1–o4, the §3.4 labels, the §3.2
ratings and the replies the model is scripted to give) is written once here so the tests agree.
What: `eu_opportunities()`, `eu_labels()`, `LABEL_REPLY` (spec 19 §3.4, with one invented input),
`STEPS_REPLY` (spec 26 §3.2) and `example_catalogue()` (a vendor-neutral catalogue holding the ids
of the spec 26 worked example).
Must not: hold a profile (use `tests/fixtures/assessment/profiles.py`), be imported by product
code, or name a real company's tool.
Spec 19 §3.2, §3.4, §3.6; spec 26 §3.2.
"""

from __future__ import annotations

import copy
from typing import Any

from app.core.config import SolutionCatalogue
from app.models.process_discovery_schemas import Opportunity, StepLabels


def eu_opportunities() -> list[Opportunity]:
    """o1–o4 of spec 18 §3.5, as grounding keeps them."""
    rows: list[dict[str, Any]] = [
        {"id": "o1", "title": "Read the site spreadsheets into the master file", "substeps": [1, 2],
         "type": "document_ai", "impact": "high", "feasibility": "medium"},
        {"id": "o2", "title": "Draft the variance summary", "substeps": [5], "type": "ai_assistant",
         "impact": "medium", "feasibility": "high"},
        {"id": "o3", "title": "Chase variance explanations automatically", "substeps": [4], "type": "workflow",
         "impact": "medium", "feasibility": "high"},
        {"id": "o4", "title": "Agree one site template", "substeps": [1], "type": "standardise",
         "impact": "medium", "feasibility": "high"},
    ]  # fmt: skip
    return [Opportunity.model_validate(r) for r in rows]


_LABELS: list[dict[str, Any]] = [
    {"step": 1, "inputs": [
        {"name": "site cost spreadsheets", "format": "digital_document", "evidence": "site cost spreadsheets"},
        {"name": "invoice scans", "format": "paper", "evidence": "site cost spreadsheets"},
    ], "decisions": []},
    {"step": 2, "inputs": [
        {"name": "set of site files", "format": "digital_document", "evidence": "set of site files"},
        {"name": "SAP cost centre report", "format": "structured", "evidence": "SAP cost centre report"},
    ], "decisions": [
        {"text": "Do the totals match SAP?", "kind": "fixed_rule", "evidence": "reconcile totals with SAP"},
    ]},
    {"step": 3, "inputs": [
        {"name": "consolidated cost file", "format": "structured", "evidence": "consolidated cost file"},
        {"name": "budget", "format": "structured", "evidence": "budget"},
    ], "decisions": [
        {"text": "Which variances need an explanation", "kind": "fixed_rule",
         "evidence": "mark lines over the threshold"},
    ]},
    {"step": 4, "inputs": [
        {"name": "list of variances", "format": "structured", "evidence": "list of variances"},
        {"name": "explanations from site managers", "format": "digital_document",
         "evidence": "explanations from site managers"},
    ], "decisions": [
        {"text": "Escalate when there is no answer", "kind": "fixed_rule",
         "evidence": "no answer by day 3; escalate to the Head of Controlling"},
    ]},
    {"step": 5, "inputs": [
        {"name": "variance list with explanations", "format": "digital_document",
         "evidence": "variance list with explanations"},
    ], "decisions": [
        {"text": "What the commentary says", "kind": "pure_judgement", "evidence": "write the commentary"},
        {"text": "Whether to approve the report", "kind": "explainable_judgement", "evidence": "Head of Controlling"},
    ]},
]  # fmt: skip

LABEL_REPLY: dict[str, Any] = {"steps": _LABELS}


def eu_labels() -> list[StepLabels]:
    """The §3.4 labels after grounding (the invented "invoice scans" input left out)."""
    steps = copy.deepcopy(_LABELS)
    steps[0]["inputs"] = steps[0]["inputs"][:1]
    return [StepLabels.model_validate(s) for s in steps]


STEPS_REPLY: dict[str, Any] = {
    "steps": [
        {"step": 1, "fit": "assist", "reason": "Site files arrive late and in different layouts.",
         "evidence": "sites send late and in different layouts", "route": "fix-first",
         "route_reason": "The layouts must be agreed before any tool can read them."},
        {"step": 2, "fit": "automate", "reason": "Numbers are copied by hand from site files into Excel.",
         "evidence": "I copy the numbers into the master file by hand", "route": "custom-ai-app",
         "route_reason": "Reading many layouts reliably needs a build."},
        {"step": 3, "fit": "automate", "reason": "A fixed threshold decides which lines are flagged.",
         "evidence": "the threshold check is done by eye", "route": "low-code-flow",
         "route_reason": "A fixed rule in a connected workbook."},
        {"step": 4, "fit": "automate", "reason": "Reminders to site managers follow a fixed rhythm.",
         "evidence": "some site managers answer only after three reminders", "route": "low-code-flow",
         "route_reason": "Reminders and escalation are a standard flow."},
        {"step": 5, "fit": "assist", "reason": "The commentary is written from scratch each month.",
         "evidence": "I write the commentary from scratch every month", "route": "office-assistant",
         "route_reason": "Drafting text in office documents with a person deciding."},
    ]
}  # fmt: skip


def _entry(
    id: str, category: str, name: str, fits: list[str], prerequisites: list[str] | None = None
) -> dict[str, Any]:
    return {"id": id, "category": category, "name": name, "good_for": f"{name}.", "choose_when": ["it fits"],
            "prerequisites": prerequisites or [], "fits": fits}  # fmt: skip


def example_catalogue(*, version: str = "test-1") -> SolutionCatalogue:
    """A vendor-neutral catalogue with the ids of the spec 26 §3.2 example."""
    return SolutionCatalogue.model_validate({
        "placeholder": True,
        "version": version,
        "solutions": [
            _entry("office-assistant", "off_the_shelf", "Office assistant", ["assist"],
                   ["Licences for the staff involved", "Short training"]),
            _entry("low-code-flow", "low_code", "Low-code workflow automation", ["automate", "assist"],
                   ["A written rule for each decision", "Connector access to the systems involved"]),
            _entry("custom-ai-app", "custom_build",
                   "Custom AI app or agent built by the AI engineering team (placeholder)", ["automate", "assist"],
                   ["A sponsor and an implementation brief", "a written rule for each decision"]),
            _entry("fix-first", "fix_first", "Fix first: standardise and digitise", ["automate", "assist"]),
            _entry("stays-with-people", "none", "No tool: stays with people", ["human"]),
        ],
    })  # fmt: skip
