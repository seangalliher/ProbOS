"""Tests for AD-397: Targeted IntentBus dispatch."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage, IntentResult


@pytest.fixture
def intent_bus():
    sm = SignalManager()
    return IntentBus(sm)


class TestTargetedDispatch:
    """Tests for IntentBus.send() — targeted single-agent delivery."""

    @pytest.mark.asyncio
    async def test_send_to_subscribed_agent(self, intent_bus):
        """send() delivers to the target agent and returns result."""
        result = IntentResult(
            intent_id="test",
            agent_id="agent-1",
            success=True,
            result="Hello from agent-1",
            confidence=0.9,
        )
        handler = AsyncMock(return_value=result)
        intent_bus.subscribe("agent-1", handler, intent_names=["test_intent"])

        intent = IntentMessage(
            intent="direct_message",
            params={"text": "hello"},
            target_agent_id="agent-1",
        )
        got = await intent_bus.send(intent)
        assert got is not None
        assert got.result == "Hello from agent-1"
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_to_unknown_agent(self, intent_bus):
        """send() returns None for unsubscribed agent."""
        intent = IntentMessage(
            intent="direct_message",
            target_agent_id="no-such-agent",
        )
        got = await intent_bus.send(intent)
        assert got is None

    @pytest.mark.asyncio
    async def test_send_timeout(self, intent_bus):
        """Agent handler that sleeps too long returns timeout result."""
        async def slow_handler(msg):
            await asyncio.sleep(10)  # way too slow
            return IntentResult(
                intent_id=msg.id,
                agent_id="slow-agent",
                success=True,
                confidence=0.5,
            )

        intent_bus.subscribe("slow-agent", slow_handler)
        intent = IntentMessage(
            intent="direct_message",
            target_agent_id="slow-agent",
            ttl_seconds=0.1,
        )
        got = await intent_bus.send(intent)
        assert got is not None
        assert got.success is False
        assert "not respond" in got.error

    @pytest.mark.asyncio
    async def test_broadcast_with_target_delegates_to_send(self, intent_bus):
        """broadcast() with target_agent_id only delivers to that agent."""
        result = IntentResult(
            intent_id="test",
            agent_id="agent-1",
            success=True,
            result="targeted",
            confidence=0.9,
        )
        handler1 = AsyncMock(return_value=result)
        handler2 = AsyncMock(return_value=None)

        intent_bus.subscribe("agent-1", handler1, intent_names=["direct_message"])
        intent_bus.subscribe("agent-2", handler2, intent_names=["direct_message"])

        intent = IntentMessage(
            intent="direct_message",
            target_agent_id="agent-1",
        )
        results = await intent_bus.broadcast(intent)
        assert len(results) == 1
        assert results[0].result == "targeted"
        handler1.assert_awaited_once()
        handler2.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_requires_target(self, intent_bus):
        """send() raises ValueError if target_agent_id is not set."""
        intent = IntentMessage(intent="test")
        with pytest.raises(ValueError, match="target_agent_id"):
            await intent_bus.send(intent)
