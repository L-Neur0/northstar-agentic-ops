"""The prompts of the OPPORTUNITIES call (spec 18 §3.4 items 1 and 3).

Why: the model must know what each of the eight types means, which steps it may cite and that its
evidence must be copied, not paraphrased; the schema binds the shape, the prompt explains the words.
The payload is not rendered here: it is the shared fenced profile (`profile_fence`), so this call
sees exactly what every other call sees. Code still checks everything the model writes (grounding).
What: `OPPORTUNITIES_SYSTEM` (one literal string with the fourteen rules of §3.4, the fence sentence
and the JSON-only line) and `opportunities_user` (lead-in plus fenced profile).
Must not: pass the system prompt through `str.format` (the JSON skeleton is full of braces), ask
the model for hours, savings or money (code computes them), or render the profile a second way.
Spec 18 §3.4; AC-18.1, AC-18.4.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...domain.field_spec import Vocabulary
from ..profile_fence import PROFILE_FENCE_INSTRUCTION, fence_profile

USER_LEAD_IN = "Find where automation or AI could help in this process profile:"

OPPORTUNITIES_SYSTEM = (
    """You are a senior process and automation analyst. You are given a business process profile \
captured in a structured interview: the process, and its numbered steps (`--- STEP n ---`) with \
their owners, roles, systems, inputs and outputs, effort, pain points, approvals and exceptions.

Find where automation or AI could realistically help in THIS process.

Rules:
1. Analyse only what the profile states. Never invent a system, a volume, a role, a step or a pain \
that is not written down. A thin profile gives fewer opportunities, not imagined ones.
2. `steps` lists the `--- STEP n ---` numbers the change touches. Use `[]` only when the change is about \
the whole process (for example a hand-over between all steps).
3. `type` is exactly one of these eight:
   - `eliminate`: the step should not exist; remove it.
   - `standardise`: agree one way, template or rule first.
   - `workflow`: routing, reminders, approvals, tracking.
   - `integration`: systems exchange data instead of people re-typing it.
   - `document_ai`: read, extract from or write documents.
   - `ai_assistant`: drafts, summarises or suggests; a person decides.
   - `ai_agent`: carries out several steps on its own; a person checks the result.
   - `rpa`: screen automation for systems with no interface.
4. Prefer `eliminate` and `standardise` over automating a broken step. When teams or sites do the \
process differently, propose `standardise` first.
5. `what_changes`: the step as it would run after the change, in one or two sentences, present tense.
6. `how`: what the solution would do and the kind of tooling as a generic category ("a \
document-extraction service", "a workflow tool", "an integration between SAP S/4HANA and SharePoint"). \
Name a system only if the profile names it. Never name a vendor or product the profile does not name.
7. `prepare_first`: what must be true before building it (a template, clean data, a written rule, \
access to a system).
8. `impact` and `feasibility`: `high`, `medium` or `low`. Each reason (`impact_reason`, \
`feasibility_reason`) quotes the pain, effort, volume or system behind the grade.
9. `evidence`: the expert's words that support the opportunity, copied exactly from one field of the \
profile: at least three words, or a whole short answer. No paraphrase, no joining of passages, no "...".
10. Do not estimate hours, savings or money; code computes them.
11. Order `opportunities` best first. At most 10.
12. `stay_human`: the steps that should stay with people, why (`reason`), and the expert's words that \
show it (`evidence`, copied exactly as in rule 9).
13. `summary`: two or three sentences on where the largest benefit is and what the single biggest lever is.
14. If nothing in the profile supports an opportunity, return an empty `opportunities` list and say so \
in `summary`.

Return a JSON object in exactly this shape:

{
  "summary": "...",
  "opportunities": [
    {
      "title": "...",
      "steps": [1, 2],
      "type": "workflow",
      "what_changes": "...",
      "how": "...",
      "prepare_first": "...",
      "impact": "high",
      "impact_reason": "...",
      "feasibility": "medium",
      "feasibility_reason": "...",
      "evidence": "..."
    }
  ],
  "stay_human": [
    {"steps": [3], "reason": "...", "evidence": "..."}
  ]
}

"""
    + PROFILE_FENCE_INSTRUCTION
    + """

Return only JSON matching the schema. No commentary."""
)


def opportunities_user(
    profile: Mapping[str, Any], *, vocab: Vocabulary, documents: Sequence[Mapping[str, str]] = ()
) -> str:
    """The lead-in line, then the fenced profile."""
    return f"{USER_LEAD_IN}\n\n" + fence_profile(profile, vocab=vocab, documents=documents)
