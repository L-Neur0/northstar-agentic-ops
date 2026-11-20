"""The quote check: is this the expert's own words, copied from one stored value? (spec 18 §3.3).

Why: product rule 6, "no quote, no claim". Every AI opportunity, stay-human step, label (spec 19) and
step rating (spec 26) must carry words the expert really said (or a document really says), and only
code can check that. A paraphrase, a quote stitched from two answers or an invented sentence must
not pass, while case, curly quotes, dash style and a trailing full stop must not make a real quote fail.
What: `profile_values` lists every text in the profile with its address and source, in a fixed
order; `normalise_quote` folds both sides the same way; `find_evidence` accepts a quote that is a
substring of one value with at least three words, or a whole value, and returns where it was found;
`restrict_to_step` and `restrict_to_step_or_process` narrow the search for per-step calls.
Must not: search across two values, accept "..." or "…", read the conversation or uploaded files,
or mutate the profile. Pure: no I/O, no clock.
Spec 18 §3.3, §4.1; AC-18.8, AC-18.9.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from app.utils.prompt_safety import normalize_for_matching

from ..domain.field_spec import SOURCE_DOCUMENT, SOURCE_EXPERT, SOURCE_SPECIALIST, step_cell_key
from ..profile.shapes import as_list, as_mapping, meta_for, normalized_profile, process_of, rows_of

Source = Literal["expert", "document", "specialist"]
Value = tuple[str, str, str]  # (key, text, source)

MAX_QUOTE_CHARS = 400
MIN_QUOTE_WORDS = 3

_PROCESS_TEXTS = ("name", "trigger", "end_result", "value_at_end", "business_pain")  # P04, P06–P09
_PROCESS_OBJECTS = ("volume", "process_owner", "baseline_metric", "target_metric", "variation")  # P10–P14
_OBJECT_TEXT_KEYS = ("raw", "period", "role", "value", "unit", "qualitative", "same", "differences")
_STEP_TEXTS = ("name", "goal", "owner", "handover")
_STEP_LISTS = ("activities", "systems", "pain_points")
_STEP_ROWS = (
    ("roles", ("role", "contribution")),
    ("approvals", ("approver_role", "waiting_time")),
    ("exceptions", ("description",)),
)

_FOLD = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "″": '"',
        "«": '"',
        "»": '"',
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "′": "'",
        "–": "-",
        "—": "-",
        "‒": "-",
        "―": "-",
        "−": "-",
    }
)
_QUOTE_EDGES = " \t\r\n\"'`.,;:!?"
_STITCH = re.compile(r"\.\.\.|…")


@dataclass(frozen=True)
class EvidenceHit:
    """Where a quote was found: the field or step-cell address, who wrote it, and the quote as given."""

    key: str
    source: Source
    quote: str


def _source(profile: Mapping[str, Any], key: str) -> str:
    meta = meta_for(profile, key)
    source = meta.get("source") if meta is not None else None
    return source if source in (SOURCE_EXPERT, SOURCE_DOCUMENT, SOURCE_SPECIALIST) else SOURCE_EXPERT


def _texts(value: Any) -> list[str]:
    return [v for v in (as_list(value) or []) if isinstance(v, str) and v.strip()]


def profile_values(profile: Mapping[str, Any]) -> list[Value]:
    """Every text in the profile, one value per entry, in the order of the §3.3 table."""
    p = normalized_profile(profile)
    proc = process_of(p)
    out: list[Value] = []

    def add(key: str, texts: Sequence[str]) -> None:
        source = _source(p, key)
        out.extend((key, t, source) for t in texts if t.strip())

    for leaf in _PROCESS_TEXTS:
        value = proc.get(leaf)
        add(f"process.{leaf}", [value] if isinstance(value, str) else [])
    for leaf in _PROCESS_OBJECTS:
        obj = as_mapping(proc.get(leaf)) or {}
        add(f"process.{leaf}", [v for k in _OBJECT_TEXT_KEYS if isinstance(v := obj.get(k), str)])
    rows = [as_mapping(r) or {} for r in as_list(proc.get("sensitive_data")) or []]
    add("process.sensitive_data", [v for r in rows for k in ("item", "detail") if isinstance(v := r.get(k), str)])

    for index, step in enumerate(rows_of(p), start=1):
        for leaf in _STEP_TEXTS:
            value = step.get(leaf)
            add(step_cell_key(index, leaf), [value] if isinstance(value, str) else [])
        for leaf in _STEP_LISTS:
            add(step_cell_key(index, leaf), _texts(step.get(leaf)))
        data = as_mapping(step.get("data")) or {}
        add(step_cell_key(index, "data"), _texts(data.get("inputs")) + _texts(data.get("outputs")))
        effort = as_mapping(step.get("effort")) or {}
        add(
            step_cell_key(index, "effort"),
            [v for k in ("duration", "frequency") if isinstance(v := effort.get(k), str)],
        )
        for leaf, keys in _STEP_ROWS:
            entries = [as_mapping(r) or {} for r in as_list(step.get(leaf)) or []]
            add(step_cell_key(index, leaf), [v for r in entries for k in keys if isinstance(v := r.get(k), str)])
    return out


def normalise_quote(text: str) -> str:
    """Both sides of the match: `normalize_for_matching`, then curly quotes and dashes folded."""
    return normalize_for_matching(text).translate(_FOLD)


def _strip_edges(text: str) -> str:
    return text.translate(_FOLD).strip(_QUOTE_EDGES)


def find_evidence(quote: Any, values: Sequence[Value]) -> EvidenceHit | None:
    """The first value (in `values` order) that `quote` is copied from, or `None`."""
    if not isinstance(quote, str):
        return None
    given = quote.strip().strip(_QUOTE_EDGES + "“”„‟‘’‚‛«»")
    if not given or len(given) > MAX_QUOTE_CHARS or _STITCH.search(quote):
        return None
    wanted = _strip_edges(normalise_quote(given))
    if not wanted or _STITCH.search(wanted):
        return None
    long_enough = len(wanted.split()) >= MIN_QUOTE_WORDS
    for key, text, source in values:
        value = normalise_quote(text)
        if (long_enough and wanted in value) or wanted == _strip_edges(value):
            return EvidenceHit(key=key, source=cast("Source", source), quote=given)
    return None


def _is_step_key(key: str, step: int) -> bool:
    return key.startswith(f"process.substeps[{step}].")


def restrict_to_step(values: Sequence[Value], step: int) -> list[Value]:
    """Only the values of step `step` (1-based); used by LABEL (spec 19)."""
    return [v for v in values if _is_step_key(v[0], step)]


def restrict_to_step_or_process(values: Sequence[Value], step: int) -> list[Value]:
    """Step `step`'s values, then the process-field values; never another step's (spec 26 §3.5)."""
    process = [v for v in values if not v[0].startswith("process.substeps[")]
    return restrict_to_step(values, step) + process
