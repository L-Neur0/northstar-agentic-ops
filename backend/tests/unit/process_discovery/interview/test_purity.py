"""Purity of the interview's decision modules and prompts (spec 14 §2; AC-14.59).

Why: phases, gates, replies and every prompt builder must give the same answer for the same state,
so they may import no clock, file, network or model module. What: an AST check of those modules,
and a determinism check of `next_ask`, the phase and the guide prompt.
"""

import ast
from pathlib import Path

import pytest

from app.services.process_discovery.interview.phases import advance_phase, next_ask
from app.services.process_discovery.interview.prompts.guide import guide_system
from app.services.process_discovery.profile.scoring import FinishCheck

from ..profile.builders import cost_review_profile

INTERVIEW = Path(__file__).resolve().parents[4] / "app" / "services" / "process_discovery" / "interview"
PURE = [INTERVIEW / n for n in ("phases.py", "gates.py", "replies.py")] + sorted((INTERVIEW / "prompts").glob("*.py"))
FORBIDDEN = {
    "time",
    "datetime",
    "random",
    "uuid",
    "os",
    "pathlib",
    "io",
    "socket",
    "httpx",
    "openai",
    "asyncio",
    "subprocess",
}
FORBIDDEN_INTERNAL = {"llm", "fake_llm", "llm_cache"}


@pytest.mark.parametrize("path", PURE, ids=lambda p: p.name)
def test_no_clock_file_network_or_model_import(path):
    """AC-14.59."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            pytest.fail(f"{path.name} opens a file")
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [module.split(".")[0]] if node.level == 0 else [module.split(".")[-1]]
        else:
            continue
        assert not FORBIDDEN.intersection(names), f"{path.name}: {names}"
        assert not FORBIDDEN_INTERNAL.intersection(names), f"{path.name}: {names}"


def test_same_state_same_answers(ctx):
    """AC-14.59."""
    profile = cost_review_profile(ctx.vocab, steps=3, filled_steps=1)
    state = {"profile": profile, "phase": "steps", "score": {"filled_points": 1, "total_points": 2}}
    finish = FinishCheck(False, "below_gate", False)
    assert next_ask(state, vocab=ctx.vocab) == next_ask(state, vocab=ctx.vocab)
    assert advance_phase(profile, "steps", {}, vocab=ctx.vocab) == advance_phase(profile, "steps", {}, vocab=ctx.vocab)
    first = guide_system(state, next_ask(state, vocab=ctx.vocab), finish, vocab=ctx.vocab)
    assert first == guide_system(state, next_ask(state, vocab=ctx.vocab), finish, vocab=ctx.vocab)
