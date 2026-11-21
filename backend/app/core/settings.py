"""Environment settings for the AI Use Case Discovery Agent (spec 10 §3.5; LLM keys from spec 11 §4).

Why: the stage, the store, the model deployments and the secrets decide how the app behaves. They
must be typed, checked once at start-up, and never guessed from the environment: a stage inferred
from hosting variables is how a test-only shortcut ends up accepted in production.
What: one `Settings` class read from environment variables (and `backend/.env` in local runs).
`WORKSPACE_OPEN` (spec 10 AC-10.21, amended 2026-11-20) opens the workspace with a name only, so
the demo stage then needs no workspace codes, only the token secret. It is built in the app lifespan and passed by dependency injection; it is never created at import
time (spec 10 AC-10.3). Invalid values stop start-up with one message per problem.
Must not: hold company content (that is `config/<company>/*.yaml`, see `app.core.config`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import Request
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent

DEV_WORKSPACE_CODE_SPECIALIST = "dev-specialist"
DEV_WORKSPACE_CODE_ENGINEER = "dev-engineer"
DEV_WORKSPACE_TOKEN_SECRET = "dev-only-secret-change-me"

Tokens = Annotated[int, Field(ge=100, le=128_000)]


class Settings(BaseSettings):
    """Typed settings. Field names map to upper-case environment variables (case-insensitive)."""

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore", case_sensitive=False)

    # Stage and company
    deployment_stage: Literal["local", "test", "demo"] = "local"
    company_config_dir: Path = REPO_DIR / "config" / "nig"
    app_version: str = "0.1.0"

    # Store
    store: Literal["memory", "cosmos"] = "memory"
    cosmos_endpoint: str | None = None
    cosmos_database: str = "discovery"
    cosmos_container: str = "sessions"
    session_retention_days: Annotated[int, Field(ge=1, le=365)] = 90  # spec 15 §3.3

    # Access (spec 16)
    workspace_code_specialist: str = DEV_WORKSPACE_CODE_SPECIALIST
    workspace_code_engineer: str = DEV_WORKSPACE_CODE_ENGINEER
    workspace_token_secret: str = DEV_WORKSPACE_TOKEN_SECRET
    workspace_open: bool = False  # spec 16 §3.2 item 5: name-only login, delete switched off
    rate_limit_per_visitor: str = "30/minute"
    rate_limit_per_ip: str = "120/minute"
    daily_token_budget: int = Field(default=2_000_000, ge=0)

    # Logging and telemetry
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    applicationinsights_connection_string: str | None = None

    # Frontend
    frontend_dist: Path = REPO_DIR / "frontend" / "dist"

    # Azure OpenAI (spec 11)
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str = "app-chat"
    azure_openai_eval_deployment: str = "eval-expert"
    azure_openai_judge_deployment: str = "app-chat"  # spec 24 §3.8 J3: the evaluation judge
    azure_openai_api_version: str = "2025-04-01-preview"
    azure_openai_api_key: str | None = None
    azure_client_id: str | None = None
    llm_timeout_seconds: Annotated[float, Field(ge=5, le=120)] = 60
    llm_max_retries: Annotated[int, Field(ge=0, le=5)] = 3
    llm_retry_max_wait_seconds: Annotated[float, Field(ge=1, le=60)] = 20
    llm_max_tokens_extract: Tokens = 32_000
    llm_max_tokens_classify: Tokens = 32_000
    llm_max_tokens_guide: Tokens = 100_000
    llm_max_tokens_read_document: Tokens = 32_000
    llm_max_tokens_opportunities: Tokens = 100_000
    llm_max_tokens_map: Tokens = 32_000
    llm_max_tokens_label: Tokens = 32_000
    llm_max_tokens_assess_steps: Tokens = 32_000
    llm_max_tokens_brief: Tokens = 32_000
    llm_max_tokens_expert: Tokens = 32_000
    llm_max_tokens_judge: Tokens = 2_000  # spec 24 §5
    llm_cache_enabled: bool | None = None  # None = on in local, off elsewhere

    # Interview (spec 14 §4)
    turn_timeout_seconds: Annotated[float, Field(ge=30, le=230)] = 150
    guide_history_turns: Annotated[int, Field(ge=2, le=200)] = 30
    placement_min_confidence: Annotated[float, Field(ge=0, le=1)] = 0.60
    placement_min_margin: Annotated[float, Field(ge=0, le=1)] = 0.15
    finish_offer_first: Annotated[int, Field(ge=1, le=1000)] = 40  # spec 14 §3.18 L2
    finish_offer_every: Annotated[int, Field(ge=1, le=1000)] = 10
    llm_cache_dir: Path = BACKEND_DIR / ".cache" / "llm"

    # Assessment at Finish (spec 20 §3.1): each of the four parallel calls gets this long
    assessment_call_timeout_seconds: Annotated[float, Field(ge=10, le=150)] = 60

    @model_validator(mode="after")
    def _check_stage_rules(self) -> Settings:
        """Cross-field rules. All problems are collected so one start-up shows every one."""
        problems: list[str] = []
        if self.store == "cosmos" and not self.cosmos_endpoint:
            problems.append("COSMOS_ENDPOINT is required when STORE=cosmos")
        if self.deployment_stage == "demo":
            if self.store != "cosmos":
                problems.append("STORE must be cosmos in the demo stage")
            codes_needed = not self.workspace_open  # an open workspace uses no code (AC-10.21)
            if codes_needed and self.workspace_code_specialist == DEV_WORKSPACE_CODE_SPECIALIST:
                problems.append("WORKSPACE_CODE_SPECIALIST must be set (not the development value) in the demo stage")
            if codes_needed and self.workspace_code_engineer == DEV_WORKSPACE_CODE_ENGINEER:
                problems.append("WORKSPACE_CODE_ENGINEER must be set (not the development value) in the demo stage")
            if self.workspace_token_secret == DEV_WORKSPACE_TOKEN_SECRET or len(self.workspace_token_secret) < 32:
                problems.append("WORKSPACE_TOKEN_SECRET must be set to at least 32 characters in the demo stage")
        if self.azure_openai_api_key and self.deployment_stage != "local":
            problems.append("AZURE_OPENAI_API_KEY is allowed only in the local stage; use managed identity")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @property
    def cache_enabled(self) -> bool:
        """The model reply cache runs only in the local stage (spec 11)."""
        if self.deployment_stage != "local":
            return False
        return True if self.llm_cache_enabled is None else self.llm_cache_enabled


def get_settings(request: Request) -> Settings:
    """FastAPI dependency: the settings built in the lifespan."""
    return request.app.state.settings
