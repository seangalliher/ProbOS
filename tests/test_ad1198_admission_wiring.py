"""AD-1198 (#1135): the wiring of peer admission.

M0 pins what nothing armed must keep: a ZeroMQ DEALER claims its node id as its routing id and the
ROUTER is given no handover option, and envelope signing without admission keeps AD-1197's trust on
first use for an unconfigured signed sender. M4 covers the wiring: hardened ZeroMQ routing (the ROUTER
handover set before the bind, an unguessable DEALER routing id, fresh on every start), the armed fleet
wrapping its transport with admission on the ZeroMQ and the NATS path, and the admission-off fleet
keeping legacy routing. M5 checks the configuration-profiles row that classifies the flag. No test
opens a socket (a recording fake ZeroMQ context and the mock NATS bus stand in) or reaches the real OS
keyring (AD-1196's autouse guard is imported, H5).
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
import zmq

import probos.federation.transport as federation_transport_module
from probos.config import (
    FederationConfig,
    MedicalConfig,
    PeerConfig,
    ScalingConfig,
    SelfModConfig,
    SystemConfig,
    UtilityAgentsConfig,
)
from probos.federation.envelope import POLICY_REQUIRE
from probos.federation.signed_transport import SignedFederationTransport, build_signed_transport
from probos.federation.transport import FederationTransport
from probos.federation_envelope_store import ENVELOPE_DB_NAME
from probos.types import FederationMessage
from tests.test_ad1196_did_key_binding import (  # noqa: F401 -- importing the autouse guard applies it here (H5)
    _armed,
    _DuckKeyring,
    _new_key,
    _no_real_os_keyring,
)
from tests.test_ad1197_envelope_wiring import _FEDERATION_SUBJECTS, _fleet, _nats_bus, _RecordingIntentBus
from tests.test_ad1197_signed_envelopes import _active_key, _node, _rows, _seal, _Wire
from tests.test_ad1198_peer_admission import _refusals
from tests.test_ad730_4_directed_federated_vision_dm import _FakeZmqContext, _FakeZmqSocket

_ROUTING_ID = re.compile(rb"probos-[0-9a-f]{32}")
_PROFILES = Path(__file__).resolve().parents[1] / "docs" / "development" / "config-profiles.yaml"
_GATE = Path(__file__).resolve().with_name("test_ad1198_cluster_gate.py")


class _RecordingZmqSocket(_FakeZmqSocket):
    """AD-730's fake socket, recording its options, binds and connects; ``inbox`` feeds ``recv_multipart``."""

    def __init__(self, kind: Any, context: _RecordingZmqContext) -> None:
        super().__init__()
        self.kind = kind
        self.inbox: asyncio.Queue[list[bytes]] = asyncio.Queue()
        self._context = context

    def setsockopt(self, name: Any, value: Any) -> None:
        self._context.ops.append((self.kind, name, value))
        self._context.events.append(("setsockopt", self.kind, name, value))

    def bind(self, address: str) -> None:
        self._context.events.append(("bind", self.kind, address))

    def connect(self, address: str) -> None:
        self._context.events.append(("connect", self.kind, address))

    async def recv_multipart(self) -> list[bytes]:
        return await self.inbox.get()


class _RecordingZmqContext(_FakeZmqContext):
    """A fake ZeroMQ context recording its sockets' kinds and options (``ops``) and, in order, every option,
    bind and connect (``events``)."""

    def __init__(self) -> None:
        super().__init__()
        self.kinds: list[Any] = []
        self.ops: list[tuple[Any, Any, Any]] = []
        self.events: list[tuple[Any, ...]] = []

    def socket(self, socket_type: Any) -> _RecordingZmqSocket:
        self.kinds.append(socket_type)
        socket = _RecordingZmqSocket(socket_type, self)
        self.sockets.append(socket)
        return socket

    def router(self) -> _RecordingZmqSocket:
        (router,) = [s for s in self.sockets if isinstance(s, _RecordingZmqSocket) and s.kind == zmq.ROUTER]
        return router

    def dealer_ids(self) -> list[bytes]:
        return [value for kind, name, value in self.ops if kind == zmq.DEALER and name == zmq.IDENTITY]


def _contexts(monkeypatch: pytest.MonkeyPatch) -> list[_RecordingZmqContext]:
    """Install a recording fake as ``zmq.asyncio.Context``; returns every context it makes, in order."""
    made: list[_RecordingZmqContext] = []

    def _context() -> _RecordingZmqContext:
        made.append(_RecordingZmqContext())
        return made[-1]

    monkeypatch.setattr(federation_transport_module.zmq.asyncio, "Context", _context)
    return made


def _admission_config(pin: str, *, admission: bool) -> SystemConfig:
    """Node-a federating with node-b under envelope policy ``require``, with peer admission armed or not."""
    return SystemConfig(
        federation=FederationConfig(
            enabled=True, node_id="node-a", gossip_interval_seconds=1_000.0,
            peers=[PeerConfig(node_id="node-b", address="tcp://127.0.0.1:65530", pinned_public_key=pin)],
            identity_keys_enabled=True, envelope_signing_enabled=True, envelope_policy="require",
            peer_admission_enabled=admission,
        ),
        scaling=ScalingConfig(enabled=False),
        utility_agents=UtilityAgentsConfig(enabled=False),
        medical=MedicalConfig(enabled=False),
        self_mod=SelfModConfig(enabled=False),
    )


def _wire_dict(message: FederationMessage) -> dict[str, Any]:
    """``message`` as both real transports put it on the wire (``auth`` only when signed)."""
    data: dict[str, Any] = {
        "type": message.type, "source_node": message.source_node, "message_id": message.message_id,
        "payload": message.payload, "timestamp": message.timestamp,
    }
    if message.auth is not None:
        data["auth"] = message.auth
    return data


async def _until(predicate: Callable[[], object], *, timeout_s: float = 5.0) -> None:
    """A barrier with a deadline: return once ``predicate()`` holds; fail if it never does."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        assert loop.time() < deadline, "the awaited condition never held"
        await asyncio.sleep(0.01)


# --------------------------------------------------------------------------- #
# M0 -- byte-identity pins (pass at the base before any source edit)
# --------------------------------------------------------------------------- #


async def test_m0_zmq_transport_claims_its_node_id_as_routing_id_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _RecordingZmqContext()
    monkeypatch.setattr(federation_transport_module.zmq.asyncio, "Context", lambda: context)
    transport = FederationTransport(
        "node-a", "tcp://127.0.0.1:65529", [PeerConfig(node_id="node-b", address="tcp://127.0.0.1:65530")],
    )

    await transport.start()
    try:
        assert context.kinds == [zmq.ROUTER, zmq.DEALER]  # premise: the fake built the ROUTER and one DEALER
        assert context.ops == [(zmq.DEALER, zmq.IDENTITY, b"node-a")]  # the node id; no ROUTER_HANDOVER, nothing else
    finally:
        await transport.stop()


async def test_m0_signing_without_admission_keeps_first_contact_trust_on_first_use(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        b = await _node(stack, wire, tmp_path, "node-b")
        c = await _node(stack, wire, tmp_path, "node-c")
        await b.transport.stop()
        transport = build_signed_transport(b.inner, policy=POLICY_REQUIRE, key_binding=b.binding, data_dir=b.data_dir)

        async def _dispatch(message: FederationMessage) -> None:
            b.dispatched.append(message)

        transport._inbound_handler = _dispatch  # the bridge's own handler contract (bridge.py:1054), as AD-1197's _wrap does
        stack.push_async_callback(transport.stop)
        await transport.start()
        sealed = await _seal(c, "node-b")

        await wire.inject("node-b", sealed)

        assert b.dispatched == [sealed]
        assert [row[:2] for row in _rows(b.store_path)["senders"]] == [("node-c", (await c.binding.status())["did"])]


# --------------------------------------------------------------------------- #
# M4 -- wiring and ZeroMQ hardening
# --------------------------------------------------------------------------- #


async def test_m4_hardened_router_sets_handover_and_dealers_claim_unguessable_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    contexts = _contexts(monkeypatch)
    transport = FederationTransport(
        "node-a", "tcp://127.0.0.1:65529",
        [
            PeerConfig(node_id="node-b", address="tcp://127.0.0.1:65530"),
            PeerConfig(node_id="node-c", address="tcp://127.0.0.1:65531"),
        ],
        harden_routing=True,
    )
    started: list[list[bytes]] = []
    for _ in range(2):
        await transport.start()
        try:
            context = contexts[-1]
            assert context.kinds == [zmq.ROUTER, zmq.DEALER, zmq.DEALER]  # premise: a ROUTER and one DEALER per peer
            assert context.events[:2] == [
                ("setsockopt", zmq.ROUTER, zmq.ROUTER_HANDOVER, 1), ("bind", zmq.ROUTER, "tcp://127.0.0.1:65529"),
            ]  # the handover is set before the ROUTER binds
            assert [op for op in context.ops if op[0] == zmq.ROUTER] == [(zmq.ROUTER, zmq.ROUTER_HANDOVER, 1)]
            routing_ids = context.dealer_ids()
            assert len(routing_ids) == 2 and all(_ROUTING_ID.fullmatch(routing_id) for routing_id in routing_ids)
            assert len(set(routing_ids)) == 2  # one per DEALER, never the node id
            started.append(routing_ids)
        finally:
            await transport.stop()
    assert len(contexts) == 2  # premise: each start built its own context
    assert set(started[0]).isdisjoint(started[1])  # a restarted node never reuses a routing id


async def test_m4_armed_fleet_hardens_zmq_routing_and_wraps_with_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    contexts = _contexts(monkeypatch)
    config = _admission_config(_new_key().public, admission=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    intent_bus = _RecordingIntentBus()
    async with _armed(tmp_path / "identity", _DuckKeyring()) as (_, binding):
        async with _fleet(config, bus=None, identity_key_binding=binding, data_dir=data_dir, intent_bus=intent_bus) as result:
            assert type(result.federation_transport) is SignedFederationTransport
            assert result.federation_bridge is not None
            (context,) = contexts  # premise: no NATS bus, so the ZeroMQ path built the transport, once
            assert context.kinds == [zmq.ROUTER, zmq.DEALER]
            assert context.events[:2] == [
                ("setsockopt", zmq.ROUTER, zmq.ROUTER_HANDOVER, 1), ("bind", zmq.ROUTER, config.federation.bind_address),
            ]
            (routing_id,) = context.dealer_ids()
            assert _ROUTING_ID.fullmatch(routing_id)
            unconfigured = FederationMessage(
                type="intent_request", source_node="node-x",
                payload={"intent": "read_file", "params": {"path": "/a"}, "id": "i-x"}, timestamp=1.0,
            )
            await context.router().inbox.put([b"probos-x", json.dumps(_wire_dict(unconfigured)).encode()])
            await _until(lambda: _refusals(caplog))
            assert _refusals(caplog) == [("intent_request", "node-x", "unconfigured source", 1)]  # refused at the seam
            assert intent_bus.broadcasts == []


async def test_m4_admission_off_fleet_keeps_legacy_zmq_routing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    contexts = _contexts(monkeypatch)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    async with _armed(tmp_path / "identity", _DuckKeyring()) as (_, binding):
        async with _fleet(
            _admission_config("", admission=False), bus=None, identity_key_binding=binding, data_dir=data_dir,
        ) as result:
            assert type(result.federation_transport) is SignedFederationTransport  # premise: envelope signing is on
            assert result.federation_bridge is not None
            (context,) = contexts
            assert context.kinds == [zmq.ROUTER, zmq.DEALER]
            assert context.ops == [(zmq.DEALER, zmq.IDENTITY, b"node-a")]  # the node id; no ROUTER_HANDOVER


async def test_m4_nats_fleet_with_admission_refuses_an_unconfigured_publisher(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    wire = _Wire()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    intent_bus = _RecordingIntentBus()
    async with contextlib.AsyncExitStack() as stack:
        b = await _node(stack, wire, tmp_path, "node-b")
        z = await _node(stack, wire, tmp_path, "node-z")
        _, pin_b = await _active_key(b.binding)
        bus = await stack.enter_async_context(_nats_bus())
        _, binding = await stack.enter_async_context(_armed(tmp_path / "identity", _DuckKeyring()))
        result = await stack.enter_async_context(_fleet(
            _admission_config(pin_b, admission=True), bus=bus, identity_key_binding=binding, data_dir=data_dir,
            intent_bus=intent_bus,
        ))
        assert type(result.federation_transport) is SignedFederationTransport
        assert bus.raw_subscriptions == _FEDERATION_SUBJECTS  # premise: the NATS path started the inner transport
        from_z = await _seal(z, "node-a", payload={"intent": "read_file", "params": {"path": "/a"}, "id": "i-z"})
        await bus.publish_raw("federation.intent.node-a", _wire_dict(from_z))
        await _until(lambda: _refusals(caplog))
        assert _refusals(caplog) == [("intent_request", "node-z", "unconfigured source", 1)]
        assert intent_bus.broadcasts == []
        from_b = await _seal(b, "node-a", payload={"intent": "read_file", "params": {"path": "/a"}, "id": "i-b"})
        await bus.publish_raw("federation.intent.node-a", _wire_dict(from_b))
        await _until(lambda: intent_bus.broadcasts)
        assert [intent.id for intent in intent_bus.broadcasts] == ["i-b"]  # the pinned peer's signed intent is broadcast
    assert [row[0] for row in _rows(data_dir / ENVELOPE_DB_NAME)["senders"]] == ["node-b"]


def test_m5_profile_classifies_peer_admission_as_a_security_control() -> None:
    manifest = yaml.safe_load(_PROFILES.read_text(encoding="utf-8"))
    rows = [row for row in manifest["flags"] if row["path"] == "federation.peer_admission_enabled"]
    assert len(rows) == 1
    row = rows[0]
    assert (row["kind"], row["profiles"], row["requires"]) == (
        "security-control", [], ["federation.envelope_signing_enabled"],
    )
    assert "federation.peer_admission_enabled" not in manifest["unclassified_flags"]
    named = set(re.findall(r"tests/test_ad1198_cluster_gate\.py::(test_\w+)", row["evidence_to_promote"]))
    assert named  # premise: the evidence names a gate test
    gate = ast.parse(_GATE.read_text(encoding="utf-8"))
    assert named <= {node.name for node in gate.body if isinstance(node, ast.FunctionDef)}
