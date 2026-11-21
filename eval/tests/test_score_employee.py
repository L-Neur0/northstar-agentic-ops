"""Employee time, detail burden and the quality split from fixed transcripts and turn logs (spec 24 §3.9b; AC-24.37 to AC-24.41).

Why: these are the headline numbers the product owner approved on 2026-11-20 (the employee's time and
being asked low-value details), so their definitions are pinned on hand-made inputs: a transcript
with known word counts, a turn log with known focus keys, field results with known keys.
What: `employee_time`, `detail_burden`, `quality_split`, the time constants and the tiers file.
Must not: call a model.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.process_discovery.domain.field_spec import STEP_SPECS
from eval.evalkit.persona import EVAL_DIR
from eval.evalkit.score_employee import (
    TimeModel,
    detail_burden,
    employee_time,
    load_tiers,
    load_time_model,
    quality_split,
)
from eval.evalkit.score_fields import FieldResult

TIERS = load_tiers(EVAL_DIR / "tiers.yaml")
MODEL = TimeModel(
    reading_wpm=230, typing_wpm=40, think_seconds=8, short_answer_think_seconds=3, short_answer_max_words=3,
    upload_seconds=20, target_minutes=20,
)  # fmt: skip


def words(n: int) -> str:
    return " ".join(["word"] * n)


def test_ac_24_37_the_constants_come_from_the_yaml_file():
    assert load_time_model(EVAL_DIR / "employee_time.yaml") == MODEL


def test_ac_24_37_time_is_reading_plus_typing_plus_thinking_plus_uploads():
    transcript = [
        {"role": "agent", "text": words(230)},
        {"role": "expert", "text": words(40)},
        {"role": "agent", "text": words(230)},
        {"role": "expert", "text": words(40)},
        {"role": "expert", "text": "yes"},
    ]
    time = employee_time(transcript, uploads=1, model=MODEL)
    assert time.reading_s == pytest.approx(120.0)
    assert time.typing_s == pytest.approx(121.5)
    assert time.think_s == pytest.approx(19.0)
    assert time.upload_s == pytest.approx(20.0)
    assert time.minutes == pytest.approx(4.675, abs=1e-3)
    assert (time.agent_messages, time.expert_messages, time.agent_words, time.expert_words) == (2, 3, 460, 81)


def test_ac_24_48_the_average_answer_length_is_expert_words_per_expert_message():
    transcript = [{"role": "agent", "text": words(50)}, {"role": "expert", "text": words(30)},
                  {"role": "expert", "text": "yes"}]  # fmt: skip
    time = employee_time(transcript, uploads=0, model=MODEL)
    assert time.avg_expert_words == pytest.approx(15.5)
    assert time.model_dump()["avg_expert_words"] == pytest.approx(15.5)  # in the JSON, so the Markdown can show it
    assert employee_time([], uploads=0, model=MODEL).avg_expert_words == 0


def test_ac_24_37_a_short_answer_is_up_to_three_words():
    four = employee_time([{"role": "expert", "text": "no it is monthly"}], uploads=0, model=MODEL)
    three = employee_time([{"role": "expert", "text": "no, the document's"}], uploads=0, model=MODEL)
    assert four.think_s == 8 and three.think_s == 3


def test_ac_24_37_the_worked_example_is_eighteen_minutes():
    transcript: list[dict[str, Any]] = []
    for _ in range(28):
        transcript += [{"role": "agent", "text": words(46)}, {"role": "expert", "text": words(12)}]
    transcript += [{"role": "agent", "text": words(46)}, {"role": "agent", "text": words(46)}]
    assert employee_time(transcript, uploads=0, model=MODEL).minutes == pytest.approx(18.13, abs=0.01)


def turn(*focus: str, event: str = "message") -> dict[str, Any]:
    return {"n": 1, "event": event, "focus": list(focus)}


def test_ac_24_39_detail_burden_counts_questions_that_ask_only_for_low_value_fields():
    turns = [
        turn("process.substeps[1].owner"),
        turn("process.target_metric"),
        turn("process.substeps[1].goal", "process.substeps[1].systems"),
        turn("process.substeps[2].name"),
        turn(),
    ]
    burden = detail_burden(turns, TIERS)
    assert burden is not None
    assert (burden.questions, burden.low_value, burden.share) == (4, 2, 0.5)
    assert burden.low_value_keys == ["process.substeps[1].owner", "process.target_metric"]


def test_ac_24_39_upload_replies_count_and_no_turn_log_is_n_a():
    burden = detail_burden([turn("process.substeps[3].goal", event="upload")] + [turn("department")] * 6, TIERS)
    assert burden is not None and burden.share == pytest.approx(1 / 7)
    assert detail_burden([], TIERS) is None
    assert detail_burden([{"n": 1, "event": "message"}], TIERS) is None  # URL mode: no focus recorded


def test_ac_24_40_every_registry_step_leaf_has_a_tier():
    registry = {s.key for s in STEP_SPECS}
    assert registry == set(TIERS.step_leaves), (
        f"tiers differ from the registry: {sorted(registry ^ set(TIERS.step_leaves))}"
    )
    assert TIERS.step_leaves["decision_type"] == "A"
    assert {k for k, t in TIERS.step_leaves.items() if t == "C"} == {"goal", "owner"}  # amended 2026-11-21
    assert TIERS.low_value_process == ["process.target_metric"]


def result(key: str, correct: bool) -> FieldResult:
    return FieldResult(key=key, id="", hidden="h", captured="c", method="code", correct=correct)


def test_ac_24_41_quality_is_split_into_tier_a_plus_core_and_the_rest():
    results = [
        result("process.name", True),  # core
        result("process.volume", False),  # core
        result("department", True),  # rest
        result("process.target_metric", False),  # rest
        result("process.substeps[1].systems", True),  # A
        result("process.substeps[1].effort", True),  # A
        result("process.substeps[1].approvals", False),  # B: rest (roles moved to A, 2026-11-21)
        result("process.substeps[1].goal", False),  # C: rest
    ]
    split = quality_split(results, TIERS)
    assert (split.core_correct, split.core_total, split.rest_correct, split.rest_total) == (3, 4, 1, 4)
    assert split.core_quality == 0.75 and split.rest_quality == 0.25
