"""The judge: narrow requests, strict output, one call per pair, a separate deployment, calibration (spec 24 §3.8; AC-24.14 to AC-24.17).

Why: the judge is the only model that touches a score, so what it sees, how its output is checked
and when its answers are trusted are tested here with `FakeLLM`. What: request contents (sentinel),
two invalid replies as `judge_error`, the memo, the deployment clash (exit 2), and the 90 % gate.
Must not: call a model.
"""

from __future__ import annotations

import argparse

from app.core.settings import Settings
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.llm import CallType
from eval.evalkit.calibrate import CalibrationPair, calibrate
from eval.evalkit.judge import JUDGE_PROMPT_VERSION, Judge
from eval.evalkit.score_fields import score_fields
from eval.evalkit.scorecard import build_scorecard, render_markdown
from eval.run import run_eval

from .conftest import FakeJudge, make_persona, profile_from_truth
from .test_scorecard import persona_score

SENTINEL = "SENTINEL-TRANSCRIPT-7731"


async def test_ac_24_14_the_request_holds_label_rule_hidden_and_captured_only():
    llm = FakeLLM({CallType.JUDGE: [{"same_meaning": True, "reason": "same"}]})
    verdict = await Judge(llm).same("Trigger", "A concrete event.", "month-end close", "books closed")
    assert verdict.same_meaning
    [call] = llm.calls
    text = "\n".join(str(m["content"]) for m in call.messages)
    for part in ("Trigger", "A concrete event.", "month-end close", "books closed", JUDGE_PROMPT_VERSION):
        assert part in text
    assert SENTINEL not in text and call.model_name == "JudgeOut"


async def test_ac_24_14_two_invalid_replies_are_a_judge_error_counted_wrong():
    persona = make_persona()
    profile = profile_from_truth(persona)
    profile["process"]["trigger"] = f"something else {SENTINEL}"
    llm = FakeLLM({CallType.JUDGE: [{"same": 1}, "not json"]})
    scores = await score_fields(persona, profile, Judge(llm))
    trigger = next(r for r in scores.results if r.key == "process.trigger")
    assert (trigger.correct, trigger.judge_error, trigger.method) == (False, True, "judge")
    assert scores.judge_errors == 1
    for call in llm.calls:  # the transcript never reaches the judge; only the captured value does
        assert "conversation" not in str(call.messages).lower()


async def test_ac_24_16_the_same_pair_is_judged_once():
    llm = FakeLLM({CallType.JUDGE: [{"same_meaning": False, "reason": "no"}]})
    judge = Judge(llm)
    first = await judge.same("Goal", "r", "a", "b")
    second = await judge.same("Goal", "r", "a", "b")
    assert first == second and len(llm.calls) == 1


async def test_ac_24_15_the_run_refuses_a_judge_on_the_expert_deployment(tmp_path):
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        azure_openai_eval_deployment="same-one",
        azure_openai_judge_deployment="same-one",
    )
    args = argparse.Namespace(quick=True, fresh=False, url=None, parallel=1, persona=[], seed_cosmos=False,
                              calibrate_only=False, max_tokens=1)  # fmt: skip
    llm = FakeLLM()
    code = await run_eval(args, settings=settings, app_llm=llm, expert_llm=llm, judge_llm=llm, runs_dir=tmp_path)
    assert code == 2 and llm.calls == []


def _pairs(n: int) -> list[CalibrationPair]:
    return [CalibrationPair(field="Goal", hidden=f"h{i}", captured=f"c{i}", label=True) for i in range(n)]


class _Agrees(FakeJudge):
    def __init__(self, wrong: int) -> None:
        super().__init__(True)
        self.wrong = wrong
        self.seen = 0

    async def same(self, label, rule, hidden, captured):
        self.seen += 1
        verdict = await super().same(label, rule, hidden, captured)
        return type(verdict)(self.seen > self.wrong, "fake")


async def test_ac_24_17_calibration_passes_at_27_of_30_and_fails_at_26():
    passed = await calibrate(_Agrees(3), _pairs(30))  # pyright: ignore[reportArgumentType]
    assert (passed.agreed, passed.passed) == (27, True)
    failed = await calibrate(_Agrees(4), _pairs(30))  # pyright: ignore[reportArgumentType]
    assert (failed.agreed, failed.passed) == (26, False)

    card = build_scorecard("r", [persona_score()], failed, None)
    assert not card.passed and not card.judge_trusted
    assert any("judge failed calibration" in r for r in card.reasons)
    text = render_markdown(card)
    assert "NOT TRUSTED" in text and "Code-only" in text


def test_ac_24_55_judge_v3_per_run_qualifier():
    """AC-24.55 (spec 24 §12 V5): judge-v3 says a per-unit-of-work qualifier keeps the meaning, a per-period one does not."""
    from eval.evalkit.calibrate import load_pairs
    from eval.evalkit.judge import JUDGE_PROMPT_VERSION, SYSTEM
    from eval.evalkit.persona import EVAL_DIR

    assert JUDGE_PROMPT_VERSION == "judge-v3"
    text = " ".join(SYSTEM.split())
    assert "per role" in text and "per week" in text
    pairs = {(p.hidden, p.captured): p.label for p in load_pairs(EVAL_DIR / "judge_calibration.yaml")}
    assert pairs[("3 working days", "3 working days per role")] is True
    assert pairs[("3 hours", "3 hours per week")] is False
