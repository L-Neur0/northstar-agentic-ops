"""Tests for the environment settings (spec 10 §3.5).

Why: settings decide the stage, the store and the secrets. A wrong value must stop the app at
start-up with a clear message, never surface later as a strange runtime error.
What: builds `Settings` from explicit values (never from the real environment) and checks the
start-up rules. Implements spec 10, AC-10.4 to AC-10.6.
"""

import pytest
from pydantic import ValidationError

from app.core.settings import Settings


def make(**values):
    """Settings from explicit values only: no `.env` file, no process environment surprises."""
    return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


def test_defaults_are_a_local_in_memory_run():
    s = make()
    assert s.deployment_stage == "local"
    assert s.store == "memory"
    assert s.azure_openai_deployment == "app-chat"
    assert s.azure_openai_eval_deployment == "eval-expert"


def test_an_unknown_stage_stops_start_up():
    """AC-10.4."""
    with pytest.raises(ValidationError, match="deployment_stage"):
        make(deployment_stage="prod")


def test_cosmos_without_an_endpoint_stops_start_up():
    """AC-10.5."""
    with pytest.raises(ValidationError, match="COSMOS_ENDPOINT"):
        make(store="cosmos")


def test_cosmos_with_an_endpoint_is_accepted():
    assert make(store="cosmos", cosmos_endpoint="https://x.documents.azure.com:443/").store == "cosmos"


def test_demo_refuses_the_development_secrets():
    """AC-10.6: the demo stage needs its own workspace codes and token secret."""
    with pytest.raises(ValidationError) as err:
        make(deployment_stage="demo", store="cosmos", cosmos_endpoint="https://x")
    text = str(err.value)
    assert "WORKSPACE_CODE_SPECIALIST" in text and "WORKSPACE_TOKEN_SECRET" in text


def test_demo_requires_cosmos():
    with pytest.raises(ValidationError, match="STORE"):
        make(
            deployment_stage="demo",
            workspace_code_specialist="s-123456",
            workspace_code_engineer="e-123456",
            workspace_token_secret="x" * 32,
        )


def test_a_complete_demo_configuration_is_accepted():
    s = make(
        deployment_stage="demo",
        store="cosmos",
        cosmos_endpoint="https://x",
        workspace_code_specialist="s-123456",
        workspace_code_engineer="e-123456",
        workspace_token_secret="x" * 32,
    )
    assert s.deployment_stage == "demo"


def test_token_budgets_have_a_range():
    with pytest.raises(ValidationError):
        make(llm_max_tokens_guide=50)
    assert make(llm_max_tokens_guide=128000).llm_max_tokens_guide == 128000


def test_interview_settings_have_defaults_and_ranges():
    """Spec 14 §4 settings keys: TURN_TIMEOUT_SECONDS, GUIDE_HISTORY_TURNS, PLACEMENT_MIN_CONFIDENCE, PLACEMENT_MIN_MARGIN."""
    s = make()
    assert (s.turn_timeout_seconds, s.guide_history_turns) == (150, 30)
    assert (s.placement_min_confidence, s.placement_min_margin) == (0.60, 0.15)
    for bad in ({"turn_timeout_seconds": 300}, {"guide_history_turns": 1}, {"placement_min_confidence": 1.5}):
        with pytest.raises(ValidationError):
            make(**bad)
