"""AD-457: Tests for Engineering Crew (Performance / Maintenance / Damage Control)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.agents.engineering import (
    DamageControlAgent,
    MaintenanceAgent,
    PerformanceMonitorAgent,
)
from probos.config import EngineeringConfig
from probos.events import EventType


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeRuntime:
    def __init__(self, pools: dict[str, Any] | None = None) -> None:
        self.pools = pools or {}
        self.emit_event = MagicMock()


# ---------------------------------------------------------------------------
# Tests — EventTypes & Config
# ---------------------------------------------------------------------------


def test_event_type_damage_control_activated_exists() -> None:
    assert EventType.DAMAGE_CONTROL_ACTIVATED.value == "damage_control_activated"


def test_event_type_maintenance_scheduled_exists() -> None:
    assert EventType.MAINTENANCE_SCHEDULED.value == "maintenance_scheduled"


def test_event_type_performance_threshold_breached_exists() -> None:
    assert EventType.PERFORMANCE_THRESHOLD_BREACHED.value == "performance_threshold_breached"


def test_engineering_config_defaults() -> None:
    cfg = EngineeringConfig()
    assert cfg.enabled is True
    assert cfg.performance_interval_seconds == 10.0
    assert cfg.maintenance_interval_seconds == 300.0
    assert cfg.damage_control_cooldown_seconds == 60.0


# ---------------------------------------------------------------------------
# Tests — PerformanceMonitorAgent
# ---------------------------------------------------------------------------


def test_performance_monitor_init_inherits_heartbeat() -> None:
    agent = PerformanceMonitorAgent()
    assert agent.agent_type == "performance_monitor"
    assert agent.tier == "core"
    assert agent.pool == "engineering_performance"
    assert any(c.can == "performance_monitor" for c in agent.default_capabilities)


@pytest.mark.asyncio
async def test_performance_monitor_collect_metrics_no_runtime() -> None:
    agent = PerformanceMonitorAgent(runtime=None)
    metrics = await agent.collect_metrics()
    assert "timestamp" in metrics
    assert "agent_id" in metrics
    # No runtime → no active_pools key
    assert "active_pools" not in metrics


# ---------------------------------------------------------------------------
# Tests — MaintenanceAgent
# ---------------------------------------------------------------------------


def test_maintenance_agent_default_pool_name() -> None:
    agent = MaintenanceAgent()
    assert agent.pool == "engineering_maintenance"
    assert agent.agent_type == "maintenance"


@pytest.mark.asyncio
async def test_maintenance_agent_schedules_due_tasks() -> None:
    rt = _FakeRuntime()
    agent = MaintenanceAgent(runtime=rt)
    await agent.collect_metrics()
    # All 4 default tasks scheduled on first cycle
    assert rt.emit_event.call_count == 4
    event_types = [call.args[0] for call in rt.emit_event.call_args_list]
    assert all(et == EventType.MAINTENANCE_SCHEDULED for et in event_types)
    tasks_emitted = {call.args[1]["task"] for call in rt.emit_event.call_args_list}
    assert tasks_emitted == {"database_compact", "log_rotate", "cache_evict", "pool_rebalance"}


@pytest.mark.asyncio
async def test_maintenance_agent_skips_recently_scheduled() -> None:
    rt = _FakeRuntime()
    agent = MaintenanceAgent(runtime=rt)
    await agent.collect_metrics()  # First cycle: 4 emits
    rt.emit_event.reset_mock()
    await agent.collect_metrics()  # Second cycle: nothing due
    assert rt.emit_event.call_count == 0


# ---------------------------------------------------------------------------
# Tests — DamageControlAgent
# ---------------------------------------------------------------------------


def test_damage_control_default_pool_name() -> None:
    agent = DamageControlAgent()
    assert agent.pool == "engineering_damage_control"
    assert agent.agent_type == "damage_control"


def test_damage_control_activate_known_signature() -> None:
    rt = _FakeRuntime()
    agent = DamageControlAgent(runtime=rt)
    activated = agent.activate("llm_brownout")
    assert activated is True
    assert rt.emit_event.call_count == 1
    args = rt.emit_event.call_args.args
    assert args[0] == EventType.DAMAGE_CONTROL_ACTIVATED
    payload = args[1]
    assert payload["signature"] == "llm_brownout"
    assert payload["recovery_action"] == "llm_failover_to_secondary_tier"


def test_damage_control_activate_unknown_signature() -> None:
    rt = _FakeRuntime()
    agent = DamageControlAgent(runtime=rt)
    activated = agent.activate("garbage")
    assert activated is False
    assert rt.emit_event.call_count == 0


def test_damage_control_cooldown_blocks_repeat() -> None:
    rt = _FakeRuntime()
    agent = DamageControlAgent(runtime=rt, cooldown_seconds=60.0)
    first = agent.activate("llm_brownout")
    second = agent.activate("llm_brownout")
    assert first is True
    assert second is False
    assert rt.emit_event.call_count == 1


# ---------------------------------------------------------------------------
# Tests — module exports
# ---------------------------------------------------------------------------


def test_engineering_init_module_exports() -> None:
    """from probos.agents.engineering import ... succeeds for all 3 agents."""
    from probos.agents.engineering import (
        DamageControlAgent as DCA,
        MaintenanceAgent as MA,
        PerformanceMonitorAgent as PMA,
    )
    assert DCA is DamageControlAgent
    assert MA is MaintenanceAgent
    assert PMA is PerformanceMonitorAgent
