"""Checks of the Dockerfile and the Docker build context (spec 25 §3.2, §7).

Why: the image must stay small, non-root and free of private material. A stray `COPY .` or a
missing `.dockerignore` line would put `.work/` or `brief/` into a public image; these tests
fail before that can happen.
What: parses `Dockerfile` (stages, pinned bases, user, command, no HEALTHCHECK, no stage or
secret baked in) and `.dockerignore`; then builds a throw-away image that copies the filtered
context and lists it, to prove the excluded paths never reach the build (AC-25.6).
Must not: push an image or call Azure. The listing image is removed after the test.
Spec: 25 §3.2. Acceptance criteria: AC-25.4, AC-25.6, AC-25.7.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from conftest import REPO

DOCKERFILE = (REPO / "Dockerfile").read_text()
IGNORE = [
    line.strip()
    for line in (REPO / ".dockerignore").read_text().splitlines()
    if line.strip() and not line.startswith("#")
]
FROMS = re.findall(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", DOCKERFILE, re.M)


def _runtime_stage() -> str:
    return DOCKERFILE.split("AS runtime", 1)[1]


def test_three_stages_with_pinned_bases() -> None:
    assert [stage for _, stage in FROMS] == ["web", "deps", "runtime"]
    for image, _ in FROMS:
        assert re.search(r":\d+\.\d+", image), f"{image} is not pinned to a minor version"
    assert FROMS[1][0] == FROMS[2][0], "deps and runtime must use the same Python base"
    assert FROMS[0][0].startswith("node:22")
    assert FROMS[2][0].startswith("python:3.12")
    assert re.search(r"COPY --from=ghcr\.io/astral-sh/uv:\d+\.\d+\.\d+ ", DOCKERFILE)


def test_ac_25_4_runtime_is_non_root_without_dev_tools() -> None:
    runtime = _runtime_stage()
    assert "USER 10001:10001" in runtime
    assert "--uid 10001" in runtime and "--gid 10001" in runtime
    assert "uv" not in re.findall(r"COPY --from=(\S+)", runtime)
    copied = re.findall(r"^COPY (?:--from=\S+ )?(\S+)", runtime, re.M)
    assert set(copied) == {"/app/backend/.venv", "backend/app", "config", "/src/frontend/dist"}
    assert "backend/tests" not in runtime


def test_ac_25_7_one_uvicorn_worker_on_port_8000() -> None:
    match = re.search(r"^CMD (\[.*?\])\s*$", DOCKERFILE.replace("\\\n", ""), re.M | re.S)
    assert match
    cmd = json.loads(match.group(1))
    assert cmd[:3] == ["uvicorn", "app.main:app", "--factory"]
    assert cmd[cmd.index("--port") + 1] == "8000"
    assert cmd[cmd.index("--workers") + 1] == "1"
    assert "gunicorn" not in DOCKERFILE
    assert "EXPOSE 8000" in DOCKERFILE


def test_no_healthcheck_stage_or_secret_baked_in() -> None:
    assert not re.search(r"^HEALTHCHECK", DOCKERFILE, re.M)
    assert "ARG APP_VERSION" in DOCKERFILE
    env_lines = " ".join(re.findall(r"^ENV .*?(?<!\\)$", DOCKERFILE, re.M | re.S))
    for name in ("DEPLOYMENT_STAGE", "WORKSPACE_", "AZURE_OPENAI_API_KEY", "STORE"):
        assert name not in env_lines


def test_ac_25_6_dockerignore_lists_private_and_local_paths() -> None:
    required = {".git", ".github", ".work", "brief", ".azure", ".env*", "**/node_modules", "**/.venv",
                "**/__pycache__", "**/.cache", "frontend/dist", "backend/tests", "eval", "docs", "specs", "infra"}  # fmt: skip
    assert required <= set(IGNORE)
    assert "**/.env*" in IGNORE  # backend/.env too


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker is needed to list the build context")
def test_ac_25_6_build_context_has_no_private_paths() -> None:
    base = FROMS[2][0]
    listing = f"FROM {base}\nCOPY . /ctx\n"
    tag = "discovery-agent-context-listing:test"
    build = subprocess.run(
        ["docker", "build", "-q", "-t", tag, "-f", "-", str(REPO)],
        input=listing, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert build.returncode == 0, build.stderr
    try:
        out = subprocess.run(
            ["docker", "run", "--rm", tag, "find", "/ctx"], capture_output=True, text=True, check=True
        ).stdout.splitlines()
    finally:
        subprocess.run(["docker", "rmi", "-f", tag], capture_output=True, check=False)
    paths = {p.removeprefix("/ctx/") for p in out if p != "/ctx"}
    assert "backend/app/main.py" in paths and "frontend/package-lock.json" in paths and "config/nig" in paths
    forbidden = (".work", "brief", ".azure", ".git", ".github", "backend/tests", "infra", "frontend/dist")
    for p in paths:
        parts = p.split("/")
        assert not any(p == f or p.startswith(f + "/") for f in forbidden), p
        assert "node_modules" not in parts and ".venv" not in parts, p
        assert not parts[-1].startswith(".env"), p
