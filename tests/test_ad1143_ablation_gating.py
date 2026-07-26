"""AD-1143 — the default-gate guard for the ablation harness's exclusion.

``tests/ablation/`` is excluded from collection structurally, by a conditional
``collect_ignore_glob`` in its own ``conftest.py``, rather than by a
``pytest.mark.skipif`` like the three existing opt-in benches. ``skipif`` still
*imports* the module during collection, and the ablation runner imports
``CrewOrchestrator``, ``CrewTaskExecutor``, ``WorkItemAgenticExecutor`` and the
store layer — so an import-time failure there would break the default gate for
everyone. ``collect_ignore_glob`` means the file is never opened.

That exclusion has a cost, and this file is where it is paid: a file CI never
opens is a file whose syntax rot is invisible. The third test below
``compile()``s every module in the package at AST level — **no import, no
execution**. That is the whole mitigation. It does not catch import errors or
type errors, and nothing here pretends otherwise; the structural mode
(``PROBOS_ABLATION=structural``) is what exercises those.

Three tests, a few seconds, in the default gate. That is the price of the
exclusion.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ABLATION_DIR = REPO_ROOT / "tests" / "ablation"
ABLATION_CONFTEST = ABLATION_DIR / "conftest.py"

EXIT_NOTESTSCOLLECTED = 5


def _load_conftest_with(monkeypatch: pytest.MonkeyPatch, mode: str | None) -> Any:
    """Import the ablation conftest by path under a given env value.

    Loaded by path and never registered in ``sys.modules`` so this never
    collides with the real conftest pytest loads in opt-in mode. ``monkeypatch``
    restores the ambient value even if the import raises.
    """
    if mode is None:
        monkeypatch.delenv("PROBOS_ABLATION", raising=False)
    else:
        monkeypatch.setenv("PROBOS_ABLATION", mode)
    spec = importlib.util.spec_from_file_location(
        "_ad1143_ablation_conftest_probe", ABLATION_CONFTEST,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (None, ["test_*.py"]),
        ("", ["test_*.py"]),
        ("1", ["test_*.py"]),
        ("true", ["test_*.py"]),
        ("Structural", ["test_*.py"]),
        ("yes", ["test_*.py"]),
        ("structural", []),
        ("live", []),
    ],
)
def test_ablation_collection_gate_opens_only_for_the_two_named_modes(
    monkeypatch: pytest.MonkeyPatch,
    mode: str | None,
    expected: list[str],
) -> None:
    """Fail closed: only ``structural`` and ``live`` open collection."""
    module = _load_conftest_with(monkeypatch, mode)
    assert module.collect_ignore_glob == expected
    assert module.VALID_MODES == frozenset({"structural", "live"})


def test_default_collection_finds_no_ablation_tests() -> None:
    """Behavioural proof, in one subprocess.

    ``-o addopts=`` is mandatory: ``pyproject.toml`` sets
    ``addopts = "-n 16 --dist=loadfile"`` and inheriting it would spawn 16 xdist
    workers inside a unit test.
    """
    env = {k: v for k, v in os.environ.items() if k != "PROBOS_ABLATION"}
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            "tests/ablation",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == EXIT_NOTESTSCOLLECTED, (
        f"expected EXIT_NOTESTSCOLLECTED ({EXIT_NOTESTSCOLLECTED}), got "
        f"{completed.returncode}:\n{output}"
    )
    assert "no tests ran" in output.lower() or "no tests collected" in output.lower()
    assert "test_sigma_ablation" not in output
    assert "test_sigma_harness_structural" not in output


def test_every_ablation_module_compiles() -> None:
    """AST-only sweep. No import, no execution — this is the syntax-rot net."""
    sources = sorted(ABLATION_DIR.rglob("*.py"))
    assert sources, f"no python modules found under {ABLATION_DIR}"
    names = {path.name for path in sources}
    assert {"conftest.py", "sigma_flags.py", "test_sigma_ablation.py"} <= names
    for path in sources:
        source = path.read_text(encoding="utf-8")
        try:
            compile(source, str(path), "exec")
        except SyntaxError as exc:  # pragma: no cover - only on real rot
            pytest.fail(f"{path} does not compile: {exc}")
