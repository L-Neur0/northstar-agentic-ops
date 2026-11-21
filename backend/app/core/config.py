"""Company configuration loader (spec 10 §3.6; product F-22).

Why: everything that differs between companies (regions, clusters, rates, readiness wording,
upload limits, yes/no words, wording overrides, the solution catalogue, the steering weights) is
configuration, so a new company is a new folder, not new code. A mistake in that folder must stop the app at start-up with every problem
listed at once, never surface as a wrong question in an interview.
What: `load_company_config(folder)` reads the nine YAML files, validates each with a strict
Pydantic model (unknown keys rejected, values range-checked), and returns one frozen
`CompanyConfig`. Any problem raises `ConfigError` with one line per problem: file, key, reason.
Owns the models of spec 10 §3.6, `ReadinessConfig` (spec 19 §4.4, AC-19.37), `SolutionCatalogue`
(spec 26 §4.3, AC-26.1) and `SteeringConfig` (spec 14 §3.15 item 11, AC-14.71).
Must not: hold field IDs, kinds or weights (those live in the registry, spec 12), hold a company's
tool names or numbers (those are the YAML files), or read the environment (`app.core.settings`).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

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


Line = Annotated[str, Field(min_length=1)]
Share = Annotated[float, Field(ge=0, le=1)]


class DimensionWording(Strict):
    to_prepare: dict[Literal["low", "medium"], Line]

    @field_validator("to_prepare")
    @classmethod
    def _both_levels(cls, v: dict[str, str]) -> dict[str, str]:
        missing = [level for level in ("low", "medium") if level not in v]
        if missing:
            raise ValueError(f"missing to-prepare line for: {', '.join(missing)}")
        return v


class Thresholds(Strict):
    """Readiness level boundaries (spec 19 §3.5); each medium bound is below its high bound."""

    min_hours_per_year_medium: float = Field(ge=0)
    min_hours_per_year_high: float = Field(ge=0)
    digital_share_high: Share
    digital_share_medium: Share
    rule_share_high: Share
    rule_share_medium: Share
    known_system_share_high: Share
    known_system_share_medium: Share
    exception_share_medium: Share = 0.5

    @model_validator(mode="after")
    def _medium_below_high(self) -> Thresholds:
        pairs = ("min_hours_per_year", "digital_share", "rule_share", "known_system_share")
        bad = [p for p in pairs if getattr(self, f"{p}_medium") >= getattr(self, f"{p}_high")]
        if bad:
            raise ValueError("; ".join(f"{p}_medium must be below {p}_high" for p in bad))
        return self


class Application(Strict):
    name: str
    aliases: tuple[str, ...] = ()
    export_or_api: bool
    #: A general office tool (spreadsheet, e-mail, chat) that needs no connector (spec 27 §3.3 Q2).
    general_tool: bool = False


class ReadinessConfig(Strict):
    dimensions: dict[str, DimensionWording]
    thresholds: Thresholds
    applications: tuple[Application, ...] = ()

    @field_validator("dimensions")
    @classmethod
    def _six(cls, v: dict[str, DimensionWording]) -> dict[str, DimensionWording]:
        missing = [d for d in READINESS_DIMENSIONS if d not in v]
        unknown = [d for d in v if d not in READINESS_DIMENSIONS]
        problems = [f"missing dimensions: {', '.join(missing)}"] if missing else []
        problems += [f"unknown dimensions: {', '.join(unknown)}"] if unknown else []
        if problems:
            raise ValueError("; ".join(problems))
        return v

    @field_validator("applications")
    @classmethod
    def _unique_names(cls, v: tuple[Application, ...]) -> tuple[Application, ...]:
        """A name or alias (case-insensitive) belongs to one application only."""
        seen: dict[str, str] = {}
        clashes: list[str] = []
        for app in v:
            for word in {w.strip().casefold() for w in (app.name, *app.aliases)}:
                if word in seen:
                    clashes.append(f"name or alias {word!r} is used by {seen[word]!r} and {app.name!r}")
                seen.setdefault(word, app.name)
        if clashes:
            raise ValueError("; ".join(clashes))
        return v


# --- Solution catalogue (spec 26 §3.1, §4.3) --------------------------------------------------------

SolutionCategory = Literal[
    "existing_internal", "off_the_shelf", "low_code", "custom_build", "integration", "fix_first", "none"
]
AIFit = Literal["automate", "assist", "human"]
ShortLine = Annotated[str, Field(min_length=1, max_length=200)]


class Solution(Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,39}$")
    category: SolutionCategory
    name: ShortLine
    good_for: str = Field(min_length=1, max_length=400)
    choose_when: tuple[ShortLine, ...] = Field(min_length=1, max_length=5)
    avoid_when: tuple[ShortLine, ...] = Field(default=(), max_length=5)
    prerequisites: tuple[ShortLine, ...] = Field(default=(), max_length=5)
    fits: tuple[AIFit, ...] = Field(min_length=1)

    @field_validator("fits")
    @classmethod
    def _no_repeat(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(v)) != len(v):
            raise ValueError("fits must not repeat a fit")
        return v


class SolutionCatalogue(Strict):
    """The only routes the step assessment may pick (spec 26). `assumed`: an assumed tool set, said so in the report."""

    placeholder: bool
    assumed: bool = False
    version: str = Field(min_length=1)
    solutions: tuple[Solution, ...] = Field(min_length=2, max_length=30)

    @field_validator("solutions")
    @classmethod
    def _catalogue_rules(cls, v: tuple[Solution, ...]) -> tuple[Solution, ...]:
        ids = [s.id for s in v]
        problems = [f"duplicate id {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
        if not any("human" in s.fits for s in v):
            problems.append("at least one entry must fit human (the stays-with-people route)")
        if problems:
            raise ValueError("; ".join(problems))
        return v

    def get(self, id: str) -> Solution | None:
        return next((s for s in self.solutions if s.id == id), None)


# --- Steering (spec 14 §3.15 item 11) -------------------------------------------------------------

Weight = Annotated[float, Field(ge=0)]
CueList = Annotated[tuple[str, ...], Field(min_length=1)]


class SteeringWeights(Strict):
    hours: Weight
    people: Weight
    data: Weight

    @model_validator(mode="after")
    def _sum_to_one(self) -> SteeringWeights:
        total = self.hours + self.people + self.data
        if abs(total - 1) > 0.001:
            raise ValueError(f"weights must sum to 1 (± 0.001), not {total:g}")
        return self


class InputCues(Strict):
    digital: CueList
    paper_verbal: CueList


class SteeringConfig(Strict):
    """How code ranks candidate processes in `find` and how long steering may last."""

    weights: SteeringWeights
    hours_full_score: float = Field(gt=0)
    people_full_score: int = Field(ge=2)
    min_known_signals: int = Field(ge=1, le=3)
    max_candidates: int = Field(ge=2, le=5)
    max_questions: int = Field(ge=1, le=3)
    input_cues: InputCues
    solo_phrases: tuple[str, ...] = ()


class DocumentsConfig(Strict):
    allowed_types: tuple[str, ...] = Field(min_length=1)
    max_files_per_session: int = Field(gt=0)
    max_file_mb: float = Field(gt=0)
    text_budget_chars: int = Field(gt=0)
    max_image_mb: float = Field(gt=0)
    max_image_pixels: int = Field(gt=0)
    image_send_side: int = Field(ge=512, le=4096)


class LanguageWords(Strict):
    yes: tuple[str, ...]
    no: tuple[str, ...]
    roles_cues: tuple[str, ...]
    systems_cues: tuple[str, ...]
    #: Phrases that accept the values the last question offered (spec 14 §3.20 O6, amended 2026-11-21).
    accept: tuple[str, ...] = ()
    #: P14 "the same everywhere" and its opposites; picking one offered candidate (spec 14 §3.20 O2, O11).
    same: tuple[str, ...] = ()
    not_same: tuple[str, ...] = ()
    pick: tuple[str, ...] = ()

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
    solutions: SolutionCatalogue
    steering: SteeringConfig


FILES: dict[str, tuple[str, type[BaseModel]]] = {
    "organisation": ("organisation.yaml", Organisation),
    "taxonomy": ("taxonomy.yaml", Taxonomy),
    "rates": ("rates.yaml", Rates),
    "readiness": ("readiness.yaml", ReadinessConfig),
    "documents": ("documents.yaml", DocumentsConfig),
    "language": ("language.yaml", LanguageConfig),
    "wording": ("wording.yaml", WordingOverrides),
    "solutions": ("solutions.yaml", SolutionCatalogue),
    "steering": ("steering.yaml", SteeringConfig),
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
