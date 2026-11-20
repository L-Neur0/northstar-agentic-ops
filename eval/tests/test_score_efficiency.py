"""Efficiency from a fixed snapshot series: messages, hard cap, efficiency, wasted turns, plateaus, curve (spec 24 §3.9a; AC-24.31 to AC-24.36).

Why: quality is only half the story; these numbers show how many messages it took and where the
interview stalled, so their definitions are pinned on hand-made series. What: snapshot series
built in the test, `score_efficiency`, `progress_curve` with a counting judge, and `sparkline`.
Must not: call a model.
"""

from __future__ import annotations

from typing import Any

from eval.evalkit.play import Snapshot
from eval.evalkit.score_efficiency import is_confirmation, progress_curve, score_efficiency, sparkline, word_set

from .conftest import FakeJudge, make_persona, profile_from_truth

WORDS = word_set(["yes", "no", "that's right", "mine", "the document's", "both"])


def snap(
    n: int, score: float, profile: dict[str, Any] | None = None, phase: str = "steps", event: str = "message"
) -> Snapshot:
    return Snapshot(n=n, event=event, phase=phase, score=score, filledPoints=0, totalPoints=0, finish={},
                    profile=profile or {"v": n}, fieldViews=[])  # fmt: skip


def series(scores: list[float]) -> list[Snapshot]:
    return [snap(0, 0.0, event="start")] + [snap(i, s) for i, s in enumerate(scores, start=1)]


def test_ac_24_31_messages_and_their_targets():
    persona = make_persona()
    eff = score_efficiency(persona, series([0.1 * i for i in range(1, 29)]), 61, WORDS, messages_to_finish=28)
    assert (eff.messages, eff.messages_to_finish, eff.message_target) == (28, 28, 30)
    difficult = make_persona(kind="difficult")
    assert score_efficiency(difficult, series([0.5]), 1, WORDS, messages_to_finish=1).message_target == 40


def test_ac_24_32_no_finish_is_a_failed_session():
    eff = score_efficiency(make_persona(), series([0.1] * 60), 30, WORDS, messages_to_finish=None)
    assert eff.failed and eff.efficiency is None and eff.messages_to_finish is None


def test_ac_24_33_efficiency_is_correct_fields_per_message():
    eff = score_efficiency(make_persona(), series([0.1 * i for i in range(1, 29)]), 61, WORDS, messages_to_finish=28)
    assert eff.efficiency == 2.18


def test_ac_24_34_wasted_turns_skip_confirmations():
    same = {"v": "same"}
    snaps = [
        snap(0, 0.0, event="start"),
        snap(1, 0.1, same),
        snap(2, 0.1, same),
        snap(3, 0.1, same),
        snap(4, 0.1, same),
    ]
    texts = ["Finance", "I said that already", "yes", "yes"]
    eff = score_efficiency(make_persona(), snaps, 1, WORDS, messages_to_finish=4, expert_texts=texts, code_replies=[4])
    assert eff.wasted_at == [2]  # 3 is a plain "yes", 4 was answered by code
    phase_moves = [snap(0, 0.0, event="start"), snap(1, 0.1, same), snap(2, 0.1, same, phase="confirm")]
    assert (
        score_efficiency(make_persona(), phase_moves, 1, WORDS, messages_to_finish=2, expert_texts=["a", "b"]).wasted
        == 0
    )
    many = [snap(0, 0.0, same, event="start")] + [snap(i, 0.0, same) for i in range(1, 5)]
    eff = score_efficiency(make_persona(), many, 1, WORDS, messages_to_finish=4, expert_texts=["hmm"] * 4)
    assert eff.wasted == 4  # above the target of 3: ✗ in the scorecard


def test_is_confirmation():
    assert is_confirmation("Yes, that's right.", WORDS) and is_confirmation("mine", WORDS)
    assert not is_confirmation("yes and we also use Excel", WORDS)


def test_ac_24_35_five_messages_without_gain_is_one_plateau():
    snaps = [snap(0, 0.4, event="start")] + [snap(i, 0.4) for i in range(1, 7)]
    eff = score_efficiency(make_persona(), snaps, 1, WORDS, messages_to_finish=6)
    assert eff.plateaus == [[1, 2, 3, 4, 5]]
    snaps = [snap(0, 0.0, event="start"), snap(1, 0.4)] + [snap(i, 0.4) for i in range(2, 6)] + [snap(6, 0.5)]
    assert score_efficiency(make_persona(), snaps, 1, WORDS, messages_to_finish=6).plateaus == []
    snaps = [snap(0, 0.0, event="start")] + [snap(i, 0.4 if i != 3 else 0.5) for i in range(1, 8)]
    assert score_efficiency(make_persona(), snaps, 1, WORDS, messages_to_finish=7).plateaus == []


async def test_ac_24_36_the_curve_scores_each_message_and_reuses_judged_values():
    persona = make_persona()
    full = profile_from_truth(persona)
    changed = profile_from_truth(persona)
    changed["process"]["trigger"] = "When the books close"
    snaps = [
        snap(0, 0.0, {}, event="start"),
        snap(1, 0.2, {}),
        snap(2, 0.5, changed),
        snap(3, 0.6, changed),
        snap(4, 1.0, full),
    ]
    judge = FakeJudge(True)
    curve = await progress_curve(persona, snaps, judge)
    assert [c.n for c in curve] == [1, 2, 3, 4]
    assert curve[0].quality == 0.0 and curve[-1].quality == 1.0 and curve[-1].score == 1.0
    assert judge.pairs.count(("Month-end close is completed in the ledger", "When the books close")) == 1


def test_sparkline():
    assert sparkline([0.0, 0.5, 1.0]) == "▁▅█"
