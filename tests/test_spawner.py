"""Tests for the AgentSpawner."""

from typing import Any

import pytest

from probos.substrate.agent import BaseAgent
from probos.types import AgentState, CapabilityDescriptor


class SpawnableAgent(BaseAgent):
    agent_type = "spawnable"
    default_capabilities = [CapabilityDescriptor(can="spawn_test")]

    async def perceive(self, intent: dict[str, Any]) -> Any:
        return None

    async def decide(self, observation: Any) -> Any:
        return None

    async def act(self, plan: Any) -> Any:
        return None

    async def report(self, result: Any) -> dict[str, Any]:
        return {}


class TestSpawner:
    @pytest.mark.asyncio
    async def test_register_and_spawn(self, spawner, registry):
        spawner.register_template("spawnable", SpawnableAgent)
        agent = await spawner.spawn("spawnable", pool="test")
        assert agent.state == AgentState.ACTIVE
        assert agent.pool == "test"
        assert registry.get(agent.id) is agent
        await agent.stop()

    @pytest.mark.asyncio
    async def test_spawn_unknown_raises(self, spawner):
        with pytest.raises(ValueError, match="Unknown agent template"):
            await spawner.spawn("nonexistent")

    @pytest.mark.asyncio
    async def test_available_templates(self, spawner):
        spawner.register_template("a", SpawnableAgent)
        spawner.register_template("b", SpawnableAgent)
        assert set(spawner.available_templates) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_recycle_with_respawn(self, spawner, registry):
        spawner.register_template("spawnable", SpawnableAgent)
        original = await spawner.spawn("spawnable", pool="mypool")
        original_id = original.id

        replacement = await spawner.recycle(original_id, respawn=True)
        assert replacement is not None
        assert replacement.id == original_id  # Phase 14c: individual persists
        assert replacement.pool == "mypool"
        assert replacement.state == AgentState.ACTIVE
        # Replacement re-registered under same ID
        assert registry.get(original_id) is replacement
        await replacement.stop()

    @pytest.mark.asyncio
    async def test_recycle_without_respawn(self, spawner, registry):
        spawner.register_template("spawnable", SpawnableAgent)
        agent = await spawner.spawn("spawnable")
        aid = agent.id

        result = await spawner.recycle(aid, respawn=False)
        assert result is None
        assert registry.get(aid) is None

    @pytest.mark.asyncio
    async def test_recycle_unknown_agent(self, spawner):
        result = await spawner.recycle("nonexistent")
        assert result is None
