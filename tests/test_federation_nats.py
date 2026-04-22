"""AD-637e: Federation Transport NATS Migration tests."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.federation.nats_transport import NATSFederationTransport
from probos.mesh.nats_bus import MockNATSBus
from probos.types import FederationMessage


def _make_message(
    type: str = "intent_request",
    source_node: str = "node-1",
    payload: dict | None = None,
) -> FederationMessage:
    return FederationMessage(
        type=type,
        source_node=source_node,
        payload=payload or {},
        timestamp=time.time(),
    )


@pytest.fixture
async def mock_nats_bus():
    bus = MockNATSBus()
    await bus.start()
    return bus


class TestNATSFederationTransport:
    """AD-637e: NATS federation transport unit tests."""

    @pytest.mark.asyncio
    async def test_nats_transport_start_subscribes(self, mock_nats_bus):
        """Test 1: start() subscribes to gossip and intent subjects."""
        transport = NATSFederationTransport(
            node_id="node-1",
            nats_bus=mock_nats_bus,
            peer_node_ids=["node-2", "node-3"],
        )
        await transport.start()

        assert "federation.gossip" in mock_nats_bus._subs
        assert "federation.intent.node-1" in mock_nats_bus._subs
        assert transport._running is True

    @pytest.mark.asyncio
    async def test_nats_transport_start_checks_subscription_results(self):
        """Test 2: start() with disconnected bus — subscribe_raw returns None."""
        bus = MockNATSBus()  # NOT started — connected=False
        # Patch subscribe_raw to return None (simulating real NATSBus behavior)
        original_subscribe = bus.subscribe_raw

        async def _subscribe_returning_none(subject, callback, queue=""):
            return None

        bus.subscribe_raw = _subscribe_returning_none

        transport = NATSFederationTransport(
            node_id="node-1",
            nats_bus=bus,
            peer_node_ids=["node-2"],
        )
        await transport.start()

        # subscribe_raw returned None — no subs stored
        assert len(transport._subscriptions) == 0
        # Transport still marks running (degraded but alive)
        assert transport._running is True

    @pytest.mark.asyncio
    async def test_nats_transport_stop_clears_state(self, mock_nats_bus):
        """Test 3: stop() clears running state."""
        transport = NATSFederationTransport(
            node_id="node-1",
            nats_bus=mock_nats_bus,
            peer_node_ids=["node-2"],
        )
        await transport.start()
        assert transport._running is True

        await transport.stop()
        assert transport._running is False

    @pytest.mark.asyncio
    async def test_send_to_peer_publishes_to_intent_subject(self, mock_nats_bus):
        """Test 4: send_to_peer publishes to federation.intent.{peer}."""
        transport = NATSFederationTransport(
            node_id="node-1",
            nats_bus=mock_nats_bus,
            peer_node_ids=["node-2"],
        )
        await transport.start()

        msg = _make_message(source_node="node-1")
        await transport.send_to_peer("node-2", msg)

        # Find the publish (filter out subscription callbacks)
        publishes = [
            (subj, data) for subj, data in mock_nats_bus.published
            if subj == "federation.intent.node-2"
        ]
        assert len(publishes) == 1
        assert publishes[0][1]["type"] == "intent_request"
        assert publishes[0][1]["source_node"] == "node-1"

    @pytest.mark.asyncio
    async def test_send_to_all_peers_publishes_to_gossip(self, mock_nats_bus):
        """Test 5: send_to_all_peers publishes to federation.gossip."""
        transport = NATSFederationTransport(
            node_id="node-1",
            nats_bus=mock_nats_bus,
            peer_node_ids=["node-2", "node-3"],
        )
        await transport.start()

        msg = _make_message(type="gossip_self_model", source_node="node-1")
        result = await transport.send_to_all_peers(msg)

        publishes = [
            (subj, data) for subj, data in mock_nats_bus.published
            if subj == "federation.gossip"
        ]
        assert len(publishes) == 1
        assert publishes[0][1]["type"] == "gossip_self_model"
        assert set(result) == {"node-2", "node-3"}

    @pytest.mark.asyncio
    async def test_inbound_intent_dispatches_to_handler(self, mock_nats_bus):
        """Test 6: Inbound intent message dispatches to _inbound_handler."""
        transport = NATSFederationTransport(
            node_id="node-1",
            nats_bus=mock_nats_bus,
            peer_node_ids=["node-2"],
        )
        received: list[FederationMessage] = []

        async def handler(msg: FederationMessage):
            received.append(msg)

        transport._inbound_handler = handler
        await transport.start()

        # Simulate node-2 sending an intent to node-1
        await mock_nats_bus.publish_raw("federation.intent.node-1", {
            "type": "intent_request",
            "source_node": "node-2",
            "message_id": "test-123",
            "payload": {"intent": "query"},
            "timestamp": time.time(),
        })

        assert len(received) == 1
        assert received[0].type == "intent_request"
        assert received[0].source_node == "node-2"
        assert received[0].payload == {"intent": "query"}

    @pytest.mark.asyncio
    async def test_inbound_response_routes_to_response_queue(self, mock_nats_bus):
        """Test 7: intent_response routes to response queue, not handler."""
        transport = NATSFederationTransport(
            node_id="node-1",
            nats_bus=mock_nats_bus,
            peer_node_ids=["node-2"],
        )
        handler_calls: list = []

        async def handler(msg):
            handler_calls.append(msg)

        transport._inbound_handler = handler
        await transport.start()

        # Simulate an intent_response from node-2
        await mock_nats_bus.publish_raw("federation.intent.node-1", {
            "type": "intent_response",
            "source_node": "node-2",
            "message_id": "resp-456",
            "payload": {"result": "ok"},
            "timestamp": time.time(),
        })

        # Handler should NOT be called for responses
        assert len(handler_calls) == 0

        # Response should be in the queue
        result = await transport.receive_with_timeout("node-2", timeout_ms=100)
        assert result is not None
        assert result.type == "intent_response"
        assert result.payload == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_self_gossip_filtered(self, mock_nats_bus):
        """Test 8: Gossip from self is filtered out."""
        transport = NATSFederationTransport(
            node_id="node-1",
            nats_bus=mock_nats_bus,
            peer_node_ids=["node-2"],
        )
        handler_calls: list = []

        async def handler(msg):
            handler_calls.append(msg)

        transport._inbound_handler = handler
        await transport.start()

        # Publish gossip with source_node == self
        await mock_nats_bus.publish_raw("federation.gossip", {
            "type": "gossip_self_model",
            "source_node": "node-1",  # Self!
            "message_id": "gossip-1",
            "payload": {},
            "timestamp": time.time(),
        })

        assert len(handler_calls) == 0  # Filtered

    @pytest.mark.asyncio
    async def test_connected_peers_empty_when_nats_disconnected(self):
        """Test 9: connected_peers returns [] when NATS disconnected."""
        bus = MockNATSBus()  # NOT started
        transport = NATSFederationTransport(
            node_id="node-1",
            nats_bus=bus,
            peer_node_ids=["node-2", "node-3"],
        )

        assert transport.connected_peers == []

    @pytest.mark.asyncio
    async def test_cross_ship_gossip_visible_with_different_prefixes(self):
        """Test 10: Critical namespace test — gossip crosses ship prefix boundaries.

        Two transports with different subject_prefix values share a single
        MockNATSBus (simulating shared NATS cluster). Gossip from node-1
        must be visible to node-2 despite different prefixes.
        """
        # Shared bus (simulates shared NATS cluster)
        shared_bus = MockNATSBus()
        await shared_bus.start()
        await shared_bus.set_subject_prefix("probos.ship-1")

        # Two transports on the same bus with different logical ships
        transport_1 = NATSFederationTransport(
            node_id="node-1",
            nats_bus=shared_bus,
            peer_node_ids=["node-2"],
        )
        transport_2 = NATSFederationTransport(
            node_id="node-2",
            nats_bus=shared_bus,
            peer_node_ids=["node-1"],
        )

        received_by_2: list[FederationMessage] = []

        async def handler_2(msg: FederationMessage):
            received_by_2.append(msg)

        transport_2._inbound_handler = handler_2

        await transport_1.start()
        await transport_2.start()

        # Change prefix to simulate ship-2 (transport_2's "ship")
        # This proves federation subjects are prefix-independent
        await shared_bus.set_subject_prefix("probos.ship-2")

        # Node-1 sends gossip — should reach node-2 regardless of prefix
        msg = _make_message(type="gossip_self_model", source_node="node-1")
        await transport_1.send_to_all_peers(msg)

        assert len(received_by_2) == 1
        assert received_by_2[0].source_node == "node-1"

    @pytest.mark.asyncio
    async def test_falls_back_to_zmq_when_nats_disconnected(self):
        """Test 11: fleet_organization falls back to ZeroMQ when NATS unavailable."""
        from probos.startup.fleet_organization import organize_fleet

        # Create a minimal config mock
        config = MagicMock()
        config.federation.enabled = True
        config.federation.node_id = "node-1"
        config.federation.bind_address = "tcp://127.0.0.1:5555"
        config.federation.peers = []
        config.federation.validate_remote_results = False
        config.federation.forward_timeout_ms = 5000
        config.federation.gossip_interval_seconds = 30
        config.scaling.enabled = False
        config.utility_agents.enabled = False
        config.medical.enabled = False
        config.self_mod.enabled = False

        pools = {}
        pool_groups = MagicMock()
        pool_groups.excluded_pools.return_value = set()

        # nats_bus=None → should skip NATS path entirely and attempt ZeroMQ
        # Mock the ZeroMQ import to raise ImportError
        import probos.startup.fleet_organization as fleet_mod
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        zmq_import_attempted = {"value": False}

        def mock_import(name, *args, **kwargs):
            if name == "probos.federation.transport":
                zmq_import_attempted["value"] = True
                raise ImportError("no pyzmq")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = await organize_fleet(
                config=config,
                pools=pools,
                pool_groups=pool_groups,
                escalation_manager=MagicMock(),
                intent_bus=MagicMock(),
                trust_network=MagicMock(),
                llm_client=MagicMock(),
                build_pool_intent_map_fn=lambda: {},
                find_consensus_pools_fn=lambda: set(),
                build_self_model_fn=lambda: {},
                validate_remote_result_fn=None,
                nats_bus=None,  # No NATS — should skip NATS path
            )

        # ZeroMQ import was attempted as fallback
        assert zmq_import_attempted["value"] is True
        # No transport available → bridge not created
        assert result.federation_bridge is None
        assert result.federation_transport is None
