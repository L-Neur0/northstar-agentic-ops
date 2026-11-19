"""Company configuration loader (spec 10 §3.6; product F-22).

Why: everything that differs between companies (regions, clusters, rates, readiness wording,
upload limits, yes/no words, wording overrides) is configuration, so a new company is a new
folder, not new code. A mistake in that folder must stop the app at start-up with every problem
listed at once, never surface as a wrong question in an interview.
What: `load_company_config(folder)` reads the seven YAML files, validates each with a strict
Pydantic model (unknown keys rejected, values range-checked), and returns one frozen
`CompanyConfig`. Any problem raises `ConfigError` with one line per problem: file, key, reason.
Must not: hold field IDs, kinds or weights (those live in the registry, spec 12) or read the
environment (that is `app.core.settings`).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config_models import Taxonomy, WordingOverrides

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
OPPORTUNITY_TYPES = (
    "eliminate",
    "standardise",
    "workflow",
    "integration",
    "document_ai",
    "ai_assistant",
    "ai_agent",
    "rpa",
)
READINESS_DIMENSIONS = ("defined", "standard", "data", "systems", "rules", "risk_size")
NOT_A_YES = {"ok", "okay", "sure", "fine"}


class Strict(BaseModel):
    """Base for config models: frozen, unknown keys are an error."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Branding(Strict):
    primary_colour: str
    accent_colour: str
    logo_path: str | None = None

    @field_validator("primary_colour", "accent_colour")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX.match(v):
            raise ValueError(f"{v!r} is not a hex colour like #1F3A5F")
        return v


class Organisation(Strict):
    product_name: str = Field(min_length=1)
    company_name: str = Field(min_length=1)
    regions: tuple[str, ...] = Field(min_length=1)
    languages: tuple[str, ...] = Field(min_length=1)
    branding: Branding

    @field_validator("regions")
    @classmethod
    def _unique_regions(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len({r.casefold() for r in v}) != len(v):
            raise ValueError("regions must be unique")
        return v


class Realisation(Strict):
    conservative: float = Field(gt=0, le=1)
    expected: float = Field(gt=0, le=1)


class Rates(Strict):
    currency: str = "EUR"
    default_hourly_rate: float = Field(gt=0)
    role_group_rates: dict[str, float] = {}
    realisation: Realisation
    saving_share: dict[str, float]

    @field_validator("saving_share")
    @classmethod
    def _shares(cls, v: dict[str, float]) -> dict[str, float]:
        problems = [f"{k}: share {s} is outside 0-0.9" for k, s in v.items() if not 0 <= s <= 0.9]
        missing = [t for t in OPPORTUNITY_TYPES if t not in v]
        unknown = [k for k in v if k not in OPPORTUNITY_TYPES]
        problems += [f"missing type {t}" for t in missing] + [f"unknown type {k}" for k in unknown]
        if problems:
            raise ValueError("; ".join(problems))
        return v


class DimensionWording(Strict):
    to_prepare: dict[str, str]


class Application(Strict):
    name: str
    aliases: tuple[str, ...] = ()
    export_or_api: bool


class ReadinessConfig(Strict):
    dimensions: dict[str, DimensionWording]
    thresholds: dict[str, float]
    applications: tuple[Application, ...] = ()

    @field_validator("dimensions")
    @classmethod
    def _six(cls, v: dict[str, DimensionWording]) -> dict[str, DimensionWording]:
        missing = [d for d in READINESS_DIMENSIONS if d not in v]
        if missing:
            raise ValueError(f"missing dimensions: {', '.join(missing)}")
        return v


class DocumentsConfig(Strict):
    allowed_types: tuple[str, ...] = Field(min_length=1)
    max_files_per_session: int = Field(gt=0)
    max_file_mb: float = Field(gt=0)
    text_budget_chars: int = Field(gt=0)


class LanguageWords(Strict):
    yes: tuple[str, ...]
    no: tuple[str, ...]
    roles_cues: tuple[str, ...]
    systems_cues: tuple[str, ...]

    @field_validator("yes")
    @classmethod
    def _no_weak_yes(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        weak = sorted({w for w in v if str(w).strip().casefold() in NOT_A_YES})
        if weak:
            raise ValueError(f"{', '.join(weak)} must not be a yes word (an acknowledgement, not a confirmation)")
        return v


class LanguageConfig(Strict):
    languages: dict[str, LanguageWords]


class CompanyConfig(Strict):
    """Everything company-specific, loaded once at start-up."""

    organisation: Organisation
    taxonomy: Taxonomy
    rates: Rates
    readiness: ReadinessConfig
    documents: DocumentsConfig
    language: LanguageConfig
    wording: WordingOverrides


FILES: dict[str, tuple[str, type[BaseModel]]] = {
    "organisation": ("organisation.yaml", Organisation),
    "taxonomy": ("taxonomy.yaml", Taxonomy),
    "rates": ("rates.yaml", Rates),
    "readiness": ("readiness.yaml", ReadinessConfig),
    "documents": ("documents.yaml", DocumentsConfig),
    "language": ("language.yaml", LanguageConfig),
    "wording": ("wording.yaml", WordingOverrides),
}


class ConfigError(Exception):
    """The company configuration is invalid. `problems` holds one readable line per problem."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Invalid company configuration:\n  " + "\n  ".join(problems))


def _read(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_company_config(folder: Path) -> CompanyConfig:
    """Load and validate every file in `folder`; raise `ConfigError` listing all problems."""
    folder = Path(folder)
    if not folder.is_dir():
        raise ConfigError([f"{folder}: company configuration folder not found"])
    problems: list[str] = []
    parts: dict[str, BaseModel] = {}
    for key, (filename, model) in FILES.items():
        path = folder / filename
        if not path.exists():
            problems.append(f"{filename}: file is missing")
            continue
        try:
            parts[key] = model.model_validate(_read(path))
        except yaml.YAMLError as exc:
            problems.append(f"{filename}: not valid YAML ({exc})")
        except ValidationError as exc:
            for err in exc.errors():
                where = ".".join(str(p) for p in err["loc"]) or "(file)"
                problems.append(f"{filename}: {where}: {err['msg']}")
    if problems:
        raise ConfigError(problems)
    return CompanyConfig(**parts)  # type: ignore[arg-type]


def get_company(request: Request) -> CompanyConfig:
    """FastAPI dependency: the company configuration loaded in the lifespan."""
    return request.app.state.company
