"""Unit tests for the assessment run of *Finish*: four calls in parallel, each bounded and degrading on its own (spec 20 §3.1).

Why: the report must survive any one call failing or hanging, a re-run must not pay for calls whose
input did not change, and a failed refresh must never wipe what a specialist already reviewed.
What: `assess` on the EU cost-review fixture with a `FakeLLM` scripted with the spec 18/19/26
worked replies; a barrier double proves the calls really overlap; a slow double proves the
per-call timeout; scripted errors prove each part degrades alone.
Must not: call Azure, or patch `assess` itself.
Covers AC-20.1 to AC-20.12, AC-20.45, AC-20.49.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import pytest

from app.models.process_discovery_schemas import Assessment
from app.services.process_discovery.artifacts.assess import assess
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.llm import CallType, LLMUnavailableError
from tests.fixtures.assessment.profiles import load_profile, nig_config, nig_vocabulary
from tests.fixtures.assessment.replies import map_reply, opportunities_reply
from tests.fixtures.assessment_19.cases import LABEL_REPLY, STEPS_REPLY, example_catalogue

NOW = "2026-11-20T10:00:00+00:00"
ALL = (CallType.OPPORTUNITIES, CallType.MAP, CallType.LABEL, CallType.ASSESS_STEPS)


def _replies() -> dict[CallType, Any]:
    return {
        CallType.OPPORTUNITIES: opportunities_reply(),
        CallType.MAP: map_reply(),
        CallType.LABEL: LABEL_REPLY,
        CallType.ASSESS_STEPS: STEPS_REPLY,
    }


def _llm(**override: Any) -> FakeLLM:
    replies = _replies()
    for name, reply in override.items():
        replies[CallType[name]] = reply
    return FakeLLM({k: [v] for k, v in replies.items()})


async def _run(llm: Any, *, profile: dict[str, Any] | None = None, previous: Assessment | None = None,
               refresh: bool = False, timeout: float = 5.0, catalogue: Any = None):  # fmt: skip
    config = nig_config()
    return await assess(
        profile or load_profile("eu"), previous, llm, config.rates, config.readiness, NOW,
        catalogue=catalogue or example_catalogue(), vocab=nig_vocabulary(), refresh=refresh, timeout=timeout,
    )  # fmt: skip


def _words(logs: list[Any]) -> dict[str, str]:
    return {o.part: o.outcome for o in logs}


async def _first() -> Assessment:
    assessment, _ = await _run(_llm())
    return assessment


async def test_ac_20_1_finish_makes_one_call_of_each_kind_and_all_are_generated():
    llm = _llm()
    assessment, logs = await _run(llm)
    assert [len(llm.calls_of(c)) for c in ALL] == [1, 1, 1, 1]
    assert assessment.outcomes == dict.fromkeys(("opportunities", "diagram", "labels", "steps"), "generated")
    assert _words(logs) == dict.fromkeys(("opportunities", "diagram", "labels", "steps"), "generated")
    assert assessment.value is not None and assessment.value.hours_per_year == 342
    assert assessment.step_assessment is not None and assessment.step_assessment.route is not None
    assert assessment.step_assessment.route.start_with == [2, 3]
    assert assessment.generated_at == NOW and assessment.steps_hash


class _Barrier:
    """Every call waits until all four have started: run one after another, this deadlocks."""

    def __init__(self, inner: FakeLLM, parties: int = 4) -> None:
        self.inner = inner
        self.barrier = asyncio.Barrier(parties)

    async def generate_structured(self, *args: Any, **kwargs: Any) -> Any:
        await self.barrier.wait()
        return await self.inner.generate_structured(*args, **kwargs)


async def test_ac_20_2_the_four_calls_really_run_concurrently():
    assessment, _ = await asyncio.wait_for(_run(_Barrier(_llm())), timeout=5)
    assert set(assessment.outcomes.values()) == {"generated"}


async def test_ac_20_3_matching_fingerprints_reuse_every_ai_part_and_recompute_the_code_parts():
    first = await _first()
    stale = first.model_copy(update={"value": None, "readiness": None, "path": None})
    llm = FakeLLM()
    again, logs = await _run(llm, previous=stale)
    assert llm.calls == []
    assert all(o.reused for o in logs)
    assert again.opportunities == first.opportunities and again.diagram == first.diagram
    assert again.value == first.value and again.readiness == first.readiness and again.path == first.path


async def test_ac_20_4_only_the_parts_whose_input_changed_run():
    first = await _first()
    assert first.diagram is not None
    map_changed = first.model_copy(update={"diagram": first.diagram.model_copy(update={"steps_hash": "old"})})
    llm = FakeLLM({CallType.MAP: [map_reply()]})
    await _run(llm, previous=map_changed)
    assert [c.call_type for c in llm.calls] == [CallType.MAP]

    profile = load_profile("eu")
    profile["process"]["substeps"][2]["pain_points"].append("the threshold check is slow")
    llm = FakeLLM({c: [_replies()[c]] for c in ALL if c is not CallType.MAP})
    await _run(llm, previous=first, profile=profile)
    assert sorted(c.call_type for c in llm.calls) == sorted([CallType.OPPORTUNITIES, CallType.LABEL,
                                                             CallType.ASSESS_STEPS])  # fmt: skip

    llm = FakeLLM({CallType.ASSESS_STEPS: [STEPS_REPLY]})
    await _run(llm, previous=first, catalogue=example_catalogue(version="test-2"))
    assert [c.call_type for c in llm.calls] == [CallType.ASSESS_STEPS]


async def test_ac_20_5_refresh_runs_all_four_even_when_nothing_changed():
    first = await _first()
    llm = _llm()
    await _run(llm, previous=first, refresh=True)
    assert [len(llm.calls_of(c)) for c in ALL] == [1, 1, 1, 1]


async def test_ac_20_6_a_failed_opportunities_call_does_not_stop_the_others():
    assessment, logs = await _run(_llm(OPPORTUNITIES=LLMUnavailableError(503)))
    assert assessment.outcomes == {"opportunities": "failed", "diagram": "generated", "labels": "generated",
                                   "steps": "generated"}  # fmt: skip
    assert assessment.opportunities == [] and assessment.summary == ""
    assert assessment.value is not None and assessment.value.complete and assessment.value.hours_per_year == 342
    assert _words(logs)["opportunities"] == "failed"


async def test_ac_20_7_an_unusable_map_reply_gives_the_simplified_map():
    assessment, logs = await _run(_llm(MAP=""))
    assert assessment.diagram is not None and assessment.diagram.simplified
    assert assessment.outcomes["diagram"] == "fallback" and _words(logs)["diagram"] == "fallback"


async def test_ac_20_7_a_failed_map_call_gives_the_linear_map():
    assessment, logs = await _run(_llm(MAP=LLMUnavailableError(503)))
    assert assessment.diagram is not None and assessment.diagram.simplified
    assert [n.step_index for n in assessment.diagram.nodes if n.type == "task"] == [1, 2, 3, 4, 5]
    assert assessment.outcomes["diagram"] == "fallback" and _words(logs)["diagram"] == "failed_linear"


async def test_ac_20_8_a_failed_label_call_leaves_data_and_rules_unknown():
    assessment, _ = await _run(_llm(LABEL=LLMUnavailableError(503)))
    assert assessment.labels == [] and assessment.outcomes["labels"] == "failed"
    assert assessment.readiness is not None
    levels = {d.key: d.level for d in assessment.readiness.dimensions}
    assert levels["data"] == levels["rules"] == "unknown"
    assert assessment.outcomes["opportunities"] == assessment.outcomes["steps"] == "generated"


class _Slow:
    """MAP never answers in time; the other calls answer at once."""

    def __init__(self, inner: FakeLLM) -> None:
        self.inner = inner

    async def generate_structured(self, model_cls: Any, call_type: CallType, *args: Any, **kwargs: Any) -> Any:
        if call_type is CallType.MAP:
            await asyncio.sleep(5)
        return await self.inner.generate_structured(model_cls, call_type, *args, **kwargs)


async def test_ac_20_9_a_call_slower_than_the_timeout_is_cancelled_and_degrades():
    llm = _llm()
    assessment, logs = await asyncio.wait_for(_run(_Slow(llm), timeout=0.05), timeout=3)
    assert _words(logs)["diagram"] == "timeout_linear" and assessment.outcomes["diagram"] == "fallback"
    assert assessment.outcomes["opportunities"] == "generated"


async def test_ac_20_10_a_failed_refresh_keeps_what_was_stored():
    first = await _first()
    down = LLMUnavailableError(503)
    llm = FakeLLM({c: [down] for c in ALL})
    again, logs = await _run(llm, previous=first, refresh=True)
    assert again.opportunities == first.opportunities and again.labels == first.labels
    assert again.diagram == first.diagram and again.step_assessment is not None
    assert again.outcomes == first.outcomes
    assert set(_words(logs).values()) == {"refresh_failed"}


@pytest.mark.parametrize("seed", range(6))
async def test_ac_20_11_an_unexpected_exception_in_any_part_never_escapes(seed: int):
    rng = random.Random(seed)
    errors: list[Exception] = [RuntimeError("bug"), KeyError("x"), ValueError("bad"), ZeroDivisionError()]
    replies: dict[CallType, Any] = _replies()
    for call in rng.sample(ALL, rng.randint(1, 4)):
        replies[call] = rng.choice(errors)
    assessment, logs = await _run(FakeLLM({k: [v] for k, v in replies.items()}))
    assert assessment.value is not None and assessment.readiness is not None
    for call in ALL:
        if isinstance(replies[call], Exception):
            part = {"OPPORTUNITIES": "opportunities", "MAP": "diagram", "LABEL": "labels",
                    "ASSESS_STEPS": "steps"}[call.value]  # fmt: skip
            assert _words(logs)[part] == "error"


async def test_ac_20_12_reviews_and_specialist_notes_survive_a_re_run():
    first = await _first()
    assert first.readiness is not None
    reviewed = [o.model_copy(update={"review": "accepted"}) if o.id == "o1" else o for o in first.opportunities]
    dims = [d.model_copy(update={"note": "Checked with IT"}) if d.key == "systems" else d
            for d in first.readiness.dimensions]  # fmt: skip
    previous = first.model_copy(
        update={"opportunities": reviewed, "readiness": first.readiness.model_copy(update={"dimensions": dims})}
    )
    again, _ = await _run(_llm(), previous=previous, refresh=True)
    assert next(o for o in again.opportunities if o.title.startswith("Read the site")).review == "accepted"
    assert again.readiness is not None
    assert next(d for d in again.readiness.dimensions if d.key == "systems").note == "Checked with IT"


async def test_ac_20_45_a_failed_step_assessment_leaves_the_other_parts_generated():
    assessment, logs = await _run(_llm(ASSESS_STEPS=LLMUnavailableError(503)))
    assert assessment.step_assessment is None and assessment.outcomes["steps"] == "failed"
    assert [assessment.outcomes[p] for p in ("opportunities", "diagram", "labels")] == ["generated"] * 3
    assert _words(logs)["steps"] == "failed"


async def test_ac_20_49_the_step_part_is_reused_and_a_failed_refresh_keeps_it():
    first = await _first()
    llm = FakeLLM()
    again, logs = await _run(llm, previous=first)
    assert llm.calls == [] and again.step_assessment == first.step_assessment
    llm = _llm(ASSESS_STEPS=LLMUnavailableError(503))
    kept, logs = await _run(llm, previous=first, refresh=True)
    assert kept.step_assessment == first.step_assessment and kept.outcomes["steps"] == "generated"
    assert _words(logs)["steps"] == "refresh_failed"
