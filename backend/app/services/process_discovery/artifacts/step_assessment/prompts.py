"""The prompts of the ASSESS_STEPS call and the catalogue block the model chooses routes from (spec 26 §3.4).

Why: the model must know what `automate`, `assist` and `human` mean, that its evidence must be copied
from the step it rates, and that a route can only be an id from the company's solution catalogue,
reusing a tool the company already runs before proposing to buy or build one. The schema binds the
shape; the prompt explains the words. Code still checks every step, quote and id (grounding).
What: `ASSESS_STEPS_SYSTEM` (one literal string: the rules of §3.4, the reuse-before-build order,
the PROFILE fence sentence, the JSON-only line), `render_catalogue` (one line per catalogue entry,
from configuration) and `assess_steps_user` (lead-in plus the shared fenced profile).
Must not: pass the system prompt through `str.format`, name any company tool in code (entries reach
the prompt only from `solutions.yaml`), ask for hours, money or scores, or render the profile a second way.
Spec 26 §3.4 and its decision note; AC-26.3, AC-26.17, AC-26.20.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.core.config import SolutionCatalogue
from app.utils.prompt_safety import single_line

from ...domain.field_spec import Vocabulary
from ..profile_fence import PROFILE_FENCE_INSTRUCTION, fence_profile

USER_LEAD_IN = "Rate each step of this process profile:"
CATALOGUE_HEADER = "SOLUTION CATALOGUE (the only routes you may choose; use the id):"
LINE_MAX = 300

ASSESS_STEPS_SYSTEM = (
    """You are a senior process and AI analyst. You are given a business process profile captured \
in a structured interview: the process, and its numbered steps (`--- STEP n ---`) with their goal, \
activities, roles, owner, systems, inputs and outputs, effort, pain points, approvals and exceptions. \
You are also given the company's SOLUTION CATALOGUE.

For EACH step, rate how AI fits it and choose the kind of solution that fits best.

Rules:
1. Rate only what the profile states. Never invent a system, input, role or pain that is not written down.
2. Return exactly one entry per `--- STEP n ---`, with that number in `step`.
3. `fit` is one of:
   - `automate`: AI or automation can do the step; a person checks samples or exceptions.
   - `assist`: AI drafts, reads, checks or suggests; a person decides or finishes.
   - `human`: judgement, relationships, accountability or physical work that stays with people.
4. `reason`: one or two sentences naming the step's inputs, systems, decisions or pain behind the fit.
5. `evidence`: the expert's words copied exactly from THAT step or from the process fields, at least \
three words or a whole short answer. No paraphrase, no joining of passages, no "...". Copy from ONE \
answer only: never the field labels (such as `pain points:`), never a list joined with commas or semicolons.
6. `route`: one `id` from the SOLUTION CATALOGUE whose `fits` include the step's fit, chosen by its \
"choose when" and "avoid when". Use "" if no entry fits. Never invent an id, never name a vendor or product.
7. Reuse before build. Choose in this order:
   a. an `existing_internal` tool (one the company already built and runs) whenever its "choose when" \
matches the step;
   b. else the licensed assistant (`off_the_shelf`);
   c. else a `low_code` entry;
   d. else a `custom_build` entry.
   An `integration` entry fits when people copy structured data between systems by hand.
8. When the step's inputs are paper or verbal, or teams do it differently, prefer a `fix_first` entry.
9. A step whose fit is `human` takes the `none` entry (stays with people) or "".
10. `route_reason`: one sentence on why this route fits better than the next best.
11. Never give hours, money, savings or scores; code computes them.

"""
    + PROFILE_FENCE_INSTRUCTION
    + "\n\nReturn only JSON matching the schema."
)


def _items(label: str, items: Sequence[str]) -> str:
    return f"; {label}: {' | '.join(items)}" if items else ""


def render_catalogue(catalogue: SolutionCatalogue) -> str:
    """The catalogue block appended to the system prompt: one line per entry, from configuration."""
    lines = [CATALOGUE_HEADER]
    for s in catalogue.solutions:
        text = (
            f"{s.id}: {s.name} [{s.category}; fits: {', '.join(s.fits)}] good for: {s.good_for}"
            f"{_items('choose when', s.choose_when)}{_items('avoid when', s.avoid_when)}"
            f"{_items('needs', s.prerequisites)}"
        )
        lines.append(f"- {single_line(text, LINE_MAX)}")
    return "\n".join(lines)


def assess_steps_system(catalogue: SolutionCatalogue) -> str:
    """The full system message: the rules, then the catalogue block."""
    return f"{ASSESS_STEPS_SYSTEM}\n\n{render_catalogue(catalogue)}"


def assess_steps_user(
    profile: Mapping[str, Any], *, vocab: Vocabulary, documents: Sequence[Mapping[str, str]] = ()
) -> str:
    """The lead-in line, then the shared fenced profile."""
    return f"{USER_LEAD_IN}\n{fence_profile(profile, vocab=vocab, documents=documents)}"
