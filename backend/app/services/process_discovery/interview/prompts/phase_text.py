"""The per-phase text the guide prompt is assembled from (spec 14 §3.9).

ACCEPTED FOR NOW — wording to be refined with the product owner. Builds the phase text; clusters come
from the company configuration, the step walk holds 2 to 6 steps, and the phases carry this
product's names.

Why: which fields a phase collects comes from the registry; what the phase is *for*, and what to
say about a verdict, a proposal or a list, is editorial prose. Every phase the machine can emit has
a headline, and an unknown phase gets an explicit "Unrecognised phase" line instead of a silent
default (a silent default once served the wrong guidance for five phases unnoticed).
What: `PHASE_HEADLINES`, `phase_headline`, and the blocks steered by state: `step_instructions`,
`rollup_instructions`, `cluster_block` (propose or picker), `widening_block`, `wrap_up_block`.
Must not: restate a field, a cluster or a limit by hand (they come from the registry and the
config), or inline untrusted text without `single_line`.
Spec 14 §3.9; AC-14.46 to AC-14.48, AC-14.50.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.utils.prompt_safety import single_line

from ...domain.field_spec import (
    DERIVED_SPECS,
    GROUP_B,
    GROUP_EFFORT,
    GROUP_NAMES,
    MAX_STEPS,
    MIN_STEPS,
    PHASE_BOUNDARIES,
    PHASE_CONFIRM,
    PHASE_CONTEXT,
    PHASE_FIND,
    PHASE_FINISHED,
    PHASE_MEASURE,
    PHASE_NO_CANDIDATE,
    PHASE_REVIEW,
    PHASE_STEP_COUNT,
    PHASE_STEPS,
    PROFILE_SPECS,
    Vocabulary,
    step_spec_by_leaf,
)
from ...domain.scope import SIGNAL_QUESTIONS, SIGNALS, failed_signals, proposable_code
from ...profile.shapes import as_mapping, parse_step_key, process_of, rows_of
from ...profile.verdicts import expected_steps, volume_words
from .common import inline_name, text_value

PHASE_HEADLINES: dict[str, str] = {
    PHASE_CONTEXT: (
        "Learn who you are talking to: their department, their own role and their region. Keep the opening warm "
        "and brief. As they answer, listen for the recurring work in what they say (the things they do every "
        "week, the hand-offs, the chasing) and remember it; you will use it to propose a candidate yourself "
        "rather than asking them to name one."
    ),
    PHASE_FIND: (
        "Settle on the one piece of recurring work most worth mapping, and get the expert to agree that is what "
        "you are mapping.\n"
        "Do not open by asking which process they want to map: that is the question you are helping them "
        "answer. Instead:\n"
        "- Ask what a normal week looks like, what they repeat most often, what they chase people for, or what "
        "they hand over to somebody else when they are done.\n"
        "- If they are not sure, draw on these to open the conversation up; ask one or two, in your own words, "
        "never as a checklist:\n"
        + "".join(f"    · {q}\n" for q in SIGNAL_QUESTIONS.values())
        + "- When you hear a candidate, name it back in the expert's own words and ask if that is the one worth "
        "mapping. Let them correct you; a correction is progress.\n"
        "- When several candidates were mentioned, THIS TURN says what to ask: a quick question about each, or the "
        "system's recommendation. Otherwise list them back in the expert's words, one line each on why it could be "
        "worth mapping (it repeats, several people, several systems), and ask which to map now; the others are kept "
        "as ideas for later.\n"
        "- They may also add a document (a procedure, a process map, an example report) at any time.\n"
        "Never bring up clusters, an internal process framework or a list of areas yourself (only when THIS TURN "
        "puts a cluster to the expert), and never ask which category their work belongs to."
    ),
    PHASE_BOUNDARIES: (
        "Pin down where {process_name} starts, what it produces, who uses the result, and what hurts most about it."
    ),
    PHASE_MEASURE: (
        "Put numbers on {process_name}: how often it runs, who owns it, how it performs today and where it should "
        "get to, whether others do it the same way, and whether it touches sensitive data or a regulation."
    ),
    PHASE_STEP_COUNT: (
        "Agree how {process_name} breaks down before walking through it. Ask the expert to list the main steps "
        f"in order, {MIN_STEPS} to {MAX_STEPS}: one answer gives both the names and the number. Anything outside "
        "that range cannot be recorded, so if their list is longer, help them group it first rather than "
        "accepting the larger number."
    ),
    PHASE_STEPS: (
        "Walk through {process_name} one step at a time, in grouped questions chosen by the system: one open "
        "question per step (including who else is involved), a short follow-up only for what is missing, then "
        "one optional question about sign-offs, what goes wrong and passing the work on. Effort is asked once for "
        "all steps at the end. Goal and owner are never asked: the system fills them in for the expert to "
        "confirm in the review."
    ),
    PHASE_CONFIRM: (
        "The walk of {process_name} is done; ask whether anything should be corrected (this phase is no longer "
        "used and moves on to the review)."
    ),
    PHASE_REVIEW: (
        "Ask the remaining fields of {process_name} once more. When nothing is missing, summarise {process_name} "
        "in two sentences and say what the FINISH STATE below allows."
    ),
    PHASE_FINISHED: "The interview for {process_name} is finished. Answer questions; do not restart the interview.",
    PHASE_NO_CANDIDATE: (
        "The expert closed this session without a process to map. Do not restart the interview and do not ask "
        "for more detail."
    ),
}


def phase_headline(phase: str, profile: Mapping[str, Any]) -> str:
    """The headline with `{process_name}` substituted, or the explicit "Unrecognised phase" line."""
    headline = PHASE_HEADLINES.get(phase)
    if headline is None:
        return (
            f"Unrecognised phase '{single_line(phase, 40)}'. Ask about whatever the profile above is still missing, "
            "and do not invent a new topic."
        )
    return headline.replace("{process_name}", inline_name(process_of(profile).get("name")))


def _labels(keys: Sequence[str], vocab: Vocabulary) -> list[str]:
    out: list[str] = []
    for key in keys:
        parsed = parse_step_key(key)
        spec = step_spec_by_leaf(parsed[1]) if parsed else None
        if spec is not None:
            out.append(f"- {vocab.label(spec)} (`{key}`): {vocab.question(spec)}")
    return out


def step_instructions(
    profile: Mapping[str, Any], keys: Sequence[str], *, vocab: Vocabulary, asked_before: bool = False
) -> str:
    """Where the walk is and the one grouped question to ask now (§3.19 W10); the fields come from code."""
    expected = expected_steps(profile, vocab=vocab)
    parsed = [p for p in (parse_step_key(k) for k in keys) if p is not None]
    if expected == 0 or not parsed:
        if expected == 0:
            return (
                f"The steps are not known yet, so the walk cannot start. Ask the expert to list the main steps of "
                f"{inline_name(process_of(profile).get('name'))} in order, {MIN_STEPS} to {MAX_STEPS}, and "
                "nothing else this turn."
            )
        return f"All {expected} steps are described."
    rows = rows_of(profile)

    def name_of(index: int) -> str:
        return single_line(rows[index - 1].get("name") or "", 120) if index <= len(rows) else ""

    together = "Ask about ALL of these together in ONE question; that is the only question for this turn."
    steps = sorted({i for i, _ in parsed})
    spec = step_spec_by_leaf(parsed[0][1])
    group = spec.group if spec is not None else None
    if group == GROUP_NAMES:
        return (
            f"The process has {expected} main steps but not all have a name. Ask for the names of the steps in "
            f"order, all in one question. {together}"
        )
    if group == GROUP_EFFORT or len(steps) > 1:
        listed = "\n".join(f'- step {i}: "{name_of(i)}"' for i in steps)
        runs = volume_words(profile, vocab=vocab) if group == GROUP_EFFORT else None
        if runs:
            return (
                "All steps are walked; now effort. Ask ONE question listing every step below by number and name: "
                "roughly how long each step takes each time. Say you will assume each step happens once per run "
                f"of the process (about {single_line(runs, 60)}), and that the expert should say if one happens "
                "more often. Do not ask how often. A rough answer per step is fine.\n"
                f"{listed}\n{together}"
            )
        return (
            "All steps are walked; now effort. Ask ONE question listing every step below by number and name: "
            "roughly how long each takes and how often. A rough answer per step is fine.\n"
            f"{listed}\n{together}"
        )
    index = steps[0]
    name = name_of(index)
    heading = f"You are on step {index} of {expected}" + (f' — "{name}".' if name else ", which has no name yet.")
    fields = "\n".join(_labels(keys, vocab))
    if group == GROUP_B:
        how = (
            "One short OPTIONAL question about this step: any sign-off needed, anything that often goes wrong, or "
            'anything special about passing it on. Say plainly that "no" is a fine answer, for example: "Any '
            "sign-off needed, anything that often goes wrong, or anything special about passing it on? If nothing, "
            'just say no."'
        )
        if any(k.endswith(".decision_criteria") for k in keys):
            evidence = (
                single_line((as_mapping(rows[index - 1].get("decision_type")) or {}).get("evidence") or "", 160)
                if index <= len(rows)
                else ""
            )
            said = f'You said "{evidence}". ' if evidence else ""
            how += (
                "\nThis step involves judgement, so in the SAME question, first ask what the decision is based on, "
                "tied to the expert's own words about it, for example: "
                f'"{said}What do you base that decision on, who sets those criteria, and are they written down '
                'anywhere? And any sign-off needed or anything that often goes wrong? If nothing, just say no."'
            )
    elif asked_before:
        how = (
            "This is the follow-up: ask only the missing ones below, short, and repeat back what you already have "
            "for this step so the expert sees it landed."
        )
    else:
        how = (
            f'One open question: ask the expert to walk you through step {index}, "{name}", covering every field '
            "below in their own words. For example: \"Walk me through 'Collect the cost data': what you do, who "
            "else is involved, with which systems and files, what comes in and goes out, what's annoying, and is "
            'it mostly fixed rules, judgement or a mix?"'
        )
    tail = f"step {index + 1}" if index < expected else "the effort question for all steps"
    return (
        f"{heading}\n{how}\nThe fields for this turn:\n{fields}\n{together}\n"
        f'Once these have an answer (including "there are none"), the walk moves on to {tail}.'
    )


def rollup_instructions(profile: Mapping[str, Any], keys: Sequence[str]) -> str:
    """Read back the lists asked this turn; any plain agreement settles a list; never ask for a form of words."""
    proc = process_of(profile)
    lines = [f"- {d.label}: {text_value(proc.get(d.key.split('.', 1)[1]))}" for d in DERIVED_SPECS if d.key in keys]
    which = "both lists" if len(keys) > 1 else "this list"
    return (
        "These lists were rolled up from the steps:\n"
        + "\n".join(lines)
        + f"\nRead {which} back as it stands and ask the expert to confirm or correct it. A correction belongs on "
        "the step it came from, so name the step when you make one.\n"
        'Any plain agreement settles a list: "yes", "correct", "that\'s right". The Confirm buttons beside the lists '
        "in the panel do the same, so you may mention them, but never imply they are the only way. Never ask the "
        "expert to repeat a particular form of words, never quote a sentence for them to type back, and never say "
        "that a specific wording is what settles it."
    )


def _cluster_line(code: str, vocab: Vocabulary) -> str:
    cluster = vocab.taxonomy.by_code(code)
    return f"{cluster.name}: {cluster.description}" if cluster else ""


def cluster_block(
    placement: Mapping[str, Any], mode: str, *, vocab: Vocabulary, process_name: str, asked_before: bool
) -> str:
    """The cluster question: put the proposal with its meaning, or show the picker (every cluster with its description)."""
    proposal = as_mapping(placement.get("proposal")) or {}
    code = proposable_code(proposal)
    if mode == "propose" and code:
        lines = [
            f"You have a proposed cluster for {process_name}. Put it to the expert as a confirmation, not as a "
            "question about an internal framework.",
            f"- Proposed cluster, word for word: {_cluster_line(code, vocab)}",
            "- Tie that meaning to the expert's own words: say where what they described sits inside it.",
            "- Ask whether that fits how they would file it.",
            "- Never name a cluster without saying what it means in the same breath.",
        ]
        runner = vocab.taxonomy.by_code(str(proposal.get("runner_up") or ""))
        if runner is not None and runner.code != code:
            lines.append(
                f"- If they say no, offer this one next, with its meaning: {_cluster_line(runner.code, vocab)}"
            )
        return "\n".join(lines)
    if placement.get("rejected") is True:
        head = "The expert said no to the proposed cluster."
    elif code and asked_before:
        head = "The proposed cluster has been put to the expert without landing. Stop proposing it."
    else:
        head = "You do not have a confident cluster for this process."
    options = "\n".join(f"- {c.name}: {c.description}" for c in vocab.taxonomy.clusters)
    return (
        f"{head} Do not guess and do not ask the expert to name a cluster unaided. Show these options, each with "
        f"its meaning, and ask which fits {process_name} best:\n{options}"
    )


def widening_block(scope: Mapping[str, Any]) -> str:
    """One widening question after a `borderline` or `task` verdict: name the signals that did not hold."""
    verdict = as_mapping(scope.get("verdict")) or {}
    label = verdict.get("verdict")
    head = (
        "What the expert described may be a single task rather than a process."
        if label == "task"
        else "What the expert described sits on the boundary between a task and a process."
    )
    reasoning = single_line(verdict.get("reasoning") or "", 400)
    prose = dict(SIGNALS)
    failed = failed_signals(verdict)
    named = "\n".join(f"  - {prose[k]} Plain question: {SIGNAL_QUESTIONS[k]}" for k in failed if k in prose)
    parts = [
        head,
        f"Assessment: {reasoning}" if reasoning else "",
        f"These tests did not hold:\n{named}" if named else "",
        "Ask ONE widening question: who receives or depends on the output once they are done? Name the signals above "
        "in plain language so the expert can see why you are asking. Do not lecture them about what counts as a "
        "process, and do not refuse to continue: if their answer widens it into something with a real consumer, map "
        "that instead.",
    ]
    return "\n".join(p for p in parts if p)


SETTLE_HINT = (
    'Offer an easy way to settle it: a range is fine ("between 2 and 4 days"), "not sure" is fine, and "none" is '
    "fine where it applies."
)


def wrap_up_block(given_up: Sequence[str], *, vocab: Vocabulary, ready: bool) -> str:
    """The wrap-up: given-up fields offered once more with an easy settle, and the honest exit (spec 14 Q4)."""
    if not given_up:
        if ready:
            return "Nothing is missing. Summarise the process in two sentences and ask whether anything should be corrected."
        return "Nothing more will be asked. Summarise the process in two sentences."
    labels = ", ".join(vocab.label(s) for s in PROFILE_SPECS if s.key in given_up)
    return (
        f"These fields are still open after several tries: {labels}. Ask about them ONE more time, together, in one "
        f"short question. {SETTLE_HINT} If the expert still cannot answer, tell them plainly that Finish needs more of "
        "the map answered, and that they can close the session with the Close button instead; that is a fine answer "
        "too. Never end the session yourself."
    )
