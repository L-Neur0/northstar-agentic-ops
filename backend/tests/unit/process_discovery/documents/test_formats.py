"""Tests for the slide and e-mail formats and the document limit (spec 17 §3.1 items 9–10, decided 2026-11-20).

Why: slides and e-mails are where much of a process lives at work. A `.pptx` must be read in slide
order (titles, text boxes, tables, notes) without its pictures; an `.eml` must keep only what helps
the form (Subject, Date, attachment names, the body) and never a sender's or a recipient's name or
address; Outlook `.msg` files are not read. The limit is ten documents, from the configuration.
What: AC-17.66 to AC-17.69 (intake and extraction; the 409 of AC-17.69 is also proved through the API).
Must not: reach the network. Spec 17 §3.1, §3.3, §3.4.
"""

from __future__ import annotations

import pytest

from app.services.process_discovery.documents.extract import extract_text
from app.services.process_discovery.documents.intake import DocumentRejected, check_intake, detect_kind

from .helpers import record


def test_ac_17_66_pptx_in_slide_order(docs_config, fixture_bytes):
    data = fixture_bytes("cost_review_slides.pptx")
    assert detect_kind("deck.pptx", data, docs_config) == "pptx"
    text = extract_text("pptx", data, 60_000).text
    order = [
        "## Slide 1",
        "Monthly cost review",
        "The review starts once month-end close is completed in the ledger.",
        "Notes: Speaker note: mention the three working days.",
        "## Slide 2",
        "Steps",
        "Step | Name",
        "1 | Export actuals",
        "2 | Compare with budget",
    ]
    positions = [text.index(line) for line in order]
    assert positions == sorted(positions)
    assert "PIC-SENTINEL" not in text


def test_ac_17_66_a_docx_named_pptx_is_refused(docs_config, fixture_bytes):
    with pytest.raises(DocumentRejected) as caught:
        detect_kind("deck.pptx", fixture_bytes("cost_review_procedure.docx"), docs_config)
    assert caught.value.code == "document_type"


def test_ac_17_67_eml_keeps_subject_date_attachments_and_body_only(docs_config, fixture_bytes):
    data = fixture_bytes("late_explanation.eml")
    assert detect_kind("mail.eml", data, docs_config) == "eml"
    text = extract_text("eml", data, 60_000).text
    assert text.splitlines()[:3] == [
        "Subject: Missing variance explanation for CC-101",
        "Date: Mon, 02 Mar 2026 09:00:00 +0100",
        "Attachments: site_report.pdf",
    ]
    assert "within three working days" in text
    for personal in ("Cost Controller", "controller@", "Site Manager", "north.manager", "example.org", "From:", "To:"):
        assert personal not in text


def test_ac_17_67_html_only_body_becomes_text(fixture_bytes):
    text = extract_text("eml", fixture_bytes("html_only.eml"), 60_000).text
    assert "The cost report is due on Friday." in text
    assert "<" not in text and "someone@" not in text


def test_ac_17_67_text_without_mail_headers_is_not_an_eml(docs_config):
    with pytest.raises(DocumentRejected) as caught:
        detect_kind("mail.eml", b"Just some notes about the review.\n", docs_config)
    assert caught.value.code == "document_type"


def test_ac_17_68_msg_is_refused(docs_config):
    assert "msg" not in docs_config.allowed_types
    with pytest.raises(DocumentRejected) as caught:
        check_intake([], "late.msg", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100, docs_config)
    assert caught.value.code == "document_type"


def test_ac_17_69_ten_documents_from_config(docs_config, fixture_bytes):
    assert docs_config.max_files_per_session == 10
    data = fixture_bytes("cost_review_notes.txt")
    assert check_intake([record(f"d{i}") for i in range(9)], "n.txt", data, docs_config)[1] == "txt"
    with pytest.raises(DocumentRejected) as caught:
        check_intake([record(f"d{i}") for i in range(10)], "n.txt", data, docs_config)
    assert caught.value.code == "document_limit"
