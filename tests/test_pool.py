"""Tests for ResourcePool."""

from typing import Any

import pytest

from probos.substrate.agent import BaseAgent
from probos.substrate.pool import ResourcePool
from probos.types import AgentState, CapabilityDescriptor


class PoolAgent(BaseAgent):
    agent_type = "pool_test"
    default_capabilities = [CapabilityDescriptor(can="pool_test")]

    async def perceive(self, intent: dict[str, Any]) -> Any:
        return None

    async def decide(self, observation: Any) -> Any:
        return None

    async def act(self, plan: Any) -> Any:
        return None

    async def report(self, result: Any) -> dict[str, Any]:
        return {}


class TestResourcePool:
    @pytest.mark.asyncio
    async def test_pool_starts_at_target_size(self, spawner, registry, pool_config):
        spawner.register_template("pool_test", PoolAgent)
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=3,
        )
        await pool.start()
        assert pool.current_size == 3
        assert registry.count == 3
        assert len(pool.healthy_agents) == 3
        await pool.stop()

    @pytest.mark.asyncio
    async def test_pool_stop_cleans_up(self, spawner, registry, pool_config):
        spawner.register_template("pool_test", PoolAgent)
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=2,
        )
        await pool.start()
        assert registry.count == 2
        await pool.stop()
        assert pool.current_size == 0
        assert registry.count == 0

    @pytest.mark.asyncio
    async def test_pool_recovers_degraded_agents(self, spawner, registry, pool_config):
        spawner.register_template("pool_test", PoolAgent)
        pool = ResourcePool(
            name="test_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=3,
        )
        await pool.start()

        # Degrade one agent
        agents = registry.get_by_pool("test_pool")
        victim = agents[0]
        for _ in range(30):
            victim.update_confidence(False)
        assert victim.state == AgentState.DEGRADED

        # Health check should recycle and respawn
        health = await pool.check_health()
        assert health["degraded"] >= 1
        assert pool.current_size == 3  # Back to target
        await pool.stop()

    @pytest.mark.asyncio
    async def test_pool_info(self, spawner, registry, pool_config):
        spawner.register_template("pool_test", PoolAgent)
        pool = ResourcePool(
            name="info_pool",
            agent_type="pool_test",
            spawner=spawner,
            registry=registry,
            config=pool_config,
            target_size=2,
        )
        await pool.start()

        info = pool.info()
        assert info["name"] == "info_pool"
        assert info["target_size"] == 2
        assert info["current_size"] == 2
        assert len(info["agents"]) == 2
        await pool.stop()
