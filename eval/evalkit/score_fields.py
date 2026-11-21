"""Report quality: every field of the hidden truth checked against what the product captured (spec 24 §3.7).

Why: report quality is the headline number of the evaluation, so it must be hard to flatter. The
denominator is every field of the hidden truth (P01-P16 plus every scored step leaf of
every true step, read from the registry): a value
the product never captured, or a whole step it missed, counts as wrong; nothing is left out. Code
decides everything it can (regions, clusters, counts, numbers read with the product's own parser,
names and aliases); the judge only reads free text, and only when code could not decide.
What: `normalise`, `align_steps` (true step to captured step by content: name, activities, data and
systems; a captured step may cover several true steps, amended 2026-11-20),
`score_fields` (one `FieldResult` per truth field, with method, result and reason) and the
"no invention" rule for fields the persona never discloses (a number there is an `invented_value`).
Must not: call the judge for a code row that matched, for a missing value, or for systems
(names are names); read anything but the profile it is given.
A merged step is scored against each true step it covers (extra list items allowed); a true step
covered by no captured step is wrong in every cell; the expert's own role is implied in step roles.
Spec 24 §3.7; AC-24.10 to AC-24.13, AC-24.44 to AC-24.47.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.services.process_discovery.domain.field_spec import PROFILE_SPECS, STEP_SPECS, FieldSpec
from app.services.process_discovery.domain.value_parse import parse_duration, parse_frequency, runs_per_year

from .persona import PROCESS_KEYS, STEP_LEAVES, Persona

SPECS: dict[str, FieldSpec] = {s.key: s for s in PROFILE_SPECS}
STEP_SPEC: dict[str, FieldSpec] = {s.key: s for s in STEP_SPECS}
CRITERIA_LEAF = "decision_criteria"  # S14, unscored in the product, scored here when the truth has it (§12 V2)
NAME_FIELDS = ("process.process_owner", "owner")
ROW_LISTS = {"roles": "role", "approvals": "approver_role"}
NONE_ROW_FIELDS = ("process.sensitive_data", "roles", "approvals", "exceptions")
DURATION_TOLERANCE, FREQUENCY_TOLERANCE = 0.25, 0.10


class JudgeLike(Protocol):
    async def same(self, label: str, rule: str, hidden: str, captured: str) -> Any: ...


class FieldResult(BaseModel):
    key: str
    id: str
    hidden: str
    captured: str
    method: str  # code | judge | missing | never
    correct: bool
    reason: str = ""
    judge_error: bool = False
    invented: bool = False


class FieldScores(BaseModel):
    results: list[FieldResult] = Field(default_factory=list)
    total: int = 0
    correct: int = 0
    code_correct: int = 0
    judged: int = 0
    judge_errors: int = 0
    invented_values: int = 0
    proposed_at_finish: int = 0

    @property
    def quality(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def code_quality(self) -> float:
        return self.code_correct / self.total if self.total else 0.0


# --- small readers ------------------------------------------------------------------------------


def normalise(text: Any) -> str:
    """Lower case, trimmed, single spaces, no end punctuation, no leading "the", no trailing plural "s"."""
    s = re.sub(r"\s+", " ", str(text or "").lower()).strip()
    s = s.rstrip(".,;:!?").strip()
    s = re.sub(r"^the ", "", s)
    if len(s) > 3 and s.endswith("s") and not s.endswith("ss"):
        s = s[:-1]
    return s


SELF_WORDS = frozenset({"i", "me", "myself", "you", "yourself"})
STOP_WORDS = frozenset({"the", "and", "for", "with", "from", "into", "out", "all", "per", "our", "their"})


def _words(text: Any) -> set[str]:
    """Normalised words of a step name, without short and stop words (for alignment)."""
    words = re.findall(r"[a-zA-Z0-9]+", str(text or "").lower())
    return {normalise(w) for w in words if len(w) > 2 and w not in STOP_WORDS}


def is_empty(value: Any) -> bool:
    if value is None or value is False:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, Mapping):
        return all(is_empty(v) for v in value.values())  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list):
        return all(is_empty(v) for v in value)  # pyright: ignore[reportUnknownVariableType]
    return False


def is_none_rows(value: Any) -> bool:
    return (
        isinstance(value, list) and bool(value) and all(isinstance(v, Mapping) and v.get("none") is True for v in value)
    )  # pyright: ignore[reportUnknownVariableType]


def as_text(value: Any) -> str:
    """A value as one readable line (for the judge and for score.json)."""
    if isinstance(value, Mapping):
        if value.get("none") is True:
            return "none"
        if value.get("none_identified"):
            return "none identified"
        if "count" in value or "period" in value or "raw" in value:
            words = f"{value.get('count') or ''} per {value.get('period')}" if value.get("period") else ""
            return str(value.get("raw") or words).strip()
        if "value" in value and "unit" in value:
            text = f"{value.get('value') or ''} {value.get('unit') or ''}".strip()
            return text or str(value.get("qualitative") or "")
        if "duration" in value or "frequency" in value:
            return f"{value.get('duration') or ''}, {value.get('frequency') or ''}".strip(", ")
        if "inputs" in value or "outputs" in value:
            return f"in: {as_text(value.get('inputs') or [])}; out: {as_text(value.get('outputs') or [])}"
        if "same" in value:
            return f"{value.get('same') or ''}; {value.get('differences') or ''}".strip("; ")
        if "code" in value:
            return str(value.get("code") or "")
        return " - ".join(str(v) for v in value.values() if v not in ("", None, False, []))  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list):
        return "; ".join(as_text(v) for v in value)  # pyright: ignore[reportUnknownVariableType]
    return "" if value is None else str(value)


def _alias_groups(persona: Persona) -> list[set[str]]:
    return [{normalise(k), *(normalise(a) for a in v)} for k, v in persona.truth.aliases.items()]


def names_match(a: Any, b: Any, groups: Sequence[set[str]]) -> bool:
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return False
    return na == nb or any(na in g and nb in g for g in groups)


def _has_number(value: Any) -> bool:
    """A digit, a count, or words the product's parser reads as a number."""
    if isinstance(value, Mapping) and isinstance(value.get("count"), int):
        return True
    text = as_text(value)
    if re.search(r"\d", text):
        return True
    return any(parse_duration(part) or parse_frequency(part) for part in re.split(r"[;,]", text) if part.strip())


def _within(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance * abs(b) + 1e-9


# --- step matching by content (A1, amended 2026-11-20) -----------------------------------------

MIN_STEP_MATCH = 0.25  # share of a true step's distinctive content a captured step must hold to cover it


def _canonical(name: Any, groups: Sequence[set[str]]) -> str:
    n = normalise(name)
    return next((min(g) for g in groups if n in g), n)


def step_tokens(step: Mapping[str, Any], groups: Sequence[set[str]] = ()) -> set[str]:
    """Content of a step: words of its name, activities and data in / out, plus its systems (aliases folded)."""
    raw = step.get("data")
    data: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}  # pyright: ignore[reportUnknownVariableType]
    texts = [
        step.get("name"),
        *(step.get("activities") or []),
        *(data.get("inputs") or []),
        *(data.get("outputs") or []),
    ]
    words = {w for t in texts for w in _words(t)}
    return words | {f"sys:{_canonical(s, groups)}" for s in step.get("systems") or [] if normalise(s)}


def _match_scores(
    truth_steps: Sequence[Mapping[str, Any]], captured_steps: Sequence[Mapping[str, Any]], groups: Sequence[set[str]]
) -> list[list[float]]:
    """score[i][j]: share of true step i's distinctive tokens (not in any other true step) found in captured step j."""
    truth = [step_tokens(s, groups) for s in truth_steps]
    captured = [step_tokens(s, groups) for s in captured_steps]
    scores: list[list[float]] = []
    for i, tokens in enumerate(truth):
        others = set().union(*(t for k, t in enumerate(truth) if k != i))
        own = (tokens - others) or tokens
        scores.append([len(own & c) / len(own) if own else 0.0 for c in captured])
    return scores


def align_steps(
    truth_steps: Sequence[Mapping[str, Any]],
    captured_steps: Sequence[Mapping[str, Any]],
    groups: Sequence[set[str]] = (),
) -> list[tuple[int, int | None]]:
    """(true step, captured step or None), matched by content (AC-24.10, AC-24.44, AC-24.45).

    1. One to one: the pairing with the highest total match (each pair at least `MIN_STEP_MATCH`);
       ties go to the pairing closest in position. 2. Equal counts: a true step left unpaired takes
       the captured step at its own position when that one is still free. 3. Merge: a true step still
       unpaired joins the captured step that covers it best (at least `MIN_STEP_MATCH`); several true
       steps may then share one captured step. Anything left is missing.
    """
    nt, nc = len(truth_steps), len(captured_steps)
    scores = _match_scores(truth_steps, captured_steps, groups)
    best: dict[tuple[int, int], tuple[tuple[float, int], tuple[int | None, ...]]] = {}

    def solve(i: int, used: int) -> tuple[tuple[float, int], tuple[int | None, ...]]:
        if i == nt:
            return (0.0, 0), ()
        if (i, used) in best:
            return best[(i, used)]
        (total, dist), rest = solve(i + 1, used)
        result = ((total, dist), (None, *rest))
        for j in range(nc):
            if used & (1 << j) or scores[i][j] < MIN_STEP_MATCH:
                continue
            (t, d), r = solve(i + 1, used | (1 << j))
            option = ((round(t + scores[i][j], 9), d - abs(i - j)), (j, *r))
            if option[0] > result[0]:
                result = option
        best[(i, used)] = result
        return result

    chosen = list(solve(0, 0)[1])
    if nt == nc:
        taken = {j for j in chosen if j is not None}
        chosen = [i if j is None and i not in taken else j for i, j in enumerate(chosen)]
    for i, j in enumerate(chosen):
        if j is None and nc:
            k = max(range(nc), key=lambda c: (scores[i][c], -abs(i - c)))
            chosen[i] = k if scores[i][k] >= MIN_STEP_MATCH else None
    return [(i + 1, None if j is None else j + 1) for i, j in enumerate(chosen)]


# --- scoring ------------------------------------------------------------------------------------


class _Scorer:
    def __init__(self, persona: Persona, judge: JudgeLike) -> None:
        self.persona = persona
        self.judge = judge
        self.groups = _alias_groups(persona)

    async def ask(self, spec: FieldSpec, hidden: str, captured: str) -> tuple[bool, str, bool]:
        verdict = await self.judge.same(spec.label, spec.rule, hidden, captured)
        return bool(verdict.same_meaning), str(verdict.reason), bool(getattr(verdict, "error", False))

    async def names(self, spec: FieldSpec, hidden: Any, captured: Any, *, judge: bool) -> tuple[bool, str, str]:
        """One name (owner): code match or alias, else the judge. Returns (ok, method, reason)."""
        if names_match(hidden, captured, self.groups):
            return True, "code", "same name or alias"
        if not judge:
            return False, "code", "different name"
        ok, reason, _ = await self.ask(spec, str(hidden), str(captured))
        return ok, "judge", reason

    async def name_list(
        self, spec: FieldSpec, hidden: list[str], captured: list[str], *, judge: bool, extras: bool = False
    ) -> tuple[bool, str, str]:
        """Every hidden item matched (alias, then judge one item at a time) and at most one extra (any with `extras`)."""
        left = list(captured)
        method = "code"
        for item in hidden:
            hit = next((c for c in left if names_match(item, c, self.groups)), None)
            if hit is None and judge:
                for c in left:
                    method = "judge"
                    ok, _, _ = await self.ask(spec, item, c)
                    if ok:
                        hit = c
                        break
            if hit is None:
                return False, method, f"{item!r} not captured"
            left.remove(hit)
        if len(left) > 1 and not extras:
            return False, method, f"{len(left)} extra items"
        return True, method, "every item matched"

    def is_own_role(self, role: Any) -> bool:
        """The expert's own role (P02, its aliases, "I", "me"): implied in a step's roles (AC-24.47)."""
        own = self.persona.truth.fields.get("user_function")
        return normalise(role) in SELF_WORDS or names_match(role, own, self.groups)

    async def field(
        self, key: str, spec: FieldSpec, hidden: Any, captured: Any, *, merged: bool = False
    ) -> FieldResult:
        h, c = as_text(hidden), as_text(captured)
        base: dict[str, Any] = {"key": key, "id": spec.id, "hidden": h, "captured": c}
        if self.persona.disclose(key) == "never":
            invented = not is_empty(captured) and _has_number(captured)
            reason = "a number was invented" if invented else "honest: no number"
            return FieldResult(**base, method="never", correct=not invented, invented=invented, reason=reason)
        if is_empty(captured):
            return FieldResult(**base, method="missing", correct=False, reason="not captured")
        ok, method, reason, error = await self._compare(spec, hidden, captured, h, c, merged)
        return FieldResult(**base, method=method, correct=ok, reason=reason[:200], judge_error=error)

    async def _compare(
        self, spec: FieldSpec, hidden: Any, captured: Any, h: str, c: str, merged: bool = False
    ) -> tuple[bool, str, str, bool]:
        leaf = spec.key.rsplit(".", 1)[-1] if spec.is_process else spec.key
        if leaf == "roles" and not spec.is_process:
            hv = [
                str(r.get("role", "")) for r in hidden if isinstance(r, Mapping) and not self.is_own_role(r.get("role"))
            ]
            cv = [str(r.get("role", "")) for r in captured if isinstance(r, Mapping) and not r.get("none")]
            cv = [r for r in cv if r.strip() and not self.is_own_role(r)]
            ok, method, reason = await self.name_list(spec, [r for r in hv if r.strip()], cv, judge=True, extras=merged)
            return ok, method, reason, False
        if spec.key in NONE_ROW_FIELDS and (is_none_rows(hidden) or is_none_rows(captured)):
            ok = is_none_rows(hidden) == is_none_rows(captured)
            return ok, "code", "none row" if ok else "none row on one side only", False
        if spec.key == "region":
            return normalise(h) == normalise(c), "code", "region", False
        if spec.key == "process.cluster":
            code = captured.get("code") if isinstance(captured, Mapping) else captured
            return str(code) == str(hidden), "code", f"cluster {code}", False
        if spec.key == "process.substep_count":
            return int(captured) == int(hidden), "code", f"{captured} steps", False
        if spec.key == "process.volume":
            a, b = runs_per_year(captured), runs_per_year(hidden)
            if a is None or b is None:
                return False, "code", "volume not readable", False
            return _within(a, b, FREQUENCY_TOLERANCE), "code", f"{a:g} vs {b:g} runs a year", False
        if spec.key in ("process.baseline_metric", "process.target_metric"):
            a, b = parse_duration(c), parse_duration(h)
            if a is not None and b is not None:
                return _within(a.hours, b.hours, DURATION_TOLERANCE), "code", f"{a.hours:g} h vs {b.hours:g} h", False
        if leaf == "effort" and not spec.is_process:
            result = self._effort(hidden, captured)
            if result is not None:
                return result[0], "code", result[1], False
        if spec.key == "process.variation" and isinstance(hidden, Mapping) and isinstance(captured, Mapping):
            if normalise(hidden.get("same")) != normalise(captured.get("same")):
                return False, "code", "same-way answer differs", False
            if not hidden.get("differences"):
                return True, "code", "same-way answer equal", False
            ok, reason, error = await self.ask(spec, str(hidden["differences"]), str(captured.get("differences") or ""))
            return ok, "judge", reason, error
        if leaf == "decision_criteria" and not spec.is_process and isinstance(hidden, Mapping):
            return await self._criteria(spec, hidden, captured if isinstance(captured, Mapping) else {})
        if leaf == "decision_type" and not spec.is_process:
            hk = hidden.get("kind") if isinstance(hidden, Mapping) else hidden
            ck = captured.get("kind") if isinstance(captured, Mapping) else captured
            return normalise(hk) == normalise(ck), "code", f"kind {ck} vs {hk}", False
        if spec.key in NAME_FIELDS:
            hv = hidden.get("role") if isinstance(hidden, Mapping) else hidden
            cv = captured.get("role") if isinstance(captured, Mapping) else captured
            ok, method, reason = await self.names(spec, hv, cv, judge=True)
            return ok, method, reason, False
        if leaf == "systems" and not spec.is_process:
            ok, method, reason = await self.name_list(spec, list(hidden), list(captured), judge=False, extras=merged)
            return ok, method, reason, False
        if leaf in ROW_LISTS and not spec.is_process:
            sub = ROW_LISTS[leaf]
            hv = [str(r.get(sub, "")) for r in hidden if isinstance(r, Mapping)]
            cv = [str(r.get(sub, "")) for r in captured if isinstance(r, Mapping) and not r.get("none")]
            ok, method, reason = await self.name_list(spec, hv, cv, judge=True, extras=merged)
            return ok, method, reason, False
        if normalise(h) == normalise(c):
            return True, "code", "same words", False
        ok, reason, error = await self.ask(spec, h, c)
        return ok, "judge", reason, error

    async def _criteria(
        self, spec: FieldSpec, hidden: Mapping[str, Any], captured: Mapping[str, Any]
    ) -> tuple[bool, str, str, bool]:
        """S14 (§12 V2): `written` exact and `set_by` by name (code, when captured), `basis` and `varies` by the judge."""
        hw, cw = normalise(hidden.get("written")), normalise(captured.get("written"))
        if hw and hw != cw:
            return False, "code", f"written {cw or '-'} vs {hw}", False
        if hidden.get("set_by") and captured.get("set_by"):
            if not names_match(hidden["set_by"], captured["set_by"], self.groups):
                return False, "code", "set by a different role", False
        ok, reason, error = await self.ask(spec, str(hidden.get("basis") or ""), str(captured.get("basis") or ""))
        if ok and hidden.get("varies") and captured.get("varies"):
            ok, reason, error = await self.ask(spec, str(hidden["varies"]), str(captured["varies"]))
        return ok, "judge", reason, error

    @staticmethod
    def _effort(hidden: Any, captured: Any) -> tuple[bool, str] | None:
        """Both duration and frequency parse on both sides: decided by code; else None (judge)."""
        if not isinstance(hidden, Mapping) or not isinstance(captured, Mapping):
            return None
        hd, cd = parse_duration(str(hidden.get("duration") or "")), parse_duration(str(captured.get("duration") or ""))
        hf, cf = (
            parse_frequency(str(hidden.get("frequency") or "")),
            parse_frequency(str(captured.get("frequency") or "")),
        )
        if hd is None or cd is None or hf is None or cf is None:
            return None
        if not _within(cd.hours, hd.hours, DURATION_TOLERANCE):
            return False, f"{cd.hours:g} h vs {hd.hours:g} h"
        if hf.kind != cf.kind or not _within(cf.value, hf.value, FREQUENCY_TOLERANCE):
            return False, "different frequency"
        return True, "duration and frequency within tolerance"


def _captured(profile: Mapping[str, Any], key: str) -> Any:
    if key.startswith("process."):
        return (profile.get("process") or {}).get(key.split(".", 1)[1])
    return profile.get(key)


async def score_fields(
    persona: Persona,
    profile: Mapping[str, Any],
    judge: JudgeLike,
    field_views: Sequence[Mapping[str, Any]] = (),
) -> FieldScores:
    """Score every truth field against `profile` (a `SessionOut.profile`). Judge only for judge rows (AC-24.12)."""
    scorer = _Scorer(persona, judge)
    results: list[FieldResult] = []
    for key in PROCESS_KEYS:
        results.append(await scorer.field(key, SPECS[key], persona.truth.fields[key], _captured(profile, key)))
    captured_steps: list[Mapping[str, Any]] = list((profile.get("process") or {}).get("substeps") or [])
    pairs = align_steps(persona.truth.steps, captured_steps, scorer.groups)
    shared = [c for _, c in pairs]
    for true_n, cap_n in pairs:
        step = persona.truth.steps[true_n - 1]
        for leaf in STEP_LEAVES:
            key = f"process.substeps[{true_n}].{leaf}"
            if cap_n is None:  # a missing step: every cell wrong, no honesty credit (AC-24.46)
                results.append(FieldResult(key=key, id=STEP_SPEC[leaf].id, hidden=as_text(step[leaf]), captured="",
                                           method="missing", correct=False, reason="step not captured"))  # fmt: skip
                continue
            cap = captured_steps[cap_n - 1]
            merged = shared.count(cap_n) > 1
            results.append(await scorer.field(key, STEP_SPEC[leaf], step[leaf], cap.get(leaf), merged=merged))
        if CRITERIA_LEAF in step:  # §12 V2: scored only when the truth has it (a judgement or mix step)
            key, spec = f"process.substeps[{true_n}].{CRITERIA_LEAF}", STEP_SPEC[CRITERIA_LEAF]
            if cap_n is None:
                results.append(FieldResult(key=key, id=spec.id, hidden=as_text(step[CRITERIA_LEAF]), captured="",
                                           method="missing", correct=False, reason="step not captured"))  # fmt: skip
            else:
                captured_value = captured_steps[cap_n - 1].get(CRITERIA_LEAF)
                results.append(await scorer.field(key, spec, step[CRITERIA_LEAF], captured_value))
    correct = sum(1 for r in results if r.correct)
    return FieldScores(
        results=results,
        total=persona.truth_field_count,
        correct=correct,
        code_correct=sum(1 for r in results if r.correct and r.method in ("code", "never")),
        judged=sum(1 for r in results if r.method == "judge"),
        judge_errors=sum(1 for r in results if r.judge_error),
        invented_values=sum(1 for r in results if r.invented),
        proposed_at_finish=sum(1 for v in field_views if v.get("status") == "proposed"),
    )
