"""Tests for text extraction, decoding, cleaning and the text budget (spec 17 §3.3 rule 3, §3.4).

Why: the stored text is the only thing a quote is checked against and the only thing a model
reads, so it must keep the document's order, drop what is not body text (headers, footers),
refuse files with no readable text, and never exceed the budget.
What: AC-17.9 to AC-17.15 against the fixtures of `make_fixtures.py`.
Must not: read anything but the fixtures and in-test strings. Spec 17 §3.4.
"""

from __future__ import annotations

import pytest

from app.services.process_discovery.documents.extract import clean_and_cap, decode_text, extract_text
from app.services.process_discovery.documents.intake import DocumentRejected

BUDGET = 60_000


def test_ac_17_9_docx_in_document_order_without_header_and_footer(fixture_bytes):
    text = extract_text("docx", fixture_bytes("cost_review_procedure.docx"), BUDGET).text
    lines = text.split("\n")
    assert lines[0] == "Monthly cost review: procedure"
    assert lines[3] == (
        "Step 1 | Export actuals | The cost controller exports actual costs per cost centre from SAP S/4HANA "
        "into the review workbook."
    )
    assert (
        lines.index(
            "Step 5 | Send the cost report | The cost controller publishes the cost report for the CFO in Power BI."
        )
        == 7
    )
    assert lines[-1].startswith("If an explanation is missing")
    assert "SENTINEL" not in text


def test_ac_17_10_xlsx_sheets_formula_and_empty_rows(fixture_bytes):
    text = extract_text("xlsx", fixture_bytes("cost_review_tracker.xlsx"), BUDGET).text
    assert text.split("\n") == [
        "## Sheet: Actuals",
        "Cost centre | Actual | Budget | Variance",
        "CC-100 Workshop | 1200 | 1000 | 200",
        "CC-200 Fleet | 800 | 900 | -100",
        "CC-300 Office | 500 | 500 | 0",
        "## Sheet: Notes",
        "Reviewed by | Head of Controlling",
        "Escalation | Department head after three working days",
    ]


def test_ac_17_11_semicolon_csv(fixture_bytes):
    text = extract_text("csv", fixture_bytes("cost_review_tracker.csv"), BUDGET).text
    assert text.split("\n") == [
        "Cost centre | Actual | Budget",
        "CC-100 Workshop | 1200 | 1000",
        "CC-200 Fleet | 800 | 900",
        "CC-300 Office | 500 | 500",
    ]


def test_ac_17_11_pdf_pages_in_order(fixture_bytes):
    text = extract_text("pdf", fixture_bytes("cost_review_procedure.pdf"), BUDGET).text
    first = text.index("Monthly cost review: procedure")
    step_five = text.index("Send the cost report")
    last = text.index("If an explanation is missing")
    assert first < step_five < last


@pytest.mark.parametrize("fixture", ["encrypted.pdf", "scanned.pdf"])
def test_ac_17_12_unreadable_pdfs(fixture_bytes, fixture):
    with pytest.raises(DocumentRejected) as caught:
        extract_text("pdf", fixture_bytes(fixture), BUDGET)
    assert caught.value.code == "document_unreadable"
    assert (
        caught.value.message == "I couldn't find any text in this file. If it is a scan, try the file it was made from."
    )


def test_ac_17_12_text_with_no_letters():
    with pytest.raises(DocumentRejected) as caught:
        extract_text("txt", b"1234 5678\n--- ...\n", BUDGET)
    assert caught.value.code == "document_unreadable"


def test_ac_17_12_broken_docx_is_unreadable():
    with pytest.raises(DocumentRejected) as caught:
        extract_text("docx", b"PK\x03\x04 not really a zip", BUDGET)
    assert caught.value.code == "document_unreadable"


def test_ac_17_13_encodings_decode_to_the_same_text(fixture_bytes):
    plain = decode_text(fixture_bytes("cost_review_notes.txt"))
    assert "café" in plain and "€" in plain
    assert decode_text(fixture_bytes("notes_utf8_bom.txt")) == plain
    assert decode_text(fixture_bytes("notes_utf16.txt")) == plain
    assert decode_text(fixture_bytes("notes_cp1252.txt")) == plain
    assert (
        extract_text("txt", fixture_bytes("notes_utf16.txt"), BUDGET).text
        == extract_text("txt", fixture_bytes("cost_review_notes.txt"), BUDGET).text
    )


def test_ac_17_14_long_text_is_cut_at_a_newline(fixture_bytes):
    raw = fixture_bytes("long_procedure.txt")
    assert len(raw) > 60_001
    result = extract_text("txt", raw, BUDGET)
    assert result.truncated is True
    assert result.chars == len(result.text) <= BUDGET
    assert result.chars > BUDGET - 500
    assert raw.decode("utf-8").startswith(result.text)
    assert raw.decode("utf-8")[result.chars] == "\n"


def test_ac_17_14_no_newline_near_the_cut_cuts_at_the_budget():
    result = clean_and_cap("x" * 70_000, BUDGET)
    assert result.truncated is True
    assert result.chars == BUDGET


def test_ac_17_14_text_at_the_budget_is_kept_whole():
    exact = clean_and_cap("y" * BUDGET, BUDGET)
    assert (exact.chars, exact.truncated) == (BUDGET, False)
    short = clean_and_cap("short text", BUDGET)
    assert (short.text, short.chars, short.truncated) == ("short text", 10, False)


def test_ac_17_15_cleaning():
    raw = "  Title\r\nline one\x07 with bell   \rline two\t tab\n\n\n\n\n\nafter blanks\x00end  \n\n"
    result = clean_and_cap(raw, BUDGET)
    assert result.text == "Title\nline one  with bell\nline two\t tab\n\nafter blanks end"
    assert "\r" not in result.text
    assert "\n\n\n" not in result.text
