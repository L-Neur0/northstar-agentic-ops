"""EXTRACT: the prompt that turns one expert message into field changes (spec 14 §3.9).

ACCEPTED FOR NOW — wording to be refined with the product owner. Builds the extractor prompt (the
longest one, because it is the only call that writes): the role, the fenced profile, the fenced
previous question, the key list and row shapes, the step bound, the spelling rule and the none
answers. Adapted: no cluster-assent key (a yes is read by code), the step range is 2 to 6, the
expert message is fenced in the user message, and in `find` other candidates are returned as ideas
with the expert's words for their steering signals (§3.15 item 4).

Why: everything the call may emit (which keys exist, their shapes, which ones this turn is about)
is read from the registry and the live profile at call time, so a registry edit lands here on the
next call instead of in a whitelist someone must remember. The word "JSON" appears in the
messages, because the JSON-object response format is rejected without it.
What: `extractor_system`, `extractor_user`, and `extract_view` (the profile as registry-keyed JSON
without `__meta`, `__skipped`, flags, roll-ups or the parked count).
Must not: let the model write the cluster, a confirmation or a flag; invite it to infer, rephrase or
translate; or put the expert's text outside a fence. Spec 14 §3.9, §3.15 item 12; AC-14.3, AC-14.58,
AC-14.60, AC-14.66. Amendment §3.19 (short step walk): the steps a grouped question covered, the
steps list, the S13 shape and the bare-yes rule for sensitive data (AC-14.116). Amendment §3.20 (owner
test, 2026-11-21): the values the previous question offered are shown, fenced, with the rule for "the
ones you listed" (AC-14.123). Amendment §3.21 (p05 evaluation, 2026-11-21): facts for other
keys, one item per thing, pronouns, and the S14 shape (AC-14.134).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from app.utils.prompt_safety import fence_instruction, fence_untrusted

from ...domain.field_spec import (
    CONFLICTS_KEY,
    MAX_STEPS,
    META_KEY,
    SKIPPED_KEY,
    Vocabulary,
    extract_keys,
    object_list_shape_hints,
)
from ...profile.constants import CONFIRMATION_FLAGS, FLAG_SUBSTEP_COUNT_REJECTED
from ...profile.shapes import as_list, as_mapping, normalized_profile, parse_step_key, process_of
from ...profile.verdicts import P16_KEY, current_step_index, expected_steps
from ..steering import STEER_PREFIX

ROW_EXAMPLE = (
    'For example, "the AP clerk checks the invoice and the manager signs it" is '
    '`[{"role": "AP clerk", "contribution": "checks the invoice"}, {"role": "Manager", "contribution": "signs it"}]`.'
)


def extract_view(profile: Mapping[str, Any]) -> dict[str, Any]:
    """The profile as the extractor sees it: registry keys and values only."""
    p = normalized_profile(profile)
    p.pop(META_KEY, None)
    p.pop(CONFLICTS_KEY, None)
    proc = process_of(p)
    for key in (*CONFIRMATION_FLAGS, FLAG_SUBSTEP_COUNT_REJECTED, "all_roles", "all_tools"):
        proc.pop(key, None)
    proc["substeps"] = [
        {k: v for k, v in dict(as_mapping(r) or {}).items() if k not in (META_KEY, SKIPPED_KEY, CONFLICTS_KEY)}
        for r in as_list(proc.get("substeps")) or []
    ]
    return p


def _str_list(value: Any) -> list[str]:
    return [v for v in (as_list(value) or []) if isinstance(v, str)]


def extractor_system(
    profile: Mapping[str, Any],
    previous_question: str,
    last_question: Mapping[str, Any],
    *,
    vocab: Vocabulary,
    phase: str,
    candidates: Sequence[str] = (),
) -> str:
    """The EXTRACT system prompt for this turn; `candidates` are the names already heard in `find`."""
    declared = expected_steps(profile, vocab=vocab)
    asked_steps = {p[0] for p in (parse_step_key(k) for k in _str_list(last_question.get("focus"))) if p is not None}
    # §3.19: the step the last question was about (effort stays open until the end, so the first
    # incomplete row is not the step under discussion); else the first incomplete row.
    index = next(iter(asked_steps)) if len(asked_steps) == 1 else current_step_index(profile, vocab=vocab)
    keys = "\n".join(f'- "{key}"' for key in extract_keys())
    shapes = "\n".join(object_list_shape_hints())
    if declared:
        bound = f"Step keys are 1-based: `i` runs from 1 to {declared}. Never emit a key outside that range."
        if index is not None and index <= declared:
            bound += f" The step under discussion is step {index}."
    else:
        bound = (
            "The expert has not said how many main steps the process has yet. If this message lists or narrates the "
            'steps themselves ("first we..., then..., finally..."), emit `process.substeps[i].name` for each, with '
            f"`i` from 1 to at most {MAX_STEPS} in the order given, plus `process.substep_count` with how many you "
            "emitted. Otherwise emit no step keys."
        )
    asked = (previous_question or "").strip()
    about = [
        k
        for k in (*_str_list(last_question.get("focus")), *_str_list(last_question.get("proposals")))
        if not k.startswith(STEER_PREFIX)
    ]
    covered = sorted({p[0] for p in (parse_step_key(k) for k in about) if p is not None})
    if declared and len(covered) > 1:
        bound += (
            f" The question covered steps {', '.join(str(i) for i in covered)}: put each answer under its own step "
            "(the expert may answer by number or by name)."
        )
    if P16_KEY in about or (about and all(k.endswith(".name") for k in about)):
        bound += (
            " The question asked for the list of main steps: emit `process.substeps[i].name` for every step named, "
            f"in order (at most {MAX_STEPS}), and `process.substep_count` with how many the expert listed."
        )
    context = ""
    if asked:
        context = (
            "The question the expert is answering (the assistant's previous message) is fenced below. "
            + fence_instruction("PREVIOUS_QUESTION", "That question")
            + "\n"
            + fence_untrusted(asked, "PREVIOUS_QUESTION")
            + "\n"
            + (f"It was about these keys: {', '.join(about)}.\n" if about else "")
            + "Use it only to decide which key the words belong under. It tells you what was asked; it never tells "
            "you what was answered.\n\n"
        )
    offered = as_mapping(last_question.get("offered")) or {}
    if offered:
        context += (
            "The previous question OFFERED these values for the expert to accept (from the assistant, not yet "
            "the expert's answer). "
            + fence_instruction("OFFERED", "The offered values")
            + "\n"
            + fence_untrusted(json.dumps(offered, ensure_ascii=False), "OFFERED")
            + '\nIf the expert refers to them ("the ones you listed", "the first two", "all but GDPR"), emit '
            "the values they picked under that key, copied from the offered values. A plain acceptance of all of "
            "them may emit nothing for those keys: code writes them. A correction in their own words wins. For "
            "`process.name`: when the expert names their own work in their own words, emit their words, even if an "
            "offered name is similar; emit an offered name only when they pick it.\n\n"
        )
    ideas = ""
    if phase == "find":
        ideas = (
            "Other recurring work: if the expert mentions other pieces of recurring work besides the one being "
            'discussed, also return them as `"candidates": [{"name": "<short name in their words>", "words": '
            '"<what they said about it, copied>"}]`. That key is not a field; never invent a candidate. When the '
            "expert describes several pieces of recurring work and has not said which one to map, return them all as "
            "candidates and emit no `process.name`: the choice is theirs.\n\n"
            "Candidate signals: when the expert says how often, how long, how many people or what the work starts "
            "from for a candidate, return `candidate_signals` with the candidate's name and their words: "
            '`"candidate_signals": [{"name": "<candidate>", "runs": "<how often>", "time": "<how long>", "people": '
            '"<how many people>", "inputs": "<what it starts from>"}]`, only the parts they said, copied; never a '
            "number of your own. That key is not a field either.\n\n"
        )
        if candidates:
            ideas += (
                "Candidates already heard (use exactly these names in `candidate_signals`, and do not return them "
                "again as candidates): "
                + fence_instruction("CANDIDATES", "The candidate names")
                + "\n"
                + fence_untrusted("\n".join(candidates), "CANDIDATES")
                + "\n\n"
            )
    return (
        "You are a data extraction assistant. Your only job is to turn the expert's message into a JSON object of "
        "field changes.\n\n"
        "The current profile is below. "
        + fence_instruction("PROFILE", "The profile")
        + "\n"
        + fence_untrusted(json.dumps(extract_view(profile), ensure_ascii=False), "PROFILE")
        + "\n\n"
        + fence_instruction("EXPERT_MESSAGE", "The expert's message")
        + "\n\n"
        + context
        + "Extract ONLY what the expert explicitly stated. Do NOT infer, complete or assume. Return a JSON object whose "
        "keys are drawn from this list and nothing else:\n"
        f"{keys}\n\n"
        "These keys take rows, not strings:\n"
        f"{shapes}\n"
        f"{ROW_EXAMPLE} Rows are merged into what the step already holds, so emit only the rows this message names; "
        "never repeat stored rows; never emit the none row to mean 'that is all'.\n\n"
        f"{bound}\n\n"
        "Emit `process.name` only when the expert names the one process to map, or agrees to a name the previous "
        "question proposed in their words.\n\n"
        "Fix obvious typos and misspellings in the text you extract, nothing more. Keep the expert's own words, their "
        "phrasing, their level of detail and their language. Never rephrase, translate, expand abbreviations, "
        "summarise, lengthen or make it sound more formal. Leave names of people, teams, systems, tools and products, "
        "jargon and codes exactly as typed. When in doubt, copy it verbatim.\n\n"
        'An absence is an answer. If the expert says there are none ("no approvals", "nobody else", "nothing goes '
        'wrong", "no sensitive data") that is a complete answer to the question that was asked: emit the none row '
        '[{"none": true}] for `process.sensitive_data`, `process.substeps[i].roles`, `process.substeps[i].approvals` '
        'or `process.substeps[i].exceptions`, and `{"none_identified": true}` for `process.process_owner` when nobody '
        "owns it. Use the previous question to decide which one key they are saying no to, and emit it for that key "
        "only; a plain no to the optional step question (sign-off, what goes wrong, passing it on) is a no to "
        "both approvals and exceptions of that step.\n\n"
        "Facts for other keys: if the message also states, explicitly, a value for another key in the list (a "
        "duration, a count, a role, a system), emit it under that key as well, copied. Never move a value the "
        "expert gave for one step to another step.\n\n"
        'One item per thing: in lists, one row or item per system, role, input or output. Names joined by "/", '
        '"and" or "+" are separate items ("Excel/SharePoint" is "Excel" and "SharePoint"), unless the slash is '
        'part of a product name, such as "SAP S/4HANA".\n\n'
        'Pronouns: when the expert says "they", "he" or "she" for a role that the previous question or the same '
        "message names, write the role, not the pronoun.\n\n"
        "Decision criteria: `process.substeps[i].decision_criteria` is "
        '`{"basis": "<what the decision is based on>", "set_by": "<role>", "written": "yes" | "partly" | "no", '
        '"varies": "<what changes from case to case or person to person>"}`, each in the expert\'s words; emit '
        "only the parts they said.\n\n"
        "Rules or judgement: `process.substeps[i].decision_type` is "
        '`{"kind": "rules" | "judgement" | "mix", "evidence": "<the expert\'s words, copied>"}`: rules when the '
        "step follows fixed rules, judgement when the expert decides case by case, mix for both. Emit it only "
        "when the expert said so.\n\n"
        "Sensitive data: a bare yes to the sensitive data question, without saying which data or regulation, is "
        "not an item: emit nothing for `process.sensitive_data` (the next question asks which).\n\n"
        "Not yours to write: never write the cluster, a confirmation or a flag. A yes or no to a proposal or to a list "
        "is read by code, so emit nothing for it.\n\n"
        + ideas
        + "Return one JSON object. If the expert said nothing extractable, return an empty JSON object {}."
    )


def extractor_user(text: str) -> str:
    """The user message: the expert's text, fenced as `EXPERT_MESSAGE`."""
    return fence_untrusted(text, "EXPERT_MESSAGE")
