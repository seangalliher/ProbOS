"""BF-892 (#1543): model-authored code outside the run_python sandbox no longer inherits the runtime's environment.

Each test plants a synthetic credential-shaped variable, first proves a child that INHERITS
this process's environment sees it (the premise), then proves the site's child does not.
Children print or write only booleans, never an environment value or listing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from probos.cognitive import dependency_resolver as dependency_resolver_module
from probos.cognitive.builder import _run_targeted_tests, _run_tests
from probos.cognitive.dependency_resolver import DependencyResolver
from probos.security.container_sandbox import ContainerExec, InProcessContainerSandbox, SandboxLimits

PLANT_NAME = "BF892_PROBE_API_KEY"
PLANT_VALUE = "bf892-planted-secret-4c1"
_SEES_PLANT = f"import os; print(os.environ.get({PLANT_NAME!r}) == {PLANT_VALUE!r})"


@pytest.fixture
def plant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PLANT_NAME, PLANT_VALUE)


def _inheriting_child_sees_plant() -> bool:
    done = subprocess.run([sys.executable, "-c", _SEES_PLANT], env=None, capture_output=True, text=True, timeout=60)
    return done.stdout.strip() == "True"


def _write_model_test(work: Path) -> Path:
    tests = work / "tests"
    tests.mkdir()
    (tests / "test_probe_env.py").write_text(
        "import json, os\n\n"
        "def test_records_what_the_child_sees():\n"
        f"    seen = {{'plant': os.environ.get({PLANT_NAME!r}) == {PLANT_VALUE!r},\n"
        f"            'pythonpath': {str(work)!r} in os.environ.get('PYTHONPATH', '').split(os.pathsep)}}\n"
        "    open('seen.json', 'w').write(json.dumps(seen))\n",
        encoding="utf-8",
    )
    return work / "seen.json"


def test_premise_an_inheriting_child_sees_the_plant(plant: None) -> None:
    assert _inheriting_child_sees_plant(), "premise: a child that inherits this process's environment must see the planted variable"


@pytest.mark.timeout(150)
async def test_run_tests_hides_the_plant_and_keeps_pythonpath(plant: None, tmp_path: Path) -> None:
    assert _inheriting_child_sees_plant(), "premise: an inheriting child must see the planted variable"
    seen_path = _write_model_test(tmp_path)

    passed, _ = await _run_tests(str(tmp_path), timeout=120)

    assert passed and seen_path.exists(), "premise: the model test must run and pass under _run_tests"
    assert json.loads(seen_path.read_text(encoding="utf-8")) == {"plant": False, "pythonpath": True}


@pytest.mark.timeout(150)
async def test_run_targeted_tests_hides_the_plant(plant: None, tmp_path: Path) -> None:
    assert _inheriting_child_sees_plant(), "premise: an inheriting child must see the planted variable"
    seen_path = _write_model_test(tmp_path)

    passed, _, test_files = await _run_targeted_tests(str(tmp_path), ["tests/test_probe_env.py"], timeout=120)

    assert test_files == [str(tmp_path / "tests" / "test_probe_env.py")], (
        "premise: the targeted path must run, not the full-suite fallback"
    )
    assert passed and seen_path.exists(), "premise: the targeted model test must run and pass"
    assert json.loads(seen_path.read_text(encoding="utf-8")) == {"plant": False, "pythonpath": True}


async def test_inprocess_container_hides_the_plant_and_keeps_request_env(plant: None) -> None:
    assert _inheriting_child_sees_plant(), "premise: an inheriting child must see the planted variable"
    request = ContainerExec(
        command=[
            sys.executable,
            "-c",
            f"import os; print(os.environ.get({PLANT_NAME!r}) == {PLANT_VALUE!r}, os.environ.get('BF892_EXTENSION') == 'kept')",
        ],
        egress_policy="bridge",
        env={"BF892_EXTENSION": "kept"},
        limits=SandboxLimits(wall_timeout_seconds=30),
    )

    out = await InProcessContainerSandbox().run(request)

    # Read into locals so a failed assert shows booleans and tokens, never the outcome's repr.
    ran_to_completion = out.success
    words = out.stdout.split()
    assert ran_to_completion, "premise: the probe command must run to completion in the in-process sandbox"
    assert words == ["False", "True"]


async def test_dependency_install_hides_the_plant_on_every_method(plant: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # Captured BEFORE the patch below: subprocess.run is one module-wide attribute, so the
    # premise and every probe child must go through the real function, not the stand-in.
    real_run = subprocess.run
    premise = real_run([sys.executable, "-c", _SEES_PLANT], env=None, capture_output=True, text=True, timeout=60)
    inheriting_child_sees_plant = premise.stdout.strip() == "True"
    assert inheriting_child_sees_plant, "premise: an inheriting child must see the planted variable"

    seen: list[tuple[str, bool]] = []

    def _probe_run(argv, **kw):
        # .strip(): the child prints "True\n"; comparing without it would never flip the flag.
        done = real_run([sys.executable, "-c", _SEES_PLANT], env=kw.get("env"), capture_output=True, text=True, timeout=60)
        seen.append((" ".join(map(str, argv[1:3])), done.stdout.strip() == "True"))
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(dependency_resolver_module.subprocess, "run", _probe_run)
    monkeypatch.setattr(dependency_resolver_module.shutil, "which", lambda name: "uv-bf892-fake")

    ok, _ = await DependencyResolver(allowed_imports=[])._install_package("bf892-not-a-package")

    assert ok is False
    assert [label for label, _ in seen] == ["-m pip", "pip install", "add bf892-not-a-package"]
    assert [flag for _, flag in seen] == [False, False, False]


async def test_dependency_install_keeps_virtual_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path))
    envs: list[dict[str, str] | None] = []

    def _record_run(argv, **kw):
        envs.append(kw.get("env"))
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(dependency_resolver_module.subprocess, "run", _record_run)
    monkeypatch.setattr(dependency_resolver_module.shutil, "which", lambda name: "uv-bf892-fake")

    await DependencyResolver(allowed_imports=[])._install_package("bf892-not-a-package")

    assert len(envs) == 3, "premise: pip, uv pip and uv add must each be reached"
    assert all(env is not None for env in envs), "premise: every method must be handed an explicit environment"
    assert [env.get("VIRTUAL_ENV") == str(tmp_path) for env in envs] == [True, True, True]


async def test_dependency_install_omits_unset_virtual_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    envs: list[dict[str, str] | None] = []

    def _record_run(argv, **kw):
        envs.append(kw.get("env"))
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(dependency_resolver_module.subprocess, "run", _record_run)
    monkeypatch.setattr(dependency_resolver_module.shutil, "which", lambda name: "uv-bf892-fake")

    await DependencyResolver(allowed_imports=[])._install_package("bf892-not-a-package")

    assert len(envs) == 3, "premise: pip, uv pip and uv add must each be reached"
    assert all(env is not None for env in envs), "premise: every method must be handed an explicit environment"
    assert ["VIRTUAL_ENV" not in env for env in envs] == [True, True, True]
