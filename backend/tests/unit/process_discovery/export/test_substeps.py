"""Unit tests for the step table builder and the PDF text rules, `export/substeps.py` (spec 20 §3.3, §3.4).

Why: one stray "&" or "<" in an answer, or one character Helvetica cannot print, must never crash
the PDF; and the step table must be built the same way at every font size the planner tries.
What: truncation with an ellipsis, escaping (XML and cp1252), and the table's shape (header "Step n",
one row per label, label column plus equal step columns, header row repeated).
Must not: format a cell value (the report model does that; see `test_report_model.py`).
Covers the text and table rules behind AC-20.34 and AC-20.35.
"""

from __future__ import annotations

from reportlab.platypus import Paragraph

from app.models.process_discovery_wire import ReportField, StepColumn
from app.services.process_discovery.export.branding import Brand
from app.services.process_discovery.export.substeps import (
    MAX_CELL_CHARS,
    build_table_flowable,
    escape_for_pdf,
    truncate_cell,
)
from tests.unit.process_discovery.export.cases import ORG

BRAND = Brand.from_config(ORG)


def _column(number: int, values: list[str]) -> StepColumn:
    cells = [ReportField(key=f"k{i}", label=f"Row {i}", value=v) for i, v in enumerate(values)]
    return StepColumn(number=number, name=f"Step {number}", cells=cells)


def test_a_runaway_cell_is_cut_to_the_budget_with_an_ellipsis_and_short_text_is_untouched():
    cut = truncate_cell("x" * 5000)
    assert len(cut) == MAX_CELL_CHARS and cut.endswith("…")
    assert truncate_cell("short") == "short" and truncate_cell(cut) == cut


def test_escaping_makes_xml_characters_literal_and_unprintable_characters_question_marks():
    assert escape_for_pdf("A & B < C > D") == "A &amp; B &lt; C &gt; D"
    assert escape_for_pdf("Prüfung — €") == "Prüfung — €"  # cp1252 has these

    assert escape_for_pdf("发票 ✓") == "?? OK"  # no CJK glyphs; the tick is written as OK
    Paragraph(escape_for_pdf("<b>not bold & broken"), BRAND.style("body"))  # parses


def test_arrows_and_common_symbols_print_as_text_not_question_marks():
    """Spec 20 §3.4: the built-in font has no arrows; "→ back to step 1" must not print as "? back to step 1"."""
    assert escape_for_pdf("totals do not match SAP → back to step 1") == "totals do not match SAP -&gt; back to step 1"
    assert escape_for_pdf("a ← b ≥ c ≤ d ✓") == "a &lt;- b &gt;= c &lt;= d OK"


def test_the_table_has_a_step_header_one_row_per_label_and_equal_step_columns():
    columns = [_column(3, ["a", "b"]), _column(4, ["c & d", "e"])]
    table = build_table_flowable(columns, 700, BRAND, font_size=8, row_labels=["Row 0", "Row 1"])
    data = table._cellvalues  # pyright: ignore[reportAttributeAccessIssue]
    assert [p.getPlainText() for p in data[0]] == ["Field", "Step 3", "Step 4"]
    assert [row[0].getPlainText() for row in data[1:]] == ["Row 0", "Row 1"]
    assert data[1][2].getPlainText() == "c & d"
    widths = table._colWidths  # pyright: ignore[reportAttributeAccessIssue]
    assert abs(sum(widths) - 700) < 0.01 and widths[1] == widths[2]
    assert table.repeatRows == 1


def test_a_column_shorter_than_the_labels_shows_a_dash():
    table = build_table_flowable([_column(1, ["a"])], 500, BRAND, row_labels=["Row 0", "Row 1"])
    assert table._cellvalues[2][1].getPlainText() == "—"  # pyright: ignore[reportAttributeAccessIssue]
