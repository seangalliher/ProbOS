"""Tests for IntentBus."""

import asyncio

import pytest

from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage, IntentResult


@pytest.fixture
def signal_manager():
    return SignalManager()


@pytest.fixture
def intent_bus(signal_manager):
    return IntentBus(signal_manager)


class TestIntentBus:
    @pytest.mark.asyncio
    async def test_broadcast_no_subscribers(self, intent_bus):
        intent = IntentMessage(intent="test", ttl_seconds=5.0)
        results = await intent_bus.broadcast(intent, timeout=1.0)
        assert results == []

    @pytest.mark.asyncio
    async def test_broadcast_single_subscriber(self, intent_bus):
        async def handler(intent: IntentMessage) -> IntentResult | None:
            return IntentResult(
                intent_id=intent.id,
                agent_id="agent-1",
                success=True,
                result="handled",
                confidence=0.9,
            )

        intent_bus.subscribe("agent-1", handler)
        intent = IntentMessage(intent="test")
        results = await intent_bus.broadcast(intent, timeout=2.0)

        assert len(results) == 1
        assert results[0].success
        assert results[0].result == "handled"
        assert results[0].agent_id == "agent-1"

    @pytest.mark.asyncio
    async def test_broadcast_multiple_subscribers(self, intent_bus):
        async def make_handler(agent_id: str):
            async def handler(intent: IntentMessage) -> IntentResult | None:
                return IntentResult(
                    intent_id=intent.id,
                    agent_id=agent_id,
                    success=True,
                    result=f"from-{agent_id}",
                    confidence=0.8,
                )
            return handler

        for i in range(3):
            aid = f"agent-{i}"
            intent_bus.subscribe(aid, await make_handler(aid))

        intent = IntentMessage(intent="test")
        results = await intent_bus.broadcast(intent, timeout=2.0)

        assert len(results) == 3
        agent_ids = {r.agent_id for r in results}
        assert agent_ids == {"agent-0", "agent-1", "agent-2"}

    @pytest.mark.asyncio
    async def test_subscriber_can_decline(self, intent_bus):
        """A subscriber returning None means it declined the intent."""

        async def declines(intent: IntentMessage) -> IntentResult | None:
            return None

        async def accepts(intent: IntentMessage) -> IntentResult | None:
            return IntentResult(
                intent_id=intent.id,
                agent_id="acceptor",
                success=True,
                result="accepted",
            )

        intent_bus.subscribe("decliner", declines)
        intent_bus.subscribe("acceptor", accepts)

        results = await intent_bus.broadcast(IntentMessage(intent="test"), timeout=2.0)
        assert len(results) == 1
        assert results[0].agent_id == "acceptor"

    @pytest.mark.asyncio
    async def test_subscriber_error_recorded(self, intent_bus):
        async def fails(intent: IntentMessage) -> IntentResult | None:
            raise RuntimeError("boom")

        intent_bus.subscribe("failing", fails)
        results = await intent_bus.broadcast(IntentMessage(intent="test"), timeout=2.0)

        assert len(results) == 1
        assert not results[0].success
        assert "boom" in results[0].error

    @pytest.mark.asyncio
    async def test_unsubscribe(self, intent_bus):
        async def handler(intent: IntentMessage) -> IntentResult | None:
            return IntentResult(
                intent_id=intent.id, agent_id="a", success=True
            )

        intent_bus.subscribe("a", handler)
        assert intent_bus.subscriber_count == 1
        intent_bus.unsubscribe("a")
        assert intent_bus.subscriber_count == 0

        results = await intent_bus.broadcast(IntentMessage(intent="test"), timeout=1.0)
        assert results == []
