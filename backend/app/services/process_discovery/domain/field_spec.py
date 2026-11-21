"""The field registry: what a field is and when it counts (spec 12 §3.1–§3.7, §3.10; product §5, F-05).

Why: the profile used to be restated in many places (prompts, models, scoring, screens), and drift
between them failed silently: a field was collected and stored but never counted. This module
declares every field once, as data (P01–P16, S01–S13, D01–D02), and every list, weight, total,
limit and whitelist is derived from it. Nothing else may restate them.
What: `FieldSpec` and the registry, `Verdict` and `evaluate_field` (the single definition of
"answered"), the counting rule for proposals (`counts`, `field_status`), address resolution, the
EXTRACT / proposal / specialist whitelists, lenient row folding, the derived roll-ups, the
interview limits, and the company `Vocabulary` (regions, taxonomy, wording overrides).
Rules it protects: a stored `false` is never an answer; a proposed value never counts; every
reason is one finished sentence a person can read. Must not: do I/O, read a clock or the
environment, or import anything outside the standard library, `pydantic` and `domain`.
Tests: AC-12.1 to AC-12.28 and AC-12.45. Short step walk amendment (approved 2026-11-20): the ask
groups, `ask_part`, `optional`, S13 `decision_type` and the `agent` source (AC-12.50 to AC-12.52).
Owner test amendment (amended 2026-11-21): roles in group A; approvals, exceptions and hand-over form
the optional group B; group C is goal and owner; `progress_step_specs` (AC-12.53).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple, cast

from pydantic import BaseModel, ConfigDict, field_validator

from .taxonomy import Taxonomy

Kind = Literal["text", "list", "number", "object", "object_list"]

# --- Phases (plain strings; the `Phase` enum lives in the models, parity is tested) -------------

PHASE_CONTEXT = "context"
PHASE_FIND = "find"
PHASE_BOUNDARIES = "boundaries"
PHASE_MEASURE = "measure"
PHASE_STEP_COUNT = "step_count"
PHASE_STEPS = "steps"
PHASE_CONFIRM = "confirm"
PHASE_REVIEW = "review"
PHASE_FINISHED = "finished"
PHASE_NO_CANDIDATE = "no_candidate"

COLLECTING_PHASES: tuple[str, ...] = (PHASE_CONTEXT, PHASE_FIND, PHASE_BOUNDARIES, PHASE_MEASURE, PHASE_STEP_COUNT)
#: `confirm` is no longer on the path (spec 14 §3.20 O10); the value stays readable for old sessions.
PHASE_ORDER: tuple[str, ...] = (*COLLECTING_PHASES, PHASE_STEPS, PHASE_REVIEW)

# --- Verdicts, sources, sidecars ----------------------------------------------------------------

STATUS_COMPLETE, STATUS_PARTIAL, STATUS_INVALID = "complete", "partial", "invalid"
SOURCE_EXPERT, SOURCE_DOCUMENT, SOURCE_SPECIALIST = "expert", "document", "specialist"
#: A Tier C step cell proposed by code from the expert's other answers (short step walk, spec 14 §3.19 W6).
SOURCE_AGENT = "agent"
META_PROPOSED, META_CONFIRMED = "proposed", "confirmed"
META_KEY, SKIPPED_KEY, NONE_KEY, NONE_FLAG = "__meta", "__skipped", "none", "none_identified"
#: Open and left document conflicts (spec 17 §3.21): on the profile and on each row, never graded or shown to a model.
CONFLICTS_KEY = "__conflicts"

#: Flags on `process`: set only by code, never fields, never scored, on no whitelist.
FLAG_KEYS: tuple[str, ...] = ("substeps_complete", "roles_confirmed", "tools_confirmed", "substep_count_rejected")
REJECTED_COUNT_KEY = "substep_count_rejected"

# --- Limits (§3.5) ------------------------------------------------------------------------------

MIN_STEPS, MAX_STEPS = 2, 6
COMPLETENESS_GATE = 0.80
FIELD_ASK_LIMIT = 3
REVIEW_ASK_LIMIT = 2
CELL_ASK_LIMIT = 3
WIDENING_LIMIT = 2
CONFIRM_TURN_LIMIT = 6
FIND_FOCUS_TURN, FIND_DIRECT_TURN = 4, 6
ACTIVITIES_SOFT_MAX = 5

VARIATION_ANSWERS = ("yes", "no", "partly")
DECISION_KINDS = ("rules", "judgement", "mix")

# --- Ask groups (short step walk, approved 2026-11-20; spec 12 §3.4, spec 14 §3.19) ---------------
#: Fields asked together in one question. Process groups pair two fields; step groups are the tiers.
GROUP_RESULT, GROUP_QUICK = "result", "quick"
GROUP_NAMES, GROUP_A, GROUP_B, GROUP_EFFORT, GROUP_C = "names", "A", "B", "effort", "C"


class Verdict(NamedTuple):
    """How one field stands. `missing` names what is still needed; `reason` says it in words."""

    status: str
    missing: tuple[str, ...] = ()
    reason: str = ""

    @property
    def is_complete(self) -> bool:
        return self.status == STATUS_COMPLETE


COMPLETE = Verdict(STATUS_COMPLETE)

Validator = Callable[[Any, Mapping[str, Any], "Vocabulary"], Verdict]


@dataclass(frozen=True)
class SubFieldSpec:
    """One key inside an `object` field or an `object_list` row."""

    key: str
    kind: str  # text | list | number | bool
    required: bool = True
    label: str = ""

    def __post_init__(self) -> None:
        if not self.label:
            object.__setattr__(self, "label", self.key.replace("_", " "))


@dataclass(frozen=True)
class FieldSpec:
    """One collected field, process level (P series) or per step (S series)."""

    id: str
    key: str
    label: str
    kind: Kind
    phase: str
    weight: int
    question: str
    rule: str
    subfields: tuple[SubFieldSpec, ...] = ()
    complete_when: tuple[tuple[str, ...], ...] = ()
    validator: Validator | None = None
    extract: bool = True
    propose: bool = True
    max_items: int | None = None
    max_asks: int | None = None
    #: Fields with the same group are asked together in one question (spec 14 §3.19).
    group: str | None = None
    #: The short phrase a code-built group question uses ("what is annoying or slow").
    ask_part: str = ""
    #: Asked at most `max_asks` times, then given up at once: never deferred, never in the review.
    optional: bool = False
    #: A step field asked, shown and counted only for some rows (spec 12 §3.13); `None` = always.
    applies_when: str | None = None

    @property
    def leaf(self) -> str:
        """The last dotted segment: how the field is named inside its parent."""
        return self.key.rsplit(".", 1)[-1]

    @property
    def is_process(self) -> bool:
        return self.key.startswith("process.")


@dataclass(frozen=True)
class DerivedSpec:
    """A roll-up built by code from other fields, never asked (D series)."""

    id: str
    key: str
    label: str
    source: str
    reducer: Callable[[Mapping[str, Any]], list[str]]


# --- Company vocabulary (§3.10) -----------------------------------------------------------------


class FieldWording(BaseModel):
    """Optional label and question override for one field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str | None = None
    question: str | None = None


class WordingOverrides(BaseModel):
    """`config/<company>/wording.yaml`: overrides by field ID. Unknown IDs are a config error."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fields: dict[str, FieldWording] = {}

    @field_validator("fields")
    @classmethod
    def _known_ids(cls, value: dict[str, FieldWording]) -> dict[str, FieldWording]:
        unknown = sorted(k for k in value if spec_by_id(k) is None)
        if unknown:
            raise ValueError(f"unknown field IDs: {', '.join(unknown)}")
        return value


@dataclass(frozen=True)
class Vocabulary:
    """The company words the validators and reason sentences need. Built once from the config."""

    taxonomy: Taxonomy
    regions: tuple[str, ...]
    wording: WordingOverrides

    def label(self, spec: FieldSpec) -> str:
        override = self.wording.fields.get(spec.id)
        return override.label if override and override.label else spec.label

    def question(self, spec: FieldSpec) -> str:
        override = self.wording.fields.get(spec.id)
        return override.question if override and override.question else spec.question

    def region(self, text: str) -> str | None:
        """The configured spelling of a region, matched case-insensitively; `None` when unknown."""
        wanted = text.strip().casefold()
        return next((r for r in self.regions if r.casefold() == wanted), None)


# --- Small typed helpers ------------------------------------------------------------------------


def _mapping(value: object) -> Mapping[str, Any] | None:
    return cast("Mapping[str, Any]", value) if isinstance(value, Mapping) else None


def _list(value: object) -> list[Any] | None:
    return cast("list[Any]", value) if isinstance(value, list) else None


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _present(value: object, kind: str) -> bool:
    """Whether one value or sub-field carries an answer (§3.2). A stored `false` never does."""
    if kind == "bool":
        return value is True
    if kind == "number":
        return value is not None and not isinstance(value, bool)
    if kind == "list":
        items = _list(value)
        return bool(items)
    return bool(_text(value))


def is_none_row(entry: Any) -> bool:
    """Whether one `object_list` entry is the explicit "there are none" row."""
    row = _mapping(entry)
    return row is not None and row.get(NONE_KEY) is True


def _not_answered(label: str, spec: FieldSpec) -> Verdict:
    return Verdict(STATUS_PARTIAL, (spec.leaf,), f"{label} has not been answered yet.")


def _sub_labels(spec: FieldSpec, keys: tuple[str, ...]) -> str:
    labels = {sf.key: sf.label for sf in spec.subfields}
    return ", ".join(labels.get(k, k.replace("_", " ")) for k in keys)


def _still_needs(label: str, spec: FieldSpec, missing: tuple[str, ...]) -> str:
    return f"{label} still needs: {_sub_labels(spec, missing)}."


# --- The grader (§3.2) --------------------------------------------------------------------------


def _groups(spec: FieldSpec) -> tuple[tuple[str, ...], ...]:
    if spec.complete_when:
        return spec.complete_when
    required = tuple(sf.key for sf in spec.subfields if sf.required)
    return (required,) if required else ()


def _best_missing(spec: FieldSpec, container: Mapping[str, Any]) -> tuple[str, ...] | None:
    """`None` when a group is satisfied, else the missing members of the closest group."""
    kinds = {sf.key: sf.kind for sf in spec.subfields}
    best: tuple[str, ...] = ()
    best_present = -1
    for group in _groups(spec):
        missing = tuple(k for k in group if not _present(container.get(k), kinds.get(k, "text")))
        if not missing:
            return None
        present = len(group) - len(missing)
        if present > best_present:
            best_present, best = present, missing
    return best


def _grade_object(spec: FieldSpec, value: Any, label: str) -> Verdict:
    missing = _best_missing(spec, _mapping(value) or {})
    if missing is None:
        return COMPLETE
    return Verdict(STATUS_PARTIAL, missing, _still_needs(label, spec, missing))


def _grade_rows(spec: FieldSpec, value: Any, label: str) -> Verdict:
    best: tuple[str, ...] | None = None
    for entry in _list(value) or []:
        if is_none_row(entry):
            return COMPLETE
        row = _mapping(entry)
        if row is None:
            continue
        missing = _best_missing(spec, row)
        if missing is None:
            return COMPLETE
        if best is None or len(missing) < len(best):
            best = missing
    groups = _groups(spec)
    missing = best if best is not None else (groups[0] if groups else (spec.leaf,))
    return Verdict(STATUS_PARTIAL, missing, f'{_still_needs(label, spec, missing)} "There are none" is also an answer.')


def evaluate_field(spec: FieldSpec, value: Any, profile: Mapping[str, Any], vocab: Vocabulary) -> Verdict:
    """Grade one field's stored value against its rule. The single definition of "answered"."""
    if spec.validator is not None:
        return spec.validator(value, profile, vocab)
    label = vocab.label(spec)
    if spec.kind == "object":
        return _grade_object(spec, value, label)
    if spec.kind == "object_list":
        return _grade_rows(spec, value, label)
    return COMPLETE if _present(value, spec.kind) else _not_answered(label, spec)


def has_any_answer(spec: FieldSpec, value: Any) -> bool:
    """Whether anything has been put into this field, counted or not.

    Looks past the empty skeleton of an object (a dict of blank sub-fields is not an answer).
    """

    def any_subfield(entry: Any) -> bool:
        row = _mapping(entry)
        return row is not None and any(_present(row.get(sf.key), sf.kind) for sf in spec.subfields)

    if spec.kind == "object_list":
        return any(is_none_row(e) or any_subfield(e) for e in _list(value) or [])
    if spec.kind == "object":
        return any_subfield(value)
    return _present(value, spec.kind)


# --- Provenance (§3.6) --------------------------------------------------------------------------


def is_proposed(meta: Mapping[str, Any] | None) -> bool:
    """Whether a meta entry marks the value as a proposal not yet confirmed by the expert."""
    return meta is not None and meta.get("status") == META_PROPOSED


def counts(verdict: Verdict, meta: Mapping[str, Any] | None) -> bool:
    """F-05.6: a field counts only when complete and not a proposal. No meta = expert, confirmed."""
    return verdict.is_complete and not is_proposed(meta)


def field_status(verdict: Verdict, meta: Mapping[str, Any] | None, *, answered: bool, skipped: bool = False) -> str:
    """Display status for the live panel and the review screen, in the order of §3.6."""
    if is_proposed(meta) and answered:
        return "proposed"
    if verdict.is_complete:
        return "complete"
    if skipped:
        return "skipped"
    if not answered:
        return "empty"
    if verdict.status == STATUS_INVALID:
        return "invalid"
    return "partial"


# --- Validators (§3.4) --------------------------------------------------------------------------


def _label_of(field_id: str, vocab: Vocabulary) -> str:
    spec = spec_by_id(field_id)
    return vocab.label(spec) if spec is not None else field_id


def _validate_region(value: Any, profile: Mapping[str, Any], vocab: Vocabulary) -> Verdict:
    label = _label_of("P03", vocab)
    text = _text(value)
    if not text:
        return Verdict(STATUS_PARTIAL, ("region",), f"{label} has not been answered yet.")
    if vocab.region(text) is None:
        return Verdict(STATUS_INVALID, ("region",), f'"{text}" is not one of the regions: {", ".join(vocab.regions)}.')
    return COMPLETE


def _validate_cluster(value: Any, profile: Mapping[str, Any], vocab: Vocabulary) -> Verdict:
    code = _text((_mapping(value) or {}).get("code"))
    if not code:
        return Verdict(STATUS_PARTIAL, ("code",), f"{_label_of('P05', vocab)} has not been confirmed yet.")
    if vocab.taxonomy.by_code(code) is None:
        return Verdict(STATUS_INVALID, ("code",), f'"{code}" is not one of the clusters.')
    return COMPLETE


def _unit_words(unit: str) -> list[str]:
    """Lower case words with a plural "s" dropped: "Working Days" and "working day" read the same."""
    return [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in unit.casefold().split()]


def same_unit(a: str, b: str) -> bool:
    """Spec 27 §3.6 R1: units match regardless of case, singular or plural ("1 working day per role" vs
    "3 working days per role"); "hours" against "days" still differ."""
    return _unit_words(a) == _unit_words(b)


def _validate_target(value: Any, profile: Mapping[str, Any], vocab: Vocabulary) -> Verdict:
    container = _mapping(value) or {}
    unit = _text(container.get("unit"))
    missing = tuple(k for k, v in (("value", _text(container.get("value"))), ("unit", unit)) if not v)
    if missing:
        return Verdict(STATUS_PARTIAL, missing, f"{_label_of('P13', vocab)} still needs: {', '.join(missing)}.")
    process = _mapping(profile.get("process")) or {}
    base_unit = _text((_mapping(process.get("baseline_metric")) or {}).get("unit"))
    if base_unit and not same_unit(unit, base_unit):
        return Verdict(
            STATUS_INVALID,
            ("unit",),
            f'The target is in "{unit}" but the time today is in "{base_unit}"; both need the same unit.',
        )
    return COMPLETE


def _validate_variation(value: Any, profile: Mapping[str, Any], vocab: Vocabulary) -> Verdict:
    label = _label_of("P14", vocab)
    container = _mapping(value) or {}
    same = _text(container.get("same")).casefold()
    if not same:
        return Verdict(STATUS_PARTIAL, ("same",), f"{label} has not been answered yet.")
    if same not in VARIATION_ANSWERS:
        return Verdict(STATUS_INVALID, ("same",), f"{label} must be yes, no or partly.")
    if same != "yes" and not _text(container.get("differences")):
        return Verdict(STATUS_PARTIAL, ("differences",), f"{label} still needs: differences.")
    return COMPLETE


def _validate_decision(value: Any, profile: Mapping[str, Any], vocab: Vocabulary) -> Verdict:
    label = _label_of("S13", vocab)
    container = _mapping(value) or {}
    kind = _text(container.get("kind")).casefold()
    if not kind:
        return Verdict(STATUS_PARTIAL, ("kind",), f"{label} has not been answered yet.")
    if kind not in DECISION_KINDS:
        return Verdict(STATUS_INVALID, ("kind",), f"{label} must be rules, judgement or a mix.")
    if not _text(container.get("evidence")):
        return Verdict(STATUS_PARTIAL, ("evidence",), f"{label} still needs: the expert's words.")
    return COMPLETE


WRITTEN_VALUES = ("yes", "partly", "no")


def _validate_criteria(value: Any, profile: Mapping[str, Any], vocab: Vocabulary) -> Verdict:
    """S14: `basis` completes it; `written`, when given, is yes, partly or no (spec 12 §3.13)."""
    label = _label_of("S14", vocab)
    container = _mapping(value) or {}
    written = _text(container.get("written")).casefold()
    if written and written not in WRITTEN_VALUES:
        return Verdict(STATUS_INVALID, ("written",), f"{label}: written must be yes, partly or no.")
    if not _text(container.get("basis")):
        return Verdict(STATUS_PARTIAL, ("basis",), f"{label} has not been answered yet.")
    return COMPLETE


def _out_of_range(count: int) -> Verdict:
    return Verdict(
        STATUS_INVALID,
        ("substep_count",),
        f"{count} steps is outside {MIN_STEPS}–{MAX_STEPS}: group them into at most {MAX_STEPS} main steps.",
    )


def _validate_step_count(value: Any, profile: Mapping[str, Any], vocab: Vocabulary) -> Verdict:
    label = _label_of("P16", vocab)
    if isinstance(value, int) and not isinstance(value, bool):
        return COMPLETE if MIN_STEPS <= value <= MAX_STEPS else _out_of_range(value)
    if value is None:
        rejected = (_mapping(profile.get("process")) or {}).get(REJECTED_COUNT_KEY)
        if isinstance(rejected, int) and not isinstance(rejected, bool):
            return _out_of_range(rejected)
        return Verdict(STATUS_PARTIAL, ("substep_count",), f"{label} has not been answered yet.")
    return Verdict(
        STATUS_PARTIAL, ("substep_count",), f"{label} must be a whole number from {MIN_STEPS} to {MAX_STEPS}."
    )


# --- The registry (§3.4). Declaration order is ask order. ---------------------------------------

PROFILE_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec(
        id="P01",
        key="department",
        label="Department",
        kind="text",
        phase=PHASE_CONTEXT,
        weight=1,
        question="Which department are you in?",
        rule="A unit or department name, not a job title.",
        propose=False,
    ),
    FieldSpec(
        id="P02",
        key="user_function",
        label="Role",
        kind="text",
        phase=PHASE_CONTEXT,
        weight=1,
        question="What is your own role in that department?",
        rule="The expert's own role in the department, never a person's name.",
        propose=False,
    ),
    FieldSpec(
        id="P03",
        key="region",
        label="Region",
        kind="text",
        phase=PHASE_CONTEXT,
        weight=1,
        question="Which region do you work in?",
        rule="One of the company's configured regions.",
        validator=_validate_region,
        propose=False,
    ),
    FieldSpec(
        id="P04",
        key="process.name",
        label="Process name",
        kind="text",
        phase=PHASE_FIND,
        weight=1,
        question="Thinking about a normal week, which piece of work comes round again and again and takes you the most time?",
        rule=(
            "A process, judged on five signals (several roles, several systems, a trigger and an outcome, "
            "recurring, someone else depends on it), named in the expert's own words. Write it only once they agree."
        ),
    ),
    FieldSpec(
        id="P05",
        key="process.cluster",
        label="Cluster",
        kind="object",
        phase=PHASE_FIND,
        weight=1,
        question="",
        rule=(
            "Set only by code, from a confirmed proposal, a cluster the expert named or the picker. "
            "Never from a model or a document."
        ),
        subfields=(
            SubFieldSpec("code", "text"),
            SubFieldSpec("name", "text", required=False),
            SubFieldSpec("decided_by", "text", required=False),
        ),
        validator=_validate_cluster,
        extract=False,
        propose=False,
    ),
    FieldSpec(
        id="P06",
        key="process.trigger",
        label="Trigger",
        kind="text",
        phase=PHASE_BOUNDARIES,
        weight=1,
        question="What starts this process off?",
        rule="A concrete event that starts the process, not only a schedule.",
    ),
    FieldSpec(
        id="P07",
        key="process.end_result",
        label="End result",
        kind="text",
        phase=PHASE_BOUNDARIES,
        weight=1,
        question="What exists at the end that did not exist before?",
        rule="A tangible result or change of state, phrased as a result.",
        group=GROUP_RESULT,
        ask_part="what exists at the end that did not exist before",
    ),
    FieldSpec(
        id="P08",
        key="process.value_at_end",
        label="Who uses the result",
        kind="text",
        phase=PHASE_BOUNDARIES,
        weight=1,
        question="Who uses that result, and what for?",
        rule="Who uses the end result and what for, not a restatement of the result.",
        group=GROUP_RESULT,
        ask_part="who uses it, and what for",
    ),
    FieldSpec(
        id="P09",
        key="process.business_pain",
        label="Business pain",
        kind="text",
        phase=PHASE_BOUNDARIES,
        weight=1,
        question="What hurts most about this process today?",
        rule="If the real pain is in another process, offer to switch to that one before measuring.",
    ),
    FieldSpec(
        id="P10",
        key="process.volume",
        label="Volume",
        kind="object",
        phase=PHASE_MEASURE,
        weight=1,
        question="How often does this process run?",
        rule="A whole-number count and a period; keep the expert's own wording in raw.",
        subfields=(
            SubFieldSpec("count", "number"),
            SubFieldSpec("period", "text"),
            SubFieldSpec("raw", "text", required=False),
        ),
        complete_when=(("count", "period"), ("raw",)),
    ),
    FieldSpec(
        id="P11",
        key="process.process_owner",
        label="Process owner",
        kind="object",
        phase=PHASE_MEASURE,
        weight=1,
        question="Who owns this process end to end?",
        rule='A role, never a name. "Nobody owns it" is an answer: set none_identified.',
        subfields=(
            SubFieldSpec("role", "text"),
            SubFieldSpec("none_identified", "bool", required=False),
        ),
        complete_when=(("role",), ("none_identified",)),
    ),
    FieldSpec(
        id="P12",
        key="process.baseline_metric",
        label="Time today",
        kind="object",
        phase=PHASE_MEASURE,
        weight=2,
        question="How would you measure how this process performs today?",
        rule="A value with a unit if they have one, else their own description. Mark estimates as estimated.",
        subfields=(
            SubFieldSpec("value", "text"),
            SubFieldSpec("unit", "text"),
            SubFieldSpec("qualitative", "text", required=False),
            SubFieldSpec("estimated", "bool", required=False),
        ),
        complete_when=(("value", "unit"), ("qualitative",)),
    ),
    FieldSpec(
        id="P13",
        key="process.target_metric",
        label="Target",
        kind="object",
        phase=PHASE_MEASURE,
        weight=2,
        question="Where would that number need to get to?",
        rule="A value and a unit, in the same unit as the time today.",
        subfields=(SubFieldSpec("value", "text"), SubFieldSpec("unit", "text")),
        validator=_validate_target,
        max_asks=1,
        optional=True,
    ),
    FieldSpec(
        id="P14",
        key="process.variation",
        label="Same way everywhere",
        kind="object",
        phase=PHASE_MEASURE,
        weight=1,
        question="Do other teams or regions do this the same way? A yes or no is enough.",
        rule="same is yes, no or partly; for no or partly, say what differs.",
        subfields=(SubFieldSpec("same", "text"), SubFieldSpec("differences", "text", required=False)),
        validator=_validate_variation,
        group=GROUP_QUICK,
        ask_part="whether other teams or regions do it the same way (yes or no)",
    ),
    FieldSpec(
        id="P15",
        key="process.sensitive_data",
        label="Sensitive data or regulation",
        kind="object_list",
        phase=PHASE_MEASURE,
        weight=1,
        question="Does it involve personal or sensitive data, or a regulation? A yes or no is enough.",
        rule=(
            'Personal or sensitive data, or a named regulation. "None" is an answer: record the none row. After a '
            "bare yes, ask which, with 2 or 3 examples typical for this work, offered for the expert to accept."
        ),
        subfields=(SubFieldSpec("item", "text"), SubFieldSpec("detail", "text", required=False)),
        group=GROUP_QUICK,
        ask_part="whether it involves personal or sensitive data or a regulation (yes or no)",
    ),
    FieldSpec(
        id="P16",
        key="process.substep_count",
        label="Number of main steps",
        kind="number",
        phase=PHASE_STEP_COUNT,
        weight=1,
        question="List the main steps in order, 2 to 6.",
        rule="A whole number from 2 to 6. Outside the range, help the expert group the steps.",
        validator=_validate_step_count,
        propose=False,
    ),
)

APPLIES_DECISION_JUDGEMENT = "decision_judgement"
APPLIES_WHEN_VALUES = frozenset({APPLIES_DECISION_JUDGEMENT})
JUDGEMENT_KINDS = ("judgement", "mix")


def check_registry(specs: tuple[FieldSpec, ...]) -> None:
    """Import-time checks the dataclass cannot express (spec 12 §3.13: `applies_when` values)."""
    for spec in specs:
        if spec.applies_when is not None and spec.applies_when not in APPLIES_WHEN_VALUES:
            raise ValueError(f"{spec.id}: unknown applies_when {spec.applies_when!r}")


STEP_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec(
        id="S01",
        key="name",
        label="Step name",
        kind="text",
        phase=PHASE_STEPS,
        weight=1,
        question="What would you call this step?",
        rule="A step: not a single click and not a whole phase.",
        group=GROUP_NAMES,
    ),
    FieldSpec(
        id="S02",
        key="goal",
        label="Goal",
        kind="text",
        phase=PHASE_STEPS,
        weight=1,
        question="What has to be true for this step to be done?",
        rule="One sentence, phrased as a result rather than an activity. Proposed by code, never asked.",
        group=GROUP_C,
        ask_part="what has to be true for the step to be done",
        max_asks=2,
    ),
    FieldSpec(
        id="S03",
        key="activities",
        label="Activities",
        kind="list",
        phase=PHASE_STEPS,
        weight=1,
        question="What do you actually do in this step?",
        rule="Two to five activities. More than five suggests the step should be split.",
        max_items=ACTIVITIES_SOFT_MAX,
        group=GROUP_A,
        ask_part="what you do",
        max_asks=2,
    ),
    FieldSpec(
        id="S04",
        key="roles",
        label="Roles involved",
        kind="object_list",
        phase=PHASE_STEPS,
        weight=1,
        question="Who else is involved, and what do they contribute?",
        rule='Roles, never names. "Nobody else" is an answer: record the none row.',
        subfields=(SubFieldSpec("role", "text"), SubFieldSpec("contribution", "text", required=False)),
        group=GROUP_A,
        ask_part="who else is involved",
        max_asks=2,
    ),
    FieldSpec(
        id="S05",
        key="owner",
        label="Step owner",
        kind="text",
        phase=PHASE_STEPS,
        weight=1,
        question="Who is accountable for this step?",
        rule="Exactly one role, never a name. Proposed by code (the expert's role), never asked.",
        group=GROUP_C,
        ask_part="who is accountable for the step",
        max_asks=2,
    ),
    FieldSpec(
        id="S06",
        key="systems",
        label="Systems",
        kind="list",
        phase=PHASE_STEPS,
        weight=1,
        question="Which systems or tools do you use here?",
        rule="Systems, tools or documents, by their common name.",
        group=GROUP_A,
        ask_part="which systems and files you use",
        max_asks=2,
    ),
    FieldSpec(
        id="S07",
        key="data",
        label="Data in and out",
        kind="object",
        phase=PHASE_STEPS,
        weight=1,
        question="What information goes in, and what comes out?",
        rule="Both the inputs and the outputs are needed.",
        subfields=(SubFieldSpec("inputs", "list"), SubFieldSpec("outputs", "list")),
        group=GROUP_A,
        ask_part="what comes in and what goes out",
        max_asks=2,
    ),
    FieldSpec(
        id="S08",
        key="effort",
        label="Effort",
        kind="object",
        phase=PHASE_STEPS,
        weight=1,
        question="How long does this step take, and how often?",
        rule="Both a duration and a frequency: one without the other says nothing. Asked once for all steps.",
        subfields=(SubFieldSpec("duration", "text"), SubFieldSpec("frequency", "text")),
        group=GROUP_EFFORT,
        ask_part="how long it takes and how often",
        max_asks=2,
    ),
    FieldSpec(
        id="S09",
        key="pain_points",
        label="Pain points",
        kind="list",
        phase=PHASE_STEPS,
        weight=1,
        question="What is annoying or slow about this step?",
        rule="Keep the expert's own words.",
        group=GROUP_A,
        ask_part="what is annoying or slow",
        max_asks=2,
    ),
    FieldSpec(
        id="S10",
        key="approvals",
        label="Approvals",
        kind="object_list",
        phase=PHASE_STEPS,
        weight=1,
        question="Does anything here need an approval or sign-off?",
        rule='Ask directly, never infer. "No approvals" is an answer: record the none row.',
        subfields=(SubFieldSpec("approver_role", "text"), SubFieldSpec("waiting_time", "text", required=False)),
        group=GROUP_B,
        ask_part="any sign-off needed",
        max_asks=1,
        optional=True,
    ),
    FieldSpec(
        id="S11",
        key="exceptions",
        label="Exceptions",
        kind="object_list",
        phase=PHASE_STEPS,
        weight=1,
        question="What goes wrong here, and where do you end up when it does?",
        rule='loops_back_to is a step number, never text. "Nothing goes wrong" is an answer: record the none row.',
        subfields=(SubFieldSpec("description", "text"), SubFieldSpec("loops_back_to", "number", required=False)),
        group=GROUP_B,
        ask_part="anything that often goes wrong",
        max_asks=1,
        optional=True,
    ),
    FieldSpec(
        id="S12",
        key="handover",
        label="Hand-over",
        kind="text",
        phase=PHASE_STEPS,
        weight=0,
        question="How does the work get to whoever does the next step?",
        rule="Optional and unscored: asked once in the optional question of the step, never blocks.",
        group=GROUP_B,
        ask_part="anything special about passing it on",
        max_asks=1,
        optional=True,
    ),
    FieldSpec(
        id="S13",
        key="decision_type",
        label="Rules or judgement",
        kind="object",
        phase=PHASE_STEPS,
        weight=1,
        question="Is this step mostly fixed rules, judgement, or a mix?",
        rule='kind is "rules", "judgement" or "mix"; evidence is the expert\'s own words, copied.',
        subfields=(SubFieldSpec("kind", "text"), SubFieldSpec("evidence", "text")),
        validator=_validate_decision,
        group=GROUP_A,
        ask_part="whether it runs on fixed rules, judgement or a mix",
        max_asks=2,
    ),
    FieldSpec(
        id="S14",
        key="decision_criteria",
        label="Decision criteria",
        kind="object",
        phase=PHASE_STEPS,
        weight=0,
        question="What do you base that decision on, who sets those criteria, and are they written down?",
        rule=(
            "basis is what the decision is based on, in the expert's words; set_by is the role that sets the "
            "criteria; written is yes, partly or no; varies is what changes from case to case or person to person."
        ),
        subfields=(
            SubFieldSpec("basis", "text"),
            SubFieldSpec("set_by", "text", required=False),
            SubFieldSpec("written", "text", required=False),
            SubFieldSpec("varies", "text", required=False),
        ),
        validator=_validate_criteria,
        group=GROUP_B,
        ask_part="what the decision is based on, who sets the criteria and whether they are written down",
        max_asks=1,
        optional=True,
        applies_when=APPLIES_DECISION_JUDGEMENT,
    ),
)

check_registry((*PROFILE_SPECS, *STEP_SPECS))


def field_applies(spec: FieldSpec, row: Mapping[str, Any]) -> bool:
    """Whether a step field applies to this row (spec 12 §3.13): S14 only for a judgement or mix step."""
    if spec.applies_when is None:
        return True
    decision = _mapping(row.get("decision_type")) or {}
    return _text(decision.get("kind")).casefold() in JUDGEMENT_KINDS


def step_specs_shown(rows: Sequence[Mapping[str, Any]]) -> list[FieldSpec]:
    """Step fields a step table shows: a conditional field (S14) only when at least one row it applies to."""
    return [s for s in STEP_SPECS if s.applies_when is None or any(field_applies(s, r) for r in rows)]


def step_specs_in_group(group: str) -> list[FieldSpec]:
    """The step fields asked together in `group`, in registry order (spec 14 §3.19)."""
    return [s for s in STEP_SPECS if s.group == group]


#: Steps assumed by the progress bar while P16 is not known (spec 14 §3.20 O4, amended 2026-11-21).
PROGRESS_DEFAULT_STEPS = 4


def progress_step_specs() -> list[FieldSpec]:
    """Scored step fields the expert is asked and that are not optional: their share of the progress bar."""
    return [s for s in STEP_SPECS if s.weight > 0 and s.group != GROUP_C and not s.optional]


# --- Derived roll-ups (D01–D02) -----------------------------------------------------------------


def _dedupe(values: list[str]) -> list[str]:
    """Case-insensitive de-duplication; the first spelling wins."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            out.append(text)
    return out


def _steps(profile: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    process = _mapping(profile.get("process")) or {}
    rows = [_mapping(r) for r in _list(process.get("substeps")) or []]
    return [r for r in rows if r is not None]


def _all_roles(profile: Mapping[str, Any]) -> list[str]:
    roles: list[str] = []
    for step in _steps(profile):
        for entry in _list(step.get("roles")) or []:
            row = _mapping(entry)
            if row is not None and not is_none_row(row):
                roles.append(_text(row.get("role")))
    return _dedupe(roles)


def _all_tools(profile: Mapping[str, Any]) -> list[str]:
    tools: list[str] = []
    for step in _steps(profile):
        tools.extend(_text(s) for s in _list(step.get("systems")) or [])
    return _dedupe(tools)


DERIVED_SPECS: tuple[DerivedSpec, ...] = (
    DerivedSpec("D01", "process.all_roles", "All roles", "process.substeps[*].roles[*].role", _all_roles),
    DerivedSpec("D02", "process.all_tools", "All systems", "process.substeps[*].systems[*]", _all_tools),
)


def recompute_derived(profile: Mapping[str, Any]) -> dict[str, list[str]]:
    """Rebuild every roll-up from scratch, so a role removed from its step disappears."""
    return {d.key: d.reducer(profile) for d in DERIVED_SPECS}


# --- Points (computed, never typed) -------------------------------------------------------------

PROCESS_POINTS: int = sum(s.weight for s in PROFILE_SPECS)
STEP_POINTS: int = sum(s.weight for s in STEP_SPECS)


def total_points_for(substep_count: int | None) -> int:
    """Score denominator: process points plus step points per declared step, clamped to 0–6."""
    n = max(0, min(substep_count or 0, MAX_STEPS))
    return PROCESS_POINTS + STEP_POINTS * n


# --- Lookups and addresses ----------------------------------------------------------------------

_STEP_CELL = re.compile(r"^process\.substeps\[(\d+)\]\.([a-z_]+)$")
STEP_KEY_TEMPLATE = "process.substeps[{index}].{leaf}"


def spec_by_id(field_id: str) -> FieldSpec | None:
    return next((s for s in (*PROFILE_SPECS, *STEP_SPECS) if s.id == field_id), None)


def step_spec_by_leaf(leaf: str) -> FieldSpec | None:
    return next((s for s in STEP_SPECS if s.key == leaf), None)


def step_cell_key(index: int, leaf: str) -> str:
    """`process.substeps[2].systems`. `index` is 1-based."""
    return STEP_KEY_TEMPLATE.format(index=index, leaf=leaf)


def step_key_template(leaf: str) -> str:
    """`process.substeps[i].<leaf>`: the form shown to the model."""
    return STEP_KEY_TEMPLATE.format(index="i", leaf=leaf)


def resolve_address(key: str) -> tuple[FieldSpec, int | None] | None:
    """Resolve a dotted key, a 1-based step cell or a bare process leaf to `(spec, step index)`.

    Bare leaves resolve only to process fields: `name` is P04, never S01.
    """
    for spec in PROFILE_SPECS:
        if spec.key == key:
            return spec, None
    cell = _STEP_CELL.match(key)
    if cell:
        index = int(cell.group(1))
        spec = step_spec_by_leaf(cell.group(2))
        return (spec, index) if spec is not None and index >= 1 else None
    if "." not in key:
        for spec in PROFILE_SPECS:
            if spec.is_process and spec.leaf == key:
                return spec, None
    return None


def specs_for_phase(phase: str) -> list[FieldSpec]:
    """Process fields collected in `phase`, in ask order."""
    return [s for s in PROFILE_SPECS if s.phase == phase]


def scored_step_specs() -> list[FieldSpec]:
    """Step fields that carry points (S12 does not)."""
    return [s for s in STEP_SPECS if s.weight > 0]


# --- Whitelists (§3.7): filters of the registry, never hand-written lists -----------------------


def extract_keys() -> list[str]:
    """Keys the EXTRACT call may write. No cluster, no flags, no roll-ups, no sidecars, no assent."""
    return [s.key for s in PROFILE_SPECS if s.extract] + [step_key_template(s.key) for s in STEP_SPECS if s.extract]


def proposal_keys() -> list[str]:
    """Keys a document or an idea may propose."""
    return [s.key for s in PROFILE_SPECS if s.propose] + [step_key_template(s.key) for s in STEP_SPECS if s.propose]


def specialist_keys() -> list[str]:
    """Keys a specialist may edit in review (the cluster also has its own route)."""
    return [s.key for s in PROFILE_SPECS] + [step_key_template(s.key) for s in STEP_SPECS]


# --- Rows of object lists -----------------------------------------------------------------------


def required_subfield(spec: FieldSpec) -> str | None:
    """The sub-field that identifies a row (`role`, `approver_role`, `description`, `item`)."""
    if spec.kind != "object_list":
        return None
    return next((sf.key for sf in spec.subfields if sf.required), None)


def lenient_object_rows(spec: FieldSpec, value: Any) -> list[Any] | None:
    """Fold the shapes a model actually emits onto rows; `None` when nothing row-like was given.

    A bare string, a list of strings, a bare mapping and a row whose only unknown key holds text
    all become rows keyed by the required sub-field. The none row passes through. Filtering and
    coercion of the rows stay with the writer (spec 13).
    """
    if isinstance(value, str) or _mapping(value) is not None:
        value = [value]
    items = _list(value)
    if items is None:
        return None
    required = required_subfield(spec)
    declared = {sf.key for sf in spec.subfields}
    rows: list[Any] = []
    for entry in items:
        if is_none_row(entry):
            rows.append(entry)
            continue
        if isinstance(entry, str):
            if required and entry.strip():
                rows.append({required: entry.strip()})
            continue
        row = _mapping(entry)
        if row is None:
            continue
        if required and required not in row:
            unknown = [k for k in row if k not in declared]
            if len(unknown) == 1 and _text(row[unknown[0]]):
                row = {**{k: v for k, v in row.items() if k in declared}, required: row[unknown[0]]}
        rows.append(dict(row))
    return rows


def object_list_shape_hints() -> list[str]:
    """One line per `object_list` field with its row shape, for the EXTRACT and READ_DOCUMENT prompts."""
    hints: list[str] = []
    for spec in (*PROFILE_SPECS, *STEP_SPECS):
        if spec.kind != "object_list":
            continue
        key = spec.key if spec.is_process else step_key_template(spec.key)
        parts = ", ".join(f'"{sf.key}": <{sf.kind}{"" if sf.required else ", optional"}>' for sf in spec.subfields)
        hints.append(
            f'- "{key}" is a list of rows, each {{{parts}}}; "there are none" is [{{"none": true}}]; '
            "never a list of plain strings"
        )
    return hints
