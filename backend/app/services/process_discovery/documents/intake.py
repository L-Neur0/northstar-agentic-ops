"""Upload checks: count, size, name, kind by content, archive safety and the injection screen (spec 17 §3.2, §3.3).

Why: an upload is untrusted bytes with an untrusted name. A file must be typed by what it is, not
by what it is called (a ZIP named `report.pdf` is not a PDF); Office archives can hide macros or
expand into gigabytes; XML can carry entities; and text meant for the model can carry
instructions. The cheapest refusal runs first (count before any byte is read), and the screen
runs last, on exactly the text that would be stored.
What: `DocumentRejected` (code + the one plain sentence the expert sees, §3.12), `DocumentNotFound`,
`clean_name`, `detect_kind`, `check_intake` and `screen`. Limits come from `DocumentsConfig`.
Must not: store, log or return the bytes; type a limit that belongs in the configuration; parse
XML with anything but `defusedxml`; reach the network. Spec 17 §3.2, §3.3, §3.12;
AC-17.1 to AC-17.7, AC-17.13 (binary noise), AC-17.16.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Sequence
from typing import Literal

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

from app.core.config import DocumentsConfig
from app.models.process_discovery_schemas import DocumentRecord
from app.utils.prompt_safety import find_injection_patterns, single_line

DocumentKind = Literal["pdf", "docx", "xlsx", "csv", "txt", "md", "bpmn"]
RejectCode = Literal["document_limit", "document_too_large", "document_type", "document_unreadable", "unsafe_input"]

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
NAME_MAX = 120
MB = 1_048_576

ZIP_MAX_MEMBERS = 2_000
ZIP_MAX_TOTAL = 100 * MB
ZIP_MAX_RATIO = 100
TEXT_PROBE = 8_192
CONTROL_SHARE = 0.01

UNREADABLE_MESSAGE = "I couldn't find any text in this file. If it is a scan, try the file it was made from."
TYPE_MESSAGE = "This file type can't be read. Use PDF, Word, Excel, CSV, text, Markdown or BPMN."
UNSAFE_MESSAGE = "This document contains text that looks like instructions to the assistant, so I didn't read it."

_FAMILY: dict[str, str] = {
    "pdf": "pdf",
    "docx": "ooxml",
    "xlsx": "ooxml",
    "csv": "text",
    "txt": "text",
    "md": "text",
    "bpmn": "xml",
    "xml": "xml",
}
_OOXML: dict[str, tuple[str, str]] = {
    "docx": ("word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"),
    "xlsx": ("xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"),
}
_CONTENT_TYPES_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class DocumentRejected(Exception):
    """A refused upload: `code` for the API, `message` for the expert, `patterns` for the log (counts only)."""

    def __init__(self, code: RejectCode, message: str, *, patterns: int = 0) -> None:
        super().__init__(code)
        self.code: RejectCode = code
        self.message = message
        self.patterns = patterns


class DocumentNotFound(Exception):
    """No document with that id in the session (404 `not_found`, spec 15)."""


def _type_error() -> DocumentRejected:
    return DocumentRejected("document_type", TYPE_MESSAGE)


def unreadable(message: str = UNREADABLE_MESSAGE) -> DocumentRejected:
    return DocumentRejected("document_unreadable", message)


# --- Names --------------------------------------------------------------------------------------


def _extension(name: str) -> str:
    base = re.split(r"[\\/]", name)[-1]
    return base.rsplit(".", 1)[1].lower() if "." in base else ""


def clean_name(filename: str) -> str:
    """Base name only, one line, at most 120 characters; `document.<ext>` when nothing is left."""
    base = re.split(r"[\\/]", filename or "")[-1]
    name = single_line(base, len(base) + 1)[:NAME_MAX].strip()
    ext = _extension(base)
    stem = name.rsplit(".", 1)[0] if "." in name else name
    if not stem.strip():
        return f"document.{ext}" if ext else "document"
    return name


# --- Kind by content ----------------------------------------------------------------------------


def decode_text(data: bytes) -> str:
    """UTF-8 (BOM removed); UTF-16 with a BOM; else cp1252 when < 1 % control characters; else `document_type`."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            text = data.decode("utf-16")
        except UnicodeDecodeError:
            raise _type_error() from None
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = data.decode("cp1252")
            except UnicodeDecodeError:
                raise _type_error() from None
            if text and len(_CONTROL.findall(text)) / len(text) >= CONTROL_SHARE:
                raise _type_error() from None
    if "\x00" in text[:TEXT_PROBE]:
        raise _type_error()
    return text


def _check_zip(data: bytes, kind: str) -> None:
    if not data.startswith(b"PK\x03\x04"):
        raise _type_error()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > ZIP_MAX_MEMBERS:
                raise _type_error()
            if sum(m.file_size for m in members) > ZIP_MAX_TOTAL:
                raise _type_error()
            names = {m.filename for m in members}
            for member in members:
                if ".." in member.filename or member.filename.startswith("/"):
                    raise _type_error()
                if member.filename.rsplit("/", 1)[-1].lower() == "vbaproject.bin":
                    raise _type_error()
                if member.file_size / max(member.compress_size, 1) > ZIP_MAX_RATIO:
                    raise _type_error()
            main_part, main_type = _OOXML[kind]
            if main_part not in names or "[Content_Types].xml" not in names:
                raise _type_error()
            types = fromstring(archive.read("[Content_Types].xml"), forbid_dtd=True)
    except (zipfile.BadZipFile, DefusedXmlException, SyntaxError, ValueError, OSError):
        raise _type_error() from None
    part = "/" + main_part
    declared = [o.get("ContentType") for o in types.iter(f"{_CONTENT_TYPES_NS}Override") if o.get("PartName") == part]
    if declared != [main_type]:
        raise _type_error()


def _check_bpmn(data: bytes) -> None:
    decode_text(data)
    try:
        root = fromstring(data, forbid_dtd=True)
    except DefusedXmlException:
        raise unreadable() from None
    except (SyntaxError, ValueError):
        raise _type_error() from None
    if root.tag != f"{{{BPMN_NS}}}definitions":
        raise _type_error()


def detect_kind(filename: str, data: bytes, config: DocumentsConfig) -> DocumentKind:
    """The kind of the file, decided by its content within the family its extension allows."""
    ext = _extension(filename)
    if ext not in config.allowed_types or ext not in _FAMILY:
        raise _type_error()
    family = _FAMILY[ext]
    if family == "pdf":
        if b"%PDF-" not in data[:1024]:
            raise _type_error()
        return "pdf"
    if family == "ooxml":
        _check_zip(data, ext)
        return "docx" if ext == "docx" else "xlsx"
    if family == "xml":
        _check_bpmn(data)
        return "bpmn"
    if data.startswith((b"%PDF-", b"PK\x03\x04")):  # a PDF or an Office file is not text, whatever its name
        raise _type_error()
    decode_text(data)
    return "csv" if ext == "csv" else "md" if ext == "md" else "txt"


def check_intake(
    existing: Sequence[DocumentRecord], filename: str, data: bytes, config: DocumentsConfig
) -> tuple[str, DocumentKind]:
    """Count, size, extension and kind, cheapest first. Returns `(clean name, kind)`."""
    if len(existing) >= config.max_files_per_session:
        raise DocumentRejected(
            "document_limit",
            f"You can add up to {config.max_files_per_session} documents. Remove one to add another.",
        )
    if not data:
        raise unreadable()
    if len(data) > int(config.max_file_mb * MB):
        raise DocumentRejected("document_too_large", f"This file is larger than {config.max_file_mb:g} MB.")
    kind = detect_kind(filename, data, config)
    return clean_name(filename), kind


def screen(name: str, text: str) -> int:
    """The injection screen on the name and the capped text; raises `unsafe_input`, else returns 0."""
    hits = len(find_injection_patterns(name)) + len(find_injection_patterns(text))
    if hits:
        raise DocumentRejected("unsafe_input", UNSAFE_MESSAGE, patterns=hits)
    return 0
