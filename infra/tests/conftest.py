"""Shared fixtures for the infra tests (spec 25 §7).

Why: every template test reads the same compiled ARM JSON; compiling once per session keeps the
suite fast and makes sure all tests judge the exact template azd would deploy.
What: `build` (the `az bicep build` result: ARM JSON plus linter diagnostics), `template`, and
`resources(...)`, which walks the main template and every nested module deployment.
Must not: deploy, call Azure, or need a login; `az bicep build` is a local compile.
Spec: 25 §7. Acceptance criteria: shared by AC-25.8 to AC-25.20, AC-25.29.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
INFRA = REPO / "infra"
DIAGNOSTIC = re.compile(r" : (Warning|Error) ")


@dataclass(frozen=True)
class Build:
    returncode: int
    template: dict[str, Any]
    diagnostics: list[str]


@dataclass(frozen=True)
class Resource:
    module: str  # "" for main, else the module deployment name
    body: dict[str, Any]
    template: dict[str, Any]  # the (nested) template that declares it

    @property
    def type(self) -> str:
        return self.body["type"]

    @property
    def props(self) -> dict[str, Any]:
        return self.body.get("properties", {})


@pytest.fixture(scope="session")
def build() -> Build:
    if shutil.which("az") is None:
        pytest.skip("Azure CLI (az) with Bicep is needed to compile the template")
    proc = subprocess.run(
        ["az", "bicep", "build", "--file", str(INFRA / "main.bicep"), "--stdout"],
        capture_output=True,
        text=True,
        check=False,
    )
    diagnostics = [line for line in proc.stderr.splitlines() if DIAGNOSTIC.search(line)]
    template = json.loads(proc.stdout) if proc.returncode == 0 else {}
    return Build(proc.returncode, template, diagnostics)


@pytest.fixture(scope="session")
def template(build: Build) -> dict[str, Any]:
    assert build.returncode == 0, build.diagnostics
    return build.template


def _as_list(resources: Any) -> list[dict[str, Any]]:
    return list(resources.values()) if isinstance(resources, dict) else list(resources)


def walk(template: dict[str, Any], module: str = "") -> Iterator[Resource]:
    for res in _as_list(template.get("resources", [])):
        yield Resource(module, res, template)
        if res["type"] == "Microsoft.Resources/deployments":
            yield from walk(res["properties"]["template"], res["name"])


@pytest.fixture(scope="session")
def resources(template: dict[str, Any]) -> list[Resource]:
    return list(walk(template))


def one(resources: list[Resource], type_: str) -> Resource:
    found = [r for r in resources if r.type == type_ and not r.body.get("existing")]
    assert len(found) == 1, f"expected one {type_}, found {len(found)}"
    return found[0]


def module(template: dict[str, Any], name: str) -> dict[str, Any]:
    for res in _as_list(template["resources"]):
        if res["type"] == "Microsoft.Resources/deployments" and res["name"] == name:
            return res
    raise AssertionError(f"module {name} not found")
