"""The discovery report model: the cover and eleven parts, built by code from the finished session (spec 20 §3.3, F-16).

Why: the expert, the specialists and the PDF must all read the same report, and every word and
number in it must be traceable: figures come from the stored `ValueResult`, levels from
`Readiness`, routes from the catalogue, and a missing answer reads "—" or a note, never invented
text. One broken part must not take the report down, so each part is built on its own and a part
that fails becomes that part with the note "This part could not be built." (F-16.2).
What: `build_report(session, org, vocab, catalogue)` returns a `DiscoveryReport` (wire models in
`app/models/process_discovery_wire.py`, so `export/` can print it without importing this peer);
the display formats live here, once: `format_hours`, `format_share`, `format_date` and
`cell_text` (the step-table cells of Part 4, also for the Excel export of spec 22).
Must not: compute a number (hours are formatted, never summed), call a model, read a clock, do
I/O, show the expert's display name, a message, a transcript or document text (only document
names and the quotes already stored in the profile), or show a euro figure, a cost, hours freed or
a saving while the value method is parked (refinement R5).
Spec 20 §3.3, §4; AC-20.18 to AC-20.31, AC-20.43, AC-20.46 to AC-20.48.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from app.core.config import Organisation, SolutionCatalogue
from app.models.process_discovery_schemas import Assessment, FieldStatus, ReadinessDimension, Session
from app.models.process_discovery_wire import (
    DiscoveryReport,
    FeasibilityPart,
    FieldsPart,
    MapPart,
    QuestionRow,
    ReadinessRow,
    ReportCover,
    ReportField,
    ReportNote,
    ReportPartBase,
    StepColumn,
    StepRow,
    StepsPart,
    SummaryPart,
)
from app.utils.prompt_safety import single_line

from ..domain.field_spec import (
    PROFILE_SPECS,
    STEP_SPECS,
    Vocabulary,
    is_none_row,
    resolve_address,
    step_cell_key,
    step_specs_shown,
)
from ..domain.scope import is_one_off
from ..profile.conflicts import open_conflicts
from ..profile.shapes import as_list, as_mapping, meta_for, normalized_profile, process_of, rows_of
from ..profile.views import field_views
from .questions import LEVEL_WORDS, QUESTION_TEXT
from .readiness import LABELS as DIMENSION_LABELS
from .summary import build_summary

logger = logging.getLogger("app.report")

EMPTY = "—"
MAX_CELL_CHARS = 1500
ELLIPSIS = "…"

TITLES = {
    "summary": "Summary",
    "process": "The process",
    "measures": "Volume and measures",
    "map": "Process map and steps",
    "steps": "Step-by-step AI assessment",
    "feasibility": "AI readiness and feasibility",
}
NUMBERS = {key: i for i, key in enumerate(TITLES, start=1)}

NOT_BUILT = "This part could not be built."
NOT_V2 = "Not assessed with this version of the report; re-run the assessment."
MAX_BULLETS = 5
NOT_MEASURED = "Not measured yet"
UNTITLED = "Untitled process"
NO_OWNER = "No process owner identified"
TASK_NOTE = "This looks like one person's task rather than a process shared by several people."
ONE_OFF_NOTE = "This looks like a one-off project, not recurring work."
MAP_SIMPLIFIED = "Simplified map built from the steps (order and owners only): the AI-drawn map was not available."
MAP_MISSING = "The process map could not be drawn."
STEPS_FAILED = "The step-by-step assessment could not be generated this time. A specialist can run it again."
ROUTE_MISSING = "No recommended route: the step-by-step assessment is not available."
CATALOGUE_NOTE = "Routes come from a placeholder solution list, not the company's real tools."
OPPORTUNITIES_FAILED = "The opportunities could not be generated this time. A specialist can run them again."
OPPORTUNITIES_EMPTY = (
    "No opportunity was found. The analysis looked for steps to remove or standardise, routing and "
    "reminders, re-typing between systems, reading or writing documents, drafting or summarising, "
    "multi-step work an AI agent could do, and screen automation."
)
EURO_PARKED = "Euro value and savings are not shown yet: the method is still being agreed."
READINESS_FOOTER = "A guide to what would make the change easier. Not a verdict."
READINESS_MISSING = "The readiness checklist is not available."
NOTHING_HERE = "Nothing here."

FIT_LABELS = {"automate": "AI can do it", "assist": "AI assists a person", "human": "Stays with people"}
NOT_ASSESSED = "Not assessed"
NO_ROUTE = "No route"
TYPE_LABELS = {
    "eliminate": "Eliminate",
    "standardise": "Standardise",
    "workflow": "Workflow",
    "integration": "Integration",
    "document_ai": "Document AI",
    "ai_assistant": "AI assistant",
    "ai_agent": "AI agent",
    "rpa": "RPA",
}
#: The question each readiness dimension answers (product spec F-15).
QUESTIONS = {
    "defined": "Clear trigger, result, owner, and a goal for every step?",
    "standard": "Done the same way across teams and regions? Exceptions the minority?",
    "data": "Are the inputs digital, structured or readable documents?",
    "systems": "Are the systems known, with an export or an API?",
    "rules": "Are decisions fixed rules, or judgement that can be explained?",
    "risk_size": "Enough hours to be worth the effort? Sensitive data or regulation that needs a human check?",
}
GAP_STATUSES = ("partial", "invalid", "empty", "proposed", "deferred", "given_up", "skipped")
GAP_WORDS = {
    "partial": "Partly answered",
    "invalid": "Not valid",
    "empty": "Not answered",
    "proposed": "Proposed from a document, not confirmed",
    "deferred": "Deferred",
    "given_up": "Given up after several questions",
    "skipped": "Skipped",
}
PART2_FIELDS = ("P06", "P07", "P08", "P09", "P11", "P05")
PART3_FIELDS = ("P10", "P12", "P13", "P14", "P15")

# --- display formats -----------------------------------------------------------------------------


def format_hours(hours: float | None) -> str:
    """Whole hours with "h" ("342 h"); "—" when there is no number."""
    return EMPTY if hours is None else f"{round(hours):,} h"


def format_share(share: float | None) -> str:
    """A share as a whole percent ("68%")."""
    return EMPTY if share is None else f"{round(share * 100)}%"


def format_date(iso: str | None) -> str:
    """An ISO time as the UTC day, "20 November 2026"; "—" when unreadable."""
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d %B %Y").lstrip("0")
    except ValueError:
        return EMPTY


def _cap(text: str, limit: int = MAX_CELL_CHARS) -> str:
    return text if len(text) <= limit else text[: max(limit - len(ELLIPSIS), 0)] + ELLIPSIS


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") and not isinstance(value, (dict, list)) else ""


def _items(value: Any) -> list[str]:
    return [t for t in (_text(v) for v in as_list(value) or []) if t]


def _row(leaf: str, row: Mapping[str, Any]) -> str:
    if leaf == "roles":
        role, contribution = _text(row.get("role")), _text(row.get("contribution"))
        return f"{role} ({contribution})" if role and contribution else role
    if leaf == "approvals":
        role, wait = _text(row.get("approver_role")), _text(row.get("waiting_time"))
        return f"{role} (waits {wait})" if role and wait else role
    if leaf == "exceptions":
        text, back = _text(row.get("description")), row.get("loops_back_to")
        return f"{text} → back to step {back}" if text and isinstance(back, int) else text
    return "; ".join(t for t in (_text(v) for v in row.values()) if t)


def _leaf_text(leaf: str, value: Any) -> str:
    rows = as_list(value)
    if rows is not None and rows and all(isinstance(r, Mapping) for r in rows):
        if any(is_none_row(r) for r in rows):
            return "None"
        return "; ".join(t for t in (_row(leaf, r) for r in rows) if t)
    if rows is not None:
        return "; ".join(_items(rows))
    obj = as_mapping(value)
    if obj is None:
        return _text(value)
    if leaf == "data":
        inputs, outputs = "; ".join(_items(obj.get("inputs"))), "; ".join(_items(obj.get("outputs")))
        return ". ".join(p for p in (f"In: {inputs}" if inputs else "", f"Out: {outputs}" if outputs else "") if p)
    if leaf == "effort":
        return ", ".join(t for t in (_text(obj.get("duration")), _text(obj.get("frequency"))) if t)
    if leaf == "decision_criteria":  # S14 (spec 12 §3.13): "Based on: …; set by …; not written down; varies: …"
        written = {"yes": "written down", "partly": "partly written down", "no": "not written down"}
        parts = [
            f"Based on: {basis}" if (basis := _text(obj.get("basis"))) else "",
            f"set by {set_by}" if (set_by := _text(obj.get("set_by"))) else "",
            written.get(_text(obj.get("written")).casefold(), ""),
            f"varies: {varies}" if (varies := _text(obj.get("varies"))) else "",
        ]
        return "; ".join(p for p in parts if p)
    if leaf == "decision_type":  # S13 (spec 20 §3.3, short step walk): "Mix: <the expert's words>"
        kind, evidence = _text(obj.get("kind")).capitalize(), _text(obj.get("evidence"))
        return f"{kind}: {evidence}" if kind and evidence else kind or evidence
    return "; ".join(t for t in (_text(v) for v in obj.values()) if t)


def cell_text(leaf: str, value: Any, *, skipped: bool, proposed: bool) -> str:
    """One step-table cell as shown everywhere (spec 20 §3.3): "—", "— (skipped)", "(proposed, not confirmed)"."""
    text = _leaf_text(leaf, value)
    if not text:
        return f"{EMPTY} (skipped)" if skipped else EMPTY
    return _cap(text + (" (proposed, not confirmed)" if proposed else ""))


# --- helpers --------------------------------------------------------------------------------------


def _status(value: Any) -> FieldStatus | None:
    return FieldStatus(value) if value in FieldStatus._value2member_map_ else None


def _note(kind: str, text: str) -> ReportNote:
    return ReportNote(kind=kind, text=text)  # pyright: ignore[reportArgumentType]


def _build[P: ReportPartBase](cls: type[P], key: str, fn: Callable[[], P]) -> P:
    """A part built on its own: any error becomes that part with the "could not be built" note."""
    try:
        return fn()
    except Exception as exc:  # F-16.2: a part fails on its own
        logger.error("report_part_failed", extra={"part": key, "error": type(exc).__name__})
        return cls(number=NUMBERS[key], title=TITLES[key], note=_note("error", NOT_BUILT))


def _step_range(steps: Sequence[int]) -> str:
    ordered = sorted(dict.fromkeys(steps))
    if len(ordered) > 1 and ordered == list(range(ordered[0], ordered[-1] + 1)):
        return f"{ordered[0]}–{ordered[-1]}"
    return ", ".join(str(s) for s in ordered)


def steps_label(steps: Sequence[int], names: Mapping[int, str], *, with_names: bool = True) -> str:
    """ "Steps 1–2: Collect site spreadsheets, Consolidate into the master file", or "Whole process"."""
    if not steps:
        return "Whole process"
    head = f"{'Step' if len(set(steps)) == 1 else 'Steps'} {_step_range(steps)}"
    if not with_names:
        return head
    listed = ", ".join(n for n in (names.get(s, "") for s in sorted(dict.fromkeys(steps))) if n)
    return f"{head}: {listed}" if listed else head


def _evidence_label(source: str | None, key: str, profile: Mapping[str, Any], docs: Mapping[str, str]) -> str:
    if source == "document":
        doc_id = (meta_for(profile, key) or {}).get("documentId") if key else None
        name = docs.get(doc_id) if isinstance(doc_id, str) else None
        return f"from {name}" if name else "from a document"
    if source == "specialist":
        return "a specialist's words"
    return "the expert's words"


class _Ctx:
    """What every part reads, prepared once."""

    def __init__(self, session: Session, org: Organisation, vocab: Vocabulary, catalogue: SolutionCatalogue):
        self.session, self.org, self.vocab, self.catalogue = session, org, vocab, catalogue
        self.profile = normalized_profile(session.profile.model_dump(mode="json", by_alias=True))
        self.process = process_of(self.profile)
        self.rows = rows_of(self.profile)
        self.names = {i: _text(r.get("name")) for i, r in enumerate(self.rows, start=1)}
        self.docs = {d.id: d.name for d in session.documents}
        self.assessment: Assessment | None = session.assessment
        a = self.assessment
        self.outcomes: dict[str, str] = {str(k): str(v) for k, v in a.outcomes.items()} if a is not None else {}
        self.value = a.value if a is not None else None
        self.hours = {s.step: s.hours_per_year for s in self.value.steps} if self.value is not None else {}
        self.views = {
            v["key"]: v
            for v in field_views(
                self.profile,
                counters=session.counters.model_dump(mode="json"),
                vocab=vocab,
                documents=[{"id": d.id, "name": d.name} for d in session.documents],
            )
        }

    def spec_label(self, field_id: str) -> str:
        spec = next(s for s in (*PROFILE_SPECS, *STEP_SPECS) if s.id == field_id)
        return self.vocab.label(spec)

    def key_label(self, key: str) -> str:
        resolved = resolve_address(key)
        if resolved is None:
            return key
        spec, index = resolved
        label = self.vocab.label(spec)
        return f"{label} of step {index}" if index else label

    def route_name(self, route_id: str | None) -> str:
        solution = self.catalogue.get(route_id) if route_id else None
        return solution.name if solution is not None else NO_ROUTE

    def field(self, field_id: str, value: str) -> ReportField:
        spec = next(s for s in PROFILE_SPECS if s.id == field_id)
        view = self.views.get(spec.key, {})
        return ReportField(key=spec.key, label=self.vocab.label(spec), value=value, status=_status(view.get("status")),
                           source=view.get("source"), quote=view.get("quote"))  # fmt: skip


# --- the parts --------------------------------------------------------------------------------------


def _owner(process: Mapping[str, Any]) -> str:
    owner = as_mapping(process.get("process_owner")) or {}
    if owner.get("none_identified") is True:
        return NO_OWNER
    return _text(owner.get("role")) or EMPTY


def _cluster(c: _Ctx) -> tuple[str, str, str]:
    ref = as_mapping(c.process.get("cluster")) or {}
    code = _text(ref.get("code"))
    known = c.vocab.taxonomy.by_code(code)
    name = known.name if known else _text(ref.get("name"))
    return code, name, known.description if known else ""


def _cover(c: _Ctx) -> ReportCover:
    code, name, _ = _cluster(c)
    status = c.session.report.status if c.session.report else "mapped"
    return ReportCover(
        product_name=c.org.product_name,
        company_name=c.org.company_name,
        process_name=_text(c.process.get("name")) or UNTITLED,
        department=_text(c.profile.get("department")) or EMPTY,
        cluster=" · ".join(p for p in (code, name) if p) or EMPTY,
        region=_text(c.profile.get("region")) or EMPTY,
        owner=_owner(c.process),
        date=format_date(c.session.finished_at),
        status="Validated by IT" if status == "validated" else "Mapped",
    )


def _dimensions(c: _Ctx) -> list[ReadinessDimension]:
    a = c.assessment
    return list(a.readiness.dimensions) if a is not None and a.readiness is not None else []


def _process(c: _Ctx) -> FieldsPart:
    values = {
        "P06": _text(c.process.get("trigger")),
        "P07": _text(c.process.get("end_result")),
        "P08": _text(c.process.get("value_at_end")),
        "P09": _text(c.process.get("business_pain")),
        "P11": _owner(c.process),
    }
    _, name, description = _cluster(c)
    values["P05"] = f"{name}: {description}" if name and description else name
    notes = []
    verdict = c.session.scope.verdict
    if verdict is not None and verdict.verdict == "task":
        notes.append(_note("task", TASK_NOTE))
    if verdict is not None and is_one_off(verdict.model_dump(mode="json")):
        notes.append(_note("one_off", ONE_OFF_NOTE))
    return FieldsPart(
        number=NUMBERS["process"], title=TITLES["process"],
        fields=[c.field(i, values[i] or EMPTY) for i in PART2_FIELDS], notes=notes,
        note=notes[0] if notes else None,
    )  # fmt: skip


def _measures(c: _Ctx) -> FieldsPart:
    p = c.process
    volume = as_mapping(p.get("volume")) or {}
    count, period = volume.get("count"), _text(volume.get("period"))
    vol = f"{count} per {period}" if isinstance(count, int) and period else _text(volume.get("raw"))
    base = as_mapping(p.get("baseline_metric")) or {}
    baseline = " ".join(t for t in (_text(base.get("value")), _text(base.get("unit"))) if t)
    if baseline and base.get("estimated") is True:
        baseline += " (estimated)"
    if baseline and _text(base.get("qualitative")):
        baseline += f" — {_text(base.get('qualitative'))}"
    target = as_mapping(p.get("target_metric")) or {}
    goal = " ".join(t for t in (_text(target.get("value")), _text(target.get("unit"))) if t)
    variation = as_mapping(p.get("variation")) or {}
    same, differences = _text(variation.get("same")), _text(variation.get("differences"))
    variation_text = " — ".join(t for t in (same.capitalize(), differences) if t)
    sensitive_rows = [r for r in (as_list(p.get("sensitive_data")) or []) if isinstance(r, Mapping)]
    if any(is_none_row(r) for r in sensitive_rows):
        sensitive = "None"
    else:
        sensitive = "; ".join(
            f"{_text(r.get('item'))} ({_text(r.get('detail'))})" if _text(r.get("detail")) else _text(r.get("item"))
            for r in sensitive_rows
            if _text(r.get("item"))
        )
    values = {"P10": vol, "P12": baseline, "P13": goal, "P14": variation_text, "P15": sensitive}
    return FieldsPart(
        number=NUMBERS["measures"], title=TITLES["measures"],
        fields=[c.field(i, values[i] or NOT_MEASURED) for i in PART3_FIELDS],
    )  # fmt: skip


def _map(c: _Ctx) -> MapPart:
    a = c.assessment
    diagram = a.diagram if a is not None else None
    systems: dict[str, str] = {}
    for row in c.rows:
        for system in _items(row.get("systems")):
            systems.setdefault(system.casefold(), system)
    columns = []
    shown = step_specs_shown(c.rows)
    for index, row in enumerate(c.rows, start=1):
        skipped = set(_items(row.get("__skipped")))
        cells = []
        for spec in shown:
            key = step_cell_key(index, spec.key)
            view = c.views.get(key, {})
            status = view.get("status")
            text = cell_text(spec.key, row.get(spec.key), skipped=spec.key in skipped or status == "skipped",
                             proposed=status == "proposed")  # fmt: skip
            cells.append(ReportField(key=key, label=c.vocab.label(spec), value=text, status=_status(status),
                                     source=view.get("source"), quote=view.get("quote")))  # fmt: skip
        columns.append(StepColumn(number=index, name=c.names.get(index) or f"Step {index}", cells=cells))
    note = caption = None
    if diagram is None:
        note = _note("missing", MAP_MISSING)
    elif diagram.simplified:
        caption = MAP_SIMPLIFIED
    return MapPart(
        number=NUMBERS["map"], title=TITLES["map"], note=note, diagram=diagram, caption=caption,
        process_name=_text(c.process.get("name")) or UNTITLED, systems=list(systems.values()), columns=columns,
        row_labels=[c.vocab.label(s) for s in shown],
    )  # fmt: skip


def _steps_available(c: _Ctx) -> bool:
    a = c.assessment
    return a is not None and a.step_assessment is not None and c.outcomes.get("steps") != "failed"


def _catalogue_note(c: _Ctx) -> str | None:
    return CATALOGUE_NOTE if c.catalogue.placeholder else None


def _steps(c: _Ctx) -> StepsPart:
    a = c.assessment
    head: dict[str, Any] = {"number": NUMBERS["steps"], "title": TITLES["steps"], "catalogue_note": _catalogue_note(c)}
    if not _steps_available(c) or a is None or a.step_assessment is None:
        return StepsPart(**head, note=_note("failed", STEPS_FAILED))
    ratings = {r.step: r for r in a.step_assessment.steps}
    fits = {f.step: f for f in a.questions.steps} if a.questions is not None else {}
    rows = []
    for number in range(1, len(c.rows) + 1):
        r = ratings.get(number)
        rows.append(StepRow(
            number=number, name=c.names.get(number) or (r.name if r else ""),
            hours=format_hours(c.hours.get(number)),
            fit=r.fit if r else None, fit_label=FIT_LABELS.get(r.fit or "", NOT_ASSESSED) if r else NOT_ASSESSED,
            route_id=r.route_id if r else None, route_name=c.route_name(r.route_id if r else None),
            route_reason=r.route_reason if r else "", reason=r.reason if r else "",
            evidence=r.evidence if r else "",
            evidence_label=_evidence_label(r.evidence_source, r.evidence_key, c.profile, c.docs)
            if r and r.evidence else "",
            level=fits[number].level if number in fits else None,
            level_label=LEVEL_WORDS["q1"][fits[number].level] if number in fits else "",
            because=list(fits[number].because) if number in fits else [],
        ))  # fmt: skip
    return StepsPart(**head, rows=rows)


def _conflict_text(value: Any) -> str:
    items = as_list(value)
    return single_line("; ".join(str(v) for v in items) if items is not None else str(value or ""), 200)


def _summary(c: _Ctx) -> SummaryPart:
    """Part 1 (spec 27 §3.5)."""
    a = c.assessment
    route = a.step_assessment.route if a is not None and a.step_assessment is not None else None
    questions = a.questions if a is not None and a.step_assessment is not None else None
    ratings = a.step_assessment.steps if a is not None and a.step_assessment is not None else []
    sentences = build_summary(
        c.profile, questions, route, c.value, vocab=c.vocab, ratings=ratings, catalogue=c.catalogue
    )
    note = None if questions is not None else _note("missing", NOT_V2)
    return SummaryPart(number=NUMBERS["summary"], title=TITLES["summary"], note=note, sentences=sentences)


def _readiness_rows(c: _Ctx) -> list[ReadinessRow]:
    return [
        ReadinessRow(key=d.key, label=d.label or DIMENSION_LABELS.get(d.key, d.key), question=QUESTIONS.get(d.key, ""),
                     level=d.level, level_label=d.level.capitalize(), reason=d.reason, to_prepare=d.to_prepare,
                     note=d.note)
        for d in _dimensions(c)
    ]  # fmt: skip


def _gaps_line(c: _Ctx) -> str:
    """The last line of part 6 (spec 27 §3.1 block C): fields missing or given up, open conflicts, sources."""
    labels = [c.key_label(k) for k, v in c.views.items() if v.get("status") in GAP_STATUSES]
    names = {d.id: d.name for d in c.session.documents}
    for x in open_conflicts(c.profile):  # spec 14 §3.17 item 5: open and left conflicts are gaps, with both values
        holder = f'"{names[x.holder_document_id]}"' if x.holder_document_id in names else "the expert"
        offering = f'"{names.get(x.document_id, "a removed document")}"'
        label = c.key_label(x.key) + (f", {x.sub.replace('_', ' ')}" if x.sub else "")
        labels.append(f'{label} (Not settled: {holder} says "{_conflict_text(x.current)}"; '
                      f'{offering} says "{_conflict_text(x.offered)}")')  # fmt: skip
    docs = [d.name for d in c.session.documents]
    gaps = ", ".join(labels) if labels else "none"
    sources = ", ".join(docs) if docs else "the interview only"
    return f"Gaps: {gaps}. Sources: {sources}."


def _feasibility(c: _Ctx) -> FeasibilityPart:
    """Part 6 (spec 27 §3.1): A the three questions, B readiness, C before starting and risks, then the gaps line."""
    a = c.assessment
    q = a.questions if a is not None and a.step_assessment is not None else None
    head: dict[str, Any] = {"number": NUMBERS["feasibility"], "title": TITLES["feasibility"]}
    rows = []
    if q is not None:
        for key, answer in (("q1", q.q1), ("q2", q.q2), ("q3", q.q3)):
            why = " ".join(answer.reasons)
            rows.append(QuestionRow(key=key, question=QUESTION_TEXT[key], level=answer.level,  # pyright: ignore[reportArgumentType]
                                    level_label=LEVEL_WORDS[key][answer.level],
                                    why=f"{why} {answer.motivation}".strip(), quote=answer.evidence))  # fmt: skip
    items: list[str] = [*q.prepare, *q.risks] if q is not None else []
    bullets = list(dict.fromkeys(items))[:MAX_BULLETS]
    note = None if q is not None else _note("missing", NOT_V2)
    return FeasibilityPart(**head, note=note, questions=rows, readiness=_readiness_rows(c),
                           readiness_footer=READINESS_FOOTER, bullets=bullets, gaps=_gaps_line(c))  # fmt: skip


def build_report(
    session: Session, org: Organisation, vocab: Vocabulary, catalogue: SolutionCatalogue
) -> DiscoveryReport:
    """The cover and the six parts of the finished session (spec 27). Pure; never raises."""
    c = _Ctx(session, org, vocab, catalogue)
    try:
        cover = _cover(c)
    except Exception as exc:  # the cover is code too; a broken value must not cost the report
        logger.error("report_part_failed", extra={"part": "cover", "error": type(exc).__name__})
        cover = ReportCover(product_name=org.product_name, company_name=org.company_name, process_name=UNTITLED,
                            department=EMPTY, cluster=EMPTY, region=EMPTY, owner=EMPTY, date=EMPTY,
                            status="Mapped")  # fmt: skip
    a = c.assessment
    return DiscoveryReport(
        cover=cover,
        summary=_build(SummaryPart, "summary", lambda: _summary(c)),
        process=_build(FieldsPart, "process", lambda: _process(c)),
        measures=_build(FieldsPart, "measures", lambda: _measures(c)),
        map=_build(MapPart, "map", lambda: _map(c)),
        steps=_build(StepsPart, "steps", lambda: _steps(c)),
        feasibility=_build(FeasibilityPart, "feasibility", lambda: _feasibility(c)),
        generated_at=(a.generated_at if a is not None else "") or session.finished_at or "",
    )
