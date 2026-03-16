"""Tests for _introspect_memory() key alignment with EpisodicMemory.get_stats() (AD-279)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.agents.introspect import IntrospectionAgent


class FakeEpisodicMemory:
    """Stub that returns known stats matching EpisodicMemory.get_stats() format."""

    def __init__(self, stats: dict[str, Any]) -> None:
        self._stats = stats

    async def get_stats(self) -> dict[str, Any]:
        return self._stats


class FakeRuntime:
    """Minimal runtime stub for IntrospectionAgent."""

    def __init__(self, episodic_memory: Any = None) -> None:
        self.episodic_memory = episodic_memory


class TestIntrospectMemoryStats:
    async def test_correct_keys_from_get_stats(self):
        """_introspect_memory() reads the right keys from get_stats()."""
        mem = FakeEpisodicMemory({
            "total": 42,
            "intent_distribution": {"get_weather": 20, "read_file": 15, "shell_command": 7},
            "avg_success_rate": 0.85,
            "most_used_agents": {"weather-0": 20},
        })
        rt = FakeRuntime(episodic_memory=mem)
        agent = IntrospectionAgent(agent_id="intro-0", agent_type="introspect", runtime=rt)

        result = await agent._introspect_memory(rt)

        assert result["success"] is True
        data = result["data"]
        assert data["enabled"] is True
        assert data["total_episodes"] == 42
        assert data["unique_intents"] == 3
        assert data["success_rate"] == 0.85
        assert data["intent_distribution"] == {"get_weather": 20, "read_file": 15, "shell_command": 7}

    async def test_no_episodic_memory(self):
        """_introspect_memory() returns enabled=False when memory is None."""
        rt = FakeRuntime(episodic_memory=None)
        agent = IntrospectionAgent(agent_id="intro-0", agent_type="introspect", runtime=rt)

        result = await agent._introspect_memory(rt)

        assert result["success"] is True
        assert result["data"]["enabled"] is False

    async def test_empty_stats(self):
        """_introspect_memory() handles zero-episode stats gracefully."""
        mem = FakeEpisodicMemory({"total": 0})
        rt = FakeRuntime(episodic_memory=mem)
        agent = IntrospectionAgent(agent_id="intro-0", agent_type="introspect", runtime=rt)

        result = await agent._introspect_memory(rt)

        data = result["data"]
        assert data["total_episodes"] == 0
        assert data["unique_intents"] == 0
        assert data["success_rate"] is None  # not present in stats → None

    async def test_get_stats_error(self):
        """_introspect_memory() handles get_stats() exceptions."""
        mem = FakeEpisodicMemory({})
        mem.get_stats = AsyncMock(side_effect=RuntimeError("db locked"))
        rt = FakeRuntime(episodic_memory=mem)
        agent = IntrospectionAgent(agent_id="intro-0", agent_type="introspect", runtime=rt)

        result = await agent._introspect_memory(rt)

        assert result["success"] is True
        assert "error" in result["data"]
