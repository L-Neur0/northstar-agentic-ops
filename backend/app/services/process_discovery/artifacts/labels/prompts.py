"""The prompts of the LABEL call (spec 19 §3.3 item 3).

Why: two readiness dimensions (Data and Rules) rest on what kind of input each step reads and what
kind of decision it takes. Those are judgements on words, the model's only job here; the prompt
defines each format and kind so the model's labels mean what the readiness rules assume. Code
still checks every step, input name and quote (grounding).
What: `LABEL_SYSTEM` (one literal string with the five rules, the PROFILE fence sentence and the
JSON-only line) and `labels_user` (lead-in plus the shared fenced profile).
Must not: pass the system prompt through `str.format`, ask for scores or numbers, or render the
profile a second way.
Spec 19 §3.3; AC-19.18.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...domain.field_spec import Vocabulary
from ..profile_fence import PROFILE_FENCE_INSTRUCTION, fence_profile

USER_LEAD_IN = "Label the inputs and decisions of each step in this process profile:"

LABEL_SYSTEM = (
    """You are a senior process analyst. You are given a business process profile captured in a \
structured interview: the process, and its numbered steps (`--- STEP n ---`).

For each step, label its inputs and its decisions.

Rules:
1. For every `--- STEP n ---`, label each input listed under "Data in and out", using its exact name.
2. Each input gets one format:
   - `structured`: fields a system can read without a person (a system record, a database export, \
a form or spreadsheet with a fixed layout);
   - `digital_document`: a digital file or message a person reads (PDF, Word, e-mail, a spreadsheet \
with a free layout);
   - `paper`: printed or handwritten;
   - `verbal`: said in a call or meeting, or known from memory.
3. List the decisions taken in the step (from its activities, approvals, exceptions and goal), each \
in at most 15 words. Each decision gets one kind:
   - `fixed_rule`: a written rule or threshold decides; anyone applying it gets the same answer;
   - `explainable_judgement`: a person decides but can name the criteria and give examples;
   - `pure_judgement`: experience or relationships decide; hard to write down.
4. `evidence`: the expert's words from THAT step, copied exactly, at least three words or a whole \
short answer. No paraphrase, no joining of passages, no "...". Copy from ONE answer only: never the \
field labels (such as `inputs:` or `approver role:`), never a list joined with commas or semicolons. \
For an input, its own name as written is good evidence.
5. Never invent inputs or decisions; a step with no decision has an empty list. Never give scores \
or numbers.

"""
    + PROFILE_FENCE_INSTRUCTION
    + "\n\nReturn only JSON matching the schema."
)


def labels_user(profile: Mapping[str, Any], *, vocab: Vocabulary, documents: Sequence[Mapping[str, str]] = ()) -> str:
    """The lead-in line, then the shared fenced profile."""
    return f"{USER_LEAD_IN}\n{fence_profile(profile, vocab=vocab, documents=documents)}"
