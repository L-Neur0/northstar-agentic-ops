"""How the interview behaved: loops, repeats, times, documents, stale values, tokens and cost (spec 24 §3.9, §3.10).

Why: a report can be right and the interview still be bad: a question asked six times, the same
message three times in a row, a 40-second turn, a stale document value kept. Product §8 sets
targets for these, and they are all countable from what the runner recorded, so code counts them.
What: `score_behaviour` returns `BehaviourScores` from a `PersonaRun`: loops (asks over the limits
in any snapshot, or three equal agent messages in a row), repeated questions, median and max turn
time over uncached turns only, *Finish* time, fallback questions, document proposals, conflicts,
stale values kept at *Finish*, and tokens and euros split into app, expert and judge from the
captured `llm_call` lines (cache hits cost nothing and are counted apart).
Must not: count a cached turn's time, invent a price for a deployment missing from `prices.yaml`
(tokens only, € `None`), or read anything the runner did not record.
Spec 24 §3.9, §3.10; AC-24.20, AC-24.21, AC-24.22.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from .persona import Persona
from .play import PersonaRun
from .score_fields import as_text, normalise

PROCESS_ASK_LIMIT, CELL_ASK_LIMIT, SAME_IN_A_ROW = 5, 3, 3

Prices = Mapping[str, Mapping[str, float]]


def load_prices(path: Path) -> dict[str, dict[str, float]]:
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): {"in": float(v["in"]), "out": float(v["out"])} for k, v in (data.get("deployments") or {}).items()}


class Tokens(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0
    cache_hits: int = 0
    euros: float | None = 0.0
    deployments: list[str] = Field(default_factory=list)


class BehaviourScores(BaseModel):
    loops: int = 0
    loop_keys: list[str] = Field(default_factory=list)
    repeats: int = 0
    turn_median_s: float | None = None
    turn_max_s: float | None = None
    finish_s: float | None = None
    fallbacks: int = 0
    proposals_confirmed: int = 0
    proposals_rejected: int = 0
    conflicts: int = 0
    stale_kept: int = 0
    app: Tokens = Field(default_factory=Tokens)
    expert: Tokens = Field(default_factory=Tokens)
    judge: Tokens = Field(default_factory=Tokens)


def count_loops(snapshots: Sequence[Any], agent_messages: Sequence[str]) -> tuple[int, list[str]]:
    """Fields over their ask limit in any snapshot, plus runs of three equal agent messages (AC-24.20)."""
    worst: dict[str, int] = {}
    for snap in snapshots:
        views = snap.fieldViews if hasattr(snap, "fieldViews") else snap.get("fieldViews", [])
        for view in views:
            key = str(view.get("key"))
            worst[key] = max(worst.get(key, 0), int(view.get("asks") or 0))
    keys = [k for k, asks in worst.items() if asks > (CELL_ASK_LIMIT if "substeps[" in k else PROCESS_ASK_LIMIT)]
    runs, streak = 0, 1
    normalised = [normalise(m) for m in agent_messages]
    for previous, current in zip(normalised, normalised[1:], strict=False):
        streak = streak + 1 if current == previous else 1
        if streak == SAME_IN_A_ROW:
            runs += 1
            keys.append(f"same message x{SAME_IN_A_ROW}")
    return len(keys), keys


def count_repeats(agent_messages: Sequence[str]) -> int:
    seen: set[str] = set()
    repeats = 0
    for message in agent_messages:
        n = normalise(message)
        repeats += n in seen
        seen.add(n)
    return repeats


def value_at(profile: Mapping[str, Any], key: str) -> Any:
    """`process.substeps[3].systems` and friends, read from a `SessionOut.profile`."""
    value: Any = profile
    for part in key.split("."):
        match = re.fullmatch(r"([a-z_]+)\[(\d+)\]", part)
        name, index = (match.group(1), int(match.group(2))) if match else (part, None)
        value = value.get(name) if isinstance(value, Mapping) else None
        if index is not None:
            value = value[index - 1] if isinstance(value, list) and len(value) >= index else None
    return value


def count_stale(persona: Persona, profile: Mapping[str, Any]) -> int:
    """A document's out-of-date value still captured at *Finish* (normalised, contained either way)."""
    kept = 0
    for doc in persona.documents:
        for stale in doc.stale:
            captured = normalise(as_text(value_at(profile, stale.key)))
            old = normalise(stale.doc_value)
            kept += bool(captured and old and (old == captured or old in captured))
    return kept


def tokens(logs: Sequence[Mapping[str, Any]], prices: Prices, kinds: set[str] | None, exclude: set[str]) -> Tokens:
    out = Tokens()
    deployments: set[str] = set()
    priced = True
    euros = 0.0
    for line in logs:
        if line.get("event") != "llm_call":
            continue
        kind = str(line.get("call_type"))
        if (kinds is not None and kind not in kinds) or kind in exclude:
            continue
        out.calls += 1
        if line.get("outcome") == "cache_hit":
            out.cache_hits += 1
            continue
        t_in, t_out = int(line.get("prompt_tokens") or 0), int(line.get("completion_tokens") or 0)
        out.tokens_in += t_in
        out.tokens_out += t_out
        deployment = str(line.get("deployment"))
        deployments.add(deployment)
        price = prices.get(deployment)
        if price is None:
            priced = False
        else:
            euros += (t_in * price["in"] + t_out * price["out"]) / 1_000_000
    out.deployments = sorted(deployments)
    out.euros = round(euros, 4) if priced else None
    return out


def score_behaviour(persona: Persona, run: PersonaRun, prices: Prices) -> BehaviourScores:
    agent = [str(m.get("text", "")) for m in run.transcript if m.get("role") == "agent"]
    loops, loop_keys = count_loops(run.snapshots, agent)
    timed = [t["wall_ms"] / 1000 for t in run.turns if t.get("event") == "message" and t.get("uncached")]
    profile = run.session.get("profile") or {}
    return BehaviourScores(
        loops=loops,
        loop_keys=loop_keys,
        repeats=count_repeats(agent),
        turn_median_s=round(statistics.median(timed), 2) if timed else None,
        turn_max_s=round(max(timed), 2) if timed else None,
        finish_s=round(run.finish_seconds, 2) if run.finish_seconds is not None and not run.finish_cached else None,
        fallbacks=sum(1 for t in run.turns if t.get("fallback_used")),
        proposals_confirmed=sum(int(t.get("proposals_confirmed") or 0) for t in run.turns),
        proposals_rejected=sum(int(t.get("proposals_rejected") or 0) for t in run.turns),
        conflicts=sum(int((u.get("report") or {}).get("conflicts") or 0) for u in run.uploads),
        stale_kept=count_stale(persona, profile),
        app=tokens(run.logs, prices, None, {"EXPERT", "JUDGE"}),
        expert=tokens(run.logs, prices, {"EXPERT"}, set()),
        judge=tokens(run.logs, prices, {"JUDGE"}, set()),
    )
