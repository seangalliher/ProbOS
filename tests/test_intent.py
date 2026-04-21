"""Tests for IntentBus."""

import asyncio
from datetime import datetime, timezone

import pytest

from probos.mesh.intent import IntentBus
from probos.mesh.nats_bus import MockNATSBus
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


# ---------------------------------------------------------------------------
# AD-637b: NATS migration tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def mock_nats_bus():
    bus = MockNATSBus()
    await bus.start()
    return bus


def _make_handler(agent_id: str, counter: dict | None = None):
    """Create a handler that returns success and optionally increments a counter."""
    async def handler(intent: IntentMessage) -> IntentResult | None:
        if counter is not None:
            counter["count"] = counter.get("count", 0) + 1
        return IntentResult(
            intent_id=intent.id,
            agent_id=agent_id,
            success=True,
            result="handled",
            confidence=0.9,
        )
    return handler


class TestIntentBusNATS:
    """AD-637b: NATS transport for send()."""

    @pytest.mark.asyncio
    async def test_send_via_nats_request_reply(self, signal_manager, mock_nats_bus):
        """Test 7: send() uses NATS request/reply when connected."""
        bus = IntentBus(signal_manager)
        bus.set_nats_bus(mock_nats_bus)

        counter: dict = {}
        bus.subscribe("agent-1", _make_handler("agent-1", counter))
        await asyncio.sleep(0)  # let ensure_future complete

        intent = IntentMessage(
            intent="test", target_agent_id="agent-1", ttl_seconds=5.0
        )
        result = await bus.send(intent)

        assert result is not None
        assert result.success
        assert result.result == "handled"
        assert result.agent_id == "agent-1"
        assert counter["count"] == 1

    @pytest.mark.asyncio
    async def test_send_fallback_when_nats_disconnected(self, signal_manager):
        """Test 8: send() falls back to direct-call when NATS not started."""
        mock_bus = MockNATSBus()  # NOT started — connected=False
        bus = IntentBus(signal_manager)
        bus.set_nats_bus(mock_bus)

        counter: dict = {}
        bus.subscribe("agent-1", _make_handler("agent-1", counter))

        intent = IntentMessage(
            intent="test", target_agent_id="agent-1", ttl_seconds=5.0
        )
        result = await bus.send(intent)

        assert result is not None
        assert result.success
        assert counter["count"] == 1

    @pytest.mark.asyncio
    async def test_send_fallback_when_no_nats(self, intent_bus):
        """Test 9: send() uses direct-call when no NATS bus wired."""
        counter: dict = {}
        intent_bus.subscribe("agent-1", _make_handler("agent-1", counter))

        intent = IntentMessage(
            intent="test", target_agent_id="agent-1", ttl_seconds=5.0
        )
        result = await intent_bus.send(intent)

        assert result is not None
        assert result.success
        assert counter["count"] == 1

    @pytest.mark.asyncio
    async def test_send_no_dual_delivery(self, signal_manager, mock_nats_bus):
        """Test 10: send() invokes handler exactly once (no dual-delivery)."""
        bus = IntentBus(signal_manager)
        bus.set_nats_bus(mock_nats_bus)

        counter: dict = {}
        bus.subscribe("agent-1", _make_handler("agent-1", counter))
        await asyncio.sleep(0)

        intent = IntentMessage(
            intent="test", target_agent_id="agent-1", ttl_seconds=5.0
        )
        await bus.send(intent)

        assert counter["count"] == 1  # exactly once, not twice

    @pytest.mark.asyncio
    async def test_nats_subscribe_creates_subscription(self, signal_manager, mock_nats_bus):
        """Test 11: subscribe() creates NATS subscription when NATS is available."""
        bus = IntentBus(signal_manager)
        bus.set_nats_bus(mock_nats_bus)

        bus.subscribe("agent-1", _make_handler("agent-1"))
        await asyncio.sleep(0)  # let ensure_future complete

        assert "agent-1" in bus._nats_subs

    @pytest.mark.asyncio
    async def test_unsubscribe_cleans_nats_subscription(self, signal_manager, mock_nats_bus):
        """Test 12: unsubscribe() removes NATS subscription."""
        bus = IntentBus(signal_manager)
        bus.set_nats_bus(mock_nats_bus)

        bus.subscribe("agent-1", _make_handler("agent-1"))
        await asyncio.sleep(0)

        assert "agent-1" in bus._nats_subs
        bus.unsubscribe("agent-1")
        assert "agent-1" not in bus._nats_subs

    @pytest.mark.asyncio
    async def test_publish_alias_calls_broadcast(self, intent_bus):
        """Test 13: publish() delegates to broadcast()."""
        counter: dict = {}
        intent_bus.subscribe("agent-1", _make_handler("agent-1", counter))

        intent = IntentMessage(intent="test", ttl_seconds=5.0)
        results = await intent_bus.publish(intent)

        assert len(results) == 1
        assert results[0].success
        assert counter["count"] == 1

    @pytest.mark.asyncio
    async def test_publish_targeted_delegates_to_send(self, intent_bus):
        """Test 14: publish() with target_agent_id delegates through broadcast→send."""
        counter: dict = {}
        intent_bus.subscribe("agent-1", _make_handler("agent-1", counter))

        intent = IntentMessage(
            intent="test", target_agent_id="agent-1", ttl_seconds=5.0
        )
        results = await intent_bus.publish(intent)

        assert len(results) == 1
        assert results[0].success
        assert counter["count"] == 1

    @pytest.mark.asyncio
    async def test_intent_serialization_roundtrip(self):
        """Test 15: IntentMessage serialization round-trip."""
        original = IntentMessage(
            intent="analyze",
            params={"key": "value", "count": 42},
            urgency=0.8,
            context="test context",
            ttl_seconds=30.0,
            target_agent_id="agent-x",
        )
        serialized = IntentBus._serialize_intent(original)
        restored = IntentBus._deserialize_intent(serialized)

        assert restored.intent == original.intent
        assert restored.params == original.params
        assert restored.urgency == original.urgency
        assert restored.context == original.context
        assert restored.ttl_seconds == original.ttl_seconds
        assert restored.id == original.id
        assert restored.target_agent_id == original.target_agent_id
        assert restored.created_at.isoformat() == original.created_at.isoformat()

    @pytest.mark.asyncio
    async def test_result_serialization_roundtrip(self):
        """Test 16: IntentResult serialization round-trip."""
        original = IntentResult(
            intent_id="abc123",
            agent_id="agent-1",
            success=True,
            result="analysis complete",
            error=None,
            confidence=0.95,
        )
        serialized = IntentBus._serialize_result(original)
        restored = IntentBus._deserialize_result(serialized)

        assert restored.intent_id == original.intent_id
        assert restored.agent_id == original.agent_id
        assert restored.success == original.success
        assert restored.result == original.result
        assert restored.error == original.error
        assert restored.confidence == original.confidence
        assert restored.timestamp.isoformat() == original.timestamp.isoformat()

    @pytest.mark.asyncio
    async def test_broadcast_still_uses_direct_call(self, signal_manager, mock_nats_bus):
        """Test 17: broadcast() still uses direct-call even with NATS connected."""
        bus = IntentBus(signal_manager)
        bus.set_nats_bus(mock_nats_bus)

        counter: dict = {}
        bus.subscribe("agent-1", _make_handler("agent-1", counter))
        await asyncio.sleep(0)

        intent = IntentMessage(intent="test", ttl_seconds=5.0)
        results = await bus.broadcast(intent, timeout=2.0)

        assert len(results) == 1
        assert results[0].success
        assert counter["count"] == 1

    @pytest.mark.asyncio
    async def test_set_nats_bus_wires_reference(self, signal_manager):
        """Test 18: set_nats_bus() wires the reference."""
        bus = IntentBus(signal_manager)
        assert bus._nats_bus is None

        mock = MockNATSBus()
        bus.set_nats_bus(mock)
        assert bus._nats_bus is mock

    @pytest.mark.asyncio
    async def test_set_federation_handler(self, signal_manager):
        """Test 19: set_federation_handler() sets _federation_fn and it's called on federated broadcast."""
        bus = IntentBus(signal_manager)
        fed_calls: list = []

        async def mock_federation(intent: IntentMessage) -> list[IntentResult]:
            fed_calls.append(intent)
            return [
                IntentResult(
                    intent_id=intent.id,
                    agent_id="remote-agent",
                    success=True,
                    result="from-federation",
                    confidence=0.7,
                )
            ]

        bus.set_federation_handler(mock_federation)
        assert bus._federation_fn is mock_federation

        intent = IntentMessage(intent="test", ttl_seconds=5.0)
        results = await bus.broadcast(intent, timeout=2.0, federated=True)

        assert len(fed_calls) == 1
        assert any(r.agent_id == "remote-agent" for r in results)
