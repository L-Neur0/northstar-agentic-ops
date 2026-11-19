"""Layer guards for the discovery engine, `app/services/process_discovery` (spec 10 §3.9).

Why: the engine is layered (foundations, then `domain/`, `profile/`, `interview/`, then the
peers `documents/`, `artifacts/`, `admin/`, `export/`, `overview/`, then `service.py` and the
facade), and dependencies must run one way only. A convention in a design document is checked
by whoever remembers it; this file turns it into a build failure instead.

What: the import graph is read with `ast`, not a regex, because the import that causes trouble
(`from ..interview import nodes`, three directories down) is the one a grep never sees. A second
test checks that the HTTP layer (`app/api`) reaches the engine only through its facade.

Implements spec 10, AC-10.16 and AC-10.17.
"""

import ast
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[3] / "app"
PACKAGE_ROOT = APP_ROOT / "services" / "process_discovery"
PREFIX = "app.services.process_discovery."

PEERS = ("documents", "artifacts", "admin", "export", "overview")

# For each layer, the layers it may not import. Read a row as "a module under `domain/` must not
# know that `profile/` exists".
FORBIDDEN: dict[str, tuple[str, ...]] = {
    "domain": ("profile", "interview", *PEERS, "service"),
    "profile": ("interview", *PEERS, "service"),
    "interview": (*PEERS, "service"),
    **{peer: (*(p for p in PEERS if p != peer), "interview", "service") for peer in PEERS},
}

# Each exception carries its reason. Every model call must see the profile rendered the same way,
# so the assessment and the document reader may reuse the interview's renderer instead of a second
# renderer that drifts from the first.
ALLOWED_EXCEPTIONS = {
    ("artifacts", "interview.prompts.common.render_profile"),
    ("documents", "interview.prompts.common.render_profile"),
}

# Infrastructure at the bottom of the stack: imported by anything, importing only other infrastructure.
INFRASTRUCTURE = ("llm.py", "json_schema.py", "fake_llm.py", "llm_cache.py")


def test_infrastructure_may_use_infrastructure_but_nothing_above(tmp_path):
    """`llm.py` may import `json_schema`; it may not import `domain/`."""
    (tmp_path / "llm.py").write_text(
        '"""x."""\nfrom .json_schema import strict_json_schema\nfrom .domain import field_spec\n'
    )
    imports = [t for t, _ in internal_imports(Path("llm.py"), tmp_path)]
    infra = {name.removesuffix(".py") for name in INFRASTRUCTURE}
    assert [t for t in imports if t.split(".")[0] not in infra] == ["domain"]


def _package_modules(root: Path = PACKAGE_ROOT) -> list[Path]:
    """Every module in the engine, as a path relative to the engine root."""
    return sorted(p.relative_to(root) for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def internal_imports(relative_path: Path, root: Path = PACKAGE_ROOT):
    """Yield `(target_module, imported_name)` for each import that stays inside the engine.

    `target_module` is dotted and relative to the engine root, so `from ..interview import nodes`
    inside `artifacts/diagram/prompts.py` comes back as `("interview", "nodes")`.
    """
    source = (root / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(relative_path))
    here = relative_path.parts[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 0:
                module = node.module or ""
                if not module.startswith(PREFIX):
                    continue
                target = module[len(PREFIX) :]
            else:
                climbed = node.level - 1
                if climbed > len(here):
                    continue
                base = here[: len(here) - climbed] if climbed else here
                target = ".".join([*base, *((node.module or "").split("."))]).strip(".")
                if not target:
                    for alias in node.names:
                        yield alias.name, None
                    continue
            for alias in node.names:
                yield target, alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(PREFIX):
                    yield alias.name[len(PREFIX) :], None


def violations(root: Path = PACKAGE_ROOT) -> list[str]:
    """Every forbidden import in the engine under `root`, as readable messages."""
    found = []
    for relative_path in _package_modules(root):
        layer = relative_path.parts[0] if len(relative_path.parts) > 1 else None
        if layer not in FORBIDDEN:
            continue
        for target, name in internal_imports(relative_path, root):
            target_layer = target.split(".")[0]
            if target_layer not in FORBIDDEN[layer]:
                continue
            if (layer, f"{target}.{name}") in ALLOWED_EXCEPTIONS:
                continue
            found.append(f"{relative_path.as_posix()} ({layer}/) imports {target}.{name} ({target_layer}/)")
    return found


def api_deep_imports(api_root: Path = APP_ROOT / "api") -> list[str]:
    """Imports from `app/api` that reach past the engine facade."""
    found = []
    for path in sorted(api_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                if name.startswith(PREFIX):
                    found.append(f"{path.name} imports {name}")
    return found


def test_the_scaffold_has_no_layer_violation():
    """AC-10.17: the rules hold on the code as it is."""
    assert violations() == []


@pytest.mark.parametrize("filename", INFRASTRUCTURE)
def test_infrastructure_imports_nothing_internal(filename):
    """The client and schema helpers sit below everything; they may use each other, nothing above them.

    An import back up into the engine would be an import-time cycle.
    """
    if not (PACKAGE_ROOT / filename).exists():
        pytest.skip(f"{filename} not written yet")
    infra = {name.removesuffix(".py") for name in INFRASTRUCTURE}
    offenders = [
        f"{t}.{n}" if n else t
        for t, n in internal_imports(Path(filename))
        if t.split(".")[0] not in infra and not (t == "" or (n is None and t in infra))
    ]
    assert offenders == []


def test_api_reaches_the_engine_only_through_its_facade():
    """AC-10.16 (second half): routes import `app.services.process_discovery`, never a deeper path."""
    assert api_deep_imports() == []


def test_an_upward_import_is_caught(tmp_path):
    """AC-10.16: a module in `domain/` that imports `profile/` fails the guard."""
    (tmp_path / "domain").mkdir()
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "mutate.py").write_text('"""x."""\n')
    (tmp_path / "domain" / "bad.py").write_text('"""x."""\nfrom ..profile import mutate\n')
    assert violations(tmp_path) == ["domain/bad.py (domain/) imports profile.mutate (profile/)"]


def test_a_peer_importing_a_peer_is_caught(tmp_path):
    """Peers stay separately deletable: `export/` may not import `artifacts/`."""
    (tmp_path / "export").mkdir()
    (tmp_path / "export" / "x.py").write_text(
        '"""x."""\nfrom app.services.process_discovery.artifacts.analysis import analyse\n'
    )
    assert violations(tmp_path) == ["export/x.py (export/) imports artifacts.analysis.analyse (artifacts/)"]


def test_the_allowed_renderer_exception_passes(tmp_path):
    """The one listed exception is allowed; anything else from `interview/` is not."""
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "ok.py").write_text('"""x."""\nfrom ..interview.prompts.common import render_profile\n')
    (tmp_path / "artifacts" / "bad.py").write_text('"""x."""\nfrom ..interview.nodes import guide_node\n')
    assert violations(tmp_path) == ["artifacts/bad.py (artifacts/) imports interview.nodes.guide_node (interview/)"]


def test_a_deep_api_import_is_caught(tmp_path):
    """AC-10.16: `app/api` importing a deep engine path fails."""
    (tmp_path / "routes.py").write_text('"""x."""\nfrom app.services.process_discovery.profile import mutate\n')
    assert api_deep_imports(tmp_path) == ["routes.py imports app.services.process_discovery.profile"]
