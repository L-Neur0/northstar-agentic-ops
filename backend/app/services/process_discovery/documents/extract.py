"""Text from an upload: one extractor per kind, then one cleaning and one cap for all (spec 17 §3.4).

Why: the stored text is the only part of a document the product keeps, the only text a quote is
checked against and the only text a model reads, so every kind must become the same thing: body
text in document order, cleaned the same way, never longer than the budget. A file with no
letters at all (a scan, an encrypted PDF, a list of numbers) is refused rather than stored empty.
What: `ExtractedText`, `extract_text` (pdf, docx, xlsx, csv, txt, md; BPMN is `bpmn_read`),
`clean_and_cap` and `decode_text` (re-exported from `intake`, where the kind check needs it).
Extraction stops once it has the budget plus one character, so a 500-page PDF is not read in full.
Must not: keep or return the bytes, read headers, footers, comments or tracked deletions, read
the clock or reach the network. Spec 17 §3.4; AC-17.9 to AC-17.15. Amendment 2026-11-20: `.pptx`
(per slide, in order: title, text boxes, tables, then the notes; pictures ignored) and `.eml`
(Subject, Date, attachment names and the plain-text body, an HTML-only body turned into text;
never a sender, recipient or address). AC-17.66, AC-17.67.
"""

from __future__ import annotations

import csv
import email
import email.policy
import io
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from email.message import EmailMessage
from html.parser import HTMLParser
from typing import Any

from .intake import DocumentKind, DocumentRejected, decode_text, unreadable

__all__ = ["ExtractedText", "clean_and_cap", "decode_text", "extract_text"]

PDF_MAX_PAGES = 500
CUT_WINDOW = 500
CELL_JOIN = " | "
CSV_SNIFF = 4_096

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_TRAILING = re.compile(r"[ \t]+\n")
_BLANKS = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class ExtractedText:
    """The cleaned, capped text that is stored; `chars == len(text)`."""

    text: str
    chars: int
    truncated: bool


def _clean(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw).replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub(" ", text)
    text = _TRAILING.sub("\n", text + "\n")
    return _BLANKS.sub("\n\n", text).strip()


def clean_and_cap(raw: str, budget: int, *, cut_early: bool = False) -> ExtractedText:
    """Clean, then cut at the budget (at a newline within the last 500 characters when there is one)."""
    text = _clean(raw)
    truncated = cut_early
    if len(text) > budget:
        cut = text[:budget]
        newline = cut.rfind("\n", budget - CUT_WINDOW)
        text = (cut[:newline] if newline > 0 else cut).rstrip()
        truncated = True
    if not any(c.isalpha() for c in text):
        raise unreadable()
    return ExtractedText(text, len(text), truncated)


def _collect(parts: Iterator[str], budget: int, separator: str) -> tuple[str, bool]:
    """Join parts until the budget plus one character is reached; `(text, stopped early)`."""
    out: list[str] = []
    size = 0
    for part in parts:
        out.append(part)
        size += len(part) + len(separator)
        if size > budget + 1:
            return separator.join(out), True
    return separator.join(out), False


def _pdf_pages(data: bytes) -> Iterator[str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted and not reader.decrypt(""):
        raise unreadable()
    for index, page in enumerate(reader.pages):
        if index >= PDF_MAX_PAGES:
            return
        yield page.extract_text() or ""


def _docx_lines(data: bytes) -> Iterator[str]:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(io.BytesIO(data))
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document).text
        elif child.tag == qn("w:tbl"):
            for row in Table(child, document).rows:
                seen: list[Any] = []
                cells: list[str] = []
                for cell in row.cells:
                    if any(cell._tc is s for s in seen):  # a merged cell repeats
                        continue
                    seen.append(cell._tc)
                    cells.append(" ".join(cell.text.split()))
                yield CELL_JOIN.join(cells)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split())


def _row_line(values: list[str]) -> str | None:
    while values and not values[-1]:
        values.pop()
    return CELL_JOIN.join(values) if any(values) else None


def _xlsx_lines(data: bytes) -> Iterator[str]:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            yield f"## Sheet: {sheet.title}"
            for row in sheet.iter_rows(values_only=True):
                line = _row_line([_cell(v) for v in row])
                if line is not None:
                    yield line
    finally:
        workbook.close()


def _csv_lines(data: bytes) -> Iterator[str]:
    text = decode_text(data)
    try:
        dialect: Any = csv.Sniffer().sniff(text[:CSV_SNIFF], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    for row in csv.reader(io.StringIO(text), dialect):
        line = _row_line([_cell(v) for v in row])
        if line is not None:
            yield line


def _shape_lines(shape: Any) -> Iterator[str]:
    """Text of one slide shape: a group's members, a table's rows, a text frame's paragraphs; pictures give nothing."""
    if getattr(shape, "shapes", None) is not None:  # a group
        for member in shape.shapes:
            yield from _shape_lines(member)
    elif getattr(shape, "has_table", False):
        for row in shape.table.rows:
            yield CELL_JOIN.join(" ".join(cell.text.split()) for cell in row.cells)
    elif getattr(shape, "has_text_frame", False):
        for paragraph in shape.text_frame.paragraphs:
            yield "".join(run.text for run in paragraph.runs)


def _pptx_lines(data: bytes) -> Iterator[str]:
    from pptx import Presentation

    deck = Presentation(io.BytesIO(data))
    for number, slide in enumerate(deck.slides, start=1):
        yield f"## Slide {number}"
        title = slide.shapes.title
        if title is not None and title.has_text_frame:
            yield title.text_frame.text
        for shape in slide.shapes:
            if title is not None and shape.shape_id == title.shape_id:
                continue
            yield from _shape_lines(shape)
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame
            if notes is not None and notes.text.strip():
                yield "Notes: " + notes.text


class _HtmlText(HTMLParser):
    """The visible text of an HTML body: tags dropped, script and style skipped, block ends as new lines."""

    BLOCKS = frozenset({"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "table"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def _html_text(html: str) -> str:
    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    return "".join(parser.parts)


def _eml_lines(data: bytes) -> Iterator[str]:
    """Subject, Date, attachment names, then the body. Never From, To, Cc or any address (§3.1 item 10)."""
    message = email.message_from_bytes(data, policy=email.policy.default)
    assert isinstance(message, EmailMessage)
    for header in ("Subject", "Date"):
        value = message.get(header)
        if value is not None and str(value).strip():
            yield f"{header}: {' '.join(str(value).split())}"
    names = [part.get_filename() for part in message.iter_attachments()]
    shown = [" ".join(n.split()) for n in names if n]
    if shown:
        yield "Attachments: " + ", ".join(shown)
    plain = message.get_body(preferencelist=("plain",))
    if plain is not None:
        yield str(plain.get_content())  # pyright: ignore[reportAttributeAccessIssue]
        return
    html = message.get_body(preferencelist=("html",))
    if html is not None:
        yield _html_text(str(html.get_content()))  # pyright: ignore[reportAttributeAccessIssue]


def extract_text(kind: DocumentKind, data: bytes, budget: int) -> ExtractedText:
    """The stored text of an upload of `kind` (not BPMN); `document_unreadable` when there is none."""
    if kind in ("txt", "md"):
        decoded = decode_text(data)
        return clean_and_cap(decoded[: budget * 2 + 1], budget, cut_early=len(decoded) > budget * 2 + 1)
    extractors = {
        "pdf": (_pdf_pages, "\n\n"),
        "docx": (_docx_lines, "\n"),
        "xlsx": (_xlsx_lines, "\n"),
        "csv": (_csv_lines, "\n"),
        "pptx": (_pptx_lines, "\n"),
        "eml": (_eml_lines, "\n"),
    }
    if kind not in extractors:
        raise ValueError(f"no text extractor for {kind!r}")
    extractor, separator = extractors[kind]
    try:
        raw, early = _collect(extractor(data), budget, separator)
    except DocumentRejected:
        raise
    except Exception:  # any library failure means the file cannot be read
        raise unreadable() from None
    return clean_and_cap(raw, budget, cut_early=early)
