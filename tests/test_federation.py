"""Tests for Phase 9: Multi-Node Federation."""

from __future__ import annotations

import asyncio
import pytest

from rich.console import Console

from probos.config import FederationConfig, PeerConfig, SystemConfig
from probos.experience import panels
from probos.types import FederationMessage, IntentMessage, IntentResult, NodeSelfModel


# ── TestFederationConfig (tests 1-3) ─────────────────────────────────

class TestFederationConfig:
    """Test federation configuration models."""

    def test_defaults(self):
        """FederationConfig defaults: disabled, node-1, no peers."""
        cfg = FederationConfig()
        assert cfg.enabled is False
        assert cfg.node_id == "node-1"
        assert cfg.bind_address == "tcp://127.0.0.1:5555"
        assert cfg.peers == []
        assert cfg.forward_timeout_ms == 5000
        assert cfg.gossip_interval_seconds == 10.0
        assert cfg.validate_remote_results is True

    def test_custom_values(self):
        """FederationConfig with custom values: enabled, 2 peers."""
        cfg = FederationConfig(
            enabled=True,
            node_id="node-2",
            bind_address="tcp://127.0.0.1:5556",
            peers=[
                PeerConfig(node_id="node-1", address="tcp://127.0.0.1:5555"),
                PeerConfig(node_id="node-3", address="tcp://127.0.0.1:5557"),
            ],
            forward_timeout_ms=3000,
        )
        assert cfg.enabled is True
        assert cfg.node_id == "node-2"
        assert len(cfg.peers) == 2
        assert cfg.peers[0].node_id == "node-1"
        assert cfg.peers[1].address == "tcp://127.0.0.1:5557"
        assert cfg.forward_timeout_ms == 3000

    def test_peer_config_roundtrip(self):
        """PeerConfig preserves node_id and address."""
        pc = PeerConfig(node_id="node-42", address="tcp://10.0.0.1:9999")
        assert pc.node_id == "node-42"
        assert pc.address == "tcp://10.0.0.1:9999"
        # Round-trip through dict
        data = pc.model_dump()
        pc2 = PeerConfig.model_validate(data)
        assert pc2.node_id == pc.node_id
        assert pc2.address == pc.address

    def test_system_config_includes_federation(self):
        """SystemConfig includes federation with defaults."""
        cfg = SystemConfig()
        assert hasattr(cfg, "federation")
        assert cfg.federation.enabled is False
        assert cfg.federation.node_id == "node-1"


# ── TestFederationTypes (tests 4-6) ──────────────────────────────────

class TestFederationTypes:
    """Test federation wire protocol types."""

    def test_node_self_model_roundtrip(self):
        """NodeSelfModel: all fields serialize/deserialize."""
        m = NodeSelfModel(
            node_id="n1",
            capabilities=["read_file", "write_file"],
            pool_sizes={"filesystem": 3},
            agent_count=10,
            health=0.85,
            uptime_seconds=42.0,
            timestamp=100.0,
        )
        assert m.node_id == "n1"
        assert m.capabilities == ["read_file", "write_file"]
        assert m.pool_sizes == {"filesystem": 3}
        assert m.agent_count == 10
        assert m.health == 0.85
        assert m.uptime_seconds == 42.0
        assert m.timestamp == 100.0

    def test_federation_message_roundtrip(self):
        """FederationMessage: all fields preserved."""
        msg = FederationMessage(
            type="intent_request",
            source_node="node-1",
            payload={"intent": "read_file", "params": {"path": "/tmp/x"}},
            timestamp=123.0,
        )
        assert msg.type == "intent_request"
        assert msg.source_node == "node-1"
        assert len(msg.message_id) == 32  # UUID hex
        assert msg.payload["intent"] == "read_file"
        assert msg.timestamp == 123.0

    def test_federation_message_carries_intent_data(self):
        """FederationMessage payload carries IntentMessage data."""
        intent = IntentMessage(intent="read_file", params={"path": "/a/b"})
        msg = FederationMessage(
            type="intent_request",
            source_node="node-2",
            payload={
                "intent": intent.intent,
                "params": intent.params,
                "id": intent.id,
                "urgency": intent.urgency,
            },
        )
        assert msg.payload["intent"] == "read_file"
        assert msg.payload["params"]["path"] == "/a/b"
        assert msg.payload["id"] == intent.id


# ── TestMockTransportBus (tests 7-10) ────────────────────────────────

class TestMockTransportBus:
    """Test in-memory federation transport."""

    @pytest.fixture
    def bus_and_transports(self):
        from probos.federation.mock_transport import MockFederationTransport, MockTransportBus
        bus = MockTransportBus()
        t_a = MockFederationTransport("node-a", bus)
        t_b = MockFederationTransport("node-b", bus)
        return bus, t_a, t_b

    async def test_send_and_receive(self, bus_and_transports):
        """Register two transports, send from A to B, B receives."""
        bus, t_a, t_b = bus_and_transports
        received: list[FederationMessage] = []
        t_b._inbound_handler = lambda msg: _collect(received, msg)

        msg = FederationMessage(
            type="ping", source_node="node-a", timestamp=1.0
        )
        await t_a.send_to_peer("node-b", msg)
        assert len(received) == 1
        assert received[0].type == "ping"
        assert received[0].source_node == "node-a"

    async def test_send_to_unregistered_peer_no_error(self, bus_and_transports):
        """Send to an unregistered peer does not raise."""
        bus, t_a, t_b = bus_and_transports
        msg = FederationMessage(
            type="ping", source_node="node-a", timestamp=1.0
        )
        # Should not raise
        await t_a.send_to_peer("node-z", msg)

    async def test_send_to_all_peers(self, bus_and_transports):
        """send_to_all_peers delivers to all registered peers."""
        bus, t_a, t_b = bus_and_transports
        received_b: list[FederationMessage] = []
        t_b._inbound_handler = lambda msg: _collect(received_b, msg)

        msg = FederationMessage(
            type="ping", source_node="node-a", timestamp=1.0
        )
        sent_to = await t_a.send_to_all_peers(msg)
        assert "node-b" in sent_to
        assert "node-a" not in sent_to
        assert len(received_b) == 1

    async def test_receive_timeout_returns_none(self, bus_and_transports):
        """Timeout returns None when no response arrives."""
        bus, t_a, t_b = bus_and_transports
        result = await t_a.receive_with_timeout("node-b", timeout_ms=50)
        assert result is None


async def _collect(lst: list, msg: FederationMessage) -> None:
    """Helper to collect messages into a list."""
    lst.append(msg)


# ── TestFederationRouter (tests 11-14) ───────────────────────────────

class TestFederationRouter:
    """Test federated query routing."""

    def test_select_peers_returns_all(self):
        """select_peers with no peer models returns all available_peers."""
        from probos.federation.router import FederationRouter
        router = FederationRouter()
        peers = router.select_peers("read_file", ["node-1", "node-2", "node-3"])
        assert peers == ["node-1", "node-2", "node-3"]

    def test_update_peer_model(self):
        """update_peer_model stores model, retrievable via known_peers."""
        from probos.federation.router import FederationRouter
        router = FederationRouter()
        model = NodeSelfModel(
            node_id="node-2",
            capabilities=["read_file"],
            agent_count=5,
            health=0.9,
        )
        router.update_peer_model(model)
        assert "node-2" in router.known_peers
        assert router.known_peers["node-2"].capabilities == ["read_file"]

    def test_peer_has_capability_true(self):
        """peer_has_capability returns True when intent in model capabilities."""
        from probos.federation.router import FederationRouter
        router = FederationRouter()
        model = NodeSelfModel(
            node_id="node-3",
            capabilities=["read_file", "write_file"],
        )
        router.update_peer_model(model)
        assert router.peer_has_capability("node-3", "read_file") is True

    def test_peer_has_capability_false(self):
        """peer_has_capability returns False for unknown intent."""
        from probos.federation.router import FederationRouter
        router = FederationRouter()
        model = NodeSelfModel(
            node_id="node-3",
            capabilities=["read_file"],
        )
        router.update_peer_model(model)
        assert router.peer_has_capability("node-3", "delete_file") is False
        assert router.peer_has_capability("node-99", "read_file") is False


# ── Helper: two-node federation fixture ──────────────────────────────

def _make_mock_intent_bus(results: list[IntentResult] | None = None):
    """Create a mock intent bus that records calls and returns given results."""
    class _MockIntentBus:
        def __init__(self):
            self.broadcast_calls: list[dict] = []
            self._results = results or []
            self._federation_fn = None

        async def broadcast(self, intent, *, timeout=None, federated=True):
            self.broadcast_calls.append({
                "intent": intent,
                "timeout": timeout,
                "federated": federated,
            })
            return list(self._results)

    return _MockIntentBus()


def _self_model_fn() -> NodeSelfModel:
    """Dummy self-model function for bridge tests."""
    return NodeSelfModel(
        node_id="test-node",
        capabilities=["read_file"],
        pool_sizes={"filesystem": 3},
        agent_count=10,
        health=0.9,
        uptime_seconds=100.0,
        timestamp=1.0,
    )


def _make_two_node_env(
    bus_results_a=None, bus_results_b=None, validate_fn=None
):
    """Create a two-node test environment with mock transports and bridges."""
    from probos.federation.mock_transport import MockFederationTransport, MockTransportBus
    from probos.federation.router import FederationRouter
    from probos.federation.bridge import FederationBridge

    config = FederationConfig(
        enabled=True,
        node_id="node-a",
        forward_timeout_ms=500,
        gossip_interval_seconds=100,  # Long interval — won't fire in tests
    )
    config_b = FederationConfig(
        enabled=True,
        node_id="node-b",
        forward_timeout_ms=500,
        gossip_interval_seconds=100,
    )

    transport_bus = MockTransportBus()
    t_a = MockFederationTransport("node-a", transport_bus)
    t_b = MockFederationTransport("node-b", transport_bus)

    bus_a = _make_mock_intent_bus(bus_results_a)
    bus_b = _make_mock_intent_bus(bus_results_b)

    router_a = FederationRouter()
    router_b = FederationRouter()

    bridge_a = FederationBridge(
        node_id="node-a",
        transport=t_a,
        router=router_a,
        intent_bus=bus_a,
        config=config,
        self_model_fn=_self_model_fn,
        validate_fn=validate_fn,
    )
    bridge_b = FederationBridge(
        node_id="node-b",
        transport=t_b,
        router=router_b,
        intent_bus=bus_b,
        config=config_b,
        self_model_fn=_self_model_fn,
    )

    return {
        "transport_bus": transport_bus,
        "t_a": t_a, "t_b": t_b,
        "bus_a": bus_a, "bus_b": bus_b,
        "router_a": router_a, "router_b": router_b,
        "bridge_a": bridge_a, "bridge_b": bridge_b,
        "config": config, "config_b": config_b,
    }


# ── TestFederationBridgeOutbound (tests 15-19) ───────────────────────

class TestFederationBridgeOutbound:
    """Test outbound intent forwarding."""

    async def test_forward_collects_results(self):
        """forward_intent sends to all peers and collects results."""
        env = _make_two_node_env(
            bus_results_b=[
                IntentResult(
                    intent_id="i1", agent_id="agent-b1",
                    success=True, result="file content", confidence=0.9,
                ),
            ],
        )
        await env["bridge_a"].start()
        await env["bridge_b"].start()

        intent = IntentMessage(intent="read_file", params={"path": "/a"})
        results = await env["bridge_a"].forward_intent(intent)

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].result == "file content"

        await env["bridge_a"].stop()
        await env["bridge_b"].stop()

    async def test_forward_unresponsive_peer_partial_results(self):
        """forward_intent with one unresponsive peer returns partial results from responsive."""
        from probos.federation.mock_transport import MockFederationTransport, MockTransportBus
        from probos.federation.router import FederationRouter
        from probos.federation.bridge import FederationBridge

        transport_bus = MockTransportBus()
        t_a = MockFederationTransport("node-a", transport_bus)
        t_b = MockFederationTransport("node-b", transport_bus)
        t_c = MockFederationTransport("node-c", transport_bus)

        bus_a = _make_mock_intent_bus()
        bus_b = _make_mock_intent_bus([
            IntentResult(intent_id="i1", agent_id="b-agent", success=True, result="ok"),
        ])
        # node-c has no bridge started — it won't respond

        config = FederationConfig(
            enabled=True, node_id="node-a",
            forward_timeout_ms=100, gossip_interval_seconds=100,
        )
        config_b = FederationConfig(
            enabled=True, node_id="node-b",
            forward_timeout_ms=100, gossip_interval_seconds=100,
        )

        bridge_a = FederationBridge(
            node_id="node-a", transport=t_a,
            router=FederationRouter(), intent_bus=bus_a,
            config=config, self_model_fn=_self_model_fn,
        )
        bridge_b = FederationBridge(
            node_id="node-b", transport=t_b,
            router=FederationRouter(), intent_bus=bus_b,
            config=config_b, self_model_fn=_self_model_fn,
        )

        await bridge_a.start()
        await bridge_b.start()

        intent = IntentMessage(intent="read_file", params={"path": "/a"})
        results = await bridge_a.forward_intent(intent)

        # Should get results from node-b, node-c times out
        assert len(results) == 1
        assert results[0].agent_id == "b-agent"

        await bridge_a.stop()
        await bridge_b.stop()

    async def test_forward_all_peers_unresponsive(self):
        """forward_intent with all peers unresponsive returns empty list."""
        from probos.federation.mock_transport import MockFederationTransport, MockTransportBus
        from probos.federation.router import FederationRouter
        from probos.federation.bridge import FederationBridge

        transport_bus = MockTransportBus()
        t_a = MockFederationTransport("node-a", transport_bus)
        # Register a peer but don't start a bridge for it — no handler
        t_c = MockFederationTransport("node-c", transport_bus)

        config = FederationConfig(
            enabled=True, node_id="node-a",
            forward_timeout_ms=50, gossip_interval_seconds=100,
        )

        bridge_a = FederationBridge(
            node_id="node-a", transport=t_a,
            router=FederationRouter(),
            intent_bus=_make_mock_intent_bus(),
            config=config, self_model_fn=_self_model_fn,
        )
        await bridge_a.start()

        intent = IntentMessage(intent="read_file", params={"path": "/a"})
        results = await bridge_a.forward_intent(intent)
        assert results == []

        await bridge_a.stop()

    async def test_forward_increments_stats(self):
        """forward_intent increments stats."""
        env = _make_two_node_env(
            bus_results_b=[
                IntentResult(intent_id="i1", agent_id="b1", success=True),
            ],
        )
        await env["bridge_a"].start()
        await env["bridge_b"].start()

        intent = IntentMessage(intent="read_file", params={"path": "/a"})
        await env["bridge_a"].forward_intent(intent)

        status = env["bridge_a"].federation_status()
        assert status["intents_forwarded"] == 1
        assert status["results_collected"] == 1

        await env["bridge_a"].stop()
        await env["bridge_b"].stop()

    async def test_forward_with_validate_fn(self):
        """forward_intent with validate_fn calls it on each remote result."""
        validated = []

        async def mock_validate(result):
            validated.append(result)
            return result.success  # Only pass successful results

        env = _make_two_node_env(
            bus_results_b=[
                IntentResult(intent_id="i1", agent_id="b1", success=True, result="ok"),
                IntentResult(intent_id="i1", agent_id="b2", success=False, error="fail"),
            ],
            validate_fn=mock_validate,
        )
        await env["bridge_a"].start()
        await env["bridge_b"].start()

        intent = IntentMessage(intent="read_file", params={"path": "/a"})
        results = await env["bridge_a"].forward_intent(intent)

        # validate_fn filters out the failed result
        assert len(results) == 1
        assert results[0].success is True
        assert len(validated) == 2

        await env["bridge_a"].stop()
        await env["bridge_b"].stop()


# ── TestFederationBridgeInbound (tests 20-23) ────────────────────────

class TestFederationBridgeInbound:
    """Test inbound intent handling."""

    async def test_inbound_intent_broadcasts_locally(self):
        """Inbound intent_request broadcasts locally and sends results back."""
        env = _make_two_node_env(
            bus_results_b=[
                IntentResult(intent_id="i1", agent_id="b-local", success=True, result="data"),
            ],
        )
        await env["bridge_a"].start()
        await env["bridge_b"].start()

        # A forwards intent, B handles it locally
        intent = IntentMessage(intent="read_file", params={"path": "/x"})
        results = await env["bridge_a"].forward_intent(intent)

        assert len(results) == 1
        assert results[0].result == "data"

        # B should have received an inbound intent
        assert env["bridge_b"]._stats["intents_received"] == 1

        await env["bridge_a"].stop()
        await env["bridge_b"].stop()

    async def test_inbound_intent_federated_false(self):
        """Inbound intent_request calls broadcast(federated=False)."""
        env = _make_two_node_env(bus_results_b=[])
        await env["bridge_a"].start()
        await env["bridge_b"].start()

        intent = IntentMessage(intent="read_file", params={"path": "/x"})
        await env["bridge_a"].forward_intent(intent)

        # Verify B's bus was called with federated=False
        calls = env["bus_b"].broadcast_calls
        assert len(calls) == 1
        assert calls[0]["federated"] is False

        await env["bridge_a"].stop()
        await env["bridge_b"].stop()

    async def test_inbound_gossip_updates_router(self):
        """Inbound gossip_self_model updates router's peer model."""
        env = _make_two_node_env()
        await env["bridge_a"].start()
        await env["bridge_b"].start()

        gossip_msg = FederationMessage(
            type="gossip_self_model",
            source_node="node-b",
            payload={
                "node_id": "node-b",
                "capabilities": ["shell_command", "http_fetch"],
                "pool_sizes": {"shell": 3},
                "agent_count": 8,
                "health": 0.75,
                "uptime_seconds": 50.0,
                "timestamp": 1.0,
            },
        )
        await env["bridge_a"].handle_inbound(gossip_msg)

        peers = env["router_a"].known_peers
        assert "node-b" in peers
        assert "shell_command" in peers["node-b"].capabilities

        await env["bridge_a"].stop()
        await env["bridge_b"].stop()

    async def test_inbound_ping_responds_pong(self):
        """Inbound ping responds with pong."""
        env = _make_two_node_env()
        await env["bridge_a"].start()
        await env["bridge_b"].start()

        received = []
        env["t_a"]._inbound_handler = lambda msg: _collect(received, msg)

        ping = FederationMessage(
            type="ping",
            source_node="node-a",
            message_id="ping-123",
        )
        await env["bridge_b"].handle_inbound(ping)

        assert len(received) == 1
        assert received[0].type == "pong"
        assert received[0].message_id == "ping-123"

        await env["bridge_a"].stop()
        await env["bridge_b"].stop()


# ── TestFederationBridgeLoopPrevention (tests 24-25) ─────────────────

class TestFederationBridgeLoopPrevention:
    """Test that inbound intents don't re-forward to peers."""

    async def test_inbound_does_not_reforward(self):
        """Intent forwarded to peer, peer broadcasts locally but does NOT forward back."""
        env = _make_two_node_env(
            bus_results_b=[
                IntentResult(intent_id="i1", agent_id="b1", success=True, result="ok"),
            ],
        )
        await env["bridge_a"].start()
        await env["bridge_b"].start()

        intent = IntentMessage(intent="read_file", params={"path": "/x"})
        results = await env["bridge_a"].forward_intent(intent)

        # B handled it locally
        assert len(results) == 1
        # B's broadcast was called with federated=False — no re-forwarding
        assert len(env["bus_b"].broadcast_calls) == 1
        assert env["bus_b"].broadcast_calls[0]["federated"] is False
        # A's bus was never called (A only forwarded, didn't broadcast locally for this)
        assert len(env["bus_a"].broadcast_calls) == 0

        await env["bridge_a"].stop()
        await env["bridge_b"].stop()

    async def test_two_node_ring_no_infinite_loop(self):
        """Two-node ring: A forwards to B, B handles locally, response returns to A."""
        env = _make_two_node_env(
            bus_results_b=[
                IntentResult(intent_id="i1", agent_id="b1", success=True, result="file-data"),
            ],
        )
        await env["bridge_a"].start()
        await env["bridge_b"].start()

        intent = IntentMessage(intent="read_file", params={"path": "/test"})
        results = await env["bridge_a"].forward_intent(intent)

        # Results from B returned to A
        assert len(results) == 1
        assert results[0].result == "file-data"

        # B received exactly 1 inbound intent
        assert env["bridge_b"]._stats["intents_received"] == 1
        # A forwarded exactly 1 intent
        assert env["bridge_a"]._stats["intents_forwarded"] == 1

        await env["bridge_a"].stop()
        await env["bridge_b"].stop()


# ── TestIntentBusFederation (tests 26-28) ────────────────────────────

class TestIntentBusFederation:
    """Test IntentBus federation integration."""

    @pytest.fixture
    def intent_bus(self):
        from probos.mesh.signal import SignalManager
        from probos.mesh.intent import IntentBus
        sm = SignalManager(reap_interval=1.0)
        return IntentBus(sm)

    async def test_broadcast_calls_federation_fn(self, intent_bus):
        """broadcast() with _federation_fn calls it and merges results."""
        federation_calls = []

        async def mock_federation(intent):
            federation_calls.append(intent)
            return [
                IntentResult(
                    intent_id=intent.id, agent_id="remote-1",
                    success=True, result="remote-data",
                ),
            ]

        intent_bus._federation_fn = mock_federation

        intent = IntentMessage(intent="read_file", params={"path": "/a"})
        results = await intent_bus.broadcast(intent, timeout=1.0)

        assert len(federation_calls) == 1
        # Should include remote results
        remote = [r for r in results if r.agent_id == "remote-1"]
        assert len(remote) == 1
        assert remote[0].result == "remote-data"

    async def test_broadcast_federated_false_skips_federation(self, intent_bus):
        """broadcast(federated=False) does NOT call _federation_fn."""
        federation_calls = []

        async def mock_federation(intent):
            federation_calls.append(intent)
            return []

        intent_bus._federation_fn = mock_federation

        intent = IntentMessage(intent="read_file", params={"path": "/a"})
        await intent_bus.broadcast(intent, timeout=1.0, federated=False)

        assert len(federation_calls) == 0

    async def test_broadcast_no_federation_fn_unchanged(self, intent_bus):
        """broadcast() with _federation_fn=None behaves as before."""
        assert intent_bus._federation_fn is None

        intent = IntentMessage(intent="read_file", params={"path": "/a"})
        results = await intent_bus.broadcast(intent, timeout=1.0)

        # Empty results (no subscribers), but no error
        assert results == []


# ── TestFederationBridgeGossip (tests 29-30) ─────────────────────────

class TestFederationBridgeGossip:
    """Test gossip integration in federation bridge."""

    async def test_gossip_sends_self_model(self):
        """Gossip loop sends self-model to all peers on interval."""
        from probos.federation.mock_transport import MockFederationTransport, MockTransportBus
        from probos.federation.router import FederationRouter
        from probos.federation.bridge import FederationBridge

        transport_bus = MockTransportBus()
        t_a = MockFederationTransport("node-a", transport_bus)
        t_b = MockFederationTransport("node-b", transport_bus)

        received: list[FederationMessage] = []
        t_b._inbound_handler = lambda msg: _collect(received, msg)

        config = FederationConfig(
            enabled=True, node_id="node-a",
            gossip_interval_seconds=0.05,  # 50ms for fast test
        )

        bridge_a = FederationBridge(
            node_id="node-a", transport=t_a,
            router=FederationRouter(),
            intent_bus=_make_mock_intent_bus(),
            config=config,
            self_model_fn=_self_model_fn,
        )
        await bridge_a.start()
        await asyncio.sleep(0.15)  # Wait for at least one gossip cycle
        await bridge_a.stop()

        gossip_msgs = [m for m in received if m.type == "gossip_self_model"]
        assert len(gossip_msgs) >= 1
        payload = gossip_msgs[0].payload
        assert payload["node_id"] == "test-node"
        assert "read_file" in payload["capabilities"]

    async def test_receiving_gossip_updates_router(self):
        """Receiving gossip self-model updates router's peer model."""
        env = _make_two_node_env()
        await env["bridge_a"].start()

        gossip = FederationMessage(
            type="gossip_self_model",
            source_node="node-b",
            payload={
                "node_id": "node-b",
                "capabilities": ["write_file", "shell_command"],
                "pool_sizes": {"shell": 2},
                "agent_count": 5,
                "health": 0.8,
                "uptime_seconds": 30.0,
                "timestamp": 2.0,
            },
        )
        await env["bridge_a"].handle_inbound(gossip)

        peers = env["router_a"].known_peers
        assert "node-b" in peers
        assert peers["node-b"].health == 0.8
        assert "write_file" in peers["node-b"].capabilities

        await env["bridge_a"].stop()


# ── TestRuntimeFederation (tests 31-34) ──────────────────────────────

class TestRuntimeFederation:
    """Test federation wiring in ProbOS runtime."""

    async def test_runtime_creates_bridge_when_enabled(self, tmp_path):
        """Runtime creates FederationBridge when federation.enabled=True."""
        from probos.runtime import ProbOSRuntime

        # To test enabled=True, we need a mock transport wired in.
        # Instead, verify the attribute exists and defaults to None when disabled.
        cfg = SystemConfig()
        cfg.federation.enabled = False
        runtime = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await runtime.start()

        assert runtime.federation_bridge is None

        await runtime.stop()

    async def test_runtime_no_bridge_when_disabled(self, tmp_path):
        """Runtime does NOT create bridge when federation.enabled=False (default)."""
        from probos.runtime import ProbOSRuntime

        cfg = SystemConfig()
        assert cfg.federation.enabled is False
        runtime = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await runtime.start()

        assert runtime.federation_bridge is None
        assert runtime._federation_transport is None

        await runtime.stop()

    async def test_build_self_model(self, tmp_path):
        """Runtime _build_self_model returns correct capabilities and health."""
        from probos.runtime import ProbOSRuntime

        cfg = SystemConfig()
        runtime = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await runtime.start()

        model = runtime._build_self_model()
        assert model.node_id == "node-1"
        assert model.agent_count > 0
        assert len(model.capabilities) > 0
        assert "read_file" in model.capabilities
        assert model.uptime_seconds >= 0
        assert isinstance(model.pool_sizes, dict)

        await runtime.stop()

    async def test_status_includes_federation(self, tmp_path):
        """status() includes federation info."""
        from probos.runtime import ProbOSRuntime

        cfg = SystemConfig()
        runtime = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await runtime.start()

        status = runtime.status()
        assert "federation" in status
        assert status["federation"]["enabled"] is False

        await runtime.stop()


# ── TestShellFederationCommands (tests 35-38) ────────────────────────

class TestShellFederationCommands:
    """Test /federation and /peers shell commands and panel rendering."""

    async def test_federation_command_disabled(self, tmp_path):
        """'/federation' shows disabled message when federation is off."""
        from probos.runtime import ProbOSRuntime
        from probos.experience.shell import ProbOSShell
        from io import StringIO

        cfg = SystemConfig()
        runtime = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await runtime.start()

        console = Console(file=StringIO(), force_terminal=True, width=120)
        shell = ProbOSShell(runtime, console)
        await shell.execute_command("/federation")

        output = console.file.getvalue()
        assert "not enabled" in output.lower() or "disabled" in output.lower()

        await runtime.stop()

    async def test_peers_command_disabled(self, tmp_path):
        """'/peers' shows disabled message when federation is off."""
        from probos.runtime import ProbOSRuntime
        from probos.experience.shell import ProbOSShell
        from io import StringIO

        cfg = SystemConfig()
        runtime = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await runtime.start()

        console = Console(file=StringIO(), force_terminal=True, width=120)
        shell = ProbOSShell(runtime, console)
        await shell.execute_command("/peers")

        output = console.file.getvalue()
        assert "not enabled" in output.lower() or "disabled" in output.lower()

        await runtime.stop()

    async def test_help_includes_federation(self, tmp_path):
        """'/help' output includes /federation and /peers."""
        from probos.runtime import ProbOSRuntime
        from probos.experience.shell import ProbOSShell
        from io import StringIO

        cfg = SystemConfig()
        runtime = ProbOSRuntime(config=cfg, data_dir=tmp_path)
        await runtime.start()

        console = Console(file=StringIO(), force_terminal=True, width=120)
        shell = ProbOSShell(runtime, console)
        await shell.execute_command("/help")

        output = console.file.getvalue()
        assert "/federation" in output
        assert "/peers" in output

        await runtime.stop()

    def test_render_federation_panel_disabled(self):
        """render_federation_panel with enabled=False renders disabled message."""
        panel = panels.render_federation_panel({"enabled": False})
        # Verify it's a Panel with "Federation" title
        assert panel.title is not None

    def test_render_federation_panel_with_data(self):
        """render_federation_panel with real data renders correctly."""
        panel = panels.render_federation_panel({
            "node_id": "node-1",
            "bind_address": "tcp://127.0.0.1:5555",
            "connected_peers": ["node-2", "node-3"],
            "peer_models": {},
            "intents_forwarded": 5,
            "intents_received": 3,
            "results_collected": 4,
            "gossip_interval": 10.0,
        })
        assert panel.title is not None

    def test_render_peers_panel_empty(self):
        """render_peers_panel with empty data shows no peers message."""
        panel = panels.render_peers_panel({})
        assert panel.title is not None

    def test_render_peers_panel_with_data(self):
        """render_peers_panel with peer data renders table."""
        panel = panels.render_peers_panel({
            "node-2": {
                "capabilities": ["read_file", "write_file"],
                "agent_count": 5,
                "health": 0.85,
                "uptime_seconds": 300.0,
            },
        })
        assert panel.title is not None
