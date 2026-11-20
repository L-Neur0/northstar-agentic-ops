"""The prompts of the MAP call (spec 18 §3.7 items 1 and 4).

Why: the model is asked for a map that grounding would keep as it is: one task per real step, lanes
named after real roles, gateways only where the profile states a decision, and valid BPMN. Asking for
it saves fallbacks; nothing downstream trusts that it got it (`grounding.py` re-checks everything).
The payload is the shared fenced profile, so the map is drawn from what every other call sees.
What: `MAP_SYSTEM` (one literal string with the nine requirements, the fence sentence and the JSON-only
line) and `map_user` (lead-in plus fenced profile).
Must not: pass the system prompt through `str.format` (the JSON skeleton is full of braces), or render
the profile a second way.
Spec 18 §3.7; AC-18.1, AC-18.19.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...domain.field_spec import Vocabulary
from ..profile_fence import PROFILE_FENCE_INSTRUCTION, fence_profile

USER_LEAD_IN = "Draw the BPMN process diagram for this process profile:"

MAP_SYSTEM = (
    """You are a senior business process analyst. You are given a business process profile captured in \
a structured interview, including its numbered steps (`--- STEP n ---`) with each step's owner, the other \
roles involved, systems, approvals, exceptions and hand-overs.

Draw THIS process, as it runs today, as a proper BPMN 2.0 process diagram with swimlanes.

Requirements:
1. Use only what the profile states. Never invent a step, a role, a system or a decision that is not \
written down.
2. `lanes` lists the roles that perform the process, one lane per role, using the role names exactly as \
the profile writes them (step owners first, in the order they first appear). Never use a person's name.
3. Draw exactly one `task` node per step, in step order, with `step_index` set to the step's 1-based \
number and `lane` set to the index of the lane of the step's owner. Keep `label` to the step's name.
4. Every task gets a `marker`, the BPMN task type, chosen from what the step's systems say:
   - `user`: the step is done by a person working in a system (most common).
   - `manual`: the step lists no system at all: pen and paper, a phone call, a conversation.
   - `service`: the step is a system acting on its own (an automated job, an integration), not a person.
   - `send` / `receive`: the step's whole point is sending or receiving a message, an email or a document.
   - `script`: an automated script or macro runs the step.
   - `business_rule`: the step applies a fixed rule or policy to decide something (a rules engine, a lookup table).
   - `none`: none of the above fits.
   Use `manual` for a step with no system, `user` for a step with one, and only reach for the others when \
the profile is explicit about it (do not guess "service" or "script" from a system name alone).
5. Add a `gateway` only where the profile states a decision, an approval or an exception path; never to \
show every possible outcome, only the ones the profile actually describes. Its `label` is a short question \
(at most six words). Give it a `marker`:
   - `exclusive`: exactly one branch is taken (a yes/no decision, an approval); the default.
   - `parallel`: the profile says several things happen at the same time, all branches taken together.
   - `inclusive`: one or more branches can be taken depending on more than one condition.
   - `event_based`: the path depends on which of several events happens first (for example "whichever \
reply arrives first").
   Its outgoing flows are labelled with the answer, for example "yes" and "no". If one branch is what \
happens when nothing else applies, set `is_default` true on that one flow only: never on more than one flow \
from the same gateway, and never on a flow that does not leave a gateway.
6. Exactly one `start` node before the first step, and at least one `end` node. Give each a `marker`:
   - start: `message` if the trigger is an email, a document or a request arriving; `timer` if it is \
scheduled or periodic; `signal` if it is broadcast by something else; `conditional` if it is a condition \
becoming true; otherwise `none`.
   - end: `message` if the process ends by sending something; `error` if it ends in a failure or an \
escalation; `terminate` if it ends by stopping everything immediately; otherwise `none`.
   Name each one as a short, correct English phrase of 2 to 6 words that you could read aloud, built from \
the profile's own words: start = the triggering event, end = the end result. Examples (another domain): \
trigger "when a customer places an order online" becomes "Customer order placed"; end result "the parcel \
is delivered and signed for" becomes "Parcel delivered and signed for". Never the full sentence. Gateways, \
start and end events have `step_index` null and sit in the lane of the step they belong to.
7. `flows` connect node ids in the order the work happens. Every node must be reachable from the start, \
and every path must reach an end. Use `label` "" and `is_default` false on flows that do not leave a gateway.
8. Node ids are short, unique strings such as "start", "t1", "g1", "end".
9. Keep it valid BPMN: every task has exactly one incoming and one outgoing flow. Where paths come back \
together, add a merge `gateway` with the same `marker` as the gateway that split them and point the paths \
at it; where a loop returns to an earlier step, add an `exclusive` merge. A gateway either splits (one flow \
in, several out) or merges (several in, one out), never both. Every flow leaving an `exclusive`, \
`inclusive` or `event_based` gateway that splits has a `label`.

Return a JSON object in exactly this shape:

{
  "lanes": ["..."],
  "nodes": [
    {"id": "start", "type": "start", "label": "...", "lane": 0, "step_index": null, "marker": "message"},
    {"id": "t1", "type": "task", "label": "...", "lane": 0, "step_index": 1, "marker": "user"}
  ],
  "flows": [
    {"source": "start", "target": "t1", "label": "", "is_default": false}
  ]
}

"""
    + PROFILE_FENCE_INSTRUCTION
    + """

Return only JSON matching the schema. No commentary."""
)


def map_user(profile: Mapping[str, Any], *, vocab: Vocabulary, documents: Sequence[Mapping[str, str]] = ()) -> str:
    """The lead-in line, then the fenced profile."""
    return f"{USER_LEAD_IN}\n\n" + fence_profile(profile, vocab=vocab, documents=documents)
