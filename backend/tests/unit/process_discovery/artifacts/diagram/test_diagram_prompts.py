"""Prompt tests for the MAP call (spec 18 §3.7 item 4; AC-18.1).

Why: grounding repairs or replaces whatever the model draws, but a prompt that asks for what grounding
enforces saves fallbacks. Each of the nine requirements is pinned by a phrase, so a requirement
deleted from the prompt fails a test. The payload must be the shared fenced profile.
"""

from __future__ import annotations

import re

import pytest

from app.services.process_discovery.artifacts.diagram.prompts import MAP_SYSTEM, USER_LEAD_IN, map_user
from app.services.process_discovery.artifacts.profile_fence import PROFILE_FENCE_INSTRUCTION, fence_profile
from tests.fixtures.assessment.profiles import load_profile, nig_vocabulary

REQUIREMENTS = {
    1: "Never invent a step, a role, a system or a decision",
    2: "Never use a person's name",
    3: "exactly one `task` node per step, in step order",
    4: "Use `manual` for a step with no system, `user` for a step with one",
    5: "Add a `gateway` only where the profile states a decision, an approval or an exception path",
    6: "short, correct English phrase of 2 to 6 words",
    7: "Every node must be reachable from the start",
    8: "Node ids are short, unique strings",
    9: "exactly one incoming and one outgoing flow",
}


@pytest.mark.parametrize("number", REQUIREMENTS, ids=lambda n: f"requirement {n}")
def test_every_requirement_is_in_the_system_prompt(number):
    assert REQUIREMENTS[number] in MAP_SYSTEM
    assert f"\n{number}. " in MAP_SYSTEM


def test_the_prompt_states_the_bpmn_rules_grounding_enforces():
    for phrase in ("merge `gateway`", "never both", "has a `label`", "at most six words",
                   "never on more than one flow"):  # fmt: skip
        assert phrase in MAP_SYSTEM


def test_the_prompt_says_a_returning_loop_uses_an_exclusive_merge():
    assert "loop returns to an earlier step, add an `exclusive` merge" in MAP_SYSTEM


def test_the_prompt_asks_for_short_state_names_with_an_example():
    assert '"Customer order placed"' in MAP_SYSTEM


def test_the_system_prompt_carries_the_fence_sentence_and_ends_with_json_only():
    """AC-18.1."""
    assert PROFILE_FENCE_INSTRUCTION in MAP_SYSTEM
    assert MAP_SYSTEM.rstrip().endswith("Return only JSON matching the schema. No commentary.")
    assert not re.search(r"\{[a-z_]+\}", MAP_SYSTEM)


def test_the_user_message_is_the_lead_in_then_the_fenced_profile():
    profile, vocab = load_profile("eu"), nig_vocabulary()
    assert map_user(profile, vocab=vocab) == f"{USER_LEAD_IN}\n\n" + fence_profile(profile, vocab=vocab)
    assert USER_LEAD_IN == "Draw the BPMN process diagram for this process profile:"
