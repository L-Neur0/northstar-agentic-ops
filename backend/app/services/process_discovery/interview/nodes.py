"""The three LangGraph nodes of one turn: EXTRACT, CLASSIFY and GUIDE (spec 14 §3.4, §3.10; architecture §3.3, §6.2).

Why: the nodes are the only place the interview talks to a model, so they are where the failure
rules live: a failed EXTRACT changes nothing (replies read by code still apply), a failed CLASSIFY
gives the neutral verdict and an unknown placement, a failed GUIDE gives a plain question built by
code. A turn always ends with a question and keeps the work already done; only a refused daily
budget in EXTRACT stops the turn (nothing is saved). Every decision is delegated to `phases`,
`gates`, `replies` and `profile`; the nodes only sequence them in the order of §3.4.
What: `extract_node`, `classify_node`, `guide_node`, `fallback_question`, the CLASSIFY output
models (`ScopeOut`, `PlacementOut`, `ClassifyBoth`, `ClassifyScope`, `ClassifyPlacement`) and the
turn guard (each call under `asyncio.wait_for` with its share of the turn deadline; a share under
1 s skips the call and takes the failure path).
Must not: write a field itself (every write goes through `profile`), log any text (keys, counts,
codes and times only), or pass `max_tokens` (budgets come from the call types).
In `find` EXTRACT also feeds steering (§3.15): candidates and their signals are kept on the session,
a yes to the recommendation writes P04 through `apply_changes`, and the guide counts the steering
and recommendation questions it asks. The ranking itself is code in `steering.py`.
Spec 14 §3.4, §3.10, §3.15; AC-14.2 to AC-14.7, AC-14.37, AC-14.49, AC-14.52, AC-14.53, AC-14.55,
AC-14.66, AC-14.72, AC-14.74, AC-14.75, AC-14.78. Amendment §3.17: a conflict reply is read by code
(step 2), a clear choice drops EXTRACT's writes to the group's fields and is written by
`resolve_conflicts` (step 8b), the asks are charged and a conflict at its limit is left (10, 10b),
and a conflict turn's question is built by code without GUIDE (AC-14.92, AC-14.97 to AC-14.99).
Amendment §3.19 (short step walk): Tier C is proposed by code after the cell limits (step 11b), a "no"
to agent proposals clears and skips them, and a group ask gets a code-built group question as its
fallback (AC-14.112, AC-14.113, AC-14.115).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from app.utils.prompt_safety import contains_injection_pattern

from ..domain.field_spec import (
    GROUP_B,
    GROUP_EFFORT,
    GROUP_NAMES,
    MAX_STEPS,
    NONE_KEY,
    PHASE_FIND,
    PHASE_REVIEW,
    PHASE_STEPS,
    PROFILE_SPECS,
    Vocabulary,
    step_cell_key,
)
from ..domain.scope import (
    SIGNAL_QUESTIONS,
    build_placement,
    build_scope_verdict,
    failed_signals,
    keyword_placement,
    neutral_scope_verdict,
    proposable_code,
    unknown_placement,
)
from ..llm import LLM, CallType, ChatMessage, LLMBudgetExceededError, LLMError
from ..profile.coercion import coerce_text
from ..profile.conflicts import ConflictView, mark_conflicts_left, open_conflicts, resolve_conflicts
from ..profile.inferred import decline_agent_proposals, is_agent_proposal, propose_tier_c
from ..profile.mutate import (
    UnknownClusterError,
    allowed_changes,
    apply_changes,
    assume_substep_count,
    confirm_rollup,
    mark_cells_skipped,
    set_cluster,
    unknown_change_keys,
)
from ..profile.proposals import confirm_proposals, proposed_keys, reject_proposals
from ..profile.scoring import FinishCheck, finish_check, score
from ..profile.shapes import (
    as_list,
    as_mapping,
    normalized_profile,
    parse_step_key,
    process_of,
    resolve_key,
    rows_of,
    stored_value,
)
from ..profile.verdicts import ASSUMED_FREQUENCY, P16_KEY, field_counts, volume_words
from .conflict_question import both_offered, conflict_question
from .finish_offer import with_finish_offer
from .gates import (
    apply_scope_verdict,
    classification_subject,
    current_name,
    needs_placement,
    needs_scope,
    refresh_scope,
)
from .phases import (
    advance_phase,
    ask_count,
    cell_escapes,
    charge_asks,
    charge_conflicts,
    deferred_keys,
    given_up_keys,
    last_question_for,
    next_ask,
    phase_blocks,
    posture,
    read_counters,
)
from .prompts.classifier import classifier_system, classifier_user
from .prompts.common import text_value
from .prompts.extractor import extractor_system, extractor_user
from .prompts.guide import from_image, guide_messages, image_documents
from .prompts.steering_text import pick_fallback, recommend_fallback, steer_fallback
from .replies import (
    Choice,
    last_agent_message,
    mentions,
    read_cluster_reply,
    read_conflict_reply,
    read_offer_reply,
    read_proposal_reply,
    read_recommendation_reply,
    read_rollup_reply,
)
from .steering import (
    STEER_PREFIX,
    add_candidates,
    advance,
    apply_signals,
    changed_ideas,
    ranked,
    read_steering,
)
from .types import Ask, InterviewContext, TurnState

GUIDE_RESERVE_SECONDS = 30
VARIATION_KEY = "process.variation"
NAME_KEY = "process.name"
MIN_SHARE_SECONDS = 1.0
IDEAS_MAX = 5


class ScopeOut(BaseModel):
    """The five signals and one sentence of reasoning (CLASSIFY part 1)."""

    model_config = ConfigDict(extra="forbid")
    multi_role: bool
    multi_system: bool
    trigger_and_outcome: bool
    recurring: bool
    external_consumer: bool
    reasoning: str


class PlacementOut(BaseModel):
    """A cluster code with a confidence, a rationale and an optional runner-up (CLASSIFY part 2)."""

    model_config = ConfigDict(extra="forbid")
    code: str
    confidence: float
    rationale: str
    runner_up: str | None
    runner_up_confidence: float | None


class ClassifyBoth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: ScopeOut
    placement: PlacementOut


class ClassifyScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: ScopeOut


class ClassifyPlacement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    placement: PlacementOut


class _Skipped(Exception):
    """The turn has less than a second left for this call."""


async def _guarded[R](make: Callable[[], Awaitable[R]], share: float) -> R:
    """Run one model call under its share of the turn; under 1 s the call is not made."""
    if share < MIN_SHARE_SECONDS:
        raise _Skipped()
    return await asyncio.wait_for(make(), timeout=share)


def _remaining(state: Mapping[str, Any]) -> float:
    deadline = state.get("deadline")
    if not isinstance(deadline, int | float):
        return float("inf")
    return float(deadline) - time.monotonic()


def _call_log(outcome: str, started: float) -> dict[str, Any]:
    return {"outcome": outcome, "ms": int((time.monotonic() - started) * 1000)}


def _log(state: Mapping[str, Any]) -> dict[str, Any]:
    log = dict(as_mapping(state.get("log")) or {})
    log["calls"] = dict(as_mapping(log.get("calls")) or {})
    return log


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    mapping = as_mapping(value)
    if mapping is not None:
        return [s for v in mapping.values() for s in _strings(v)]
    items = as_list(value)
    if items is not None:
        return [s for v in items for s in _strings(v)]
    return []


def screen(changes: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Drop every entry whose text matches an injection pattern; return the kept entries and the dropped keys."""
    kept: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in changes.items():
        if any(contains_injection_pattern(text) for text in _strings(value)):
            dropped.append(key)
        else:
            kept[key] = value
    return kept, dropped


def _ideas(raw: Any, profile: Mapping[str, Any]) -> list[dict[str, str]]:
    """Candidates from EXTRACT (find only): screened, capped at 5, the chosen name removed."""
    chosen = str(process_of(profile).get("name") or "").strip().casefold()
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in as_list(raw) or []:
        item = as_mapping(entry) or {}
        name = coerce_text(item.get("name"))
        words = coerce_text(item.get("words")) or ""
        if name is None or name.casefold() in seen or name.casefold() == chosen:
            continue
        if contains_injection_pattern(name) or contains_injection_pattern(words):
            continue
        seen.add(name.casefold())
        out.append({"name": name, "words": words})
        if len(out) >= IDEAS_MAX:
            break
    return out


# --- EXTRACT --------------------------------------------------------------------------------------


async def extract_node(state: TurnState, llm: LLM, ctx: InterviewContext) -> dict[str, Any]:
    """§3.4: read replies in code, call EXTRACT, apply, settle replies, charge asks, apply limits, score, phase."""
    vocab = ctx.vocab
    now = state.get("now", "")
    text = (state.get("user_input") or "").strip()
    prior_phase = state.get("phase", "context")
    question = dict(state.get("last_question") or {})
    profile = normalized_profile(state.get("profile"))
    counters = read_counters(state.get("counters"))
    placement = dict(state.get("placement") or {})
    log = _log(state)

    # 2. replies read by code, on the incoming state
    cluster_reply = read_cluster_reply(state, text, vocab=vocab, lexicon=ctx.lexicon) if text else None
    proposal_verdict, proposal_keys = read_proposal_reply(state, text, lexicon=ctx.lexicon) if text else (None, ())
    recommend_verdict, recommended = (
        read_recommendation_reply(state, text, vocab=vocab, lexicon=ctx.lexicon) if text else (None, None)
    )
    steering_in = read_steering(state.get("steering"))
    conflict_keys = [k for k in as_list(question.get("conflicts")) or [] if isinstance(k, str)]
    group = [v for v in open_conflicts(profile, status="open") if v.conflict_key in conflict_keys]
    choice = _conflict_choice(state, text, profile, group) if text and group else None
    offer_verdict, offered = read_offer_reply(state, text, lexicon=ctx.lexicon) if text else (None, {})

    # 3. the model call
    raw: dict[str, Any] = {}
    if text:
        messages: list[ChatMessage] = [
            {
                "role": "system",
                "content": extractor_system(
                    profile,
                    last_agent_message(state),
                    question,
                    vocab=vocab,
                    phase=prior_phase,
                    candidates=[c["name"] for c in steering_in["candidates"]],
                ),
            },
            {"role": "user", "content": extractor_user(text)},
        ]
        started = time.monotonic()
        try:
            raw = await _guarded(
                lambda: llm.generate_json(CallType.EXTRACT, messages), _remaining(state) - GUIDE_RESERVE_SECONDS
            )
            log["calls"]["extract"] = _call_log("ok", started)
        except LLMBudgetExceededError:
            raise
        except _Skipped:
            log["calls"]["extract"] = _call_log("skipped", started)
        except TimeoutError:
            log["calls"]["extract"] = _call_log("timeout", started)
        except LLMError:
            log["calls"]["extract"] = _call_log("failed", started)
        log["extract"] = "ok" if log["calls"]["extract"]["outcome"] == "ok" else "failed"

    # 4. whitelist and injection screen
    candidates = raw.get("candidates") if prior_phase == PHASE_FIND else None
    allowed = allowed_changes(raw)
    screened, injected = screen(allowed)
    side_keys = ("candidates", "candidate_signals")
    dropped = [*unknown_change_keys(raw), *(k for k in raw if k not in allowed and k not in side_keys)]

    # 4b. a process name that is an offered candidate the reply did not pick is dropped (§3.20 O2)
    if text and _unpicked_offer(screened, offered, text, ctx):
        screened = _without_fields(screened, {NAME_KEY})
        dropped.append(f"{NAME_KEY}(unpicked_offer)")

    # 5. apply (a clear conflict choice is the answer: EXTRACT's writes to those fields are dropped, §3.17)
    if choice is not None:
        screened = _without_fields(screened, {v.key for v in group})
    result = apply_changes(profile, screened, vocab=vocab, at=now)
    profile = result.profile
    dropped += [f"{k}({r})" for k, r in result.refused] + [f"{k}(injection)" for k in injected]

    # 5a. durations answered on the effort question take the assumed frequency (§3.21 P3)
    assumed = _assumed_frequencies(profile, offered, set(result.written)) if text else {}
    if assumed:
        quote = f"{text} (accepted the agent's assumption)"
        profile = apply_changes(profile, assumed, vocab=vocab, at=now, quote=quote).profile
    offered = {k: v for k, v in offered.items() if not k.endswith(".effort")}

    # 5b. a yes to the values the last question offered writes them as the expert's answer (§3.20 O6)
    accepted: list[str] = []
    if offer_verdict == "yes":
        taken = _accepted_offer(profile, offered, set(result.written), vocab=vocab)
        quote = f"{text} (accepted the agent's suggestion)"
        offer_result = apply_changes(profile, taken, vocab=vocab, at=now, quote=quote)
        profile, accepted = offer_result.profile, offer_result.written
    # 5b'. a plain yes to the two quick yes/no questions is a yes to "the same everywhere" (§3.20 O11);
    # a bare yes to sensitive data names nothing, so the next question asks which (with examples, O5)
    focus = [k for k in as_list(question.get("focus")) or [] if isinstance(k, str)]
    # (EXTRACT may copy the whole sentence into `same`, which is then invalid: code reads the reply instead)
    if text and VARIATION_KEY in focus and not field_counts(profile, VARIATION_KEY, vocab=vocab):
        if ctx.lexicon.says_same(text):
            profile = apply_changes(profile, {VARIATION_KEY: {"same": "yes"}}, vocab=vocab, at=now).profile
    # 5c. a plain no to the optional step question settles approvals and exceptions with the none row (§3.20 O8)
    if text and ctx.lexicon.is_no(text):
        nones = {k: [{NONE_KEY: True}] for k in _optional_none_keys(question) if k not in result.written}
        if nones:
            profile = apply_changes(profile, nones, vocab=vocab, at=now).profile

    # 6. ideas and steering (find only): candidates and their signals; a yes to the recommendation names it
    steering = steering_in
    if prior_phase == PHASE_FIND:
        steering = add_candidates(steering, _ideas(candidates, profile) if candidates is not None else [])
        if ctx.steering is not None:
            steering = apply_signals(steering, raw.get("candidate_signals"), ctx.steering)
    chosen = next((c for c in steering["candidates"] if c["id"] == recommended), None)
    if recommend_verdict == "yes" and chosen is not None and not field_counts(profile, NAME_KEY, vocab=vocab):
        profile = apply_changes(profile, {NAME_KEY: chosen["name"]}, vocab=vocab, at=now).profile
    elif recommend_verdict == "no":
        steering = {**steering, "declined": True}

    # 7. cluster reply
    if cluster_reply is not None and cluster_reply.verdict is True and cluster_reply.code:
        try:
            decided = "named" if cluster_reply.source == "named" else "proposal"
            profile = set_cluster(profile, cluster_reply.code, decided_by=decided, vocab=vocab, at=now)
        except UnknownClusterError:
            placement = {**placement, "proposal": None, "rejected": True}
    elif cluster_reply is not None and cluster_reply.verdict is False:
        placement = {**placement, "proposal": None, "rejected": True}
    log["cluster_reply"] = (
        "none"
        if cluster_reply is None or cluster_reply.verdict is None
        else "named"
        if cluster_reply.source == "named"
        else "yes"
        if cluster_reply.verdict
        else "no"
    )

    # 8. proposal reply (a key the expert's own words rewrote keeps them)
    rewritten = set(result.written)
    waiting = [k for k in proposal_keys if (a := resolve_key(k)) is not None and a.key not in rewritten]
    confirmed: list[str] = []
    rejected: list[str] = []
    if proposal_verdict == "yes" and waiting:
        done = confirm_proposals(profile, waiting, vocab=vocab, at=now)
        profile, confirmed = done.profile, done.written
    elif proposal_verdict == "no" and waiting:
        agent = [k for k in waiting if is_agent_proposal(profile, k)]  # §3.19 W8: cleared and skipped
        others = [k for k in waiting if k not in agent]
        if agent:
            profile = decline_agent_proposals(profile, agent)
            rejected += agent
        if others:
            done = reject_proposals(profile, others, vocab=vocab, at=now)
            profile, rejected = done.profile, [*rejected, *done.written]

    # 8b. conflict choice (§3.17 item 5)
    if choice is not None:
        profile = resolve_conflicts(profile, [v.conflict_key for v in group], choice, vocab=vocab, at=now).profile

    # 9. roll-up reply
    targets = read_rollup_reply(
        state, text, lexicon=ctx.lexicon, steps_written=result.touched_steps, profile_after=profile
    )
    for target in targets:
        profile = confirm_rollup(profile, target, vocab=vocab)

    # 10. charge the asks; 10b. a conflict asked to its limit is left as it is (§3.17 item 5)
    left: list[str] = []
    if text:
        counters = charge_asks(counters, question, prior_phase, find_turns_before=counters["find_turns"])
        still_open = {v.conflict_key for v in open_conflicts(profile, status="open")}
        counters, left = charge_conflicts(counters, conflict_keys, still_open)
        if left:
            profile = mark_conflicts_left(profile, left)

    # 11. step-cell limits
    none_rows, skips = cell_escapes(profile, counters, vocab=vocab)
    if none_rows:
        profile = apply_changes(profile, none_rows, vocab=vocab, at=now).profile
    if skips:
        profile = mark_cells_skipped(profile, skips, vocab=vocab)
    # 11b. Tier C is proposed by code, never asked (§3.19 W6)
    profile = propose_tier_c(profile, vocab=vocab, at=now)

    # 12. a deferred step count is assumed the same turn
    assumed = False
    if (
        not field_counts(profile, P16_KEY, vocab=vocab)
        and (
            P16_KEY in deferred_keys(profile, counters, vocab=vocab)
            or P16_KEY in given_up_keys(profile, counters, vocab=vocab)
        )
        and not phase_blocks(profile, "step_count", counters, vocab=vocab)
    ):
        profile = assume_substep_count(profile, vocab=vocab, at=now)
        assumed = True

    # 13. score and phase; steering moves on (§3.15 item 8)
    sc = score(profile, vocab=vocab)
    phase = advance_phase(profile, prior_phase, counters, vocab=vocab)
    if ctx.steering is not None:
        steering = advance(
            steering,
            phase=phase,
            name_counts=field_counts(profile, NAME_KEY, vocab=vocab),
            posture=posture(counters["find_turns"]),
            cfg=ctx.steering,
        )
    name = str(process_of(profile).get("name") or "") if field_counts(profile, NAME_KEY, vocab=vocab) else ""
    ideas = changed_ideas(steering_in, steering, name) if prior_phase == PHASE_FIND else []
    # 13b. once the walk has started, the mapped steps refresh the scope verdict (§3.21 P6)
    scope_in = as_mapping(state.get("scope")) or {}
    scope_out = refresh_scope(scope_in, profile) if phase in (PHASE_STEPS, PHASE_REVIEW) else dict(scope_in)

    # 14. log fields (keys, counts and codes only)
    log.update(
        phase_in=prior_phase,
        offered=sorted(str(k) for k in raw),
        dropped=dropped,
        written_but_incomplete=sorted(
            f"{k}({'+'.join(v.missing) or v.status})" for k, v in result.verdicts.items() if not v.is_complete
        ),
        proposals_confirmed=confirmed,
        offer=offer_verdict,
        offer_accepted=accepted,
        proposals_rejected=rejected,
        rollups_confirmed=list(targets),
        escapes=sorted([*none_rows, *skips]),
        deferred=deferred_keys(profile, counters, vocab=vocab),
        given_up=given_up_keys(profile, counters, vocab=vocab),
        substep_count_assumed=assumed,
        ideas=len(ideas),
        conflicts=len(conflict_keys),
        choice=(choice or ("own_words" if set(result.conflicts_closed) & set(conflict_keys) else "none"))
        if conflict_keys
        else None,
        left=len(left),
    )
    return {
        "profile": profile,
        "score": sc._asdict(),
        "counters": counters,
        "phase": phase,
        "placement": placement,
        "user_input": "",
        "ideas": ideas,
        "steering": steering,
        "scope": scope_out,
        "log": log,
    }


def _accepted_offer(
    profile: Mapping[str, Any], offered: Mapping[str, Any], written: set[str], *, vocab: Vocabulary
) -> dict[str, Any]:
    """The offered values to write: those EXTRACT did not write this turn (a correction wins); offered step
    names with no counting P16 also set the count to the number of names."""
    taken = {k: v for k, v in offered.items() if (a := resolve_key(k)) is not None and a.key not in written}
    name = taken.pop(NAME_KEY, None)
    names = [n for n in (as_list(name) or [name]) if isinstance(n, str) and n.strip()]
    if len(names) == 1:  # several suggested candidates: "the first one" is resolved by EXTRACT, never by code
        taken[NAME_KEY] = names[0]
    names = [parse_step_key(k) for k in taken if k.endswith(".name")]
    indexes = [n[0] for n in names if n is not None]
    if indexes and not field_counts(profile, P16_KEY, vocab=vocab) and P16_KEY not in written:
        taken = {P16_KEY: max(indexes), **taken}
    return taken


def _unpicked_offer(changes: Mapping[str, Any], offered: Mapping[str, Any], text: str, ctx: InterviewContext) -> bool:
    """EXTRACT named the process with an offered candidate that the expert did not pick: a yes, a pick
    ("the second one") or the name itself in the reply. Their own words are the name, never our offer."""
    candidates = [c for c in (as_list(offered.get(NAME_KEY)) or [offered.get(NAME_KEY)]) if isinstance(c, str)]
    nested = as_mapping(changes.get("process")) or {}
    name = changes.get(NAME_KEY, nested.get("name"))
    if not isinstance(name, str) or name.strip().casefold() not in {c.strip().casefold() for c in candidates}:
        return False
    lexicon = ctx.lexicon
    return not (lexicon.accepts(text) or lexicon.picks(text) or mentions(text, name.strip()))


def _optional_none_keys(question: Mapping[str, Any]) -> list[str]:
    """The asked approvals and exceptions cells of the optional step question (group B)."""
    out: list[str] = []
    for key in as_list(question.get("focus")) or []:
        address = resolve_key(key) if isinstance(key, str) else None
        if address is not None and address.step is not None and address.spec.group == GROUP_B:
            if address.spec.key in ("approvals", "exceptions"):
                out.append(address.key)
    return out


def _conflict_choice(
    state: Mapping[str, Any], text: str, profile: Mapping[str, Any], group: list[ConflictView]
) -> Choice | None:
    names = {str(d.get("id")): str(d.get("name")) for d in state.get("documents") or []}
    first = group[0]
    return read_conflict_reply(
        text,
        kind=first.kind,
        both_offered=both_offered(profile, group),
        holder_name=names.get(first.holder_document_id or "") if first.kind == "document" else None,
        offered_name=names.get(first.document_id, ""),
    )


def _without_fields(changes: Mapping[str, Any], fields: set[str]) -> dict[str, Any]:
    """The changes without those that land on `fields` (canonical keys), nested `process` form included."""
    out: dict[str, Any] = {}
    for key, value in changes.items():
        nested = as_mapping(value) if key == "process" else None
        if nested is not None:
            kept = {leaf: v for leaf, v in nested.items() if f"process.{leaf}" not in fields}
            if kept:
                out[key] = kept
            continue
        address = resolve_key(key)
        if address is None or address.key not in fields:
            out[key] = value
    return out


# --- CLASSIFY -------------------------------------------------------------------------------------


async def classify_node(state: TurnState, llm: LLM, ctx: InterviewContext) -> dict[str, Any]:
    """Judge the named activity (scope) and place it (cluster); one keyword hit settles placement without a call."""
    vocab = ctx.vocab
    profile = normalized_profile(state.get("profile"))
    subject = classification_subject(state, vocab=vocab)
    name = current_name(profile, vocab=vocab)
    log = _log(state)
    if not subject or not name:
        return {"log": log}
    want_scope = needs_scope(state, vocab=vocab)
    want_placement = needs_placement(state, vocab=vocab)
    scope = dict(state.get("scope") or {})
    counters = read_counters(state.get("counters"))
    placement = dict(state.get("placement") or {})
    keyword_hit = False
    if want_placement:
        hit = vocab.taxonomy.single_match(name)
        if hit is not None:
            placement = {"proposal": keyword_placement(hit.code), "placed_for": name, "rejected": False}
            want_placement = False
            keyword_hit = True
    halves = [h for h, on in (("scope", want_scope), ("placement", want_placement)) if on]
    updates: dict[str, Any] = {"placement": placement}
    log["classify"] = {"halves": halves, "keyword_hit": keyword_hit, "raw_confidence": None}
    if not halves:
        updates["log"] = log
        return updates

    model_cls: type[BaseModel] = (
        ClassifyBoth if want_scope and want_placement else ClassifyScope if want_scope else ClassifyPlacement
    )
    messages: list[ChatMessage] = [
        {
            "role": "system",
            "content": classifier_system(with_scope=want_scope, with_placement=want_placement, taxonomy=vocab.taxonomy),
        },
        {
            "role": "user",
            "content": classifier_user(subject, profile, widening=(scope.get("awaiting_widening") is True)),
        },
    ]
    started = time.monotonic()
    parsed: dict[str, Any] = {}
    try:
        out = await _guarded(
            lambda: llm.generate_structured(model_cls, CallType.CLASSIFY, messages),
            _remaining(state) - GUIDE_RESERVE_SECONDS,
        )
        parsed = out.model_dump()
        log["calls"]["classify"] = _call_log("ok", started)
    except _Skipped:
        log["calls"]["classify"] = _call_log("skipped", started)
    except TimeoutError:
        log["calls"]["classify"] = _call_log("timeout", started)
    except LLMError:
        log["calls"]["classify"] = _call_log("failed", started)

    if want_scope:
        raw_scope = as_mapping(parsed.get("scope"))
        verdict = build_scope_verdict(raw_scope) if raw_scope is not None else neutral_scope_verdict()
        scope, counters = apply_scope_verdict(scope, counters, verdict, name)
        updates.update(scope=scope, counters=counters, classified=True)
    if want_placement:
        raw_placement = as_mapping(parsed.get("placement"))
        proposal = (
            build_placement(
                raw_placement,
                vocab.taxonomy,
                min_confidence=ctx.settings.placement_min_confidence,
                min_margin=ctx.settings.placement_min_margin,
            )
            if raw_placement is not None
            else unknown_placement()
        )
        log["classify"]["raw_confidence"] = proposal["raw_confidence"]
        updates["placement"] = {"proposal": proposal, "placed_for": name, "rejected": False}
    updates["log"] = log
    return updates


# --- GUIDE ----------------------------------------------------------------------------------------


def _label(key: str, vocab: Vocabulary) -> str:
    address = resolve_key(key)
    return vocab.label(address.spec) if address is not None else key


def fallback_question(
    ask: Ask,
    profile: Mapping[str, Any],
    *,
    vocab: Vocabulary,
    process_name: str,
    images: frozenset[str] = frozenset(),
    counters: Mapping[str, Any] | None = None,
) -> str:
    """A plain question built by code from the ask target; never mentions a failure, never "noted"."""
    p = normalized_profile(profile)
    if ask.kind in ("field", "cell") and len(ask.keys) > 1:
        return group_fallback(ask, p, vocab=vocab, counters=counters)
    if ask.kind in ("field", "cell") and ask.keys:
        address = resolve_key(ask.keys[0])
        if address is not None:
            question = vocab.question(address.spec) or f"Could you tell me about {vocab.label(address.spec).lower()}?"
            if address.step is not None:
                rows = rows_of(p)
                name = str(rows[address.step - 1].get("name") or "").strip() if address.step <= len(rows) else ""
                return f"For step {address.step}{', ' + name if name else ''}: {question}"
            return question
    if ask.kind == "proposals" and ask.keys and all(is_agent_proposal(p, k) for k in ask.keys):
        parts = [f"{_step_label(k, vocab)}: {text_value(stored_value(p, k))}" for k in ask.keys]
        return (
            f"I filled these in from your answers: {'; '.join(parts)}. Is that right? Say yes, or tell me what is "
            "different."
        )
    if ask.kind == "proposals" and ask.keys:
        parts = [f"{_label(k, vocab)}: {text_value(stored_value(p, k))}" for k in ask.keys]
        lead = (
            "I saw this in your image"
            if all(from_image(p, k, images) for k in ask.keys)
            else ("I read this in your document")
        )
        return f"{lead}: {'; '.join(parts)}. Is that right? Say yes, or tell me what is different."
    if ask.kind == "cluster":
        return _cluster_fallback(ask, vocab=vocab, process_name=process_name, proposal=None)
    if ask.kind == "rollups":
        proc = process_of(p)
        parts: list[str] = []
        if "process.all_roles" in ask.keys:
            parts.append(f"These are the roles across the steps: {text_value(proc.get('all_roles'))}.")
        if "process.all_tools" in ask.keys:
            lead = "And the systems" if parts else "These are the systems across the steps"
            parts.append(f"{lead}: {text_value(proc.get('all_tools'))}.")
        return " ".join(parts) + " Is that right?"
    if ask.kind == "widening":
        return SIGNAL_QUESTIONS["external_consumer"]
    if finish_check(p, vocab=vocab).ready:
        return "Is there anything you would like to correct before you press Finish?"
    labels = [vocab.label(s) for s in PROFILE_SPECS if s.key in ask.keys]
    if labels:
        return f"We still need: {', '.join(labels)}. Could you tell me about {labels[0].lower()}?"
    return "Is there anything you would like to add or correct?"


def _step_label(key: str, vocab: Vocabulary) -> str:
    address = resolve_key(key)
    if address is None:
        return key
    label = vocab.label(address.spec)
    return f"{label} (step {address.step})" if address.step is not None else label


def _parts(keys: tuple[str, ...]) -> str:
    """The `ask_part` phrases of the keys, joined as one sentence: "a, b and c"."""
    parts = [a.spec.ask_part or a.spec.label.lower() for a in (resolve_key(k) for k in keys) if a is not None]
    parts = list(dict.fromkeys(parts))
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


def group_fallback(
    ask: Ask, profile: Mapping[str, Any], *, vocab: Vocabulary, counters: Mapping[str, Any] | None = None
) -> str:
    """The code-built question for a group ask (§3.19 W11), from the registry's `ask_part` phrases."""
    first = resolve_key(ask.keys[0])
    if first is None:
        return "Could you tell me more?"
    if first.step is None:
        return f"Could you tell me {_parts(ask.keys)}?"
    rows = rows_of(profile)
    steps = sorted({a.step for a in (resolve_key(k) for k in ask.keys) if a is not None and a.step is not None})
    group = first.spec.group
    if group == GROUP_NAMES:
        return vocab.question(next(s for s in PROFILE_SPECS if s.key == P16_KEY))
    if group == GROUP_EFFORT or len(steps) > 1:
        listed = ", ".join(f"{i} {_row_name(rows, i)}".strip() for i in steps)
        runs = volume_words(profile, vocab=vocab) if group == GROUP_EFFORT else None
        if runs:
            return (
                "Roughly how long does each step take each time? I'll assume each step happens once per run of "
                f"the process (about {runs}); tell me if one happens more often. {listed}"
            )
        return f"Roughly how long does each step take, and how often? {listed}"
    index = first.step
    name = _row_name(rows, index)
    where = f'step {index}, "{name}"' if name else f"step {index}"
    if group == GROUP_B:
        return f"For {where}: {_parts(ask.keys)}? If nothing, just say no."
    if ask_count(ask, counters or {}) >= 1:
        return f"For {where}, I still need: {_parts(ask.keys)}."
    return f"Walk me through {where}: {_parts(ask.keys)}?"


def _row_name(rows: list[dict[str, Any]], index: int) -> str:
    return str(rows[index - 1].get("name") or "").strip() if 1 <= index <= len(rows) else ""


def _cluster_fallback(ask: Ask, *, vocab: Vocabulary, process_name: str, proposal: Mapping[str, Any] | None) -> str:
    code = proposable_code(proposal) if proposal is not None else ""
    cluster = vocab.taxonomy.by_code(code) if code else None
    if ask.mode == "propose" and cluster is not None:
        return (
            f"Would you file {process_name} under {cluster.name}: {cluster.description} "
            "Say yes, or name the cluster that fits better."
        )
    options = "\n".join(f"- {c.name}: {c.description}" for c in vocab.taxonomy.clusters)
    return f"Which of these fits {process_name} best?\n{options}"


def _fallback(state: Mapping[str, Any], ask: Ask, vocab: Vocabulary) -> str:
    profile = normalized_profile(as_mapping(state.get("profile")))
    name = str(process_of(profile).get("name") or "").strip() or "this work"
    if ask.kind == "cluster":
        placement = as_mapping(state.get("placement")) or {}
        return _cluster_fallback(ask, vocab=vocab, process_name=name, proposal=as_mapping(placement.get("proposal")))
    if ask.kind == "widening":
        scope = as_mapping(state.get("scope")) or {}
        failed = failed_signals(as_mapping(scope.get("verdict")) or {})
        return SIGNAL_QUESTIONS[failed[0]] if failed else SIGNAL_QUESTIONS["external_consumer"]
    steering = read_steering(as_mapping(state.get("steering")))
    if ask.kind == "steer":
        steered = [c for c in steering["candidates"] if c.get("rank")] or steering["candidates"]
        return steer_fallback([k.removeprefix(STEER_PREFIX) for k in ask.keys], steered)
    if ask.kind == "recommend":
        top = next((c for c in steering["candidates"] if c["id"] == steering["recommended_id"]), None)
        if ask.mode == "recommend" and top is not None:
            return recommend_fallback(top)
        return pick_fallback(ranked(steering) or steering["candidates"])
    return fallback_question(
        ask,
        profile,
        vocab=vocab,
        process_name=name,
        images=image_documents(state),
        counters=read_counters(as_mapping(state.get("counters"))),
    )


def _agent_reply(state: TurnState, reply: str, finish: FinishCheck, ctx: InterviewContext) -> dict[str, Any]:
    """The one place a turn's reply is finished: the *Finish* offer line (§3.18) is appended by code here."""
    text = with_finish_offer(
        reply,
        state,
        finish,
        vocab=ctx.vocab,
        first=ctx.settings.finish_offer_first,
        every=ctx.settings.finish_offer_every,
    )
    message = {"id": str(uuid.uuid4()), "role": "agent", "text": text, "at": state.get("now", "")}
    return {"messages": [*(state.get("messages") or []), message], "reply": text}


async def guide_node(state: TurnState, llm: LLM, ctx: InterviewContext) -> dict[str, Any]:
    """Write the one question of this turn; on any failure, the code-built fallback for the same ask target."""
    vocab = ctx.vocab
    profile = normalized_profile(state.get("profile"))
    ask = next_ask(state, vocab=vocab, steering=ctx.steering)
    finish = finish_check(profile, vocab=vocab, scope=state.get("scope"))
    log = _log(state)
    if ask.kind == "conflict":  # §3.17 Q4: the code-built question, no GUIDE call
        names = {str(d.get("id")): str(d.get("name")) for d in state.get("documents") or []}
        group = [v for v in open_conflicts(profile, status="open") if v.conflict_key in ask.keys]
        reply = conflict_question(profile, group, vocab=vocab, names=names)
        log.update(ask_kind=ask.kind, focus=[], focus_asks=ask_count(ask, read_counters(state.get("counters"))),
                   finish_blocked_by=finish.blocked_by, fallback_used=False,
                   proposals_waiting=len(proposed_keys(profile)))  # fmt: skip
        return {**_agent_reply(state, reply, finish, ctx), "last_question": last_question_for(ask), "log": log}
    messages = cast(
        "list[ChatMessage]",
        guide_messages(state, ask, finish, vocab=vocab, history_turns=ctx.settings.guide_history_turns),
    )
    started = time.monotonic()
    reply = ""
    try:
        reply = (await _guarded(lambda: llm.generate_text(CallType.GUIDE, messages), _remaining(state))).strip()
        log["calls"]["guide"] = _call_log("ok" if reply else "failed", started)
    except _Skipped:
        log["calls"]["guide"] = _call_log("skipped", started)
    except TimeoutError:
        log["calls"]["guide"] = _call_log("timeout", started)
    except LLMError:
        log["calls"]["guide"] = _call_log("failed", started)
    reply, offered_raw = parse_guide_reply(reply)
    fallback_used = not reply
    if fallback_used:
        reply = _fallback(state, ask, vocab)
    offered = {} if fallback_used else kept_offers(ask, offered_raw)
    offered |= assumed_effort(ask, normalized_profile(as_mapping(state.get("profile"))), vocab=vocab)
    counters = read_counters(state.get("counters"))
    log.update(
        ask_kind=ask.kind,
        focus=list(ask.keys),
        focus_asks=ask_count(ask, counters),
        finish_blocked_by=finish.blocked_by,
        fallback_used=fallback_used,
        proposals_waiting=len(proposed_keys(profile)),
    )
    steering = read_steering(state.get("steering"))
    if ask.kind == "steer":
        steering["questions"] += 1
    elif ask.kind == "recommend":
        steering["recommend_asks"] += 1
    return {
        **_agent_reply(state, reply, finish, ctx),
        "last_question": {**last_question_for(ask), "offered": offered},
        "steering": steering,
        "log": {**log, "guide_offered": sorted(offered)},
    }


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse_guide_reply(text: str) -> tuple[str, dict[str, Any]]:
    """GUIDE's `{"question", "offered"}` (§3.20 O5): plain text is the question with nothing offered;
    a reply that starts like JSON but is not that object gives `""`, so the code-built question is sent."""
    body = _FENCE.sub("", text.strip()).strip()
    if not body.startswith("{"):
        return text.strip(), {}
    try:
        parsed = json.loads(body)
    except ValueError:
        return "", {}
    question = parsed.get("question") if isinstance(parsed, dict) else None
    if not isinstance(question, str) or not question.strip():
        return "", {}
    return question.strip(), dict(as_mapping(parsed.get("offered")) or {})


def assumed_effort(ask: Ask, profile: Mapping[str, Any], *, vocab: Vocabulary) -> dict[str, Any]:
    """§3.21 P3: on the effort question, with P10 counting, "each time" is offered for every listed step."""
    keys = [k for k in ask.keys if k.endswith(".effort")]
    if ask.kind != "cell" or not keys or len(keys) != len(ask.keys) or volume_words(profile, vocab=vocab) is None:
        return {}
    return {k: {"frequency": ASSUMED_FREQUENCY} for k in keys}


def _assumed_frequencies(profile: Mapping[str, Any], offered: Mapping[str, Any], written: set[str]) -> dict[str, Any]:
    """§3.21 P3: each offered effort cell whose duration was written this turn and whose frequency is still
    empty takes the assumed frequency; a frequency the expert gave wins."""
    out: dict[str, Any] = {}
    for key, value in offered.items():
        address = resolve_key(key)
        if address is None or address.step is None or address.spec.key != "effort" or key not in written:
            continue
        rows = rows_of(profile)
        effort = as_mapping(rows[address.step - 1].get("effort")) if address.step <= len(rows) else None
        duration = str((effort or {}).get("duration") or "").strip()
        if duration and not str((effort or {}).get("frequency") or "").strip():
            out[key] = {"duration": duration, "frequency": (as_mapping(value) or {}).get("frequency")}
    return out


OFFER_KINDS = ("field", "cell", "wrap_up")
#: Candidate names a find question may suggest at once (§3.20 O2).
SUGGESTED_MAX = 3


def kept_offers(ask: Ask, offered: Mapping[str, Any]) -> dict[str, Any]:
    """The offered values code keeps: asks that collect answers, keys of the ask (a P16 ask also allows
    the step names), a value that is not blank and passes the injection screen."""
    if ask.kind not in OFFER_KINDS or not offered:
        return {}
    allowed = set(ask.keys)
    if P16_KEY in allowed:
        allowed |= {step_cell_key(i, "name") for i in range(1, MAX_STEPS + 1)}
    kept: dict[str, Any] = {}
    for key, value in offered.items():
        address = resolve_key(key)
        if address is None or address.key not in allowed or value in (None, "", [], {}):
            continue
        if address.key == NAME_KEY and isinstance(value, list):
            value = [v for v in value if isinstance(v, str) and v.strip()][:SUGGESTED_MAX] or None
            if value is None:
                continue
        kept[address.key] = value
    return screen(kept)[0]
