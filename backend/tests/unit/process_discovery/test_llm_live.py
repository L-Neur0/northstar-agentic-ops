"""Opt-in live smoke test of the model client against the real Azure deployment (spec 11 §7).

Why: the unit tests prove the client's rules against a stub, but only a real call proves that the
identity-based auth works, that the API version is right and that Azure accepts the strict schema
`strict_json_schema` produces (spec 11 open question Q3).
What: one tiny `generate_text` and one tiny `generate_structured` call through `create_llm`, using
the settings from `backend/.env` (your `az login` locally; no keys). Marked `live` and skipped
unless `RUN_LIVE=1`; never run in CI. Covers AC-11.2/AC-11.3 (auth), AC-11.5 and AC-11.21 for real.
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel, Field

from app.core.settings import Settings
from app.services.process_discovery.llm import CallType, create_llm

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="live Azure call; set RUN_LIVE=1"),
]


class Capital(BaseModel):
    """Has a default, a description and an optional field: does strict mode accept them (spec 11 Q3)?"""

    city: str = Field(description="The capital city")
    country: str = "unknown"
    population_millions: float | None = None


async def test_a_real_text_and_structured_call():
    """One text and one strict-schema call; the cache is off so both really reach Azure."""
    settings = Settings(llm_cache_enabled=False)  # pyright: ignore[reportCallIssue]
    llm = create_llm(settings)
    try:
        text = await llm.generate_text(
            CallType.GUIDE, [{"role": "user", "content": "Reply with the single word: ready"}], max_tokens=2000
        )
        assert "ready" in text.lower()
        capital = await llm.generate_structured(
            Capital,
            CallType.MAP,
            [{"role": "user", "content": "What is the capital of France? Answer in JSON."}],
            max_tokens=2000,
        )
        assert capital.city.lower() == "paris"
    finally:
        await llm.aclose()
