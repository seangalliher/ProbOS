"""AD-1197 (#1134): federation envelopes signed with the ship key, with replay protection.

M0 pins the unsigned wire on both real transports, the message's legacy fields and
repr, and the off fleet organisation, so arming envelope signing provably changes
none of them. M1 drives the thin real chain: two armed AD-1196 bindings, real
bridges and the mock transport, each node's transport wrapped by
``build_signed_transport``. M2 covers the verifier, the replay window, the key
holds and the store; every negative test first shows the honest path succeeding
with the same inputs. M3 covers the two policies, mixed fleets, the binding's
latch and re-sign, and log hygiene; A-0 a body too deep for RFC 8785. M4 carries
the signature block over both real transports' wire forms. A-1 covers a ship whose
key history outgrows the envelope bound, the first-contact anchor, and a malformed
signature block in every mode. A-2 covers the key ids a holder records for each
sender, and A-2b the bound on a signed envelope's source node id.

No test opens a socket or reaches the real OS keyring: AD-1196's autouse guard is
imported (H4), and every binding gets an in-memory duck keyring. Nodes are wired by
hand (constructor injection); the config and fleet wiring belong to M5.
"""

from __future__ import annotations

import ast
import asyncio
import base64
import contextlib
import copy
import dataclasses
import json
import logging
import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import probos.federation.envelope as envelope_module
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
from probos.federation.ard.jcs import canonicalize
from probos.federation.ard.jws import JWS_ALG, b64url_decode, b64url_encode, encode_protected_header, parse_detached
from probos.federation.bridge import FederationBridge
from probos.federation.envelope import (
    BROADCAST,
    MAX_AUTH_BYTES,
    MAX_KEY_EVENTS,
    MAX_SEQUENCE,
    POLICY_REQUIRE,
    POLICY_SIGN,
    REPLAY_WINDOW,
    EnvelopeAuth,
    EnvelopeGuard,
    EnvelopeNotSent,
    EnvelopeRejected,
    advance_window,
    body_digest,
    envelope_statement,
    key_events_from_wire,
    key_events_to_wire,
    parse_auth,
)
from probos.federation.mock_transport import MockFederationTransport, MockTransportBus
from probos.federation.nats_transport import NATSFederationTransport
from probos.federation.router import FederationRouter
from probos.federation.signed_transport import SignedFederationTransport, build_signed_transport
from probos.federation.transport import FederationTransport
from probos.federation_envelope_store import (
    ENVELOPE_DB_NAME,
    EnvelopeStateConflict,
    EnvelopeStore,
    StoredSender,
    StoredWindow,
)
from probos.identity import AgentIdentityRegistry
from probos.identity_key_binding import IdentityKeyBinding
from probos.identity_key_store import KeyringKeyStore
from probos.identity_keys import (
    ENVELOPE_JWS_TYP,
    EVENT_INCEPTION,
    EVENT_RECOVERY,
    EVENT_REINCEPTION,
    EVENT_ROTATION,
    KEY_EVENT_JWS_TYP,
    STATUS_ACTIVE,
    VC_JWS_TYP,
    KeyEvent,
    KeyEventInvalid,
    KeyState,
    KeyStoreUnavailable,
    build_event_payload,
    canonical_bytes,
    derive_key_state,
    event_digest,
    generate_recovery_keypair,
    jws_kid,
    keeps_held_key_events,
    key_id,
    sign_recovery_authorization,
    sign_with,
    verify_signature_for,
)
from probos.mesh.intent import IntentBus
from probos.mesh.nats_bus import MockNATSBus
from probos.mesh.signal import SignalManager
from probos.startup.fleet_organization import organize_fleet
from probos.storage.sqlite_factory import default_factory
from probos.substrate.device_pairing import decode_private_key, sign_challenge
from probos.substrate.pool_group import PoolGroupRegistry
from probos.types import FederationMessage, IntentMessage, IntentResult, NodeSelfModel
from tests.test_ad1196_did_key_binding import (  # noqa: F401 -- importing the autouse guard applies it here (H4)
    _armed,
    _birth,
    _block_for,
    _DuckKeyring,
    _FailingFactory,
    _no_real_os_keyring,
)

_LEGACY_MEMBERS = ["type", "source_node", "message_id", "payload", "timestamp"]
_BRIDGE_TYPES = frozenset({
    "relay_one_way", "intent_request", "intent_response", "gossip_self_model", "ping", "pong",
    "chain_request", "chain_response", "transfer_request", "transfer_response",
})
_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"
_ENVELOPE_MODULE = _SRC / "federation" / "envelope.py"
_SIGNED_TRANSPORT_MODULE = _SRC / "federation" / "signed_transport.py"
_STORE_MODULE = _SRC / "federation_envelope_store.py"
_ENVELOPE_LOGGER = "probos.federation.envelope"
_REJECTED = "AD-1197: envelope %r from %r rejected (%s); not delivered"
_REQUEST = {"intent": "read_file", "params": {"path": "/a"}, "id": "i-1"}


def _representative_messages() -> list[FederationMessage]:
    """One message of each type the bridge builds or answers, payloads shaped as the bridge builds them."""
    return [
        FederationMessage(
            type="relay_one_way", source_node="node-a", message_id="m01",
            payload={
                "relay_version": 1, "target_node_id": "node-b", "topic": "test.telemetry.v1",
                "payload": {"agent_id": "a1", "frame_type": "snapshot", "data": {"sequence": 7}}, "hop_count": 0,
            },
            timestamp=12.5,
        ),
        FederationMessage(
            type="intent_request", source_node="node-a", message_id="m02",
            payload={
                "intent": "read_file", "params": {"path": "/a", "f": 0.1, "u": "\u00e9"}, "urgency": 0.5,
                "context": "", "id": "i1", "ttl_seconds": 30.0,
            },
            timestamp=13.0,
        ),
        FederationMessage(
            type="intent_response", source_node="node-b", message_id="m02",
            payload={
                "results": [{
                    "intent_id": "i1", "agent_id": "b1", "success": True, "result": "ok", "error": None,
                    "confidence": 0.9,
                }],
                "admitted": True,
            },
            timestamp=13.5,
        ),
        FederationMessage(
            type="gossip_self_model", source_node="node-a", message_id="m03",
            payload={
                "node_id": "node-a", "capabilities": ["read_file"], "pool_sizes": {"filesystem": 2},
                "agent_count": 3, "health": 1.0, "uptime_seconds": 12.0, "timestamp": 1.0,
            },
            timestamp=14.0,
        ),
        FederationMessage(type="ping", source_node="node-a", message_id="m04", timestamp=15.0),
        FederationMessage(type="pong", source_node="node-b", message_id="m04", timestamp=15.5),
        FederationMessage(type="chain_request", source_node="node-a", message_id="m05", payload={}, timestamp=16.0),
        FederationMessage(
            type="chain_response", source_node="node-b", message_id="m05", payload={"blocks": []}, timestamp=16.5,
        ),
        FederationMessage(
            type="transfer_request", source_node="node-a", message_id="m06",
            payload={"cert_dict": {"agent_uuid": "u1", "did": "did:probos:ship-a:u1"}, "chain_blocks": []},
            timestamp=17.0,
        ),
        FederationMessage(
            type="transfer_response", source_node="node-b", message_id="m06",
            payload={"accepted": False, "message": "identity_registry not wired", "agent_uuid": None},
            timestamp=17.5,
        ),
    ]


def _off_system_config(node_id: str) -> SystemConfig:
    return SystemConfig(
        federation=FederationConfig(enabled=True, node_id=node_id, gossip_interval_seconds=1_000.0),
        scaling=ScalingConfig(enabled=False),
        utility_agents=UtilityAgentsConfig(enabled=False),
        medical=MedicalConfig(enabled=False),
        self_mod=SelfModConfig(enabled=False),
    )


# --------------------------------------------------------------------------- #
# M0 -- byte-identity pins (pass at b621d3ab before any source edit)
# --------------------------------------------------------------------------- #


def test_m0_unsigned_wire_bytes_are_unchanged_on_both_transports(monkeypatch) -> None:
    assert federation_transport_module._HAS_ZMQ is True  # premise: the ZeroMQ transport can be constructed

    def _no_context(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("constructing the ZeroMQ transport must open nothing")

    monkeypatch.setattr(federation_transport_module.zmq.asyncio, "Context", _no_context)
    zmq_transport = FederationTransport(node_id="node-a", bind_address="tcp://127.0.0.1:65530", peers=[])
    nats_transport = NATSFederationTransport(node_id="node-a", nats_bus=MockNATSBus(), peer_node_ids=[])
    messages = _representative_messages()
    assert {message.type for message in messages} == _BRIDGE_TYPES
    for message in messages:
        legacy = {
            "type": message.type, "source_node": message.source_node, "message_id": message.message_id,
            "payload": message.payload, "timestamp": message.timestamp,
        }
        assert zmq_transport._serialize(message) == json.dumps(legacy).encode(), message.type
        nats_wire = nats_transport._serialize(message)
        assert nats_wire == legacy and list(nats_wire) == _LEGACY_MEMBERS, message.type
        assert zmq_transport._deserialize(zmq_transport._serialize(message)) == message, message.type
        assert nats_transport._deserialize(json.loads(json.dumps(nats_wire))) == message, message.type


def test_m0_federation_message_keeps_its_legacy_fields_and_repr() -> None:
    fields = {field.name: field for field in dataclasses.fields(FederationMessage)}
    assert list(fields)[:5] == _LEGACY_MEMBERS
    for required in ("type", "source_node"):
        assert fields[required].default is dataclasses.MISSING
        assert fields[required].default_factory is dataclasses.MISSING
    assert fields["message_id"].default is dataclasses.MISSING
    assert re.fullmatch(r"[0-9a-f]{32}", fields["message_id"].default_factory())
    assert fields["payload"].default_factory() == {}
    assert fields["timestamp"].default == 0.0
    message = FederationMessage(type="ping", source_node="a", message_id="m", payload={}, timestamp=1.0)
    assert repr(message) == "FederationMessage(type='ping', source_node='a', message_id='m', payload={}, timestamp=1.0)"


async def test_m0_off_fleet_organization_returns_the_raw_transport() -> None:
    bus = MockNATSBus()
    await bus.start()
    result = None
    try:
        result = await organize_fleet(
            config=_off_system_config("node-a"),
            pools={},
            pool_groups=PoolGroupRegistry(),
            escalation_manager=SimpleNamespace(),
            intent_bus=IntentBus(SignalManager()),
            trust_network=SimpleNamespace(),
            llm_client=SimpleNamespace(),
            build_pool_intent_map_fn=dict,
            find_consensus_pools_fn=set,
            build_self_model_fn=lambda: NodeSelfModel(node_id="node-a"),
            validate_remote_result_fn=None,
            attachment_resolver_fn=None,
            nats_bus=bus,
        )
        assert result.federation_bridge is not None
        assert type(result.federation_transport) is NATSFederationTransport
    finally:
        if result is not None and result.federation_bridge is not None:
            await result.federation_bridge.stop()
        if result is not None and result.federation_transport is not None:
            await result.federation_transport.stop()
        await bus.stop()


# --------------------------------------------------------------------------- #
# Doubles and helpers (M1-M2)
# --------------------------------------------------------------------------- #


class _Wire:
    """A MockTransportBus whose deliveries are recorded and can be held back.

    ``inject`` delivers a captured or forged message exactly as the bus does.
    """

    def __init__(self) -> None:
        self.bus = MockTransportBus()
        self.sent: list[tuple[str, FederationMessage]] = []
        self.hold = False
        self._deliver = self.bus.deliver

        async def _recording_deliver(target: str, message: FederationMessage) -> None:
            self.sent.append((target, message))
            if not self.hold:
                await self._deliver(target, message)

        self.bus.deliver = _recording_deliver  # type: ignore[method-assign]

    async def inject(self, target: str, message: FederationMessage) -> None:
        await self._deliver(target, message)


class _RecordingIntentBus:
    """The two intent-bus members FederationBridge uses for an inbound request; records each broadcast."""

    def __init__(self, node: str) -> None:
        self.node = node
        self.broadcasts: list[IntentMessage] = []

    def candidate_agent_ids(self, intent_name: str) -> set[str]:
        return {f"{self.node}-agent"}

    async def broadcast(
        self, intent: IntentMessage, *, timeout: Any = None, federated: bool = True, raise_on_denial: bool = False,
    ) -> list[IntentResult]:
        self.broadcasts.append(intent)
        return [IntentResult(
            intent_id=intent.id, agent_id=f"{self.node}-agent", success=True, result=f"done by {self.node}",
            confidence=0.9,
        )]


@dataclass
class _Node:
    """One armed node wired by hand: binding, mock transport, store, guard and wrapper."""

    name: str
    binding: IdentityKeyBinding
    registry: AgentIdentityRegistry
    duck: _DuckKeyring
    inner: MockFederationTransport
    data_dir: Path
    guard: EnvelopeGuard
    transport: SignedFederationTransport
    dispatched: list[FederationMessage] = field(default_factory=list)
    signer: Any = None
    key_store: Any = None

    @property
    def store_path(self) -> Path:
        return self.data_dir / ENVELOPE_DB_NAME


async def _wrap(
    stack: contextlib.AsyncExitStack,
    name: str,
    inner: MockFederationTransport,
    binding: IdentityKeyBinding,
    data_dir: Path,
    dispatched: list[FederationMessage],
    *,
    policy: str,
    connection_factory: Any = None,
    signer: Any = None,
) -> tuple[EnvelopeGuard, SignedFederationTransport]:
    store = EnvelopeStore(data_dir / ENVELOPE_DB_NAME, connection_factory=connection_factory)
    guard = EnvelopeGuard(
        signer=binding if signer is None else signer, store=store, local_node_id=name, policy=policy,
    )
    transport = SignedFederationTransport(inner, guard)

    async def _dispatch(message: FederationMessage) -> None:
        dispatched.append(message)

    transport._inbound_handler = _dispatch  # the handler contract the bridge itself uses (bridge.py:1054)
    stack.push_async_callback(transport.stop)
    await transport.start()
    return guard, transport


async def _node(
    stack: contextlib.AsyncExitStack,
    wire: _Wire,
    tmp: Path,
    name: str,
    *,
    policy: str = POLICY_REQUIRE,
    recovery_public_key: str = "",
    connection_factory: Any = None,
    signer: Callable[[IdentityKeyBinding], Any] | None = None,
    key_store: Callable[[Any], Any] | None = None,
) -> _Node:
    duck = _DuckKeyring()
    store = None if key_store is None else key_store(KeyringKeyStore(backend=duck))
    registry, binding = await stack.enter_async_context(_armed(
        tmp / f"{name}-identity", duck, recovery_public_key=recovery_public_key,
        instance_id=name.replace("node", "ship"), store=store,
    ))
    assert binding.key_status == STATUS_ACTIVE  # premise: commissioned, so the ship key signs
    data_dir = tmp / f"{name}-data"
    data_dir.mkdir()
    inner = MockFederationTransport(name, wire.bus)
    dispatched: list[FederationMessage] = []
    guard_signer = None if signer is None else signer(binding)
    guard, transport = await _wrap(
        stack, name, inner, binding, data_dir, dispatched, policy=policy, connection_factory=connection_factory,
        signer=guard_signer,
    )
    return _Node(
        name, binding, registry, duck, inner, data_dir, guard, transport, dispatched, signer=guard_signer,
        key_store=store,
    )


async def _restart(stack: contextlib.AsyncExitStack, node: _Node, *, policy: str = POLICY_REQUIRE) -> None:
    """Stop the node's wrapper and start a new guard, store and wrapper on the same store file."""
    await node.transport.stop()
    node.guard, node.transport = await _wrap(
        stack, node.name, node.inner, node.binding, node.data_dir, node.dispatched, policy=policy,
    )


async def _seal(
    node: _Node,
    target: str,
    *,
    kind: str = "intent_request",
    payload: dict[str, Any] | None = None,
    timestamp: float = 1.0,
) -> FederationMessage:
    message = FederationMessage(
        type=kind, source_node=node.name, payload=copy.deepcopy(_REQUEST if payload is None else payload),
        timestamp=timestamp,
    )
    sealed = await node.guard.seal(message, target)
    assert sealed is not None and sealed.auth is not None, "premise: the ship key signs"
    return sealed


async def _active_key(binding: IdentityKeyBinding) -> tuple[str, str]:
    status = await binding.status()
    kid = status["active_kid"]
    return kid, next(key["public_key"] for key in status["keys"] if key["kid"] == kid)


async def _history(binding: IdentityKeyBinding) -> tuple[KeyEvent, ...]:
    signature = await binding.sign_envelope(lambda state: {"probe": state.seq})
    assert signature is not None
    return signature.key_events


def _statement_bytes(message: FederationMessage, auth: dict[str, Any]) -> bytes:
    return canonical_bytes(envelope_statement(
        message, target=auth["target"], epoch=auth["epoch"], seq=auth["seq"], key_seq=auth["key_seq"],
        key_head=auth["key_head"], body_sha256=body_digest(message.payload),
    ))


def _signature_verifies(message: FederationMessage, *, public_key: str, kid: str) -> bool:
    assert message.auth is not None
    return verify_signature_for(
        message.auth["jws"], _statement_bytes(message, message.auth), public_key_b64=public_key, kid=kid,
        typ=ENVELOPE_JWS_TYP,
    )


def _forge(
    message: FederationMessage,
    *,
    target: str,
    epoch: int,
    seq: int,
    key_seq: int,
    key_head: str,
    key_events: list[dict[str, Any]],
    private_key: Any,
    kid: str,
) -> FederationMessage:
    """An envelope signed by any private key over a statement naming any key state."""
    auth: dict[str, Any] = {
        "v": 1, "target": target, "epoch": epoch, "seq": seq, "key_seq": key_seq, "key_head": key_head,
        "jws": "", "key_events": copy.deepcopy(key_events),
    }
    auth["jws"] = sign_with(
        _statement_bytes(message, auth), kid=kid, typ=ENVELOPE_JWS_TYP,
        sign=lambda text: sign_challenge(private_key, text),
    )
    return dataclasses.replace(message, auth=auth)


def _rejections(caplog: pytest.LogCaptureFixture) -> list[tuple[Any, ...]]:
    return [
        tuple(record.args)  # type: ignore[arg-type]
        for record in caplog.records
        if record.name == _ENVELOPE_LOGGER and record.msg == _REJECTED
    ]


def _rows(db_path: Path) -> dict[str, list[tuple[Any, ...]]]:
    with contextlib.closing(sqlite3.connect(db_path)) as db:
        return {
            "senders": db.execute(
                "SELECT source_node, did, key_seq, key_head FROM envelope_senders ORDER BY source_node"
            ).fetchall(),
            "windows": db.execute(
                "SELECT source_node, channel, key_seq, epoch, hwm, mask FROM envelope_windows "
                "ORDER BY source_node, channel"
            ).fetchall(),
            "epoch": db.execute("SELECT epoch FROM envelope_send_epoch").fetchall(),
        }


def _calls_and_imports(path: Path) -> tuple[set[str], set[str]]:
    calls: set[str] = set()
    imports: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
            elif isinstance(node.func, ast.Name):
                calls.add(node.func.id)
    return calls, imports


# --------------------------------------------------------------------------- #
# M1 -- the thin real chain
# --------------------------------------------------------------------------- #


async def test_m1_thin_chain_signs_verifies_and_refuses_a_replay_and_an_altered_field(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        nodes: dict[str, tuple[SignedFederationTransport, FederationBridge, _RecordingIntentBus, Path]] = {}
        for name in ("node-a", "node-b"):
            _, binding = await stack.enter_async_context(
                _armed(tmp_path / f"{name}-identity", _DuckKeyring(), instance_id=name.replace("node", "ship")),
            )
            assert binding.key_status == STATUS_ACTIVE  # premise: both ships are commissioned and armed
            data_dir = tmp_path / f"{name}-data"
            data_dir.mkdir()
            transport = build_signed_transport(
                MockFederationTransport(name, wire.bus), policy=POLICY_REQUIRE, key_binding=binding,
                data_dir=data_dir,
            )
            stack.push_async_callback(transport.stop)
            await transport.start()
            bus = _RecordingIntentBus(name)
            bridge = FederationBridge(
                node_id=name, transport=transport, router=FederationRouter(), intent_bus=bus,
                config=FederationConfig(
                    enabled=True, node_id=name, forward_timeout_ms=500, gossip_interval_seconds=100,
                ),
                self_model_fn=lambda: NodeSelfModel(node_id="unused"),
            )
            stack.push_async_callback(bridge.stop)
            await bridge.start()
            nodes[name] = (transport, bridge, bus, data_dir)
        a_transport, a_bridge, _, a_dir = nodes["node-a"]
        _, _, b_bus, b_dir = nodes["node-b"]

        results = await a_bridge.forward_intent(IntentMessage(intent="read_file", params={"path": "/a"}))

        assert [result.agent_id for result in results] == ["node-b-agent"]
        assert len(b_bus.broadcasts) == 1
        requests = [message for target, message in wire.sent if target == "node-b"]
        responses = [message for target, message in wire.sent if target == "node-a"]
        assert [message.type for message in requests] == ["intent_request"]
        assert [message.type for message in responses] == ["intent_response"]
        assert requests[0].auth is not None and requests[0].auth["target"] == "node-b"
        assert responses[0].auth is not None and responses[0].auth["target"] == "node-a"
        for data_dir, peer in ((a_dir, "node-b"), (b_dir, "node-a")):
            rows = _rows(data_dir / ENVELOPE_DB_NAME)
            assert [row[0] for row in rows["senders"]] == [peer]
            assert [row[:2] for row in rows["windows"]] == [(peer, "direct")]
            assert rows["epoch"] == [(1,)]
        assert _rejections(caplog) == []

        await wire.inject("node-b", requests[0])  # a replay of the accepted request

        assert len(b_bus.broadcasts) == 1
        assert _rejections(caplog) == [("intent_request", "node-a", "duplicate")]

        wire.hold = True
        await a_transport.send_to_peer("node-b", FederationMessage(
            type="intent_request", source_node="node-a",
            payload={"intent": "read_file", "params": {"path": "/b"}, "id": "i-2"}, timestamp=2.0,
        ))
        wire.hold = False
        fresh = wire.sent[-1][1]
        assert fresh.auth is not None and len(b_bus.broadcasts) == 1  # premise: sealed, not yet delivered

        await wire.inject("node-b", dataclasses.replace(fresh, payload={**fresh.payload, "intent": "delete_file"}))

        assert len(b_bus.broadcasts) == 1
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "signature")
        await wire.inject("node-b", fresh)  # premise: the unaltered envelope is then dispatched
        assert len(b_bus.broadcasts) == 2 and b_bus.broadcasts[-1].id == "i-2"


async def test_sign_envelope_signs_with_the_active_key_and_returns_its_history(tmp_path: Path) -> None:
    seen: list[KeyState] = []

    def statement_for(state: KeyState) -> dict[str, Any]:
        seen.append(state)
        return {"type": "probe", "head": state.head_digest}

    async with _armed(tmp_path / "ship", _DuckKeyring()) as (registry, binding):
        signature = await binding.sign_envelope(statement_for)
        status = await binding.status()
        chain = await registry.export_chain()

    assert signature is not None
    assert signature.kid == status["active_kid"] == signature.state.active_kid
    assert seen == [signature.state]
    anchored = tuple(
        KeyEvent(
            index=block["index"], payload=block["attestation"]["event"],
            signatures=block["attestation"]["signatures"], digest=block["certificate_hash"],
        )
        for block in chain
        if (block.get("attestation") or {}).get("kind") == "key_event"
    )
    assert signature.key_events == anchored and len(anchored) == status["seq"] + 1
    payload = canonical_bytes({"type": "probe", "head": signature.state.head_digest})
    public_key = signature.state.active.public_key
    assert verify_signature_for(
        signature.jws, payload, public_key_b64=public_key, kid=signature.kid, typ=ENVELOPE_JWS_TYP,
    )
    parsed = parse_detached(signature.jws, expected_typ=ENVELOPE_JWS_TYP)
    assert parsed is not None and set(parsed.header) == {"alg", "kid", "typ"}
    for other_typ in (KEY_EVENT_JWS_TYP, VC_JWS_TYP):  # domain separation
        assert not verify_signature_for(
            signature.jws, payload, public_key_b64=public_key, kid=signature.kid, typ=other_typ,
        )


def test_m1_envelope_modules_reuse_rfc8785_and_jws_and_add_no_signing_stack() -> None:
    envelope_imports = {
        (node.module, alias.name)
        for node in ast.walk(ast.parse(_ENVELOPE_MODULE.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert ("probos.federation.ard.jcs", "canonicalize") in envelope_imports
    assert ("probos.federation.ard.jws", "parse_detached") in envelope_imports
    foreign_stacks = {"cryptography", "nacl", "jose", "jwt", "hmac"}
    signing_primitives = {
        "sign_challenge", "sign_with", "_sign_detached", "compact_detached", "encode_protected_header",
        "signing_input", "Ed25519PrivateKey", "decode_private_key", "generate_keypair",
    }
    for path in (_ENVELOPE_MODULE, _SIGNED_TRANSPORT_MODULE, _STORE_MODULE):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        named: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {alias.name.split(".")[0] for alias in node.names} & foreign_stacks, path.name
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in foreign_stacks, path.name
                named.update(alias.name for alias in node.names)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                named.add(node.name)
                assert node.name != "canonicalize", path.name
            elif isinstance(node, ast.Name):
                named.add(node.id)
            elif isinstance(node, ast.Attribute):
                named.add(node.attr)
        assert not named & signing_primitives, (path.name, sorted(named & signing_primitives))


# --------------------------------------------------------------------------- #
# M2 -- verification, replay, holds, store
# --------------------------------------------------------------------------- #

_ALTERED_REASONS = {
    "payload_value": "signature",
    "payload_member_added": "signature",
    "payload_member_removed": "signature",
    "topic": "signature",
    "source_node": "signature",
    "message_id": "signature",
    "timestamp": "signature",
    "auth_target": "target",
    "auth_epoch": "signature",
    "auth_seq": "signature",
    "auth_key_seq": "stale key",  # A-1: a run shorter than key_seq + 1 is a valid suffix, so a raised key_seq is caught by the key-state check
    "auth_key_head": "stale key",
    "auth_jws_signature_bit": "signature",
    "auth_jws_kid_swapped": "signature",
    "auth_header_extra_member": "header",
    "auth_extra_member": "malformed",
    "auth_key_events_other_did": "stale key",
    "auth_version": "malformed",
}


async def _altered(case: str, sealed: FederationMessage, node: _Node, other_history: list[dict[str, Any]]) -> FederationMessage:
    """``sealed`` with exactly one member changed, as an attacker on the path would change it."""
    auth = dict(sealed.auth or {})
    payload = copy.deepcopy(sealed.payload)
    if case == "payload_value":
        payload["params"]["path"] = "/etc/passwd"
        return dataclasses.replace(sealed, payload=payload)
    if case == "payload_member_added":
        payload["urgency"] = 0.9
        return dataclasses.replace(sealed, payload=payload)
    if case == "payload_member_removed":
        del payload["id"]
        return dataclasses.replace(sealed, payload=payload)
    if case == "topic":
        return dataclasses.replace(sealed, type="chain_request")  # a topic verified before dispatch
    if case == "source_node":
        return dataclasses.replace(sealed, source_node="node-c")
    if case == "message_id":
        return dataclasses.replace(sealed, message_id="f" * 32)
    if case == "timestamp":
        return dataclasses.replace(sealed, timestamp=sealed.timestamp + 1.0)
    protected, _, signature = auth["jws"].partition("..")
    if case == "auth_target":
        auth["target"] = "node-c"
    elif case in ("auth_epoch", "auth_seq", "auth_key_seq"):
        member = case.removeprefix("auth_")
        auth[member] += 1
    elif case == "auth_key_head":
        auth["key_head"] = "0" * 64
        assert sealed.auth is not None and sealed.auth["key_head"] != auth["key_head"]
    elif case == "auth_jws_signature_bit":
        auth["jws"] = f"{protected}..{'B' if signature[0] == 'A' else 'A'}{signature[1:]}"
    elif case == "auth_jws_kid_swapped":
        other = encode_protected_header({"alg": JWS_ALG, "kid": "did:probos:ship-x#key-0000000000000000", "typ": ENVELOPE_JWS_TYP})
        auth["jws"] = f"{other}..{signature}"
    elif case == "auth_header_extra_member":
        kid, public_key = await _active_key(node.binding)
        private_key = decode_private_key(node.duck.secret(kid))
        statement = _statement_bytes(sealed, auth)
        auth["jws"] = sign_with(
            statement, kid=kid, typ=ENVELOPE_JWS_TYP, sign=lambda text: sign_challenge(private_key, text),
            claims={"nonce": 7},
        )
        assert verify_signature_for(  # premise: the re-signed token is a valid signature by the real key
            auth["jws"], statement, public_key_b64=public_key, kid=kid, typ=ENVELOPE_JWS_TYP,
        )
    elif case == "auth_extra_member":
        auth["note"] = "unsigned"
    elif case == "auth_key_events_other_did":
        assert len(other_history) == len(auth["key_events"]) and other_history != auth["key_events"]
        auth["key_events"] = other_history
    elif case == "auth_version":
        auth["v"] = 2
    else:  # pragma: no cover - the parametrisation names every case
        raise AssertionError(case)
    return dataclasses.replace(sealed, auth=auth)


@pytest.mark.parametrize("case", sorted(_ALTERED_REASONS))
async def test_altered_field_is_rejected(case: str, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        other_history: list[dict[str, Any]] = []
        if case == "auth_key_events_other_did":
            _, other = await stack.enter_async_context(_armed(tmp_path / "x-identity", _DuckKeyring(), instance_id="ship-x"))
            other_history = key_events_to_wire(await _history(other))
        sealed = await _seal(a, "node-b")
        altered = await _altered(case, sealed, a, other_history)
        assert altered != sealed  # premise: one member really changed

        await wire.inject("node-b", altered)

        assert b.dispatched == []
        assert _rejections(caplog) == [(altered.type, altered.source_node, _ALTERED_REASONS[case])]
        await wire.inject("node-b", sealed)  # premise: the unaltered envelope is accepted
        assert b.dispatched == [sealed]


async def test_target_confusion_is_rejected(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        c = await _node(stack, wire, tmp_path, "node-c")

        for_b = await _seal(a, "node-b")
        await wire.inject("node-c", for_b)
        assert c.dispatched == [] and _rejections(caplog)[-1] == ("intent_request", "node-a", "target")
        await wire.inject("node-b", for_b)
        assert b.dispatched == [for_b]  # premise: delivered to its target, the same envelope is accepted

        second = await _seal(a, "node-b")
        assert second.auth is not None
        await wire.inject("node-c", dataclasses.replace(second, auth={**second.auth, "target": "node-c"}))
        assert c.dispatched == [] and _rejections(caplog)[-1] == ("intent_request", "node-a", "signature")
        await wire.inject("node-b", second)
        assert b.dispatched == [for_b, second]

        broadcast_request = await _seal(a, BROADCAST)
        await wire.inject("node-b", broadcast_request)
        assert b.dispatched == [for_b, second]
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "target")

        gossip = await _seal(a, BROADCAST, kind="gossip_self_model", payload={"node_id": "node-a"})
        await wire.inject("node-b", gossip)
        await wire.inject("node-c", gossip)
        assert b.dispatched == [for_b, second, gossip] and c.dispatched == [gossip]


async def test_reflected_envelope_is_rejected(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        gossip = await _seal(a, BROADCAST, kind="gossip_self_model", payload={"node_id": "node-a"})
        await wire.inject("node-b", gossip)
        assert b.dispatched == [gossip]  # premise: it verifies and is admitted as a first contact

        await wire.inject("node-a", gossip)

        assert a.dispatched == []
        assert _rejections(caplog) == [("gossip_self_model", "node-a", "reflected")]


async def test_keeps_held_key_events_contract(tmp_path: Path) -> None:
    async with contextlib.AsyncExitStack() as stack:
        _, rotating = await stack.enter_async_context(_armed(tmp_path / "a", _DuckKeyring(), instance_id="ship-a"))
        before = await _history(rotating)
        await rotating.rotate()
        after = await _history(rotating)
        for _ in range(3):
            await rotating.rotate()
        five = await _history(rotating)
        _, reincepting = await stack.enter_async_context(_armed(tmp_path / "b", _DuckKeyring(), instance_id="ship-b"))
        root = await _history(reincepting)
        await reincepting.reincept(reason="lost", compromised_after_index=None)
        reincepted = await _history(reincepting)
    assert len(before) == 1 and after[:1] == before and len(after) == 2  # premise: a rotation appends
    assert five[:2] == after and [event.payload["seq"] for event in five] == [0, 1, 2, 3, 4]
    assert reincepted[:1] == root and reincepted[1].payload["event"] == EVENT_REINCEPTION

    assert keeps_held_key_events((), (), carried_head=0) == (True, "keeps")
    assert keeps_held_key_events((), after, carried_head=1) == (True, "keeps")
    assert keeps_held_key_events(before, after, carried_head=1) == (True, "keeps")
    assert keeps_held_key_events(after, after, carried_head=1) == (True, "keeps")
    assert keeps_held_key_events(after, before, carried_head=0) == (False, "stale key")
    changed = (dataclasses.replace(after[0], signatures={"new": after[1].signatures["new"]}), after[1])
    assert keeps_held_key_events(after, changed, carried_head=1) == (False, "held history")
    assert keeps_held_key_events(before, root, carried_head=0) == (False, "held history")  # a fork: another inception
    assert keeps_held_key_events(root, reincepted, carried_head=1) == (False, "held history")
    assert keeps_held_key_events((), reincepted, carried_head=1) == (True, "keeps")  # nothing held: trust on first use

    # A-1: both runs end at their heads and are aligned by seq.
    assert keeps_held_key_events(five[:2], five[3:], carried_head=4) == (False, "key history gap")
    assert keeps_held_key_events(five[:2], five[2:], carried_head=4) == (True, "keeps")  # starts at the held head + 1
    assert keeps_held_key_events(five[2:4], five[1:], carried_head=4) == (True, "keeps")  # held from seq 2
    assert keeps_held_key_events(five[2:4], five, carried_head=4) == (True, "keeps")  # carried from before the held run
    unheld_changed = (five[0], dataclasses.replace(five[1], signatures={"new": five[2].signatures["new"]}), *five[2:])
    assert keeps_held_key_events(five[2:4], unheld_changed, carried_head=4) == (True, "keeps")  # only the overlap
    assert keeps_held_key_events(five[2:4], five[:3], carried_head=2) == (False, "stale key")  # an older head
    overlap_changed = (five[1], dataclasses.replace(five[2], signatures={"new": five[3].signatures["new"]}), *five[3:])
    assert keeps_held_key_events(five[2:4], overlap_changed, carried_head=4) == (False, "held history")


class _DictSubclass(dict):  # type: ignore[type-arg]
    pass


async def test_parse_auth_contract(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        sealed = await _seal(a, "node-b")
    auth = sealed.auth
    assert auth is not None
    item = auth["key_events"][0]

    def with_(**changes: Any) -> dict[str, Any]:
        return {**auth, **changes}

    def items(count: int) -> list[dict[str, Any]]:
        return [{**copy.deepcopy(item), "index": item["index"] + offset} for offset in range(count)]

    assert parse_auth(auth) == EnvelopeAuth(
        target="node-b", epoch=auth["epoch"], seq=auth["seq"], key_seq=0, key_head=auth["key_head"],
        jws=auth["jws"], key_events=tuple(auth["key_events"]),
    )
    cyclic = dict(auth)
    cyclic["jws"] = cyclic
    too_many = with_(key_events=items(MAX_KEY_EVENTS + 1), key_seq=MAX_KEY_EVENTS)
    assert len(json.dumps(too_many)) <= MAX_AUTH_BYTES  # premise: only the count rule refuses it
    assert auth["key_head"] != auth["key_head"].upper()  # premise: the digest has letters to upper-case
    refused: list[tuple[str, object]] = [
        ("none", None),
        ("list", [auth]),
        ("dict subclass", _DictSubclass(auth)),
        ("missing member", {key: value for key, value in auth.items() if key != "seq"}),
        ("extra member", with_(note="x")),
        ("not JSON", with_(jws=object())),
        ("self-referencing", cyclic),
        ("oversized", with_(key_events=[{**item, "event": {**item["event"], "pad": "x" * MAX_AUTH_BYTES}}])),
        ("version 2", with_(v=2)),
        ("version bool", with_(v=True)),
        ("version str", with_(v="1")),
        ("empty target", with_(target="")),
        ("long target", with_(target="n" * 257)),
        ("target not str", with_(target=5)),
        ("epoch 0", with_(epoch=0)),
        ("epoch beyond 2**53-1", with_(epoch=MAX_SEQUENCE + 1)),
        ("epoch bool", with_(epoch=True)),
        ("epoch float", with_(epoch=1.0)),
        ("seq 0", with_(seq=0)),
        ("seq beyond 2**53-1", with_(seq=MAX_SEQUENCE + 1)),
        ("seq bool", with_(seq=True)),
        ("seq str", with_(seq="1")),
        ("key_seq negative", with_(key_seq=-1)),
        ("key_seq bool", with_(key_seq=False)),
        ("key_seq beyond 2**53-1", with_(key_seq=MAX_SEQUENCE + 1)),
        ("key_head short", with_(key_head=auth["key_head"][:63])),
        ("key_head upper case", with_(key_head=auth["key_head"].upper())),
        ("key_head not hex", with_(key_head="g" * 64)),
        ("key_head not str", with_(key_head=7)),
        ("jws too long", with_(jws="x" * 4097)),
        ("jws not str", with_(jws=b"x")),
        ("key_events not a list", with_(key_events=tuple(auth["key_events"]))),
        ("no key events", with_(key_events=[])),
        ("33 key events", too_many),
        ("more events than key_seq + 1", with_(key_events=items(2))),
        ("item not a dict", with_(key_events=["x"])),
        ("item missing member", with_(key_events=[{k: v for k, v in item.items() if k != "signatures"}])),
        ("item extra member", with_(key_events=[{**item, "x": 1}])),
        ("index zero", with_(key_events=[{**item, "index": 0}])),
        ("index str", with_(key_events=[{**item, "index": "1"}])),
        ("index bool", with_(key_events=[{**item, "index": True}])),
        ("event not a dict", with_(key_events=[{**item, "event": []}])),
        ("signatures not a dict", with_(key_events=[{**item, "signatures": "x"}])),
    ]
    for label, value in refused:
        assert parse_auth(value) is None, label

    padded = copy.deepcopy(item)
    padded["event"]["pad"] = ""
    padded["event"]["pad"] = "x" * (MAX_AUTH_BYTES - len(json.dumps(with_(key_events=[padded]))))
    at_limit = with_(key_events=[padded])
    assert len(json.dumps(at_limit)) == MAX_AUTH_BYTES
    over = copy.deepcopy(at_limit)
    over["key_events"][0]["event"]["pad"] += "x"
    accepted = [
        at_limit,
        with_(epoch=MAX_SEQUENCE, seq=MAX_SEQUENCE),
        with_(target="n" * 256),
        with_(jws="x" * 4096),
        with_(key_events=items(MAX_KEY_EVENTS), key_seq=MAX_KEY_EVENTS - 1),
        with_(key_seq=40),  # a suffix: one event under key_seq 40
        with_(key_seq=MAX_SEQUENCE),  # key_seq 2**53-1 with one event
    ]
    for value in accepted:
        assert parse_auth(value) is not None
    assert parse_auth(over) is None


async def test_duplicate_message_is_rejected(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        request = await _seal(a, "node-b")
        await wire.inject("node-b", request)
        assert b.dispatched == [request]  # premise: the first delivery is dispatched

        await wire.inject("node-b", request)

        assert b.dispatched == [request]
        assert _rejections(caplog) == [("intent_request", "node-a", "duplicate")]

        first = await _seal(b, "node-a", kind="intent_response", payload={"results": [], "admitted": True})
        await a.transport.deliver_response("node-b", first)
        assert await a.transport.receive_with_timeout("node-b", 500) is first
        genuine = await _seal(b, "node-a", kind="intent_response", payload={"results": [], "admitted": False})
        await a.transport.deliver_response("node-b", first)  # the replay, queued ahead of the genuine response
        await a.transport.deliver_response("node-b", genuine)

        taken = await a.transport.receive_with_timeout("node-b", 500)

        assert taken is genuine
        assert _rejections(caplog)[-1] == ("intent_response", "node-b", "duplicate")


async def test_replay_window_accepts_reordering_and_refuses_what_falls_out(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    window = StoredWindow
    assert advance_window(None, 0, 1, 5) == (window(0, 1, 5, 1), "fresh")
    assert advance_window(window(0, 1, 9, 0b111), 0, 2, 1) == (window(0, 2, 1, 1), "fresh")
    assert advance_window(window(0, 5, 9, 0b111), 1, 1, 1) == (window(1, 1, 1, 1), "fresh")
    assert advance_window(window(1, 1, 9, 1), 0, 9, 50) == (None, "stale key")
    assert advance_window(window(0, 2, 9, 1), 0, 1, 50) == (None, "stale epoch")
    assert advance_window(window(0, 1, 5, 0b1), 0, 1, 7) == (window(0, 1, 7, 0b101), "advanced")
    assert advance_window(window(0, 1, 5, 0b1), 0, 1, 5 + REPLAY_WINDOW - 1) == (
        window(0, 1, 5 + REPLAY_WINDOW - 1, (1 << 63) | 1), "advanced",
    )
    assert advance_window(window(0, 1, 5, 0b11111), 0, 1, 5 + REPLAY_WINDOW) == (
        window(0, 1, 5 + REPLAY_WINDOW, 1), "advanced",
    )
    assert advance_window(window(0, 1, 70, 1), 0, 1, 6) == (None, "too old")
    assert advance_window(window(0, 1, 70, 1), 0, 1, 7) == (window(0, 1, 70, 1 | (1 << 63)), "filled")
    assert advance_window(window(0, 1, 10, 0b101), 0, 1, 8) == (None, "duplicate")
    assert advance_window(window(0, 1, 10, 0b001), 0, 1, 8) == (window(0, 1, 10, 0b101), "filled")

    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        sealed = {}
        for _ in range(70):
            message = await _seal(a, "node-b")
            assert message.auth is not None
            sealed[message.auth["seq"]] = message
        assert sorted(sealed) == list(range(1, 71))  # premise: one global sequence, 1..70

        for seq in (5, 3, 4):
            await wire.inject("node-b", sealed[seq])
        assert b.dispatched == [sealed[5], sealed[3], sealed[4]]
        await wire.inject("node-b", sealed[3])
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "duplicate")
        await wire.inject("node-b", sealed[70])
        await wire.inject("node-b", sealed[6])  # never delivered, but 64 behind
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "too old")
        await wire.inject("node-b", sealed[7])  # never delivered, and just inside the window
        await wire.inject("node-b", sealed[5])
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "too old")
        assert b.dispatched == [sealed[5], sealed[3], sealed[4], sealed[70], sealed[7]]


async def test_sender_restart_starts_a_new_epoch_and_old_epochs_are_refused(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        first = await _seal(a, "node-b")
        unseen = await _seal(a, "node-b")
        assert first.auth is not None and unseen.auth is not None
        assert (first.auth["epoch"], first.auth["seq"], unseen.auth["seq"]) == (1, 1, 2)
        await wire.inject("node-b", first)

        await _restart(stack, a)

        assert _rows(a.store_path)["epoch"] == [(2,)]
        restarted = await _seal(a, "node-b")
        assert restarted.auth is not None and (restarted.auth["epoch"], restarted.auth["seq"]) == (2, 1)
        await wire.inject("node-b", restarted)
        assert b.dispatched == [first, restarted]
        kid, public_key = await _active_key(a.binding)
        assert _signature_verifies(unseen, public_key=public_key, kid=kid)  # premise: genuine and never seen
        await wire.inject("node-b", unseen)
        assert b.dispatched == [first, restarted]
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "stale epoch")


async def test_replay_state_and_holds_survive_a_receiver_restart(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b", policy=POLICY_SIGN)
        first = await _seal(a, "node-b")
        await wire.inject("node-b", first)
        assert b.dispatched == [first]

        await _restart(stack, b, policy=POLICY_SIGN)

        await wire.inject("node-b", first)
        assert b.dispatched == [first]
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "duplicate")
        unsigned = FederationMessage(
            type="intent_request", source_node="node-a", payload=copy.deepcopy(_REQUEST), timestamp=1.0,
        )
        await wire.inject("node-b", unsigned)
        assert b.dispatched == [first]
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "downgrade")
        never_signed = dataclasses.replace(unsigned, source_node="node-z")
        await wire.inject("node-b", never_signed)
        assert b.dispatched == [first, never_signed]  # premise: 'sign' accepts a sender never seen signing


async def test_stale_key_after_rotation_is_rejected(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        first = await _seal(a, "node-b")
        await wire.inject("node-b", first)
        old_kid, old_public_key = await _active_key(a.binding)
        await a.binding.rotate()
        new_kid, _ = await _active_key(a.binding)
        assert new_kid != old_kid
        learn = await _seal(a, "node-b")
        assert learn.auth is not None and first.auth is not None and learn.auth["key_seq"] == 1
        await wire.inject("node-b", learn)
        assert b.dispatched == [first, learn]  # B learned the rotation from A's next envelope
        stale = _forge(
            FederationMessage(type="intent_request", source_node="node-a", payload={"id": "k1"}, timestamp=1.0),
            target="node-b", epoch=learn.auth["epoch"], seq=learn.auth["seq"] + 1,
            key_seq=first.auth["key_seq"], key_head=first.auth["key_head"], key_events=first.auth["key_events"],
            private_key=decode_private_key(a.duck.secret(old_kid)), kid=old_kid,
        )
        assert _signature_verifies(stale, public_key=old_public_key, kid=old_kid)  # premise: K1's signature

        await wire.inject("node-b", stale)

        assert b.dispatched == [first, learn]
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "stale key")


async def test_stale_key_after_compromise_recovery_is_rejected(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    recovery_private, recovery_public = generate_recovery_keypair()
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a", recovery_public_key=recovery_public)
        b = await _node(stack, wire, tmp_path, "node-b")
        first = await _seal(a, "node-b")
        await wire.inject("node-b", first)
        old_kid, old_public_key = await _active_key(a.binding)
        activated = (await a.binding.status())["keys"][0]["activated_at"]
        prepared = await a.binding.prepare_recovery(
            reason="compromised", compromised_after_index=activated, next_recovery_public_key="",
        )
        await a.binding.apply_recovery(
            authorization=sign_recovery_authorization(recovery_private, prepared["signing_payload"]),
            reason="compromised", compromised_after_index=activated, next_recovery_public_key="",
        )
        assert a.binding.key_status == STATUS_ACTIVE and (await _active_key(a.binding))[0] != old_kid
        learn = await _seal(a, "node-b")
        assert learn.auth is not None and first.auth is not None
        assert learn.auth["key_events"][-1]["event"]["event"] == EVENT_RECOVERY
        await wire.inject("node-b", learn)
        assert b.dispatched == [first, learn]  # B learned the recovery
        stale = _forge(
            FederationMessage(type="intent_request", source_node="node-a", payload={"id": "k1"}, timestamp=1.0),
            target="node-b", epoch=learn.auth["epoch"], seq=learn.auth["seq"] + 1,
            key_seq=first.auth["key_seq"], key_head=first.auth["key_head"], key_events=first.auth["key_events"],
            private_key=decode_private_key(a.duck.secret(old_kid)), kid=old_kid,
        )
        assert _signature_verifies(stale, public_key=old_public_key, kid=old_kid)  # premise: the replaced key signed

        await wire.inject("node-b", stale)

        assert b.dispatched == [first, learn]
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "stale key")


async def test_an_envelope_naming_another_key_state_is_rejected(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        first = await _seal(a, "node-b")
        await wire.inject("node-b", first)
        assert first.auth is not None
        message = FederationMessage(type="intent_request", source_node="node-a", payload={"id": "h1"}, timestamp=1.0)
        epoch, seq, bogus_head = first.auth["epoch"], first.auth["seq"] + 1, "0" * 64
        signature = await a.binding.sign_envelope(lambda state: envelope_statement(
            message, target="node-b", epoch=epoch, seq=seq, key_seq=state.seq, key_head=bogus_head,
            body_sha256=body_digest(message.payload),
        ))
        assert signature is not None and signature.state.head_digest != bogus_head
        named = dataclasses.replace(message, auth={
            "v": 1, "target": "node-b", "epoch": epoch, "seq": seq, "key_seq": signature.state.seq,
            "key_head": bogus_head, "jws": signature.jws, "key_events": key_events_to_wire(signature.key_events),
        })
        kid, public_key = await _active_key(a.binding)
        assert _signature_verifies(named, public_key=public_key, kid=kid)  # premise: a valid signature

        await wire.inject("node-b", named)

        assert b.dispatched == [first]
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "stale key")


async def test_clock_skewed_peer_is_accepted_and_orders_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        skewed = [await _seal(a, "node-b", timestamp=timestamp) for timestamp in (-1e9, 0.0, 9.9e15)]
        assert [message.auth["seq"] for message in skewed if message.auth] == [1, 2, 3]
        for message in skewed:
            await wire.inject("node-b", message)
        assert b.dispatched == skewed
        earlier = await _seal(a, "node-b", timestamp=-5e9)  # a lower timestamp under a higher sequence
        await wire.inject("node-b", earlier)
        assert b.dispatched == [*skewed, earlier]

        await wire.inject("node-b", skewed[2])

        assert b.dispatched == [*skewed, earlier]
        assert _rejections(caplog) == [("intent_request", "node-a", "duplicate")]


def test_envelope_verifier_and_store_read_no_clock() -> None:
    clock_calls = {"time", "monotonic", "perf_counter", "now", "utcnow", "today"}
    transport_calls, _ = _calls_and_imports(_SIGNED_TRANSPORT_MODULE)
    assert "time" in transport_calls  # premise: the scan sees a clock read where one exists (a local deadline)
    for path, marker in ((_ENVELOPE_MODULE, "derive_key_state"), (_STORE_MODULE, "execute")):
        calls, imports = _calls_and_imports(path)
        assert marker in calls, path.name  # premise: the scan reads this module's calls
        assert not {module.split(".")[0] for module in imports} & {"time", "datetime"}, path.name
        assert not calls & clock_calls, (path.name, sorted(calls & clock_calls))


async def test_held_history_fork_is_rejected(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        c = await _node(stack, wire, tmp_path, "node-c")
        held = await _seal(a, "node-b")
        await wire.inject("node-b", held)
        assert b.dispatched == [held]  # B now holds A's history
        _, fork_binding = await stack.enter_async_context(
            _armed(tmp_path / "fork-identity", _DuckKeyring(), instance_id="ship-a"),
        )
        fork_dir = tmp_path / "fork-data"
        fork_dir.mkdir()
        fork = EnvelopeGuard(
            signer=fork_binding, store=EnvelopeStore(fork_dir / ENVELOPE_DB_NAME), local_node_id="node-a",
            policy=POLICY_REQUIRE,
        )
        stack.push_async_callback(fork.stop)
        await fork.start()
        claim = FederationMessage(type="intent_request", source_node="node-a", payload={"id": "f1"}, timestamp=1.0)
        for_b = await fork.seal(claim, "node-b")
        for_c = await fork.seal(claim, "node-c")
        assert for_b is not None and for_b.auth is not None and for_c is not None and held.auth is not None
        assert len(for_b.auth["key_events"]) == len(held.auth["key_events"])
        assert for_b.auth["key_events"] != held.auth["key_events"]  # premise: same length, another inception
        await wire.inject("node-c", for_c)
        assert c.dispatched == [for_c]  # premise: the fork is self-consistent -- a fresh receiver accepts it

        await wire.inject("node-b", for_b)

        assert b.dispatched == [held]
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "held history")


async def test_held_history_reinception_is_rejected_and_first_contact_accepts_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        c = await _node(stack, wire, tmp_path, "node-c")
        held = await _seal(a, "node-b")
        await wire.inject("node-b", held)
        assert b.dispatched == [held]
        await a.binding.reincept(reason="lost", compromised_after_index=None)
        for_b = await _seal(a, "node-b")
        for_c = await _seal(a, "node-c")
        assert for_b.auth is not None and for_b.auth["key_events"][-1]["event"]["event"] == EVENT_REINCEPTION
        await wire.inject("node-c", for_c)
        assert c.dispatched == [for_c]  # a receiver that never held A accepts the re-incepted history (R-1)

        await wire.inject("node-b", for_b)

        assert b.dispatched == [held]
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "held history")


async def test_first_contact_is_bounded(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(envelope_module, "MAX_HELD_SENDERS", 1)
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        c = await _node(stack, wire, tmp_path, "node-c")
        first = await _seal(a, "node-b")
        await wire.inject("node-b", first)
        assert b.dispatched == [first]
        gossip = await _seal(c, BROADCAST, kind="gossip_self_model", payload={"node_id": "node-c"})

        await wire.inject("node-b", gossip)

        assert b.dispatched == [first]
        assert _rejections(caplog)[-1] == ("gossip_self_model", "node-c", "first contact refused")
        await wire.inject("node-a", gossip)
        assert a.dispatched == [gossip]  # premise: valid -- a node with room holds it
        second = await _seal(a, "node-b")
        await wire.inject("node-b", second)
        assert b.dispatched == [first, second]  # the sender already held is still accepted


async def test_oversized_or_malformed_key_history_is_rejected(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        sealed = await _seal(a, "node-b")
        auth = sealed.auth
        assert auth is not None
        item = auth["key_events"][0]
        variants = {
            "33 items": {
                **auth, "key_seq": MAX_KEY_EVENTS,
                "key_events": [{**item, "index": item["index"] + offset} for offset in range(MAX_KEY_EVENTS + 1)],
            },
            "more events than key_seq + 1": {**auth, "key_events": [item, {**item, "index": item["index"] + 1}]},
            "missing member": {**auth, "key_events": [{"index": item["index"], "event": item["event"]}]},
            "index not an int": {**auth, "key_events": [{**item, "index": str(item["index"])}]},
            "over 65,536 bytes": {
                **auth, "key_events": [{**item, "event": {**item["event"], "pad": "x" * MAX_AUTH_BYTES}}],
            },
        }
        for label, bad in variants.items():
            await wire.inject("node-b", dataclasses.replace(sealed, auth=bad))
            assert b.dispatched == [], label
            assert _rejections(caplog)[-1] == ("intent_request", "node-a", "malformed"), label

        await wire.inject("node-b", sealed)

        assert b.dispatched == [sealed]  # premise: the unaltered envelope is accepted


async def test_receive_returns_only_the_peer_asked_for(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        c = await _node(stack, wire, tmp_path, "node-c")
        from_c = await _seal(c, "node-a", kind="intent_response", payload={"results": []})
        await a.transport.deliver_response("node-b", from_c)

        assert await a.transport.receive_with_timeout("node-b", 50) is None

        await a.transport.deliver_response("node-c", from_c)
        assert await a.transport.receive_with_timeout("node-c", 500) is from_c  # premise: valid from its source


async def test_store_refuses_to_move_replay_state_or_a_hold_backwards(tmp_path: Path) -> None:
    path = tmp_path / ENVELOPE_DB_NAME
    store = EnvelopeStore(path)
    try:
        await store.start()
        assert await store.load() == ({}, {})
        assert [await store.next_send_epoch(), await store.next_send_epoch()] == [1, 2]
        held = StoredSender("did:probos:ship-b", 0, "a" * 64, "[0]")
        await store.record("node-b", "direct", held, StoredWindow(0, 2, 5, 1))
        base = _rows(path)
        assert base["senders"] == [("node-b", "did:probos:ship-b", 0, "a" * 64)]
        assert base["windows"] == [("node-b", "direct", 0, 2, 5, "0000000000000001")]

        for backwards in (StoredWindow(0, 2, 4, 1), StoredWindow(0, 1, 99, 1), StoredWindow(0, 2, 5, 0)):
            with pytest.raises(EnvelopeStateConflict):
                await store.record("node-b", "direct", None, backwards)
            assert _rows(path) == base, backwards
        forward = StoredWindow(0, 2, 6, 3)
        for refused in (
            StoredSender("did:probos:ship-x", 1, "b" * 64, "[0,1]"),  # another DID
            StoredSender("did:probos:ship-b", 0, "b" * 64, "[0]"),  # a history that does not grow
        ):
            with pytest.raises(EnvelopeStateConflict):
                await store.record("node-b", "direct", refused, forward)
            assert _rows(path) == base, refused
        grown = StoredSender("did:probos:ship-b", 1, "c" * 64, "[0,1]")
        with pytest.raises(EnvelopeStateConflict):
            await store.record("node-b", "direct", grown, StoredWindow(0, 2, 4, 1))
        assert _rows(path) == base  # the refused window rolled back the growth written before it

        await store.record("node-b", "direct", grown, StoredWindow(1, 1, 1, 1))  # a newer key, a lower epoch
        await store.record("node-b", "direct", None, StoredWindow(1, 1, 1, 1))  # an equal row is idempotent
        await store.record("node-b", "direct", None, StoredWindow(1, 1, 3, (1 << 63) | 0b101))
        await store.record("node-b", "broadcast", None, StoredWindow(1, 1, 1, 1))
        rows = _rows(path)
        assert rows["senders"] == [("node-b", "did:probos:ship-b", 1, "c" * 64)]
        assert rows["windows"] == [
            ("node-b", "broadcast", 1, 1, 1, "0000000000000001"),
            ("node-b", "direct", 1, 1, 3, "8000000000000005"),
        ]
        assert await store.load() == (
            {"node-b": grown},
            {("node-b", "broadcast"): StoredWindow(1, 1, 1, 1),
             ("node-b", "direct"): StoredWindow(1, 1, 3, (1 << 63) | 0b101)},
        )
        with pytest.raises(sqlite3.IntegrityError):
            await store.record("node-c", "node-a", None, StoredWindow(0, 1, 1, 1))  # the channel CHECK
        assert _rows(path) == rows
    finally:
        await store.stop()
    await store.stop()  # stopping twice is harmless
    with pytest.raises(RuntimeError):
        await store.load()


async def test_an_envelope_whose_replay_state_cannot_be_recorded_is_not_delivered(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    factory = _FailingFactory("INSERT INTO envelope_windows")
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b", connection_factory=factory)
        sealed = await _seal(a, "node-b")
        factory.arm()

        await wire.inject("node-b", sealed)

        assert b.dispatched == []
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "not recorded (OperationalError)")
        rows = _rows(b.store_path)
        assert rows["senders"] == [] and rows["windows"] == []
        assert factory.connection is not None
        factory.connection.armed = False
        await wire.inject("node-b", sealed)
        assert b.dispatched == [sealed]  # premise: valid, and the failed write changed no state


async def test_a_stored_history_that_does_not_replay_refuses_that_sender(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b", policy=POLICY_SIGN)
        c = await _node(stack, wire, tmp_path, "node-c")
        first = await _seal(a, "node-b")
        await wire.inject("node-b", first)
        assert b.dispatched == [first]
        await b.transport.stop()
        with contextlib.closing(sqlite3.connect(b.store_path)) as db:
            db.execute("UPDATE envelope_senders SET key_head = ? WHERE source_node = ?", ("0" * 64, "node-a"))
            db.commit()

        await _restart(stack, b, policy=POLICY_SIGN)

        errors = [
            record.getMessage() for record in caplog.records
            if record.name == _ENVELOPE_LOGGER and record.levelno == logging.ERROR
        ]
        assert errors == ["AD-1197: the key history held for 'node-a' does not replay; its envelopes are refused "
                          "until an operator resolves it"]
        await wire.inject("node-b", await _seal(a, "node-b"))
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "held history")
        await wire.inject("node-b", FederationMessage(
            type="intent_request", source_node="node-a", payload=copy.deepcopy(_REQUEST), timestamp=1.0,
        ))
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "downgrade")
        assert b.dispatched == [first]
        from_c = await _seal(c, "node-b")
        await wire.inject("node-b", from_c)
        assert b.dispatched == [first, from_c]  # premise: the restarted guard accepts other senders


async def test_a_sender_that_lost_its_envelope_store_recovers_by_rotating(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        await wire.inject("node-b", await _seal(a, "node-b"))
        await _restart(stack, a)
        second = await _seal(a, "node-b")
        assert second.auth is not None and second.auth["epoch"] == 2
        await wire.inject("node-b", second)
        assert len(b.dispatched) == 2
        await a.transport.stop()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{a.store_path}{suffix}").unlink(missing_ok=True)
        assert not a.store_path.exists()

        await _restart(stack, a)

        lost = await _seal(a, "node-b")
        assert lost.auth is not None and (lost.auth["epoch"], lost.auth["seq"]) == (1, 1)
        kid, public_key = await _active_key(a.binding)
        assert _signature_verifies(lost, public_key=public_key, kid=kid)  # premise: genuine
        await wire.inject("node-b", lost)
        assert len(b.dispatched) == 2
        assert _rejections(caplog)[-1] == ("intent_request", "node-a", "stale epoch")
        await a.binding.rotate()
        recovered = await _seal(a, "node-b")
        assert recovered.auth is not None and (recovered.auth["key_seq"], recovered.auth["epoch"]) == (1, 1)
        await wire.inject("node-b", recovered)
        assert b.dispatched[-1] is recovered


# --------------------------------------------------------------------------- #
# M3 -- policies, mixed fleets, binding
# --------------------------------------------------------------------------- #

_BRIDGE_LOGGER = "probos.federation.bridge"
_DIRECTED_FAILURE = "Directed federation request failed"


class _SwitchableSigner:
    """An ``EnvelopeSigner`` over a real binding that can be switched off, as a key that stops answering would."""

    def __init__(self, binding: IdentityKeyBinding) -> None:
        self.binding = binding
        self.off = False

    @property
    def key_status(self) -> str:
        return "key_unavailable" if self.off else self.binding.key_status

    async def sign_envelope(self, statement_for: Any) -> Any:
        if self.off:
            return None
        return await self.binding.sign_envelope(statement_for)


class _HoldingKeyStore:
    """Delegates to a real key store; holds the next ``hold`` envelope signatures until released.

    A held signature raises ``KeyStoreUnavailable`` on release while ``fail_held`` is set.
    Key-event signatures (rotation) are never held.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.hold = 0
        self.fail_held = False
        self.held = asyncio.Event()
        self.release = asyncio.Event()
        self.envelope_kids: list[str] = []
        self.failed: list[str] = []

    async def describe(self) -> Any:
        return await self.inner.describe()

    async def create(self, did: str) -> tuple[str, str]:
        return await self.inner.create(did)

    async def public_key(self, kid: str) -> str | None:
        return await self.inner.public_key(kid)

    async def sign(self, kid: str, message: str) -> str:
        header = json.loads(b64url_decode(message.split(".", 1)[0]))
        if header.get("typ") == ENVELOPE_JWS_TYP:
            self.envelope_kids.append(kid)
            if self.hold:
                self.hold -= 1
                self.release.clear()
                self.held.set()
                await self.release.wait()
                if self.fail_held:
                    self.failed.append(kid)
                    raise KeyStoreUnavailable("AD-1197 test: the held envelope signature failed")
        return await self.inner.sign(kid, message)


async def _rotate_while_held(store: _HoldingKeyStore, binding: IdentityKeyBinding, pending: asyncio.Task[Any]) -> str:
    """Wait for the held envelope signature, commit a rotation under it, release it; return the new active kid."""
    await asyncio.wait_for(store.held.wait(), timeout=10)  # hang guard only
    store.held.clear()
    assert not pending.done()  # premise: the envelope signature is held mid-call
    await binding.rotate()
    assert binding.key_status == STATUS_ACTIVE  # premise: the rotation committed and the binding is active
    store.release.set()
    return (await binding.status())["active_kid"]


async def _bridge(
    stack: contextlib.AsyncExitStack,
    node_id: str,
    transport: Any,
    intent_bus: Any,
    *,
    peers: tuple[str, ...] = (),
) -> FederationBridge:
    bridge = FederationBridge(
        node_id=node_id, transport=transport, router=FederationRouter(), intent_bus=intent_bus,
        config=FederationConfig(
            enabled=True, node_id=node_id, forward_timeout_ms=500, gossip_interval_seconds=100,
            peers=[PeerConfig(node_id=peer, address="tcp://127.0.0.1:65530") for peer in peers],
        ),
        self_model_fn=lambda: NodeSelfModel(node_id=node_id),
    )
    stack.push_async_callback(bridge.stop)
    await bridge.start()
    return bridge


async def _unarmed(stack: contextlib.AsyncExitStack, wire: _Wire, name: str) -> MockFederationTransport:
    """A node with no envelope signing at all: the plain mock transport, as at b621d3ab."""
    transport = MockFederationTransport(name, wire.bus)
    stack.push_async_callback(transport.stop)
    await transport.start()
    return transport


def _unsigned(source: str, *, kind: str = "intent_request", payload: dict[str, Any] | None = None) -> FederationMessage:
    return FederationMessage(
        type=kind, source_node=source, payload=copy.deepcopy(_REQUEST if payload is None else payload),
        timestamp=1.0,
    )


def _dm_intent() -> IntentMessage:
    return IntentMessage(
        intent="direct_message", params={"text": "status?"}, ttl_seconds=2.0, target_agent_id="target_agent_001",
    )


def _directed_failures(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The exception type named by each of the bridge's directed-request failure WARNINGs."""
    return [
        record.args[-1]  # type: ignore[index]
        for record in caplog.records
        if record.name == _BRIDGE_LOGGER and isinstance(record.msg, str) and record.msg.startswith(_DIRECTED_FAILURE)
    ]


def _envelope_messages(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    return [
        record.getMessage() for record in caplog.records if record.name == _ENVELOPE_LOGGER and record.levelno == level
    ]


async def _sent_to(wire: _Wire, target: str, after: int) -> FederationMessage:
    """The first message sent to ``target`` after ``after`` recorded sends."""
    for _ in range(1_000):
        found = [message for sent_to, message in wire.sent[after:] if sent_to == target]
        if found:
            return found[0]
        await asyncio.sleep(0.005)  # hang guard only: a bounded wait for the send to happen
    raise AssertionError(f"nothing was sent to {target}")


async def test_require_rejects_unsigned_and_sends_nothing_unsigned(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        await wire.inject("node-b", _unsigned("node-d"))  # from a sender never seen signing

        assert b.dispatched == []
        assert _rejections(caplog) == [("intent_request", "node-d", "unsigned")]

        bridge = await _bridge(stack, "node-a", a.transport, _RecordingIntentBus("node-a"), peers=("node-b",))
        await _seal(a, "node-b")  # premise: A's key signs while it is active
        a.duck.forget((await a.binding.status())["active_kid"])
        sent = len(wire.sent)

        await a.transport.send_to_peer("node-b", _unsigned("node-a"))
        assert a.binding.key_status == "key_unavailable"  # premise: the failed signature latched the key
        assert await a.transport.send_to_all_peers(
            _unsigned("node-a", kind="gossip_self_model", payload={"node_id": "node-a"}),
        ) == []
        with pytest.raises(EnvelopeNotSent):
            await a.transport.request_peer("node-b", _unsigned("node-a"), 500)
        result = await bridge.forward_direct_message("node-b", _dm_intent())

        assert wire.sent[sent:] == []
        assert result.success is False and result.error == "federation_target_delivery_failed"
        assert _directed_failures(caplog) == ["EnvelopeNotSent"]


async def test_sign_accepts_unsigned_only_from_senders_never_seen_signing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b", policy=POLICY_SIGN)
        never_held = _unsigned("node-d")
        await wire.inject("node-b", never_held)
        assert b.dispatched == [never_held]
        signed = await _seal(a, "node-b")
        await wire.inject("node-b", signed)
        assert b.dispatched == [never_held, signed]  # premise: B now holds A's history

        await wire.inject("node-b", _unsigned("node-a"))
        await wire.inject("node-b", dataclasses.replace(_unsigned("node-e"), auth={"v": 1}))

        assert b.dispatched == [never_held, signed]
        assert _rejections(caplog) == [
            ("intent_request", "node-a", "downgrade"), ("intent_request", "node-e", "malformed"),
        ]


async def test_sign_sends_unsigned_when_it_cannot_sign_and_says_so_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a", policy=POLICY_SIGN, signer=_SwitchableSigner)
        b = await _node(stack, wire, tmp_path, "node-b", policy=POLICY_SIGN)
        a.signer.off = True
        unsigned = [_unsigned("node-a", payload={**_REQUEST, "id": f"u-{index}"}) for index in range(3)]

        for message in unsigned:
            await a.transport.send_to_peer("node-b", message)

        assert [message for _, message in wire.sent] == unsigned and all(m.auth is None for m in unsigned)
        assert b.dispatched == unsigned
        assert _envelope_messages(caplog, logging.WARNING) == [
            "AD-1197: federation envelopes cannot be signed (the ship key is key_unavailable); under policy 'sign' "
            "they are sent unsigned",
        ]
        assert a.binding.key_status == STATUS_ACTIVE  # the switch only pretends: nothing latched
        a.signer.off = False
        await a.transport.send_to_peer("node-b", _unsigned("node-a", payload={**_REQUEST, "id": "s-1"}))
        signed = wire.sent[-1][1]
        assert signed.auth is not None and b.dispatched[-1] is signed
        assert _envelope_messages(caplog, logging.INFO).count("AD-1197: federation envelopes are signed again") == 1
        assert len(_envelope_messages(caplog, logging.WARNING)) == 1


async def _send_an_unsignable_body(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, policy: str, payload: dict[str, Any],
) -> None:
    """A sends a body with no RFC 8785 form three ways; 'sign' sends it unsigned, 'require' sends nothing."""
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a", policy=policy)
        b = await _node(stack, wire, tmp_path, "node-b", policy=POLICY_SIGN)
        await _seal(a, "node-b")  # premise: A's key signs an ordinary body (sealed, never sent)
        gets, sent = a.duck.gets, len(wire.sent)
        messages = [
            FederationMessage(type=kind, source_node="node-a", payload=payload, timestamp=1.0)
            for kind in ("intent_request", "gossip_self_model", "intent_request")
        ]

        await a.transport.send_to_peer("node-b", messages[0])
        peers = await a.transport.send_to_all_peers(messages[1])
        if policy == POLICY_SIGN:
            assert await a.transport.request_peer("node-b", messages[2], 50) is None  # sent; nobody answers
        else:
            with pytest.raises(EnvelopeNotSent):  # the refusal 'require' specifies for a request (§3.7)
                await a.transport.request_peer("node-b", messages[2], 50)

        assert a.binding.key_status == STATUS_ACTIVE and a.duck.gets == gets  # no latch; the key store never asked
        delivered = [message for _, message in wire.sent[sent:]]
        if policy == POLICY_SIGN:
            assert peers == ["node-b"]
            assert len(delivered) == 3 and all(got is sent_ for got, sent_ in zip(delivered, messages))
            assert all(message.auth is None for message in delivered)
            assert len(b.dispatched) == 3 and all(got is sent_ for got, sent_ in zip(b.dispatched, messages))
            expected = "under policy 'sign' they are sent unsigned"
        else:
            assert peers == [] and delivered == [] and b.dispatched == []
            expected = "under policy 'require' they are not sent"
        assert _envelope_messages(caplog, logging.WARNING) == [
            f"AD-1197: federation envelopes cannot be signed (the body has no RFC 8785 form); {expected}",
        ]


@pytest.mark.parametrize("policy", [POLICY_SIGN, POLICY_REQUIRE])
async def test_a_body_without_an_rfc8785_form_is_never_signed(
    policy: str, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    payload = {"n": 2**60}
    assert json.loads(json.dumps(payload)) == payload  # premise: plain JSON carries it
    with pytest.raises(ValueError):
        canonicalize(payload)  # premise: RFC 8785 has no form for an integer beyond 2**53 - 1
    await _send_an_unsignable_body(tmp_path, caplog, policy, payload)


async def test_armed_sender_and_unarmed_receiver_interoperate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    outcomes: dict[str, tuple[list[str], int, bool, bool]] = {}
    for policy in (POLICY_SIGN, POLICY_REQUIRE):
        (tmp_path / policy).mkdir()
        wire = _Wire()
        async with contextlib.AsyncExitStack() as stack:
            a = await _node(stack, wire, tmp_path / policy, "node-a", policy=policy)
            a_bridge = await _bridge(stack, "node-a", a.transport, _RecordingIntentBus("node-a"))
            b_bus = _RecordingIntentBus("node-b")
            await _bridge(stack, "node-b", await _unarmed(stack, wire, "node-b"), b_bus)

            results = await a_bridge.forward_intent(IntentMessage(intent="read_file", params={"path": "/a"}))

            request = next(message for target, message in wire.sent if target == "node-b")
            response = next(message for target, message in wire.sent if target == "node-a")
            outcomes[policy] = (
                [result.agent_id for result in results], len(b_bus.broadcasts), request.auth is not None,
                response.auth is None,
            )

    assert outcomes[POLICY_SIGN] == (["node-b-agent"], 1, True, True)  # B processed it; A took B's unsigned reply
    assert outcomes[POLICY_REQUIRE] == ([], 1, True, True)  # B processed it; A refused the unsigned reply
    assert _rejections(caplog) == [("intent_response", "node-b", "unsigned")]


async def test_unarmed_sender_and_armed_sign_receiver_interoperate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a", policy=POLICY_SIGN)
        a_bus = _RecordingIntentBus("node-a")
        await _bridge(stack, "node-a", a.transport, a_bus)
        b_bridge = await _bridge(stack, "node-b", await _unarmed(stack, wire, "node-b"), _RecordingIntentBus("node-b"))

        results = await b_bridge.forward_intent(IntentMessage(intent="read_file", params={"path": "/b"}))

        assert len(a_bus.broadcasts) == 1
        assert [result.agent_id for result in results] == ["node-a-agent"]
        request = next(message for target, message in wire.sent if target == "node-a")
        response = next(message for target, message in wire.sent if target == "node-b")
        assert request.auth is None and response.auth is not None  # A still signs what it sends
        assert _rejections(caplog) == []


async def test_envelope_signing_takes_no_ledger_lock(tmp_path: Path) -> None:
    async with _armed(tmp_path / "ship", _DuckKeyring()) as (registry, binding):
        k1 = (await binding.status())["active_kid"]
        async with registry._ledger_lock:  # held elsewhere for the whole signature (probe G5)
            rotation = asyncio.create_task(binding.rotate())
            signature = await asyncio.wait_for(  # hang guard only
                binding.sign_envelope(lambda state: {"probe": state.seq}), timeout=10,
            )
            assert not rotation.done()  # premise: a key action is held by this same lock
        await rotation
        k2 = (await binding.status())["active_kid"]

    assert signature is not None and signature.kid == k1 and jws_kid(signature.jws) == k1
    assert k2 != k1  # premise: the rotation ran once the lock was released


async def test_a_failed_envelope_signature_latches_key_unavailable(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    duck = _DuckKeyring()
    async with _armed(tmp_path / "ship", duck) as (registry, binding):
        assert await binding.sign_envelope(lambda state: {"probe": 0}) is not None  # premise: the active key signs
        kid = (await binding.status())["active_kid"]
        genuine = duck.forget(kid)

        assert await binding.sign_envelope(lambda state: {"probe": 1}) is None

        status = await binding.status()
        assert (status["status"], status["reason"]) == ("key_unavailable", f"no private key is stored for {kid}")
        bravo = await _birth(registry, "Bravo")
        chain = await registry.export_chain()
        assert "attestation" not in _block_for(chain, bravo.certificate_hash)  # certificates go unsigned too
        duck.set_password(f"probos.identity:{kid}", kid, genuine)
        gets = duck.gets
        assert await binding.sign_envelope(lambda state: {"probe": 2}) is None
        assert duck.gets == gets  # latched: refused before the key store is asked
        assert binding.key_status == "key_unavailable"
    assert any("is key_unavailable" in record.getMessage() for record in caplog.records)


async def test_an_envelope_signed_across_a_rotation_is_resigned_with_the_new_key(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a", key_store=_HoldingKeyStore)
        b = await _node(stack, wire, tmp_path, "node-b")
        k1 = (await a.binding.status())["active_kid"]
        a.key_store.hold = 1
        sealing = asyncio.create_task(a.guard.seal(_unsigned("node-a"), "node-b"))

        k2 = await _rotate_while_held(a.key_store, a.binding, sealing)
        sealed = await asyncio.wait_for(sealing, timeout=10)  # hang guard only

        assert a.key_store.envelope_kids == [k1, k2]  # the signature made across the rotation was discarded
        assert sealed is not None and sealed.auth is not None
        assert jws_kid(sealed.auth["jws"]) == k2 and sealed.auth["key_seq"] == 1
        await wire.inject("node-b", sealed)
        assert b.dispatched == [sealed]
        assert a.binding.key_status == STATUS_ACTIVE and _rejections(caplog) == []


async def test_a_failure_of_a_key_retired_mid_signature_does_not_latch(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a", key_store=_HoldingKeyStore)
        b = await _node(stack, wire, tmp_path, "node-b")
        k1 = (await a.binding.status())["active_kid"]
        a.key_store.hold, a.key_store.fail_held = 1, True
        sealing = asyncio.create_task(a.guard.seal(_unsigned("node-a"), "node-b"))

        k2 = await _rotate_while_held(a.key_store, a.binding, sealing)
        sealed = await asyncio.wait_for(sealing, timeout=10)  # hang guard only

        assert a.key_store.failed == [k1] and a.key_store.envelope_kids == [k1, k2]  # premise: K1's signature failed
        assert a.binding.key_status == STATUS_ACTIVE  # the retired key's failure latched nothing
        assert not any("is key_unavailable" in record.getMessage() for record in caplog.records)
        assert sealed is not None and sealed.auth is not None and jws_kid(sealed.auth["jws"]) == k2
        await wire.inject("node-b", sealed)
        assert b.dispatched == [sealed]


async def test_no_key_material_or_signature_in_envelope_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        c = await _node(stack, wire, tmp_path, "node-c", policy=POLICY_SIGN)
        sealed = [await _seal(a, "node-b") for _ in range(4)]
        gossip = await _seal(a, BROADCAST, kind="gossip_self_model", payload={"node_id": "node-a"})
        header = await _altered("auth_header_extra_member", sealed[3], a, [])
        assert header.auth is not None and sealed[2].auth is not None
        deliveries: list[tuple[str, FederationMessage]] = [
            ("node-b", sealed[0]),  # accepted
            ("node-b", sealed[0]),  # duplicate
            ("node-b", dataclasses.replace(sealed[1], payload={"id": "x"})),  # signature
            ("node-c", sealed[1]),  # target
            ("node-b", dataclasses.replace(sealed[2], auth={**sealed[2].auth, "note": 1})),  # malformed
            ("node-b", dataclasses.replace(sealed[2], auth={**sealed[2].auth, "key_head": "0" * 64})),  # stale key
            ("node-b", header),  # header
            ("node-a", gossip),  # reflected
            ("node-b", _unsigned("node-d")),  # unsigned
            ("node-c", gossip),  # accepted: C now holds A
            ("node-c", _unsigned("node-a")),  # downgrade
        ]
        for target, message in deliveries:
            await wire.inject(target, message)
        private = [secret for node in (a, b, c) for secret in node.duck.entries.values()]
        a.duck.forget((await a.binding.status())["active_kid"])
        await a.transport.send_to_peer("node-b", _unsigned("node-a"))  # the latch, then 'require' sends nothing
        assert a.binding.key_status == "key_unavailable"  # premise: the latch path ran
        statuses = [await node.binding.status() for node in (a, b, c)]

    reasons = [record[2] for record in _rejections(caplog)]
    assert reasons == [
        "duplicate", "signature", "target", "malformed", "stale key", "header", "reflected", "unsigned", "downgrade",
    ]  # premise: every kind above was logged
    assert all(type(arg) is str for record in _rejections(caplog) for arg in record)  # no counter is ever an argument
    public: list[str] = []
    for status in statuses:
        for record in status["keys"]:
            public += [record["public_key"], b64url_encode(base64.b64decode(record["public_key"]))]
    for message in (*sealed, gossip, header):
        assert message.auth is not None
        public += [message.auth["jws"], json.dumps(message.auth["key_events"])]
        public += [jws for item in message.auth["key_events"] for jws in item["signatures"].values()]
    assert len(private) >= 3 and len(public) > 12
    ours = "\n".join(record.getMessage() for record in caplog.records if record.name.startswith("probos"))
    assert "is key_unavailable" in ours and "rejected (duplicate)" in ours  # premise: the paths did log
    for secret in private:
        assert secret not in caplog.text  # not ours, and not aiosqlite's DEBUG echo of SQL parameters
    for value in public:
        assert value not in ours  # ProbOS's own messages (aiosqlite's DEBUG echoes the public rows it writes)
    assert "auth" not in repr(sealed[0]) and sealed[0].auth["jws"] not in repr(sealed[0])


async def test_directed_response_failing_verification_is_reported_not_trusted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        a_bridge = await _bridge(stack, "node-a", a.transport, _RecordingIntentBus("node-a"), peers=("node-b",))
        b_bus = IntentBus(SignalManager())

        async def _target(inbound: IntentMessage) -> IntentResult:
            return IntentResult(
                intent_id=inbound.id, agent_id="target_agent_001", success=True, result="genuine", confidence=0.9,
            )

        b_bus.subscribe("target_agent_001", _target, ["direct_message"])
        await _bridge(stack, "node-b", b.transport, b_bus, peers=("node-a",))
        intent = _dm_intent()
        genuine = await a_bridge.forward_direct_message("node-b", intent)
        assert genuine.success is True and genuine.result == "genuine"  # premise: B's signed reply is accepted
        reply = next(m for target, m in reversed(wire.sent) if target == "node-a" and m.type == "intent_response")
        assert reply.auth is not None and _rejections(caplog) == []

        wire.hold = True
        mark = len(wire.sent)
        pending = asyncio.create_task(a_bridge.forward_direct_message("node-b", intent))
        request = await _sent_to(wire, "node-b", mark)  # A's request is on the wire, held back from B
        await wire.inject("node-a", dataclasses.replace(reply, message_id=request.message_id))  # answers first
        result = await asyncio.wait_for(pending, timeout=10)  # hang guard only

        assert result.success is False and result.error == "federation_target_delivery_failed"
        assert _rejections(caplog) == [("intent_response", "node-b", "signature")]
        assert _directed_failures(caplog) == ["EnvelopeRejected"]


# --------------------------------------------------------------------------- #
# A-0 -- a body too deep for RFC 8785 never escapes as an exception
# --------------------------------------------------------------------------- #

_DEEP = 600


def _too_deep_body() -> dict[str, Any]:
    """A body plain JSON carries and RFC 8785 cannot canonicalise -- checked in this process, never assumed."""
    body: dict[str, Any] = {}
    node = body
    for _ in range(_DEEP):
        node["a"] = {}
        node = node["a"]
    try:
        json.dumps(body)
    except RecursionError:
        pytest.fail(f"premise: json.dumps must carry a body nested {_DEEP} deep in this process")
    try:
        canonicalize(body)
    except RecursionError:
        return body
    pytest.fail(f"premise: canonicalize must raise RecursionError for a body nested {_DEEP} deep in this process")


@pytest.mark.parametrize("policy", [POLICY_SIGN, POLICY_REQUIRE])
async def test_a_body_too_deep_for_rfc8785_is_never_signed(
    policy: str, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    await _send_an_unsignable_body(tmp_path, caplog, policy, _too_deep_body())


async def test_an_inbound_signed_body_too_deep_for_rfc8785_is_rejected(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    deep = _too_deep_body()
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        first = await _seal(a, "node-b")
        await wire.inject("node-b", first)
        assert b.dispatched == [first]  # premise: A's genuine envelopes are accepted
        genuine = await _seal(a, "node-b")

        await wire.inject("node-b", dataclasses.replace(genuine, payload=deep))

        assert b.dispatched == [first]
        rejected = [message for message in _envelope_messages(caplog, logging.WARNING) if "rejected" in message]
        assert rejected == ["AD-1197: envelope 'intent_request' from 'node-a' rejected (no canonical form); not delivered"]
        await wire.inject("node-b", genuine)
        assert b.dispatched[-1] is genuine  # premise: valid, and the rejection consumed nothing
        response = await _seal(b, "node-a", kind="intent_response", payload={"results": []})
        await a.transport.deliver_response("node-b", dataclasses.replace(response, payload=deep))

        assert await a.transport.receive_with_timeout("node-b", 50) is None  # discarded where consumed, no raise

        assert _rejections(caplog)[-1] == ("intent_response", "node-b", "no canonical form")
        await a.transport.deliver_response("node-b", response)
        assert await a.transport.receive_with_timeout("node-b", 500) is response  # premise: the genuine reply is taken


async def test_a_resign_race_on_both_attempts_names_the_key_change(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a", policy=POLICY_SIGN, key_store=_HoldingKeyStore)
        k1 = (await a.binding.status())["active_kid"]
        a.key_store.hold = 2
        message = _unsigned("node-a")
        sealing = asyncio.create_task(a.guard.seal(message, "node-b"))

        k2 = await _rotate_while_held(a.key_store, a.binding, sealing)
        k3 = await _rotate_while_held(a.key_store, a.binding, sealing)
        sealed = await asyncio.wait_for(sealing, timeout=10)  # hang guard only

        assert a.key_store.envelope_kids == [k1, k2]  # premise: both attempts signed, each discarded by a key event
        assert sealed is message and message.auth is None  # 'sign' sends it unsigned
        assert a.binding.key_status == STATUS_ACTIVE  # a key change latches nothing
        assert _envelope_messages(caplog, logging.WARNING) == [
            "AD-1197: federation envelopes cannot be signed (the ship key changed during both signing attempts); "
            "under policy 'sign' they are sent unsigned",
        ]
        signed = await _seal(a, "node-b")
        assert signed.auth is not None and jws_kid(signed.auth["jws"]) == k3  # the next one signs with the new key


# --------------------------------------------------------------------------- #
# M4 -- the wire: both real transports carry the signature block
# --------------------------------------------------------------------------- #


def _no_zmq_context(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("constructing the ZeroMQ transport must open nothing")


def _serializers(monkeypatch: pytest.MonkeyPatch) -> tuple[FederationTransport, NATSFederationTransport]:
    """Both real transports, constructed without opening anything (no context, no subscription)."""
    monkeypatch.setattr(federation_transport_module.zmq.asyncio, "Context", _no_zmq_context)
    return (
        FederationTransport(node_id="node-x", bind_address="tcp://127.0.0.1:65530", peers=[]),
        NATSFederationTransport(node_id="node-x", nats_bus=MockNATSBus(), peer_node_ids=[]),
    )


def _legacy_zmq_deserialize(data: bytes) -> FederationMessage:
    """The ZeroMQ deserializer as it was at b621d3ab: five members read, anything else ignored."""
    obj = json.loads(data.decode())
    return FederationMessage(
        type=obj["type"], source_node=obj["source_node"], message_id=obj.get("message_id", "legacy"),
        payload=obj.get("payload", {}), timestamp=obj.get("timestamp", 0.0),
    )


class _ShimCountingTransport(SignedFederationTransport):
    """Records the topic of every message that reaches the inbound shim (probe F)."""

    def __init__(self, inner: Any, guard: EnvelopeGuard) -> None:
        super().__init__(inner, guard)
        self.shim_topics: list[str] = []

    async def _on_inbound(self, message: Any) -> None:
        self.shim_topics.append(message.type)
        await super()._on_inbound(message)


async def test_signed_envelope_survives_both_transport_round_trips_and_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    zmq_transport, nats_transport = _serializers(monkeypatch)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        via_zmq, via_nats = await _seal(a, "node-b"), await _seal(a, "node-b")

        zmq_bytes = zmq_transport._serialize(via_zmq)
        nats_wire = json.loads(json.dumps(nats_transport._serialize(via_nats)))  # NATSBus JSON-encodes the dict
        from_zmq, from_nats = zmq_transport._deserialize(zmq_bytes), nats_transport._deserialize(nats_wire)

        assert json.loads(zmq_bytes)["auth"] == via_zmq.auth and nats_wire["auth"] == via_nats.auth
        assert list(nats_wire) == [*_LEGACY_MEMBERS, "auth"]
        assert (from_zmq, from_nats) == (via_zmq, via_nats) and from_zmq.auth == via_zmq.auth
        assert from_nats.auth == via_nats.auth
        await wire.inject("node-b", from_zmq)
        await wire.inject("node-b", from_nats)
        assert b.dispatched == [from_zmq, from_nats]


def test_unsigned_envelope_serializes_without_an_auth_member(monkeypatch: pytest.MonkeyPatch) -> None:
    zmq_transport, nats_transport = _serializers(monkeypatch)
    for message in _representative_messages():
        assert message.auth is None
        assert "auth" not in json.loads(zmq_transport._serialize(message)), message.type
        assert "auth" not in nats_transport._serialize(message), message.type
        assert zmq_transport._deserialize(zmq_transport._serialize(message)).auth is None
        assert nats_transport._deserialize(nats_transport._serialize(message)).auth is None
    empty = dataclasses.replace(_representative_messages()[1], auth={})  # an empty block is not "unsigned"
    assert json.loads(zmq_transport._serialize(empty))["auth"] == {} and nats_transport._serialize(empty)["auth"] == {}
    assert zmq_transport._deserialize(zmq_transport._serialize(empty)).auth == {}
    assert nats_transport._deserialize(nats_transport._serialize(empty)).auth == {}


async def test_an_older_receiver_drops_auth_and_behaves_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    zmq_transport, _ = _serializers(monkeypatch)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        sealed = await _seal(a, "node-b")
    wire_bytes = zmq_transport._serialize(sealed)
    assert json.loads(wire_bytes)["auth"] == sealed.auth  # premise: the new wire carries the block
    older = _legacy_zmq_deserialize(wire_bytes)
    plain = dataclasses.replace(sealed, auth=None)
    assert older == plain  # an older receiver reads exactly the unsigned message

    outcomes = []
    for message in (older, plain):
        b_wire = _Wire()
        async with contextlib.AsyncExitStack() as stack:
            b_bus = _RecordingIntentBus("node-b")
            b_bridge = await _bridge(stack, "node-b", await _unarmed(stack, b_wire, "node-b"), b_bus)
            await b_bridge.handle_inbound(message)
        outcomes.append((
            [(intent.intent, intent.params, intent.id) for intent in b_bus.broadcasts],
            [(target, sent.type, sent.message_id, sent.payload, sent.auth) for target, sent in b_wire.sent],
        ))

    assert outcomes[0] == outcomes[1]
    assert len(outcomes[0][0]) == 1 and [sent[:2] for sent in outcomes[0][1]] == [("node-a", "intent_response")]


async def test_nats_two_nodes_sign_gossip_and_intents_and_verify_responses_where_consumed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    bus = MockNATSBus()
    await bus.start()
    assert bus.connected  # premise: the mock NATS bus routes publishes to subscribers
    try:
        async with contextlib.AsyncExitStack() as stack:
            nodes: dict[str, tuple[_ShimCountingTransport, FederationBridge, _RecordingIntentBus, Path]] = {}
            for name, peer in (("node-a", "node-b"), ("node-b", "node-a")):
                _, binding = await stack.enter_async_context(
                    _armed(tmp_path / f"{name}-identity", _DuckKeyring(), instance_id=name.replace("node", "ship")),
                )
                data_dir = tmp_path / f"{name}-data"
                data_dir.mkdir()
                guard = EnvelopeGuard(
                    signer=binding, store=EnvelopeStore(data_dir / ENVELOPE_DB_NAME), local_node_id=name,
                    policy=POLICY_REQUIRE,
                )
                transport = _ShimCountingTransport(
                    NATSFederationTransport(node_id=name, nats_bus=bus, peer_node_ids=[peer]), guard,
                )
                stack.push_async_callback(transport.stop)
                await transport.start()
                intent_bus = _RecordingIntentBus(name)
                nodes[name] = (transport, await _bridge(stack, name, transport, intent_bus), intent_bus, data_dir)
            a_transport, a_bridge, _, a_dir = nodes["node-a"]
            b_transport, _, b_bus, b_dir = nodes["node-b"]

            results = await a_bridge.forward_intent(IntentMessage(intent="read_file", params={"path": "/n"}))

            assert [result.agent_id for result in results] == ["node-b-agent"] and len(b_bus.broadcasts) == 1
            request = next(data for subject, data in bus.published if subject == "federation.intent.node-b")
            response = next(data for subject, data in bus.published if subject == "federation.intent.node-a")
            assert request["auth"]["target"] == "node-b" and response["auth"]["target"] == "node-a"
            assert b_transport.shim_topics == ["intent_request"]  # the request is verified before dispatch
            assert a_transport.shim_topics == []  # premise: over NATS the response bypasses the shim ...
            assert [row[:2] for row in _rows(a_dir / ENVELOPE_DB_NAME)["windows"]] == [("node-b", "direct")]
            # ... and was verified and recorded where forward_intent consumed it.

            gossip = FederationMessage(
                type="gossip_self_model", source_node="node-a", payload=_representative_messages()[3].payload,
                timestamp=1.0,
            )
            assert await a_transport.send_to_all_peers(gossip) == ["node-b"]
            published = next(data for subject, data in reversed(bus.published) if subject == "federation.gossip")
            assert published["auth"]["target"] == BROADCAST
            assert b_transport.shim_topics == ["intent_request", "gossip_self_model"]
            assert ("node-a", "broadcast") in [row[:2] for row in _rows(b_dir / ENVELOPE_DB_NAME)["windows"]]

            replay = NATSFederationTransport(node_id="node-x", nats_bus=MockNATSBus(), peer_node_ids=[])._deserialize(
                json.loads(json.dumps(response)),
            )
            await a_transport.deliver_response("node-b", replay)  # a captured response, queued ahead
            again = await a_bridge.forward_intent(IntentMessage(intent="read_file", params={"path": "/m"}))

            assert [result.agent_id for result in again] == ["node-b-agent"]  # the genuine response was taken
            assert _rejections(caplog) == [("intent_response", "node-b", "duplicate")]
    finally:
        await bus.stop()


# --------------------------------------------------------------------------- #
# M6 -- branch coverage for the new modules, beyond the contract's named tests
# --------------------------------------------------------------------------- #


class _MemoryStore:
    """An ``EnvelopeStateStore`` in memory whose start, stop or record can be made to raise."""

    def __init__(
        self, *, start_error: BaseException | None = None, stop_error: BaseException | None = None,
        record_error: BaseException | None = None,
    ) -> None:
        self.start_error, self.stop_error, self.record_error = start_error, stop_error, record_error
        self.stops = 0

    async def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error

    async def stop(self) -> None:
        self.stops += 1
        if self.stop_error is not None:
            raise self.stop_error

    async def next_send_epoch(self) -> int:
        return 1

    async def load(self) -> tuple[dict[str, StoredSender], dict[tuple[str, str], StoredWindow]]:
        return {}, {}

    async def key_ids(self, source: str) -> frozenset[str]:
        return frozenset()

    async def record(
        self, source: str, channel: str, sender: StoredSender | None, window: StoredWindow,
        key_ids: frozenset[str] = frozenset(),
    ) -> None:
        if self.record_error is not None:
            raise self.record_error


class _StartFailingConnection:
    """Delegates to an aiosqlite connection; raises for one SQL prefix and records ``close``."""

    def __init__(self, inner: Any, prefix: str) -> None:
        self._inner = inner
        self._prefix = prefix
        self.closed = False

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        if sql.lstrip().startswith(self._prefix):
            raise sqlite3.OperationalError("AD-1197 test: injected start failure")
        return self._inner.execute(sql, parameters)

    async def close(self) -> None:
        self.closed = True
        await self._inner.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _StartFailingFactory:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self.connection: _StartFailingConnection | None = None

    async def connect(self, db_path: str) -> Any:
        self.connection = _StartFailingConnection(await default_factory.connect(db_path), self._prefix)
        return self.connection


class _FailingStartTransport(MockFederationTransport):
    async def start(self) -> None:
        raise RuntimeError("AD-1197 test: the transport could not start")


def test_envelope_guard_refuses_an_unknown_policy_or_an_empty_node_id() -> None:
    with pytest.raises(ValueError, match="policy"):
        EnvelopeGuard(signer=SimpleNamespace(), store=_MemoryStore(), local_node_id="node-a", policy="strict")
    with pytest.raises(ValueError, match="node id"):
        EnvelopeGuard(signer=SimpleNamespace(), store=_MemoryStore(), local_node_id="", policy=POLICY_SIGN)
    guard = EnvelopeGuard(signer=SimpleNamespace(), store=_MemoryStore(), local_node_id="node-a", policy=POLICY_REQUIRE)
    assert guard.accepts_traffic is False  # premise: valid arguments construct, and nothing opens before start


async def test_a_guard_that_is_not_armed_seals_and_admits_nothing() -> None:
    store = _MemoryStore()
    guard = EnvelopeGuard(signer=SimpleNamespace(), store=store, local_node_id="node-b", policy=POLICY_SIGN)
    message = _unsigned("node-x")
    assert await guard.admit(message) is False and await guard.seal(_unsigned("node-b"), "node-x") is None  # new
    await guard.start()
    assert await guard.admit(message) is True  # premise: armed, 'sign' admits a sender never seen signing
    await guard.stop()
    assert await guard.admit(message) is False and await guard.seal(_unsigned("node-b"), "node-x") is None
    assert store.stops == 1


async def test_a_store_that_fails_to_close_still_stops_the_guard(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    guard = EnvelopeGuard(
        signer=SimpleNamespace(), store=_MemoryStore(stop_error=OSError("closed badly")), local_node_id="node-b",
        policy=POLICY_SIGN,
    )
    await guard.start()
    assert guard.accepts_traffic  # premise: armed

    await guard.stop()

    assert guard.accepts_traffic is False
    assert _envelope_messages(caplog, logging.WARNING) == [
        "AD-1197: the federation envelope store did not close cleanly (OSError); the guard is stopped",
    ]


async def test_a_cancelled_store_start_is_not_swallowed() -> None:
    store = _MemoryStore(start_error=asyncio.CancelledError())
    guard = EnvelopeGuard(signer=SimpleNamespace(), store=store, local_node_id="node-b", policy=POLICY_SIGN)
    with pytest.raises(asyncio.CancelledError):
        await guard.start()
    assert store.stops == 1 and guard.accepts_traffic is False  # the store was closed; the guard never armed


async def test_a_cancelled_record_is_not_swallowed(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        sealed = await _seal(a, "node-b")
    guard = EnvelopeGuard(
        signer=SimpleNamespace(), store=_MemoryStore(record_error=asyncio.CancelledError()), local_node_id="node-b",
        policy=POLICY_REQUIRE,
    )
    await guard.start()
    with pytest.raises(asyncio.CancelledError):
        await guard.admit(sealed)  # verified, then cancelled while recording: never read as a rejection
    await guard.stop()


async def test_a_stored_history_that_cannot_be_read_refuses_that_sender(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    path = tmp_path / ENVELOPE_DB_NAME
    store = EnvelopeStore(path)
    try:
        await store.start()
        await store.record(
            "node-a", "direct", StoredSender("did:probos:ship-a", 0, "a" * 64, "not json"), StoredWindow(0, 1, 1, 1),
        )
    finally:
        await store.stop()
    guard = EnvelopeGuard(signer=SimpleNamespace(), store=EnvelopeStore(path), local_node_id="node-b", policy=POLICY_SIGN)
    await guard.start()
    try:
        refused, accepted = await guard.admit(_unsigned("node-a")), await guard.admit(_unsigned("node-c"))
    finally:
        await guard.stop()
    assert (refused, accepted) == (False, True)
    assert _envelope_messages(caplog, logging.ERROR) == [
        "AD-1197: the key history held for 'node-a' does not replay; its envelopes are refused until an operator "
        "resolves it",
    ]
    assert _rejections(caplog) == [("intent_request", "node-a", "downgrade")]


async def test_a_statement_with_no_rfc8785_form_is_sent_unsigned_without_a_latch(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a", policy=POLICY_SIGN)
        gets = a.duck.gets
        message = dataclasses.replace(_unsigned("node-a"), timestamp=float("nan"))
        with pytest.raises(ValueError):
            canonical_bytes({"timestamp": message.timestamp})  # premise: RFC 8785 has no form for NaN

        assert await a.guard.seal(message, "node-b") is message

        assert a.binding.key_status == STATUS_ACTIVE and a.duck.gets == gets  # no latch; the key store never asked
    assert _envelope_messages(caplog, logging.WARNING) == [
        "AD-1197: federation envelopes cannot be signed (the envelope has no RFC 8785 form); under policy 'sign' "
        "they are sent unsigned",
    ]


async def test_admit_rejects_what_is_not_a_well_formed_message(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        b = await _node(stack, wire, tmp_path, "node-b", policy=POLICY_SIGN)
        assert await b.guard.admit(_unsigned("node-a")) is True  # premise: a well-formed unsigned message is admitted
        for bad in (
            object(),
            dataclasses.replace(_unsigned("node-a"), type=5),
            dataclasses.replace(_unsigned("node-a"), source_node=None),
            dataclasses.replace(_unsigned("node-a"), message_id=7),
        ):
            assert await b.guard.admit(bad) is False
    assert _rejections(caplog) == [
        ("NoneType", "NoneType", "malformed"), ("int", "node-a", "malformed"), ("intent_request", "NoneType", "malformed"),
        ("intent_request", "node-a", "malformed"),
    ]


async def test_a_key_history_that_does_not_replay_or_canonicalise_is_rejected(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        sealed = await _seal(a, "node-b")
        assert sealed.auth is not None
        broken = copy.deepcopy(sealed.auth)
        signature = broken["key_events"][0]["signatures"]["new"]
        broken["key_events"][0]["signatures"]["new"] = f"{signature[:-2]}{'AA' if signature[-2:] != 'AA' else 'BA'}"
        not_canonical = copy.deepcopy(sealed.auth)
        not_canonical["key_events"][0]["event"]["nan"] = float("nan")

        await wire.inject("node-b", dataclasses.replace(sealed, auth=broken))
        await wire.inject("node-b", dataclasses.replace(sealed, auth=not_canonical))

        assert b.dispatched == []
        assert _rejections(caplog) == [
            ("intent_request", "node-a", "key history does not replay"),
            ("intent_request", "node-a", "malformed (ValueError)"),
        ]
        await wire.inject("node-b", sealed)
        assert b.dispatched == [sealed]  # premise: the unaltered envelope is accepted


async def test_a_jws_whose_protected_header_does_not_parse_is_rejected(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        sealed = await _seal(a, "node-b")
        assert sealed.auth is not None
        _, _, signature = sealed.auth["jws"].partition("..")
        unreadable = f"{b64url_encode(b'not json')}..{signature}"
        with pytest.raises(ValueError):
            parse_detached(unreadable, expected_typ=ENVELOPE_JWS_TYP)  # premise: the parser raises, not None

        await wire.inject("node-b", dataclasses.replace(sealed, auth={**sealed.auth, "jws": unreadable}))

        assert b.dispatched == [] and _rejections(caplog) == [("intent_request", "node-a", "header")]
        await wire.inject("node-b", sealed)
        assert b.dispatched == [sealed]  # premise: the unaltered envelope is accepted


async def test_signed_transport_offers_only_what_the_bridge_uses(tmp_path: Path) -> None:
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        assert a.transport.node_id == a.inner.node_id == "node-a"
        assert a.transport._inbound_handler is not None  # the handler _wrap installed, read back
        assert a.transport.add_peer == a.inner.add_peer  # proxied by getattr, as bridge.py does
        with pytest.raises(AttributeError):
            a.transport.relay_one_way  # noqa: B018 -- nothing else is proxied
        assert await a.transport.receive_with_timeout("node-b", 0) is None  # an exhausted deadline returns at once
        handler = a.transport._inbound_handler
        a.transport._inbound_handler = None
        await a.transport._on_inbound(_unsigned("node-b"))  # no handler: nothing is dispatched
        a.transport._inbound_handler = handler
        assert a.dispatched == []


async def test_a_transport_that_fails_to_start_closes_its_guard(tmp_path: Path) -> None:
    wire = _Wire()
    async with _armed(tmp_path / "identity", _DuckKeyring()) as (_, binding):
        transport = build_signed_transport(
            _FailingStartTransport("node-a", wire.bus), policy=POLICY_REQUIRE, key_binding=binding, data_dir=tmp_path,
        )
        with pytest.raises(RuntimeError):
            await transport.start()
        assert _rows(tmp_path / ENVELOPE_DB_NAME)["epoch"] == [(1,)]  # premise: the guard had started
        assert transport.connected_peers == []  # the guard is stopped: nothing is sent or accepted
        await transport.send_to_peer("node-b", _unsigned("node-a"))
        await transport.stop()  # stopping after a failed start is harmless
    assert wire.sent == []


async def test_store_start_failure_closes_its_connection(tmp_path: Path) -> None:
    factory = _StartFailingFactory("PRAGMA synchronous")
    store = EnvelopeStore(tmp_path / ENVELOPE_DB_NAME, connection_factory=factory)
    with pytest.raises(sqlite3.OperationalError):
        await store.start()
    assert factory.connection is not None and factory.connection.closed  # no aiosqlite thread is left behind (H17)
    await store.stop()  # nothing to close: harmless
    with pytest.raises(RuntimeError):
        await store.next_send_epoch()


async def test_store_epoch_failure_rolls_back(tmp_path: Path) -> None:
    factory = _FailingFactory("INSERT INTO envelope_send_epoch")
    store = EnvelopeStore(tmp_path / ENVELOPE_DB_NAME, connection_factory=factory)
    try:
        await store.start()
        factory.arm()
        with pytest.raises(sqlite3.OperationalError):
            await store.next_send_epoch()
        assert factory.connection is not None
        factory.connection.armed = False
        assert await store.next_send_epoch() == 1  # the failed increment left nothing behind
    finally:
        await store.stop()


# --------------------------------------------------------------------------- #
# A-1 -- a ship signs for life; a malformed block is malformed in every mode
# --------------------------------------------------------------------------- #

_SIX_KINDS = {
    (EVENT_INCEPTION, ""), (EVENT_ROTATION, ""), (EVENT_RECOVERY, "lost"), (EVENT_RECOVERY, "compromised"),
    (EVENT_REINCEPTION, "lost"), (EVENT_REINCEPTION, "compromised"),
}


def _held_run(db_path: Path, source: str) -> tuple[int, list[dict[str, Any]]]:
    """The ``key_seq`` a receiver's store holds for ``source`` and the run of key events stored with it."""
    with contextlib.closing(sqlite3.connect(db_path)) as db:
        row = db.execute(
            "SELECT key_seq, key_events_json FROM envelope_senders WHERE source_node = ?", (source,),
        ).fetchone()
    assert row is not None, source
    return int(row[0]), json.loads(row[1])


@dataclass(frozen=True)
class _Histories:
    """Two real key-event histories, the in-memory keyrings holding their keys, and the recovery key."""

    recovering: tuple[KeyEvent, ...]
    reincepting: tuple[KeyEvent, ...]
    recovering_duck: _DuckKeyring
    reincepting_duck: _DuckKeyring
    recovery_private: str
    recovery_public: str


async def _active_activated_at(binding: IdentityKeyBinding) -> int:
    status = await binding.status()
    return next(key["activated_at"] for key in status["keys"] if key["kid"] == status["active_kid"])


async def _key_histories(tmp_path: Path, *, rotations: tuple[int, int, int]) -> _Histories:
    """Two histories built with real AD-1196 key actions that together hold all six kinds of key event.

    One commits a recovery key and recovers twice (``lost``, then ``compromised``); the other
    commits none and re-incepts twice -- a committed recovery key is never removed and refuses
    a re-inception, so no one history holds both. ``rotations`` rotations come before the first
    of the two, between them and after the second.
    """
    recovery_private, recovery_public = generate_recovery_keypair()
    recovering_duck, reincepting_duck = _DuckKeyring(), _DuckKeyring()
    async with contextlib.AsyncExitStack() as stack:
        _, recovering = await stack.enter_async_context(_armed(
            tmp_path / "recovering", recovering_duck, recovery_public_key=recovery_public, instance_id="ship-r",
        ))
        _, reincepting = await stack.enter_async_context(
            _armed(tmp_path / "reincepting", reincepting_duck, instance_id="ship-i"),
        )
        for reason, count in zip((None, "lost", "compromised"), rotations):
            if reason is not None:
                compromised = await _active_activated_at(recovering) if reason == "compromised" else None
                prepared = await recovering.prepare_recovery(
                    reason=reason, compromised_after_index=compromised, next_recovery_public_key="",
                )
                await recovering.apply_recovery(
                    authorization=sign_recovery_authorization(recovery_private, prepared["signing_payload"]),
                    reason=reason, compromised_after_index=compromised, next_recovery_public_key="",
                )
                compromised = await _active_activated_at(reincepting) if reason == "compromised" else None
                await reincepting.reincept(reason=reason, compromised_after_index=compromised)
            for _ in range(count):
                await recovering.rotate()
                await reincepting.rotate()
        return _Histories(
            await _history(recovering), await _history(reincepting), recovering_duck, reincepting_duck,
            recovery_private, recovery_public,
        )


def _key_signer(event: KeyEvent, duck: _DuckKeyring) -> tuple[str, Any, str]:
    """The kid, private key and public key of the key ``event`` introduced."""
    key = event.payload["key"]
    return key["kid"], decode_private_key(duck.secret(key["kid"])), key["public_key"]


def _resigned(event: KeyEvent, payload: dict[str, Any], signers: dict[str, tuple[str, Any, str]]) -> KeyEvent:
    """``event`` carrying ``payload``, each role signed afresh by its key, so the changed rule is its only fault."""
    body = canonical_bytes(payload)
    signatures: dict[str, str] = {}
    for role, (kid, private_key, public_key) in signers.items():
        signatures[role] = sign_with(
            body, kid=kid, typ=KEY_EVENT_JWS_TYP, sign=lambda text: sign_challenge(private_key, text),
        )
        assert verify_signature_for(  # premise: the re-signed signature verifies
            signatures[role], body, public_key_b64=public_key, kid=kid, typ=KEY_EVENT_JWS_TYP,
        ), role
    return dataclasses.replace(event, payload=payload, signatures=signatures, digest=event_digest(payload))


def _refusal(replay: Callable[[], object]) -> str | None:
    """The ``KeyEventInvalid`` message ``replay`` raises, or ``None`` when it replays."""
    try:
        replay()
    except KeyEventInvalid as exc:
        return str(exc)
    return None


def _without_records_before(state: KeyState, run: Sequence[KeyEvent]) -> KeyState:
    """``state`` without what an anchor at ``run[0]`` cannot know: every record from before that event."""
    index = run[0].index
    broken_at = tuple(at for at in state.broken_at if at >= index)
    roots = any(event.payload["event"] in (EVENT_INCEPTION, EVENT_REINCEPTION) for event in run)
    return dataclasses.replace(
        state,
        keys=tuple(record for record in state.keys if record.activated_at >= index),
        broken_at=broken_at,
        continuity="broken" if broken_at else "intact",
        ship_certificate_hash=state.ship_certificate_hash if roots else "",
        ship_credential_digest=state.ship_credential_digest if roots else "",
    )


async def test_a_long_lived_ship_keeps_exchanging_signed_envelopes_past_the_key_history_bound(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        holders = [
            await _node(stack, wire, tmp_path, "node-b"),
            await _node(stack, wire, tmp_path, "node-s", policy=POLICY_SIGN),
        ]
        for holder in holders:
            first = await _seal(a, holder.name)
            await wire.inject(holder.name, first)
            assert holder.dispatched == [first]  # premise: each holder holds A from its first envelope

        for rotation in range(1, 41):
            await a.binding.rotate()
            for holder in holders:
                sealed = await _seal(a, holder.name)
                assert sealed.auth is not None
                assert parse_auth(sealed.auth) is not None, f"rotation {rotation}: a receiver's parser refuses the block"
                assert len(sealed.auth["key_events"]) <= MAX_KEY_EVENTS, rotation
                assert len(json.dumps(sealed.auth)) <= MAX_AUTH_BYTES, rotation
                await wire.inject(holder.name, sealed)
                assert holder.dispatched[-1] is sealed, (rotation, holder.name, _rejections(caplog)[-1:])

        assert _rejections(caplog) == []
        assert len(await _history(a.binding)) == 41 > MAX_KEY_EVENTS  # premise: the history outgrew the bound
        last = await _seal(a, "node-b")
        assert last.auth is not None and last.auth["key_seq"] == 40
        assert len(last.auth["key_events"]) == MAX_KEY_EVENTS and last.auth["key_events"][0]["event"]["seq"] == 9
        for name, policy in (("node-c", POLICY_REQUIRE), ("node-d", POLICY_SIGN)):
            fresh = await _node(stack, wire, tmp_path, name, policy=policy)
            sealed = await _seal(a, name)
            await wire.inject(name, sealed)
            assert fresh.dispatched == [sealed], (name, _rejections(caplog)[-1:])
        b = holders[0]
        key_seq, run = _held_run(b.store_path, "node-a")
        assert key_seq == 40 and len(run) == MAX_KEY_EVENTS and run[0]["event"]["seq"] == 9

        await _restart(stack, b)
        await a.binding.rotate()
        after_restart = await _seal(a, "node-b")
        await wire.inject("node-b", after_restart)

        assert b.dispatched[-1] is after_restart
        assert _rejections(caplog) == []


async def test_derive_key_state_continues_from_a_held_state_exactly(tmp_path: Path) -> None:
    histories = await _key_histories(tmp_path, rotations=(10, 5, 20))
    pair = (histories.recovering, histories.reincepting)
    kinds = {(event.payload["event"], event.payload["reason"]) for history in pair for event in history}
    assert all(len(history) >= 38 for history in pair) and kinds == _SIX_KINDS  # premise: long, every kind

    for history in pair:
        full = derive_key_state(history)
        assert full is not None
        differs: list[tuple[int, str]] = []
        for split in range(len(history) + 1):
            try:
                continued = derive_key_state(history[split:], after=derive_key_state(history[:split]))
            except KeyEventInvalid as exc:
                differs.append((split, str(exc)))
                continue
            if continued != full:
                differs.append((split, "a different state"))
        assert differs == []
        assert derive_key_state((), after=full) is full
        for split in range(1, len(history)):
            moved = (dataclasses.replace(history[split], index=history[split - 1].index), *history[split + 1:])
            assert _refusal(lambda: derive_key_state((*history[:split], *moved))) is not None, split
            assert _refusal(lambda: derive_key_state(moved, after=derive_key_state(history[:split]))) is not None, split


async def test_replay_from_any_event_equals_the_full_replay_without_what_precedes_it(tmp_path: Path) -> None:
    from probos.identity_keys import replay_key_events

    histories = await _key_histories(tmp_path, rotations=(10, 5, 20))
    pair = (histories.recovering, histories.reincepting)
    anchors = {event.payload["event"] for history in pair for event in history[1:]}
    assert all(len(history) >= 38 for history in pair)
    assert anchors == {EVENT_ROTATION, EVENT_RECOVERY, EVENT_REINCEPTION}  # premise: anchors of every later kind

    for history in pair:
        full = derive_key_state(history)
        assert full is not None
        differs: list[tuple[int, str]] = []
        for start in range(len(history)):
            try:
                anchored = replay_key_events(history[start:])
            except KeyEventInvalid as exc:
                differs.append((start, str(exc)))
                continue
            if anchored != _without_records_before(full, history[start:]):
                differs.append((start, "a different state"))
        assert differs == []
        assert replay_key_events(history) == full
    assert replay_key_events(()) is None


async def test_an_anchor_applies_every_rule_that_needs_no_earlier_event(tmp_path: Path) -> None:
    from probos.identity_keys import replay_key_events

    histories = await _key_histories(tmp_path, rotations=(2, 1, 1))
    recovering, reincepting = histories.recovering, histories.reincepting
    duck = histories.recovering_duck
    at_rotation = next(k for k, event in enumerate(recovering) if k >= 2 and event.payload["event"] == EVENT_ROTATION)
    at_recovery = next(k for k, event in enumerate(recovering) if event.payload["event"] == EVENT_RECOVERY)
    at_reinception = next(
        k for k, event in enumerate(reincepting)
        if event.payload["event"] == EVENT_REINCEPTION and event.payload["reason"] == "compromised"
    )
    rotation, recovery, reinception = recovering[at_rotation], recovering[at_recovery], reincepting[at_reinception]
    rotation_signers = {"prior": _key_signer(recovering[at_rotation - 1], duck), "new": _key_signer(rotation, duck)}
    recovery_signers = {
        "recovery": (
            key_id(recovery.payload["did"], histories.recovery_public, role="recovery"),
            decode_private_key(histories.recovery_private), histories.recovery_public,
        ),
        "new": _key_signer(recovery, duck),
    }
    reinception_signers = {"new": _key_signer(reinception, histories.reincepting_duck)}
    _, prior_private, prior_public = rotation_signers["prior"]
    new_kid, body = rotation.payload["key"]["kid"], canonical_bytes(rotation.payload)
    by_another_key = sign_with(body, kid=new_kid, typ=KEY_EVENT_JWS_TYP, sign=lambda text: sign_challenge(prior_private, text))
    assert verify_signature_for(  # premise: a genuine signature, by another key, naming the new key
        by_another_key, body, public_key_b64=prior_public, kid=new_kid, typ=KEY_EVENT_JWS_TYP,
    )
    cases: list[tuple[str, tuple[KeyEvent, ...], int, KeyEvent]] = [
        ("seq 0", recovering, at_rotation, _resigned(rotation, {**rotation.payload, "seq": 0}, rotation_signers)),
        ("a prior that is not a digest", recovering, at_rotation,
         _resigned(rotation, {**rotation.payload, "prior": "x"}, rotation_signers)),
        ("the new key's signature by another key", recovering, at_rotation,
         dataclasses.replace(rotation, signatures={**rotation.signatures, "new": by_another_key})),
        ("a recovery that removes its recovery key", recovering, at_recovery,
         _resigned(recovery, {**recovery.payload, "recovery_public_key": ""}, recovery_signers)),
        ("a reason its event does not allow", recovering, at_rotation,
         _resigned(rotation, {**rotation.payload, "reason": "lost"}, rotation_signers)),
        ("a compromise point without its reason", recovering, at_rotation,
         _resigned(rotation, {**rotation.payload, "compromised_after_index": 1}, rotation_signers)),
        ("a compromise point at its event", reincepting, at_reinception,
         _resigned(reinception, {**reinception.payload, "compromised_after_index": reinception.index}, reinception_signers)),
        ("a compromise point after its event", reincepting, at_reinception,
         _resigned(reinception, {**reinception.payload, "compromised_after_index": reinception.index + 1}, reinception_signers)),
        ("ship hashes on a rotation", recovering, at_rotation,
         _resigned(rotation, {**rotation.payload, "ship_certificate_hash": "a" * 64}, rotation_signers)),
        ("a missing signature role", recovering, at_rotation,
         dataclasses.replace(rotation, signatures={"new": rotation.signatures["new"]})),
        # structural faults, met before any signature is checked: nothing to re-sign
        ("a ledger index at genesis", recovering, at_rotation, dataclasses.replace(rotation, index=0)),
        ("a digest that is not its payload's", recovering, at_rotation, dataclasses.replace(rotation, digest="0" * 64)),
        ("a payload with no RFC 8785 form", recovering, at_rotation, dataclasses.replace(
            rotation, payload={**rotation.payload, "key": {**rotation.payload["key"], "public_key": float("nan")}},
        )),
    ]
    for history in (recovering, reincepting):
        assert derive_key_state(history) is not None  # premise: the genuine histories replay
    for event in (rotation, recovery, reinception):
        assert _refusal(lambda: replay_key_events([event])) is None  # premise: each genuine event anchors

    for label, history, position, changed in cases:
        assert _refusal(lambda: replay_key_events([changed])) is not None, label
        assert _refusal(lambda: derive_key_state((*history[:position], changed, *history[position + 1:]))) is not None, label


async def test_an_anchor_takes_on_trust_only_what_needs_the_events_before_it(tmp_path: Path) -> None:
    from probos.identity_keys import replay_key_events

    histories = await _key_histories(tmp_path, rotations=(4, 1, 1))
    history, duck = histories.recovering, histories.recovering_duck
    position = next(k for k, event in enumerate(history) if k >= 4 and event.payload["event"] == EVENT_ROTATION)
    rotation, earlier = history[position], history[position - 3]
    prior = _key_signer(history[position - 1], duck)
    cases = {
        "a wrong prior digest": _resigned(
            rotation, {**rotation.payload, "prior": "0" * 64}, {"prior": prior, "new": _key_signer(rotation, duck)},
        ),
        "a key used before it": _resigned(
            rotation, {**rotation.payload, "key": dict(earlier.payload["key"])},
            {"prior": prior, "new": _key_signer(earlier, duck)},
        ),
    }
    assert derive_key_state(history) is not None  # premise: the genuine history replays
    assert rotation.payload["prior"] != "0" * 64 and earlier.payload["key"] != rotation.payload["key"]

    for label, changed in cases.items():
        assert _refusal(lambda: derive_key_state((*history[:position], changed))) is not None, label
        assert _refusal(lambda: replay_key_events([changed])) is None, label  # R-20: taken on trust at an anchor
        anchored = replay_key_events([changed])
        assert anchored is not None and anchored.active_kid == changed.payload["key"]["kid"], label


async def test_a_holder_that_missed_more_events_than_an_envelope_carries_refuses_the_gap(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        g = await _node(stack, wire, tmp_path, "node-g")
        g2 = await _node(stack, wire, tmp_path, "node-g2")
        firsts = {}
        for holder in (g, g2):
            firsts[holder.name] = await _seal(a, holder.name)
            await wire.inject(holder.name, firsts[holder.name])
            assert holder.dispatched == [firsts[holder.name]]  # premise: each holds A at seq 0
        for _ in range(MAX_KEY_EVENTS):
            await a.binding.rotate()
        reached = await _seal(a, "node-g")
        await wire.inject("node-g", reached)
        assert _rejections(caplog) == []
        assert g.dispatched == [firsts["node-g"], reached]
        assert reached.auth is not None and reached.auth["key_events"][0]["event"]["seq"] == 1  # the held head plus one

        await a.binding.rotate()
        gapped = await _seal(a, BROADCAST, kind="gossip_self_model", payload={"node_id": "node-a"})
        assert gapped.auth is not None and gapped.auth["key_events"][0]["event"]["seq"] == 2
        fresh = await _node(stack, wire, tmp_path, "node-h")
        await wire.inject("node-h", gapped)
        assert fresh.dispatched == [gapped]  # premise: genuine -- a peer that never held A holds it

        await wire.inject("node-g2", gapped)

        assert g2.dispatched == [firsts["node-g2"]]
        assert _rejections(caplog) == [("gossip_self_model", "node-a", "key history gap")]
        assert _held_run(g2.store_path, "node-a")[0] == 0


async def test_a_run_that_does_not_extend_the_held_head_is_refused(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        c = await _node(stack, wire, tmp_path, "node-c")
        held = await _seal(a, "node-b")
        await wire.inject("node-b", held)
        assert held.auth is not None and b.dispatched == [held]  # premise: B holds A at seq 0
        _, other_binding = await stack.enter_async_context(  # another binding of A's DID, as the fork test builds one
            _armed(tmp_path / "x-identity", _DuckKeyring(), instance_id="ship-a"),
        )
        for _ in range(MAX_KEY_EVENTS):
            await other_binding.rotate()
        other_dir = tmp_path / "x-data"
        other_dir.mkdir()
        other = EnvelopeGuard(
            signer=other_binding, store=EnvelopeStore(other_dir / ENVELOPE_DB_NAME), local_node_id="node-a",
            policy=POLICY_REQUIRE,
        )
        stack.push_async_callback(other.stop)
        await other.start()
        claim = FederationMessage(type="intent_request", source_node="node-a", payload={"id": "x1"}, timestamp=1.0)
        for_b, for_c = await other.seal(claim, "node-b"), await other.seal(claim, "node-c")
        assert for_b is not None and for_b.auth is not None and for_c is not None
        await wire.inject("node-c", for_c)
        assert _rejections(caplog) == [] and c.dispatched == [for_c]  # premise: self-consistent -- a fresh peer holds it
        carried = key_events_from_wire(for_b.auth["key_events"])
        assert [event.payload["seq"] for event in carried] == list(range(1, MAX_KEY_EVENTS + 1))
        assert keeps_held_key_events(  # premise: no overlap with the held run and no gap after it
            key_events_from_wire(held.auth["key_events"]), carried, carried_head=for_b.auth["key_seq"],
        ) == (True, "keeps")

        await wire.inject("node-b", for_b)

        assert b.dispatched == [held]
        assert _rejections(caplog) == [("intent_request", "node-a", "key history does not replay")]
        key_seq, run = _held_run(b.store_path, "node-a")
        assert key_seq == 0 and len(run) == 1  # B keeps its hold


@pytest.mark.parametrize("policy", [POLICY_SIGN, POLICY_REQUIRE])
async def test_a_block_too_large_for_the_receivers_bound_is_shortened_or_never_sent_signed(
    policy: str, tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a", policy=policy)
        b = await _node(stack, wire, tmp_path, "node-b")
        for _ in range(2):
            await a.binding.rotate()
        head = await _seal(a, "node-b")
        await wire.inject("node-b", head)
        assert head.auth is not None and b.dispatched == [head]  # premise: B holds A at its head (three events)
        sizes = [len(json.dumps({**head.auth, "key_events": head.auth["key_events"][-count:]})) for count in (1, 2, 3)]
        assert sizes[0] < sizes[1] < sizes[2] == len(json.dumps(head.auth))  # premise: measured from a sealed block
        bound = sizes[1] + 64  # a margin for the counters' digits
        assert bound < sizes[2]
        monkeypatch.setattr(envelope_module, "MAX_AUTH_BYTES", bound)

        await a.transport.send_to_peer("node-b", _unsigned("node-a", payload={**_REQUEST, "id": "two"}))

        assert _rejections(caplog) == []
        shortened = wire.sent[-1][1]
        assert shortened.auth is not None and len(shortened.auth["key_events"]) == 2
        assert parse_auth(shortened.auth) is not None and len(json.dumps(shortened.auth)) <= bound
        assert b.dispatched[-1] is shortened

        monkeypatch.setattr(envelope_module, "MAX_AUTH_BYTES", sizes[0] - 64)
        wire.hold = True
        sent = len(wire.sent)
        await a.transport.send_to_peer("node-b", _unsigned("node-a", payload={**_REQUEST, "id": "none"}))

        exceeded = [
            message for message in _envelope_messages(caplog, logging.WARNING)
            if "the signature block exceeds the envelope bounds" in message
        ]
        assert len(exceeded) == 1
        if policy == POLICY_REQUIRE:
            assert wire.sent[sent:] == []
        else:
            assert [message.auth for _, message in wire.sent[sent:]] == [None]


async def test_an_unguarded_guard_refuses_a_malformed_block_and_admits_well_formed_traffic_unverified(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        sealed = await _seal(a, "node-b")
    guard = EnvelopeGuard(
        signer=SimpleNamespace(), store=_MemoryStore(start_error=OSError("AD-1197 test: the store cannot open")),
        local_node_id="node-b", policy=POLICY_SIGN,
    )
    await guard.start()
    try:
        outbound = _unsigned("node-b")
        assert guard.accepts_traffic and await guard.seal(outbound, "node-a") is outbound  # premise: unguarded
        for bad in ({"v": 1}, {}, 5, "x", []):
            assert await guard.admit(dataclasses.replace(_unsigned("node-z"), auth=bad)) is False, bad
        assert _rejections(caplog) == [("intent_request", "node-z", "malformed")] * 5
        altered = dataclasses.replace(sealed, payload={**sealed.payload, "id": "altered"})
        for admitted in (_unsigned("node-z"), sealed, altered):
            assert await guard.admit(admitted) is True  # the designed degrade: admitted, unverified
        assert len(_rejections(caplog)) == 5
    finally:
        await guard.stop()


async def test_a_present_null_auth_is_malformed_never_unsigned(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    zmq_transport, nats_transport = _serializers(monkeypatch)
    wire = _Wire()
    base = {"type": "intent_request", "source_node": "node-n", "message_id": "m", "payload": {"id": "n"}, "timestamp": 1.0}
    async with contextlib.AsyncExitStack() as stack:
        b = await _node(stack, wire, tmp_path, "node-b", policy=POLICY_SIGN)
        absent = [
            zmq_transport._deserialize(json.dumps(base).encode()),
            nats_transport._deserialize(json.loads(json.dumps(base))),
        ]
        assert [message.auth for message in absent] == [None, None]
        for message in absent:
            assert await b.guard.admit(message) is True  # premise: unsigned, from a never-held source, under 'sign'
        null = {**base, "auth": None}

        present = [
            zmq_transport._deserialize(json.dumps(null).encode()),
            nats_transport._deserialize(json.loads(json.dumps(null))),
        ]

        assert [message.auth for message in present] == [{}, {}]
        for message in present:
            assert await b.guard.admit(message) is False
        assert _rejections(caplog) == [("intent_request", "node-n", "malformed")] * 2


# --------------------------------------------------------------------------- #
# A-2 -- a holder never forgets a key it verified
# --------------------------------------------------------------------------- #

_REUSE = "a key event may not reintroduce a key the DID already used"
_Key = tuple[str, Any, str]


def _fresh_key(did: str) -> _Key:
    """A key no history has used: its kid under ``did``, private key and public key."""
    private_b64, public = generate_recovery_keypair()
    return key_id(did, public), decode_private_key(private_b64), public


def _continuation(
    head: KeyEvent, *, event: str, key: _Key, signers: dict[str, _Key], recovery_public: str, reason: str = "",
    compromised: int | None = None, seq: int | None = None, prior: str | None = None, index: int | None = None,
    did: str | None = None, ship: tuple[str, str] = ("", ""),
) -> KeyEvent:
    """A key event after ``head`` introducing ``key``, each role in ``signers`` signing its RFC 8785 payload."""
    payload = build_event_payload(
        did=head.payload["did"] if did is None else did, seq=head.payload["seq"] + 1 if seq is None else seq,
        event=event, prior=head.digest if prior is None else prior, kid=key[0], public_key=key[2],
        recovery_public_key=recovery_public, reason=reason, compromised_after_index=compromised,
        ship_certificate_hash=ship[0], ship_credential_digest=ship[1],
    )
    body = canonical_bytes(payload)
    signatures = {
        role: sign_with(body, kid=kid, typ=KEY_EVENT_JWS_TYP, sign=lambda text, p=private: sign_challenge(p, text))
        for role, (kid, private, _public) in signers.items()
    }
    return KeyEvent(
        index=head.index + 1 if index is None else index, payload=payload, signatures=signatures,
        digest=event_digest(payload),
    )


def _candidates(
    history: tuple[KeyEvent, ...], k: int, duck: _DuckKeyring, recovery: _Key | None,
) -> list[tuple[str, KeyEvent, _Key]]:
    """Continuations of ``history[:k]``: every earlier key reused, one break of each prior-state rule, valid controls.

    Each item is ``(label, event, key that signs its envelope)``; labels of valid events start with ``control``.
    """
    prefix, head = history[:k], history[k - 1]
    state = derive_key_state(prefix)
    assert state is not None
    did, active, committed = head.payload["did"], _key_signer(head, duck), state.recovery_public_key
    ship = (state.ship_certificate_hash, state.ship_credential_digest)
    out: list[tuple[str, KeyEvent, _Key]] = []
    for earlier in prefix:
        used = _key_signer(earlier, duck)
        out.append((f"rotation reusing seq {earlier.payload['seq']}'s key", _continuation(
            head, event=EVENT_ROTATION, key=used, signers={"prior": active, "new": used}, recovery_public=committed), used))
        if recovery is not None:
            out.append((f"recovery reusing seq {earlier.payload['seq']}'s key", _continuation(
                head, event=EVENT_RECOVERY, key=used, signers={"recovery": recovery, "new": used},
                recovery_public=committed, reason="lost"), used))
        else:
            out.append((f"re-inception reusing seq {earlier.payload['seq']}'s key", _continuation(
                head, event=EVENT_REINCEPTION, key=used, signers={"new": used}, recovery_public="", reason="lost",
                ship=ship), used))
    fresh = _fresh_key(did)
    other_did_key = (key_id(did + "x", fresh[2]), fresh[1], fresh[2])
    rotation = {"prior": active, "new": fresh}
    out += [
        ("an index that does not increase", _continuation(
            head, event=EVENT_ROTATION, key=fresh, signers=rotation, recovery_public=committed, index=head.index), fresh),
        ("a seq gap", _continuation(
            head, event=EVENT_ROTATION, key=fresh, signers=rotation, recovery_public=committed, seq=k + 1), fresh),
        ("a wrong prior digest", _continuation(
            head, event=EVENT_ROTATION, key=fresh, signers=rotation, recovery_public=committed, prior="0" * 64), fresh),
        ("another DID", _continuation(
            head, event=EVENT_ROTATION, key=other_did_key, signers={"prior": active, "new": other_did_key},
            recovery_public=committed, did=did + "x"), other_did_key),
        ("a second inception", _continuation(
            head, event=EVENT_INCEPTION, key=fresh, signers={"new": fresh}, recovery_public=committed, ship=ship), fresh),
        ("a prior signature by a retired key", _continuation(
            head, event=EVENT_ROTATION, key=fresh, signers={"prior": _key_signer(history[k - 2], duck), "new": fresh},
            recovery_public=committed), fresh),
        ("control: a rotation to a fresh key", _continuation(
            head, event=EVENT_ROTATION, key=fresh, signers=rotation, recovery_public=committed), fresh),
    ]
    if recovery is not None:
        other_private, other_public = generate_recovery_keypair()
        other = (key_id(did, other_public, role="recovery"), decode_private_key(other_private), other_public)
        activated = state.active.activated_at
        out += [
            ("a rotation changing the committed recovery key", _continuation(
                head, event=EVENT_ROTATION, key=fresh, signers=rotation, recovery_public=other_public), fresh),
            ("a compromise point before the active key", _continuation(
                head, event=EVENT_RECOVERY, key=fresh, signers={"recovery": recovery, "new": fresh},
                recovery_public=committed, reason="compromised", compromised=activated - 1), fresh),
            ("a recovery signed by another recovery key", _continuation(
                head, event=EVENT_RECOVERY, key=fresh, signers={"recovery": other, "new": fresh},
                recovery_public=committed, reason="lost"), fresh),
            ("a re-inception while a recovery key is committed", _continuation(
                head, event=EVENT_REINCEPTION, key=fresh, signers={"new": fresh}, recovery_public="", reason="lost",
                ship=ship), fresh),
            ("control: a recovery to a fresh key", _continuation(
                head, event=EVENT_RECOVERY, key=fresh, signers={"recovery": recovery, "new": fresh},
                recovery_public=committed, reason="lost"), fresh),
            ("control: a compromised recovery at the active key's activation", _continuation(
                head, event=EVENT_RECOVERY, key=fresh, signers={"recovery": recovery, "new": fresh},
                recovery_public=committed, reason="compromised", compromised=activated), fresh),
        ]
    else:
        stray_private, stray_public = generate_recovery_keypair()
        stray = (key_id(did, stray_public, role="recovery"), decode_private_key(stray_private), stray_public)
        out += [
            ("a recovery with no committed recovery key", _continuation(
                head, event=EVENT_RECOVERY, key=fresh, signers={"recovery": stray, "new": fresh},
                recovery_public=stray_public, reason="lost"), fresh),
            ("control: a re-inception to a fresh key", _continuation(
                head, event=EVENT_REINCEPTION, key=fresh, signers={"new": fresh}, recovery_public="", reason="lost",
                ship=ship), fresh),
        ]
    return out


def _envelope(source: str, target: str, run: tuple[KeyEvent, ...], key: _Key, label: str) -> FederationMessage:
    """An envelope from ``source`` carrying ``run`` (its last event the head), signed by ``key``."""
    message = FederationMessage(type="intent_request", source_node=source, payload={"id": label[:60]}, timestamp=1.0)
    return _forge(
        message, target=target, epoch=1, seq=1, key_seq=run[-1].payload["seq"], key_head=run[-1].digest,
        key_events=key_events_to_wire(run), private_key=key[1], kid=key[0],
    )


def _copy_store(source: Path, target: Path) -> None:
    """A copy of the store at ``source``, taken with SQLite's backup API."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(source)) as live, contextlib.closing(sqlite3.connect(target)) as copy_:
        live.backup(copy_)


async def _holder(path: Path) -> EnvelopeGuard:
    """A started ``require`` guard over the store at ``path``."""
    guard = EnvelopeGuard(
        signer=SimpleNamespace(), store=EnvelopeStore(path), local_node_id="node-h", policy=POLICY_REQUIRE,
    )
    await guard.start()
    return guard


def _recorded_key_ids(db_path: Path, source: str) -> list[str]:
    """The key ids a receiver's store records for ``source``."""
    with contextlib.closing(sqlite3.connect(db_path)) as db:
        row = db.execute("SELECT key_ids_json FROM envelope_senders WHERE source_node = ?", (source,)).fetchone()
    assert row is not None, source
    return json.loads(row[0])


@pytest.mark.parametrize("restarted", [True, False], ids=["restarted", "running"])
async def test_a_holder_past_its_roll_forward_refuses_a_key_the_sender_used_before_its_held_run(
    restarted: bool, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    recovery_private, recovery_public = generate_recovery_keypair()
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a", recovery_public_key=recovery_public)
        b = await _node(stack, wire, tmp_path, "node-b")
        for rotation in range(35):
            if rotation:
                await a.binding.rotate()
            sealed = await _seal(a, "node-b")
            await wire.inject("node-b", sealed)
            assert b.dispatched[-1] is sealed, rotation  # premise: B holds A from its inception, every step admitted
        history = await _history(a.binding)
        key_seq, run = _held_run(b.store_path, "node-a")
        assert key_seq == 34 and run[0]["event"]["seq"] == 3  # premise: the inception fell out of B's 32-event hold
        did = history[0].payload["did"]
        recovery = (key_id(did, recovery_public, role="recovery"), decode_private_key(recovery_private), recovery_public)
        inception = _key_signer(history[0], a.duck)
        reuse = _continuation(
            history[-1], event=EVENT_RECOVERY, key=inception, signers={"recovery": recovery, "new": inception},
            recovery_public=recovery_public, reason="lost",
        )
        fresh = _fresh_key(did)
        control = _continuation(
            history[-1], event=EVENT_RECOVERY, key=fresh, signers={"recovery": recovery, "new": fresh},
            recovery_public=recovery_public, reason="lost",
        )
        assert _refusal(lambda: derive_key_state((*history, reuse))) == _REUSE  # premise: the full replay refuses it
        assert _refusal(lambda: derive_key_state((*history, control))) is None  # ... and the reuse is its only fault
        if restarted:
            await _restart(stack, b)
        before = len(b.dispatched)

        await wire.inject("node-b", _envelope("node-a", "node-b", (*history, reuse)[-MAX_KEY_EVENTS:], inception, "reuse"))

        assert len(b.dispatched) == before
        assert _rejections(caplog) == [("intent_request", "node-a", "key history does not replay")]
        assert _held_run(b.store_path, "node-a")[0] == 34
        c = await _node(stack, wire, tmp_path, "node-c")  # R-20: a first contact takes what precedes its anchor on trust
        first_contact = _envelope("node-a", "node-c", (*history, reuse)[-MAX_KEY_EVENTS:], inception, "reuse")
        await wire.inject("node-c", first_contact)
        assert c.dispatched == [first_contact]


async def test_a_holder_refuses_exactly_what_the_full_replay_refuses_across_roll_forwards_and_restarts(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    histories = await _key_histories(tmp_path, rotations=(10, 5, 20))
    pair = (histories.recovering, histories.reincepting)
    kinds = {(event.payload["event"], event.payload["reason"]) for history in pair for event in history}
    assert all(len(history) == 38 for history in pair) and kinds == _SIX_KINDS  # premise: past the bound, every kind
    did = histories.recovering[0].payload["did"]
    recovery = (
        key_id(did, histories.recovery_public, role="recovery"), decode_private_key(histories.recovery_private),
        histories.recovery_public,
    )
    checked = 0
    for name, history, duck, rec in (
        ("node-r", histories.recovering, histories.recovering_duck, recovery),
        ("node-i", histories.reincepting, histories.reincepting_duck, None),
    ):
        path = tmp_path / name / ENVELOPE_DB_NAME
        path.parent.mkdir()
        guard = await _holder(path)
        try:
            for step in (20, 21, 24, "restart", "check", 29, 32, 33, "check", 34, "restart", 36, 37, "restart", "check"):
                if step == "restart":
                    await guard.stop()
                    guard = await _holder(path)
                    continue
                if isinstance(step, int):
                    run = history[max(0, step - MAX_KEY_EVENTS + 1):step + 1]
                    genuine = _envelope(name, "node-h", run, _key_signer(history[step], duck), f"head {step}")
                    assert await guard.admit(genuine), (name, step)  # premise: the genuine history is held throughout
                    continue
                held_seq, held_run = _held_run(path, name)
                k = held_seq + 1
                assert k <= MAX_KEY_EVENTS or held_run[0]["event"]["seq"] > 0  # premise: past the bound, the hold rolled
                for label, event, key in _candidates(history, k, duck, rec):
                    full = _refusal(lambda: derive_key_state((*history[:k], event)))
                    envelope = _envelope(name, "node-h", (event,), key, label)
                    if label.startswith("control"):
                        assert full is None, label  # premise: the control is valid
                        copy_path = tmp_path / f"{name}-copy-{checked}" / ENVELOPE_DB_NAME
                        _copy_store(path, copy_path)
                        other = await _holder(copy_path)  # a restart on a copy, so the hold under test never grows
                        try:
                            admitted = await other.admit(envelope)
                        finally:
                            await other.stop()
                        assert admitted is (event.payload["event"] != EVENT_REINCEPTION), (name, k, label)  # R-3
                        checked += 1
                        continue
                    assert full is not None, (name, k, label)  # premise: the full replay refuses it
                    before = len(_rejections(caplog))
                    admitted = await guard.admit(envelope)
                    reasons = [args[2] for args in _rejections(caplog)[before:]]
                    if event.payload["event"] == EVENT_REINCEPTION:
                        expected = "held history"  # AD-1197: no held history is re-incepted (R-3)
                    elif label == "a seq gap":
                        expected = "key history gap"
                    else:
                        expected = "key history does not replay"
                    assert (admitted, reasons) == (False, [expected]), (name, k, label, full)
                    checked += 1
        finally:
            await guard.stop()
    assert checked == 454


async def test_derive_key_state_refuses_every_key_used_before_the_records_it_continues(tmp_path: Path) -> None:
    from probos.identity_keys import replay_key_events

    histories = await _key_histories(tmp_path, rotations=(10, 5, 20))
    for history, duck in (
        (histories.recovering, histories.recovering_duck), (histories.reincepting, histories.reincepting_duck),
    ):
        full = derive_key_state(history)
        assert full is not None and len(history) == 38
        for k in range(MAX_KEY_EVENTS + 1, len(history) + 1):
            kept = replay_key_events(history[k - MAX_KEY_EVENTS:k])
            used = frozenset(event.payload["key"]["kid"] for event in history[:k])
            assert kept is not None
            continued = derive_key_state(history[k:], after=kept, used_key_ids=used)  # genuine events never reuse
            assert continued is not None and (continued.seq, continued.head_digest, continued.active) == (
                full.seq, full.head_digest, full.active,
            )
            head, active, committed = history[k - 1], _key_signer(history[k - 1], duck), kept.recovery_public_key
            for earlier in history[:k - MAX_KEY_EVENTS]:  # the keys that fell out of the 32 kept events
                key = _key_signer(earlier, duck)
                reuse = _continuation(
                    head, event=EVENT_ROTATION, key=key, signers={"prior": active, "new": key}, recovery_public=committed,
                )
                assert _refusal(lambda: derive_key_state((*history[:k], reuse))) == _REUSE  # premise
                assert _refusal(lambda: derive_key_state((reuse,), after=kept)) is None  # premise: the kept records allow it
                assert _refusal(lambda: derive_key_state((reuse,), after=kept, used_key_ids=used)) == _REUSE
        assert derive_key_state((), after=full, used_key_ids=frozenset({"x"})) is full


async def test_a_sender_past_the_key_id_bound_is_refused_and_never_forgotten(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    monkeypatch.setattr(envelope_module, "MAX_HELD_KEY_IDS", 4, raising=False)  # raising=False: RED by behaviour
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        for rotation in range(4):
            if rotation:
                await a.binding.rotate()
            sealed = await _seal(a, "node-b")
            await wire.inject("node-b", sealed)
            assert b.dispatched[-1] is sealed, rotation  # premise: up to the bound, every growth is admitted
        assert len(_held_run(b.store_path, "node-a")[1]) == 4  # premise: four events, four keys -- the bound
        await a.binding.rotate()
        past = await _seal(a, "node-b")

        await wire.inject("node-b", past)

        assert b.dispatched[-1] is not past
        assert _rejections(caplog) == [("intent_request", "node-a", "key history too long")]
        assert _held_run(b.store_path, "node-a")[0] == 3 and len(_recorded_key_ids(b.store_path, "node-a")) == 4
        monkeypatch.setattr(envelope_module, "MAX_HELD_KEY_IDS", 5)
        await wire.inject("node-b", past)
        assert b.dispatched[-1] is past  # premise: genuine -- the bound alone refused it, and nothing was forgotten
        assert len(_recorded_key_ids(b.store_path, "node-a")) == 5


async def test_the_store_never_forgets_a_recorded_key_id(tmp_path: Path) -> None:
    path = tmp_path / ENVELOPE_DB_NAME
    store = EnvelopeStore(path)
    try:
        await store.start()
        held = StoredSender("did:probos:ship-b", 0, "a" * 64, "[0]")
        await store.record("node-b", "direct", held, StoredWindow(0, 1, 1, 1), frozenset({"k0"}))
        assert await store.key_ids("node-b") == frozenset({"k0"}) and await store.key_ids("node-z") == frozenset()
        grown = StoredSender("did:probos:ship-b", 1, "b" * 64, "[0,1]")
        with pytest.raises(EnvelopeStateConflict):
            await store.record("node-b", "direct", grown, StoredWindow(1, 1, 1, 1), frozenset({"k1"}))
        assert await store.key_ids("node-b") == frozenset({"k0"}) and _held_run(path, "node-b")[0] == 0
        await store.record("node-b", "direct", grown, StoredWindow(1, 1, 1, 1), frozenset({"k0", "k1"}))
        assert await store.key_ids("node-b") == frozenset({"k0", "k1"}) and _held_run(path, "node-b")[0] == 1
        written = _rows(path)
        with pytest.raises(ValueError):
            await store.record("node-b", "direct", None, StoredWindow(1, 1, 2, 3), frozenset({"k2"}))
        assert await store.key_ids("node-b") == frozenset({"k0", "k1"}) and _rows(path) == written  # nothing written
        for tampered in ('{"k0": 1}', "[1]", "7"):
            with contextlib.closing(sqlite3.connect(path)) as db:
                db.execute("UPDATE envelope_senders SET key_ids_json = ? WHERE source_node = ?", (tampered, "node-b"))
                db.commit()
            with pytest.raises(ValueError):
                await store.key_ids("node-b")
    finally:
        await store.stop()


async def test_an_unreadable_key_id_record_refuses_the_growth(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    factory = _FailingFactory("SELECT key_ids_json")
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b", connection_factory=factory)
        first = await _seal(a, "node-b")
        await wire.inject("node-b", first)
        assert b.dispatched == [first]  # premise: B holds A at seq 0
        await a.binding.rotate()
        grown = await _seal(a, "node-b")
        factory.arm()

        await wire.inject("node-b", grown)

        assert b.dispatched == [first]
        assert _rejections(caplog) == [("intent_request", "node-a", "not recorded (OperationalError)")]
        assert _held_run(b.store_path, "node-a")[0] == 0
        assert factory.connection is not None
        factory.connection.armed = False
        await wire.inject("node-b", grown)
        assert b.dispatched == [first, grown]  # premise: valid -- the unread record refused it, nothing else


# --------------------------------------------------------------------------- #
# A-2b -- a signed envelope's source node id is bounded like its target
# --------------------------------------------------------------------------- #

_NODE_ID_BOUND = 256  # A-2b: a signed envelope's source and target node ids are 1 to 256 characters


@pytest.mark.parametrize(
    ("source", "label"),
    [("", ""), (7, "int"), ("s" * (_NODE_ID_BOUND + 1), "s" * 64)],
    ids=["empty", "non_str", "too_long"],
)
async def test_a_signed_envelope_with_an_unbounded_source_node_is_refused_before_the_store(
    source: object, label: str, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        b = await _node(stack, wire, tmp_path, "node-b")
        run = await _history(a.binding)
        key = _key_signer(run[-1], a.duck)
        at_bound = _envelope("s" * _NODE_ID_BOUND, "node-b", run, key, "at the bound")
        await wire.inject("node-b", at_bound)
        assert b.dispatched == [at_bound]  # premise: a 256-character source signed by the same key is admitted ...
        recorded = _rows(b.store_path)
        assert [row[0] for row in recorded["senders"]] == [at_bound.source_node]  # ... and recorded
        assert [row[0] for row in recorded["windows"]] == [at_bound.source_node]
        beyond = _envelope(source, "node-b", run, key, "beyond the bound")  # type: ignore[arg-type]

        await wire.inject("node-b", beyond)

        assert b.dispatched == [at_bound]
        assert _rejections(caplog) == [("intent_request", label, "malformed (source)")]
        assert _rows(b.store_path) == recorded  # refused before the store: no hold and no window for it
        assert not any("s" * (_NODE_ID_BOUND + 1) in record.getMessage() for record in caplog.records)
    unguarded = EnvelopeGuard(
        signer=SimpleNamespace(), store=_MemoryStore(start_error=OSError("AD-1197 test: the store cannot open")),
        local_node_id="node-b", policy=POLICY_SIGN,
    )
    await unguarded.start()
    try:
        assert await unguarded.admit(at_bound) is True  # premise: unguarded admits a well-formed signed envelope
        assert await unguarded.admit(beyond) is False  # every mode refuses it
    finally:
        await unguarded.stop()
    assert _rejections(caplog) == [("intent_request", label, "malformed (source)")] * 2
    assert envelope_module.MAX_NODE_ID_CHARS == _NODE_ID_BOUND


@pytest.mark.parametrize("policy", [POLICY_SIGN, POLICY_REQUIRE])
async def test_a_local_node_id_beyond_the_bound_is_never_signed(
    policy: str, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_ENVELOPE_LOGGER)
    wire = _Wire()
    local = "n" * (_NODE_ID_BOUND + 1)
    async with contextlib.AsyncExitStack() as stack:
        a = await _node(stack, wire, tmp_path, "node-a")
        data_dir = tmp_path / "local-data"
        data_dir.mkdir()
        guard = EnvelopeGuard(
            signer=a.binding, store=EnvelopeStore(data_dir / ENVELOPE_DB_NAME), local_node_id=local, policy=policy,
        )
        transport = SignedFederationTransport(MockFederationTransport(local, wire.bus), guard)
        stack.push_async_callback(transport.stop)
        await transport.start()
        at_bound = await guard.seal(_unsigned("n" * _NODE_ID_BOUND), "node-a")
        assert at_bound is not None and at_bound.auth is not None  # premise: the ship key signs; only the bound refuses
        sent = len(wire.sent)

        await transport.send_to_peer("node-a", _unsigned(local))

        if policy == POLICY_REQUIRE:
            assert wire.sent[sent:] == []
        else:
            assert [(target, message.auth) for target, message in wire.sent[sent:]] == [("node-a", None)]
        assert [message for message in _envelope_messages(caplog, logging.WARNING) if "cannot be signed" in message] == [
            "AD-1197: federation envelopes cannot be signed (the source node id is not 1 to 256 characters); under "
            + ("policy 'require' they are not sent" if policy == POLICY_REQUIRE else "policy 'sign' they are sent unsigned"),
        ]
    assert envelope_module.MAX_NODE_ID_CHARS == _NODE_ID_BOUND
