"""Prompt tests for the OPPORTUNITIES call (spec 18 §3.4 items 1 and 3; AC-18.1).

Why: the schema binds the reply's shape, but only the prompt tells the model what the eight types
mean, which steps it may cite and that evidence must be copied. A rule silently deleted from the prompt
would lower quality without failing anything, so each rule of the §3.4 table is pinned here. The
payload must be the shared fenced profile, so this call sees what every other call sees.
"""

from __future__ import annotations

import re

import pytest

from app.models.process_discovery_schemas import OpportunityType
from app.services.process_discovery.artifacts.analysis.prompts import (
    OPPORTUNITIES_SYSTEM,
    USER_LEAD_IN,
    opportunities_user,
)
from app.services.process_discovery.artifacts.profile_fence import PROFILE_FENCE_INSTRUCTION, fence_profile
from tests.fixtures.assessment.profiles import load_profile, nig_vocabulary

RULE_PHRASES = {
    1: "Never invent a system, a volume, a role, a step or a pain",
    2: "`[]` only when the change is about the whole process",
    3: "`type` is exactly one of these eight",
    4: "Prefer `eliminate` and `standardise` over automating a broken step",
    5: "the step as it would run after the change, in one or two sentences, present tense",
    6: "Never name a vendor or product the profile does not name",
    7: "what must be true before building it",
    8: "quotes the pain, effort, volume or system behind the grade",
    9: "copied exactly from one field of the profile: at least three words, or a whole short answer",
    10: "Do not estimate hours, savings or money; code computes them",
    11: "Order `opportunities` best first. At most 10",
    12: "the steps that should stay with people",
    13: "where the largest benefit is and what the single biggest lever is",
    14: "return an empty `opportunities` list and say so",
}


@pytest.mark.parametrize("rule", RULE_PHRASES, ids=lambda r: f"rule {r}")
def test_every_rule_of_the_table_is_in_the_system_prompt(rule):
    assert RULE_PHRASES[rule] in OPPORTUNITIES_SYSTEM
    assert f"\n{rule}. " in OPPORTUNITIES_SYSTEM


@pytest.mark.parametrize("kind", [t.value for t in OpportunityType])
def test_the_system_prompt_explains_every_type(kind):
    assert f"- `{kind}`: " in OPPORTUNITIES_SYSTEM


def test_the_system_prompt_carries_the_fence_sentence_and_ends_with_json_only():
    """AC-18.1: the system prompt names the PROFILE fence."""
    assert PROFILE_FENCE_INSTRUCTION in OPPORTUNITIES_SYSTEM
    assert OPPORTUNITIES_SYSTEM.rstrip().endswith("Return only JSON matching the schema. No commentary.")


def test_no_format_placeholder_is_left():
    """A literal string, never formatted: only the JSON skeleton has braces, and it names no placeholder."""
    assert not re.search(r"\{[a-z_]+\}", OPPORTUNITIES_SYSTEM)
    for key in ("summary", "opportunities", "stay_human", "steps", "evidence", "what_changes"):
        assert f'"{key}"' in OPPORTUNITIES_SYSTEM


def test_the_user_message_is_the_lead_in_then_the_fenced_profile():
    profile, vocab = load_profile("eu"), nig_vocabulary()
    user = opportunities_user(profile, vocab=vocab)
    assert user == f"{USER_LEAD_IN}\n\n" + fence_profile(profile, vocab=vocab)
    assert USER_LEAD_IN == "Find where automation or AI could help in this process profile:"
    assert user.rstrip().endswith("PROFILE>>>")
