"""AD-815d: cowork-base image smoke test.

File-layout + entrypoint-content checks always run. The build/smoke
pair that actually exercises Docker is skipped when docker is missing
(CI lanes can force-run via COWORK_SMOKE=1).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_DOCKER = shutil.which("docker")
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOCKERFILE_DIR = _REPO_ROOT / "docker" / "cowork-base"


def _docker_available() -> bool:
    if _DOCKER is None:
        return False
    try:
        subprocess.run(
            [_DOCKER, "info"], capture_output=True, timeout=5, check=True
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False
    return True


_NEED_DOCKER = pytest.mark.skipif(
    not _docker_available() and os.environ.get("COWORK_SMOKE") != "1",
    reason="docker not available; set COWORK_SMOKE=1 to force",
)


def test_dockerfile_layout_present():
    assert (_DOCKERFILE_DIR / "Dockerfile").exists()
    assert (_DOCKERFILE_DIR / "cowork-entrypoint.sh").exists()
    assert (_DOCKERFILE_DIR / "README.md").exists()


def test_dockerfile_uses_non_root_probos_user():
    text = (_DOCKERFILE_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert "useradd" in text and "probos" in text
    assert "USER probos" in text


def test_dockerfile_installs_office_stack():
    text = (_DOCKERFILE_DIR / "Dockerfile").read_text(encoding="utf-8")
    for pkg in ("python-docx", "openpyxl", "python-pptx", "weasyprint", "playwright"):
        assert pkg in text, f"missing pinned dep: {pkg}"


def test_entrypoint_handles_requirements_and_extras():
    text = (_DOCKERFILE_DIR / "cowork-entrypoint.sh").read_text(encoding="utf-8")
    assert "requirements.txt" in text
    assert "PROBOS_PIP_EXTRAS" in text
    assert "AD-815e: installed extras" in text


def test_entrypoint_uses_no_deps_install():
    text = (_DOCKERFILE_DIR / "cowork-entrypoint.sh").read_text(encoding="utf-8")
    assert "--no-deps" in text


@_NEED_DOCKER
@pytest.mark.slow
def test_cowork_base_imports_all_pinned_libs():
    build = subprocess.run(
        [_DOCKER, "build", "-t", "probos/cowork-base:test", str(_DOCKERFILE_DIR)],
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert build.returncode == 0, f"docker build failed:\n{build.stderr}"
    run = subprocess.run(
        [
            _DOCKER, "run", "--rm", "probos/cowork-base:test",
            "python", "-c",
            "import docx, openpyxl, pptx, weasyprint, pandas, "
            "playwright, jinja2, bs4, lxml, PIL, reportlab, xlsxwriter; "
            "print('OK')",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, f"smoke run failed:\n{run.stderr}"
    assert "OK" in run.stdout
