"""AD-993: SubprocessSandbox (Tier-1 isolation) tests.

BF-287: real subprocess execution against the host interpreter, no mocks at the
substrate boundary. Resource-limit assertions are POSIX-only (the ``resource``
module does not exist on Windows); those tests are skipped on win32.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from probos.execution.isolation import (
    ExecutionRequest,
    ExecutionResult,
    IsolationBackend,
    IsolationTier,
    SubprocessSandbox,
)


def _sandbox(tmp_path: Path) -> SubprocessSandbox:
    return SubprocessSandbox(scratch_root=str(tmp_path / "scratch"))


# ---------------------------------------------------------------------------
# protocol + tier
# ---------------------------------------------------------------------------


def test_sandbox_satisfies_protocol(tmp_path: Path):
    sb = _sandbox(tmp_path)
    assert isinstance(sb, IsolationBackend)
    assert sb.tier == IsolationTier.SUBPROCESS == 1
    assert sb.available() is True


# ---------------------------------------------------------------------------
# code execution
# ---------------------------------------------------------------------------


async def test_runs_code_captures_stdout(tmp_path: Path):
    res = await _sandbox(tmp_path).run(ExecutionRequest(code="print('hi-there')"))
    assert isinstance(res, ExecutionResult)
    assert res.success is True
    assert res.exit_code == 0
    assert "hi-there" in res.stdout
    assert res.tier == 1


async def test_argv_execution(tmp_path: Path):
    res = await _sandbox(tmp_path).run(
        ExecutionRequest(argv=[sys.executable, "-c", "print(1 + 1)"])
    )
    assert res.success is True
    assert res.stdout.strip() == "2"


async def test_nonzero_exit_marks_failure(tmp_path: Path):
    res = await _sandbox(tmp_path).run(ExecutionRequest(code="import sys; sys.exit(2)"))
    assert res.success is False
    assert res.exit_code == 2
    assert res.timed_out is False


async def test_stderr_captured(tmp_path: Path):
    res = await _sandbox(tmp_path).run(
        ExecutionRequest(code="import sys; sys.stderr.write('boom'); sys.exit(1)")
    )
    assert res.success is False
    assert "boom" in res.stderr


# ---------------------------------------------------------------------------
# bounds
# ---------------------------------------------------------------------------


async def test_timeout_kills(tmp_path: Path):
    res = await _sandbox(tmp_path).run(
        ExecutionRequest(code="while True: pass", timeout_seconds=1.0)
    )
    assert res.success is False
    assert res.timed_out is True


async def test_output_capped(tmp_path: Path):
    cap = 1024
    res = await _sandbox(tmp_path).run(
        ExecutionRequest(
            code="print('A' * 100000)",
            max_output_bytes=cap,
        )
    )
    # Output is truncated to the cap (a short truncation marker may be appended).
    assert len(res.stdout) <= cap + 64


# ---------------------------------------------------------------------------
# honest-degrade (never raises out of run)
# ---------------------------------------------------------------------------


async def test_bad_executable_degrades(tmp_path: Path):
    res = await _sandbox(tmp_path).run(
        ExecutionRequest(
            code="print('x')",
            python_executable="/no/such/python-xyz",
        )
    )
    assert res.success is False
    assert res.error
    assert res.timed_out is False


async def test_no_code_or_argv_degrades(tmp_path: Path):
    res = await _sandbox(tmp_path).run(ExecutionRequest())
    assert res.success is False
    assert res.error


# ---------------------------------------------------------------------------
# scratch lifecycle
# ---------------------------------------------------------------------------


async def test_internal_scratch_is_reaped(tmp_path: Path):
    res = await _sandbox(tmp_path).run(ExecutionRequest(code="print('ok')"))
    assert res.success is True
    # When the sandbox creates the workdir, it reaps it afterwards.
    assert res.workdir
    assert not Path(res.workdir).exists()


async def test_explicit_workdir_not_reaped(tmp_path: Path):
    work = tmp_path / "caller_owned"
    work.mkdir()
    res = await _sandbox(tmp_path).run(
        ExecutionRequest(code="print('ok')", workdir=work)
    )
    assert res.success is True
    # The caller owns an explicitly-passed workdir; the sandbox must not delete it.
    assert work.exists()


# ---------------------------------------------------------------------------
# POSIX-only resource limits
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="resource limits are POSIX-only")
async def test_memory_limit_enforced(tmp_path: Path):
    # Try to allocate ~1 GB under a 128 MB cap -> the child should die.
    res = await _sandbox(tmp_path).run(
        ExecutionRequest(
            code="x = bytearray(1024 * 1024 * 1024)",
            max_memory_mb=128,
            timeout_seconds=10.0,
        )
    )
    assert res.success is False
    assert res.timed_out is False
