"""BF-245: NATS/xdist stream isolation tests."""

import os

import pytest

from probos.config import NatsConfig


def test_nats_config_env_override_disables(monkeypatch):
    """BF-245: PROBOS_NATS_ENABLED=false overrides config enabled=True."""
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "false")
    cfg = NatsConfig(enabled=True)
    assert cfg.enabled is False


def test_nats_config_env_override_enables(monkeypatch):
    """BF-245: PROBOS_NATS_ENABLED=true overrides config enabled=False."""
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "true")
    cfg = NatsConfig(enabled=False)
    assert cfg.enabled is True


def test_nats_config_no_env_preserves_default(monkeypatch):
    """BF-245: Without env var, config value is used as-is."""
    monkeypatch.delenv("PROBOS_NATS_ENABLED", raising=False)
    cfg = NatsConfig(enabled=True)
    assert cfg.enabled is True


def test_nats_config_no_arg_respects_env(monkeypatch):
    """BF-245: NatsConfig() with no args still checks PROBOS_NATS_ENABLED."""
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "true")
    cfg = NatsConfig()
    assert cfg.enabled is True


@pytest.mark.asyncio
async def test_init_nats_returns_none_when_disabled(monkeypatch):
    """BF-245: init_nats skips connection when NATS disabled via env."""
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "false")
    from probos.startup.nats import init_nats
    from probos.config import SystemConfig
    config = SystemConfig()
    result = await init_nats(config)
    assert result is None


def test_conftest_sets_nats_disabled():
    """BF-245: conftest.py sets PROBOS_NATS_ENABLED=false at import time."""
    assert os.environ.get("PROBOS_NATS_ENABLED") == "false"


@pytest.mark.asyncio
async def test_runtime_starts_without_nats(tmp_path, monkeypatch):
    """BF-245: ProbOSRuntime.start() succeeds with NATS disabled, no stream creation."""
    from unittest.mock import patch
    from probos.runtime import ProbOSRuntime
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "false")
    with patch("probos.mesh.nats_bus.NATSBus") as mock_bus_cls:
        rt = ProbOSRuntime(data_dir=tmp_path / "data")
        await rt.start()
        assert rt._started
        assert rt.nats_bus is None
        mock_bus_cls.assert_not_called()
        await rt.stop()


def test_real_nats_fixture_enables(real_nats):
    """BF-245: real_nats fixture sets PROBOS_NATS_ENABLED=true."""
    assert os.environ.get("PROBOS_NATS_ENABLED") == "true"