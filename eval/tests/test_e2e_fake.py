"""End to end with scripted models: a two-step persona is played in process, finishes and is scored (spec 24 AC-24.28).

Why: the unit tests pin each piece; only a full run proves they compose through the real app (the
real `create_app`, its lifespan, the memory store, every route) into a run folder and a scorecard.
What: the app's model is a `FakeLLM` that answers each EXTRACT from the expert message it was given
(so the script does not depend on how many calls a turn makes), CLASSIFY with a Finance placement
and GUIDE with a generic question that names the proposed cluster; the assessment calls fail and
fall back. The expert is scripted; the judge says "same" exactly when the two texts are equal.
Must not: reach Azure.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from app.core.settings import Settings
from app.services.process_discovery.fake_llm import FakeLLM
from app.services.process_discovery.llm import CallType, LLMUnavailableError
from eval.run import run_eval

from .conftest import FIXTURES, ROOT

STEP = {
    "goal": "Step {i} is done",
    "activities": ["export", "check"],
    "roles": [{"role": "Controller", "contribution": "checks"}],
    "owner": "Controller",
    "systems": ["SAP"],
    "data": {"inputs": ["actuals"], "outputs": ["report"]},
    "effort": {"duration": "2 hours", "frequency": "monthly"},
    "pain_points": ["slow"],
    "approvals": [{"none": True}],
    "exceptions": [{"none": True}],
    "handover": "by e-mail",
}


def step(i: int) -> dict[str, Any]:
    cells = {"name": f"Step {i}", **json.loads(json.dumps(STEP).replace("{i}", str(i)))}
    return {f"process.substeps[{i}].{leaf}": value for leaf, value in cells.items()}


SCRIPT: dict[str, dict[str, Any]] = {
    "I work in Finance.": {"department": "Finance"},
    "I am a cost controller.": {"user_function": "Cost controller"},
    "Europe.": {"region": "Europe"},
    "The monthly cost review.": {"process.name": "Monthly cost review"},
    "It starts when the month-end close is done in the ledger.": {
        "process.trigger": "Month-end close is completed in the ledger"
    },
    "At the end there is the monthly cost report, and the CFO uses it.": {
        "process.end_result": "The monthly cost report",
        "process.value_at_end": "The CFO uses it to decide on budget corrections",
        "process.business_pain": "Chasing explanations takes days",
    },
    "Once a month; the Head of Controlling owns it; it takes about 4 days.": {
        "process.volume": {"count": 1, "period": "month"},
        "process.process_owner": {"role": "Head of Controlling"},
        "process.baseline_metric": {"value": "4", "unit": "days"},
    },
    "We want 2 days.": {"process.target_metric": {"value": "2", "unit": "days"}},
    "Same everywhere; no personal data.": {
        "process.variation": {"same": "yes"},
        "process.sensitive_data": [{"none": True}],
    },
    "Two steps.": {"process.substep_count": 2},
    "First we export and check the actuals.": step(1),
    "Then we write and send the report.": step(2),
}
CLASSIFY = {
    "scope": {"multi_role": True, "multi_system": True, "trigger_and_outcome": True, "recurring": True,
              "external_consumer": True, "reasoning": "several roles and systems"},
    "placement": {"code": "FIN", "confidence": 0.9, "rationale": "cost work", "runner_up": None, "runner_up_confidence": None},
}  # fmt: skip
FENCED = re.compile(r"<<<EXPERT_MESSAGE\n(.*?)\nEXPERT_MESSAGE>>>", re.S)
PAIR = re.compile(r"<<<HIDDEN\n(.*?)\nHIDDEN>>>\n<<<CAPTURED\n(.*?)\nCAPTURED>>>", re.S)


class ScriptedApp(FakeLLM):
    """Replies made on demand from the request, so the test does not depend on the number of calls."""

    def _next(self, call_type, method, messages, model_name, budget):  # pyright: ignore[reportIncompatibleMethodOverride]
        if not self._replies[call_type]:  # pyright: ignore[reportPrivateUsage]
            self.add(call_type, self._reply(call_type, messages))
        return super()._next(call_type, method, messages, model_name, budget)

    def _reply(self, call_type: CallType, messages: list[Any]) -> Any:
        text = "\n".join(str(m["content"]) for m in messages)
        if call_type is CallType.EXTRACT:
            found = FENCED.findall(text)
            return SCRIPT.get(found[-1].strip(), {}) if found else {}
        if call_type is CallType.CLASSIFY:
            return CLASSIFY
        if call_type is CallType.GUIDE:
            # a different question each time: equal messages in a row would (rightly) count as a loop
            return f"Thank you ({len(self.calls_of(CallType.GUIDE))}). Does this belong to Finance? Tell me more?"
        if call_type is CallType.JUDGE:
            hidden, captured = PAIR.findall(text)[-1]
            return {"same_meaning": hidden == captured, "reason": "exact"}
        return LLMUnavailableError(503)  # assessment calls fall back


async def test_ac_24_28_a_tiny_persona_is_played_end_to_end(tmp_path: Path):
    settings = Settings(_env_file=None, company_config_dir=ROOT / "config" / "nig", frontend_dist=tmp_path / "none")  # pyright: ignore[reportCallIssue]
    expert = FakeLLM({CallType.EXPERT: [*SCRIPT, *["yes"] * 40]})
    args = argparse.Namespace(quick=True, fresh=False, url=None, parallel=1, persona=[], seed_cosmos=False,
                              calibrate_only=False, max_tokens=1)  # fmt: skip
    out = tmp_path / "out.txt"
    with out.open("w") as handle:
        code = await run_eval(
            args,
            settings=settings,
            app_llm=ScriptedApp(),
            expert_llm=expert,
            judge_llm=ScriptedApp(),
            personas_dir=FIXTURES / "personas",
            calibration_file=FIXTURES / "calibration_exact.yaml",
            runs_dir=tmp_path / "runs",
            reports_dir=tmp_path / "reports",
            out=handle,
        )
    [run_dir] = list((tmp_path / "runs").iterdir())
    folder = run_dir / "tiny"
    for name in ("transcript.md", "transcript.json", "turns.jsonl", "snapshots.jsonl", "session.json",
                 "report.json", "report.pdf", "score.json", "curve.json"):  # fmt: skip
        assert (folder / name).exists(), name
    card = json.loads((run_dir / "scorecard.json").read_text())
    [persona] = card["personas"]
    assert persona["status"] == "finished", out.read_text()
    assert persona["quality"] == 1.0, [w for w in persona["wrong"]]
    assert persona["behaviour"]["loops"] == 0
    assert persona["efficiency"]["wasted"] == 0, persona["efficiency"]
    assert len(persona["curve"]) == persona["efficiency"]["messages"] and persona["curve"][-1]["quality"] == 1.0
    assert card["calibration"]["passed"] is True
    assert json.loads((run_dir / "run.json").read_text())["judge_prompt_version"] == "judge-v1"
    assert (run_dir / "scorecard.md").read_text().startswith("# Evaluation scorecard")
    assert not (tmp_path / "reports" / "latest.json").exists()  # a quick run never replaces latest
    assert code in (0, 1)
