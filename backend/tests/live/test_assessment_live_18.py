"""Opt-in live tests of the OPPORTUNITIES and MAP calls against the real Azure deployment (spec 18 §7).

Why: the unit tests prove grounding on scripted replies, but only a real call proves that Azure
accepts both strict schemas and that the model's quotes and step numbers survive the code checks.
What: the cost-review EU fixture goes through `run_opportunities` and `run_map` with the real client
from `create_llm` (settings from `backend/.env`, your `az login` locally; cache off). Each test prints
what survived grounding and checks the minimum a usable report needs.
Must not: run in CI or by default (marked `live`, skipped unless `RUN_LIVE=1`), or print profile text.
Covers AC-18.2 for real (strict schemas accepted), AC-18.5 and AC-18.19 on a real reply.
"""

from __future__ import annotations

import os

import pytest

from app.core.settings import Settings
from app.services.process_discovery.artifacts.analysis.analysis import run_opportunities
from app.services.process_discovery.artifacts.diagram.diagram import run_map
from app.services.process_discovery.llm import create_llm
from tests.fixtures.assessment.profiles import load_profile, nig_config, nig_vocabulary

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="live Azure call; set RUN_LIVE=1"),
]


async def test_live_opportunities_survive_grounding():
    llm = create_llm(Settings(llm_cache_enabled=False))  # pyright: ignore[reportCallIssue]
    try:
        result = await run_opportunities(load_profile("eu"), llm, nig_config().rates, vocab=nig_vocabulary())
    finally:
        await llm.aclose()
    print(
        f"\nOPPORTUNITIES kept={len(result.opportunities)} stay_human={len(result.stay_human)} "
        f"dropped={result.dropped} types={[o.type.value for o in result.opportunities]}"
    )
    assert result.opportunities, "no opportunity survived grounding"
    assert result.summary


async def test_live_map_is_grounded():
    llm = create_llm(Settings(llm_cache_enabled=False))  # pyright: ignore[reportCallIssue]
    try:
        diagram = await run_map(load_profile("eu"), llm, vocab=nig_vocabulary())
    finally:
        await llm.aclose()
    types = [n.type for n in diagram.nodes]
    print(
        f"\nMAP simplified={diagram.simplified} nodes={len(diagram.nodes)} "
        f"gateways={types.count('gateway')} flows={len(diagram.flows)} lanes={len(diagram.lanes)} "
        f"data_objects={len(diagram.data_objects)} data_stores={len(diagram.data_stores)}"
    )
    assert types.count("task") == 5
