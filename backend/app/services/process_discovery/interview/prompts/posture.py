"""How hard to push in the find phase: open, then narrowed, then direct, and the honest exit (spec 14 §3.8; F-03.4–5).

ACCEPTED FOR NOW — wording to be refined with the product owner. Builds the posture ladder; the rung
boundaries live in `phases.posture` (computed from `counters.find_turns`), only the text is here.

Why: an open question is right on the first find question and unhelpful on the sixth. Most experts
do not arrive with a process in mind, so the agent converges on schedule: stop opening new ground,
then propose one candidate for a plain yes or no, and offer the exit. The rung text and the exit
are only correct relative to each other, so they live together.
What: `posture_text(posture, awaiting_widening)`: nothing on the open rung (the find headline is
the open posture), the narrowed text, or the direct text plus the honest exit (withheld while a
widening question is outstanding, so the offer never talks over an unanswered question).
Must not: let the agent end the session: only the expert closes it, with the Close button.
Spec 14 §3.8; AC-14.46.
"""

from __future__ import annotations

NARROWED_TEXT = (
    "This conversation has been open for a few turns already. Stop opening new ground: do not ask "
    "again what a normal week looks like. Pick the single strongest piece of recurring work the "
    "expert has ALREADY mentioned and drill into that one: who else is involved, what sets it off, "
    "how often it comes round, who is waiting on the result."
)

DIRECT_TEXT = (
    "This conversation has been open long enough. Do not ask another open question. Name one "
    "specific candidate process out of what the expert has already told you, in their own words, and "
    "ask for a plain yes or no. If they say no, ask them to point at the closest thing to it rather "
    "than re-opening the conversation."
)

NO_CANDIDATE_EXIT = (
    "If the expert declines that candidate and offers nothing in its place, stop pushing and offer "
    "the honest exit: say plainly that what they have described may not be the kind of repeating, "
    "multi-person work worth mapping yet, that this is a perfectly fine answer, and that they can "
    "close the session with the Close button or look at another part of their week. Never end the "
    "session yourself and do not assume they want to stop: offer, state the reason, and wait. "
    "Closing is theirs to choose."
)


def posture_text(posture: str, *, awaiting_widening: bool = False) -> str:
    """What the rung changes about the next find question; "" on the open rung."""
    if posture == "narrowed":
        return NARROWED_TEXT
    if posture == "direct":
        return DIRECT_TEXT if awaiting_widening else f"{DIRECT_TEXT}\n{NO_CANDIDATE_EXIT}"
    return ""
