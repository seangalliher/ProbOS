"""AD-801: tests for the pluggable doctor check registry + new checks."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from probos.doctor import (
    CheckOutcome,
    CheckResult,
    DoctorContext,
    iter_checks,
    register_check,
    run_doctor,
)
from probos.doctor.checks.disk_check import _DiskCheck
from probos.doctor.checks.overlay_check import _OverlayCheck
from probos.doctor.checks.sandbox_check import _SandboxCheck
from probos.doctor.protocol import DoctorCheck
from probos.doctor import registry as registry_module


@pytest.fixture
def fresh_registry():
    """Swap the module-level registry for an isolated copy per test."""
    saved_checks = list(registry_module._CHECKS)
    saved_names = set(registry_module._NAMES)
    registry_module._CHECKS.clear()
    registry_module._NAMES.clear()
    yield
    registry_module._CHECKS.clear()
    registry_module._NAMES.clear()
    registry_module._CHECKS.extend(saved_checks)
    registry_module._NAMES.update(saved_names)


@dataclass(frozen=True)
class _FakeCheck:
    name: str
    outcome: CheckOutcome

    async def run(self, ctx: DoctorContext) -> CheckResult:
        return CheckResult(outcome=self.outcome, message=f"{self.name}: {self.outcome.value}")


def _ctx(tmp_path: Path, config: Any = None) -> DoctorContext:
    home = tmp_path / "home"
    data = tmp_path / "data"
    home.mkdir(exist_ok=True)
    data.mkdir(exist_ok=True)
    return DoctorContext(config=config, home_dir=home, data_dir=data, config_path=None)


# ----- protocol + registry -----


def test_builtin_checks_satisfy_doctorcheck_protocol():
    """Every built-in check is structurally a DoctorCheck."""
    from probos.doctor.checks import (
        config_check, data_dir_check, llm_check, nats_check,
        chroma_check, security_check, disk_check, federation_check,
        overlay_check, sandbox_check,
    )
    modules = [
        config_check, data_dir_check, llm_check, nats_check,
        chroma_check, security_check, disk_check, federation_check,
        overlay_check, sandbox_check,
    ]
    # Each module should have registered at least one check whose object
    # exposes name + async run.
    for check in iter_checks():
        assert isinstance(check, DoctorCheck), f"{check} fails DoctorCheck protocol"
        assert callable(getattr(check, "run", None))
        assert isinstance(check.name, str) and check.name


def test_register_check_rejects_duplicate_name(fresh_registry):
    register_check(_FakeCheck(name="dupe", outcome=CheckOutcome.OK))
    with pytest.raises(ValueError, match="already registered"):
        register_check(_FakeCheck(name="dupe", outcome=CheckOutcome.FAIL))


# ----- runner aggregation semantics -----


@pytest.mark.asyncio
async def test_run_doctor_returns_zero_when_all_ok(fresh_registry, tmp_path):
    register_check(_FakeCheck(name="a", outcome=CheckOutcome.OK))
    register_check(_FakeCheck(name="b", outcome=CheckOutcome.OK))
    code = await run_doctor(argparse.Namespace(), Console(), ctx=_ctx(tmp_path))
    assert code == 0


@pytest.mark.asyncio
async def test_run_doctor_returns_fail_count(fresh_registry, tmp_path):
    register_check(_FakeCheck(name="ok", outcome=CheckOutcome.OK))
    register_check(_FakeCheck(name="bad1", outcome=CheckOutcome.FAIL))
    register_check(_FakeCheck(name="bad2", outcome=CheckOutcome.FAIL))
    code = await run_doctor(argparse.Namespace(), Console(), ctx=_ctx(tmp_path))
    assert code == 2


@pytest.mark.asyncio
async def test_warn_does_not_increment_fail_count(fresh_registry, tmp_path):
    register_check(_FakeCheck(name="ok", outcome=CheckOutcome.OK))
    register_check(_FakeCheck(name="warn", outcome=CheckOutcome.WARN))
    code = await run_doctor(argparse.Namespace(), Console(), ctx=_ctx(tmp_path))
    assert code == 0


@pytest.mark.asyncio
async def test_check_raising_is_treated_as_fail(fresh_registry, tmp_path):
    @dataclass(frozen=True)
    class _Boom:
        name: str = "boom"
        async def run(self, ctx: DoctorContext) -> CheckResult:
            raise RuntimeError("simulated check failure")
    register_check(_Boom())
    code = await run_doctor(argparse.Namespace(), Console(), ctx=_ctx(tmp_path))
    assert code == 1


# ----- disk_check thresholds -----


@pytest.mark.asyncio
async def test_disk_check_fail_below_100mb(tmp_path, monkeypatch):
    from probos.doctor.checks import disk_check as disk_module
    class _Usage:
        free = 50 * 1024 * 1024  # 50 MB
    monkeypatch.setattr(disk_module.shutil, "disk_usage", lambda _p: _Usage())
    result = await _DiskCheck().run(_ctx(tmp_path))
    assert result.outcome is CheckOutcome.FAIL


@pytest.mark.asyncio
async def test_disk_check_warn_below_1gb(tmp_path, monkeypatch):
    from probos.doctor.checks import disk_check as disk_module
    class _Usage:
        free = 500 * 1024 * 1024  # 500 MB
    monkeypatch.setattr(disk_module.shutil, "disk_usage", lambda _p: _Usage())
    result = await _DiskCheck().run(_ctx(tmp_path))
    assert result.outcome is CheckOutcome.WARN


@pytest.mark.asyncio
async def test_disk_check_ok_when_plenty_free(tmp_path, monkeypatch):
    from probos.doctor.checks import disk_check as disk_module
    class _Usage:
        free = 50 * 1024 * 1024 * 1024  # 50 GB
    monkeypatch.setattr(disk_module.shutil, "disk_usage", lambda _p: _Usage())
    result = await _DiskCheck().run(_ctx(tmp_path))
    assert result.outcome is CheckOutcome.OK


# ----- overlay_check reporting -----


@pytest.mark.asyncio
async def test_overlay_check_reports_oss_only_when_no_providers(tmp_path, monkeypatch):
    from probos.extensions import overlay as overlay_module
    monkeypatch.setattr(overlay_module, "loaded_providers", lambda: ())
    monkeypatch.setattr(overlay_module, "is_commercial_loaded", lambda: False)
    monkeypatch.setattr(overlay_module, "discover_extensions", lambda: None)
    result = await _OverlayCheck().run(_ctx(tmp_path))
    assert result.outcome is CheckOutcome.OK
    assert "OSS-only" in result.message


@pytest.mark.asyncio
async def test_overlay_check_lists_providers_when_loaded(tmp_path, monkeypatch):
    from probos.extensions import overlay as overlay_module
    monkeypatch.setattr(overlay_module, "loaded_providers", lambda: ("commercial",))
    monkeypatch.setattr(overlay_module, "is_commercial_loaded", lambda: True)
    monkeypatch.setattr(overlay_module, "discover_extensions", lambda: None)
    result = await _OverlayCheck().run(_ctx(tmp_path))
    assert result.outcome is CheckOutcome.OK
    assert "commercial" in result.message.lower()


# ----- sandbox_check forward-compat behavior -----


@pytest.mark.asyncio
async def test_sandbox_check_inprocess_default_is_ok(tmp_path):
    # No security.sandbox_backend on the default config -> default 'inprocess'.
    class _Cfg:
        security = None
    ctx = DoctorContext(config=_Cfg(), home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    result = await _SandboxCheck().run(ctx)
    assert result.outcome is CheckOutcome.OK
    assert "in-process" in result.message


@pytest.mark.asyncio
async def test_sandbox_check_container_with_no_docker_is_fail(tmp_path, monkeypatch):
    from probos.doctor.checks import sandbox_check as sb
    class _Sec:
        sandbox_backend = "container"
    class _Cfg:
        security = _Sec()
    monkeypatch.setattr(sb, "_docker_info_sync", lambda _t: (False, "docker: command not found"))
    ctx = DoctorContext(config=_Cfg(), home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    result = await _SandboxCheck().run(ctx)
    assert result.outcome is CheckOutcome.FAIL
    assert "docker" in result.message.lower()
