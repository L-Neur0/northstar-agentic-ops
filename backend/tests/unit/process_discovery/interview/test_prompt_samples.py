"""Rendered prompt samples for the joint review with the product owner (spec 14 §3.9).

Why: the prompts are drafts; reviewing them as code is hard, so the full system and user messages
of every call (EXTRACT, CLASSIFY, GUIDE) are written for three sample states into
`tests/fixtures/prompts/`. The messages are captured from real turns through `FakeLLM`, so a sample
is exactly what the model would receive. No live model is called.
What: builds the three states (the start in `context`; `find` with a cluster proposal; the step walk
with a deferred field and a pending document proposal), runs one turn on each, and compares the
captured messages with the files. Set `UPDATE_PROMPT_SAMPLES=1` to rewrite the files after a prompt
change. Must not: hold assertions about wording; that is the review's job.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.models.process_discovery_schemas import Profile, Session
from app.services.process_discovery.domain.field_spec import step_cell_key
from app.services.process_discovery.fake_llm import FakeLLM, RecordedCall
from app.services.process_discovery.interview.graph import build_graph
from app.services.process_discovery.interview.turn import run_turn
from app.services.process_discovery.llm import CallType
from app.services.process_discovery.profile.mutate import apply_changes
from app.services.process_discovery.profile.proposals import FieldProposal, ProposalDiff, apply_proposals

from ..profile.builders import AT, context_changes, step_changes
from .helpers import NOW, new_session
from .sessions import BOUNDARIES, MEASURE, profile_with, session_at

SAMPLES = Path(__file__).resolve().parents[3] / "fixtures" / "prompts"
SCOPE = {
    "multi_role": True,
    "multi_system": True,
    "trigger_and_outcome": True,
    "recurring": True,
    "external_consumer": False,
    "reasoning": "Several roles take part but nobody outside the team waits on it.",
}
PLACEMENT = {
    "code": "FIN",
    "confidence": 0.82,
    "rationale": "'the numbers we report'",
    "runner_up": "ANL",
    "runner_up_confidence": 0.41,
}
STATES = {
    1: "start: the context phase, the expert's first answer",
    2: "find: a name agreed and a cluster proposal put to the expert",
    3: "steps: mid-walk, with a deferred field and a pending document proposal",
}


async def capture(ctx, session: Session, text: str, **script: list[Any]) -> list[RecordedCall]:
    llm = FakeLLM({CallType[k]: v for k, v in script.items()})
    await run_turn(session, text, llm=llm, graph=build_graph(llm, ctx), ctx=ctx, now=NOW)
    return llm.calls


def state_1(ctx):
    return new_session(ctx), "I'm a cost controller in the Finance department"


def state_2(ctx):
    profile = apply_changes(profile_with(ctx), {}, vocab=ctx.vocab, at=AT).profile
    profile["process"]["cluster"] = {"code": "", "name": "", "decided_by": ""}
    del profile["__meta"]["process.cluster"]
    proposal = {
        "code": "FIN",
        "confidence": 0.82,
        "raw_confidence": 0.82,
        "runner_up": "ANL",
        "runner_up_confidence": 0.41,
        "rationale": "'the numbers we report'",
        "ambiguous": False,
        "source": "model",
    }
    session = session_at(
        ctx,
        "find",
        profile,
        placement={"proposal": proposal, "placed_for": "Monthly cost review"},
        counters={"find_turns": 3},
        last_question={"focus": ["process.cluster"], "confirm": "cluster"},
        messages=[
            {
                "role": "agent",
                "text": "So we map the monthly cost review. Would you file it under Finance: planning, "
                "recording and reporting money?",
                "at": AT,
            }
        ],
    )
    return session, "Hmm, it is really about the numbers we report to the CFO"


def state_3(ctx):
    keys = [k for k in MEASURE if k != "process.target_metric"]
    profile = profile_with(ctx, *BOUNDARIES, *keys, steps=4)
    profile = apply_changes(
        profile,
        {
            **step_changes(1),
            **step_changes(
                2,
                leave_out=(
                    "activities",
                    "roles",
                    "owner",
                    "systems",
                    "data",
                    "effort",
                    "pain_points",
                    "approvals",
                    "exceptions",
                    "handover",
                ),
            ),
        },
        vocab=ctx.vocab,
        at=AT,
    ).profile
    diff = ProposalDiff(
        "d1",
        step_cells=(
            FieldProposal(
                step_cell_key(2, "systems"), ["Excel", "SAP S/4HANA"], "compares actuals with the budget in Excel"
            ),
        ),
    )
    profile = apply_proposals(profile, diff, vocab=ctx.vocab, at=AT).profile
    session = session_at(
        ctx,
        "steps",
        profile,
        counters={"field_asks": {"process.target_metric": 3}, "cell_asks": {step_cell_key(2, "activities"): 1}},
        last_question={"focus": [step_cell_key(2, "activities")]},
        documents=[
            {
                "id": "d1",
                "name": "Cost review procedure.docx",
                "kind": "docx",
                "bytes": 1,
                "chars": 1,
                "uploaded_at": AT,
                "outcome": "read",
            }
        ],
        messages=[
            {"role": "agent", "text": 'You are on step 2, "Step 2". What do you actually do in this step?', "at": AT}
        ],
    )
    return session, "I compare actuals with the budget and flag what is off by more than 5%"


def classify_session(ctx, n):
    """CLASSIFY does not run in every state: 1 = a first name (both halves), 2 = a widening answer (scope only),
    3 = a settled scope for a name without a cluster (placement only)."""
    if n == 1:
        base = apply_changes(empty(ctx), context_changes(), vocab=ctx.vocab, at=AT).profile
        return (
            new_session(ctx, phase="find", profile=Profile.model_validate(base)),
            "the quarterly supplier scorecard",
            {
                "EXTRACT": [{"process.name": "Quarterly supplier scorecard"}],
                "CLASSIFY": [{"scope": SCOPE, "placement": PLACEMENT}],
                "GUIDE": ["Q?"],
            },
        )
    name = "Quarterly supplier scorecard"
    base = apply_changes(empty(ctx), {**context_changes(), "process.name": name}, vocab=ctx.vocab, at=AT).profile
    if n == 2:
        verdict = {
            "verdict": "borderline",
            "score": 4,
            "signals": {k: v for k, v in SCOPE.items() if k != "reasoning"},
            "reasoning": SCOPE["reasoning"],
        }
        session = new_session(
            ctx,
            phase="find",
            profile=Profile.model_validate(base),
            scope={"verdict": verdict, "scoped_for": name, "awaiting_widening": True},
            placement={"proposal": None, "placed_for": name, "rejected": True},
            messages=[{"role": "agent", "text": "Who receives the scorecard once you are done?", "at": AT}],
        )
        return (
            session,
            "Procurement uses it to decide which suppliers we keep",
            {"EXTRACT": [{}], "CLASSIFY": [{"scope": SCOPE}], "GUIDE": ["Q?"]},
        )
    session = new_session(
        ctx, phase="find", profile=Profile.model_validate(base), scope={"verdict": None, "scoped_for": name}
    )
    return session, "yes, that one", {"EXTRACT": [{}], "CLASSIFY": [{"placement": PLACEMENT}], "GUIDE": ["Q?"]}


def empty(ctx):
    from app.services.process_discovery.profile.shapes import empty_profile

    return empty_profile()


def render(call: RecordedCall, title: str) -> str:
    out = [
        f"# {call.call_type.value} — {title}",
        "# ACCEPTED FOR NOW — to be refined with the product owner. Captured from a real turn (FakeLLM).",
        "",
    ]
    for message in call.messages:
        out += [f"=== {message['role']} ===", message["content"], ""]
    return "\n".join(out)


async def samples(ctx) -> dict[str, str]:
    files: dict[str, str] = {}
    builders = {1: state_1, 2: state_2, 3: state_3}
    names = {1: "1_context_start", 2: "2_find_cluster_proposal", 3: "3_steps_deferred_and_proposal"}
    for n, build in builders.items():
        session, text = build(ctx)
        calls = await capture(
            ctx, session, text, EXTRACT=[{}], GUIDE=["Q?"], CLASSIFY=[{"scope": SCOPE, "placement": PLACEMENT}]
        )
        for call in calls:
            if call.call_type in (CallType.EXTRACT, CallType.GUIDE):
                files[f"{call.call_type.value.lower()}_{names[n]}.txt"] = render(call, f"sample {n}: {STATES[n]}")
    classify_titles = {
        1: "sample 1: a first process name (scope and placement)",
        2: "sample 2: a widening answer (scope only)",
        3: "sample 3: scope settled, cluster still open (placement only)",
    }
    classify_names = {1: "1_first_name_both_halves", 2: "2_widening_scope_only", 3: "3_placement_only"}
    for n in (1, 2, 3):
        session, text, script = classify_session(ctx, n)
        calls = await capture(ctx, session, text, **script)
        call = next(c for c in calls if c.call_type is CallType.CLASSIFY)
        files[f"classify_{classify_names[n]}.txt"] = render(call, classify_titles[n])
    return files


async def test_prompt_samples_are_current(ctx):
    """The review samples match what the prompts render today (rewrite with UPDATE_PROMPT_SAMPLES=1)."""
    files = await samples(ctx)
    assert len(files) == 9
    if os.environ.get("UPDATE_PROMPT_SAMPLES") == "1":
        SAMPLES.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (SAMPLES / name).write_text(text, encoding="utf-8")
    for name, text in files.items():
        assert (SAMPLES / name).read_text(encoding="utf-8") == text, (
            f"{name} is stale: run with UPDATE_PROMPT_SAMPLES=1"
        )
