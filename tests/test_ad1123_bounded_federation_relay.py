"""AD-1123: bounded federation one-way relay tests."""

from __future__ import annotations

import asyncio
import ast
import copy
import functools
import hashlib
import inspect
import json
import math
import re
import subprocess
import textwrap
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Awaitable, Callable

import pytest

import probos.federation.bridge as bridge_module
import probos.federation.mock_transport as mock_transport_module
import probos.federation.nats_transport as nats_transport_module
import probos.federation.relay as relay_module
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
from probos.federation.bridge import FederationBridge
from probos.federation.mock_transport import (
    MockFederationTransport,
    MockTransportBus,
)
from probos.federation.nats_transport import NATSFederationTransport
from probos.federation.relay import (
    MAX_RELAY_DEPTH,
    MAX_RELAY_ENVELOPE_BYTES,
    MAX_RELAY_NODES,
    MAX_RELAY_STRING_CHARS,
    MAX_RELAY_STRING_UTF8_BYTES,
    MAX_RELAY_TOPICS,
    RELAY_RATE_LIMIT_PER_SECOND,
    FederationRelayTopic,
    build_relay_topic_registry,
    detach_relay_payload,
    extract_relay_wire_payload,
    finalize_relay_wire_payload,
    is_canonical_relay_topic,
    is_valid_relay_timestamp,
)
from probos.federation.router import FederationRouter
from probos.federation.transport import FederationTransport
from probos.mesh.intent import IntentBus
from probos.mesh.nats_bus import MockNATSBus
from probos.mesh.signal import SignalManager
from probos.startup.fleet_organization import organize_fleet
from probos.substrate.pool_group import PoolGroupRegistry
from probos.types import FederationMessage, IntentMessage, IntentResult, NodeSelfModel


_TOPIC = "test.telemetry.v1"
_DECOY_TOPIC = "test.decoy.v1"
_SAFE_AGENT_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_TEST_PAYLOAD_KEYS = frozenset({"agent_id", "frame_type", "data"})
_TEST_DATA_KEYS = frozenset({"sequence", "metrics"})
_TEST_METRIC_KEYS = frozenset({"temperature", "active", "labels"})


def _strict_test_payload_validator(payload: dict[str, Any]) -> bool:
    """Test-only exact semantic contract; intentionally not allow-all."""
    if type(payload) is not dict or set(dict.keys(payload)) != _TEST_PAYLOAD_KEYS:
        return False
    agent_id = dict.__getitem__(payload, "agent_id")
    frame_type = dict.__getitem__(payload, "frame_type")
    data = dict.__getitem__(payload, "data")
    if (
        type(agent_id) is not str
        or _SAFE_AGENT_RE.fullmatch(agent_id) is None
        or type(frame_type) is not str
        or frame_type not in {"snapshot", "diff"}
        or type(data) is not dict
        or set(dict.keys(data)) != _TEST_DATA_KEYS
    ):
        return False
    sequence = dict.__getitem__(data, "sequence")
    metrics = dict.__getitem__(data, "metrics")
    if (
        type(sequence) is not int
        or sequence < 0
        or sequence > 1_000_000
        or type(metrics) is not dict
        or set(dict.keys(metrics)) != _TEST_METRIC_KEYS
    ):
        return False
    temperature = dict.__getitem__(metrics, "temperature")
    active = dict.__getitem__(metrics, "active")
    labels = dict.__getitem__(metrics, "labels")
    if (
        type(temperature) is not float
        or not math.isfinite(temperature)
        or temperature < -100.0
        or temperature > 100.0
        or type(active) is not bool
        or type(labels) is not list
        or list.__len__(labels) > 8
    ):
        return False
    for index in range(list.__len__(labels)):
        label = list.__getitem__(labels, index)
        if type(label) is not str or not label or str.__len__(label) > 64:
            return False
    return True


async def _noop_sink(_source_node: str, _payload: dict[str, Any]) -> None:
    return None


def _valid_payload(
    sequence: int = 1,
    *,
    frame_type: str = "snapshot",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "agent_id": "agent-001",
        "frame_type": frame_type,
        "data": {
            "sequence": sequence,
            "metrics": {
                "temperature": 21.5,
                "active": True,
                "labels": ["nominal"] if labels is None else labels,
            },
        },
    }


def _topic(
    sink: Callable[[str, dict[str, Any]], Awaitable[None]] = _noop_sink,
    *,
    name: str = _TOPIC,
    validator: Callable[[dict[str, Any]], bool] = _strict_test_payload_validator,
) -> FederationRelayTopic:
    return FederationRelayTopic(
        name=name,
        validate_payload=validator,
        sink=sink,
    )


def _federation_config(
    *,
    node_id: str,
    peer_ids: list[str],
) -> FederationConfig:
    return FederationConfig(
        enabled=True,
        node_id=node_id,
        peers=[
            PeerConfig(
                node_id=peer_id,
                address=f"tcp://127.0.0.1:{65000 + index}",
            )
            for index, peer_id in enumerate(peer_ids)
        ],
        forward_timeout_ms=100,
        gossip_interval_seconds=1_000.0,
        validate_remote_results=False,
    )


def _system_config(*, node_id: str, peer_ids: list[str]) -> SystemConfig:
    return SystemConfig(
        federation=_federation_config(node_id=node_id, peer_ids=peer_ids),
        scaling=ScalingConfig(enabled=False),
        utility_agents=UtilityAgentsConfig(enabled=False),
        medical=MedicalConfig(enabled=False),
        self_mod=SelfModConfig(enabled=False),
    )


async def _organize_node(
    *,
    node_id: str,
    peer_ids: list[str],
    nats_bus: MockNATSBus,
    relay_topics: tuple[FederationRelayTopic, ...],
) -> Any:
    config = _system_config(node_id=node_id, peer_ids=peer_ids)
    return await organize_fleet(
        config=config,
        pools={},
        pool_groups=PoolGroupRegistry(),
        escalation_manager=SimpleNamespace(),
        intent_bus=IntentBus(SignalManager()),
        trust_network=SimpleNamespace(),
        llm_client=SimpleNamespace(),
        build_pool_intent_map_fn=dict,
        find_consensus_pools_fn=set,
        build_self_model_fn=lambda: NodeSelfModel(node_id=node_id),
        validate_remote_result_fn=None,
        attachment_resolver_fn=None,
        relay_topics=relay_topics,
        nats_bus=nats_bus,
    )


async def _stop_organized(result: Any) -> None:
    if result is None:
        return
    if result.federation_bridge is not None:
        await result.federation_bridge.stop()
    if result.federation_transport is not None:
        await result.federation_transport.stop()


class _CaptureTransport:
    def __init__(
        self,
        *,
        connected_peers: list[str] | None = None,
        send_error: BaseException | None = None,
    ) -> None:
        self._connected_peers = ["node-b"] if connected_peers is None else connected_peers
        self.send_error = send_error
        self.sent: list[tuple[str, FederationMessage]] = []
        self.broadcasts: list[FederationMessage] = []
        self.delivered_responses: list[tuple[str, FederationMessage]] = []
        self.request_calls = 0
        self.receive_calls = 0
        self._inbound_handler: Any = None

    @property
    def connected_peers(self) -> list[str]:
        return list(self._connected_peers)

    async def send_to_peer(
        self,
        peer_node_id: str,
        message: FederationMessage,
    ) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append((peer_node_id, message))

    async def send_to_all_peers(self, message: FederationMessage) -> list[str]:
        self.broadcasts.append(message)
        return list(self._connected_peers)

    async def deliver_response(
        self,
        source_node: str,
        message: FederationMessage,
    ) -> None:
        self.delivered_responses.append((source_node, message))

    async def request_peer(
        self,
        _peer_node_id: str,
        _message: FederationMessage,
        _timeout_ms: int,
    ) -> FederationMessage | None:
        self.request_calls += 1
        return None

    async def receive_with_timeout(
        self,
        _peer_node_id: str,
        _timeout_ms: int,
    ) -> FederationMessage | None:
        self.receive_calls += 1
        return None


class _CountingIntentBus(IntentBus):
    def __init__(self) -> None:
        super().__init__(SignalManager())
        self.broadcast_calls = 0
        self.send_calls = 0

    async def broadcast(
        self,
        intent: IntentMessage,
        timeout: float | None = None,
        *,
        federated: bool = True,
        raise_on_denial: bool = False,
    ) -> list[IntentResult]:
        self.broadcast_calls += 1
        return await super().broadcast(
            intent,
            timeout=timeout,
            federated=federated,
            raise_on_denial=raise_on_denial,
        )

    async def send(self, intent: IntentMessage) -> IntentResult | None:
        self.send_calls += 1
        return await super().send(intent)


class _OutcomeRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def record_outcome(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


def _make_bridge(
    *,
    node_id: str = "node-a",
    peer_ids: list[str] | None = None,
    transport: Any | None = None,
    relay_topics: tuple[FederationRelayTopic, ...] | None = None,
    intent_bus: IntentBus | None = None,
    trust_network: Any | None = None,
    hebbian_map: Any | None = None,
) -> tuple[FederationBridge, Any, IntentBus]:
    actual_peers = ["node-b"] if peer_ids is None else peer_ids
    actual_transport = transport or _CaptureTransport(connected_peers=actual_peers)
    actual_bus = intent_bus or _CountingIntentBus()
    bridge = FederationBridge(
        node_id=node_id,
        transport=actual_transport,
        router=FederationRouter(),
        intent_bus=actual_bus,
        config=_federation_config(node_id=node_id, peer_ids=actual_peers),
        self_model_fn=lambda: NodeSelfModel(node_id=node_id),
        trust_network=trust_network,
        hebbian_map=hebbian_map,
        relay_topics=(_topic(),) if relay_topics is None else relay_topics,
    )
    return bridge, actual_transport, actual_bus


def _relay_message(
    *,
    source_node: str = "node-a",
    target_node_id: str = "node-b",
    topic: str = _TOPIC,
    payload: Any = None,
    relay_version: Any = 1,
    hop_count: Any = 0,
    message_id: Any = "relay-message-001",
    timestamp: Any = 0.0,
) -> FederationMessage:
    return FederationMessage(
        type="relay_one_way",
        source_node=source_node,
        message_id=message_id,
        payload={
            "relay_version": relay_version,
            "target_node_id": target_node_id,
            "topic": topic,
            "payload": _valid_payload() if payload is None else payload,
            "hop_count": hop_count,
        },
        timestamp=timestamp,
    )


def _wire_payload(payload: Any) -> dict[str, Any]:
    return {
        "relay_version": 1,
        "target_node_id": "node-b",
        "topic": _TOPIC,
        "payload": payload,
        "hop_count": 0,
    }


@pytest.mark.asyncio
async def test_two_organized_bridges_deliver_registered_topic_to_exact_receiver_sink_only() -> None:
    received: list[tuple[str, dict[str, Any]]] = []
    decoy: list[tuple[str, dict[str, Any]]] = []

    async def _receiver_sink(source: str, payload: dict[str, Any]) -> None:
        received.append((source, payload))

    async def _decoy_sink(source: str, payload: dict[str, Any]) -> None:
        decoy.append((source, payload))

    shared_bus = MockNATSBus()
    await shared_bus.start()
    origin = None
    receiver = None
    original = _valid_payload(sequence=7, labels=["headline"])
    try:
        origin = await _organize_node(
            node_id="node-a",
            peer_ids=["node-b"],
            nats_bus=shared_bus,
            relay_topics=(
                _topic(_noop_sink),
                _topic(_decoy_sink, name=_DECOY_TOPIC),
            ),
        )
        receiver = await _organize_node(
            node_id="node-b",
            peer_ids=["node-a"],
            nats_bus=shared_bus,
            relay_topics=(
                _topic(_receiver_sink),
                _topic(_decoy_sink, name=_DECOY_TOPIC),
            ),
        )

        accepted = await origin.federation_bridge.relay_one_way(
            "node-b", _TOPIC, original
        )
        original["data"]["metrics"]["labels"].append("mutated-after-send")

        assert accepted is True
        assert received == [(
            "node-a",
            _valid_payload(sequence=7, labels=["headline"]),
        )]
        assert decoy == []
        relay_publishes = [
            (subject, body)
            for subject, body in shared_bus.published
            if body.get("type") == "relay_one_way"
        ]
        assert len(relay_publishes) == 1
        assert relay_publishes[0][0] == "federation.intent.node-b"
    finally:
        await _stop_organized(receiver)
        await _stop_organized(origin)
        await shared_bus.stop()


@pytest.mark.asyncio
async def test_one_peer_addressing_publishes_once_and_never_reaches_third_node() -> None:
    received_b: list[str] = []
    received_c: list[str] = []

    async def _sink_b(source: str, _payload: dict[str, Any]) -> None:
        received_b.append(source)

    async def _sink_c(source: str, _payload: dict[str, Any]) -> None:
        received_c.append(source)

    shared_bus = MockNATSBus()
    await shared_bus.start()
    results: list[Any] = []
    try:
        results.append(await _organize_node(
            node_id="node-a",
            peer_ids=["node-b", "node-c"],
            nats_bus=shared_bus,
            relay_topics=(_topic(),),
        ))
        results.append(await _organize_node(
            node_id="node-b",
            peer_ids=["node-a"],
            nats_bus=shared_bus,
            relay_topics=(_topic(_sink_b),),
        ))
        results.append(await _organize_node(
            node_id="node-c",
            peer_ids=["node-a"],
            nats_bus=shared_bus,
            relay_topics=(_topic(_sink_c),),
        ))

        assert await results[0].federation_bridge.relay_one_way(
            "node-b", _TOPIC, _valid_payload()
        ) is True

        assert received_b == ["node-a"]
        assert received_c == []
        subjects = [
            subject
            for subject, body in shared_bus.published
            if body.get("type") == "relay_one_way"
        ]
        assert subjects == ["federation.intent.node-b"]
    finally:
        for result in reversed(results):
            await _stop_organized(result)
        await shared_bus.stop()


@pytest.mark.asyncio
async def test_receiver_invokes_only_exact_registered_sink() -> None:
    exact: list[str] = []
    decoy: list[str] = []

    async def _exact(source: str, _payload: dict[str, Any]) -> None:
        exact.append(source)

    async def _decoy(source: str, _payload: dict[str, Any]) -> None:
        decoy.append(source)

    bridge, transport, bus = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        relay_topics=(
            _topic(_exact),
            _topic(_decoy, name=_DECOY_TOPIC),
        ),
    )

    await bridge.handle_inbound(_relay_message())
    await bridge.handle_inbound(_relay_message(topic="test.unregistered.v1"))

    assert exact == ["node-a"]
    assert decoy == []
    assert transport.sent == []
    assert transport.delivered_responses == []
    assert bus.broadcast_calls == 0
    assert bus.send_calls == 0


@pytest.mark.asyncio
async def test_sender_rejects_unregistered_topic_before_transport() -> None:
    bridge, transport, _ = _make_bridge()

    accepted = await bridge.relay_one_way(
        "node-b", "test.unregistered.v1", _valid_payload()
    )

    assert accepted is False
    assert transport.sent == []


@pytest.mark.asyncio
async def test_receiver_empty_registry_drops_before_payload_traversal_or_rate_allocation() -> None:
    bridge, transport, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        relay_topics=(),
    )
    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic

    await bridge.handle_inbound(_relay_message(payload=cyclic))

    assert transport.sent == []
    assert bridge._relay_rate == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["node-c", "node-b", "bad.source"])
async def test_unconfigured_self_and_malformed_sources_drop_before_validator_sink_or_response(
    source: str,
) -> None:
    validator_calls = 0
    sink_calls = 0

    def _validator(payload: dict[str, Any]) -> bool:
        nonlocal validator_calls
        validator_calls += 1
        return _strict_test_payload_validator(payload)

    async def _sink(_source: str, _payload: dict[str, Any]) -> None:
        nonlocal sink_calls
        sink_calls += 1

    bridge, transport, bus = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        relay_topics=(_topic(_sink, validator=_validator),),
    )

    await bridge.handle_inbound(_relay_message(source_node=source))

    assert validator_calls == 0
    assert sink_calls == 0
    assert transport.sent == []
    assert transport.delivered_responses == []
    assert bus.broadcast_calls == 0
    assert bus.send_calls == 0


@pytest.mark.asyncio
async def test_wrong_target_drops_before_validator_sink_and_response() -> None:
    validator_calls = 0
    sink_calls = 0

    def _validator(payload: dict[str, Any]) -> bool:
        nonlocal validator_calls
        validator_calls += 1
        return _strict_test_payload_validator(payload)

    async def _sink(_source: str, _payload: dict[str, Any]) -> None:
        nonlocal sink_calls
        sink_calls += 1

    bridge, transport, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        relay_topics=(_topic(_sink, validator=_validator),),
    )

    await bridge.handle_inbound(_relay_message(target_node_id="node-c"))

    assert validator_calls == 0
    assert sink_calls == 0
    assert transport.sent == []


@pytest.mark.asyncio
async def test_exact_five_key_schema_rejects_missing_extra_bad_key_and_dict_subclass() -> None:
    class _DictSubclass(dict):
        pass

    bridge, transport, _ = _make_bridge(node_id="node-b", peer_ids=["node-a"])
    messages: list[FederationMessage] = []
    missing = _relay_message()
    missing.payload.pop("hop_count")
    messages.append(missing)
    extra = _relay_message()
    extra.payload["extra"] = True
    messages.append(extra)
    bad_key = _relay_message()
    bad_key.payload[7] = bad_key.payload.pop("hop_count")
    messages.append(bad_key)
    subclassed = _relay_message()
    subclassed.payload = _DictSubclass(subclassed.payload)
    messages.append(subclassed)

    for message in messages:
        await bridge.handle_inbound(message)

    assert transport.sent == []
    assert bridge._relay_rate == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("relay_version", True),
        ("relay_version", 1.0),
        ("relay_version", 2),
        ("relay_version", "1"),
        ("hop_count", False),
        ("hop_count", 0.0),
        ("hop_count", 1),
        ("hop_count", "0"),
    ],
)
async def test_exact_version_and_zero_hop_are_required(field: str, value: Any) -> None:
    bridge, transport, _ = _make_bridge(node_id="node-b", peer_ids=["node-a"])
    kwargs = {field: value}

    await bridge.handle_inbound(_relay_message(**kwargs))

    assert transport.sent == []
    assert bridge._relay_rate == {}


@pytest.mark.asyncio
async def test_inbound_requires_safe_correlation_and_finite_exact_timestamp() -> None:
    bridge, transport, _ = _make_bridge(node_id="node-b", peer_ids=["node-a"])
    invalid = [
        _relay_message(message_id=""),
        _relay_message(message_id="bad.id"),
        _relay_message(message_id="x" * 129),
        _relay_message(message_id=7),
        _relay_message(timestamp=True),
        _relay_message(timestamp="0"),
        _relay_message(timestamp=float("nan")),
        _relay_message(timestamp=float("inf")),
        _relay_message(timestamp=2**63),
        _relay_message(timestamp=-(2**63) - 1),
        _relay_message(timestamp=10**10_000),
        _relay_message(timestamp=_HostileInt(1)),
        _relay_message(timestamp=_HostileFloat(1.0)),
    ]

    for message in invalid:
        await bridge.handle_inbound(message)

    assert transport.sent == []
    assert bridge._relay_rate == {}


@pytest.mark.asyncio
async def test_outbound_target_and_topic_admission_rejects_before_payload_work() -> None:
    transport = _CaptureTransport(connected_peers=["node-b"])
    bridge, _, _ = _make_bridge(transport=transport)
    invalid_targets: list[Any] = ["", "node-a", "node-c", "bad.node", "x" * 129, 7]
    invalid_topics: list[Any] = ["", "Test.Telemetry", ".bad", "bad topic", "x" * 65, 7]
    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic

    for target in invalid_targets:
        assert await bridge.relay_one_way(target, _TOPIC, cyclic) is False
    for topic in invalid_topics:
        assert await bridge.relay_one_way("node-b", topic, cyclic) is False
    transport._connected_peers = []
    assert await bridge.relay_one_way("node-b", _TOPIC, cyclic) is False

    assert transport.sent == []


def test_topic_registry_is_exact_bounded_canonical_frozen_and_duplicate_safe() -> None:
    class _TupleSubclass(tuple):
        pass

    class _TopicSubclass(FederationRelayTopic):
        pass

    valid = _topic()
    registry = build_relay_topic_registry((valid,))
    assert isinstance(registry, MappingProxyType)
    assert dict(registry) == {_TOPIC: valid}
    with pytest.raises(TypeError):
        registry[_DECOY_TOPIC] = _topic(name=_DECOY_TOPIC)

    invalid_inputs: list[Any] = [
        [valid],
        _TupleSubclass((valid,)),
        tuple(_topic(name=f"test.topic-{index}") for index in range(MAX_RELAY_TOPICS + 1)),
        (valid, valid),
        (_topic(name="Bad.Topic"),),
        (_topic(name="x" * 65),),
        (_TopicSubclass(_TOPIC, _strict_test_payload_validator, _noop_sink),),
    ]
    for value in invalid_inputs:
        with pytest.raises(ValueError):
            build_relay_topic_registry(value)


def test_topic_registry_rejects_bad_validator_and_sink_contracts() -> None:
    def _validator_zero() -> bool:
        return True

    def _validator_two(_payload: dict[str, Any], _extra: Any) -> bool:
        return True

    def _validator_variadic(*_args: Any) -> bool:
        return True

    async def _validator_async(_payload: dict[str, Any]) -> bool:
        return True

    def _sink_sync(_source: str, _payload: dict[str, Any]) -> None:
        return None

    async def _sink_one(_source: str) -> None:
        return None

    async def _sink_three(
        _source: str,
        _payload: dict[str, Any],
        _extra: Any,
    ) -> None:
        return None

    async def _sink_variadic(*_args: Any) -> None:
        return None

    bad_contracts = [
        FederationRelayTopic(_TOPIC, _validator_zero, _noop_sink),
        FederationRelayTopic(_TOPIC, _validator_two, _noop_sink),
        FederationRelayTopic(_TOPIC, _validator_variadic, _noop_sink),
        FederationRelayTopic(_TOPIC, _validator_async, _noop_sink),
        FederationRelayTopic(_TOPIC, _strict_test_payload_validator, _sink_sync),
        FederationRelayTopic(_TOPIC, _strict_test_payload_validator, _sink_one),
        FederationRelayTopic(_TOPIC, _strict_test_payload_validator, _sink_three),
        FederationRelayTopic(_TOPIC, _strict_test_payload_validator, _sink_variadic),
        FederationRelayTopic(_TOPIC, None, _noop_sink),
        FederationRelayTopic(_TOPIC, _strict_test_payload_validator, None),
    ]
    for contract in bad_contracts:
        with pytest.raises(ValueError):
            build_relay_topic_registry((contract,))


def test_topic_name_predicate_is_exact_and_canonical() -> None:
    assert is_canonical_relay_topic("a") is True
    assert is_canonical_relay_topic(_TOPIC) is True
    assert is_canonical_relay_topic("a" * 64) is True
    for value in ("", "A", "1topic", "a topic", ".topic", "a" * 65, 1):
        assert is_canonical_relay_topic(value) is False


@pytest.mark.asyncio
async def test_nested_payload_round_trip_is_deeply_detached_without_aliasing() -> None:
    seen: list[dict[str, Any]] = []

    async def _sink(_source: str, payload: dict[str, Any]) -> None:
        seen.append(payload)

    bus = MockTransportBus()
    origin_transport = MockFederationTransport("node-a", bus)
    receiver_transport = MockFederationTransport("node-b", bus)
    origin, _, _ = _make_bridge(
        node_id="node-a",
        peer_ids=["node-b"],
        transport=origin_transport,
        relay_topics=(_topic(),),
    )
    receiver, _, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        transport=receiver_transport,
        relay_topics=(_topic(_sink),),
    )
    await origin.start()
    await receiver.start()
    payload = _valid_payload(labels=["one", "two"])
    baseline = copy.deepcopy(payload)
    try:
        assert await origin.relay_one_way("node-b", _TOPIC, payload) is True
        payload["data"]["metrics"]["labels"][0] = "changed"
    finally:
        await receiver.stop()
        await origin.stop()

    assert seen == [baseline]
    assert seen[0] is not payload
    assert seen[0]["data"] is not payload["data"]


def _nested_payload(container_count: int) -> dict[str, Any]:
    value: Any = "leaf"
    for _ in range(container_count):
        value = [value]
    return {"value": value}


def test_depth_boundary_accepts_depth_eight_and_rejects_depth_nine() -> None:
    accepted = _nested_payload(MAX_RELAY_DEPTH - 1)
    rejected = _nested_payload(MAX_RELAY_DEPTH)

    assert detach_relay_payload(accepted) == accepted
    with pytest.raises(ValueError, match="relay_payload_invalid"):
        detach_relay_payload(rejected)


def test_node_boundary_counts_root_keys_containers_and_values() -> None:
    exact = {"items": [None] * (MAX_RELAY_NODES - 3)}
    over = {"items": [None] * (MAX_RELAY_NODES - 2)}

    assert detach_relay_payload(exact) == exact
    with pytest.raises(ValueError, match="relay_payload_invalid"):
        detach_relay_payload(over)


def test_string_and_key_character_boundaries_are_exact() -> None:
    exact_value = {"value": "x" * MAX_RELAY_STRING_CHARS}
    exact_key = {"k" * MAX_RELAY_STRING_CHARS: None}
    assert detach_relay_payload(exact_value) == exact_value
    assert detach_relay_payload(exact_key) == exact_key

    for payload in (
        {"value": "x" * (MAX_RELAY_STRING_CHARS + 1)},
        {"k" * (MAX_RELAY_STRING_CHARS + 1): None},
    ):
        with pytest.raises(ValueError, match="relay_payload_invalid"):
            detach_relay_payload(payload)


def test_aggregate_utf8_boundary_counts_keys_and_string_values() -> None:
    exact = {"v": ["x" * 4_096 for _ in range(7)] + ["x" * 4_095]}
    over = {"v": ["x" * 4_096 for _ in range(8)]}

    detached = detach_relay_payload(exact)
    assert detached == exact
    assert sum(
        len(value.encode("utf-8"))
        for value in detached["v"]
    ) + len("v".encode("utf-8")) == MAX_RELAY_STRING_UTF8_BYTES
    with pytest.raises(ValueError, match="relay_payload_invalid"):
        detach_relay_payload(over)


def _complete_wire_size(payload: dict[str, Any]) -> int:
    wire = {
        "type": "relay_one_way",
        "source_node": "node-a",
        "message_id": "fixed-message-id",
        "payload": _wire_payload(payload),
        "timestamp": 0.0,
    }
    return len(json.dumps(
        wire,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8"))


def test_complete_final_envelope_byte_cap_has_exact_success_and_one_byte_rejection() -> None:
    chunks = ["x" * 4_096 for _ in range(7)]
    chosen: dict[str, Any] | None = None
    for tail_length in range(4_097):
        candidate = {"chunks": [*chunks, "x" * tail_length]}
        if _complete_wire_size(candidate) == MAX_RELAY_ENVELOPE_BYTES:
            chosen = candidate
            break
    assert chosen is not None
    assert sum(len(v.encode("utf-8")) for v in chosen["chunks"]) + len(
        "chunks".encode("utf-8")
    ) < MAX_RELAY_STRING_UTF8_BYTES

    finalized = finalize_relay_wire_payload(
        source_node="node-a",
        message_id="fixed-message-id",
        relay_payload=_wire_payload(chosen),
        timestamp=0.0,
    )
    over = copy.deepcopy(chosen)
    over["chunks"][-1] += "x"

    assert finalized is not None
    assert finalized["payload"] == chosen
    assert finalize_relay_wire_payload(
        source_node="node-a",
        message_id="fixed-message-id",
        relay_payload=_wire_payload(over),
        timestamp=0.0,
    ) is None


def test_signed_int64_boundaries_accept_exact_and_reject_overflow() -> None:
    exact = {"minimum": -(2**63), "maximum": 2**63 - 1}
    assert detach_relay_payload(exact) == exact
    for value in (-(2**63) - 1, 2**63):
        with pytest.raises(ValueError, match="relay_payload_invalid"):
            detach_relay_payload({"value": value})


def test_sender_timestamp_metadata_is_exact_finite_and_signed_int64_bounded() -> None:
    for value in (-(2**63), 2**63 - 1, -1.5, 0.0, 1.5):
        assert is_valid_relay_timestamp(value) is True
    for value in (
        True,
        2**63,
        -(2**63) - 1,
        10**10_000,
        math.nan,
        math.inf,
        -math.inf,
        _HostileInt(1),
        _HostileFloat(1.0),
        "0",
    ):
        assert is_valid_relay_timestamp(value) is False
        assert finalize_relay_wire_payload(
            source_node="node-a",
            message_id="fixed-message-id",
            relay_payload=_wire_payload({}),
            timestamp=value,
        ) is None


class _HostileList(list):
    touched = 0

    def __iter__(self):
        type(self).touched += 1
        raise AssertionError("list override invoked")

    def __len__(self):
        type(self).touched += 1
        raise AssertionError("list override invoked")

    def __getitem__(self, _key: Any):
        type(self).touched += 1
        raise AssertionError("list override invoked")


class _HostileDict(dict):
    touched = 0

    def items(self):
        type(self).touched += 1
        raise AssertionError("dict override invoked")

    def keys(self):
        type(self).touched += 1
        raise AssertionError("dict override invoked")

    def __len__(self):
        type(self).touched += 1
        raise AssertionError("dict override invoked")

    def __getitem__(self, _key: Any):
        type(self).touched += 1
        raise AssertionError("dict override invoked")


class _HostileString(str):
    touched = 0

    def encode(self, *_args: Any, **_kwargs: Any):
        type(self).touched += 1
        raise AssertionError("string override invoked")

    def lower(self):
        type(self).touched += 1
        raise AssertionError("string override invoked")


class _HostileInt(int):
    touched = 0

    def __int__(self):
        type(self).touched += 1
        raise AssertionError("int override invoked")


class _HostileFloat(float):
    touched = 0

    def __float__(self):
        type(self).touched += 1
        raise AssertionError("float override invoked")


class _HostileListElement:
    touched = 0

    def __getattribute__(self, name: str) -> Any:
        if name != "touched":
            type(self).touched += 1
            raise AssertionError("oversized list element was inspected")
        return object.__getattribute__(self, name)


class _HostileDictKey:
    touched = 0

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, _other: Any) -> bool:
        type(self).touched += 1
        raise AssertionError("oversized dict key was compared")


@pytest.mark.parametrize(
    ("factory", "hostile_type"),
    [
        (lambda: _HostileList([1]), _HostileList),
        (lambda: _HostileDict({"safe": 1}), _HostileDict),
        (lambda: _HostileString("safe"), _HostileString),
        (lambda: _HostileInt(1), _HostileInt),
        (lambda: _HostileFloat(1.0), _HostileFloat),
    ],
)
def test_hostile_subclasses_are_rejected_without_invoking_overrides(
    factory: Callable[[], Any],
    hostile_type: type,
) -> None:
    hostile_type.touched = 0
    value = factory()
    with pytest.raises(ValueError, match="relay_payload_invalid"):
        detach_relay_payload({"value": value})
    assert hostile_type.touched == 0


@dataclass
class _ModelValue:
    value: int


def test_non_json_exact_types_are_rejected() -> None:
    for value in (
        (1, 2),
        {1, 2},
        frozenset({1}),
        b"binary",
        bytearray(b"binary"),
        memoryview(b"binary"),
        Decimal("1"),
        _ModelValue(1),
        object(),
    ):
        with pytest.raises(ValueError, match="relay_payload_invalid"):
            detach_relay_payload({"value": value})


def test_cycles_nonfinite_and_binary_reject_before_final_serialization() -> None:
    self_cycle: list[Any] = []
    self_cycle.append(self_cycle)
    first: list[Any] = []
    second = [first]
    first.append(second)
    invalid = [self_cycle, first, math.nan, math.inf, -math.inf, b"x"]
    for value in invalid:
        with pytest.raises(ValueError, match="relay_payload_invalid"):
            detach_relay_payload({"value": value})


def test_every_forbidden_secret_key_is_rejected_at_nested_depths() -> None:
    forbidden = (
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "authorization",
        "cookie",
        "set-cookie",
        "private_key",
        "client_secret",
    )
    for index, key in enumerate(forbidden):
        variants = (key, key.upper(), key.title())
        for variant in variants:
            payload = {"safe": [{"depth": {variant: f"value-{index}"}}]}
            with pytest.raises(ValueError, match="relay_payload_invalid"):
                detach_relay_payload(payload)


def test_every_credential_data_and_private_key_prefix_is_rejected_with_case_and_whitespace() -> None:
    forbidden = (
        "data:text/plain;base64,AAAA",
        "Bearer credential",
        "Basic credential",
        "-----BEGIN PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
    )
    for value in forbidden:
        for variant in (value, value.swapcase(), f" \t\r\n{value}"):
            with pytest.raises(ValueError, match="relay_payload_invalid"):
                detach_relay_payload({"safe": variant})

    for accepted in ("bearer", "bearer-token", "basic", "database: value"):
        assert detach_relay_payload({"safe": accepted}) == {"safe": accepted}


@pytest.mark.asyncio
async def test_rejection_logs_never_include_payload_values_keys_hashes_or_bodies(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG", logger="probos.federation.bridge")
    canary_key = "TOKEN"
    canary_value = "CANARY_SUPER_SECRET_VALUE"
    bridge, transport, _ = _make_bridge()

    assert await bridge.relay_one_way(
        "node-b",
        _TOPIC,
        {canary_key: canary_value},
    ) is False

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert transport.sent == []
    assert canary_key not in rendered
    assert canary_value not in rendered
    assert hashlib.sha256(canary_value.encode()).hexdigest() not in rendered
    assert "{'" not in rendered


def test_million_entry_containers_fail_before_json_or_entry_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_called = False

    def _unexpected_json(*_args: Any, **_kwargs: Any) -> str:
        nonlocal json_called
        json_called = True
        raise AssertionError("generic JSON ran before bounded admission")

    monkeypatch.setattr(relay_module.json, "dumps", _unexpected_json)
    million_list = [None] * 1_000_000
    million_dict = dict.fromkeys(range(1_000_000))

    with pytest.raises(ValueError, match="relay_payload_invalid"):
        detach_relay_payload({"items": million_list})
    with pytest.raises(ValueError, match="relay_payload_invalid"):
        detach_relay_payload(million_dict)

    _HostileString.touched = 0
    hostile_key_payload = {_HostileString("safe"): None}
    with pytest.raises(ValueError, match="relay_payload_invalid"):
        detach_relay_payload(hostile_key_payload)
    assert _HostileString.touched == 0
    assert json_called is False


def test_impossible_container_lengths_reject_before_inspecting_hostile_entries() -> None:
    _HostileListElement.touched = 0
    bomb = _HostileListElement()
    oversized_list = [bomb] * MAX_RELAY_NODES
    with pytest.raises(ValueError, match="relay_payload_invalid"):
        detach_relay_payload({"items": oversized_list})
    assert _HostileListElement.touched == 0

    _HostileDictKey.touched = 0
    oversized_dict = {
        _HostileDictKey(): None for _ in range(MAX_RELAY_NODES)
    }
    with pytest.raises(ValueError, match="relay_payload_invalid"):
        detach_relay_payload(oversized_dict)
    assert _HostileDictKey.touched == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("validator_kind", "accepted"),
    [("true", True), ("false", False), ("truthy", False), ("exception", False)],
)
async def test_validator_requires_literal_true_and_contains_ordinary_exception(
    validator_kind: str,
    accepted: bool,
) -> None:
    def _validator(payload: dict[str, Any]) -> Any:
        assert _strict_test_payload_validator(payload)
        if validator_kind == "true":
            return True
        if validator_kind == "false":
            return False
        if validator_kind == "truthy":
            return 1
        raise RuntimeError("validator private failure")

    bridge, transport, _ = _make_bridge(
        relay_topics=(_topic(validator=_validator),),
    )

    result = await bridge.relay_one_way("node-b", _TOPIC, _valid_payload())

    assert result is accepted
    assert len(transport.sent) == (1 if accepted else 0)


@pytest.mark.asyncio
async def test_mutating_validators_receive_isolated_copies_outbound_and_inbound() -> None:
    def _mutating_validator(payload: dict[str, Any]) -> bool:
        assert _strict_test_payload_validator(payload)
        payload["agent_id"] = "mutated-validator"
        payload["data"]["metrics"]["labels"].append("mutated-validator")
        return True

    outbound, transport, _ = _make_bridge(
        relay_topics=(_topic(validator=_mutating_validator),),
    )
    original = _valid_payload(labels=["safe"])
    assert await outbound.relay_one_way("node-b", _TOPIC, original) is True
    sent_payload = transport.sent[0][1].payload["payload"]
    assert sent_payload == original

    seen: list[dict[str, Any]] = []

    async def _sink(_source: str, payload: dict[str, Any]) -> None:
        seen.append(payload)

    inbound, _, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        relay_topics=(_topic(_sink, validator=_mutating_validator),),
    )
    await inbound.handle_inbound(_relay_message(payload=original))

    assert seen == [original]
    assert "mutated-validator" not in seen[0]["data"]["metrics"]["labels"]


class _SinkCanaryError(RuntimeError):
    def __str__(self) -> str:
        raise AssertionError("sink error message was inspected")


@pytest.mark.asyncio
async def test_sink_ordinary_exception_is_contained_type_only_without_response_or_retry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    exact_calls = 0
    decoy_calls = 0

    async def _failing_sink(_source: str, _payload: dict[str, Any]) -> None:
        nonlocal exact_calls
        exact_calls += 1
        raise _SinkCanaryError("CANARY_SINK_SECRET")

    async def _decoy_sink(_source: str, _payload: dict[str, Any]) -> None:
        nonlocal decoy_calls
        decoy_calls += 1

    caplog.set_level("WARNING", logger="probos.federation.bridge")
    bridge, transport, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        relay_topics=(
            _topic(_failing_sink),
            _topic(_decoy_sink, name=_DECOY_TOPIC),
        ),
    )

    await bridge.handle_inbound(_relay_message())

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert exact_calls == 1
    assert decoy_calls == 0
    assert transport.sent == []
    assert transport.delivered_responses == []
    assert "_SinkCanaryError" in rendered
    assert "CANARY_SINK_SECRET" not in rendered
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_direct_plugin_cancelled_error_is_contained_when_task_has_no_cancel_request() -> None:
    async def _direct_cancel(_source: str, _payload: dict[str, Any]) -> None:
        raise asyncio.CancelledError

    bridge, transport, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        relay_topics=(_topic(_direct_cancel),),
    )

    await bridge.handle_inbound(_relay_message())

    assert transport.sent == []


@pytest.mark.asyncio
async def test_real_inbound_task_cancellation_propagates_from_waiting_sink() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def _waiting_sink(_source: str, _payload: dict[str, Any]) -> None:
        entered.set()
        await release.wait()

    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        relay_topics=(_topic(_waiting_sink),),
    )
    task = asyncio.create_task(bridge.handle_inbound(_relay_message()))
    await entered.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_ordinary_transport_exception_returns_false_without_response_api() -> None:
    transport = _CaptureTransport(send_error=RuntimeError("private transport body"))
    bridge, _, _ = _make_bridge(transport=transport)

    accepted = await bridge.relay_one_way("node-b", _TOPIC, _valid_payload())

    assert accepted is False
    assert transport.request_calls == 0
    assert transport.receive_calls == 0
    assert transport.delivered_responses == []


@pytest.mark.asyncio
async def test_direct_transport_cancelled_error_propagates() -> None:
    transport = _CaptureTransport(send_error=asyncio.CancelledError())
    bridge, _, _ = _make_bridge(transport=transport)

    with pytest.raises(asyncio.CancelledError):
        await bridge.relay_one_way("node-b", _TOPIC, _valid_payload())


@pytest.mark.asyncio
async def test_real_outbound_task_cancellation_propagates_from_transport_await() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class _WaitingTransport(_CaptureTransport):
        async def send_to_peer(
            self,
            peer_node_id: str,
            message: FederationMessage,
        ) -> None:
            self.sent.append((peer_node_id, message))
            entered.set()
            await release.wait()

    bridge, _, _ = _make_bridge(transport=_WaitingTransport())
    task = asyncio.create_task(
        bridge.relay_one_way("node-b", _TOPIC, _valid_payload())
    )
    await entered.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_outbound_uses_exact_one_send_and_no_request_receive_or_response() -> None:
    bridge, transport, _ = _make_bridge()

    assert await bridge.relay_one_way("node-b", _TOPIC, _valid_payload()) is True

    assert len(transport.sent) == 1
    assert transport.sent[0][0] == "node-b"
    assert transport.sent[0][1].type == "relay_one_way"
    assert transport.request_calls == 0
    assert transport.receive_calls == 0
    assert transport.delivered_responses == []
    assert transport.broadcasts == []


@pytest.mark.asyncio
async def test_receiver_sixty_fifth_message_drops_before_detach_validator_and_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 100.0}
    monkeypatch.setattr(bridge_module.time, "monotonic", lambda: clock["now"])
    validator_calls = 0
    sink_calls = 0
    finalizer_calls = 0
    real_finalizer = bridge_module.finalize_relay_wire_payload

    def _validator(payload: dict[str, Any]) -> bool:
        nonlocal validator_calls
        validator_calls += 1
        return _strict_test_payload_validator(payload)

    async def _sink(_source: str, _payload: dict[str, Any]) -> None:
        nonlocal sink_calls
        sink_calls += 1

    def _count_finalizer(**kwargs: Any) -> dict[str, Any] | None:
        nonlocal finalizer_calls
        finalizer_calls += 1
        return real_finalizer(**kwargs)

    monkeypatch.setattr(bridge_module, "finalize_relay_wire_payload", _count_finalizer)
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        relay_topics=(_topic(_sink, validator=_validator),),
    )

    for sequence in range(RELAY_RATE_LIMIT_PER_SECOND + 1):
        await bridge.handle_inbound(
            _relay_message(payload=_valid_payload(sequence=sequence))
        )

    assert sink_calls == RELAY_RATE_LIMIT_PER_SECOND
    assert validator_calls == RELAY_RATE_LIMIT_PER_SECOND
    assert finalizer_calls == RELAY_RATE_LIMIT_PER_SECOND * 2
    assert len(bridge._relay_rate[("node-a", _TOPIC)]) == RELAY_RATE_LIMIT_PER_SECOND


@pytest.mark.asyncio
async def test_malformed_and_validator_rejected_messages_consume_no_valid_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge_module.time, "monotonic", lambda: 200.0)
    mode = {"accept": False}
    sink_calls = 0

    def _validator(payload: dict[str, Any]) -> bool:
        return mode["accept"] and _strict_test_payload_validator(payload)

    async def _sink(_source: str, _payload: dict[str, Any]) -> None:
        nonlocal sink_calls
        sink_calls += 1

    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        relay_topics=(_topic(_sink, validator=_validator),),
    )
    for _ in range(RELAY_RATE_LIMIT_PER_SECOND):
        await bridge.handle_inbound(_relay_message(payload={"malformed": True}))
        await bridge.handle_inbound(_relay_message(payload=_valid_payload()))
    assert bridge._relay_rate == {}

    mode["accept"] = True
    for sequence in range(RELAY_RATE_LIMIT_PER_SECOND):
        await bridge.handle_inbound(
            _relay_message(payload=_valid_payload(sequence=sequence))
        )

    assert sink_calls == RELAY_RATE_LIMIT_PER_SECOND


@pytest.mark.asyncio
async def test_rate_buckets_are_source_topic_isolated_and_cartesian_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bridge_module.time, "monotonic", lambda: 300.0)
    calls: list[tuple[str, str]] = []

    async def _sink_one(source: str, _payload: dict[str, Any]) -> None:
        calls.append((source, _TOPIC))

    async def _sink_two(source: str, _payload: dict[str, Any]) -> None:
        calls.append((source, _DECOY_TOPIC))

    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a", "node-c"],
        relay_topics=(
            _topic(_sink_one),
            _topic(_sink_two, name=_DECOY_TOPIC),
        ),
    )
    for source in ("node-a", "node-c"):
        for topic in (_TOPIC, _DECOY_TOPIC):
            await bridge.handle_inbound(_relay_message(source_node=source, topic=topic))
    await bridge.handle_inbound(_relay_message(source_node="node-x"))
    await bridge.handle_inbound(_relay_message(topic="test.unknown.v1"))

    assert set(calls) == {
        ("node-a", _TOPIC),
        ("node-a", _DECOY_TOPIC),
        ("node-c", _TOPIC),
        ("node-c", _DECOY_TOPIC),
    }
    assert len(bridge._relay_rate) == 4
    assert len(bridge._relay_rate) <= len(bridge._config.peers) * len(bridge._relay_topics)


@pytest.mark.asyncio
async def test_rate_window_recovers_and_prunes_empty_key_before_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 400.0}
    monkeypatch.setattr(bridge_module.time, "monotonic", lambda: clock["now"])
    mode = {"accept": True}
    sink_calls = 0

    def _validator(payload: dict[str, Any]) -> bool:
        return mode["accept"] and _strict_test_payload_validator(payload)

    async def _sink(_source: str, _payload: dict[str, Any]) -> None:
        nonlocal sink_calls
        sink_calls += 1

    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        relay_topics=(_topic(_sink, validator=_validator),),
    )
    for sequence in range(RELAY_RATE_LIMIT_PER_SECOND):
        await bridge.handle_inbound(
            _relay_message(payload=_valid_payload(sequence=sequence))
        )
    assert len(bridge._relay_rate[("node-a", _TOPIC)]) == RELAY_RATE_LIMIT_PER_SECOND

    clock["now"] += 1.001
    mode["accept"] = False
    await bridge.handle_inbound(_relay_message())
    assert bridge._relay_rate == {}

    mode["accept"] = True
    await bridge.handle_inbound(_relay_message())
    assert sink_calls == RELAY_RATE_LIMIT_PER_SECOND + 1
    assert len(bridge._relay_rate[("node-a", _TOPIC)]) == 1


@pytest.mark.asyncio
async def test_start_stop_clear_rate_state_and_restart_reopens_admission() -> None:
    sink_calls = 0

    async def _sink(_source: str, _payload: dict[str, Any]) -> None:
        nonlocal sink_calls
        sink_calls += 1

    bridge, transport, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        relay_topics=(_topic(_sink),),
    )
    await bridge.handle_inbound(_relay_message())
    assert bridge._relay_rate

    await bridge.stop()
    assert bridge._relay_rate == {}
    await bridge.handle_inbound(_relay_message())
    assert sink_calls == 1
    outbound, outbound_transport, _ = _make_bridge()
    await outbound.stop()
    assert await outbound.relay_one_way("node-b", _TOPIC, _valid_payload()) is False
    assert outbound_transport.sent == []

    await bridge.start()
    try:
        assert bridge._relay_rate == {}
        await bridge.handle_inbound(_relay_message())
    finally:
        await bridge.stop()
    assert sink_calls == 2
    assert transport.sent == []


@pytest.mark.asyncio
async def test_inbound_relay_is_terminal_without_loop_fanout_event_or_runtime_dispatch() -> None:
    sink_calls = 0

    async def _sink(_source: str, _payload: dict[str, Any]) -> None:
        nonlocal sink_calls
        sink_calls += 1

    bridge, transport, bus = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        relay_topics=(_topic(_sink),),
    )

    async def _forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("forbidden relay side effect")

    transport.send_to_peer = _forbidden
    transport.send_to_all_peers = _forbidden
    transport.deliver_response = _forbidden
    bus.broadcast = _forbidden
    bus.send = _forbidden
    bridge._emit_event = _forbidden

    await bridge.handle_inbound(_relay_message())
    await bridge.handle_inbound(_relay_message(hop_count=1))

    assert sink_calls == 1


@pytest.mark.asyncio
async def test_relay_send_receive_malformed_validator_and_sink_fail_do_not_touch_learning() -> None:
    trust = _OutcomeRecorder()
    hebbian = _OutcomeRecorder()

    def _reject(_payload: dict[str, Any]) -> bool:
        return False

    async def _fail_sink(_source: str, _payload: dict[str, Any]) -> None:
        raise RuntimeError("sink failure")

    outbound, _, _ = _make_bridge(trust_network=trust, hebbian_map=hebbian)
    assert await outbound.relay_one_way("node-b", _TOPIC, _valid_payload()) is True
    inbound, _, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        relay_topics=(
            _topic(_fail_sink),
            _topic(name=_DECOY_TOPIC, validator=_reject),
        ),
        trust_network=trust,
        hebbian_map=hebbian,
    )
    await inbound.handle_inbound(_relay_message())
    await inbound.handle_inbound(_relay_message(topic=_DECOY_TOPIC))
    await inbound.handle_inbound(_relay_message(payload={"bad": b"binary"}))

    assert trust.calls == []
    assert hebbian.calls == []


def test_nats_and_zeromq_relay_serializer_round_trip_parity_without_edits() -> None:
    message = _relay_message()
    nats = NATSFederationTransport(
        node_id="node-a",
        nats_bus=MockNATSBus(),
        peer_node_ids=["node-b"],
    )
    zmq = object.__new__(FederationTransport)

    nats_object = nats._serialize(message)
    zmq_object = json.loads(zmq._serialize(message).decode("utf-8"))

    assert nats_object == zmq_object
    assert nats._deserialize(nats_object) == zmq._deserialize(
        json.dumps(zmq_object).encode("utf-8")
    )


@pytest.mark.asyncio
async def test_mock_transport_round_trip_reaches_one_sink_and_no_response_queue() -> None:
    received: list[tuple[str, dict[str, Any]]] = []

    async def _sink(source: str, payload: dict[str, Any]) -> None:
        received.append((source, payload))

    bus = MockTransportBus()
    origin_transport = MockFederationTransport("node-a", bus)
    receiver_transport = MockFederationTransport("node-b", bus)
    origin, _, _ = _make_bridge(
        node_id="node-a",
        peer_ids=["node-b"],
        transport=origin_transport,
    )
    receiver, _, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        transport=receiver_transport,
        relay_topics=(_topic(_sink),),
    )
    await origin.start()
    await receiver.start()
    try:
        assert await origin.relay_one_way("node-b", _TOPIC, _valid_payload()) is True
    finally:
        await receiver.stop()
        await origin.stop()

    assert received == [("node-a", _valid_payload())]
    assert origin_transport._response_queues == {}
    assert receiver_transport._response_queues == {}
    assert origin_transport._pending_requests == {}
    assert receiver_transport._pending_requests == {}


@pytest.mark.asyncio
async def test_legacy_untargeted_intent_envelope_and_broadcast_remain_unchanged() -> None:
    transport = _CaptureTransport(connected_peers=["node-b"])
    origin, _, _ = _make_bridge(transport=transport)
    intent = IntentMessage(
        intent="legacy_read",
        params={"path": "safe.txt"},
        urgency=0.7,
        context="legacy",
        id="legacy-intent",
        ttl_seconds=12.0,
    )
    await origin.forward_intent(intent)
    assert transport.sent[0][1].payload == {
        "intent": "legacy_read",
        "params": {"path": "safe.txt"},
        "urgency": 0.7,
        "context": "legacy",
        "id": "legacy-intent",
        "ttl_seconds": 12.0,
    }

    receiver_transport = _CaptureTransport(connected_peers=["node-a"])
    receiver_bus = _CountingIntentBus()

    async def _handler(message: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=message.id,
            agent_id="legacy-agent",
            success=True,
        )

    receiver_bus.subscribe("legacy-agent", _handler, ["legacy_read"])
    receiver, _, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        transport=receiver_transport,
        intent_bus=receiver_bus,
    )
    await receiver.handle_inbound(transport.sent[0][1])
    assert receiver_bus.broadcast_calls == 1
    assert receiver_bus.send_calls == 0
    assert receiver_transport.sent[0][1].type == "intent_response"


@pytest.mark.asyncio
async def test_directed_dm_target_and_correlation_path_remains_available() -> None:
    class _DirectedTransport(_CaptureTransport):
        async def request_peer(
            self,
            peer_node_id: str,
            message: FederationMessage,
            _timeout_ms: int,
        ) -> FederationMessage | None:
            self.request_calls += 1
            return FederationMessage(
                type="intent_response",
                source_node=peer_node_id,
                message_id=message.message_id,
                payload={
                    "delivery_mode": "targeted_dm",
                    "results": [{
                        "intent_id": message.payload["id"],
                        "agent_id": message.payload["target_agent_id"],
                        "success": True,
                        "result": {"ok": True},
                        "error": None,
                        "confidence": 0.8,
                    }],
                },
            )

    transport = _DirectedTransport()
    bridge, _, _ = _make_bridge(transport=transport)
    intent = IntentMessage(
        intent="direct_message",
        params={"text": "hello"},
        id="directed-intent",
        ttl_seconds=1.0,
        target_agent_id="target-agent",
    )

    result = await bridge.forward_direct_message("node-b", intent)

    assert result.success is True
    assert result.agent_id == "target-agent"
    assert transport.request_calls == 1


_FROZEN_METHOD_HASHES = {
    ("src/probos/federation/bridge.py", "FederationBridge", "forward_intent"):
        "595c3fd2fc311b91f8ba3049909d0c383985dbdb15f9d9f19b35f806bf1a7eac",
    # BF-799 (#1263): rewritten deliberately, not as a side effect. The only
    # change to this method is putting the carried AD-1248 disclosure back onto
    # `metadata` after reconstruction, so a tool failure on a remote node is
    # visible to the Captain instead of being dropped at the hop. The bridge
    # still never interprets the payload -- `ToolFailures.from_wire` at the
    # local consumer validates it and degrades to empty on anything malformed.
    # Previous hash: 8189296e1b8902126031f0f9e35050c48eebce5f2e03ea142ecc968285595cb4
    ("src/probos/federation/bridge.py", "FederationBridge", "forward_direct_message"):
        "3d5920d7631f6d306d27315c7191133d362662a329158fb6eb76d1a5dc0b6de7",
    # AD-1276 (BF-789, #1253): rewritten deliberately, not as a side effect.
    # The local fan-out now opts into `raise_on_denial=True` so an AD-698
    # policy refusal is distinguishable from "no agent answered" -- both were
    # an empty `results` list, so the peer could not tell which it had -- and
    # any other exception becomes a reported failure in the response instead of
    # escaping to the transport and leaving the peer to time out. The envelope
    # is ADDITIVE: `results` is still carried unchanged, so a peer that
    # predates the `denied`/`error` keys behaves exactly as it did.
    # Previous hash: e9f950e1c291249f86a6181c1198284da4e783945540c486b148a21978a47348
    ("src/probos/federation/bridge.py", "FederationBridge", "_handle_intent_request"):
        "b47b8d1ca55923c744f1de056d7b921f8adc1856c56bbbc9a5115e87c86641de",
    ("src/probos/federation/bridge.py", "FederationBridge", "_send_directed_response"):
        "ba1ce85fdd6fb6c3f7e821795c92cc97d8d0f3eb39980145491649c46e8f35f2",
    ("src/probos/federation/bridge.py", "FederationBridge", "_handle_direct_message_request"):
        "3c42fe328f49c3667d4e19d8c8a5a9ce15d1c890de8d61bcac48686913487673",
    ("src/probos/federation/nats_transport.py", "NATSFederationTransport", "_serialize"):
        "1f45de4520164bcbb565259b2b9356ae0b42ad7a39434a1c85483dc37409cbbf",
    ("src/probos/federation/nats_transport.py", "NATSFederationTransport", "_deserialize"):
        "88b50d275a63b5a92db1d208350679c179dbc2906756b51d40ff1fad1524d8f1",
    ("src/probos/federation/nats_transport.py", "NATSFederationTransport", "send_to_peer"):
        "9ad857133b2532ae9d5176c9530724108d531ebf5f3b4779541f0f45581e1cd6",
    ("src/probos/federation/transport.py", "FederationTransport", "_serialize"):
        "11491399ff191d2fb65ff5f0480aafad8a0145f633359dcfd82b1a8b03c5f702",
    ("src/probos/federation/transport.py", "FederationTransport", "_deserialize"):
        "7b5024d9d18ea5d90c6eb2ba04e62619c486edafe60b025bfeafea3075aa34f2",
    ("src/probos/federation/transport.py", "FederationTransport", "send_to_peer"):
        "95f05ada8a2e84aa11648a8fae9a10f86b7b10d8383bb88170aa9783e51c3ad9",
    ("src/probos/federation/mock_transport.py", "MockFederationTransport", "send_to_peer"):
        "39a597a65eb1948bec8d323549f6dee70e37e2d66d880620a1e6d9c28bc33b8b",
    ("src/probos/federation/mock_transport.py", "MockFederationTransport", "deliver_response"):
        "a6bc723bb6466adf51f92af12e34f7221bfaac3713258aa5a60ae03aabddda0e",
}


def _method_ast_hash(path: Path, class_name: str, method_name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    return hashlib.sha256(
                        ast.dump(child, include_attributes=False).encode("utf-8")
                    ).hexdigest()
    raise AssertionError(f"missing {class_name}.{method_name}")


def test_all_five_bridge_and_eight_transport_executable_ast_hashes_are_frozen() -> None:
    root = Path(__file__).resolve().parents[1]
    for (relative, class_name, method_name), expected in _FROZEN_METHOD_HASHES.items():
        assert _method_ast_hash(root / relative, class_name, method_name) == expected


@pytest.mark.asyncio
async def test_direct_empty_registry_rejects_outbound_before_transport() -> None:
    bridge, transport, _ = _make_bridge(relay_topics=())

    assert await bridge.relay_one_way("node-b", _TOPIC, _valid_payload()) is False

    assert transport.sent == []
    assert bridge._relay_rate == {}


@pytest.mark.asyncio
async def test_real_fleet_composition_with_explicit_empty_registry_is_inert() -> None:
    shared_bus = MockNATSBus()
    await shared_bus.start()
    result = None
    try:
        result = await _organize_node(
            node_id="node-a",
            peer_ids=["node-b"],
            nats_bus=shared_bus,
            relay_topics=(),
        )
        bridge = result.federation_bridge
        assert bridge is not None
        assert dict(bridge._relay_topics) == {}
        assert await bridge.relay_one_way(
            "node-b", _TOPIC, _valid_payload()
        ) is False
        await bridge.handle_inbound(
            _relay_message(source_node="node-b", target_node_id="node-a")
        )
        assert bridge._relay_rate == {}
        assert [
            item for item in shared_bus.published if item[1].get("type") == "relay_one_way"
        ] == []
    finally:
        await _stop_organized(result)
        await shared_bus.stop()


def test_relay_public_signatures_contract_and_registry_shape_are_exact() -> None:
    assert str(inspect.signature(FederationBridge.relay_one_way)) == (
        "(self, target_node_id: 'str', topic: 'str', "
        "payload: 'dict[str, Any]') -> 'bool'"
    )
    assert str(inspect.signature(FederationRelayTopic)) == (
        "(name: 'str', validate_payload: 'RelayPayloadValidator', "
        "sink: 'RelaySink') -> None"
    )
    bridge, _, _ = _make_bridge()
    assert isinstance(bridge._relay_topics, MappingProxyType)
    assert tuple(bridge._relay_topics) == (_TOPIC,)


def test_finalizer_returns_only_json_loaded_detached_relay_payload() -> None:
    source = _wire_payload({"nested": {"items": [1, 2, 3]}})
    finalized = finalize_relay_wire_payload(
        source_node="node-a",
        message_id="fixed-message-id",
        relay_payload=source,
        timestamp=0.0,
    )
    assert finalized == source
    assert finalized is not source
    assert finalized["payload"] is not source["payload"]
    source["payload"]["nested"]["items"].append(4)
    assert finalized["payload"] == {"nested": {"items": [1, 2, 3]}}


def test_exact_relay_payload_extractor_does_not_traverse_nested_content() -> None:
    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic
    payload = _wire_payload(cyclic)
    extracted = extract_relay_wire_payload(payload)
    assert extracted is payload

    for invalid in (
        {key: value for key, value in payload.items() if key != "hop_count"},
        {**payload, "extra": True},
        {7: 1, **payload},
    ):
        assert extract_relay_wire_payload(invalid) is None


def test_source_guards_forbid_dispatch_learning_queue_task_and_allow_all_shapes() -> None:
    relay_source = inspect.getsource(relay_module)
    handler_source = textwrap.dedent(
        inspect.getsource(FederationBridge._handle_relay_one_way)
    )
    outbound_source = textwrap.dedent(inspect.getsource(FederationBridge.relay_one_way))
    forbidden_relay_module = (
        "IntentMessage",
        "IntentBus",
        "EventType",
        "_emit_event",
        "send_to_all_peers",
        "record_outcome",
        "hebbian",
        "create_task",
        "Queue(",
        "probos.runtime",
    )
    for token in forbidden_relay_module:
        assert token not in relay_source
    assert "not cryptographic source authentication" in relay_source
    forbidden_handler = (
        "send_to_peer(",
        "send_to_all_peers(",
        ".broadcast(",
        ".send(",
        "_emit_event(",
        "handle_inbound(",
        "record_outcome(",
        "create_task(",
        "Queue(",
        "intent_response",
    )
    for token in forbidden_handler:
        assert token not in handler_source
    assert "request_peer(" not in outbound_source
    assert "receive_with_timeout(" not in outbound_source
    assert "lambda _: True" not in relay_source
    assert "lambda _: True" not in inspect.getsource(_strict_test_payload_validator)

    bridge, _, _ = _make_bridge()
    relay_state_names = {
        name for name in vars(bridge) if name.startswith("_relay_")
    }
    assert relay_state_names == {
        "_relay_topics",
        "_relay_admission_open",
        "_relay_rate",
    }


def test_federation_relay_contract_has_no_unrelated_worktree_diff() -> None:
    """Guard AD-1123-owned relay files, not future shared mesh maintenance.

    The list below is the relay surface this AD owns. It previously also named
    ``src/probos/types.py``, ``src/probos/events.py`` and
    ``src/probos/startup/fleet_organization.py`` -- shared mesh modules, which
    the docstring above explicitly disclaims. Since the guard reads the
    *worktree* diff, naming them made any uncommitted edit to a core type fail
    the gate on an unrelated build: AD-1203 hit exactly that adding a field to
    ``IntentResult``. Narrowed to the files the guard says it protects.
    """
    root = Path(__file__).resolve().parents[1]
    forbidden = (
        "src/probos/federation/bridge.py",
        "src/probos/federation/relay.py",
        "src/probos/federation/nats_transport.py",
        "src/probos/federation/transport.py",
        "src/probos/federation/mock_transport.py",
    )
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    changed = set(result.stdout.splitlines())
    assert changed.isdisjoint(forbidden)


def test_constants_pin_all_protocol_bounds() -> None:
    assert MAX_RELAY_DEPTH == 8
    assert MAX_RELAY_NODES == 512
    assert MAX_RELAY_STRING_CHARS == 4_096
    assert MAX_RELAY_STRING_UTF8_BYTES == 32_768
    assert MAX_RELAY_ENVELOPE_BYTES == 32_768
    assert MAX_RELAY_TOPICS == 16
    assert RELAY_RATE_LIMIT_PER_SECOND == 64


# ---------------------------------------------------------------------------
# AD-1123 blocked-review corrections C1-C3
# ---------------------------------------------------------------------------


class _RelayNodeIdSubclass(str):
    touched = 0

    def __eq__(self, _other: object) -> bool:
        type(self).touched += 1
        raise AssertionError("relay node string override invoked")

    def encode(self, *_args: Any, **_kwargs: Any) -> bytes:
        type(self).touched += 1
        raise AssertionError("relay node string override invoked")

    __hash__ = str.__hash__


class _HostileRelayPeerList(list[Any]):
    touched = 0

    def __iter__(self):
        type(self).touched += 1
        raise AssertionError("configured peers inspected before local admission")


_UNSAFE_RELAY_NODE_IDS = (
    pytest.param("", id="empty"),
    pytest.param("bad.node", id="dot"),
    pytest.param("bad node", id="space"),
    pytest.param("x" * 129, id="oversized"),
    pytest.param(_RelayNodeIdSubclass("safe-node"), id="string-subclass"),
)


@pytest.mark.parametrize("value", _UNSAFE_RELAY_NODE_IDS)
def test_safe_relay_node_id_predicate_rejects_malformed_and_subclass_values(
    value: Any,
) -> None:
    _RelayNodeIdSubclass.touched = 0
    assert relay_module.is_safe_relay_node_id(value) is False
    assert _RelayNodeIdSubclass.touched == 0


def test_safe_relay_node_id_predicate_accepts_exact_128_character_value() -> None:
    assert relay_module.is_safe_relay_node_id("n" * 128) is True


@pytest.mark.parametrize("field", ["source", "target"])
@pytest.mark.parametrize("value", _UNSAFE_RELAY_NODE_IDS)
def test_finalizer_rejects_unsafe_relay_source_and_target_before_payload_detach(
    field: str,
    value: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detach_calls = 0
    _RelayNodeIdSubclass.touched = 0

    def _unexpected_detach(_value: Any) -> dict[str, Any]:
        nonlocal detach_calls
        detach_calls += 1
        raise AssertionError("payload detachment ran before relay node admission")

    monkeypatch.setattr(relay_module, "detach_relay_payload", _unexpected_detach)
    source_node: Any = value if field == "source" else "node-a"
    target_node_id: Any = value if field == "target" else "node-b"

    finalized = finalize_relay_wire_payload(
        source_node=source_node,
        message_id="fixed-message-id",
        relay_payload={
            "relay_version": 1,
            "target_node_id": target_node_id,
            "topic": _TOPIC,
            "payload": _valid_payload(),
            "hop_count": 0,
        },
        timestamp=0.0,
    )

    assert finalized is None
    assert detach_calls == 0
    assert _RelayNodeIdSubclass.touched == 0


def test_finalizer_accepts_exact_128_character_source_and_target() -> None:
    source_node = "s" * 128
    target_node_id = "t" * 128

    finalized = finalize_relay_wire_payload(
        source_node=source_node,
        message_id="fixed-message-id",
        relay_payload={
            "relay_version": 1,
            "target_node_id": target_node_id,
            "topic": _TOPIC,
            "payload": _valid_payload(),
            "hop_count": 0,
        },
        timestamp=0.0,
    )

    assert finalized is not None
    assert finalized["target_node_id"] == target_node_id


@pytest.mark.asyncio
@pytest.mark.parametrize("local_source", _UNSAFE_RELAY_NODE_IDS)
async def test_outbound_unsafe_local_source_rejects_before_peer_topic_finalizer_validator_or_send(
    local_source: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NoPeerLookupTransport(_CaptureTransport):
        @property
        def connected_peers(self) -> list[str]:
            raise AssertionError("connected peers inspected for unsafe local source")

    validator_calls = 0
    finalizer_calls = 0

    def _validator(_payload: dict[str, Any]) -> bool:
        nonlocal validator_calls
        validator_calls += 1
        return True

    def _unexpected_finalizer(**_kwargs: Any) -> dict[str, Any] | None:
        nonlocal finalizer_calls
        finalizer_calls += 1
        raise AssertionError("finalizer ran for unsafe local source")

    monkeypatch.setattr(
        bridge_module,
        "finalize_relay_wire_payload",
        _unexpected_finalizer,
    )
    _RelayNodeIdSubclass.touched = 0
    _HostileRelayPeerList.touched = 0
    transport = _NoPeerLookupTransport(connected_peers=["node-b"])
    bridge, _, _ = _make_bridge(
        node_id=local_source,
        peer_ids=["node-b"],
        transport=transport,
        relay_topics=(_topic(validator=_validator),),
    )
    bridge._config.peers = _HostileRelayPeerList(bridge._config.peers)

    accepted = await bridge.relay_one_way(
        "node-b",
        _TOPIC,
        _valid_payload(),
    )

    assert accepted is False
    assert finalizer_calls == 0
    assert validator_calls == 0
    assert transport.sent == []
    assert _HostileRelayPeerList.touched == 0
    assert _RelayNodeIdSubclass.touched == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("target_node_id", _UNSAFE_RELAY_NODE_IDS)
async def test_outbound_unsafe_target_rejects_before_peer_topic_finalizer_validator_or_send(
    target_node_id: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NoPeerLookupTransport(_CaptureTransport):
        @property
        def connected_peers(self) -> list[str]:
            raise AssertionError("connected peers inspected for unsafe target")

    validator_calls = 0
    finalizer_calls = 0

    def _validator(_payload: dict[str, Any]) -> bool:
        nonlocal validator_calls
        validator_calls += 1
        return True

    def _unexpected_finalizer(**_kwargs: Any) -> dict[str, Any] | None:
        nonlocal finalizer_calls
        finalizer_calls += 1
        raise AssertionError("finalizer ran for unsafe target")

    monkeypatch.setattr(
        bridge_module,
        "finalize_relay_wire_payload",
        _unexpected_finalizer,
    )
    _RelayNodeIdSubclass.touched = 0
    _HostileRelayPeerList.touched = 0
    transport = _NoPeerLookupTransport(connected_peers=["node-b"])
    bridge, _, _ = _make_bridge(
        transport=transport,
        relay_topics=(_topic(validator=_validator),),
    )
    bridge._config.peers = _HostileRelayPeerList(bridge._config.peers)

    accepted = await bridge.relay_one_way(
        target_node_id,
        _TOPIC,
        _valid_payload(),
    )

    assert accepted is False
    assert finalizer_calls == 0
    assert validator_calls == 0
    assert transport.sent == []
    assert _HostileRelayPeerList.touched == 0
    assert _RelayNodeIdSubclass.touched == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("local_target", _UNSAFE_RELAY_NODE_IDS)
async def test_inbound_unsafe_local_target_rejects_before_source_payload_clock_rate_validator_or_sink(
    local_target: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator_calls = 0
    sink_calls = 0
    finalizer_calls = 0

    def _validator(_payload: dict[str, Any]) -> bool:
        nonlocal validator_calls
        validator_calls += 1
        return True

    async def _sink(_source: str, _payload: dict[str, Any]) -> None:
        nonlocal sink_calls
        sink_calls += 1

    def _unexpected_finalizer(**_kwargs: Any) -> dict[str, Any] | None:
        nonlocal finalizer_calls
        finalizer_calls += 1
        raise AssertionError("finalizer ran for unsafe local target")

    def _unexpected_clock() -> float:
        raise AssertionError("clock read for unsafe local target")

    monkeypatch.setattr(
        bridge_module,
        "finalize_relay_wire_payload",
        _unexpected_finalizer,
    )
    monkeypatch.setattr(
        bridge_module,
        "time",
        SimpleNamespace(monotonic=_unexpected_clock),
    )
    _RelayNodeIdSubclass.touched = 0
    _HostileRelayPeerList.touched = 0
    bridge, transport, _ = _make_bridge(
        node_id=local_target,
        peer_ids=["node-a"],
        relay_topics=(_topic(_sink, validator=_validator),),
    )
    bridge._config.peers = _HostileRelayPeerList(bridge._config.peers)

    await bridge.handle_inbound(
        _relay_message(target_node_id=local_target)
    )

    assert finalizer_calls == 0
    assert validator_calls == 0
    assert sink_calls == 0
    assert bridge._relay_rate == {}
    assert transport.sent == []
    assert _HostileRelayPeerList.touched == 0
    assert _RelayNodeIdSubclass.touched == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("source_node", _UNSAFE_RELAY_NODE_IDS)
async def test_inbound_unsafe_source_rejects_before_config_payload_clock_rate_validator_or_sink(
    source_node: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator_calls = 0
    sink_calls = 0
    finalizer_calls = 0

    def _validator(_payload: dict[str, Any]) -> bool:
        nonlocal validator_calls
        validator_calls += 1
        return True

    async def _sink(_source: str, _payload: dict[str, Any]) -> None:
        nonlocal sink_calls
        sink_calls += 1

    def _unexpected_finalizer(**_kwargs: Any) -> dict[str, Any] | None:
        nonlocal finalizer_calls
        finalizer_calls += 1
        raise AssertionError("finalizer ran for unsafe source")

    def _unexpected_extractor(_payload: Any) -> dict[str, Any] | None:
        raise AssertionError("payload inspected for unsafe source")

    def _unexpected_clock() -> float:
        raise AssertionError("clock read for unsafe source")

    monkeypatch.setattr(
        bridge_module,
        "finalize_relay_wire_payload",
        _unexpected_finalizer,
    )
    monkeypatch.setattr(
        bridge_module,
        "extract_relay_wire_payload",
        _unexpected_extractor,
    )
    monkeypatch.setattr(
        bridge_module,
        "time",
        SimpleNamespace(monotonic=_unexpected_clock),
    )
    _RelayNodeIdSubclass.touched = 0
    _HostileRelayPeerList.touched = 0
    bridge, transport, _ = _make_bridge(
        node_id="node-b",
        peer_ids=["node-a"],
        relay_topics=(_topic(_sink, validator=_validator),),
    )
    bridge._config.peers = _HostileRelayPeerList(bridge._config.peers)

    await bridge.handle_inbound(
        _relay_message(source_node=source_node)
    )

    assert finalizer_calls == 0
    assert validator_calls == 0
    assert sink_calls == 0
    assert bridge._relay_rate == {}
    assert transport.sent == []
    assert _HostileRelayPeerList.touched == 0
    assert _RelayNodeIdSubclass.touched == 0


@pytest.mark.asyncio
async def test_exact_128_character_source_and_target_succeed_through_bridge_round_trip() -> None:
    source_node = "s" * 128
    target_node_id = "t" * 128
    received: list[tuple[str, dict[str, Any]]] = []

    async def _sink(source: str, payload: dict[str, Any]) -> None:
        received.append((source, payload))

    bus = MockTransportBus()
    origin_transport = MockFederationTransport(source_node, bus)
    receiver_transport = MockFederationTransport(target_node_id, bus)
    origin, _, _ = _make_bridge(
        node_id=source_node,
        peer_ids=[target_node_id],
        transport=origin_transport,
    )
    receiver, _, _ = _make_bridge(
        node_id=target_node_id,
        peer_ids=[source_node],
        transport=receiver_transport,
        relay_topics=(_topic(_sink),),
    )
    await origin.start()
    await receiver.start()
    try:
        accepted = await origin.relay_one_way(
            target_node_id,
            _TOPIC,
            _valid_payload(),
        )
    finally:
        await receiver.stop()
        await origin.stop()

    assert accepted is True
    assert received == [(source_node, _valid_payload())]


@pytest.mark.parametrize(
    "inspection_boundary",
    ["callable", "iscoroutinefunction", "signature"],
)
@pytest.mark.parametrize("callable_role", ["validator", "sink"])
def test_topic_registry_normalizes_every_ordinary_inspection_failure_to_exact_value_error(
    inspection_boundary: str,
    callable_role: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = _strict_test_payload_validator
    sink = _noop_sink
    target = validator if callable_role == "validator" else sink

    if inspection_boundary == "callable":
        original = callable

        def _raise_ordinary(value: Any) -> bool:
            if value is target:
                raise RuntimeError("HOSTILE_PRIVATE_METADATA")
            return original(value)

        monkeypatch.setattr(
            relay_module,
            "callable",
            _raise_ordinary,
            raising=False,
        )
    elif inspection_boundary == "iscoroutinefunction":
        original = inspect.iscoroutinefunction

        def _raise_ordinary(value: Any) -> bool:
            if value is target:
                raise RuntimeError("HOSTILE_PRIVATE_METADATA")
            return original(value)

        monkeypatch.setattr(
            relay_module.inspect,
            "iscoroutinefunction",
            _raise_ordinary,
        )
    else:
        original = inspect.signature

        def _raise_ordinary(value: Any) -> inspect.Signature:
            if value is target:
                raise RuntimeError("HOSTILE_PRIVATE_METADATA")
            return original(value)

        monkeypatch.setattr(relay_module.inspect, "signature", _raise_ordinary)

    with pytest.raises(ValueError) as raised:
        build_relay_topic_registry((
            FederationRelayTopic(_TOPIC, validator, sink),
        ))

    assert type(raised.value) is ValueError
    assert raised.value.args == ("relay_topics_invalid",)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


class _HostileCallableSignature:
    def __call__(self, _payload: dict[str, Any]) -> bool:
        return True

    @property
    def __signature__(self) -> inspect.Signature:
        raise RuntimeError("HOSTILE_REAL_SIGNATURE_METADATA")


def test_topic_registry_normalizes_real_hostile_callable_metadata_without_invocation() -> None:
    validator = _HostileCallableSignature()

    with pytest.raises(ValueError) as raised:
        build_relay_topic_registry((
            FederationRelayTopic(_TOPIC, validator, _noop_sink),
        ))

    assert type(raised.value) is ValueError
    assert raised.value.args == ("relay_topics_invalid",)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


class _RegistryInspectionBaseException(BaseException):
    pass


@pytest.mark.parametrize(
    "inspection_boundary",
    ["callable", "iscoroutinefunction", "signature"],
)
@pytest.mark.parametrize("callable_role", ["validator", "sink"])
def test_topic_registry_propagates_base_exception_identity_at_each_inspection_boundary(
    inspection_boundary: str,
    callable_role: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = _RegistryInspectionBaseException(inspection_boundary)
    validator = _strict_test_payload_validator
    sink = _noop_sink
    target = validator if callable_role == "validator" else sink

    if inspection_boundary == "callable":
        original = callable

        def _raise_base(value: Any) -> bool:
            if value is target:
                raise sentinel
            return original(value)

        monkeypatch.setattr(
            relay_module,
            "callable",
            _raise_base,
            raising=False,
        )
    elif inspection_boundary == "iscoroutinefunction":
        original = inspect.iscoroutinefunction

        def _raise_base(value: Any) -> bool:
            if value is target:
                raise sentinel
            return original(value)

        monkeypatch.setattr(
            relay_module.inspect,
            "iscoroutinefunction",
            _raise_base,
        )
    else:
        original = inspect.signature

        def _raise_base(value: Any) -> inspect.Signature:
            if value is target:
                raise sentinel
            return original(value)

        monkeypatch.setattr(relay_module.inspect, "signature", _raise_base)

    with pytest.raises(_RegistryInspectionBaseException) as raised:
        build_relay_topic_registry((
            FederationRelayTopic(_TOPIC, validator, sink),
        ))

    assert raised.value is sentinel


def test_topic_registry_accepts_partial_with_exact_effective_validator_and_sink_signatures() -> None:
    def _validator_with_policy(
        _policy: str,
        payload: dict[str, Any],
    ) -> bool:
        return _strict_test_payload_validator(payload)

    async def _sink_with_policy(
        _policy: str,
        _source: str,
        _payload: dict[str, Any],
    ) -> None:
        return None

    contract = FederationRelayTopic(
        _TOPIC,
        functools.partial(_validator_with_policy, "strict"),
        functools.partial(_sink_with_policy, "strict"),
    )

    registry = build_relay_topic_registry((contract,))

    assert registry[_TOPIC] is contract


@pytest.mark.parametrize("partial_kind", ["validator", "sink"])
def test_topic_registry_rejects_partial_with_bound_away_or_extra_effective_argument(
    partial_kind: str,
) -> None:
    def _validator(
        _policy: str,
        _payload: dict[str, Any],
    ) -> bool:
        return True

    async def _sink(
        _policy: str,
        _source: str,
        _payload: dict[str, Any],
    ) -> None:
        return None

    if partial_kind == "validator":
        contracts = (
            FederationRelayTopic(
                _TOPIC,
                functools.partial(_validator, "strict", _valid_payload()),
                _noop_sink,
            ),
            FederationRelayTopic(
                _TOPIC,
                functools.partial(_validator),
                _noop_sink,
            ),
        )
    else:
        contracts = (
            FederationRelayTopic(
                _TOPIC,
                _strict_test_payload_validator,
                functools.partial(_sink, "strict", "node-a"),
            ),
            FederationRelayTopic(
                _TOPIC,
                _strict_test_payload_validator,
                functools.partial(_sink),
            ),
        )

    for contract in contracts:
        with pytest.raises(ValueError, match="^relay_topics_invalid$"):
            build_relay_topic_registry((contract,))


class _SyncValidatorCallable:
    def __call__(self, payload: dict[str, Any]) -> bool:
        return _strict_test_payload_validator(payload)


class _AsyncSinkCallable:
    async def __call__(
        self,
        _source: str,
        _payload: dict[str, Any],
    ) -> None:
        return None


def test_topic_registry_accepts_sync_callable_object_as_validator() -> None:
    validator = _SyncValidatorCallable()
    contract = FederationRelayTopic(_TOPIC, validator, _noop_sink)

    registry = build_relay_topic_registry((contract,))

    assert registry[_TOPIC].validate_payload is validator


def test_topic_registry_rejects_async_callable_object_as_sink_without_invoking_it() -> None:
    sink = _AsyncSinkCallable()
    contract = FederationRelayTopic(
        _TOPIC,
        _strict_test_payload_validator,
        sink,
    )

    with pytest.raises(ValueError, match="^relay_topics_invalid$"):
        build_relay_topic_registry((contract,))


def test_topic_registry_accepts_true_async_decorated_wrapper_and_rejects_sync_coroutine_wrapper() -> None:
    async def _wrapped_sink(
        _source: str,
        _payload: dict[str, Any],
    ) -> None:
        return None

    @functools.wraps(_wrapped_sink)
    async def _async_wrapper(
        source: str,
        payload: dict[str, Any],
    ) -> None:
        await _wrapped_sink(source, payload)

    @functools.wraps(_wrapped_sink)
    def _sync_wrapper(
        source: str,
        payload: dict[str, Any],
    ) -> Awaitable[None]:
        return _wrapped_sink(source, payload)

    accepted = FederationRelayTopic(
        _TOPIC,
        _strict_test_payload_validator,
        _async_wrapper,
    )
    rejected = FederationRelayTopic(
        _TOPIC,
        _strict_test_payload_validator,
        _sync_wrapper,
    )

    assert build_relay_topic_registry((accepted,))[_TOPIC] is accepted
    with pytest.raises(ValueError, match="^relay_topics_invalid$"):
        build_relay_topic_registry((rejected,))


@pytest.mark.asyncio
async def test_failed_bridge_start_is_relay_closed_empty_taskless_and_restartable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailOnceInboundAssignmentTransport(_CaptureTransport):
        def __init__(self) -> None:
            self.fail_inbound_assignment = False
            self.inbound_assignments = 0
            super().__init__(connected_peers=["node-b"])
            self.fail_inbound_assignment = True

        def __setattr__(self, name: str, value: Any) -> None:
            if name == "_inbound_handler" and getattr(
                self,
                "fail_inbound_assignment",
                False,
            ):
                self.inbound_assignments += 1
                raise RuntimeError("inbound handler assignment failed")
            object.__setattr__(self, name, value)

    validator_calls = 0
    created_tasks: list[asyncio.Task[None]] = []
    real_create_task = asyncio.create_task

    def _record_create_task(
        coroutine: Any,
        *,
        name: str | None = None,
    ) -> asyncio.Task[None]:
        task = real_create_task(coroutine, name=name)
        created_tasks.append(task)
        return task

    def _validator(payload: dict[str, Any]) -> bool:
        nonlocal validator_calls
        validator_calls += 1
        return _strict_test_payload_validator(payload)

    transport = _FailOnceInboundAssignmentTransport()
    asyncio_probe = SimpleNamespace(
        CancelledError=asyncio.CancelledError,
        create_task=_record_create_task,
        current_task=asyncio.current_task,
        sleep=asyncio.sleep,
    )
    monkeypatch.setattr(bridge_module, "asyncio", asyncio_probe)
    bridge, _, _ = _make_bridge(
        transport=transport,
        relay_topics=(_topic(validator=_validator),),
    )
    bridge._relay_rate[("node-b", _TOPIC)] = deque([1.0])

    with pytest.raises(
        RuntimeError,
        match="^inbound handler assignment failed$",
    ):
        await bridge.start()

    assert bridge._relay_admission_open is False
    assert bridge._relay_rate == {}
    assert bridge._gossip_task is None
    assert created_tasks == []
    assert transport.inbound_assignments == 1
    assert await bridge.relay_one_way(
        "node-b",
        _TOPIC,
        _valid_payload(),
    ) is False
    assert validator_calls == 0
    assert transport.sent == []

    transport.fail_inbound_assignment = False
    await bridge.start()
    try:
        assert bridge._relay_admission_open is True
        assert bridge._gossip_task is not None
        assert not bridge._gossip_task.done()
        assert created_tasks == [bridge._gossip_task]
        assert await bridge.relay_one_way(
            "node-b",
            _TOPIC,
            _valid_payload(),
        ) is True
        assert validator_calls == 1
        assert len(transport.sent) == 1
    finally:
        await bridge.stop()

    assert bridge._relay_admission_open is False
    assert bridge._relay_rate == {}
    assert bridge._gossip_task is None
