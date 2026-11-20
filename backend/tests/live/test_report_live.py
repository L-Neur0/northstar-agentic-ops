"""Opt-in live test of *Finish* and the PDF against the real Azure deployment (spec 20).

Why: the unit and API tests prove the orchestration and the layout against scripted replies; only
a real run proves that the four calls succeed together within their timeouts on the real model and
that the PDF of a real assessment lays out. It also leaves a sample PDF for review.
What: finishes the EU cost-review profile through `DiscoveryService.finish` with the real client
from `create_llm` (settings from `backend/.env`, your `az login` locally; cache off) and the real NIG
configuration, prints the four outcomes, builds the PDF through `report_pdf` and writes it to
`tests/fixtures/assessment/cost_review_eu_report.pdf`, printing its page count.
Must not: run in CI or by default (marked `live`, skipped unless `RUN_LIVE=1`), or log profile text.
Covers AC-20.1 and AC-20.32 for real.
"""

from __future__ import annotations

import io
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.core.settings import Settings
from app.models.process_discovery_schemas import Message, Profile, Session
from app.services.process_discovery.llm import create_llm
from app.services.process_discovery.service import DiscoveryService, build_context
from app.services.store.memory import MemoryRepository
from tests.fixtures.assessment.profiles import NIG, load_profile, nig_config

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="live Azure call; set RUN_LIVE=1"),
]

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "assessment" / "cost_review_eu_report.pdf"
OWNER = "owner-live-" + "a" * 54


async def test_live_finish_assesses_the_eu_cost_review_and_writes_the_pdf() -> None:
    settings = Settings(llm_cache_enabled=False)  # pyright: ignore[reportCallIssue]
    company = nig_config()
    llm = create_llm(settings)
    repo = MemoryRepository()
    now = datetime.now(UTC).isoformat()
    service = DiscoveryService(
        repo, llm, build_context(company, settings), None, clock=lambda: datetime.now(UTC).isoformat(),
        company=company, config_dir=NIG, assessment_timeout=settings.assessment_call_timeout_seconds,
    )  # fmt: skip
    seeded = await repo.create_session(
        Session(owner_id=OWNER, created_at=now, updated_at=now, phase="review",  # pyright: ignore[reportArgumentType]
                profile=Profile.model_validate(load_profile("eu")),
                messages=[Message.model_validate({"role": "agent", "text": "Welcome", "at": now})])
    )  # fmt: skip
    started = datetime.now(UTC)
    try:
        finished = await service.finish(OWNER, seeded.id)
    finally:
        await llm.aclose()
    seconds = (datetime.now(UTC) - started).total_seconds()
    assert finished.assessment is not None
    outcomes = dict(finished.assessment.outcomes)
    value = finished.assessment.value
    print(f"\nfinish took {seconds:.1f} s; outcomes={outcomes}")
    print(f"hours={value.hours_per_year if value else None}; opportunities={len(finished.assessment.opportunities)}")
    pdf, filename = await service.report_pdf(OWNER, seeded.id)
    OUT.write_bytes(pdf)
    pages = len(PdfReader(io.BytesIO(pdf)).pages)
    print(f"{filename}: {pages} pages, {len(pdf)} bytes -> {OUT}")
    assert set(outcomes) == {"opportunities", "diagram", "labels", "steps"}
    assert pdf.startswith(b"%PDF") and pages > 3
