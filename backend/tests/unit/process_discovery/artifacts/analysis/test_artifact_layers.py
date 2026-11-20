"""Layer guard inside `artifacts`: `analysis/` and `diagram/` never import each other (spec 18 §2; AC-18.40).

Why: each package must be deletable on its own, and what they share lives in `profile_fence.py`,
`evidence.py` and `fingerprint.py`. The engine-wide layer test (spec 10) checks the peers, not the
sub-packages, so this test reads the same `ast` import graph and adds the rule for the two packages.
It also proves the check bites, on a planted bad import.
"""

from __future__ import annotations

from pathlib import Path

from tests.unit.process_discovery.test_architecture import PACKAGE_ROOT, internal_imports

FORBIDDEN = {
    "analysis": ("artifacts.diagram", "export"),
    "diagram": ("artifacts.analysis", "export"),
}


def _offenders(root: Path, package: str) -> list[str]:
    found = []
    for path in sorted((root / "artifacts" / package).rglob("*.py")):
        relative = path.relative_to(root)
        for target, name in internal_imports(relative, root):
            if any(target == bad or target.startswith(bad + ".") for bad in FORBIDDEN[package]):
                found.append(f"{relative.as_posix()} imports {target}.{name}")
    return found


def test_analysis_and_diagram_do_not_import_each_other_or_export():
    """AC-18.40."""
    assert _offenders(PACKAGE_ROOT, "analysis") == []
    assert _offenders(PACKAGE_ROOT, "diagram") == []


def test_the_guard_catches_a_planted_import(tmp_path):
    for package in ("analysis", "diagram"):
        (tmp_path / "artifacts" / package).mkdir(parents=True)
    (tmp_path / "artifacts" / "analysis" / "x.py").write_text('"""x."""\nfrom ..diagram import grounding\n')
    (tmp_path / "artifacts" / "diagram" / "y.py").write_text('"""y."""\nfrom ...export import bpmn\n')
    assert _offenders(tmp_path, "analysis") == ["artifacts/analysis/x.py imports artifacts.diagram.grounding"]
    assert _offenders(tmp_path, "diagram") == ["artifacts/diagram/y.py imports export.bpmn"]
