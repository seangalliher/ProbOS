"""Tests for PoolGroup and PoolGroupRegistry (AD-291)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.substrate.pool_group import PoolGroup, PoolGroupRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockPool:
    """Minimal pool stub for group_health tests."""

    def __init__(self, agent_type: str, current: int, target: int):
        self._agent_type = agent_type
        self._current = current
        self._target = target

    def info(self) -> dict[str, Any]:
        return {
            "agent_type": self._agent_type,
            "current_size": self._current,
            "target_size": self._target,
        }


# ---------------------------------------------------------------------------
# PoolGroup unit tests
# ---------------------------------------------------------------------------

class TestPoolGroup:
    def test_pool_group_creation(self):
        """Create a PoolGroup and verify all fields."""
        group = PoolGroup(
            name="medical",
            display_name="Medical",
            pool_names={"medical_vitals", "medical_diagnostician"},
            exclude_from_scaler=True,
        )
        assert group.name == "medical"
        assert group.display_name == "Medical"
        assert group.pool_names == {"medical_vitals", "medical_diagnostician"}
        assert group.exclude_from_scaler is True


class TestPoolGroupRegistry:
    @pytest.fixture
    def registry(self) -> PoolGroupRegistry:
        return PoolGroupRegistry()

    def test_register_and_retrieve(self, registry: PoolGroupRegistry):
        """Register a group and verify get_group retrieval."""
        group = PoolGroup(name="core", display_name="Core", pool_names={"system", "filesystem"})
        registry.register(group)
        assert registry.get_group("core") is group
        assert registry.get_group("nonexistent") is None

    def test_reverse_index(self, registry: PoolGroupRegistry):
        """group_for_pool returns the correct group name."""
        registry.register(PoolGroup(
            name="core", display_name="Core", pool_names={"system", "filesystem"},
        ))
        assert registry.group_for_pool("system") == "core"
        assert registry.group_for_pool("filesystem") == "core"

    def test_excluded_pools(self, registry: PoolGroupRegistry):
        """excluded_pools returns union of pools from excluded groups."""
        registry.register(PoolGroup(
            name="core", display_name="Core",
            pool_names={"system", "filesystem"},
            exclude_from_scaler=True,
        ))
        registry.register(PoolGroup(
            name="medical", display_name="Medical",
            pool_names={"medical_vitals"},
            exclude_from_scaler=True,
        ))
        excluded = registry.excluded_pools()
        assert excluded == {"system", "filesystem", "medical_vitals"}

    def test_excluded_pools_mixed(self, registry: PoolGroupRegistry):
        """Only pools from excluded groups appear in excluded_pools."""
        registry.register(PoolGroup(
            name="core", display_name="Core",
            pool_names={"system"},
            exclude_from_scaler=True,
        ))
        registry.register(PoolGroup(
            name="utility", display_name="Utility",
            pool_names={"weather", "news"},
            exclude_from_scaler=False,
        ))
        excluded = registry.excluded_pools()
        assert excluded == {"system"}
        assert "weather" not in excluded
        assert "news" not in excluded

    def test_all_groups_sorted(self, registry: PoolGroupRegistry):
        """all_groups returns groups sorted alphabetically by name."""
        registry.register(PoolGroup(name="medical", display_name="Medical", pool_names=set()))
        registry.register(PoolGroup(name="core", display_name="Core", pool_names=set()))
        registry.register(PoolGroup(name="utility", display_name="Utility", pool_names=set()))
        names = [g.name for g in registry.all_groups()]
        assert names == ["core", "medical", "utility"]

    def test_group_health(self, registry: PoolGroupRegistry):
        """group_health aggregates across pools in a group."""
        registry.register(PoolGroup(
            name="core", display_name="Core Systems",
            pool_names={"system", "filesystem"},
        ))
        pools = {
            "system": _MockPool("system_heartbeat", 2, 2),
            "filesystem": _MockPool("file_reader", 3, 3),
        }
        health = registry.group_health("core", pools)
        assert health["name"] == "core"
        assert health["display_name"] == "Core Systems"
        assert health["total_agents"] == 5
        assert health["healthy_agents"] == 5
        assert health["health_ratio"] == 1.0
        assert "system" in health["pools"]
        assert "filesystem" in health["pools"]

    def test_group_status(self, registry: PoolGroupRegistry):
        """status() returns all group summaries."""
        registry.register(PoolGroup(
            name="core", display_name="Core", pool_names={"system"},
        ))
        registry.register(PoolGroup(
            name="medical", display_name="Medical", pool_names={"medical_vitals"},
        ))
        pools = {
            "system": _MockPool("system_heartbeat", 2, 2),
            "medical_vitals": _MockPool("vitals_monitor", 1, 1),
        }
        status = registry.status(pools)
        assert "core" in status
        assert "medical" in status
        assert status["core"]["total_agents"] == 2
        assert status["medical"]["total_agents"] == 1

    def test_ungrouped_pool(self, registry: PoolGroupRegistry):
        """Pool not in any group returns None from group_for_pool."""
        registry.register(PoolGroup(name="core", display_name="Core", pool_names={"system"}))
        assert registry.group_for_pool("unrelated_pool") is None


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestPoolGroupIntegration:
    def test_runtime_pool_groups_registered(self):
        """Runtime has pool_groups attribute after construction."""
        from probos.runtime import ProbOSRuntime
        rt = ProbOSRuntime()
        assert hasattr(rt, "pool_groups")
        assert isinstance(rt.pool_groups, PoolGroupRegistry)

    @pytest.mark.asyncio
    async def test_scaler_excluded_from_groups(self, tmp_path):
        """After boot, PoolScaler exclusions match pool_groups.excluded_pools()."""
        from probos.runtime import ProbOSRuntime
        from probos.config import SystemConfig

        cfg = SystemConfig()
        cfg.scaling.enabled = True
        rt = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await rt.start()
        try:
            expected = rt.pool_groups.excluded_pools()
            if rt.pool_scaler:
                actual = rt.pool_scaler.excluded_pools
                assert expected == actual
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_status_includes_pool_groups(self, tmp_path):
        """runtime.status() includes pool_groups key."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime(data_dir=tmp_path)
        await rt.start()
        try:
            status = rt.status()
            assert "pool_groups" in status
            groups = status["pool_groups"]
            assert "core" in groups
            assert groups["core"]["display_name"] == "Core Systems"
            assert groups["core"]["total_agents"] > 0
        finally:
            await rt.stop()

    def test_status_panel_renders_groups(self):
        """render_status_panel includes 'Crew Teams' heading when pool_groups present."""
        from probos.experience.panels import render_status_panel

        status = {
            "system": {"name": "ProbOS", "version": "0.1.0", "log_level": "INFO"},
            "started": True,
            "total_agents": 10,
            "pools": {"system": {"current_size": 2, "target_size": 2, "agent_type": "system_heartbeat"}},
            "pool_groups": {
                "core": {
                    "name": "core",
                    "display_name": "Core Systems",
                    "total_agents": 2,
                    "healthy_agents": 2,
                    "health_ratio": 1.0,
                    "pools": {"system": {"current_size": 2, "target_size": 2, "agent_type": "system_heartbeat"}},
                },
            },
            "mesh": {"intent_subscribers": 0, "capability_agents": 0, "gossip_view_size": 0, "hebbian_weights": 0, "active_signals": 0},
            "consensus": {"trust_network_agents": 0, "red_team_agents": 0, "quorum_policy": {}},
            "cognitive": {},
        }
        panel = render_status_panel(status)
        # Panel is a rich.Panel — render to plain string for assertion
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        Console(file=buf, width=120, force_terminal=False).print(panel)
        panel_str = buf.getvalue()
        assert "Crew Teams" in panel_str
        assert "Core Systems" in panel_str
