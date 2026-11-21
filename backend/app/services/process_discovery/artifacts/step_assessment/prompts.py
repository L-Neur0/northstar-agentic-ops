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
Spec 26 §3.4 and its decision note (rule 3b: the S13 rules-or-judgement answer, short step walk,
approved 2026-11-20) and §3.9 (S14 decision criteria as input, draft 2026-11-21); AC-26.3, AC-26.17, AC-26.20, AC-26.21.
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
activities, roles, owner, systems, inputs and outputs, effort, pain points, approvals, exceptions and \
whether the step runs on fixed rules, judgement or a mix (`Rules or judgement`). \
You are also given the company's SOLUTION CATALOGUE.

For EACH step, rate how AI fits it and choose the kind of solution that fits best.

Rules:
1. Rate only what the profile states. Never invent a system, input, role or pain that is not written down.
2. Return exactly one entry per `--- STEP n ---`, with that number in `step`.
3. `fit` is one of:
   - `automate`: AI or automation can do the step; a person checks samples or exceptions.
   - `assist`: AI drafts, reads, checks or suggests; a person decides or finishes.
   - `human`: judgement, relationships, accountability or physical work that stays with people.
   The step's `Rules or judgement` answer is the expert's own view: `rules` leans to `automate`, \
`judgement` to `assist` or `human`, `mix` to `assist`. It never overrides what the step's other answers say.
   The step's `Decision criteria` (when present: what the decision is based on, who sets it, whether \
it is written down, what varies) are input too: criteria that are written down and the same each time \
lean a `judgement` step towards `assist`; criteria that are not written down, or that change from person \
to person, keep it at `assist` or `human`, and the `route_reason` names writing the criteria down as the \
first thing to prepare. They never override what the step's other answers say.
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
12. `signals`: list every signal below that holds for the step, each with `evidence` copied exactly from \
THAT step's words (as in rule 5). Leave a signal out when the step's words do not show it:
   - `reads_unstructured`: the step reads documents or free text whose layout or wording varies (CVs, e-mails, \
free-layout files).
   - `compares_to_criteria`: the step checks items against requirements, criteria or a policy written in words.
   - `finds_patterns`: the step looks across many items for patterns, outliers or duplicates.
   - `drafts_text`: the step writes, summarises or explains in words.
   - `must_be_exact`: the result must be exactly right every time (an amount, a legal or safety decision), with \
no room for a reviewed draft.
   - `fixed_rules`: the same written rule gives the same answer every time; a script or a rules engine could do it.
13. Three motivations for the whole process, each one or two sentences with `evidence` copied exactly from one \
field of the profile: `fit_motivation` (is this a good use of AI, and why), `assistant_motivation` (would a \
dedicated solution or a general assistant such as a chat tool suit it better, and why: think of sensitive data, \
systems to reach, instructions repeated every run), `worth_motivation` (is it worth the effort, and why). Never \
answer yes or no and never give a verdict; describe what fits and why.

GUIDELINES (what AI is good at): AI language models are strong at reading varied documents, comparing text with \
criteria, finding patterns in language, and summarising or drafting. They are weak where the same input must \
always give the same output, at strict arithmetic or rule logic, and where an unchecked mistake is costly: there, \
rules or a script come first, and the common design is a hybrid (rules check, AI reads and drafts, a person approves).

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
