"""Every Python file starts with a header docstring (spec 10, AC-10.20; project coding rules).

Why: a reader (or an agent) must learn why a file exists, what it does and which spec it
implements before reading its code. The rule is only real if a test enforces it.
What: parses every module under `app/` and `tests/` and checks for a docstring of at least three
sentences.
"""

import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
FILES = sorted(p for root in ("app", "tests") for p in (BACKEND / root).rglob("*.py") if "__pycache__" not in p.parts)


def sentences(text: str) -> int:
    return len([s for s in re.split(r"[.!?](?:\s|$)", text) if s.strip()])


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(BACKEND)))
def test_module_has_a_header(path):
    doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    assert doc, f"{path.relative_to(BACKEND)} has no module docstring"
    assert sentences(doc) >= 3, f"{path.relative_to(BACKEND)}: header needs why, what and the spec it implements"
