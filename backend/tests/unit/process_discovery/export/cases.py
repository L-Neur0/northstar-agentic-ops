"""Finished sessions for the report tests: the EU cost review after a scripted *Finish*, and a thin one (spec 20 §7).

Why: the report model, the PDF and the routes must all be tested on the same finished session,
built the way *Finish* builds it (the real `assess` over the spec 18/19/26 worked replies), so the
tests check the report the expert would really get, not a hand-typed copy that drifts.
What: `eu_assessment()` (run once and cached; callers get copies), `eu_session(**update)`,
`thin_session()`, `ORG`, `VOCAB`, `CATALOGUE` (the vendor-neutral example catalogue, placeholder).
Must not: call Azure or edit the shared fixtures.
"""

from __future__ import annotations

import asyncio
from functools import cache
from typing import Any

from app.models.process_discovery_schemas import Assessment, Phase, Profile, ReportState, Session, SessionStatus
from app.services.process_discovery.artifacts.assess import assess
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.llm import CallType
from tests.fixtures.assessment.profiles import load_profile, nig_config, nig_vocabulary
from tests.fixtures.assessment.replies import map_reply, opportunities_reply
from tests.fixtures.assessment_19.cases import LABEL_REPLY, STEPS_REPLY, example_catalogue

AT = "2026-11-20T10:00:00+00:00"
ORG = nig_config().organisation
VOCAB = nig_vocabulary()
CATALOGUE = example_catalogue()


def scripted_llm() -> FakeLLM:
    return FakeLLM({
        CallType.OPPORTUNITIES: [opportunities_reply()],
        CallType.MAP: [map_reply()],
        CallType.LABEL: [LABEL_REPLY],
        CallType.ASSESS_STEPS: [STEPS_REPLY],
    })  # fmt: skip


@cache
def _eu_assessment_json() -> str:
    config = nig_config()
    assessment, _ = asyncio.run(
        assess(
            load_profile("eu"),
            None,
            scripted_llm(),
            config.rates,
            config.readiness,
            AT,
            catalogue=CATALOGUE,
            vocab=VOCAB,
        )  # fmt: skip
    )
    return assessment.model_dump_json(by_alias=True)


def eu_assessment() -> Assessment:
    return Assessment.model_validate_json(_eu_assessment_json())


def eu_session(profile: dict[str, Any] | None = None, **update: Any) -> Session:
    data: dict[str, Any] = {
        "owner_id": "owner-a",
        "created_at": AT,
        "updated_at": AT,
        "finished_at": AT,
        "status": "finished",
        "phase": "finished",
        "profile": Profile.model_validate(profile or load_profile("eu")),
        "assessment": eu_assessment(),
        "report": ReportState(),
    }
    data.update(update)
    return Session(**data)


def thin_session() -> Session:
    """Finished with almost nothing: one named step, no assessment."""
    profile = {"process": {"name": "Tiny", "substep_count": 1, "substeps": [{"name": "Do it"}]}}
    return Session(owner_id="owner-a", created_at=AT, updated_at=AT, finished_at=AT, status=SessionStatus.FINISHED,
                   phase=Phase.FINISHED, profile=Profile.model_validate(profile))  # fmt: skip
