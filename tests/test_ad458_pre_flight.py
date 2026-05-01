"""AD-458: Tests for Pre-Flight Validation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.pre_flight import (
    PreFlightCheck,
    PreFlightReport,
    PreFlightResult,
    PreFlightRunner,
    TargetFilesExistCheck,
    TargetFilesWritableCheck,
)
from probos.config import PreFlightConfig
from probos.events import EventType


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class _FakeBuildSpec:
    """Stand-in for cognitive/builder.BuildSpec for test isolation."""

    def __init__(self, title: str = "test build", target_files: list[str] | None = None) -> None:
        self.title = title
        self.target_files = list(target_files or [])


# ---------------------------------------------------------------------------
# Tests — EventType + Config
# ---------------------------------------------------------------------------


def test_event_type_preflight_failed_exists() -> None:
    assert EventType.PREFLIGHT_FAILED.value == "preflight_failed"


def test_pre_flight_config_defaults() -> None:
    cfg = PreFlightConfig()
    assert cfg.enabled is True


# ---------------------------------------------------------------------------
# Tests — TargetFilesExistCheck
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_target_files_exist_check_passes_when_present(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    check = TargetFilesExistCheck(repo_root=tmp_path)
    spec = _FakeBuildSpec(target_files=["a.py"])
    result = await check.check(spec)
    assert result.passed is True
    assert "1 target file" in result.detail


@pytest.mark.asyncio
async def test_target_files_exist_check_fails_when_missing(tmp_path: Path) -> None:
    check = TargetFilesExistCheck(repo_root=tmp_path)
    spec = _FakeBuildSpec(target_files=["missing.py"])
    result = await check.check(spec)
    assert result.passed is False
    assert "missing" in result.detail.lower()
    assert "missing.py" in result.detail


@pytest.mark.asyncio
async def test_target_files_exist_check_skips_when_no_target_files(tmp_path: Path) -> None:
    check = TargetFilesExistCheck(repo_root=tmp_path)
    spec = _FakeBuildSpec(target_files=[])
    result = await check.check(spec)
    assert result.passed is True
    assert "CREATE mode" in result.detail


# ---------------------------------------------------------------------------
# Tests — TargetFilesWritableCheck
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_target_files_writable_check_detects_readonly(tmp_path: Path) -> None:
    """Read-only file is detected (Windows ACL approximation noted in WHAT NOT)."""
    f = tmp_path / "ro.py"
    f.write_text("x = 1\n", encoding="utf-8")
    f.chmod(0o444)  # read-only
    try:
        check = TargetFilesWritableCheck(repo_root=tmp_path)
        spec = _FakeBuildSpec(target_files=["ro.py"])
        result = await check.check(spec)
        # On systems where chmod read-only is honored, this should fail
        # On Windows with default ACLs it may pass — flag both as acceptable v1
        if not os.access(f, os.W_OK):
            assert result.passed is False
            assert "ro.py" in result.detail
        else:
            assert result.passed is True
    finally:
        f.chmod(0o644)


# ---------------------------------------------------------------------------
# Tests — PreFlightRunner
# ---------------------------------------------------------------------------


class _BlockingFailCheck:
    name = "blocking_fail"

    async def check(self, spec: Any) -> PreFlightResult:
        return PreFlightResult(passed=False, check_name=self.name, detail="boom", blocking=True)


class _NonBlockingFailCheck:
    name = "non_blocking_fail"

    async def check(self, spec: Any) -> PreFlightResult:
        return PreFlightResult(passed=False, check_name=self.name, detail="soft", blocking=False)


class _PassCheck:
    def __init__(self, name: str = "pass_check") -> None:
        self.name = name
        self.calls = 0

    async def check(self, spec: Any) -> PreFlightResult:
        self.calls += 1
        return PreFlightResult(passed=True, check_name=self.name, detail="ok")


@pytest.mark.asyncio
async def test_pre_flight_runner_short_circuits_on_blocking_failure() -> None:
    second = _PassCheck("second")
    runner = PreFlightRunner(checks=[_BlockingFailCheck(), second])
    report = await runner.run(_FakeBuildSpec())
    assert report.passed is False
    assert second.calls == 0
    assert len(report.results) == 1
    assert report.results[0].check_name == "blocking_fail"


@pytest.mark.asyncio
async def test_pre_flight_runner_continues_on_non_blocking_failure() -> None:
    second = _PassCheck("second")
    runner = PreFlightRunner(checks=[_NonBlockingFailCheck(), second])
    report = await runner.run(_FakeBuildSpec())
    # Non-blocking failure does not abort; second runs
    assert second.calls == 1
    # Aggregate `passed` reflects only blocking failures (none here)
    assert report.passed is True
    assert len(report.results) == 2


@pytest.mark.asyncio
async def test_pre_flight_runner_emits_event_on_failure() -> None:
    emit = MagicMock()
    runner = PreFlightRunner(checks=[_BlockingFailCheck()])
    report = await runner.run(_FakeBuildSpec(title="my-build"), emit_event=emit)
    assert report.passed is False
    assert emit.call_count == 1
    args = emit.call_args.args
    assert args[0] == EventType.PREFLIGHT_FAILED
    payload = args[1]
    assert payload["build_title"] == "my-build"
    assert "started_at" in payload
    assert "completed_at" in payload
    assert payload["check_count"] == 1
    assert isinstance(payload["failures"], list)
    assert payload["failures"][0]["check"] == "blocking_fail"


# ---------------------------------------------------------------------------
# Tests — Protocol runtime_checkable
# ---------------------------------------------------------------------------


def test_pre_flight_check_protocol_is_runtime_checkable(tmp_path: Path) -> None:
    """Concrete check classes satisfy isinstance(impl, PreFlightCheck) via duck typing."""
    impl = TargetFilesExistCheck(repo_root=tmp_path)
    assert isinstance(impl, PreFlightCheck)
