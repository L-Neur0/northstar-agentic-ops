"""Tests for the quote check: a quote counts only when it is really in the stored text (spec 17 §3.8).

Why: "no quote, no claim". A model can invent a plausible sentence; code must be able to say it
is not in the document, while forgiving what extraction and typography change (line breaks,
case, curly quotes, dashes, look-alike letters, table cell joins).
What: AC-17.24, including the table of §3.8 as parametrised cases.
Must not: accept a paraphrase or parts out of order. Spec 17 §3.8.
"""

from __future__ import annotations

import pytest

from app.services.process_discovery.documents.quotes import normalise_for_quote, quote_found

TEXT = (
    "The review starts once\nmonth-end close is completed in the ledger.\n"
    "Step 4 | Review | The Head of Controlling approves the commentary.\n"
    "Cost centre managers explain flagged variances by e-mail within three working days."
)
NORMAL = normalise_for_quote(TEXT)


@pytest.mark.parametrize(
    ("quote", "result"),
    [
        ('"The review starts once month-end close is completed"', "ok"),
        ("“the REVIEW starts once month–end close”", "ok"),
        ('"Cost centre managers explain … within three working days"', "ok"),
        ("Cost centre managers explain ... within three working days", "ok"),
        ('"The review takes about four days"', "quote_not_found"),
        ('"ok"', "quote_invalid"),
    ],
)
def test_ac_17_24_table_of_section_3_8(quote, result):
    assert quote_found(quote, NORMAL) == result


def test_ac_17_24_table_joins_and_look_alikes():
    assert quote_found("Step 4 | Review", NORMAL) == "ok"
    assert quote_found("Step 4 Review", NORMAL) == "ok"
    assert quote_found("Thе Head of Controlling", NORMAL) == "ok"  # Cyrillic e
    assert quote_found("...approves the commentary...", NORMAL) == "ok"


def test_ac_17_24_parts_must_be_in_order():
    assert quote_found("within three working days ... Cost centre managers", NORMAL) == "quote_not_found"


def test_ac_17_24_length_limits():
    assert quote_found("ab", NORMAL) == "quote_invalid"
    assert quote_found("   ", NORMAL) == "quote_invalid"
    assert quote_found("x" * 301, NORMAL) == "quote_invalid"
    assert quote_found("the", NORMAL) == "ok"
