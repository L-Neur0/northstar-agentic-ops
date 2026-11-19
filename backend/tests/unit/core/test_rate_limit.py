"""Unit tests for the daily model budget, the limiter and the client IP rule (spec 16 §3.3, §3.4; AC-16.12, AC-16.13, AC-16.15, AC-16.16).

Why: the open link is protected only by these counters; a budget that never resets, a warning that
fires on every call, or an IP key the client can choose would each defeat the protection quietly.
What: `BudgetTracker` (guard, record, snapshot, the UTC day reset, one log line at 80 % and at
100 %), `build_limiter` (refuses a bad limit string at start-up) and `client_ip` (the platform
proxy's last `X-Forwarded-For` hop only behind the proxy; the peer address otherwise).
Must not: sleep or read the real clock; time is passed in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from starlette.requests import Request

from app.core.rate_limit import BudgetTracker, build_limiter, client_ip, usage_scope
from app.core.settings import Settings


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 19, 23, 59, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_ac_16_12_guard_below_and_at_the_limit_and_record_adds_both_sides():
    tracker = BudgetTracker(100, Clock())
    assert tracker.guard("EXTRACT") is True
    tracker.record(Usage(60, 39))
    assert tracker.snapshot()["used"] == 99 and tracker.guard("GUIDE") is True
    tracker.record(Usage(1, 0))
    assert tracker.guard("GUIDE") is False


def test_ac_16_12_zero_means_unlimited():
    tracker = BudgetTracker(0, Clock())
    tracker.record(Usage(10**9, 10**9))
    assert tracker.guard("EXTRACT") is True


def test_ac_16_13_the_budget_resets_at_the_next_utc_day():
    clock = Clock()
    tracker = BudgetTracker(10, clock)
    tracker.record(Usage(10, 0))
    assert tracker.guard("EXTRACT") is False
    clock.now += timedelta(minutes=1)  # 00:00 UTC on the 20th
    assert tracker.guard("EXTRACT") is True
    assert tracker.snapshot() == {"day": "2026-11-20", "used": 0, "limit": 10}


def test_ac_16_15_one_line_at_80_and_one_at_100_percent_per_day(caplog: pytest.LogCaptureFixture):
    clock = Clock()
    tracker = BudgetTracker(100, clock)
    with caplog.at_level(logging.INFO, logger="app"):
        for _ in range(12):
            tracker.record(Usage(10, 0))
        clock.now += timedelta(days=1)
        tracker.record(Usage(85, 0))
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("budget_")]
    assert lines == ["budget_warning", "budget_exhausted", "budget_warning"]


def test_usage_scope_collects_the_tokens_of_calls_made_inside_it():
    tracker = BudgetTracker(0, Clock())
    with usage_scope() as usage:
        tracker.record(Usage(3, 4))
        tracker.record(Usage(1, 1))
    tracker.record(Usage(100, 100))
    assert (usage.tokens_in, usage.tokens_out) == (4, 5)


def test_build_limiter_refuses_a_bad_limit_string():
    with pytest.raises(ValueError, match="RATE_LIMIT_PER_VISITOR"):
        build_limiter(Settings(_env_file=None, rate_limit_per_visitor="thirty a minute"))  # pyright: ignore[reportCallIssue]


def _request(*, peer: str, forwarded: str | None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def test_ac_16_16_without_the_proxy_a_client_header_cannot_change_the_key():
    request = _request(peer="10.0.0.5", forwarded="1.2.3.4")
    assert client_ip(request, behind_proxy=False) == "10.0.0.5"


def test_ac_16_16_behind_the_proxy_only_its_appended_hop_counts():
    plain = _request(peer="100.64.0.1", forwarded="203.0.113.9")
    spoofed = _request(peer="100.64.0.1", forwarded="1.1.1.1, 2.2.2.2, 203.0.113.9")
    assert client_ip(plain, behind_proxy=True) == client_ip(spoofed, behind_proxy=True) == "203.0.113.9"


def test_ac_16_16_behind_the_proxy_without_the_header_the_peer_is_used():
    assert client_ip(_request(peer="100.64.0.1", forwarded=None), behind_proxy=True) == "100.64.0.1"
