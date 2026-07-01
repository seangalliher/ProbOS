"""Tests for AD-447 PoolGroup phase gates."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.config import (
    FederationConfig,
    MedicalConfig,
    ScalingConfig,
    SelfModConfig,
    SystemConfig,
    UtilityAgentsConfig,
)
from probos.substrate.pool_group import PoolGroup, PoolGroupRegistry


def test_pool_group_startup_phase_default() -> None:
    group = PoolGroup(name="core", display_name="Core")

    assert group.startup_phase == 1


def test_pool_group_custom_phase() -> None:
    group = PoolGroup(name="science", display_name="Science", startup_phase=3)

    assert group.startup_phase == 3


def test_groups_by_phase() -> None:
    registry = PoolGroupRegistry()
    registry.register(PoolGroup(name="science", display_name="Science", startup_phase=3))
    registry.register(PoolGroup(name="core", display_name="Core", startup_phase=1))
    registry.register(PoolGroup(name="security", display_name="Security", startup_phase=2))

    phases = registry.groups_by_phase()

    assert list(phases.keys()) == [1, 2, 3]
    assert [group.name for group in phases[1]] == ["core"]
    assert [group.name for group in phases[2]] == ["security"]
    assert [group.name for group in phases[3]] == ["science"]


def test_get_phase_pools() -> None:
    registry = PoolGroupRegistry()
    registry.register(PoolGroup(name="security", display_name="Security", pool_names={"security_officer"}, startup_phase=2))
    registry.register(PoolGroup(name="engineering", display_name="Engineering", pool_names={"builder", "engineering_officer"}, startup_phase=2))
    registry.register(PoolGroup(name="core", display_name="Core", pool_names={"system"}, startup_phase=1))

    assert registry.get_phase_pools(2) == {"security_officer", "builder", "engineering_officer"}


def test_max_phase() -> None:
    registry = PoolGroupRegistry()
    registry.register(PoolGroup(name="core", display_name="Core", startup_phase=1))
    registry.register(PoolGroup(name="security", display_name="Security", startup_phase=2))
    registry.register(PoolGroup(name="science", display_name="Science", startup_phase=3))
    registry.register(PoolGroup(name="utility", display_name="Utility", startup_phase=4))

    assert registry.max_phase() == 4


def test_max_phase_empty() -> None:
    registry = PoolGroupRegistry()

    assert registry.max_phase() == 0


def test_phase_summary() -> None:
    registry = PoolGroupRegistry()
    registry.register(PoolGroup(name="security", display_name="Security", pool_names={"security_officer"}, startup_phase=2))
    registry.register(PoolGroup(name="engineering", display_name="Engineering", pool_names={"builder", "engineering_officer"}, startup_phase=2))

    summary = registry.phase_summary()

    assert summary == {
        "phase_2": {
            "groups": ["engineering", "security"],
            "pool_count": 3,
        }
    }


@pytest.mark.asyncio
async def test_core_is_phase_1() -> None:
    from probos.startup.fleet_organization import organize_fleet

    config = SystemConfig(
        federation=FederationConfig(enabled=False),
        scaling=ScalingConfig(enabled=False),
        utility_agents=UtilityAgentsConfig(enabled=False),
        medical=MedicalConfig(enabled=False),
        self_mod=SelfModConfig(enabled=False),
    )
    pool_groups = PoolGroupRegistry()

    await organize_fleet(
        config=config,
        pools={},
        pool_groups=pool_groups,
        escalation_manager=MagicMock(),
        intent_bus=MagicMock(),
        trust_network=MagicMock(),
        llm_client=MagicMock(),
        build_pool_intent_map_fn=lambda: {},
        find_consensus_pools_fn=lambda: set(),
        build_self_model_fn=lambda: {},
        validate_remote_result_fn=None,
        nats_bus=None,
    )

    core = pool_groups.get_group("core")
    bridge = pool_groups.get_group("bridge")
    assert core is not None
    assert bridge is not None
    assert core.startup_phase == 1
    assert bridge.startup_phase == 1
    # AD-766: Yeoman joins the Bridge so it renders inside the bridge sphere
    # on the HXI canvas (pool_to_group drives cluster membership).
    assert "counselor" in bridge.pool_names
    assert "yeoman" in bridge.pool_names
    assert pool_groups.get_group_for_pool("yeoman") == "bridge"
