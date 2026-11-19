"""The quote check: a proposed value counts only when its quote is really in the stored text (spec 17 §3.8).

Why: "no quote, no claim" (product rule 6). A model can write a plausible sentence the document
never contained; code must catch that, while forgiving what extraction and typography change on
the way (line breaks, case, curly quotes, dashes, look-alike letters, table cells joined by ` | `).
One function serves model output and BPMN output alike, so both paths obey the same rule.
What: `normalise_for_quote` (applied once to the stored text and to every quote) and `quote_found`
(`ok`, `quote_not_found` or `quote_invalid`); a quote split by `...` must match part by part, in order.
Must not: accept a paraphrase, check against anything but the capped stored text, or log a quote.
Spec 17 §3.8; AC-17.24.
"""

from __future__ import annotations

import re
from typing import Literal

from app.utils.prompt_safety import normalize_for_matching

QuoteResult = Literal["ok", "quote_not_found", "quote_invalid"]

QUOTE_MIN, QUOTE_MAX = 3, 300
ELLIPSIS = "..."

_FOLD = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})
_SPACES = re.compile(r"\s+")
_EDGES = "\"' \t"


def normalise_for_quote(text: str) -> str:
    """`normalize_for_matching`, then quotes and dashes folded, `…` as `...`, ` | ` as one space."""
    folded = normalize_for_matching(text).translate(_FOLD).replace("…", ELLIPSIS)
    return _SPACES.sub(" ", folded.replace(" | ", " ").replace("|", " ")).strip()


def _strip(quote: str) -> str:
    previous = None
    while previous != quote:
        previous = quote
        quote = quote.strip(_EDGES)
        quote = quote.removeprefix(ELLIPSIS).removesuffix(ELLIPSIS)
    return quote


def quote_found(quote: str, normalised_text: str) -> QuoteResult:
    """Whether `quote` is in the (already normalised) stored text."""
    clean = _strip(normalise_for_quote(quote or ""))
    if not QUOTE_MIN <= len(clean) <= QUOTE_MAX:
        return "quote_invalid"
    parts = [p.strip() for p in clean.split(ELLIPSIS)]
    parts = [p for p in parts if len(p) >= QUOTE_MIN]
    if not parts:
        return "quote_invalid"
    position = 0
    for part in parts:
        found = normalised_text.find(part, position)
        if found < 0:
            return "quote_not_found"
        position = found + len(part)
    return "ok"
