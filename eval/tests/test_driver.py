"""The drivers: in-process limits and the URL pacer (spec 24 §3.5; AC-24.7, AC-24.8).

Why: the runner must never trip the product's rate limits or budget: in process they are raised,
over a URL it paces itself and waits once on a 429. What: the in-process settings; the pacer with a
fake clock; the URL driver over a fake transport that answers 429. Must not: open a network
connection or call a model.
"""

from __future__ import annotations

import httpx

from app.core.settings import Settings
from eval.evalkit.driver import Pacer, RateLimited, UrlDriver, in_process_settings


def test_ac_24_7_in_process_settings_raise_limits_and_drop_the_budget():
    settings = in_process_settings(Settings(_env_file=None, store="cosmos", cosmos_endpoint="https://x"))  # pyright: ignore[reportCallIssue]
    assert settings.store == "memory" and settings.deployment_stage == "local"
    assert settings.rate_limit_per_visitor == "10000/minute" and settings.rate_limit_per_ip == "10000/minute"
    assert settings.daily_token_budget == 0


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


async def test_ac_24_8_at_most_20_a_minute_per_key():
    clock = FakeClock()
    pacer = Pacer(clock=clock, sleep=clock.sleep)
    for _ in range(21):
        await pacer.wait("key-a")
    assert clock.slept == [60.0] and clock.now == 60.0


async def test_ac_24_8_at_most_60_a_minute_in_total():
    clock = FakeClock()
    pacer = Pacer(clock=clock, sleep=clock.sleep)
    times: list[float] = []
    for i in range(61):
        await pacer.wait(f"key-{i % 4}")
        times.append(clock.now)
    assert times[59] == 0.0 and times[60] == 60.0
    window = [t for t in times if t < 60.0]
    assert len(window) == 60


async def test_ac_24_8_a_429_waits_once_then_ends_the_persona():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/sessions":
            return httpx.Response(201, json={"id": "s1", "status": "active"})
        return httpx.Response(429, headers={"retry-after": "7"}, json={"code": "rate_limited"})

    clock = FakeClock()
    driver = UrlDriver(
        "http://demo.test",
        pacer=Pacer(clock=clock, sleep=clock.sleep),
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
    )
    async with driver:
        await driver.create("p")
        try:
            await driver.send("s1", "hello")
        except RateLimited:
            pass
        else:
            raise AssertionError("expected RateLimited")
    assert clock.slept == [7.0] and calls.count("/api/sessions/s1/messages") == 2
