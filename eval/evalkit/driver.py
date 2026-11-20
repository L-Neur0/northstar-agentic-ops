"""How the runner talks to the product: the real API, in process or over a URL (spec 24 §3.5).

Why: the evaluation must measure what an expert's browser gets, so every action goes through the
HTTP API (specs 15, 17, 20), never through engine internals. In process (the default) the same app
runs on the memory store with raised limits, so nothing is paced and the stored session and log
lines can be read; over a URL the runner must stay under the demo's rate limits (spec 16).
What: the `Driver` protocol; `InProcessDriver` (the real `create_app` with its lifespan, an
`httpx.ASGITransport` client, the stored session from the memory store); `UrlDriver` (real HTTP,
one visitor key per persona, a `Pacer` of at most 20 calls a minute per key and 60 in total, one
wait on a 429 then `RateLimited`); `LogCapture`, a logging handler that keeps the `llm_call` and
`interview_turn` lines tagged with the persona and the API call they came from.
Must not: write to a session except through the API, use a workspace code, or import the engine
beyond `app.main`, `app.core.settings` and `llm.py` (AC-24.29).
Spec 24 §3.5; AC-24.7, AC-24.8.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import secrets
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.core.settings import Settings
from app.main import create_app
from app.services.process_discovery.llm import LLM

PERSONA: ContextVar[str] = ContextVar("eval_persona", default="")
CALL: ContextVar[str] = ContextVar("eval_call", default="")
CAPTURED = ("llm_call", "interview_turn")
_STANDARD = frozenset(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class RateLimited(RuntimeError):
    """A second 429 for one persona: that persona ends as `rate_limited` (URL mode)."""


class LogCapture(logging.Handler):
    """Keeps every `llm_call` and `interview_turn` line as a dict, tagged with persona and call id."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.msg not in CAPTURED:
            return
        fields = {k: v for k, v in vars(record).items() if k not in _STANDARD and not k.startswith("_")}
        self.records.append({"event": record.msg, "persona": PERSONA.get(), "call": CALL.get(), **fields})

    def for_call(self, call: str) -> list[dict[str, Any]]:
        return [r for r in self.records if r["call"] == call]

    def for_persona(self, persona: str) -> list[dict[str, Any]]:
        return [r for r in self.records if r["persona"] == persona]

    def install(self) -> None:
        logger = logging.getLogger("app")
        if self not in logger.handlers:
            logger.addHandler(self)
        logger.setLevel(logging.INFO)


class Driver(Protocol):
    """The API calls the runner makes. Every method is one HTTP request."""

    @property
    def capture(self) -> LogCapture | None: ...

    async def create(self, display_name: str) -> dict[str, Any]: ...
    async def get(self, session_id: str) -> dict[str, Any]: ...
    async def send(self, session_id: str, text: str) -> tuple[dict[str, Any], float]: ...
    async def upload(self, session_id: str, path: Path) -> tuple[dict[str, Any], float]: ...
    async def finish(self, session_id: str) -> tuple[int, dict[str, Any], float]: ...
    async def report(self, session_id: str) -> tuple[dict[str, Any], bytes]: ...
    async def ideas(self, session_id: str) -> list[dict[str, Any]]: ...
    async def stored(self, session_id: str) -> dict[str, Any] | None: ...
    def last_call(self, session_id: str) -> str: ...


def new_visitor_key() -> str:
    """22 random URL-safe characters (the shortest key the API accepts)."""
    return secrets.token_urlsafe(32)[:22]


class _HttpDriver:
    """The shared HTTP calls; subclasses supply the client and the pacing."""

    capture: LogCapture | None = None

    def __init__(self) -> None:
        self._keys: dict[str, str] = {}
        self._last: dict[str, str] = {}
        self.client: httpx.AsyncClient

    async def _request(self, key: str, method: str, url: str, **kwargs: Any) -> httpx.Response:
        call = uuid.uuid4().hex
        token = CALL.set(call)
        try:
            headers = {"X-Visitor-Key": key, "X-Correlation-Id": call}
            response = await self._send(key, method, url, headers=headers, **kwargs)
        finally:
            CALL.reset(token)
        session_id = url.split("/")[3] if url.count("/") >= 3 else ""
        self._last[session_id] = call
        return response

    async def _send(self, key: str, method: str, url: str, **kwargs: Any) -> httpx.Response:
        return await self.client.request(method, url, **kwargs)

    def last_call(self, session_id: str) -> str:
        return self._last.get(session_id, "")

    def _key(self, session_id: str) -> str:
        return self._keys[session_id]

    async def create(self, display_name: str) -> dict[str, Any]:
        key = new_visitor_key()
        response = await self._request(key, "POST", "/api/sessions", json={"displayName": display_name[:40]})
        response.raise_for_status()
        body = response.json()
        self._keys[body["id"]] = key
        return body

    async def get(self, session_id: str) -> dict[str, Any]:
        response = await self._request(self._key(session_id), "GET", f"/api/sessions/{session_id}")
        response.raise_for_status()
        return response.json()

    async def send(self, session_id: str, text: str) -> tuple[dict[str, Any], float]:
        started = time.monotonic()
        response = await self._request(
            self._key(session_id), "POST", f"/api/sessions/{session_id}/messages", json={"text": text}
        )
        seconds = time.monotonic() - started
        response.raise_for_status()
        return response.json(), seconds

    async def upload(self, session_id: str, path: Path) -> tuple[dict[str, Any], float]:
        started = time.monotonic()
        files = {"file": (path.name, path.read_bytes(), "text/markdown")}
        response = await self._request(
            self._key(session_id), "POST", f"/api/sessions/{session_id}/documents", files=files
        )
        seconds = time.monotonic() - started
        response.raise_for_status()
        return response.json(), seconds

    async def finish(self, session_id: str) -> tuple[int, dict[str, Any], float]:
        started = time.monotonic()
        response = await self._request(self._key(session_id), "POST", f"/api/sessions/{session_id}/finish")
        seconds = time.monotonic() - started
        if response.status_code not in (200, 409):
            response.raise_for_status()
        return response.status_code, response.json(), seconds

    async def report(self, session_id: str) -> tuple[dict[str, Any], bytes]:
        key = self._key(session_id)
        report = await self._request(key, "GET", f"/api/sessions/{session_id}/report")
        report.raise_for_status()
        pdf = await self._request(key, "GET", f"/api/sessions/{session_id}/report.pdf")
        pdf.raise_for_status()
        return report.json(), pdf.content

    async def ideas(self, session_id: str) -> list[dict[str, Any]]:
        response = await self._request(self._key(session_id), "GET", "/api/ideas")
        response.raise_for_status()
        return list(response.json().get("ideas") or [])

    async def stored(self, session_id: str) -> dict[str, Any] | None:
        return None


def in_process_settings(base: Settings | None = None, **overrides: Any) -> Settings:
    """The app's settings for an in-process run: memory store, stage local, raised limits, no budget."""
    values = (base or Settings()).model_dump()
    values.update(
        store="memory",
        deployment_stage="local",
        rate_limit_per_visitor="10000/minute",
        rate_limit_per_ip="10000/minute",
        daily_token_budget=0,
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


class InProcessDriver(_HttpDriver):
    """The real app in this process (spec 24 §3.5 in-process mode). Use as an async context manager."""

    def __init__(self, settings: Settings, llm: LLM | None = None, capture: LogCapture | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.app = create_app(settings, llm=llm)
        self.capture = capture or LogCapture()
        self._lifespan: contextlib.AbstractAsyncContextManager[Any] | None = None

    async def __aenter__(self) -> InProcessDriver:
        self.capture.install()  # pyright: ignore[reportOptionalMemberAccess]
        self._lifespan = self.app.router.lifespan_context(self.app)
        await self._lifespan.__aenter__()
        transport = httpx.ASGITransport(app=self.app)
        self.client = httpx.AsyncClient(transport=transport, base_url="http://eval.local", timeout=600)
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.client.aclose()
        if self._lifespan is not None:
            await self._lifespan.__aexit__(None, None, None)

    async def stored_model(self, session_id: str) -> Any:
        """The stored `Session` model (for seeding, spec 24 §3.12)."""
        owner = hashlib.sha256(self._key(session_id).encode("ascii")).hexdigest()
        return await self.app.state.store.get_session(owner, session_id)

    async def stored(self, session_id: str) -> dict[str, Any] | None:
        session = await self.stored_model(session_id)
        return session.model_dump(mode="json", by_alias=True) if session is not None else None


class Pacer:
    """At most `per_key` calls a `window` per visitor key and `total` in all; waits (never drops) a call."""

    def __init__(
        self,
        per_key: int = 20,
        total: int = 60,
        window: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.per_key, self.total, self.window = per_key, total, window
        self._clock, self._sleep = clock, sleep
        self._all: deque[float] = deque()
        self._keys: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def wait(self, key: str) -> None:
        async with self._lock:
            while True:
                now = self._clock()
                for times in (self._all, self._keys[key]):
                    while times and times[0] <= now - self.window:
                        times.popleft()
                blocked = [
                    t[0] for t, cap in ((self._all, self.total), (self._keys[key], self.per_key)) if len(t) >= cap
                ]
                if not blocked:
                    self._all.append(now)
                    self._keys[key].append(now)
                    return
                await self._sleep(max(blocked) + self.window - now)


class UrlDriver(_HttpDriver):
    """A running app over HTTP (spec 24 §3.5 URL mode): paced, one wait on a 429, then `RateLimited`."""

    def __init__(
        self,
        base_url: str,
        *,
        pacer: Pacer | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__()
        self.pacer = pacer or Pacer()
        self._sleep = sleep
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), transport=transport, timeout=300)

    async def __aenter__(self) -> UrlDriver:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.client.aclose()

    async def _send(self, key: str, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(2):
            await self.pacer.wait(key)
            response = await self.client.request(method, url, **kwargs)
            if response.status_code != 429:
                return response
            if attempt == 0:
                try:
                    wait = float(response.headers.get("retry-after", "30"))
                except ValueError:
                    wait = 30.0
                await self._sleep(wait)
        raise RateLimited(url)
