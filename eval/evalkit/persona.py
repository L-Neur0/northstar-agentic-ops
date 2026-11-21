"""Persona files: the simulated experts and their hidden true processes (spec 24 §3.2, §3.3).

Why: a persona is the test case of the evaluation. If a file names a field the registry does not
know, a cluster the taxonomy does not have, or a route the catalogue does not hold, every score
built on it is meaningless, so a bad file must stop the run before any model call (exit 2).
What: the Pydantic models (`Persona`, `Truth`, `Expected`, ...), `load_personas` (validation against
the field registry, the taxonomy, the solution catalogue and the document types) and `Company`, the
few company facts the runner reads from `config/<company>/*.yaml` (codes, routes, regions, the
yes / no words). `HARD_CAP` is the evaluation's own limit on expert messages (§3.9a).
Must not: import the engine beyond the field registry (AC-24.29), or change any file it reads.
Spec 24 §3.2, §4; AC-24.1, AC-24.2.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.services.process_discovery.domain.field_spec import PROFILE_SPECS, STEP_SPECS

HARD_CAP = 80  # safety net (spec 24 §3.9a, amended 2026-11-20; was 60)
EVAL_DIR = Path(__file__).resolve().parents[1]
PROCESS_KEYS: tuple[str, ...] = tuple(s.key for s in PROFILE_SPECS)
STEP_LEAVES: tuple[str, ...] = tuple(s.key for s in STEP_SPECS if s.weight > 0)  # scored leaves: S01-S11, S13
OPTIONAL_STEP_LEAVES: tuple[str, ...] = tuple(s.key for s in STEP_SPECS if s.weight == 0)  # S12
FITS = ("automate", "assist", "human")
DEFAULT_CONFLICT_WORDS = ("mine", "the document's", "the documents", "both", "my version", "the document")


class PersonaError(ValueError):
    """A persona file that cannot be used; names the file and the key."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WeekItem(Strict):
    name: str
    runs: str = ""
    time: str = ""
    people: str = ""
    inputs: str = ""


class Truth(Strict):
    fields: dict[str, Any]
    steps: list[dict[str, Any]]
    aliases: dict[str, list[str]] = Field(default_factory=dict)
    disclose: dict[str, Literal["always", "vague", "never"]] = Field(default_factory=dict)
    week: list[WeekItem] = Field(default_factory=list)


class StaleValue(Strict):
    key: str
    doc_value: str


class PersonaDocument(Strict):
    file: str
    at: dict[str, Any]
    stale: list[StaleValue] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_moment(self) -> PersonaDocument:
        if len(self.at) != 1 or next(iter(self.at)) not in ("start", "turn", "phase"):
            raise ValueError("`at` must be exactly one of {start: true}, {turn: n}, {phase: <phase>}")
        return self


class Steering(Strict):
    recommended: str
    chosen: str
    ideas: list[str] = Field(default_factory=list)


class StepRoute(Strict):
    fit: list[Literal["automate", "assist", "human"]]
    route: list[str]


class Expected(Strict):
    cluster: str
    scope: Literal["process", "task"] = "process"
    steering: Steering | None = None
    routes: dict[int, StepRoute] = Field(default_factory=dict)
    min_conflicts: int = 0


class Persona(Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,48}$")
    version: int = Field(ge=1)
    quick: bool = False
    seed: bool = False
    kind: Literal["cooperative", "difficult"]
    profile: str
    behaviour: list[str] = Field(min_length=2, max_length=10)
    truth: Truth
    documents: list[PersonaDocument] = Field(default_factory=list, max_length=3)
    expected: Expected

    def disclose(self, key: str) -> str:
        """`always`, `vague` or `never` for a process key or a step leaf (`steps[*].<leaf>`)."""
        if key in self.truth.disclose:
            return self.truth.disclose[key]
        leaf = key.rsplit(".", 1)[-1]
        return self.truth.disclose.get(f"steps[*].{leaf}", "always")

    @property
    def truth_field_count(self) -> int:
        """P01-P16 plus every scored step leaf (registry weight > 0) of every true step (§3.7 item 5)."""
        criteria = sum(1 for step in self.truth.steps if "decision_criteria" in step)  # §12 V2
        return len(PROCESS_KEYS) + len(STEP_LEAVES) * len(self.truth.steps) + criteria


@dataclass(frozen=True)
class Company:
    """The company facts the evaluation checks persona files against (read from YAML, no engine import)."""

    clusters: frozenset[str]
    catalogue: Mapping[str, frozenset[str]]  # route id -> fits it allows
    regions: tuple[str, ...]
    allowed_types: frozenset[str]
    yes_no_words: frozenset[str] = field(default_factory=frozenset)


def load_company(config_dir: Path) -> Company:
    def read(name: str) -> Any:
        return yaml.safe_load((config_dir / name).read_text(encoding="utf-8")) or {}

    taxonomy, solutions, organisation = read("taxonomy.yaml"), read("solutions.yaml"), read("organisation.yaml")
    documents, language = read("documents.yaml"), read("language.yaml")
    words: set[str] = set(DEFAULT_CONFLICT_WORDS)
    for lang in (language.get("languages") or {}).values():
        for key in ("yes", "no", "conflict", "mine", "theirs", "both"):
            words.update(str(w).lower() for w in lang.get(key) or [])
    return Company(
        clusters=frozenset(str(c["code"]) for c in taxonomy.get("clusters") or []),
        catalogue={str(s["id"]): frozenset(s.get("fits") or []) for s in solutions.get("solutions") or []},
        regions=tuple(organisation.get("regions") or []),
        allowed_types=frozenset(str(t).lower() for t in documents.get("allowed_types") or []),
        yes_no_words=frozenset(words),
    )


def _check(persona: Persona, company: Company, documents_dir: Path) -> list[str]:
    """Every problem in one persona, as `key: why`."""
    problems: list[str] = []
    fields = persona.truth.fields
    problems += [f"truth.fields.{k}: not a registry key" for k in fields if k not in PROCESS_KEYS]
    problems += [f"truth.fields.{k}: missing" for k in PROCESS_KEYS if k not in fields]
    count = fields.get("process.substep_count")
    if count != len(persona.truth.steps):
        problems.append(f"truth.fields.process.substep_count: {count} but truth.steps has {len(persona.truth.steps)}")
    for i, step in enumerate(persona.truth.steps, start=1):
        problems += [
            f"truth.steps[{i}].{k}: not a registry key" for k in step if k not in (*STEP_LEAVES, *OPTIONAL_STEP_LEAVES)
        ]
        problems += [f"truth.steps[{i}].{k}: missing" for k in STEP_LEAVES if k not in step]
        kind = str((step.get("decision_type") or {}).get("kind") or "")
        if "decision_criteria" in step and kind not in ("judgement", "mix"):
            problems.append(f"truth.steps[{i}].decision_criteria: only for a judgement or mix step (§12 V2)")
    if fields.get("process.cluster") not in company.clusters:
        problems.append(f"truth.fields.process.cluster: unknown cluster {fields.get('process.cluster')!r}")
    if company.regions and fields.get("region") not in company.regions:
        problems.append(f"truth.fields.region: not a configured region {fields.get('region')!r}")
    if persona.expected.cluster not in company.clusters:
        problems.append(f"expected.cluster: unknown cluster {persona.expected.cluster!r}")
    for number, route in persona.expected.routes.items():
        if not 1 <= number <= len(persona.truth.steps):
            problems.append(f"expected.routes.{number}: no such step")
        for rid in route.route:
            if rid not in company.catalogue:
                problems.append(f"expected.routes.{number}.route: {rid!r} is not in solutions.yaml")
            elif not company.catalogue[rid] & set(route.fit):
                problems.append(f"expected.routes.{number}.route: {rid!r} allows none of {route.fit}")
    steering = persona.expected.steering
    if steering is not None:
        names = {w.name.lower() for w in persona.truth.week} | {str(fields.get("process.name", "")).lower()}
        for name in (steering.recommended, steering.chosen):
            if name.lower() not in names:
                problems.append(f"expected.steering: {name!r} is not in truth.week or the process name")
    for doc in persona.documents:
        suffix = doc.file.rsplit(".", 1)[-1].lower()
        if suffix not in company.allowed_types:
            problems.append(f"documents.{doc.file}: type {suffix!r} is not allowed")
        if not (documents_dir / doc.file).is_file():
            problems.append(f"documents.{doc.file}: file not found")
    return problems


def load_persona(path: Path, company: Company, documents_dir: Path) -> Persona:
    try:
        persona = Persona.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (ValidationError, yaml.YAMLError) as error:
        raise PersonaError(f"{path.name}: {error}") from None
    problems = _check(persona, company, documents_dir)
    if problems:
        raise PersonaError(f"{path.name}: " + "; ".join(problems))
    return persona


def load_personas(
    folder: Path,
    *,
    quick: bool,
    company: Company,
    documents_dir: Path | None = None,
    only: tuple[str, ...] = (),
) -> list[Persona]:
    """Every persona in `folder` (only `quick: true` ones with `quick`), sorted by id. Raises `PersonaError`."""
    documents_dir = documents_dir or folder.parent / "documents"
    personas = [load_persona(p, company, documents_dir) for p in sorted(folder.glob("*.yaml"))]
    ids = [p.id for p in personas]
    if len(ids) != len(set(ids)):
        raise PersonaError("persona ids must be unique")
    if quick:
        personas = [p for p in personas if p.quick]
    if only:
        personas = [p for p in personas if p.id in only]
    return personas
