"""`eval/` reaches the backend only through the pieces spec 24 §2 allows (AC-24.29), and every eval file has a header.

Why: an evaluation that imported interview internals or prompts could score things the API never
shows. An AST scan keeps the boundary real. What: parses every module under `eval/` (tests
included, except this guard's own fixtures) and checks backend imports against the allow-list, and
that each file starts with a docstring of at least three sentences. Must not: import the modules.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[1]
ALLOWED = (
    "app.main",
    "app.core.settings",
    "app.services.store.memory",
    "app.services.store.cosmos",
    "app.services.process_discovery.llm",
    "app.services.process_discovery.fake_llm",
    "app.services.process_discovery.domain",
    "app.models.process_discovery_schemas",  # spec 24 §13 D5: the demo copy is a stored `Session`
)
FILES = sorted(p for p in EVAL.rglob("*.py") if "__pycache__" not in p.parts)


def _imports(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return [n for n in names if n == "app" or n.startswith("app.")]


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(EVAL)))
def test_ac_24_29_backend_imports_stay_on_the_allow_list(path):
    bad = [n for n in _imports(path) if not any(n == a or n.startswith(f"{a}.") for a in ALLOWED)]
    assert not bad, f"{path.relative_to(EVAL)} imports {bad}"


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(EVAL)))
def test_every_eval_file_has_a_header(path):
    doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
    assert len([s for s in re.split(r"[.!?](?:\s|$)", doc) if s.strip()]) >= 3, path.name
