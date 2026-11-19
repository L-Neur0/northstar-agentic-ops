"""Import-order guard for the models, the config loader and the registry (spec 12 §2).

Why: `app.core.config` and the models import domain modules, and the engine facade will import
`service.py`, which imports the models; a facade that loads the service eagerly would close an
import cycle that only shows in a fresh interpreter, in whichever order the app happens to start.
What: for each entry point, a clean subprocess imports it alone and then checks that
`app.services.process_discovery.service` was never loaded. Implements AC-12.44.
"""

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[3]

SCRIPT = """
import importlib, sys
importlib.import_module({module!r})
loaded = [m for m in sys.modules if m.startswith("app.services.process_discovery.service")]
print("LOADED" if loaded else "ok")
"""


@pytest.mark.parametrize(
    "module",
    [
        "app.models.process_discovery_schemas",
        "app.core.config",
        "app.services.process_discovery.domain.field_spec",
        "app.services.process_discovery",
    ],
)
def test_each_entry_point_imports_alone_without_the_service(module):
    """AC-12.44."""
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT.format(module=module)],
        cwd=BACKEND,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_the_facade_loads_unknown_names_lazily():
    """AC-12.44: the facade resolves names on demand and refuses unknown ones clearly."""
    import app.services.process_discovery as facade

    with pytest.raises(AttributeError):
        facade.definitely_not_a_use_case  # noqa: B018
