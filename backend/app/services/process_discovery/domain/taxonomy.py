"""The company's cluster taxonomy: model, validation and lookups (spec 12 §3.8; product F-07, F-22).

Why: every process is placed in one of the company's clusters, and the clusters are configuration,
not code, so a new company is a new YAML file. Placing a process from a keyword without a model
call (F-07.1) is only safe when no keyword can fire in two clusters, so the file is validated
hard at start-up and a bad file stops the app with a message naming the cluster and the rule.
What: `Cluster` and `Taxonomy` (frozen Pydantic models, `CompanyConfig.taxonomy`), the keyword
matcher `keyword_hit`, and the lookups `by_code`, `by_spoken`, `match_keywords`, `single_match`,
`codes` and `prompt_block`. Pure: it reads no file (spec 10 does), no clock and no environment.
Must not hold any company's cluster names; they live in `config/<company>/taxonomy.yaml`.
Tests: AC-12.29 to AC-12.32.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

UNKNOWN_CODE = "UNKNOWN"

#: Words too vague to place anything: a keyword equal to one of them would fire everywhere.
GENERIC_TERMS: frozenset[str] = frozenset(
    {
        "process",
        "report",
        "review",
        "approval",
        "data",
        "system",
        "email",
        "meeting",
        "document",
        "request",
        "team",
        "manager",
        "plan",
        "update",
        "check",
        "project",
    }
)

MAX_DESCRIPTION_WORDS = 25
_CODE = re.compile(r"^[A-Z]{2,4}$")
_SHORT_KEYWORD = 3
_CONFIRM = re.compile(r"(?:i\s+)?confirm[:\s]+(.+?)(?:\s*\(([^)]*)\))?\s*\.?", re.IGNORECASE)


def keyword_hit(keyword: str, text: str) -> bool:
    """Whether `keyword` appears in `text`: case-insensitive, word boundary on the left.

    Keywords of three characters or fewer also need a boundary on the right, so "nda" matches
    "sign an NDA" but not "standard", while "invoice" still matches "invoices".
    """
    if not keyword:
        return False
    tail = r"\b" if len(keyword) <= _SHORT_KEYWORD else ""
    return re.search(rf"\b{re.escape(keyword)}{tail}", text, re.IGNORECASE) is not None


def _spoken_key(text: str) -> str:
    """Lower case, "&" read as "and", letters and digits only: "IT & Security" → "itandsecurity"."""
    return re.sub(r"[^a-z0-9]+", "", text.lower().replace("&", " and "))


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.IGNORECASE) is not None


class Cluster(BaseModel):
    """One cluster: a short code, the company's name for it, a plain description and keywords."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    keywords: tuple[str, ...]


class Taxonomy(BaseModel):
    """The company's clusters in display order. Frozen; validated as a whole (§3.8)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    clusters: tuple[Cluster, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Taxonomy:
        problems = _problems(self.clusters)
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def codes(self) -> list[str]:
        """Codes in file order."""
        return [c.code for c in self.clusters]

    def by_code(self, code: str | None) -> Cluster | None:
        """The cluster with this code, case-insensitive; `None` when unknown."""
        if not code:
            return None
        wanted = code.strip().upper()
        return next((c for c in self.clusters if c.code == wanted), None)

    def by_spoken(self, text: str | None) -> Cluster | None:
        """The cluster a person's reply names, as a whole reply; never a match inside prose.

        Accepts a code or a name however it is typed ("it and security", "IT", "Finance") and the
        sentence `I confirm <name> (<CODE>)`.
        """
        if not text or not text.strip():
            return None
        stripped = text.strip()
        confirm = _CONFIRM.fullmatch(stripped)
        if confirm:
            found = self.by_code(confirm.group(2)) or self.by_spoken(confirm.group(1))
            if found is not None:
                return found
        key = _spoken_key(stripped)
        if not key:
            return None
        return next((c for c in self.clusters if key in (_spoken_key(c.code), _spoken_key(c.name))), None)

    def match_keywords(self, text: str | None) -> list[Cluster]:
        """Every cluster with a keyword hit in `text`, in file order."""
        if not text:
            return []
        return [c for c in self.clusters if any(keyword_hit(k, text) for k in c.keywords)]

    def single_match(self, text: str | None) -> Cluster | None:
        """The cluster when exactly one matches, else `None` (F-07.1)."""
        matches = self.match_keywords(text)
        return matches[0] if len(matches) == 1 else None

    def prompt_block(self) -> str:
        """One line `CODE · name: description` per cluster, for the CLASSIFY prompt."""
        return "\n".join(f"{c.code} · {c.name}: {c.description}" for c in self.clusters)


def _problems(clusters: tuple[Cluster, ...]) -> list[str]:
    """Every rule of §3.8 broken by `clusters`, one readable line each, naming the cluster."""
    problems: list[str] = []
    seen_codes: dict[str, str] = {}
    seen_names: dict[str, str] = {}
    keyword_owner: dict[str, str] = {}
    for c in clusters:
        who = f"cluster {c.code} ({c.name})"
        if c.code == UNKNOWN_CODE:
            problems.append(f"{who}: the code {UNKNOWN_CODE} is reserved")
        elif not _CODE.match(c.code):
            problems.append(f"{who}: the code must be 2 to 4 capital letters")
        if c.code in seen_codes:
            problems.append(f"{who}: the code is already used by cluster {seen_codes[c.code]}")
        seen_codes.setdefault(c.code, c.name)
        folded = c.name.casefold()
        if folded in seen_names:
            problems.append(f"{who}: the name is already used by cluster {seen_names[folded]}")
        seen_names.setdefault(folded, c.code)
        words = len(c.description.split())
        if words > MAX_DESCRIPTION_WORDS:
            problems.append(f"{who}: the description has {words} words (at most {MAX_DESCRIPTION_WORDS})")
        if c.description.strip().casefold() == folded:
            problems.append(f"{who}: the description only repeats the name")
        if not c.keywords:
            problems.append(f"{who}: needs at least one keyword")
        for k in c.keywords:
            if k != k.strip().lower() or not k.strip():
                problems.append(f"{who}: keyword {k!r} must be lowercase and trimmed")
            if k in GENERIC_TERMS:
                problems.append(f"{who}: keyword {k!r} is too generic to place anything")
            owner = keyword_owner.get(k)
            if owner is not None and owner != c.code:
                problems.append(f"{who}: keyword {k!r} is also a keyword of cluster {owner}")
            keyword_owner.setdefault(k, c.code)
    for c in clusters:
        who = f"cluster {c.code} ({c.name})"
        for other in clusters:
            if other is c:
                continue
            if c.name.casefold() == other.code.casefold():
                problems.append(f"{who}: the name equals the code of cluster {other.code}")
            if _contains_phrase(c.description, other.name):
                problems.append(f"{who}: the description names cluster {other.code} ({other.name})")
            for k in c.keywords:
                for inner in other.keywords:
                    if k != inner and keyword_hit(k, inner):
                        problems.append(f"{who}: keyword {k!r} fires inside keyword {inner!r} of cluster {other.code}")
    return problems
