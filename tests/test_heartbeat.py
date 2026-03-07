"""Tests for heartbeat agent and system heartbeat monitor."""

import asyncio

import pytest

from probos.substrate.heartbeat import HeartbeatAgent
from probos.agents.heartbeat_monitor import SystemHeartbeatAgent
from probos.types import AgentState


class TestHeartbeatAgent:
    @pytest.mark.asyncio
    async def test_heartbeat_pulses(self):
        agent = HeartbeatAgent(pool="system", interval=0.2)
        await agent.start()
        assert agent.state == AgentState.ACTIVE

        # Wait for a few pulses
        await asyncio.sleep(0.7)
        assert agent._pulse_count >= 2

        await agent.stop()

    @pytest.mark.asyncio
    async def test_heartbeat_listener(self):
        received: list[dict] = []

        agent = HeartbeatAgent(pool="system", interval=0.2)
        agent.add_listener(lambda m: received.append(m))
        await agent.start()
        await asyncio.sleep(0.5)
        await agent.stop()

        assert len(received) >= 1
        assert "pulse" in received[0]
        assert "agent_id" in received[0]

    @pytest.mark.asyncio
    async def test_heartbeat_async_listener(self):
        received: list[dict] = []

        async def on_pulse(metrics: dict) -> None:
            received.append(metrics)

        agent = HeartbeatAgent(pool="system", interval=0.2)
        agent.add_listener(on_pulse)
        await agent.start()
        await asyncio.sleep(0.5)
        await agent.stop()

        assert len(received) >= 1

    @pytest.mark.asyncio
    async def test_heartbeat_info_includes_pulse_count(self):
        agent = HeartbeatAgent(pool="system", interval=0.2)
        await agent.start()
        await asyncio.sleep(0.5)
        info = agent.info()
        assert "pulse_count" in info
        assert info["pulse_count"] >= 1
        await agent.stop()

    @pytest.mark.asyncio
    async def test_heartbeat_confidence_increases(self):
        agent = HeartbeatAgent(pool="system", interval=0.2)
        original = agent.confidence
        await agent.start()
        await asyncio.sleep(0.5)
        await agent.stop()
        assert agent.confidence >= original


class TestSystemHeartbeatAgent:
    @pytest.mark.asyncio
    async def test_system_heartbeat_metrics(self):
        agent = SystemHeartbeatAgent(pool="system", interval=0.2)
        await agent.start()
        await asyncio.sleep(0.5)
        await agent.stop()

        metrics = agent._last_metrics
        assert "cpu_count" in metrics
        assert "pid" in metrics
        assert "platform" in metrics
        assert metrics["agent_id"] == agent.id

    @pytest.mark.asyncio
    async def test_system_heartbeat_type(self):
        agent = SystemHeartbeatAgent()
        assert agent.agent_type == "system_heartbeat"
        assert any(c.can == "system_metrics" for c in agent.capabilities)
