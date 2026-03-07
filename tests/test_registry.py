"""Tests for the AgentRegistry."""

import pytest

from probos.substrate.agent import BaseAgent
from probos.types import AgentState, CapabilityDescriptor
from typing import Any


class StubAgent(BaseAgent):
    agent_type = "stub"
    default_capabilities = [
        CapabilityDescriptor(can="stub_action"),
    ]

    async def perceive(self, intent: dict[str, Any]) -> Any:
        return None

    async def decide(self, observation: Any) -> Any:
        return None

    async def act(self, plan: Any) -> Any:
        return None

    async def report(self, result: Any) -> dict[str, Any]:
        return {}


class TestRegistry:
    @pytest.mark.asyncio
    async def test_register_and_get(self, registry):
        a = StubAgent(pool="test")
        await registry.register(a)
        assert registry.get(a.id) is a
        assert registry.count == 1

    @pytest.mark.asyncio
    async def test_unregister(self, registry):
        a = StubAgent(pool="test")
        await registry.register(a)
        removed = await registry.unregister(a.id)
        assert removed is a
        assert registry.get(a.id) is None
        assert registry.count == 0

    @pytest.mark.asyncio
    async def test_unregister_missing(self, registry):
        result = await registry.unregister("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_pool(self, registry):
        a1 = StubAgent(pool="alpha")
        a2 = StubAgent(pool="alpha")
        a3 = StubAgent(pool="beta")
        for a in [a1, a2, a3]:
            await registry.register(a)

        alpha = registry.get_by_pool("alpha")
        assert len(alpha) == 2
        assert all(a.pool == "alpha" for a in alpha)

    @pytest.mark.asyncio
    async def test_get_by_capability(self, registry):
        a = StubAgent(pool="test")
        await registry.register(a)
        found = registry.get_by_capability("stub_action")
        assert len(found) == 1
        assert found[0].id == a.id

        empty = registry.get_by_capability("nonexistent")
        assert len(empty) == 0

    @pytest.mark.asyncio
    async def test_summary(self, registry):
        for pool in ["fs", "fs", "net"]:
            await registry.register(StubAgent(pool=pool))
        summary = registry.summary()
        assert summary == {"fs": 2, "net": 1}

    @pytest.mark.asyncio
    async def test_all(self, registry):
        for _ in range(5):
            await registry.register(StubAgent())
        assert len(registry.all()) == 5
