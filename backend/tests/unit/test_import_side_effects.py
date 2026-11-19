"""Importing the app must have no side effects (spec 10 §3.5, AC-10.3).

Why: objects created at import time (settings, clients, singletons) make tests depend on the
environment and hide configuration errors until the first request.
What: in a clean subprocess with an empty environment, forbid building `Settings`, then import
every module under `app/`. Any import-time construction fails the test.
"""

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

SCRIPT = r"""
import importlib, pkgutil, sys
import app.core.settings as s
def refuse(*a, **k):
    raise RuntimeError("Settings created at import time")
s.Settings.__init__ = refuse
import app
for m in pkgutil.walk_packages(app.__path__, "app."):
    importlib.import_module(m.name)
print("ok")
"""


def test_importing_every_module_creates_nothing():
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        cwd=BACKEND,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("ok")
