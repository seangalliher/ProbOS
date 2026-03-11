"""Tests for deterministic agent identity (Phase 14c)."""

from __future__ import annotations

import asyncio
import pytest

from probos.substrate.identity import generate_agent_id, generate_pool_ids


# ------------------------------------------------------------------
# Identity generation tests
# ------------------------------------------------------------------


class TestGenerateAgentId:
    def test_returns_string(self):
        result = generate_agent_id("file_reader", "filesystem", 0)
        assert isinstance(result, str)

    def test_deterministic(self):
        a = generate_agent_id("file_reader", "filesystem", 0)
        b = generate_agent_id("file_reader", "filesystem", 0)
        assert a == b

    def test_different_inputs_produce_different_ids(self):
        a = generate_agent_id("file_reader", "filesystem", 0)
        b = generate_agent_id("file_reader", "filesystem", 1)
        c = generate_agent_id("file_writer", "filesystem", 0)
        d = generate_agent_id("file_reader", "other_pool", 0)
        assert len({a, b, c, d}) == 4

    def test_id_format_is_human_readable(self):
        result = generate_agent_id("file_reader", "filesystem", 0)
        assert "file_reader" in result
        assert "filesystem" in result
        assert "_0_" in result

    def test_idempotent_across_calls(self):
        ids = [generate_agent_id("shell_command", "shell", 2) for _ in range(10)]
        assert len(set(ids)) == 1


class TestGeneratePoolIds:
    def test_returns_correct_count(self):
        ids = generate_pool_ids("file_reader", "filesystem", 3)
        assert len(ids) == 3

    def test_all_unique(self):
        ids = generate_pool_ids("file_reader", "filesystem", 5)
        assert len(set(ids)) == 5

    def test_stable_across_calls(self):
        a = generate_pool_ids("file_reader", "filesystem", 3)
        b = generate_pool_ids("file_reader", "filesystem", 3)
        assert a == b


# ------------------------------------------------------------------
# BaseAgent agent_id kwarg tests
# ------------------------------------------------------------------


class TestAgentIdKwarg:
    def test_agent_accepts_agent_id_kwarg(self):
        from probos.substrate.agent import BaseAgent

        class _DummyAgent(BaseAgent):
            agent_type = "dummy"

            async def perceive(self, intent):
                return None

            async def decide(self, obs):
                return None

            async def act(self, plan):
                return None

            async def report(self, result):
                return {}

        agent = _DummyAgent(pool="test", agent_id="my_stable_id")
        assert agent.id == "my_stable_id"

    def test_agent_without_agent_id_falls_back_to_uuid(self):
        from probos.substrate.agent import BaseAgent

        class _DummyAgent(BaseAgent):
            agent_type = "dummy"

            async def perceive(self, intent):
                return None

            async def decide(self, obs):
                return None

            async def act(self, plan):
                return None

            async def report(self, result):
                return {}

        a = _DummyAgent(pool="test")
        b = _DummyAgent(pool="test")
        assert a.id != b.id  # random UUIDs differ
        assert len(a.id) == 32  # uuid4 hex length


# ------------------------------------------------------------------
# Spawner forwarding test
# ------------------------------------------------------------------


class TestSpawnerForwardsAgentId:
    @pytest.mark.asyncio
    async def test_spawn_forwards_agent_id(self):
        from probos.substrate.spawner import AgentSpawner
        from probos.substrate.registry import AgentRegistry
        from probos.substrate.agent import BaseAgent

        class _DummyAgent(BaseAgent):
            agent_type = "dummy"

            async def perceive(self, intent):
                return None

            async def decide(self, obs):
                return None

            async def act(self, plan):
                return None

            async def report(self, result):
                return {}

        registry = AgentRegistry()
        spawner = AgentSpawner(registry)
        spawner.register_template("dummy", _DummyAgent)

        agent = await spawner.spawn("dummy", "test_pool", agent_id="spawner_id_42")
        assert agent.id == "spawner_id_42"
        await agent.stop()


# ------------------------------------------------------------------
# Pool tests
# ------------------------------------------------------------------


class TestPoolWithDeterministicIds:
    @pytest.mark.asyncio
    async def test_pool_uses_provided_agent_ids(self):
        from probos.substrate.pool import ResourcePool
        from probos.substrate.spawner import AgentSpawner
        from probos.substrate.registry import AgentRegistry
        from probos.substrate.agent import BaseAgent
        from probos.config import PoolConfig

        class _DummyAgent(BaseAgent):
            agent_type = "dummy"

            async def perceive(self, intent):
                return None

            async def decide(self, obs):
                return None

            async def act(self, plan):
                return None

            async def report(self, result):
                return {}

        registry = AgentRegistry()
        spawner = AgentSpawner(registry)
        spawner.register_template("dummy", _DummyAgent)
        cfg = PoolConfig()

        predetermined = ["id_a", "id_b"]
        pool = ResourcePool(
            name="test_pool",
            agent_type="dummy",
            spawner=spawner,
            registry=registry,
            config=cfg,
            target_size=2,
            agent_ids=predetermined,
        )
        await pool.start()
        assert pool._agent_ids == ["id_a", "id_b"]
        await pool.stop()

    @pytest.mark.asyncio
    async def test_pool_without_agent_ids_falls_back_to_random(self):
        from probos.substrate.pool import ResourcePool
        from probos.substrate.spawner import AgentSpawner
        from probos.substrate.registry import AgentRegistry
        from probos.substrate.agent import BaseAgent
        from probos.config import PoolConfig

        class _DummyAgent(BaseAgent):
            agent_type = "dummy"

            async def perceive(self, intent):
                return None

            async def decide(self, obs):
                return None

            async def act(self, plan):
                return None

            async def report(self, result):
                return {}

        registry = AgentRegistry()
        spawner = AgentSpawner(registry)
        spawner.register_template("dummy", _DummyAgent)
        cfg = PoolConfig()

        pool = ResourcePool(
            name="test_pool",
            agent_type="dummy",
            spawner=spawner,
            registry=registry,
            config=cfg,
            target_size=2,
        )
        await pool.start()
        # IDs should be random UUIDs (32 hex chars)
        assert len(pool._agent_ids) == 2
        assert pool._agent_ids[0] != pool._agent_ids[1]
        await pool.stop()

    @pytest.mark.asyncio
    async def test_add_agent_generates_deterministic_id(self):
        from probos.substrate.pool import ResourcePool
        from probos.substrate.spawner import AgentSpawner
        from probos.substrate.registry import AgentRegistry
        from probos.substrate.agent import BaseAgent
        from probos.config import PoolConfig

        class _DummyAgent(BaseAgent):
            agent_type = "dummy"

            async def perceive(self, intent):
                return None

            async def decide(self, obs):
                return None

            async def act(self, plan):
                return None

            async def report(self, result):
                return {}

        registry = AgentRegistry()
        spawner = AgentSpawner(registry)
        spawner.register_template("dummy", _DummyAgent)
        cfg = PoolConfig()

        pool = ResourcePool(
            name="test_pool",
            agent_type="dummy",
            spawner=spawner,
            registry=registry,
            config=cfg,
            target_size=1,
            agent_ids=["id_0"],
        )
        await pool.start()
        new_id = await pool.add_agent()
        # Should be deterministic based on next instance_index
        expected = generate_agent_id("dummy", "test_pool", 1)
        assert new_id == expected
        await pool.stop()

    @pytest.mark.asyncio
    async def test_recycle_preserves_agent_id(self):
        from probos.substrate.pool import ResourcePool
        from probos.substrate.spawner import AgentSpawner
        from probos.substrate.registry import AgentRegistry
        from probos.substrate.agent import BaseAgent
        from probos.config import PoolConfig
        from probos.types import AgentState

        class _DummyAgent(BaseAgent):
            agent_type = "dummy"

            async def perceive(self, intent):
                return None

            async def decide(self, obs):
                return None

            async def act(self, plan):
                return None

            async def report(self, result):
                return {}

        registry = AgentRegistry()
        spawner = AgentSpawner(registry)
        spawner.register_template("dummy", _DummyAgent)
        cfg = PoolConfig()

        pool = ResourcePool(
            name="test_pool",
            agent_type="dummy",
            spawner=spawner,
            registry=registry,
            config=cfg,
            target_size=1,
            agent_ids=["stable_id"],
        )
        await pool.start()
        assert pool._agent_ids == ["stable_id"]

        # Degrade the agent to trigger recycle
        agent = registry.get("stable_id")
        agent.state = AgentState.DEGRADED

        await pool.check_health()

        # After recycle, pool should still have the same ID
        assert "stable_id" in pool._agent_ids
        recycled_agent = registry.get("stable_id")
        assert recycled_agent is not None
        assert recycled_agent.id == "stable_id"
        await pool.stop()
