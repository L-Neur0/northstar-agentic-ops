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
Spec 14 §3.4, §3.10; AC-14.2 to AC-14.7, AC-14.37, AC-14.49, AC-14.52, AC-14.53, AC-14.55.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from pydantic import BaseModel, ConfigDict

from app.utils.prompt_safety import contains_injection_pattern

from ..domain.field_spec import PHASE_FIND, PROFILE_SPECS, Vocabulary
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
from ..profile.scoring import finish_check, score
from ..profile.shapes import as_list, as_mapping, normalized_profile, process_of, resolve_key, rows_of, stored_value
from ..profile.verdicts import P16_KEY, field_counts
from .gates import apply_scope_verdict, classification_subject, current_name, needs_placement, needs_scope
from .phases import (
    advance_phase,
    ask_count,
    cell_escapes,
    charge_asks,
    deferred_keys,
    given_up_keys,
    last_question_for,
    next_ask,
    phase_blocks,
    read_counters,
)
from .prompts.classifier import classifier_system, classifier_user
from .prompts.common import text_value
from .prompts.extractor import extractor_system, extractor_user
from .prompts.guide import guide_messages
from .replies import last_agent_message, read_cluster_reply, read_proposal_reply, read_rollup_reply
from .types import Ask, InterviewContext, TurnState

GUIDE_RESERVE_SECONDS = 30
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

    # 3. the model call
    raw: dict[str, Any] = {}
    if text:
        messages: list[ChatMessage] = [
            {
                "role": "system",
                "content": extractor_system(
                    profile, last_agent_message(state), question, vocab=vocab, phase=prior_phase
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
    dropped = [*unknown_change_keys(raw), *(k for k in raw if k not in allowed and k != "candidates")]

    # 5. apply
    result = apply_changes(profile, screened, vocab=vocab, at=now)
    profile = result.profile
    dropped += [f"{k}({r})" for k, r in result.refused] + [f"{k}(injection)" for k in injected]

    # 6. ideas
    ideas = _ideas(candidates, profile) if candidates is not None else []

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
        done = reject_proposals(profile, waiting, vocab=vocab, at=now)
        profile, rejected = done.profile, done.written

    # 9. roll-up reply
    targets = read_rollup_reply(
        state, text, lexicon=ctx.lexicon, steps_written=result.touched_steps, profile_after=profile
    )
    for target in targets:
        profile = confirm_rollup(profile, target, vocab=vocab)

    # 10. charge the asks
    if text:
        counters = charge_asks(counters, question, prior_phase, find_turns_before=counters["find_turns"])

    # 11. step-cell limits
    none_rows, skips = cell_escapes(profile, counters, vocab=vocab)
    if none_rows:
        profile = apply_changes(profile, none_rows, vocab=vocab, at=now).profile
    if skips:
        profile = mark_cells_skipped(profile, skips, vocab=vocab)

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

    # 13. score and phase
    sc = score(profile, vocab=vocab)
    phase = advance_phase(profile, prior_phase, counters, vocab=vocab)

    # 14. log fields (keys, counts and codes only)
    log.update(
        phase_in=prior_phase,
        offered=sorted(str(k) for k in raw),
        dropped=dropped,
        written_but_incomplete=sorted(
            f"{k}({'+'.join(v.missing) or v.status})" for k, v in result.verdicts.items() if not v.is_complete
        ),
        proposals_confirmed=confirmed,
        proposals_rejected=rejected,
        rollups_confirmed=list(targets),
        escapes=sorted([*none_rows, *skips]),
        deferred=deferred_keys(profile, counters, vocab=vocab),
        given_up=given_up_keys(profile, counters, vocab=vocab),
        substep_count_assumed=assumed,
        ideas=len(ideas),
    )
    return {
        "profile": profile,
        "score": sc._asdict(),
        "counters": counters,
        "phase": phase,
        "placement": placement,
        "user_input": "",
        "ideas": ideas,
        "log": log,
    }


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


def fallback_question(ask: Ask, profile: Mapping[str, Any], *, vocab: Vocabulary, process_name: str) -> str:
    """A plain question built by code from the ask target; never mentions a failure, never "noted"."""
    p = normalized_profile(profile)
    if ask.kind in ("field", "cell") and ask.keys:
        address = resolve_key(ask.keys[0])
        if address is not None:
            question = vocab.question(address.spec) or f"Could you tell me about {vocab.label(address.spec).lower()}?"
            if address.step is not None:
                rows = rows_of(p)
                name = str(rows[address.step - 1].get("name") or "").strip() if address.step <= len(rows) else ""
                return f"For step {address.step}{', ' + name if name else ''}: {question}"
            return question
    if ask.kind == "proposals" and ask.keys:
        parts = [f"{_label(k, vocab)}: {text_value(stored_value(p, k))}" for k in ask.keys]
        return (
            f"I read this in your document: {'; '.join(parts)}. Is that right? Say yes, or tell me what is different."
        )
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
    return fallback_question(ask, profile, vocab=vocab, process_name=name)


async def guide_node(state: TurnState, llm: LLM, ctx: InterviewContext) -> dict[str, Any]:
    """Write the one question of this turn; on any failure, the code-built fallback for the same ask target."""
    vocab = ctx.vocab
    profile = normalized_profile(state.get("profile"))
    ask = next_ask(state, vocab=vocab)
    finish = finish_check(profile, vocab=vocab, scope=state.get("scope"))
    log = _log(state)
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
    fallback_used = not reply
    if fallback_used:
        reply = _fallback(state, ask, vocab)
    counters = read_counters(state.get("counters"))
    log.update(
        ask_kind=ask.kind,
        focus=list(ask.keys),
        focus_asks=ask_count(ask, counters),
        finish_blocked_by=finish.blocked_by,
        fallback_used=fallback_used,
        proposals_waiting=len(proposed_keys(profile)),
    )
    message = {"id": str(uuid.uuid4()), "role": "agent", "text": reply, "at": state.get("now", "")}
    return {
        "messages": [*(state.get("messages") or []), message],
        "reply": reply,
        "last_question": last_question_for(ask),
        "log": log,
    }
