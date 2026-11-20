"""Steering toward value and ready data in `find`: candidates, quick questions, scores and ranks (spec 14 §3.15).

Why: when the expert names several pieces of recurring work, the agent should help them pick the
one worth mapping first, and that pick must be explainable and reproducible. So the model only
copies the expert's words for four signals (how often, how long, how many people, what the work
starts from); code reads those words into numbers, scores every candidate with the configured
weights, ranks them, and the agent states the top one with a one-line why. The expert decides.
What: the steering state (`read_steering`, `add_candidates`, `apply_signals`, `advance`), the
readers (`read_runs`, `read_hours`, `read_people`, `read_inputs`), `rank`, `recommendation`,
`next_signals` (the next quick question), `why_line` and `changed_ideas`.
Rules it protects: the model never ranks or scores (no model key is read as one); only the first
`max_candidates` candidates are steered; at most `max_questions` questions; the status never moves
back; an unknown part adds 0. Must not: read a clock, a file or the network, call a model, or write
the profile. Durations and frequencies are read with the shared grammar of `domain/value_parse.py`.
Spec 14 §3.15; AC-14.63 to AC-14.70, AC-14.79.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.core.config import SteeringConfig
from app.models.process_discovery_schemas import SteeringCandidate, SteeringState
from app.utils.prompt_safety import contains_injection_pattern

from ..domain.value_parse import NUMBER_WORDS, parse_duration, parse_frequency, periods_a_year
from ..profile.coercion import coerce_text
from ..profile.shapes import as_list, as_mapping
from .replies import mentions, normalise_reply

SIGNALS: tuple[str, ...] = ("runs", "time", "people", "inputs")
#: The steering questions in order (§3.15 item 3): each covers every steered candidate.
QUESTIONS: tuple[tuple[str, ...], ...] = (("runs", "time"), ("people",), ("inputs",))
STEER_PREFIX = "steer:"
RECOMMEND_ASK_LIMIT = 2
CANDIDATES_MAX = 5
TEXT_MAX = 200
INPUT_WORDS: dict[float, str] = {1.0: "digital", 0.5: "mixed", 0.0: "paper or verbal"}

# --- Reading the words (the grammar is `domain/value_parse.py`, spec 19 §3.1) ------------------------------

_PERIOD_TOTAL = re.compile(r"^(.+?)\s+(?:a|an|per|every|each|/)\s*([a-z-]+)$")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?(?:\s*(?:-|–|—|to)\s*\d+(?:[.,]\d+)?)?")
_PEOPLE_WORDS = {w: n for w, n in NUMBER_WORDS.items() if w not in ("a", "an", "once", "twice")}


def read_runs(text: str | None) -> float | None:
    """Runs a year from a periodic frequency ("every month" → 12); per-run or unreadable → `None`."""
    found = parse_frequency(text or "")
    return found.value if found is not None and found.kind == "periodic" else None


def read_hours(time: str | None, runs_per_year: float | None) -> float | None:
    """Hours a year: a per-run time × runs a year, or a period total ("6 hours a month" → 72)."""
    text = " ".join((time or "").casefold().split()).removesuffix(".")
    total = _PERIOD_TOTAL.match(text)
    if total is not None:
        hours, periods = parse_duration(total.group(1)), periods_a_year(total.group(2))
        if hours is not None and periods:
            return round(hours.hours * periods, 6)
    per_run = parse_duration(text)
    if per_run is None or runs_per_year is None:
        return None
    return round(per_run.hours * runs_per_year, 6)


def read_people(text: str | None, cfg: SteeringConfig) -> float | None:
    """The first number or number word (a range → midpoint); a solo phrase → 1; anything else `None`."""
    reply = normalise_reply(text)
    if any(mentions(reply, normalise_reply(p)) for p in cfg.solo_phrases):
        return 1.0
    found = _NUMBER.search((text or "").casefold())
    if found is not None:
        numbers = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", found.group(0))]
        return sum(numbers) / len(numbers)
    word = next((w for w in reply.split() if w in _PEOPLE_WORDS), None)
    return float(_PEOPLE_WORDS[word]) if word else None


def read_inputs(text: str | None, cfg: SteeringConfig) -> float | None:
    """1.0 for digital cues only, 0.5 for both kinds, 0.0 for paper or verbal cues only, `None` for no cue."""
    reply = normalise_reply(text)
    digital = any(mentions(reply, normalise_reply(c)) for c in cfg.input_cues.digital)
    paper = any(mentions(reply, normalise_reply(c)) for c in cfg.input_cues.paper_verbal)
    if digital and paper:
        return 0.5
    if digital:
        return 1.0
    if paper:
        return 0.0
    return None


# --- The state ---------------------------------------------------------------------------------------------


def read_steering(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """A clean copy of the stored steering state (spec 12 `SteeringState`)."""
    return SteeringState.model_validate(dict(raw or {})).model_dump(mode="json")


def add_candidates(state: Mapping[str, Any], ideas: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Append new candidates in mention order, at most 5, ids c1…c5; a name already heard (or inside one) is skipped."""
    out = read_steering(state)
    for idea in ideas:
        name = coerce_text(idea.get("name"))
        if name is None or len(out["candidates"]) >= CANDIDATES_MAX:
            continue
        if any(_matches(name, c["name"]) for c in out["candidates"]):
            continue
        words = coerce_text(idea.get("words")) or ""
        candidate = SteeringCandidate(id=f"c{len(out['candidates']) + 1}", name=name, words=words)
        out["candidates"].append(candidate.model_dump(mode="json"))
    return out


def _matches(said: str, name: str) -> bool:
    """Normalised equality, or either name as whole words inside the other ("cost review" ↔ "monthly cost review")."""
    a, b = normalise_reply(said), normalise_reply(name)
    return bool(a and b) and (a == b or mentions(a, b) or mentions(b, a))


def _match(said: str, candidates: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The one candidate `said` names; an exact name wins; two or more loose matches are no match."""
    exact = [c for c in candidates if normalise_reply(c["name"]) == normalise_reply(said)]
    loose = exact or [c for c in candidates if _matches(said, c["name"])]
    return loose[0] if len(loose) == 1 else None


def apply_signals(state: Mapping[str, Any], raw: Any, cfg: SteeringConfig) -> dict[str, Any]:
    """Keep EXTRACT's `candidate_signals` for matched steered candidates: screened, capped, later wins."""
    out = read_steering(state)
    steered = out["candidates"][: cfg.max_candidates]
    for entry in as_list(raw) or []:
        item = as_mapping(entry) or {}
        said = coerce_text(item.get("name"))
        texts = {s: coerce_text(item.get(s)) for s in SIGNALS}
        if said is None or any(contains_injection_pattern(t) for t in [said, *texts.values()] if t):
            continue
        target = _match(said, steered)
        if target is None:
            continue
        for signal, text in texts.items():
            if text is not None:
                target["signals"][signal] = text[:TEXT_MAX]
    return out


def _known(candidate: Mapping[str, Any]) -> int:
    return sum(candidate.get(k) is not None for k in ("hours_per_year", "people", "data_score"))


def rank(state: Mapping[str, Any], cfg: SteeringConfig) -> dict[str, Any]:
    """Read the numbers, score and rank the steered candidates (§3.15 item 6); later ones get none."""
    out = read_steering(state)
    w = cfg.weights
    steered = out["candidates"][: cfg.max_candidates]
    for candidate in out["candidates"]:
        for key in ("runs_per_year", "hours_per_year", "people", "data_score", "score", "rank"):
            candidate[key] = None
    for candidate in steered:
        signals = candidate["signals"]
        runs = read_runs(signals.get("runs"))
        hours = read_hours(signals.get("time"), runs)
        people = read_people(signals.get("people"), cfg)
        data = read_inputs(signals.get("inputs"), cfg)
        s_hours = min(1.0, hours / cfg.hours_full_score) if hours is not None else 0.0
        s_people = max(0.0, min(1.0, (people - 1) / (cfg.people_full_score - 1))) if people is not None else 0.0
        score = w.hours * s_hours + w.people * s_people + w.data * (data or 0.0)
        candidate.update(
            runs_per_year=runs, hours_per_year=hours, people=people, data_score=data, score=round(score, 6)
        )
    order = sorted(range(len(steered)), key=lambda i: (-steered[i]["score"], -_known(steered[i]), i))
    for position, index in enumerate(order, start=1):
        steered[index]["rank"] = position
    return out


def recommendation(state: Mapping[str, Any], cfg: SteeringConfig) -> dict[str, Any] | None:
    """The rank-1 candidate, if it has `min_known_signals` known and a score above 0."""
    top = next((c for c in read_steering(state)["candidates"] if c.get("rank") == 1), None)
    if top is None or _known(top) < cfg.min_known_signals or not (top.get("score") or 0) > 0:
        return None
    return top


def _missing(state: Mapping[str, Any], cfg: SteeringConfig, signals: Sequence[str]) -> tuple[str, ...]:
    steered = read_steering(state)["candidates"][: cfg.max_candidates]
    return tuple(s for s in signals if any(c["signals"].get(s) is None for c in steered))


def next_signals(state: Mapping[str, Any], cfg: SteeringConfig) -> tuple[str, ...]:
    """The signals of the next steering question (first question with a signal still missing), or ()."""
    st = read_steering(state)
    if st["status"] != "collecting" or st["questions"] >= cfg.max_questions:
        return ()
    return next((m for q in QUESTIONS if (m := _missing(st, cfg, q))), ())


def advance(
    state: Mapping[str, Any], *, phase: str, name_counts: bool, posture: str, cfg: SteeringConfig
) -> dict[str, Any]:
    """Move the status forward (off → collecting → ranked → chosen; never back) and re-rank (§3.15 items 2, 8)."""
    st = read_steering(state)
    status = st["status"]
    if status in ("collecting", "ranked") and name_counts:
        status = "chosen"
    if status == "off" and phase == "find" and not name_counts and len(st["candidates"]) >= 2 and posture != "direct":
        status = "collecting"
    if status == "collecting" and (
        posture == "direct" or st["questions"] >= cfg.max_questions or not next_signals({**st, "status": status}, cfg)
    ):
        status = "ranked"
    st = rank({**st, "status": status}, cfg) if status != "off" else st
    if status in ("collecting", "ranked"):
        top = recommendation(st, cfg)
        st["recommended_id"] = top["id"] if top else None
    return st


# --- Words for the guide and the ideas ----------------------------------------------------------------------


def _number(value: float) -> str:
    return f"{round(value):d}" if abs(value - round(value)) < 0.05 or value >= 10 else f"{value:.1f}"


def why_line(candidate: Mapping[str, Any]) -> str:
    """`<name>: about <H> hours a year, <P> people, <kind> inputs.`; unknown parts left out."""
    parts: list[str] = []
    hours, people, data = candidate.get("hours_per_year"), candidate.get("people"), candidate.get("data_score")
    if hours is not None:
        parts.append(f"about {_number(hours)} hours a year")
    if people is not None:
        parts.append(f"{_number(people)} {'person' if people == 1 else 'people'}")
    if data is not None:
        parts.append(f"{INPUT_WORDS.get(data, 'mixed')} inputs")
    return f"{candidate.get('name', '')}: {', '.join(parts) if parts else 'not enough detail yet'}."


def ranked(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The steered candidates in rank order."""
    return sorted((c for c in read_steering(state)["candidates"] if c.get("rank")), key=lambda c: c["rank"])


def _idea(candidate: Mapping[str, Any], recommended_id: str | None) -> dict[str, Any]:
    keys = ("name", "words", "signals", "hours_per_year", "people", "data_score", "score", "rank")
    return {**{k: candidate.get(k) for k in keys}, "recommended": candidate.get("id") == recommended_id}


def changed_ideas(before: Mapping[str, Any], after: Mapping[str, Any], chosen: str) -> list[dict[str, Any]]:
    """The candidates that are new or changed this turn, as ideas; the chosen process is not an idea."""
    old = {c["id"]: _idea(c, read_steering(before)["recommended_id"]) for c in read_steering(before)["candidates"]}
    st = read_steering(after)
    out: list[dict[str, Any]] = []
    for candidate in st["candidates"]:
        idea = _idea(candidate, st["recommended_id"])
        if candidate["name"].casefold() == chosen.casefold() or old.get(candidate["id"]) == idea:
            continue
        out.append(idea)
    return out
