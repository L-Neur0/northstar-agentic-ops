"""From a raw reading to a proposal diff: quote check, shaping, fill-only, and what happens to the steps (spec 17 §3.8–§3.11).

Why: what the model (or the BPMN reader) returns is a request, not a fact. Code decides what a
document may propose: only values whose quote is in the stored text, shaped to the registry,
never over a value a person gave (fill-only: a proposal fills a gap and loses every argument), and
steps only as new rows on an empty table or as gap-fills in rows the expert already named.
Everything dropped is reported with a reason, never silently lost.
What: `Skip`, `Filtered`, `build_diff` (one code path for model and BPMN output) and
`match_steps` (§3.10 case B: by name, then by position only when the counts agree).
Must not: write the profile (that is `profile.apply_proposals`, which re-checks the same rules at
write time), add, remove or reorder an existing row, propose P16 or a none answer, read a clock,
or log a value. Spec 17 §3.8–§3.11; AC-17.25 to AC-17.31, AC-17.40 to AC-17.44.
Amendment §3.18 (reading in context): the role table of item 5 decides which parts of a reading are
used (`not_used` for the rest); `resolve_target` picks the step a step-scoped file belongs to (T1–T5);
`check_description` is the evidence rule for a file description (D1–D5), placed first in the target
step's `data` (D6) and merged into a proposed cell (D7). §3.19 I4: every value read from an image
passes the contact-data check (`personal_data`). Spec 17 Q5: a partly answered field takes a
whole-field proposal that keeps the person's sub-values (`conflicts_with_expert` for a differing one).
AC-17.47 to AC-17.53, AC-17.58, AC-17.59, AC-17.62, AC-17.65.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.models.process_discovery_schemas import StepListItem
from app.utils.prompt_safety import contains_injection_pattern, single_line

from ..domain.field_spec import (
    MAX_STEPS,
    MIN_STEPS,
    PROFILE_SPECS,
    STEP_SPECS,
    FieldSpec,
    Vocabulary,
    has_any_answer,
    is_proposed,
    proposal_keys,
    required_subfield,
    step_cell_key,
    step_key_template,
)
from ..profile.constants import NUMBER_BOUNDS_PROPOSAL
from ..profile.proposals import FieldProposal, ProposalDiff, StepProposal, fill_target, merge_offered
from ..profile.shapes import meta_for, normalized_profile, process_of, resolve_key, rows_of
from ..profile.verdicts import P16_KEY
from .context import ReadingContext
from .quotes import normalise_for_quote, quote_found
from .schema import STEP_SCOPED

TEXT_MAX = 500
ITEM_MAX = 200
ITEMS_PER_FIELD = 20
STEP_LIST_MAX = 30
QUOTE_JOIN = " … "
QUOTES_MAX = 500

# Skip reasons (§3.17).
CONFIRMED = "confirmed"
SPECIALIST_OWNED = "specialist_owned"
NOT_ALLOWED = "not_allowed"
EMPTY_VALUE = "empty_value"
UNSAFE_VALUE = "unsafe_value"
NO_MATCHING_STEP = "no_matching_step"
TOO_FEW_STEPS = "too_few_steps"
TOO_MANY_STEPS = "too_many_steps"
COUNT_MISMATCH = "count_mismatch"
NOT_USED = "not_used"
NO_TARGET_STEP = "no_target_step"
DESCRIPTION_INVALID = "description_invalid"
DESCRIPTION_UNSUPPORTED = "description_unsupported"
PERSONAL_DATA = "personal_data"
CONFLICTS_WITH_EXPERT = "conflicts_with_expert"
QUOTE_INVALID = "quote_invalid"
STEPS_KEY = "steps"
TARGET_KEY = "target_step"
DESCRIPTION_KEY = "file_description"
TARGET_CELLS_KEY = "target_cells"

DESCRIPTION_MIN = 10
DESCRIPTION_MAX = 200
EXCERPT_MIN = 10
#: Contact data a value may not carry (§3.18 D4): an e-mail address, a URL, a run of 7+ digits.
_EMAIL = re.compile(r"\S+@\S+\.\S+")
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
_DIGITS = re.compile(r"\d(?:[\s.\-+()]*\d){6,}")
_WORD = re.compile(r"[^\W\d_]+")
#: Where a file description goes, by role (§3.18 item 5, D6).
DESCRIPTION_LIST: dict[str, str] = {"step_output_example": "outputs", "step_input_example": "inputs"}

Loop = Callable[[Any], int | None]


@dataclass(frozen=True)
class Skip:
    """One dropped proposal: its key, the reason, and how many items or rows when only some were dropped."""

    key: str
    reason: str
    items: int = 0


@dataclass(frozen=True)
class Filtered:
    """The diff for `apply_proposals`, what was dropped, the step list, and the offered counts for the report."""

    diff: ProposalDiff
    skipped: tuple[Skip, ...]
    step_list: tuple[StepListItem, ...]
    offered_fields: int = 0
    offered_steps: int = 0
    offered_cells: int = 0
    steps_given: bool = False
    role: str = "whole_process"
    target_step: int | None = None
    target_source: str = "none"

    @property
    def unmatched(self) -> int:
        return sum(1 for s in self.skipped if s.reason == NO_MATCHING_STEP)


# --- Small shapers ------------------------------------------------------------------------------


def _text(value: Any, limit: int) -> str:
    """Trimmed, one line, at most `limit` characters; "" when there is nothing."""
    if not isinstance(value, str):
        return ""
    return single_line(value, len(value) + 1)[:limit].strip()


def _number(value: Any) -> int | None:
    low, high = NUMBER_BOUNDS_PROPOSAL
    if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
        return value
    return None


def _offered(value: Any) -> bool:
    return value is not None and value != [] and value != {}


def _join_quotes(quotes: Sequence[str]) -> str:
    """Item quotes in order, de-duplicated, joined by ` … `, cut on a whole quote at 500 characters."""
    out: list[str] = []
    for quote in dict.fromkeys(q for q in quotes if q):
        if out and len(QUOTE_JOIN.join([*out, quote])) > QUOTES_MAX:
            break
        out.append(quote)
    return QUOTE_JOIN.join(out)


def _same_name(a: Any, b: Any) -> bool:
    return (
        isinstance(a, str)
        and isinstance(b, str)
        and " ".join(a.split()).casefold() == " ".join(b.split()).casefold() != ""
    )


# --- Fill-only (§3.9) ---------------------------------------------------------------------------


def refusal(profile: Mapping[str, Any], key: str, *, vocab: Vocabulary | None = None) -> str | None:
    """Why a proposal may not land at `key` now, or `None` when the target is empty, proposed or partly answered."""
    address = resolve_key(key)
    if address is None:
        return NOT_ALLOWED
    allowed = step_key_template(address.spec.key) if address.step is not None else address.spec.key
    if allowed not in proposal_keys():
        return NOT_ALLOWED
    return fill_target(profile, address.key, vocab=vocab).refusal


def has_contact_data(text: str) -> bool:
    """An e-mail address, a URL or a run of 7+ digits (spaces, dots, dashes, `+` and brackets ignored)."""
    return bool(_EMAIL.search(text) or _URL.search(text) or _DIGITS.search(text))


def check_description(value: Any, quote: Any, *, text: str, name: str) -> str | None:
    """D1–D5 for a file description and its excerpt: the skip reason, or `None` when it may be used."""
    description = _text(value, DESCRIPTION_MAX + 1)
    if not DESCRIPTION_MIN <= len(description) <= DESCRIPTION_MAX:
        return DESCRIPTION_INVALID
    excerpt = quote if isinstance(quote, str) else ""
    normal_text = normalise_for_quote(text)
    if len(normalise_for_quote(excerpt.strip().strip("\"'“”‘’").strip())) < EXCERPT_MIN:
        return QUOTE_INVALID
    found = quote_found(excerpt, normal_text)
    if found != "ok":
        return found
    words = {w for w in _WORD.findall(description.casefold()) if len(w) >= 4}
    known = set(_WORD.findall(normal_text)) | set(_WORD.findall(normalise_for_quote(name)))
    if not words & known:
        return DESCRIPTION_UNSUPPORTED
    if has_contact_data(description):
        return PERSONAL_DATA
    if contains_injection_pattern(description):
        return UNSAFE_VALUE
    return None


def _mentions_step(message: str, name: str, step: int) -> bool:
    normal = normalise_for_quote(message)
    named = normalise_for_quote(name)
    return bool(named and named in normal) or re.search(rf"\bstep {step}\b", normal) is not None


def resolve_target(raw: Mapping[str, Any], *, text: str, context: ReadingContext, rows: int) -> tuple[int | None, str]:
    """T1–T5: `(target row, source)`; the model's step only when the document or the expert's last words name it."""
    if rows == 0:
        return None, "none"
    step = raw.get("target_step")
    by = raw.get("target_named_by")
    if isinstance(step, int) and not isinstance(step, bool) and 1 <= step <= rows:
        name = context.step_names[step - 1] if step <= len(context.step_names) else ""
        normal_name = normalise_for_quote(name)
        if by == "document" and normal_name and normal_name in normalise_for_quote(text):
            return step, "document"
        if by == "expert" and _mentions_step(context.last_expert, name, step):
            return step, "expert"
    focus = context.focus_step
    if focus is not None and 1 <= focus <= rows:
        return focus, "focus"
    return None, "none"


# --- Steps (§3.10) ------------------------------------------------------------------------------


def _declared(profile: Mapping[str, Any]) -> int | None:
    count = process_of(profile).get("substep_count")
    return count if isinstance(count, int) and not isinstance(count, bool) else None


def match_steps(doc_names: Sequence[str], profile: Mapping[str, Any]) -> list[int | None]:
    """§3.10 case B: for each document step, the matched 1-based row, or `None`."""
    rows = rows_of(normalized_profile(profile))
    matched: list[int | None] = [None] * len(doc_names)
    used: set[int] = set()
    for i, name in enumerate(doc_names):
        for r, row in enumerate(rows, start=1):
            if r not in used and _same_name(row.get("name"), name):
                matched[i] = r
                used.add(r)
                break
    declared = _declared(profile)
    if len(doc_names) == (declared if declared is not None else len(rows)):
        for i in range(len(doc_names)):
            position = i + 1
            if matched[i] is None and position <= len(rows) and position not in used:
                matched[i] = position
                used.add(position)
    return matched


def _table_empty(profile: Mapping[str, Any]) -> bool:
    return not any(has_any_answer(spec, row.get(spec.key)) for row in rows_of(profile) for spec in STEP_SPECS)


# --- The builder --------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Step:
    position: int
    name: str
    quote: str
    raw: Mapping[str, Any]


class _Builder:
    """Collects proposals and skips for one document; every shaper returns `(value, quote)` or `None`."""

    def __init__(
        self, text: str, profile: dict[str, Any], *, vocab: Vocabulary | None = None, from_image: bool = False
    ) -> None:
        self.normal = normalise_for_quote(text)
        self.profile = profile
        self.vocab = vocab
        self.from_image = from_image
        self.skips: list[Skip] = []

    def unsafe(self, texts: Sequence[Any]) -> str | None:
        """`unsafe_value` for an injection pattern; from an image, `personal_data` for contact data (I4)."""
        strings = [t for t in texts if isinstance(t, str)]
        if any(contains_injection_pattern(t) for t in strings):
            return UNSAFE_VALUE
        if self.from_image and any(has_contact_data(t) for t in strings):
            return PERSONAL_DATA
        return None

    def skip(self, key: str, reason: str, items: int = 0) -> None:
        self.skips.append(Skip(key, reason, items))

    def skip_counts(self, key: str, counts: dict[str, int]) -> None:
        for reason, n in counts.items():
            if n:
                self.skip(key, reason, n)

    def check_quote(self, quote: Any) -> str | None:
        result = quote_found(quote if isinstance(quote, str) else "", self.normal)
        return None if result == "ok" else result

    # one value with one quote (text, number, scalar object)

    def single(self, spec: FieldSpec, raw: Mapping[str, Any], key: str) -> tuple[Any, str] | None:
        reason = self.check_quote(raw.get("quote"))
        if reason is not None:
            self.skip(key, reason)
            return None
        if spec.kind == "object":
            value = self.object_value(spec, raw)
            texts = [v for v in (value or {}).values() if isinstance(v, str)]
        elif spec.kind == "number":
            number = _number(raw.get("value"))
            value, texts = number, []
        else:
            text = _text(raw.get("value"), TEXT_MAX)
            value, texts = (text or None), [text]
        if value is None:
            self.skip(key, EMPTY_VALUE)
            return None
        unsafe = self.unsafe(texts)
        if unsafe is not None:
            self.skip(key, unsafe)
            return None
        return value, str(raw["quote"]).strip()

    @staticmethod
    def object_value(spec: FieldSpec, raw: Mapping[str, Any]) -> dict[str, Any] | None:
        value: dict[str, Any] = {}
        present = False
        for sub in spec.subfields:
            if sub.kind == "bool":
                value[sub.key] = False
            elif sub.kind == "number":
                value[sub.key] = _number(raw.get(sub.key))
                present = present or value[sub.key] is not None
            else:
                value[sub.key] = _text(raw.get(sub.key), TEXT_MAX)
                present = present or bool(value[sub.key])
        return value if present else None

    # many items, one quote each (list, object of lists, object_list)

    def items(self, raw_items: Any, counts: dict[str, int], seen: set[str], kept: list[str], quotes: list[str]) -> None:
        for item in raw_items or []:
            if len(kept) >= ITEMS_PER_FIELD:
                return
            reason = self.check_quote(item.get("quote"))
            text = _text(item.get("value"), ITEM_MAX)
            if reason is None and not text:
                reason = EMPTY_VALUE
            if reason is None:
                reason = self.unsafe([text])
            if reason is not None:
                counts[reason] = counts.get(reason, 0) + 1
                continue
            if text.casefold() in seen:
                continue
            seen.add(text.casefold())
            kept.append(text)
            quotes.append(str(item["quote"]).strip())

    def item_list(self, raw_items: Any, key: str) -> tuple[Any, str] | None:
        counts: dict[str, int] = {}
        kept: list[str] = []
        quotes: list[str] = []
        self.items(raw_items, counts, set(), kept, quotes)
        self.skip_counts(key, counts)
        return (kept, _join_quotes(quotes)) if kept else None

    def list_object(self, spec: FieldSpec, raw: Mapping[str, Any], key: str) -> tuple[Any, str] | None:
        counts: dict[str, int] = {}
        quotes: list[str] = []
        value: dict[str, Any] = {}
        for sub in spec.subfields:
            kept: list[str] = []
            self.items(raw.get(sub.key), counts, set(), kept, quotes)
            value[sub.key] = kept
        self.skip_counts(key, counts)
        return (value, _join_quotes(quotes)) if any(value.values()) else None

    def rows(self, spec: FieldSpec, raw_rows: Any, key: str, loop: Loop) -> tuple[Any, str] | None:
        required = required_subfield(spec)
        counts: dict[str, int] = {}
        rows: list[dict[str, Any]] = []
        quotes: list[str] = []
        for raw in raw_rows or []:
            reason = self.check_quote(raw.get("quote"))
            row: dict[str, Any] = {}
            for sub in spec.subfields:
                if sub.kind == "bool":
                    continue
                if sub.kind == "number":
                    row[sub.key] = loop(raw.get(sub.key)) if sub.key == "loops_back_to" else _number(raw.get(sub.key))
                else:
                    row[sub.key] = _text(raw.get(sub.key), TEXT_MAX)
            if reason is None and required is not None and not row.get(required):
                reason = EMPTY_VALUE
            if reason is None:
                reason = self.unsafe(list(row.values()))
            if reason is not None:
                counts[reason] = counts.get(reason, 0) + 1
                continue
            rows.append(row)
            quotes.append(str(raw["quote"]).strip())
        self.skip_counts(key, counts)
        return (rows, _join_quotes(quotes)) if rows else None

    def shape(self, spec: FieldSpec, raw: Any, key: str, loop: Loop) -> tuple[Any, str] | None:
        """The registry-shaped value and its verified quote(s), or `None` (with the skips recorded)."""
        if spec.kind == "list":
            return self.item_list(raw, key)
        if spec.kind == "object_list":
            return self.rows(spec, raw, key, loop)
        if spec.kind == "object" and any(s.kind == "list" for s in spec.subfields):
            return self.list_object(spec, raw, key)
        return self.single(spec, raw, key)

    def propose(self, spec: FieldSpec, raw: Any, key: str, emit: str, loop: Loop) -> FieldProposal | None:
        """Shape, then the fill-only check against the current profile; `emit` is the key in the diff.

        A partly answered field gets the whole value: the person's sub-values kept, the document's
        missing ones added (spec 17 Q5); offered sub-values that differ are reported, never proposed.
        """
        shaped = self.shape(spec, raw, key, loop)
        if shaped is None:
            return None
        reason = refusal(self.profile, key, vocab=self.vocab)
        if reason is not None:
            self.skip(key, reason)
            return None
        value, conflicts = merge_offered(spec, shaped[0], fill_target(self.profile, key, vocab=self.vocab))
        if conflicts:
            self.skip(key, CONFLICTS_WITH_EXPERT, conflicts)
        if value is None:
            if not conflicts:
                self.skip(key, CONFIRMED)
            return None
        return FieldProposal(emit, value, shaped[1])


def _no_loop(_: Any) -> int | None:
    return None


def _loop_to(rows: Mapping[int, int], own_row: int) -> Loop:
    """`loops_back_to` from the document's step number to the row it became; itself or unknown → `None`."""

    def translate(target: Any) -> int | None:
        if not isinstance(target, int) or isinstance(target, bool):
            return None
        row = rows.get(target)
        return row if row is not None and row != own_row else None

    return translate


def _description_raw(
    data: Mapping[str, Any], role: str, builder: _Builder, *, text: str, name: str
) -> dict[str, Any] | None:
    """The file description as one `{value, quote}` item for `data.<list>` (D1–D6), or `None` (with the skip)."""
    offered = data.get(DESCRIPTION_KEY)
    if not isinstance(offered, Mapping) or not offered:
        return None
    if role not in DESCRIPTION_LIST:
        builder.skip(DESCRIPTION_KEY, NOT_USED)
        return None
    reason = check_description(offered.get("value"), offered.get("quote"), text=text, name=name)
    if reason is not None:
        builder.skip(DESCRIPTION_KEY, reason)
        return None
    return {"value": _text(offered.get("value"), DESCRIPTION_MAX), "quote": str(offered.get("quote")).strip()}


def _target_cells(
    data: Mapping[str, Any],
    role: str,
    builder: _Builder,
    *,
    target: int,
    rows: int,
    text: str,
    name: str,
) -> list[FieldProposal]:
    """§3.18 items 7–8: the cells of the target row, the description first in `data.outputs`/`inputs`."""
    cells = dict(data.get(TARGET_CELLS_KEY) or {})
    description = _description_raw(data, role, builder, text=text, name=name)
    if description is not None:
        raw_data = dict(cells.get("data") or {})
        listed = DESCRIPTION_LIST[role]
        raw_data[listed] = [description, *(raw_data.get(listed) or [])]
        cells["data"] = raw_data

    def loop(value: Any) -> int | None:
        ok = isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= rows and value != target
        return value if ok else None

    out: list[FieldProposal] = []
    for spec in STEP_SPECS:
        if not spec.propose or spec.key == "name" or not _offered(cells.get(spec.key)):
            continue
        key = step_cell_key(target, spec.key)
        cell = builder.propose(spec, cells[spec.key], key, key, loop)
        if cell is not None:
            out.append(cell)
    return out


def build_diff(
    raw: BaseModel,
    *,
    document_id: str,
    text: str,
    profile: Mapping[str, Any],
    vocab: Vocabulary | None = None,
    context: ReadingContext | None = None,
    name: str = "",
    from_image: bool = False,
) -> Filtered:
    """Turn one reading (model or BPMN) into the proposal diff of §3.11, with every drop reported.

    The role (§3.18 item 5) decides what is used: steps only for `whole_process`; for the other
    roles the target step's cells and the file description. `vocab` enables partial-field proposals.
    """
    current = normalized_profile(profile)
    data = raw.model_dump()
    builder = _Builder(text, current, vocab=vocab, from_image=from_image)
    role = str(data.get("document_role") or "whole_process")

    fields: list[FieldProposal] = []
    offered_fields = 0
    for spec in PROFILE_SPECS:
        if not (spec.is_process and spec.propose) or not _offered(data.get(spec.leaf)):
            continue
        offered_fields += 1
        proposal = builder.propose(spec, data[spec.leaf], spec.key, spec.key, _no_loop)
        if proposal is not None:
            fields.append(proposal)

    raw_steps: list[Mapping[str, Any]] = list(data.get("steps") or [])
    offered_steps = len(raw_steps)
    step_specs = [s for s in STEP_SPECS if s.propose and s.key != "name"]
    offered_cells = sum(1 for step in raw_steps for s in STEP_SPECS if _offered(step.get(s.key)))
    target_cells_raw = data.get(TARGET_CELLS_KEY) or {}
    offered_cells += sum(1 for s in STEP_SPECS if _offered(target_cells_raw.get(s.key)))
    if role in STEP_SCOPED and raw_steps:
        builder.skip(STEPS_KEY, NOT_USED)
        raw_steps = []
    valid: list[_Step] = []
    for position, step in enumerate(raw_steps, start=1):
        name_raw = step.get("name") or {}
        reason = builder.check_quote(name_raw.get("quote"))
        name = _text(name_raw.get("value"), TEXT_MAX)
        if reason is None and not name:
            reason = EMPTY_VALUE
        if reason is None and contains_injection_pattern(name):
            reason = UNSAFE_VALUE
        if reason is not None:
            builder.skip(f"{STEPS_KEY}[{position}]", reason)
            continue
        valid.append(_Step(position, name, str(name_raw["quote"]).strip(), step))

    new_rows: list[StepProposal] = []
    step_cells: list[FieldProposal] = []
    step_list: list[StepListItem] = []
    steps_given = not _table_empty(current)

    if not steps_given and valid:
        declared = _declared(current)
        p16_fixed = declared is not None and not is_proposed(meta_for(current, P16_KEY))
        if len(valid) < MIN_STEPS:
            builder.skip(STEPS_KEY, TOO_FEW_STEPS)
        elif len(valid) > MAX_STEPS or (p16_fixed and declared != len(valid)):
            step_list = [StepListItem(name=s.name, quote=s.quote) for s in valid[:STEP_LIST_MAX]]
            builder.skip(STEPS_KEY, TOO_MANY_STEPS if len(valid) > MAX_STEPS else COUNT_MISMATCH)
        else:
            row_of = {s.position: r for r, s in enumerate(valid, start=1)}
            for row, step in enumerate(valid, start=1):
                cells = [FieldProposal("name", step.name, step.quote)]
                for spec in step_specs:
                    if not _offered(step.raw.get(spec.key)):
                        continue
                    key = step_cell_key(row, spec.key)
                    cell = builder.propose(spec, step.raw[spec.key], key, spec.key, _loop_to(row_of, row))
                    if cell is not None:
                        cells.append(cell)
                new_rows.append(StepProposal(tuple(cells)))
    elif valid:
        matched = match_steps([s.name for s in valid], current)
        row_of = {s.position: r for s, r in zip(valid, matched, strict=True) if r is not None}
        rows = rows_of(current)
        for step, row in zip(valid, matched, strict=True):
            if row is None:
                builder.skip(f"{STEPS_KEY}[{step.position}]", NO_MATCHING_STEP)
                continue
            name_key = step_cell_key(row, "name")
            if not _same_name(rows[row - 1].get("name"), step.name) and refusal(current, name_key) is None:
                step_cells.append(FieldProposal(name_key, step.name, step.quote))
            for spec in step_specs:
                if not _offered(step.raw.get(spec.key)):
                    continue
                key = step_cell_key(row, spec.key)
                cell = builder.propose(spec, step.raw[spec.key], key, key, _loop_to(row_of, row))
                if cell is not None:
                    step_cells.append(cell)

    target: int | None = None
    source = "none"
    scoped_offer = _offered(data.get(TARGET_CELLS_KEY)) or _offered(data.get(DESCRIPTION_KEY))
    if role not in STEP_SCOPED:
        for key in (TARGET_CELLS_KEY, DESCRIPTION_KEY):
            if _offered(data.get(key)):
                builder.skip(key, NOT_USED)
    else:
        rows = len(rows_of(current))
        target, source = resolve_target(data, text=text, context=context or ReadingContext(), rows=rows)
        if target is None:
            if scoped_offer:
                builder.skip(TARGET_KEY, NO_TARGET_STEP)
        else:
            step_cells = _target_cells(data, role, builder, target=target, rows=rows, text=text, name=name)

    diff = ProposalDiff(document_id, fields=tuple(fields), steps=tuple(new_rows), step_cells=tuple(step_cells))
    return Filtered(
        diff,
        tuple(builder.skips),
        tuple(step_list),
        offered_fields=offered_fields,
        offered_steps=offered_steps,
        offered_cells=offered_cells,
        steps_given=steps_given,
        role=role,
        target_step=target,
        target_source=source,
    )
