"""Opt-in live tests of the LABEL and ASSESS_STEPS calls against the real Azure deployment (specs 19, 26).

Why: the unit tests prove the calls and their grounding against scripted replies; only a real call
proves that Azure accepts the strict schemas, that the model copies its evidence from the right step
and that it picks routes from the company catalogue (reusing an existing internal tool before a build).
What: each test runs one call on the shared EU cost-review profile with the real client from
`create_llm` (settings from `backend/.env`, your `az login` locally; cache off) and the real NIG
configuration, prints what was kept (labels; per-step fit and route) and checks that enough survived.
Must not: run in CI or by default (marked `live`, skipped unless `RUN_LIVE=1`), or log profile text.
Covers AC-19.17 / AC-19.18 and AC-26.2 / AC-26.3 for real.
"""

from __future__ import annotations

import os

import pytest

from app.core.settings import Settings
from app.services.process_discovery.artifacts.labels.labels import run_labels
from app.services.process_discovery.artifacts.step_assessment.route import route_summary
from app.services.process_discovery.artifacts.step_assessment.steps import run_step_assessment
from app.services.process_discovery.artifacts.value import compute_value
from app.services.process_discovery.llm import create_llm
from tests.fixtures.assessment.profiles import load_profile, nig_config, nig_vocabulary

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="live Azure call; set RUN_LIVE=1"),
]


async def test_live_label_keeps_grounded_labels() -> None:
    llm = create_llm(Settings(llm_cache_enabled=False))  # pyright: ignore[reportCallIssue]
    try:
        labels, dropped = await run_labels(load_profile("eu"), llm, vocab=nig_vocabulary())
    finally:
        await llm.aclose()
    print(f"\ndropped={dropped}")
    for step in labels:
        print(f"step {step.step}: inputs={[(i.name, i.format) for i in step.inputs]} "
              f"decisions={[(d.text, d.kind) for d in step.decisions]}")  # fmt: skip
    assert sum(len(s.inputs) for s in labels) >= 6  # of 8 inputs
    assert sum(len(s.decisions) for s in labels) >= 1


async def test_live_assess_steps_rates_every_step_from_the_catalogue() -> None:
    config = nig_config()
    profile = load_profile("eu")
    llm = create_llm(Settings(llm_cache_enabled=False))  # pyright: ignore[reportCallIssue]
    try:
        ratings, dropped, _motivations = await run_step_assessment(
            profile, llm, config.solutions, vocab=nig_vocabulary()
        )
    finally:
        await llm.aclose()
    route = route_summary(ratings, compute_value(profile, [], config.rates), config.solutions)
    print(f"\ndropped={dropped}")
    for r in ratings:
        print(f"step {r.step} {r.name}: fit={r.fit} route={r.route_id} evidence_key={r.evidence_key}")
    print(f"route: start={route.start_with} later={route.later} fix_first={route.fix_first} "
          f"stay={route.stay_with_people} not_routed={route.not_routed}\nheadline: {route.headline}")  # fmt: skip
    assert sum(r.fit is not None for r in ratings) >= 4
    assert any(r.route_id for r in ratings)
