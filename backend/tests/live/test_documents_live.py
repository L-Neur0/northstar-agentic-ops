"""Opt-in live test of the READ_DOCUMENT call against the real Azure deployment (spec 17 §3.7, §7).

Why: the unit tests prove the document pipeline against scripted replies, but only a real call
proves that Azure accepts the registry-generated strict schema, that the model fills it with
quotes copied from the text, and that enough of those quotes survive the code quote check.
What: one tiny procedure (a few lines, in the test) goes through `read_document` with the real
client from `create_llm` (settings from `backend/.env`, your `az login` locally; no keys, cache
off). It prints the offered, kept and skipped counts and checks that the reading succeeded and
that at least one quoted proposal survived.
Must not: run in CI or by default (marked `live`, skipped unless `RUN_LIVE=1`), or log the text.
Covers AC-17.21 (strict schema accepted for real), AC-17.32 (real reply through the pipeline) and the
§3.19 item 4 assumption (`test_image_read`: the deployment reads an image under the strict schema).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.config import load_company_config
from app.core.settings import Settings
from app.models.process_discovery_schemas import Session
from app.services.process_discovery.documents import read_document
from app.services.process_discovery.domain.field_spec import Vocabulary
from app.services.process_discovery.llm import create_llm

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="live Azure call; set RUN_LIVE=1"),
]

AT = "2026-11-19T10:00:00+00:00"
NIG = Path(__file__).resolve().parents[3] / "config" / "nig"
PROCEDURE = (
    "Monthly cost review: procedure\n"
    "Owner: Head of Controlling\n"
    "The review starts once month-end close is completed in the ledger. It runs every month.\n"
    "Step 1 | Export actuals | The cost controller exports actual costs from SAP S/4HANA into the review workbook.\n"
    "Step 2 | Compare with budget | The cost controller compares actuals with the budget in Excel.\n"
    "Step 3 | Send the cost report | The cost controller publishes the cost report for the CFO in Power BI.\n"
    "The process ends with the monthly cost report.\n"
)


async def test_live_read_document_keeps_quoted_proposals():
    config = load_company_config(NIG)
    vocab = Vocabulary(taxonomy=config.taxonomy, regions=config.organisation.regions, wording=config.wording)
    llm = create_llm(Settings(llm_cache_enabled=False))  # pyright: ignore[reportCallIssue]
    try:
        result = await read_document(
            Session(owner_id="live-test", created_at=AT, updated_at=AT),
            filename="procedure.txt",
            data=PROCEDURE.encode("utf-8"),
            llm=llm,
            config=config.documents,
            document_id="d1",
            now=AT,
            vocab=vocab,
        )
    finally:
        await llm.aclose()
    report = result.report
    print(
        f"\noffered={report.offered.model_dump()} kept={report.kept.model_dump()} "
        f"skipped={[(s.key, s.reason, s.items) for s in report.skipped]}"
    )
    assert report.outcome == "read"
    assert report.kept.fields + report.kept.steps + report.kept.cells > 0


async def test_image_read():
    """Spec 17 §3.19 item 4: the `app-chat` deployment reads one image with the strict image schema."""
    from app.services.process_discovery.documents.context import ReadingContext

    config = load_company_config(NIG)
    vocab = Vocabulary(taxonomy=config.taxonomy, regions=config.organisation.regions, wording=config.wording)
    llm = create_llm(Settings(llm_cache_enabled=False))  # pyright: ignore[reportCallIssue]
    data = (Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "planning_tool.png").read_bytes()
    try:
        result = await read_document(
            Session(owner_id="live-test", created_at=AT, updated_at=AT),
            filename="planning_tool.png",
            data=data,
            llm=llm,
            config=config.documents,
            document_id="d1",
            now=AT,
            vocab=vocab,
            context=ReadingContext(phase="steps"),
        )
    finally:
        await llm.aclose()
    assert result.report.outcome == "read" and result.from_image
    assert result.record.text.startswith("Image: ") and "Planning tool" in result.record.text
