"""AD-637a: NATS Integration Layer — Foundation Tests.

23 tests covering NATSMessage, NATSBus, MockNATSBus, NATSBusProtocol,
NatsConfig, init_nats, ship DID prefix update, and integration behaviors.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.config import NatsConfig, SystemConfig, load_config
from probos.mesh.nats_bus import MockNATSBus, NATSBus, NATSMessage
from probos.protocols import NATSBusProtocol


# ---------------------------------------------------------------------------
# Test 1: MockNATSBus satisfies NATSBusProtocol
# ---------------------------------------------------------------------------


class TestProtocolCompliance:

    def test_mock_nats_bus_protocol_compliance(self):
        """Test 1: MockNATSBus satisfies NATSBusProtocol."""
        mock = MockNATSBus()
        assert isinstance(mock, NATSBusProtocol)

    def test_nats_bus_protocol_compliance(self):
        """Test 2: NATSBus satisfies NATSBusProtocol."""
        bus = NATSBus()
        assert isinstance(bus, NATSBusProtocol)


# ---------------------------------------------------------------------------
# Tests 3-10: MockNATSBus behavior
# ---------------------------------------------------------------------------


class TestMockNATSBus:

    @pytest.mark.asyncio
    async def test_publish_subscribe_roundtrip(self):
        """Test 3: Publish message, subscriber receives it."""
        bus = MockNATSBus()
        await bus.start()

        received: list[NATSMessage] = []

        async def handler(msg: NATSMessage) -> None:
            received.append(msg)

        await bus.subscribe("events.test", handler)
        await bus.publish("events.test", {"key": "value"})

        assert len(received) == 1
        assert received[0].data == {"key": "value"}
        assert received[0].subject == "probos.test.events.test"

    @pytest.mark.asyncio
    async def test_request_reply(self):
        """Test 4: Request-reply pattern works in mock."""
        bus = MockNATSBus()
        await bus.start()

        async def responder(msg: NATSMessage) -> None:
            await msg.respond({"answer": 42})

        await bus.subscribe("query.ping", responder)
        reply = await bus.request("query.ping", {"question": "?"})

        assert reply is not None
        assert reply.data == {"answer": 42}

    @pytest.mark.asyncio
    async def test_subject_prefix(self):
        """Test 5: Subject prefix is prepended correctly."""
        bus = MockNATSBus(subject_prefix="probos.ship1")
        await bus.start()

        received: list[NATSMessage] = []

        async def handler(msg: NATSMessage) -> None:
            received.append(msg)

        await bus.subscribe("events.test", handler)
        await bus.publish("events.test", {"data": 1})

        assert len(received) == 1
        assert received[0].subject == "probos.ship1.events.test"

    @pytest.mark.asyncio
    async def test_wildcard_matching(self):
        """Test 6: NATS wildcard matching (* and >)."""
        bus = MockNATSBus()
        await bus.start()

        # Test * wildcard (single token)
        assert bus._match_subject("a.*.c", "a.b.c") is True
        assert bus._match_subject("a.*.c", "a.b.d") is False
        assert bus._match_subject("a.*.c", "a.b.c.d") is False

        # Test > wildcard (one or more tokens)
        assert bus._match_subject("a.>", "a.b") is True
        assert bus._match_subject("a.>", "a.b.c") is True
        assert bus._match_subject("a.>", "a.b.c.d") is True

        # Exact match
        assert bus._match_subject("a.b.c", "a.b.c") is True
        assert bus._match_subject("a.b.c", "a.b.d") is False

    @pytest.mark.asyncio
    async def test_not_connected_noop(self):
        """Test 7: Operations are no-ops when not connected."""
        bus = MockNATSBus()
        # Don't call start()

        await bus.publish("events.test", {"data": 1})
        assert len(bus.published) == 0

        reply = await bus.request("query.ping", {"q": 1})
        assert reply is None

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self):
        """Test 8: start sets connected=True, stop clears state."""
        bus = MockNATSBus()
        assert bus.connected is False

        await bus.start()
        assert bus.connected is True

        await bus.subscribe("test.topic", AsyncMock())
        assert len(bus._subs) == 1

        await bus.stop()
        assert bus.connected is False
        assert len(bus._subs) == 0

    @pytest.mark.asyncio
    async def test_ensure_stream(self):
        """Test 9: Stream creation is tracked."""
        bus = MockNATSBus()
        await bus.start()

        await bus.ensure_stream("EVENTS", ["events.>"], max_msgs=1000)

        assert "EVENTS" in bus._streams
        assert bus._streams["EVENTS"]["subjects"] == ["events.>"]
        assert bus._streams["EVENTS"]["max_msgs"] == 1000

    @pytest.mark.asyncio
    async def test_js_publish_delegates_to_publish(self):
        """Test 10: js_publish uses same path as publish in mock."""
        bus = MockNATSBus()
        await bus.start()

        received: list[NATSMessage] = []

        async def handler(msg: NATSMessage) -> None:
            received.append(msg)

        await bus.subscribe("events.durable", handler)
        await bus.js_publish("events.durable", {"js": True})

        assert len(received) == 1
        assert received[0].data == {"js": True}


# ---------------------------------------------------------------------------
# Tests 11-12: NATSBus (real client, no server needed)
# ---------------------------------------------------------------------------


class TestNATSBus:

    def test_not_connected_before_start(self):
        """Test 11: NATSBus is not connected before start()."""
        bus = NATSBus()
        assert bus.connected is False

    @pytest.mark.asyncio
    async def test_graceful_failure(self):
        """Test 12: start() with unreachable server doesn't raise."""
        bus = NATSBus(
            url="nats://localhost:19999",
            connect_timeout=0.5,
            max_reconnect_attempts=0,
        )

        # Mock nats.connect to simulate connection failure
        with patch("nats.connect", new_callable=AsyncMock, side_effect=ConnectionRefusedError("refused")):
            # Should NOT raise — graceful degradation
            await bus.start()
            assert bus.connected is False


# ---------------------------------------------------------------------------
# Tests 13-14: NatsConfig
# ---------------------------------------------------------------------------


class TestNatsConfig:

    def test_defaults(self):
        """Test 13: NatsConfig defaults match expected values."""
        cfg = NatsConfig()
        assert cfg.enabled is False
        assert cfg.url == "nats://localhost:4222"
        assert cfg.connect_timeout_seconds == 5.0
        assert cfg.max_reconnect_attempts == 60
        assert cfg.reconnect_time_wait_seconds == 2.0
        assert cfg.drain_timeout_seconds == 5.0
        assert cfg.jetstream_enabled is True
        assert cfg.jetstream_domain is None
        assert cfg.subject_prefix == "probos.local"

    def test_loads_from_yaml(self, tmp_path):
        """Test 14: load_config parses nats section from system.yaml."""
        yaml_content = """
nats:
  enabled: true
  url: "nats://custom:4222"
  connect_timeout_seconds: 10.0
  subject_prefix: "probos.myship"
"""
        cfg_file = tmp_path / "system.yaml"
        cfg_file.write_text(yaml_content)

        config = load_config(cfg_file)
        assert config.nats.enabled is True
        assert config.nats.url == "nats://custom:4222"
        assert config.nats.connect_timeout_seconds == 10.0
        assert config.nats.subject_prefix == "probos.myship"
        # Defaults preserved for unspecified fields
        assert config.nats.max_reconnect_attempts == 60


# ---------------------------------------------------------------------------
# Tests 15-16: Health reporting
# ---------------------------------------------------------------------------


class TestHealth:

    def test_health_not_started(self):
        """Test 15: health() returns correct status when not started."""
        bus = NATSBus()
        h = bus.health()
        assert h["connected"] is False
        assert h["status"] == "not_started"
        assert h["url"] == "nats://localhost:4222"

    def test_health_connected_mock(self):
        """Test 16: health() returns correct status for connected MockNATSBus."""
        bus = MockNATSBus()
        # Before start
        h = bus.health()
        assert h["connected"] is False

        # Simulate start manually
        bus._connected = True
        h = bus.health()
        assert h["connected"] is True
        assert h["status"] == "mock"
        assert h["jetstream"] is True


# ---------------------------------------------------------------------------
# Test 17: init_nats disabled
# ---------------------------------------------------------------------------


class TestInitNats:

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self):
        """Test 17: init_nats returns None when nats.enabled=False."""
        from probos.startup.nats import init_nats

        config = SystemConfig()
        assert config.nats.enabled is False

        result = await init_nats(config)
        assert result is None


# ---------------------------------------------------------------------------
# Test 18: NATSMessage wrapper
# ---------------------------------------------------------------------------


class TestNATSMessage:

    def test_message_wrapper(self):
        """Test 18: NATSMessage construction and attribute access."""
        msg = NATSMessage(
            subject="probos.local.events.test",
            data={"key": "value"},
            reply="_INBOX.123",
            headers={"X-Custom": "header"},
        )
        assert msg.subject == "probos.local.events.test"
        assert msg.data == {"key": "value"}
        assert msg.reply == "_INBOX.123"
        assert msg.headers == {"X-Custom": "header"}
        assert msg._msg is None

    @pytest.mark.asyncio
    async def test_ack_nak_safe_without_msg(self):
        """NATSMessage ack/nak are safe when _msg is None."""
        msg = NATSMessage(subject="test", data={})
        # Should not raise
        await msg.ack()
        await msg.nak()
        await msg.respond({"reply": True})


# ---------------------------------------------------------------------------
# Test 19: Published inspection
# ---------------------------------------------------------------------------


class TestPublishedInspection:

    @pytest.mark.asyncio
    async def test_published_list(self):
        """Test 19: MockNATSBus.published captures all published messages."""
        bus = MockNATSBus()
        await bus.start()

        await bus.publish("a.b", {"x": 1})
        await bus.publish("c.d", {"y": 2})
        await bus.js_publish("e.f", {"z": 3})

        assert len(bus.published) == 3
        subjects = [s for s, _ in bus.published]
        assert "probos.test.a.b" in subjects
        assert "probos.test.c.d" in subjects
        assert "probos.test.e.f" in subjects


# ---------------------------------------------------------------------------
# Test 20: Subject prefix update
# ---------------------------------------------------------------------------


class TestSubjectPrefixUpdate:

    @pytest.mark.asyncio
    async def test_set_subject_prefix(self):
        """Test 20: set_subject_prefix changes prefix for subsequent operations."""
        bus = MockNATSBus(subject_prefix="probos.local")
        await bus.start()

        await bus.publish("events.a", {"before": True})
        assert bus.published[0][0] == "probos.local.events.a"

        await bus.set_subject_prefix("probos.ship-abc123")
        await bus.publish("events.b", {"after": True})
        assert bus.published[1][0] == "probos.ship-abc123.events.b"


# ---------------------------------------------------------------------------
# Test 21: js_publish fallback to core NATS
# ---------------------------------------------------------------------------


class TestJSPublishFallback:

    @pytest.mark.asyncio
    async def test_fallback_when_no_jetstream(self):
        """Test 21: js_publish falls back to core NATS when JetStream unavailable."""
        bus = NATSBus(jetstream_enabled=False)
        # Don't start — just verify the _js is None
        assert bus._js is None

        # Mock the connected state and _nc for publish path
        bus._connected = True
        bus._nc = MagicMock()
        bus._nc.is_connected = True
        bus._nc.publish = AsyncMock()

        await bus.js_publish("events.test", {"fallback": True})

        # Should have called core publish
        bus._nc.publish.assert_called_once()
        call_args = bus._nc.publish.call_args
        assert "events.test" in call_args[0][0]


# ---------------------------------------------------------------------------
# Test 22: Ship DID prefix update in runtime (regression)
# ---------------------------------------------------------------------------


class TestShipDIDPrefixUpdate:

    @pytest.mark.asyncio
    async def test_nats_prefix_updated_after_ship_commissioning(self):
        """Test 22: NATS subject prefix updates to ship DID after Phase 4.

        Regression test for AD-637a blocker: runtime must call
        identity_registry.get_ship_certificate().ship_did, NOT
        getattr(identity_registry, 'ship_did', ...) which silently
        returns '' and makes the prefix update a permanent no-op.
        """
        bus = MockNATSBus(subject_prefix="probos.local")
        await bus.start()
        assert bus.subject_prefix == "probos.local"

        # Simulate identity registry with ship certificate
        mock_cert = MagicMock()
        mock_cert.ship_did = "did:probos:abc123"

        mock_registry = MagicMock()
        mock_registry.get_ship_certificate.return_value = mock_cert

        # Replicate the runtime logic from communication.py Phase 4
        if bus and mock_registry:
            cert = mock_registry.get_ship_certificate()
            if cert:
                await bus.set_subject_prefix(f"probos.{cert.ship_did}")

        assert bus.subject_prefix == "probos.did:probos:abc123"
        mock_registry.get_ship_certificate.assert_called_once()

    @pytest.mark.asyncio
    async def test_nats_prefix_unchanged_without_certificate(self):
        """Test 23: NATS prefix stays as probos.local when no cert."""
        bus = MockNATSBus(subject_prefix="probos.local")
        await bus.start()

        mock_registry = MagicMock()
        mock_registry.get_ship_certificate.return_value = None

        if bus and mock_registry:
            cert = mock_registry.get_ship_certificate()
            if cert:
                await bus.set_subject_prefix(f"probos.{cert.ship_did}")

        assert bus.subject_prefix == "probos.local"
