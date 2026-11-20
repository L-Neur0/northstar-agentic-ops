"""Layer guard for the assessment sub-packages that call a model (spec 26 §2, spec 19 §2).

Why: `step_assessment/`, `labels/`, `analysis/` and `diagram/` are peers inside `artifacts/`; each must
be removable on its own, so none may import another. What they share lives in `profile_fence.py`,
`evidence.py` and `fingerprint.py`. The engine-wide layer test does not look inside `artifacts/`, so
this file adds the check, reading imports with the same `ast` walker.
What: the check on the real code, and a planted violation in a temporary tree to prove it fires.
Must not: change the engine-wide rules in `test_architecture.py`.
Covers AC-26.19 (and the spec 19 §2 rule that `labels/` never imports `analysis/` or `diagram/`).
"""

from __future__ import annotations

from pathlib import Path

from tests.unit.process_discovery.test_architecture import PACKAGE_ROOT, internal_imports

PEERS = ("step_assessment", "labels", "analysis", "diagram")


def peer_violations(root: Path = PACKAGE_ROOT) -> list[str]:
    found: list[str] = []
    for peer in PEERS:
        folder = root / "artifacts" / peer
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*.py")):
            relative = path.relative_to(root)
            for target, name in internal_imports(relative, root):
                parts = target.split(".")
                if len(parts) >= 2 and parts[0] == "artifacts" and parts[1] in PEERS and parts[1] != peer:
                    found.append(f"{relative.as_posix()} imports {target}.{name}")
    return found


def test_ac_26_19_peers_do_not_import_each_other() -> None:
    assert peer_violations() == []


def test_ac_26_19_a_peer_import_is_caught(tmp_path: Path) -> None:
    (tmp_path / "artifacts" / "step_assessment").mkdir(parents=True)
    (tmp_path / "artifacts" / "labels").mkdir()
    (tmp_path / "artifacts" / "labels" / "x.py").write_text(
        '"""x."""\nfrom ..step_assessment.route import route_summary\n'
    )
    (tmp_path / "artifacts" / "step_assessment" / "y.py").write_text('"""y."""\nfrom ..evidence import find_evidence\n')
    assert peer_violations(tmp_path) == ["artifacts/labels/x.py imports artifacts.step_assessment.route.route_summary"]
