"""Tests for per-run phrases with a unit of work and two-part answers (spec 19 §3.8).

Why: in evaluation run 20261121-084902 every step frequency was "once per role, about 6 times a
month", which the grammar could not read, so the report had no hours a year at all. These tests pin
the phrases experts really use, and the ones that must stay unreadable (a rate is not a duration).
What: `parse_frequency` and `parse_duration` on the §3.8 F1-F4 rows.
Must not: test hours a year (that is `artifacts/test_value.py`) or call a model.
Covers AC-19.44 to AC-19.46.
"""

from __future__ import annotations

import pytest

from app.services.process_discovery.domain.value_parse import parse_duration, parse_frequency


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("once per role", 1),
        ("per candidate", 1),
        ("for every request", 1),
        ("once for each new starter", 1),
        ("each site visit", 1),
        ("every time we hire", 1),
        ("twice per candidate", 2),
        ("3 times each request", 3),
    ],
)
def test_ac_19_44_per_run_with_a_unit_of_work(text: str, value: float) -> None:
    """AC-19.44: a unit-of-work noun after per / each / for every is per run."""
    freq = parse_frequency(text)
    assert freq is not None and freq.kind == "per_run" and freq.value == value


def test_ac_19_44_period_words_are_not_units_of_work() -> None:
    """AC-19.44: "once per month" stays periodic; "per weekday" is never per run."""
    monthly = parse_frequency("once per month")
    assert monthly is not None and (monthly.kind, monthly.value) == ("periodic", 12)
    weekday = parse_frequency("per weekday")
    assert weekday is None or weekday.kind == "periodic"


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        ("once per role, about 6 times a month", "per_run", 1),
        ("about 6 times a month, once per role", "per_run", 1),
        ("about 6 times a month; sometimes more", "periodic", 72),
    ],
)
def test_ac_19_45_two_part_answers(text: str, kind: str, value: float) -> None:
    """AC-19.45: read part by part; a per-run part wins, else the first part that parses."""
    freq = parse_frequency(text)
    assert freq is not None and (freq.kind, freq.value) == (kind, value)
    assert freq.text == text


def test_ac_19_45_nothing_readable_stays_unreadable() -> None:
    """AC-19.45: no part parses → None (code never guesses)."""
    assert parse_frequency("it depends, really") is None


@pytest.mark.parametrize(
    ("text", "hours"),
    [("3 working days per role", 24), ("about 3 hours each candidate", 3), ("2 hours for each request", 2)],
)
def test_ac_19_46_duration_with_a_unit_of_work_tail(text: str, hours: float) -> None:
    """AC-19.46: a per-unit-of-work tail is the duration of one run."""
    duration = parse_duration(text)
    assert duration is not None and duration.hours == hours


def test_ac_19_46_a_rate_is_not_a_duration() -> None:
    """AC-19.46: a period word after per stays unreadable."""
    assert parse_duration("3 hours per week") is None
