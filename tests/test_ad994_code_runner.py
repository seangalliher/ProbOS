"""AD-994: CodeRunnerAgent (run_python, install_package) tests.

BF-287: real agent + a REAL ``ExecutionConfig`` at the config boundary (no
MagicMock — phantom attributes would pass against a mock). Happy-path tests run
real Python subprocesses cross-platform. The venv/pip machinery is exercised
offline (a file:// index that resolves nothing) so it is deterministic without
network access.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.agents.code_runner import CodeRunnerAgent, _venv_python
from probos.config import ExecutionConfig
from probos.types import IntentMessage


def _agent(tmp_path: Path, **exec_kwargs) -> CodeRunnerAgent:
    exec_kwargs.setdefault("scratch_dir", str(tmp_path / "exec"))
    cfg = ExecutionConfig(**exec_kwargs)
    runtime = SimpleNamespace(config=SimpleNamespace(execution=cfg))
    return CodeRunnerAgent(agent_id="cr-test", runtime=runtime)


async def _call(agent: CodeRunnerAgent, intent: str, **params) -> dict:
    msg = IntentMessage(intent=intent, params=params)
    res = await agent.handle_intent(msg)
    return {"success": res.success, "data": res.result, "error": res.error}


# ---------------------------------------------------------------------------
# gating (default OFF)
# ---------------------------------------------------------------------------


async def test_run_python_disabled_returns_error(tmp_path: Path):
    agent = _agent(tmp_path, enabled=False)
    res = await _call(agent, "run_python", code="print('x')")
    assert res["success"] is False
    assert "disabled" in res["error"].lower()


async def test_install_package_disabled_returns_error(tmp_path: Path):
    agent = _agent(tmp_path, enabled=False)
    res = await _call(agent, "install_package", packages=["requests"])
    assert res["success"] is False
    assert "disabled" in res["error"].lower()


async def test_no_runtime_config_degrades(tmp_path: Path):
    # Defense in depth: no runtime wired -> treated as disabled, never raises.
    agent = CodeRunnerAgent(agent_id="cr-bare")
    res = await _call(agent, "run_python", code="print('x')")
    assert res["success"] is False
    assert res["error"]


# ---------------------------------------------------------------------------
# run_python happy path (real subprocess, no network)
# ---------------------------------------------------------------------------


async def test_run_python_happy_path(tmp_path: Path):
    agent = _agent(tmp_path, enabled=True)
    res = await _call(agent, "run_python", code="print('hello-from-script')")
    assert res["success"] is True
    assert "hello-from-script" in res["data"]["stdout"]
    assert res["data"]["exit_code"] == 0
    assert res["data"]["tier"] == 1
    assert res["data"]["installed"] == []


async def test_run_python_nonzero_exit(tmp_path: Path):
    agent = _agent(tmp_path, enabled=True)
    res = await _call(agent, "run_python", code="raise SystemExit(5)")
    assert res["success"] is False
    assert res["data"]["exit_code"] == 5


async def test_run_python_empty_code_errors(tmp_path: Path):
    agent = _agent(tmp_path, enabled=True)
    res = await _call(agent, "run_python", code="   ")
    assert res["success"] is False
    assert "no code" in res["error"].lower()


async def test_run_python_timeout(tmp_path: Path):
    agent = _agent(tmp_path, enabled=True, timeout_seconds=1.0)
    res = await _call(agent, "run_python", code="while True: pass")
    assert res["success"] is False
    assert res["data"]["timed_out"] is True


# ---------------------------------------------------------------------------
# package install gating
# ---------------------------------------------------------------------------


async def test_run_python_with_packages_blocked_when_install_off(tmp_path: Path):
    # enabled but allow_package_install=False -> packages refused without network.
    agent = _agent(tmp_path, enabled=True, allow_package_install=False)
    res = await _call(agent, "run_python", code="print(1)", packages=["requests"])
    assert res["success"] is False
    assert "install disabled" in res["error"].lower()


async def test_install_package_no_packages_errors(tmp_path: Path):
    agent = _agent(tmp_path, enabled=True, allow_package_install=True)
    res = await _call(agent, "install_package", packages=[])
    assert res["success"] is False
    assert "no packages" in res["error"].lower()


# ---------------------------------------------------------------------------
# real venv + pip machinery, exercised offline (deterministic, no network)
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_install_package_offline_degrades_honestly(tmp_path: Path):
    empty_index = tmp_path / "empty_index"
    empty_index.mkdir()
    agent = _agent(
        tmp_path,
        enabled=True,
        allow_package_install=True,
        pip_index_url=empty_index.as_uri(),
        install_timeout_seconds=120.0,
    )
    res = await _call(agent, "install_package", packages=["definitely-not-a-real-pkg-xyz"])
    # The venv is really created and pip really runs; with an empty index the
    # package cannot resolve, so we honest-degrade (no crash, clear error).
    assert res["success"] is False
    assert "pip install failed" in res["error"].lower()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_clean_packages_strips_flags_and_nonstrings():
    clean = CodeRunnerAgent._clean_packages(
        ["requests", "--index-url=evil", "-r", "  numpy  ", "", "x" * 500]
    )
    assert clean == ["requests", "numpy"]


def test_clean_packages_non_list_returns_empty():
    assert CodeRunnerAgent._clean_packages("requests") == []
    assert CodeRunnerAgent._clean_packages(None) == []


def test_resolve_timeout_clamps():
    assert CodeRunnerAgent._resolve_timeout(None, 30.0) == 30.0
    assert CodeRunnerAgent._resolve_timeout(5, 30.0) == 5.0
    assert CodeRunnerAgent._resolve_timeout(99999, 30.0) == 300.0
    assert CodeRunnerAgent._resolve_timeout(-4, 30.0) == 1.0
    assert CodeRunnerAgent._resolve_timeout("bad", 30.0) == 30.0


def test_venv_python_path_is_platform_specific(tmp_path: Path):
    p = _venv_python(tmp_path / "venv")
    if sys.platform == "win32":
        assert p.name == "python.exe"
        assert p.parent.name == "Scripts"
    else:
        assert p.name == "python"
        assert p.parent.name == "bin"
