"""Tests for the LABEL call, its prompt, its wire schema and its grounding (spec 19 §3.3, §3.4).

Why: Data and Rules are counted from these labels, so a label on an input the step does not list,
evidence from another step or a sixth decision must each be caught by code; the call must fail
loudly (no invented labels) on any client error and log counts only.
What: `ground_labels` on the §3.4 reply against the shared EU fixture, then adversarial entries;
`run_labels` through `FakeLLM`; the prompt rules by phrase; the strict schema and its literals.
Must not: reach the network.
Covers AC-19.17 to AC-19.22.
"""

from __future__ import annotations

import copy
import logging
import typing

import pytest

from app.services.process_discovery.artifacts.labels.labels import LabelsFailedError, ground_labels, run_labels
from app.services.process_discovery.artifacts.labels.prompts import LABEL_SYSTEM, labels_user
from app.services.process_discovery.artifacts.labels.schemas import DecisionKind, InputFormat, LabelsOut
from app.services.process_discovery.artifacts.profile_fence import PROFILE_FENCE_INSTRUCTION
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.json_schema import strict_json_schema
from app.services.process_discovery.llm import (
    CallType,
    LLMBudgetExceededError,
    LLMEmptyResponseError,
    LLMInvalidOutputError,
    LLMUnavailableError,
)
from tests.fixtures.assessment.profiles import load_profile, nig_vocabulary
from tests.fixtures.assessment_19.cases import LABEL_REPLY, eu_labels

SENTINEL = "ZQX-SENTINEL-1919"


def _reply() -> dict:
    return copy.deepcopy(LABEL_REPLY)


def _ground(reply):
    return ground_labels(reply, load_profile("eu"))


def test_ac_19_17_strict_schema_and_literals() -> None:
    """AC-19.17: the strict schema builds; the format and kind literals are pinned."""
    assert strict_json_schema(LabelsOut, "LabelsOut")
    assert typing.get_args(InputFormat) == ("structured", "digital_document", "paper", "verbal")
    assert typing.get_args(DecisionKind) == ("fixed_rule", "explainable_judgement", "pure_judgement")


def test_ac_19_18_prompt_rules() -> None:
    """AC-19.18 (prompt): the five rules, the fence sentence, JSON only."""
    for phrase in (
        'label each input listed under "Data in and out", using its exact name',
        "`structured`: fields a system can read without a person",
        "`digital_document`: a digital file or message a person reads",
        "`paper`: printed or handwritten",
        "`verbal`: said in a call or meeting, or known from memory",
        "each in at most 15 words",
        "`fixed_rule`: a written rule or threshold decides",
        "`explainable_judgement`: a person decides but can name the criteria",
        "`pure_judgement`: experience or relationships decide",
        "the expert's words from THAT step, copied exactly, at least three words",
        "Never invent inputs or decisions; a step with no decision has an empty list",
        "Never give scores",
        PROFILE_FENCE_INSTRUCTION,
        "Return only JSON matching the schema.",
    ):
        assert phrase in LABEL_SYSTEM.replace("\\\n", ""), phrase


async def test_ac_19_18_one_call_with_fenced_profile() -> None:
    """AC-19.18 (call): one structured LABEL call with the fenced profile."""
    llm = FakeLLM({CallType.LABEL: [_reply()]})
    labels, dropped = await run_labels(load_profile("eu"), llm, vocab=nig_vocabulary())
    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert (call.call_type, call.method, call.model_name) == (CallType.LABEL, "structured", "LabelsOut")
    assert call.messages[0] == {"role": "system", "content": LABEL_SYSTEM}
    assert call.messages[1] == {"role": "user", "content": labels_user(load_profile("eu"), vocab=nig_vocabulary())}
    assert labels == eu_labels() and dropped["input"] == 1
    llm.assert_all_used()


@pytest.mark.parametrize(
    "error",
    [LLMEmptyResponseError("truncated"), LLMUnavailableError(503), LLMBudgetExceededError("b"),
     LLMInvalidOutputError(["steps"])],
    ids=lambda e: type(e).__name__,
)  # fmt: skip
async def test_ac_19_18_any_client_error_fails(error: Exception) -> None:
    """AC-19.18: any `LLMError` → `LabelsFailedError`, chained."""
    llm = FakeLLM({CallType.LABEL: [error]})
    with pytest.raises(LabelsFailedError) as raised:
        await run_labels(load_profile("eu"), llm, vocab=nig_vocabulary())
    assert raised.value.__cause__ is error


async def test_log_line_counts_only(caplog: pytest.LogCaptureFixture) -> None:
    """One `assessment_call` line with counts; no profile or reply text in any record."""
    profile = load_profile("eu")
    profile["process"]["substeps"][0]["goal"] += SENTINEL
    reply = _reply()
    reply["steps"][1]["decisions"][0]["text"] += SENTINEL
    llm = FakeLLM({CallType.LABEL: [reply]})
    with caplog.at_level(logging.DEBUG):
        await run_labels(profile, llm, vocab=nig_vocabulary())
    lines = [r for r in caplog.records if r.getMessage() == "assessment_call"]
    assert len(lines) == 1 and lines[0].__dict__["call"] == "LABEL"
    assert lines[0].__dict__["dropped"] == {"step": 0, "input": 1, "quote": 0, "invalid": 0, "cap": 0}
    for r in caplog.records:
        assert SENTINEL not in r.getMessage() and SENTINEL not in repr(r.__dict__)


def test_ac_19_19_worked_example() -> None:
    """AC-19.19: 5 StepLabels with the §3.4 inputs and decisions; "invoice scans" dropped (`input`)."""
    labels, dropped = _ground(_reply())
    assert labels == eu_labels()
    assert [len(s.inputs) for s in labels] == [1, 2, 2, 2, 1]
    assert [d.kind for s in labels for d in s.decisions] == [
        "fixed_rule", "fixed_rule", "fixed_rule", "pure_judgement", "explainable_judgement"
    ]  # fmt: skip
    assert dropped == {"step": 0, "input": 1, "quote": 0, "invalid": 0, "cap": 0}


@pytest.mark.parametrize("bad", [0, 6, True])
def test_ac_19_20_bad_step_dropped(bad: object) -> None:
    """AC-19.20: step 0, 6 or a bool → dropped (`step`)."""
    reply = _reply()
    reply["steps"].append({"step": bad, "inputs": [], "decisions": []})
    labels, dropped = _ground(reply)
    assert dropped["step"] == 1 and len(labels) == 5


def test_ac_19_20_repeated_step_and_spelling() -> None:
    """AC-19.20: a repeated step is dropped; a name takes the stored spelling; a second label per input dropped."""
    reply = _reply()
    reply["steps"].append({"step": 2, "inputs": [], "decisions": []})
    reply["steps"][1]["inputs"][1]["name"] = "sap cost centre REPORT"
    reply["steps"][1]["inputs"].append(
        {"name": "Set of site files", "format": "paper", "evidence": "set of site files"}
    )
    labels, dropped = _ground(reply)
    assert dropped["step"] == 1 and dropped["input"] == 2
    assert [i.name for i in labels[1].inputs] == ["set of site files", "SAP cost centre report"]


def test_ac_19_21_evidence_only_from_that_step() -> None:
    """AC-19.21: evidence found only in another step → `quote`; the step's own cell is accepted."""
    reply = _reply()
    reply["steps"][2]["decisions"][0]["evidence"] = "reconcile totals with SAP"  # step 2's words
    labels, dropped = _ground(reply)
    assert dropped["quote"] == 1 and labels[2].decisions == []
    assert labels[1].decisions[0].evidence == "reconcile totals with SAP"


def test_ac_19_22_decision_caps_and_cleaning() -> None:
    """AC-19.22: first 5 decisions kept; empty text dropped; long text cleaned and capped."""
    reply = _reply()
    decision = {"text": "Do the totals match SAP?", "kind": "fixed_rule", "evidence": "reconcile totals with SAP"}
    reply["steps"][1]["decisions"] = [
        {**decision, "text": "  \n "},
        {**decision, "text": "Line one\nline two " + "x" * 300},
        *[{**decision, "text": f"Decision {i}"} for i in range(6)],
    ]
    labels, dropped = _ground(reply)
    texts = [d.text for d in labels[1].decisions]
    assert len(texts) == 5
    assert texts[0].startswith("Line one line two") and len(texts[0]) == 200 and texts[0].endswith("…")
    assert texts[1:] == [f"Decision {i}" for i in range(4)]
    assert dropped["invalid"] == 1 and dropped["cap"] == 2


def test_l5_mapping_with_unknown_format_or_kind() -> None:
    """L5: a mapping reply with a format or kind outside the literals is dropped (`invalid`)."""
    reply = _reply()
    reply["steps"][0]["inputs"][0]["format"] = "fax"
    reply["steps"][1]["decisions"][0]["kind"] = "gut_feeling"
    labels, dropped = _ground(reply)
    assert labels[0].inputs == [] and labels[1].decisions == []
    assert dropped["invalid"] == 2


def test_l6_skipped_steps_are_empty() -> None:
    labels, _ = _ground({"steps": []})
    assert [(s.step, s.inputs, s.decisions) for s in labels] == [(k, [], []) for k in range(1, 6)]
