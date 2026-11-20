"""The step table of the report as a reportlab table, and the text rules every PDF string follows (spec 20 §3.4).

Why: the step table is the widest thing in the report (up to six steps × twelve rows of free
text), so it has its own builder that the page planner can call at several font sizes and widths;
and every string that came from a session must be escaped before reportlab's tiny XML dialect
reads it, or one "&" or "<" in an answer would crash the PDF.
What: `EMPTY_CELL`, `MAX_CELL_CHARS`, `truncate_cell` (cap with "…"), `escape_for_pdf` (escape
`&`, `<`, `>`; characters outside cp1252 become "?", since the built-in Helvetica cannot print
them), and `build_table_flowable` (one header row "Step N", one row per S01–S12 label, wrapped
cells, fixed label column, the other columns sharing the width; the header row repeats).
Must not: format a cell value (the report model already did: `artifacts/report.cell_text`),
import `artifacts/`, or hard-code a colour (they come from `branding`).
Spec 20 §3.4 (Step table, Text); AC-20.34, AC-20.35.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table

from app.models.process_discovery_wire import StepColumn

from .branding import TEXT, Brand, table_style

EMPTY_CELL = "—"
MAX_CELL_CHARS = 1500
ELLIPSIS = "…"
LABEL_SHARE = 0.15


def truncate_cell(text: str, limit: int = MAX_CELL_CHARS) -> str:
    """`text` cut to at most `limit` characters, ending in "…" when anything was dropped."""
    if len(text) <= limit:
        return text
    return text[: max(limit - len(ELLIPSIS), 0)] + ELLIPSIS


# Symbols the built-in Helvetica cannot draw, written out instead of printing "?".
_PLAIN_SYMBOLS = {"→": "->", "←": "<-", "≥": ">=", "≤": "<=", "✓": "OK", "✗": "x"}


def escape_for_pdf(text: Any) -> str:
    """Session text made safe for a reportlab `Paragraph`: XML-escaped, printable in Helvetica."""
    plain = str(text)
    for symbol, words in _PLAIN_SYMBOLS.items():
        plain = plain.replace(symbol, words)
    printable = plain.encode("cp1252", errors="replace").decode("cp1252")
    return _xml_escape(printable)


def build_table_flowable(
    columns: Sequence[StepColumn], width: float, brand: Brand, *, font_size: int = 9,
    row_labels: Sequence[str] = (),
) -> Table:  # fmt: skip
    """The step columns as one table `width` wide, at `font_size` (leading scales with it)."""
    leading = font_size + 2
    head = ParagraphStyle("StepHead", fontName="Helvetica-Bold", fontSize=font_size, leading=leading,
                          textColor=brand.primary)  # fmt: skip
    cell = ParagraphStyle("StepCell", fontName="Helvetica", fontSize=font_size, leading=leading, textColor=TEXT)
    labels = list(row_labels) or [c.label for c in (columns[0].cells if columns else [])]
    data: list[list[Any]] = [[Paragraph("Field", head)] + [Paragraph(f"Step {c.number}", head) for c in columns]]
    for i, label in enumerate(labels):
        row: list[Any] = [Paragraph(escape_for_pdf(label), head)]
        for column in columns:
            value = column.cells[i].value if i < len(column.cells) else EMPTY_CELL
            row.append(Paragraph(escape_for_pdf(value), cell))
        data.append(row)
    label_width = width * LABEL_SHARE
    rest = width - label_width
    col_width = rest / len(columns) if columns else rest
    table = Table(data, colWidths=[label_width] + [col_width] * len(columns), repeatRows=1)
    table.setStyle(table_style(brand))
    return table
