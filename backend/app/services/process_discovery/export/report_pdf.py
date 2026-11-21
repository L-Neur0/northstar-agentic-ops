"""The discovery report as a PDF: cover, eleven parts, landscape pages for the map and the step table (spec 20 §3.4).

Why: the expert and the specialists take the report away as a file, and it must render for any
session: long answers, odd characters, a broken stored map. So the layout never trusts its input:
every session string is escaped, the map is test-rendered before it is placed (a failure is a note
on that page), the step table shrinks its font and then narrows its chunk before it ever splits
rows, and a reportlab `LayoutError` anywhere gives a one-page note document instead of an error.
What: `write_pdf(report, brand) -> bytes`. A4 portrait with 1-inch margins; the cover (banner,
"Discovery report" card, process name, meta card, vertically centred by measuring each block);
the parts in one flow (a section heading kept with its first block); Part 4's map and step table
on landscape pages (`NextPageTemplate`), at most 4 steps per page, fonts 9 → 8 → 7 → 6 pt, chunks
4 → 2 → 1 step, then row splits, with a "Step table — steps 1–4 of 5 (page 1 of 2)" caption; the
footer and primary rule on every page; PDF title = process name, no author.
Must not: format a value (the report model holds display-ready strings), import `artifacts/`, add
a closing call-to-action, or hard-code a colour or a company word (they come from `Brand`).
Spec 20 §3.4; AC-20.32 to AC-20.39.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Sequence
from typing import Any

from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import landscape
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
)
from reportlab.platypus.doctemplate import LayoutError

from app.models.process_discovery_wire import (
    DiscoveryReport,
    FeasibilityPart,
    FieldsPart,
    MapPart,
    ReportPartBase,
    StepColumn,
    StepsPart,
    SummaryPart,
)

from . import bpmn
from .branding import (
    FOOTER_NAME_CHARS,
    PAGE_SIZE,
    Brand,
    banner_flowable,
    card_flowable,
    page_decoration,
    section_heading_flowables,
    table_style,
)
from .substeps import build_table_flowable, escape_for_pdf, truncate_cell

logger = logging.getLogger("app.export")

MAX_COVER_FIELD_CHARS = 1000
MIN_DIAGRAM_HEIGHT_MM = 40
MAX_STEPS_PER_TABLE_PAGE = 4
GRID_FONT_SIZES = (9, 8, 7, 6)
MAP_FAILED_NOTE = "The process map could not be drawn."
LAYOUT_FALLBACK_NOTE = (
    "This report could not be laid out in full: one or more answers are too long to fit on a page. "
    "A specialist can shorten them."
)
MARGIN = inch
FRAME_PADDING = 12  # a Frame's own 6 pt padding on each side


def _shrinking_sizes(max_size: int) -> tuple[int, ...]:
    """`max_size`, then halved down to 1: (4, 2, 1)."""
    sizes = [max_size]
    while sizes[-1] > 1:
        sizes.append(max(sizes[-1] // 2, 1))
    return tuple(sizes)


CHUNK_SIZES = _shrinking_sizes(MAX_STEPS_PER_TABLE_PAGE)


def _p(text: Any, brand: Brand, style: str = "body") -> Paragraph:
    return Paragraph(escape_for_pdf(text), brand.style(style))


def _labelled(label: str, value: Any, brand: Brand) -> Paragraph:
    """ "<b>Label:</b> value": fixed labels are ours; the value is session text, so it is escaped."""
    return Paragraph(f"<b>{escape_for_pdf(label)}:</b> {escape_for_pdf(value)}", brand.style("body"))


def _bullets(items: Sequence[str], brand: Brand) -> list[Flowable]:
    return [Paragraph(f"• {escape_for_pdf(i)}", brand.style("body")) for i in items]


def _note_card(text: str, brand: Brand, width: float) -> Flowable:
    return card_flowable(brand, [Paragraph(escape_for_pdf(text), brand.style("muted"))], width)


def _keep_heading_with_first(heading: list[Flowable], content: list[Flowable]) -> list[Flowable]:
    """The heading glued to the first block only, so a long table stays free to split."""
    if not content:
        return heading
    return [KeepTogether(heading + content[:1]), *content[1:]]


def _table(rows: list[list[str]], fractions: Sequence[float], width: float, brand: Brand) -> Table:
    """A data table of wrapped cells with a repeated header row."""
    head, cell = brand.style("cell_head"), brand.style("cell")
    data = [[Paragraph(escape_for_pdf(c), head) for c in rows[0]]]
    data += [[Paragraph(escape_for_pdf(c), cell) for c in row] for row in rows[1:]]
    table = Table(data, colWidths=[width * f for f in fractions], repeatRows=1)
    table.setStyle(table_style(brand))
    return table


# --- cover --------------------------------------------------------------------------------------------


def _cover_page(report: DiscoveryReport, brand: Brand, width: float, height: float) -> list[Flowable]:
    """Banner and "Discovery report" card at the top; title and meta card centred in the height left."""
    c = report.cover
    top_gap, mid_gap = 8 * mm, 4 * mm
    banner = banner_flowable(brand, width)
    header = card_flowable(
        brand,
        [Paragraph("Discovery report", brand.style("card_title")), Spacer(1, 2 * mm),
         Paragraph(f"Generated on {escape_for_pdf(c.date)}", brand.style("cover_meta"))],
        width,
    )  # fmt: skip
    title = Paragraph(escape_for_pdf(truncate_cell(c.process_name, MAX_COVER_FIELD_CHARS)), brand.style("title"))
    meta = card_flowable(
        brand,
        [_labelled(label, truncate_cell(value, MAX_COVER_FIELD_CHARS), brand) for label, value in (
            ("Department", c.department), ("Cluster", c.cluster), ("Region", c.region),
            ("Process owner", c.owner), ("Status", c.status))],
        width,
    )  # fmt: skip
    heights = [f.wrap(width, height)[1] for f in (banner, header, title, meta)]
    gap = max((height - heights[0] - top_gap - heights[1] - heights[2] - mid_gap - heights[3]) / 2, top_gap)
    return [banner, Spacer(1, top_gap), header, Spacer(1, gap), title, Spacer(1, mid_gap), meta]


# --- the parts ------------------------------------------------------------------------------------------


def _section(title: str, content: list[Flowable], brand: Brand, width: float) -> list[Flowable]:
    return _keep_heading_with_first(section_heading_flowables(brand, title, width), content)


def _summary(part: SummaryPart, brand: Brand, width: float) -> list[Flowable]:
    """Part 1 (spec 27 §3.5): the sentences as one paragraph each."""
    return [_p(sentence, brand) for sentence in part.sentences]


def _fields(part: FieldsPart, brand: Brand, width: float) -> list[Flowable]:
    notes = [_note_card(n.text, brand, width) for n in part.notes if n != part.note]
    return notes + [_labelled(f.label, f.value, brand) for f in part.fields]


def _steps(part: StepsPart, brand: Brand, width: float) -> list[Flowable]:
    out: list[Flowable] = []
    if part.rows:
        rows = [["Step", "Hours a year", "AI fit", "Route", "Reason", "Evidence"]]
        for r in part.rows:
            route = f"{r.route_name}: {r.route_reason}" if r.route_reason else r.route_name
            evidence = f'"{r.evidence}" ({r.evidence_label})' if r.evidence else "—"
            fit = f"{r.level_label} ({r.fit_label})" if r.level_label else r.fit_label
            rows.append([f"{r.number}. {r.name}", r.hours, fit, route, r.reason or "—", evidence])
        out.append(_table(rows, (0.17, 0.09, 0.13, 0.21, 0.2, 0.2), width, brand))
    if part.catalogue_note:
        out.append(_p(part.catalogue_note, brand, "muted"))
    return out


def _feasibility(part: FeasibilityPart, brand: Brand, width: float) -> list[Flowable]:
    """Part 6 (spec 27 §3.1): the three questions, readiness, before starting and risks, the gaps line."""
    out: list[Flowable] = []
    for q in part.questions:  # paragraphs, not a table: a long answer must be able to break across pages
        out.append(
            Paragraph(f"<b>{escape_for_pdf(q.question)}</b> {escape_for_pdf(q.level_label)}", brand.style("body"))
        )
        why = q.why + (f' ("{q.quote}")' if q.quote else "")
        if why:
            out.append(_p(why, brand))
        out.append(Spacer(1, 2 * mm))
    if part.readiness:
        out.append(Paragraph("Readiness", brand.style("label")))
        rows = [["Dimension", "Level", "To prepare"]]
        rows += [[d.label, d.level_label, d.to_prepare or "—"] for d in part.readiness]
        out.append(_table(rows, (0.2, 0.15, 0.65), width, brand))
    if part.bullets:
        out.append(Paragraph("Before starting and risks", brand.style("label")))
        out += _bullets(part.bullets, brand)
    if part.gaps:
        out.append(_p(part.gaps, brand, "muted"))
    return out


_PORTRAIT = {
    SummaryPart: _summary,
    FieldsPart: _fields,
    StepsPart: _steps,
    FeasibilityPart: _feasibility,
}


def _part_flowables(part: ReportPartBase, brand: Brand, width: float) -> list[Flowable]:
    content: list[Flowable] = [_note_card(part.note.text, brand, width)] if part.note is not None else []
    builder = _PORTRAIT.get(type(part))
    if builder is not None:
        content += builder(part, brand, width)  # pyright: ignore[reportArgumentType]
    return _section(f"{part.number}. {part.title}", content, brand, width)


# --- Part 4: map and step table ---------------------------------------------------------------------


def _slice_rows(columns: Sequence[StepColumn], start: int, end: int) -> list[StepColumn]:
    return [c.model_copy(update={"cells": c.cells[start:end]}) for c in columns]


def _best_fit_table(columns: Sequence[StepColumn], labels: Sequence[str], width: float, height: float,
                    brand: Brand) -> Table | None:  # fmt: skip
    """The largest font at which `columns` fit `height`, or `None` if even 6 pt does not."""
    for size in GRID_FONT_SIZES:
        table = build_table_flowable(columns, width, brand, font_size=size, row_labels=labels)
        if table.wrap(width, height)[1] <= height:
            return table
    return None


def _table_for_chunk(columns: Sequence[StepColumn], labels: Sequence[str], width: float, height: float,
                     brand: Brand) -> list[Flowable]:  # fmt: skip
    """One chunk on one page when possible; else its rows split in halves, recursively, never dropped."""
    table = _best_fit_table(columns, labels, width, height, brand)
    if table is not None:
        return [table]
    if len(labels) <= 1:
        return [build_table_flowable(columns, width, brand, font_size=GRID_FONT_SIZES[-1], row_labels=labels)]
    mid = len(labels) // 2
    return (
        _table_for_chunk(_slice_rows(columns, 0, mid), labels[:mid], width, height, brand)
        + [PageBreak()]
        + _table_for_chunk(_slice_rows(columns, mid, len(labels)), labels[mid:], width, height, brand)
    )


def _plan_chunk_end(columns: Sequence[StepColumn], labels: Sequence[str], start: int, width: float, height: float,
                    brand: Brand) -> int:  # fmt: skip
    """Where the chunk starting at `start` ends: 4 steps, else 2, else 1, whichever first fits one page."""
    tried: set[int] = set()
    for size in CHUNK_SIZES:
        end = min(start + size, len(columns))
        if end - start in tried:
            continue
        tried.add(end - start)
        if _best_fit_table(columns[start:end], labels, width, height, brand) is not None:
            return end
    return min(start + MAX_STEPS_PER_TABLE_PAGE, len(columns))


def grid_pages(columns: Sequence[StepColumn], labels: Sequence[str], width: float, height: float,
               brand: Brand) -> list[Flowable]:  # fmt: skip
    """The step table as landscape-page flowables, with a step-range caption when it takes more than one page."""
    if not columns:
        return _table_for_chunk(columns, labels, width, height, brand)
    chunks: list[tuple[int, int]] = []
    start = 0
    while start < len(columns):
        end = _plan_chunk_end(columns, labels, start, width, height, brand)
        chunks.append((start, end))
        start = end
    out: list[Flowable] = []
    for page, (start, end) in enumerate(chunks, start=1):
        if page > 1:
            out.append(PageBreak())
        if len(chunks) > 1:
            first, last = columns[start].number, columns[end - 1].number
            steps = f"steps {first}–{last}" if last != first else f"step {first}"
            caption = f"Step table — {steps} of {len(columns)} (page {page} of {len(chunks)})"
            out += [Paragraph(escape_for_pdf(caption), brand.style("muted")), Spacer(1, 2 * mm)]
        out += _table_for_chunk(columns[start:end], labels, width, height, brand)
    return out


def diagram_page(part: MapPart, brand: Brand, width: float, height: float) -> list[Flowable]:
    """The map on its own landscape page: heading, the drawing in the height left, the caption.

    The drawing is test-rendered here, so any failure becomes the note on this page, not a failed PDF.
    """
    heading = section_heading_flowables(brand, "Process map", width)
    used = sum(f.wrap(width, height)[1] for f in heading)
    caption: list[Flowable] = []
    if part.caption:
        caption = [Spacer(1, 2 * mm), _p(part.caption, brand, "muted")]
        used += sum(f.wrap(width, height)[1] for f in caption)
    try:
        if not bpmn.layout(part.diagram):
            raise ValueError("the stored diagram has no drawable nodes")
        drawing_height = max(height - used - 4 * mm, MIN_DIAGRAM_HEIGHT_MM * mm)
        drawing = bpmn.build_drawing(part.diagram, width, drawing_height, brand, part.process_name)
        renderPDF.drawToString(drawing)
    except Exception as exc:
        logger.error("report_map_failed", extra={"error": type(exc).__name__})
        return [*heading, _note_card(MAP_FAILED_NOTE, brand, width)]
    return [*heading, drawing, *caption]


def _map_flowables(part: MapPart, brand: Brand, width: float, grid_width: float, grid_height: float) -> list[Flowable]:
    portrait: list[Flowable] = [_note_card(part.note.text, brand, width)] if part.note is not None else []
    portrait.append(_labelled("Systems used", "; ".join(part.systems) or "—", brand))
    out = _section(f"{part.number}. {part.title}", portrait, brand, width)
    out += [NextPageTemplate("landscape"), PageBreak()]
    if part.diagram is not None:
        out += diagram_page(part, brand, grid_width, grid_height) + [PageBreak()]
    labels = part.row_labels or [c.label for c in (part.columns[0].cells if part.columns else [])]
    out += section_heading_flowables(brand, "Steps", grid_width)
    out += grid_pages(part.columns, labels, grid_width, grid_height - 15 * mm, brand)
    # `NextPageTemplate` only switches at the next break: without it Part 5 would start on the last landscape page.
    out += [NextPageTemplate("portrait"), PageBreak()]
    return out


# --- the document -----------------------------------------------------------------------------------


def _doc(buffer: io.BytesIO, report: DiscoveryReport, brand: Brand, *, with_landscape: bool) -> BaseDocTemplate:
    portrait_size = PAGE_SIZE
    footer = f"{brand.product_name} · Discovery report · {truncate_cell(report.cover.process_name, FOOTER_NAME_CHARS)}"
    decorate = page_decoration(brand, footer)

    def frame(size: tuple[float, float], frame_id: str) -> Frame:
        return Frame(MARGIN, MARGIN, size[0] - 2 * MARGIN, size[1] - 2 * MARGIN, id=frame_id)

    doc = BaseDocTemplate(buffer, pagesize=portrait_size, title=report.cover.process_name, author="",
                          creator=brand.product_name)  # fmt: skip
    templates = [PageTemplate(id="portrait", pagesize=portrait_size, onPage=decorate,
                              frames=[frame(portrait_size, "portrait")])]  # fmt: skip
    if with_landscape:
        size = landscape(portrait_size)
        templates.append(
            PageTemplate(id="landscape", pagesize=size, onPage=decorate, frames=[frame(size, "landscape")])
        )
    doc.addPageTemplates(templates)
    return doc


def write_pdf(report: DiscoveryReport, brand: Brand) -> bytes:
    """The report as PDF bytes. A layout problem gives a one-page note document, never an exception."""
    portrait_size = PAGE_SIZE
    width, height = portrait_size[0] - 2 * MARGIN, portrait_size[1] - 2 * MARGIN
    land = landscape(portrait_size)
    grid_width, grid_height = land[0] - 2 * MARGIN - FRAME_PADDING, land[1] - 2 * MARGIN - FRAME_PADDING
    content_width = width - FRAME_PADDING

    story: list[Flowable] = _cover_page(report, brand, content_width, height - FRAME_PADDING)
    story.append(PageBreak())
    for part in report.parts():
        if isinstance(part, MapPart):
            story += _map_flowables(part, brand, content_width, grid_width, grid_height)
        else:
            story += _part_flowables(part, brand, content_width)

    buffer = io.BytesIO()
    try:
        _doc(buffer, report, brand, with_landscape=True).build(story)
    except LayoutError as exc:
        logger.error("report_layout_failed", extra={"error": type(exc).__name__})
        buffer = io.BytesIO()
        _doc(buffer, report, brand, with_landscape=False).build([
            Paragraph(escape_for_pdf(truncate_cell(report.cover.process_name, 200)), brand.style("part")),
            Spacer(1, 2 * mm),
            Paragraph(escape_for_pdf(LAYOUT_FALLBACK_NOTE), brand.style("muted")),
        ])  # fmt: skip
    return buffer.getvalue()
