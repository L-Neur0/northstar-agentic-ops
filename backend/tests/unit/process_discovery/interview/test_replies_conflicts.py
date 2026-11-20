"""Tests for reading a reply to a conflict question in code (spec 14 §3.17 item 4).

Why: whether "both", "2" or "site report march" chose a value is decidable from the question that
was asked, so the model is never asked what the expert meant; anything unclear decides nothing
and is read as the expert's own words.
What: AC-14.96, parametrised over every row of the item 4 table for both kinds.
Must not: call a model. Spec 14 §3.17 item 4.
"""

from __future__ import annotations

import pytest

from app.services.process_discovery.interview.replies import read_conflict_reply

SITE = "site_report_march.xlsx"
PROCEDURE = "Monthly cost review procedure.docx"
SLIDES = "review_slides.pptx"


def expert(text: str, *, both: bool = True):
    return read_conflict_reply(text, kind="expert", both_offered=both, holder_name=None, offered_name=SITE)


def document(text: str):
    return read_conflict_reply(text, kind="document", both_offered=False, holder_name=PROCEDURE, offered_name=SLIDES)


@pytest.mark.parametrize(
    ("text", "expert_choice", "document_choice"),
    [
        ("keep", "current", "current"),
        ("Leave it", "current", "current"),
        ("as it is", "current", "current"),
        ("behalten", "current", "current"),
        ("mine", "current", None),
        ("Yours", "current", None),
        ("keep mine", "current", None),
        ("as I said", "current", None),
        ("the document's", "offered", None),
        ("the file", "offered", None),
        ("the new one", "offered", None),
        ("das Dokument", "offered", None),
        ("both", "both", None),
        ("keep both", "both", None),
        ("beide", "both", None),
        ("1", "current", "current"),
        ("option 2", "offered", "offered"),
        ("3", "both", None),
        ("yes", None, None),
        ("no", None, None),
        ("ok", None, None),
        ("It's the Excel report, one tab per site", None, None),
    ],
)
def test_ac_14_96_reply_table(text, expert_choice, document_choice):
    assert expert(text) == expert_choice
    assert document(text) == document_choice


def test_ac_14_96_file_names_and_limits():
    assert expert("site report march") == "offered"
    assert expert("the site_report_march.xlsx one") == "offered"
    assert document("review slides") == "offered"
    assert document("the procedure: Monthly cost review procedure") == "current"
    assert document("review slides, not monthly cost review procedure") is None  # both files named
    assert expert("3", both=False) is None
    assert expert("both", both=False) is None
    assert expert("I think mine is better than that") is None  # 7 words
