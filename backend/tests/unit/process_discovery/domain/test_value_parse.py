"""Tests for the duration and frequency grammar (spec 19 §3.1).

Why: every hour in the report starts here, so each row of the spec's "read as" tables is pinned,
and so is every phrase that must stay unreadable: code never guesses a number.
What: parametrised tables for `parse_duration`, `parse_frequency` and `runs_per_year`, the midpoint
flag, and the import check that the module sits in `domain/` and is reachable from the layers above.
Must not: test the hours a year (that is `test_value.py`) or call a model.
Covers AC-19.1 to AC-19.5 and AC-19.42.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.services.process_discovery.domain.value_parse import (
    parse_duration,
    parse_frequency,
    runs_per_year,
)


@pytest.mark.parametrize(
    ("text", "hours"),
    [
        ("6 hours", 6),
        ("1 day", 8),
        ("15 minutes", 0.25),
        ("about 2-3 hours each time", 2.5),
        ("half an hour", 0.5),
        ("1 hour 30 minutes", 1.5),
        ("1h30", 1.5),
        ("1,5 hours", 1.5),
        ("half a day", 4),
        ("an hour", 1),
        ("two hours", 2),
        ("2 to 3 hours", 2.5),
        ("1 working week", 40),
        ("Around 45 mins.", 0.75),
    ],
)
def test_ac_19_1_durations_read(text: str, hours: float) -> None:
    """AC-19.1: every "read as" row of §3.1 gives the stated hours."""
    duration = parse_duration(text)
    assert duration is not None
    assert duration.hours == pytest.approx(hours)
    assert duration.text == text.strip()


@pytest.mark.parametrize("text", ["a while", "depends", "6 hours a month", "up to 6 hours", "", "6", "about"])
def test_ac_19_2_durations_unreadable(text: str) -> None:
    """AC-19.2: anything outside the grammar is unreadable, never guessed."""
    assert parse_duration(text) is None


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        ("every month", "periodic", 12),
        ("monthly", "periodic", 12),
        ("once a month", "periodic", 12),
        ("10 times a month", "periodic", 120),
        ("every 2 weeks", "periodic", 25),
        ("every Monday", "periodic", 50),
        ("month-end", "periodic", 12),
        ("quarterly", "periodic", 4),
        ("twice a week", "periodic", 100),
        ("3 times per day", "periodic", 750),
        ("each time", "per_run", 1),
        ("twice each time", "per_run", 2),
        ("once", "per_run", 1),
        ("same as the process", "per_run", 1),
    ],
)
def test_ac_19_3_frequencies_read(text: str, kind: str, value: float) -> None:
    """AC-19.3: periodic and per-run rows of §3.1."""
    frequency = parse_frequency(text)
    assert frequency is not None
    assert (frequency.kind, frequency.value) == (kind, pytest.approx(value))


@pytest.mark.parametrize("text", ["when needed", "sometimes", "", "a few times"])
def test_ac_19_3_frequency_unreadable(text: str) -> None:
    """AC-19.3: "when needed" (and the like) is unreadable."""
    assert parse_frequency(text) is None


def test_ac_19_4_range_is_its_midpoint() -> None:
    """AC-19.4: a range is read as its midpoint and says so; a plain number does not."""
    ranged = parse_duration("between 2 and 4 hours")
    assert ranged is not None and ranged.hours == 3 and ranged.midpoint
    freq = parse_frequency("2-4 times a month")
    assert freq is not None and freq.value == 36 and freq.midpoint
    plain = parse_duration("6 hours")
    assert plain is not None and not plain.midpoint


@pytest.mark.parametrize(
    ("volume", "expected"),
    [
        ({"count": 1, "period": "month"}, 12),
        ({"count": 400, "period": "a month"}, 4800),
        ({"raw": "twice a week"}, 100),
        ({"raw": "a few hundred a month"}, None),
        ({"count": None, "period": "", "raw": ""}, None),
        ({"raw": "each time"}, None),
    ],
)
def test_ac_19_5_runs_per_year(volume: dict[str, object], expected: float | None) -> None:
    """AC-19.5: count × periods, else `raw` read as a periodic frequency, else unreadable."""
    assert runs_per_year(volume) == expected


def test_ac_19_5_proposed_volume_is_not_used() -> None:
    """AC-19.5: a volume that is only proposed by a document is not used."""
    meta = {"source": "document", "status": "proposed", "quote": "monthly", "documentId": "d1", "at": "t"}
    assert runs_per_year({"count": 1, "period": "month"}, meta) is None


def test_ac_19_42_value_parse_lives_in_domain_and_is_pure() -> None:
    """AC-19.42 (and AC-19.38 for this module): in `domain/`, importing nothing that does I/O."""
    path = Path(__file__).resolve().parents[4] / "app/services/process_discovery/domain/value_parse.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert modules <= {"__future__", "re", "collections.abc", "dataclasses", "typing"}
