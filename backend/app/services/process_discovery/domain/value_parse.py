"""Reads the expert's durations and frequencies with one small, fixed grammar (spec 19 §3.1).

Why: hours a year are made by code, never guessed (product rule 3). The expert answers in words
("1 day", "10 times a month", "each time"), so code needs one reader that turns those words into
numbers the same way every time, and says "unreadable" for anything outside the grammar ("a
while", "when needed", "up to 6 hours") instead of guessing. It lives in `domain/` so the
assessment (spec 19) and the interview's steering (spec 14 §3.15) read words the same way.
What: `parse_duration` (hours per run), `parse_frequency` (per run or periodic, with runs a year),
`periods_a_year` (one period word) and `runs_per_year` (the process volume, P10), plus the
working-year constants they use (an assumption, shown in every report).
Must not: do I/O, read a clock, call a model, or accept a form the grammar does not list.
Spec 19 §3.1, §4.1; AC-19.1 to AC-19.5, AC-19.42.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

HOURS_PER_DAY = 8
HOURS_PER_WEEK = 40
WORKING_YEAR: dict[str, float] = {
    "day": 250,
    "working day": 250,
    "business day": 250,
    "week": 50,
    "fortnight": 25,
    "month": 12,
    "month end": 12,
    "month-end": 12,
    "quarter": 4,
    "half year": 2,
    "half-year": 2,
    "year": 1,
    "annum": 1,
}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
ADVERBS: dict[str, float] = {
    "daily": 250,
    "weekly": 50,
    "fortnightly": 25,
    "biweekly": 25,
    "monthly": 12,
    "quarterly": 4,
    "half-yearly": 2,
    "yearly": 1,
    "annually": 1,
}
UNIT_HOURS: dict[str, float] = {
    "minute": 1 / 60,
    "minutes": 1 / 60,
    "min": 1 / 60,
    "mins": 1 / 60,
    "hour": 1,
    "hours": 1,
    "h": 1,
    "hr": 1,
    "hrs": 1,
    "day": HOURS_PER_DAY,
    "days": HOURS_PER_DAY,
    "working day": HOURS_PER_DAY,
    "working days": HOURS_PER_DAY,
    "business day": HOURS_PER_DAY,
    "business days": HOURS_PER_DAY,
    "week": HOURS_PER_WEEK,
    "weeks": HOURS_PER_WEEK,
    "working week": HOURS_PER_WEEK,
    "working weeks": HOURS_PER_WEEK,
}
NUMBER_WORDS: dict[str, float] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "a": 1, "an": 1, "once": 1, "twice": 2,
}  # fmt: skip

FILLERS = ("approximately", "around", "roughly", "usually", "typically", "at least", "approx.", "approx",
           "about", "circa", "ca.", "ca", "~")  # fmt: skip
PER_RUN_TAILS = ("each time", "every time", "per run", "each run", "every run", "each cycle", "every cycle")
DURATION_TAILS = ("each time", "every time", "per run", "per cycle", "each")
PER_RUN_EXACT = frozenset({*PER_RUN_TAILS, "once", "once per run", "same as the process"})


@dataclass(frozen=True)
class Duration:
    """Hours of one run, the words they were read from, and whether a range midpoint was used."""

    hours: float
    text: str
    midpoint: bool


@dataclass(frozen=True)
class Frequency:
    """`per_run`: `value` is the multiplier of the process runs; `periodic`: `value` is runs a year."""

    kind: Literal["per_run", "periodic"]
    value: float
    text: str
    midpoint: bool


# --- Step 1: clean --------------------------------------------------------------------------------

_NUM = r"\d+(?:[.,]\d+)?"
_RANGE_TO = re.compile(rf"({_NUM})\s*(?:–|—|-|\s+to\s+)\s*({_NUM})")


def _clean(text: str) -> str:
    s = re.sub(r"\s+", " ", text.casefold().replace("–", "-").replace("—", "-")).strip()
    s = _RANGE_TO.sub(r"\1-\2", s)
    for filler in FILLERS:
        if s == filler:
            return ""
        if s.startswith(filler) and (filler == "~" or s[len(filler)] == " " or filler.endswith(".")):
            s = s[len(filler) :].strip()
            break
    return s.removesuffix(".").strip()


# --- Step 2: quantities ---------------------------------------------------------------------------

_WORDS = "|".join(sorted(NUMBER_WORDS, key=len, reverse=True))
_QTY = re.compile(rf"^(?:between ({_NUM}) and ({_NUM})|({_NUM})-({_NUM})|(half an?)\b|({_NUM})|({_WORDS})\b)\s*")


def _number(token: str) -> float:
    return float(token.replace(",", ".")) if token[0].isdigit() else NUMBER_WORDS[token]


def _take_qty(s: str) -> tuple[float, bool, str] | None:
    """(quantity, midpoint used, rest) for a quantity at the start of `s`."""
    m = _QTY.match(s)
    if m is None:
        return None
    lo, hi = m.group(1) or m.group(3), m.group(2) or m.group(4)
    if lo and hi:
        value, midpoint = (_number(lo) + _number(hi)) / 2, True
    elif m.group(5):
        value, midpoint = 0.5, False
    else:
        value, midpoint = _number(m.group(6) or m.group(7)), False
    return value, midpoint, s[m.end() :]


# --- Step 3: durations ----------------------------------------------------------------------------

_UNITS = "|".join(re.escape(u) for u in sorted(UNIT_HOURS, key=len, reverse=True))
_UNIT = re.compile(rf"^({_UNITS})(?![a-z])\s*")


def _take_part(s: str) -> tuple[float, bool, str, float] | None:
    """One `QTY UNIT`: (hours, midpoint, rest, unit hours)."""
    qty = _take_qty(s)
    if qty is None:
        return None
    value, midpoint, rest = qty
    unit = _UNIT.match(rest)
    if unit is None:
        return None
    per = UNIT_HOURS[unit.group(1)]
    return value * per, midpoint, rest[unit.end() :], per


def parse_duration(text: str) -> Duration | None:
    """Hours per run, or `None` when the words are outside the grammar."""
    s = _clean(text)
    first = _take_part(s)
    if first is None:
        return None
    hours, midpoint, rest, per = first
    second = _take_part(rest.removeprefix("and ").strip()) if rest else None
    if second is not None:
        hours, midpoint, rest = hours + second[0], midpoint or second[1], second[2]
    elif per == 1 and (bare := re.match(r"^(\d{1,2})\b\s*", rest)):
        hours, rest = hours + int(bare.group(1)) / 60, rest[bare.end() :]  # "1h30"
    rest = rest.strip()
    if rest and rest not in DURATION_TAILS and not _per_unit_tail(rest):
        return None
    return Duration(hours=hours, text=text.strip(), midpoint=midpoint)


# --- Per-run tails with a unit of work (§3.8) -------------------------------------------------------

_UNIT_OF_WORK_TAIL = re.compile(r"^(?:per|each|for each|for every)\s+([a-z][a-z'-]*(?:\s+[a-z][a-z'-]*){0,2})$")


def _is_unit_of_work(words: str) -> bool:
    """1-3 words whose first word is not a period word nor run / time / cycle ("role", "new starter")."""
    first = words.split()[0]
    return first not in _NOT_A_UNIT_OF_WORK and first.removesuffix("s") not in _NOT_A_UNIT_OF_WORK


def _per_unit_tail(rest: str) -> bool:
    """`per N`, `each N`, `for each N`, `for every N` with N a unit of work: one run of the process."""
    m = _UNIT_OF_WORK_TAIL.match(rest.strip())
    return m is not None and _is_unit_of_work(m.group(1))


# --- Step 4: frequencies --------------------------------------------------------------------------

_PERIOD_WORDS = sorted({*WORKING_YEAR, *(f"{p}s" for p in WORKING_YEAR), *WEEKDAYS}, key=len, reverse=True)
_PERIOD = "|".join(re.escape(p) for p in _PERIOD_WORDS)
_NOT_A_UNIT_OF_WORK = frozenset(
    {*_PERIOD_WORDS, "run", "time", "cycle", "working", "business", "half", "weekday", "weekend", "shift"}
)


def periods_a_year(word: str) -> float | None:
    """Periods a working year for one period word ("month", "a month", "every month", "monthly")."""
    s = _clean(word)
    s = re.sub(r"^(?:a|an|per|every|each|/)\s*", "", s).strip()
    if s in ADVERBS:
        return ADVERBS[s]
    if s in WEEKDAYS:
        return WORKING_YEAR["week"]
    return WORKING_YEAR.get(s) or WORKING_YEAR.get(s.removesuffix("s")) if s else None


def parse_frequency(text: str) -> Frequency | None:
    """Per run (× the process runs) or periodic (runs a year), or `None` outside the grammar.

    A text that does not parse whole is read part by part (split on "," and ";"): the first per-run
    part wins, else the first part that parses (§3.8 F3).
    """
    given = text.strip()
    whole = _parse_frequency_part(_clean(text), given)
    if whole is not None or not re.search(r"[,;]", text):
        return whole
    parts = [f for f in (_parse_frequency_part(_clean(p), given) for p in re.split(r"[,;]", text)) if f is not None]
    return next((f for f in parts if f.kind == "per_run"), parts[0] if parts else None)


def _parse_frequency_part(s: str, given: str) -> Frequency | None:
    """One part of a frequency answer, already cleaned."""
    if s.startswith("every time "):
        return Frequency("per_run", 1, given, False)  # "every time we hire" (§3.8 F1)
    once = re.match(r"^(?:once )?(.+)$", s)
    if once is not None and _per_unit_tail(once.group(1)):
        return Frequency("per_run", 1, given, False)  # "once per role", "for every request"
    if s in PER_RUN_EXACT:
        return Frequency("per_run", 1, given, False)
    if s in ADVERBS:
        return Frequency("periodic", ADVERBS[s], given, False)
    if s in ("month end", "month-end", "every month end", "every month-end"):
        return Frequency("periodic", 12, given, False)
    every = re.match(rf"^every (?:({_NUM}|{_WORDS}) )?({_PERIOD})$", s)
    if every is not None:
        periods = periods_a_year(every.group(2))
        count = _number(every.group(1)) if every.group(1) else 1
        return Frequency("periodic", periods / count, given, False) if periods and count else None
    qty = _take_qty(s)
    if qty is None:
        return None
    value, midpoint, rest = qty
    rest = re.sub(r"^times?\b\s*", "", rest).strip()
    if rest in PER_RUN_TAILS or _per_unit_tail(rest):
        return Frequency("per_run", value, given, midpoint)
    periodic = re.match(rf"^(?:a|an|per|every|each|/)\s*({_PERIOD})$", rest)
    if periodic is None:
        return None
    periods = periods_a_year(periodic.group(1))
    return Frequency("periodic", value * periods, given, midpoint) if periods else None


def runs_per_year(volume: Mapping[str, Any] | None, meta: Mapping[str, Any] | None = None) -> float | None:
    """Process runs a year from P10: `count` × the period, else `raw` read as a periodic frequency.

    `meta` is the field's `__meta` entry; a volume that is only proposed (not confirmed) is not used.
    """
    if not isinstance(volume, Mapping) or (meta is not None and meta.get("status") == "proposed"):
        return None
    count, period, raw = volume.get("count"), volume.get("period"), volume.get("raw")
    if isinstance(count, int | float) and not isinstance(count, bool) and isinstance(period, str) and period.strip():
        periods = periods_a_year(period)
        if periods is not None:
            return count * periods
    if isinstance(raw, str) and raw.strip():
        frequency = parse_frequency(raw)
        if frequency is not None and frequency.kind == "periodic":
            return frequency.value
    return None
