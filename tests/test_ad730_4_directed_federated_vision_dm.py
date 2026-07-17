"""AD-730-4: directed federated vision DM protocol tests."""

from __future__ import annotations

import asyncio
import ast
import copy
import hashlib
import inspect
import json
import math
import subprocess
import textwrap
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

import httpx
import pytest
from fastapi import FastAPI

import probos.federation.bridge as bridge_module
import probos.federation.mock_transport as mock_transport_module
import probos.federation.nats_transport as nats_transport_module
import probos.federation.transport as federation_transport_module
from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import (
    A2APeerConfig,
    AttachmentsConfig,
    AuthConfig,
    FederationA2AConfig,
    FederationConfig,
    MedicalConfig,
    PeerConfig,
    ScalingConfig,
    SelfModConfig,
    SystemConfig,
    UtilityAgentsConfig,
)
from probos.federation.attachment_resolve import resolve_missing_attachments
from probos.federation.bridge import FederationBridge
from probos.federation.mock_transport import (
    MockFederationTransport,
    MockTransportBus,
)
from probos.federation.nats_transport import NATSFederationTransport
from probos.federation.router import FederationRouter
from probos.federation.transport import FederationTransport
from probos.mesh.intent import IntentBus
from probos.mesh.nats_bus import MockNATSBus
from probos.mesh.signal import SignalManager
from probos.routers import federation_attachments
from probos.startup.fleet_organization import organize_fleet
from probos.substrate.agent import BaseAgent
from probos.substrate.identity import generate_agent_id
from probos.substrate.pool_group import PoolGroupRegistry
from probos.types import (
    IntentDescriptor,
    FederationMessage,
    IntentMessage,
    IntentResult,
    NodeSelfModel,
)


_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
    b"\x00\x00IEND\xaeB`\x82"
)
_PNG_SHA = hashlib.sha256(_PNG_BYTES).hexdigest()
_TOKEN = "ad730-4-token"


class _IntSubclass(int):
    pass


class _CapturingRequestTransport:
    def __init__(
        self,
        *,
        connected_peers: list[str] | None = None,
        response_factory: Callable[
            [str, FederationMessage, int], FederationMessage | None
        ] | None = None,
    ) -> None:
        self._connected_peers = (
            ["node-b"] if connected_peers is None else connected_peers
        )
        self._response_factory = response_factory
        self.requests: list[tuple[str, FederationMessage, int]] = []
        self.sent: list[tuple[str, FederationMessage]] = []
        self._inbound_handler: Any = None

    @property
    def connected_peers(self) -> list[str]:
        return list(self._connected_peers)

    async def request_peer(
        self,
        peer_node_id: str,
        message: FederationMessage,
        timeout_ms: int,
    ) -> FederationMessage | None:
        self.requests.append((peer_node_id, message, timeout_ms))
        if self._response_factory is None:
            return None
        return self._response_factory(peer_node_id, message, timeout_ms)

    async def send_to_peer(
        self,
        peer_node_id: str,
        message: FederationMessage,
    ) -> None:
        self.sent.append((peer_node_id, message))

    async def receive_with_timeout(
        self,
        peer_node_id: str,
        timeout_ms: int,
    ) -> FederationMessage | None:
        return None


def _directed_response(
    request: FederationMessage,
    *,
    source_node: str = "node-b",
    results: list[dict[str, Any]] | None = None,
    delivery_mode: str = "targeted_dm",
) -> FederationMessage:
    if results is None:
        results = [{
            "intent_id": request.payload["id"],
            "agent_id": request.payload["target_agent_id"],
            "success": True,
            "result": {"ok": True},
            "error": None,
            "confidence": 0.8,
        }]
    return FederationMessage(
        type="intent_response",
        source_node=source_node,
        message_id=request.message_id,
        payload={"delivery_mode": delivery_mode, "results": results},
        timestamp=0.0,
    )


def _make_bridge(
    *,
    node_id: str = "node-a",
    peer_node_id: str = "node-b",
    transport: Any | None = None,
    intent_bus: IntentBus | None = None,
    resolver: Callable[[dict[str, Any], str], Awaitable[int]] | None = None,
    validate_fn: Callable[..., Awaitable[bool]] | None = None,
) -> tuple[FederationBridge, Any, IntentBus]:
    actual_transport = transport or _CapturingRequestTransport()
    actual_bus = intent_bus or IntentBus(SignalManager())
    bridge = FederationBridge(
        node_id=node_id,
        transport=actual_transport,
        router=FederationRouter(),
        intent_bus=actual_bus,
        config=FederationConfig(
            enabled=True,
            node_id=node_id,
            peers=[
                PeerConfig(
                    node_id=peer_node_id,
                    address="tcp://127.0.0.1:65530",
                )
            ],
            forward_timeout_ms=1,
            gossip_interval_seconds=100.0,
        ),
        self_model_fn=lambda: NodeSelfModel(node_id=node_id),
        validate_fn=validate_fn,
        attachment_resolver=resolver,
    )
    return bridge, actual_transport, actual_bus


def _text_intent(
    *,
    target_agent_id: str = "target_agent_001",
    ttl_seconds: Any = 60.0,
    params: Any = None,
    intent_name: str = "direct_message",
    intent_id: str = "directed_intent_001",
) -> IntentMessage:
    intent = IntentMessage(
        intent=intent_name,
        params={"text": "hello"} if params is None else {},
        id=intent_id,
        target_agent_id=target_agent_id,
    )
    intent.params = {"text": "hello"} if params is None else params
    intent.ttl_seconds = ttl_seconds
    return intent


def _directed_request(
    *,
    source_node: str = "node-a",
    target_node_id: str = "node-b",
    target_agent_id: str = "target_agent_001",
    intent_name: str = "direct_message",
    params: Any = None,
    intent_id: str = "directed_intent_001",
    ttl_seconds: Any = 60.0,
    timestamp: float = 1.0,
    delivery_mode: str = "targeted_dm",
    message_id: str = "federation_message_001",
) -> FederationMessage:
    return FederationMessage(
        type="intent_request",
        source_node=source_node,
        message_id=message_id,
        payload={
            "delivery_mode": delivery_mode,
            "target_node_id": target_node_id,
            "target_agent_id": target_agent_id,
            "intent": intent_name,
            "params": {"text": "hello"} if params is None else params,
            "id": intent_id,
            "ttl_seconds": ttl_seconds,
        },
        timestamp=timestamp,
    )


class _CountingResolver:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self.calls: list[tuple[dict[str, Any], str]] = []
        self.error = error

    async def __call__(
        self,
        params: dict[str, Any],
        source_node: str,
    ) -> int:
        self.calls.append((copy.deepcopy(params), source_node))
        if self.error is not None:
            raise self.error
        return 0


class _CountingBus(IntentBus):
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
    ) -> list[IntentResult]:
        self.broadcast_calls += 1
        return await super().broadcast(
            intent, timeout=timeout, federated=federated
        )

    async def send(self, intent: IntentMessage) -> IntentResult | None:
        self.send_calls += 1
        return await super().send(intent)


def _response_messages(transport: _CapturingRequestTransport) -> list[FederationMessage]:
    return [message for _peer, message in transport.sent]


def _fleet_config(
    *,
    node_id: str,
    peer_node_id: str,
    serve_remote_enabled: bool,
    a2a_peers: list[A2APeerConfig],
) -> SystemConfig:
    return SystemConfig(
        attachments=AttachmentsConfig(
            serve_remote_enabled=serve_remote_enabled,
            auto_resolve_remote_enabled=True,
        ),
        auth=AuthConfig(crew_scope_token=_TOKEN),
        federation=FederationConfig(
            enabled=True,
            node_id=node_id,
            peers=[
                PeerConfig(
                    node_id=peer_node_id,
                    address="tcp://127.0.0.1:65530",
                )
            ],
            forward_timeout_ms=1_000,
            gossip_interval_seconds=100.0,
            validate_remote_results=False,
            a2a=FederationA2AConfig(outbound_peers=a2a_peers),
        ),
        scaling=ScalingConfig(enabled=False),
        utility_agents=UtilityAgentsConfig(enabled=False),
        medical=MedicalConfig(enabled=False),
        self_mod=SelfModConfig(enabled=False),
    )


async def _organize_node(
    *,
    config: SystemConfig,
    intent_bus: IntentBus,
    attachment_resolver_fn: Callable[
        [dict[str, Any], str], Awaitable[int]
    ],
    nats_bus: MockNATSBus,
) -> Any:
    return await organize_fleet(
        config=config,
        pools={},
        pool_groups=PoolGroupRegistry(),
        escalation_manager=SimpleNamespace(),
        intent_bus=intent_bus,
        trust_network=SimpleNamespace(),
        llm_client=SimpleNamespace(),
        build_pool_intent_map_fn=lambda: {},
        find_consensus_pools_fn=lambda: set(),
        build_self_model_fn=lambda: NodeSelfModel(
            node_id=config.federation.node_id
        ),
        validate_remote_result_fn=None,
        attachment_resolver_fn=attachment_resolver_fn,
        nats_bus=nats_bus,
    )


async def _stop_node(result: Any) -> None:
    if result is None:
        return
    if result.federation_bridge is not None:
        await result.federation_bridge.stop()
    if result.federation_transport is not None:
        await result.federation_transport.stop()


class _RecordingDirectMessageAgent(BaseAgent):
    agent_type = "ad730_4_recording"
    intent_descriptors = [
        IntentDescriptor(name="direct_message", tier="domain")
    ]

    def __init__(
        self,
        *,
        agent_id: str,
        store: FilesystemAttachmentStore,
        expected_blob: bytes,
    ) -> None:
        super().__init__(
            pool="ad730_4_recording",
            agent_id=agent_id,
        )
        self._store = store
        self._expected_blob = expected_blob
        self.calls: list[IntentMessage] = []
        self.saw_prefetched_bytes: list[bool] = []

    async def perceive(self, intent: dict[str, Any]) -> Any:
        return intent

    async def decide(self, observation: Any) -> Any:
        return observation

    async def act(self, plan: Any) -> Any:
        return plan

    async def report(self, result: Any) -> dict[str, Any]:
        return {"result": result}

    async def handle_intent(
        self,
        intent: IntentMessage,
    ) -> IntentResult:
        self.calls.append(copy.deepcopy(intent))
        ref = intent.params["vision_messages"][0]["content"][0]["source"][
            "sha256"
        ]
        assert ref == _PNG_SHA
        present = await self._store.exists(ref)
        self.saw_prefetched_bytes.append(present)
        assert present
        assert await self._store.read(ref) == self._expected_blob
        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=True,
            result={"vision": "ready", "attachment_ref": ref},
            confidence=0.9,
        )


@pytest.mark.asyncio
async def test_directed_vision_dm_two_organized_bridges_prefetches_and_targets_only(
    tmp_path,
) -> None:
    origin_store = FilesystemAttachmentStore(tmp_path / "origin-attachments")
    receiver_store = FilesystemAttachmentStore(tmp_path / "receiver-attachments")
    await origin_store.write(_PNG_SHA, _PNG_BYTES, "image/png")

    origin_config = _fleet_config(
        node_id="node-a",
        peer_node_id="node-b",
        serve_remote_enabled=True,
        a2a_peers=[
            A2APeerConfig(
                node_id="node-b",
                peer_url="http://receiver.invalid",
                auth_token=_TOKEN,
            )
        ],
    )
    receiver_config = _fleet_config(
        node_id="node-b",
        peer_node_id="node-a",
        serve_remote_enabled=False,
        a2a_peers=[
            A2APeerConfig(
                node_id="node-a",
                peer_url="http://origin.test",
                auth_token=_TOKEN,
            )
        ],
    )
    origin_runtime = SimpleNamespace(
        config=origin_config,
        attachment_store=origin_store,
    )
    receiver_runtime = SimpleNamespace(
        config=receiver_config,
        attachment_store=receiver_store,
    )

    app = FastAPI()
    app.include_router(federation_attachments.router)
    app.state.runtime = origin_runtime
    fetches = {"count": 0}

    async def _count_fetch(_request: httpx.Request) -> None:
        fetches["count"] += 1

    target_id = generate_agent_id(
        "ad730_4_target", "ad730_4_recording", 0
    )
    decoy_id = generate_agent_id(
        "ad730_4_decoy", "ad730_4_recording", 0
    )
    target = _RecordingDirectMessageAgent(
        agent_id=target_id,
        store=receiver_store,
        expected_blob=_PNG_BYTES,
    )
    decoy = _RecordingDirectMessageAgent(
        agent_id=decoy_id,
        store=receiver_store,
        expected_blob=_PNG_BYTES,
    )

    shared_bus = MockNATSBus()
    await shared_bus.start()
    origin_bus = IntentBus(SignalManager())
    receiver_bus = IntentBus(SignalManager())
    receiver_bus.subscribe(
        target.id,
        target.handle_intent,
        intent_names=["direct_message"],
    )
    receiver_bus.subscribe(
        decoy.id,
        decoy.handle_intent,
        intent_names=["direct_message"],
    )

    origin_result = None
    receiver_result = None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://origin.test",
        event_hooks={"request": [_count_fetch]},
    ) as asgi_client:

        async def _origin_resolver(
            params: dict[str, Any], source_node: str
        ) -> int:
            return await resolve_missing_attachments(
                origin_runtime,
                params,
                source_node,
                http=asgi_client,
            )

        async def _receiver_resolver(
            params: dict[str, Any], source_node: str
        ) -> int:
            return await resolve_missing_attachments(
                receiver_runtime,
                params,
                source_node,
                http=asgi_client,
            )

        try:
            origin_result = await _organize_node(
                config=origin_config,
                intent_bus=origin_bus,
                attachment_resolver_fn=_origin_resolver,
                nats_bus=shared_bus,
            )
            receiver_result = await _organize_node(
                config=receiver_config,
                intent_bus=receiver_bus,
                attachment_resolver_fn=_receiver_resolver,
                nats_bus=shared_bus,
            )

            params = {
                "text": "Describe this image.",
                "vision_messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Describe this image.",
                            },
                            {
                                "type": "image",
                                "source": {
                                    "type": "attachment_ref",
                                    "sha256": _PNG_SHA,
                                    "media_type": "image/png",
                                },
                            },
                        ],
                    }
                ],
                "has_image_attachment": True,
                "nested_private": {"values": [1, {"two": 2}]},
            }
            original_graph = copy.deepcopy(params)
            intent = IntentMessage(
                intent="direct_message",
                params=params,
                id="ad730-4-headline-intent",
                target_agent_id=target.id,
                ttl_seconds=60.0,
            )

            result = await origin_result.federation_bridge.forward_direct_message(
                "node-b",
                intent,
            )

            assert result.success is True
            assert result.intent_id == intent.id
            assert result.agent_id == target.id
            assert target.saw_prefetched_bytes == [True]
            assert len(target.calls) == 1
            assert target.calls[0].target_agent_id == target.id
            assert target.calls[0].params["vision_messages"] == [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "attachment_ref",
                                "sha256": _PNG_SHA,
                                "media_type": "image/png",
                            },
                        }
                    ],
                }
            ]
            assert decoy.calls == []
            assert fetches["count"] == 1
            assert await receiver_store.read(_PNG_SHA) == _PNG_BYTES
            assert intent.params == original_graph
            assert params == original_graph
        finally:
            await _stop_node(receiver_result)
            await _stop_node(origin_result)
            await shared_bus.stop()


@pytest.mark.asyncio
async def test_directed_text_dm_targets_only_and_performs_zero_fetches() -> None:
    resolver = _CountingResolver()
    transport_bus = MockTransportBus()
    origin_transport = MockFederationTransport("node-a", transport_bus)
    receiver_transport = MockFederationTransport("node-b", transport_bus)
    origin_bus = _CountingBus()
    receiver_bus = _CountingBus()
    target_calls: list[IntentMessage] = []
    decoy_calls: list[IntentMessage] = []

    async def _target(intent: IntentMessage) -> IntentResult:
        target_calls.append(copy.deepcopy(intent))
        return IntentResult(
            intent_id=intent.id,
            agent_id="target_agent_001",
            success=True,
            result="text-ready",
        )

    async def _decoy(intent: IntentMessage) -> IntentResult:
        decoy_calls.append(intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="decoy_agent_001",
            success=True,
        )

    receiver_bus.subscribe("target_agent_001", _target, ["direct_message"])
    receiver_bus.subscribe("decoy_agent_001", _decoy, ["direct_message"])
    origin_bridge, _, _ = _make_bridge(
        transport=origin_transport,
        intent_bus=origin_bus,
    )
    receiver_bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=receiver_transport,
        intent_bus=receiver_bus,
        resolver=resolver,
    )
    await origin_bridge.start()
    await receiver_bridge.start()
    try:
        result = await origin_bridge.forward_direct_message(
            "node-b", _text_intent()
        )
    finally:
        await receiver_bridge.stop()
        await origin_bridge.stop()

    assert result.success is True
    assert result.result == "text-ready"
    assert len(target_calls) == 1
    assert target_calls[0].target_agent_id == "target_agent_001"
    assert decoy_calls == []
    assert resolver.calls == [(
        {
            "text": "hello",
            "from": "federation:node-a",
            "federation_source_node": "node-a",
            "federation_message_id": target_calls[0].params[
                "federation_message_id"
            ],
            "session": False,
            "session_history": [],
        },
        "node-a",
    )]
    assert receiver_bus.send_calls == 1
    assert receiver_bus.broadcast_calls == 0


@pytest.mark.asyncio
async def test_absent_target_returns_one_correlated_not_found_result_without_prefetch() -> None:
    resolver = _CountingResolver()
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
        resolver=resolver,
    )

    await bridge.handle_inbound(_directed_request())

    responses = _response_messages(transport)
    assert len(responses) == 1
    results = responses[0].payload["results"]
    assert results == [{
        "intent_id": "directed_intent_001",
        "agent_id": "target_agent_001",
        "success": False,
        "result": None,
        "error": "federation_target_not_found",
        "confidence": 0.0,
    }]
    assert resolver.calls == []
    assert bus.send_calls == 0
    assert bus.broadcast_calls == 0


@pytest.mark.asyncio
async def test_callsign_is_not_resolved_as_remote_agent_id() -> None:
    resolver = _CountingResolver()
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    real_calls: list[IntentMessage] = []

    async def _real(intent: IntentMessage) -> IntentResult:
        real_calls.append(intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="stable_agent_001",
            success=True,
        )

    bus.subscribe("stable_agent_001", _real, ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
        resolver=resolver,
    )

    await bridge.handle_inbound(
        _directed_request(target_agent_id="Ezri")
    )

    result = _response_messages(transport)[0].payload["results"][0]
    assert result["error"] == "federation_target_not_found"
    assert result["agent_id"] == "Ezri"
    assert real_calls == []
    assert resolver.calls == []
    assert bus.send_calls == 0
    assert bus.broadcast_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_agent_id",
    [
        pytest.param("", id="empty"),
        pytest.param("bad.agent", id="dot"),
        pytest.param("bad agent", id="space"),
        pytest.param("a" * 257, id="oversize"),
        pytest.param(7, id="non-string"),
    ],
)
async def test_malformed_target_agent_id_fails_before_network(
    invalid_agent_id: Any,
) -> None:
    bridge, transport, _ = _make_bridge()
    intent = _text_intent()
    intent.target_agent_id = invalid_agent_id

    result = await bridge.forward_direct_message("node-b", intent)

    assert result.error == "federation_target_agent_invalid"
    assert transport.requests == []


@pytest.mark.asyncio
async def test_unconfigured_target_node_fails_before_network() -> None:
    bridge, transport, _ = _make_bridge()

    result = await bridge.forward_direct_message(
        "node-c", _text_intent()
    )

    assert result.error == "federation_target_node_unavailable"
    assert transport.requests == []


@pytest.mark.asyncio
async def test_self_target_node_fails_before_network() -> None:
    bridge, transport, _ = _make_bridge()

    result = await bridge.forward_direct_message(
        "node-a", _text_intent()
    )

    assert result.error == "federation_target_node_invalid"
    assert transport.requests == []


@pytest.mark.asyncio
async def test_inbound_wrong_target_node_returns_mismatch_without_delivery_or_prefetch() -> None:
    resolver = _CountingResolver()
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    calls: list[IntentMessage] = []

    async def _target(intent: IntentMessage) -> IntentResult:
        calls.append(intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="target_agent_001",
            success=True,
        )

    bus.subscribe("target_agent_001", _target, ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
        resolver=resolver,
    )

    await bridge.handle_inbound(
        _directed_request(target_node_id="node-c")
    )

    result = _response_messages(transport)[0].payload["results"][0]
    assert result["error"] == "federation_target_node_mismatch"
    assert calls == []
    assert resolver.calls == []
    assert bus.send_calls == 0
    assert bus.broadcast_calls == 0


@pytest.mark.asyncio
async def test_inbound_unconfigured_spoofed_source_is_dropped_without_response() -> None:
    resolver = _CountingResolver()
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
        resolver=resolver,
    )

    await bridge.handle_inbound(
        _directed_request(source_node="node-c")
    )

    assert transport.sent == []
    assert resolver.calls == []
    assert bus.send_calls == 0
    assert bus.broadcast_calls == 0


@pytest.mark.asyncio
async def test_inbound_self_spoofed_source_is_dropped_without_response() -> None:
    resolver = _CountingResolver()
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
        resolver=resolver,
    )

    await bridge.handle_inbound(
        _directed_request(source_node="node-b")
    )

    assert transport.sent == []
    assert resolver.calls == []
    assert bus.send_calls == 0
    assert bus.broadcast_calls == 0


@pytest.mark.asyncio
async def test_non_direct_message_targeted_envelope_is_rejected_without_send() -> None:
    resolver = _CountingResolver()
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    bus.subscribe("target_agent_001", lambda intent: None, ["write_file"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
        resolver=resolver,
    )

    await bridge.handle_inbound(
        _directed_request(intent_name="write_file")
    )

    result = _response_messages(transport)[0].payload["results"][0]
    assert result["error"] == "federation_directed_intent_not_allowed"
    assert resolver.calls == []
    assert bus.send_calls == 0
    assert bus.broadcast_calls == 0


@pytest.mark.asyncio
async def test_malformed_directed_params_never_fall_back_to_broadcast() -> None:
    resolver = _CountingResolver()
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    bus.subscribe("target_agent_001", lambda intent: None, ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
        resolver=resolver,
    )

    await bridge.handle_inbound(_directed_request(params=[]))

    result = _response_messages(transport)[0].payload["results"][0]
    assert result["error"] == "federation_payload_invalid"
    assert resolver.calls == []
    assert bus.send_calls == 0
    assert bus.broadcast_calls == 0


_ORIGIN_INVALID_TTLS = [
    pytest.param(True, id="bool"),
    pytest.param("1", id="string"),
    pytest.param(_IntSubclass(1), id="numeric-subclass"),
    pytest.param(Decimal("1"), id="non-built-in-numeric"),
    pytest.param(0, id="zero"),
    pytest.param(-1, id="negative"),
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="positive-infinity"),
    pytest.param(float("-inf"), id="negative-infinity"),
    pytest.param(10**10000, id="oversized-int-overflow"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("ttl", _ORIGIN_INVALID_TTLS)
async def test_origin_rejects_nonfinite_or_nonpositive_ttl_before_network(
    ttl: Any,
) -> None:
    bridge, transport, _ = _make_bridge()

    result = await bridge.forward_direct_message(
        "node-b", _text_intent(ttl_seconds=ttl)
    )

    assert result.error == "federation_payload_invalid"
    assert transport.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ttl", "expected_wire", "expected_timeout_ms"),
    [
        pytest.param(120, 60.0, 60_000, id="origin-120-to-60"),
        pytest.param(0.00001, 0.00001, 1, id="tiny-positive-clamped-ms"),
    ],
)
async def test_origin_caps_ttl_at_sixty_for_wire_and_request_wait(
    ttl: float,
    expected_wire: float,
    expected_timeout_ms: int,
) -> None:
    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        return _directed_response(request)

    transport = _CapturingRequestTransport(response_factory=_respond)
    bridge, _, _ = _make_bridge(transport=transport)

    result = await bridge.forward_direct_message(
        "node-b", _text_intent(ttl_seconds=ttl)
    )

    assert result.success is True
    assert len(transport.requests) == 1
    _peer, request, timeout_ms = transport.requests[0]
    assert request.payload["ttl_seconds"] == expected_wire
    assert timeout_ms == expected_timeout_ms


_WIRE_INVALID_TTLS = [
    *_ORIGIN_INVALID_TTLS,
    pytest.param(60.0001, id="over-cap-60-point-0001"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("ttl", _WIRE_INVALID_TTLS)
async def test_receiver_rejects_nonfinite_nonpositive_or_over_cap_ttl_before_prefetch_or_send(
    ttl: Any,
) -> None:
    resolver = _CountingResolver()
    transport = _CapturingRequestTransport()
    bus = _CountingBus()

    async def _target(intent: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=intent.id,
            agent_id="target_agent_001",
            success=True,
        )

    bus.subscribe("target_agent_001", _target, ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
        resolver=resolver,
    )

    await bridge.handle_inbound(_directed_request(ttl_seconds=ttl))

    result = _response_messages(transport)[0].payload["results"][0]
    assert result["error"] == "federation_payload_invalid"
    assert resolver.calls == []
    assert bus.send_calls == 0
    assert bus.broadcast_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sender_timestamp",
    [
        pytest.param(0.0, id="zero-epoch"),
        pytest.param(10**30, id="unrelated-large-epoch"),
        pytest.param(-10**30, id="unrelated-negative-epoch"),
    ],
)
async def test_receiver_does_not_compare_sender_monotonic_timestamp_and_starts_local_intent_lifetime(
    sender_timestamp: float,
) -> None:
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    seen: list[IntentMessage] = []
    before = datetime.now(timezone.utc)

    async def _target(intent: IntentMessage) -> IntentResult:
        seen.append(intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="target_agent_001",
            success=True,
        )

    bus.subscribe("target_agent_001", _target, ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
    )

    await bridge.handle_inbound(
        _directed_request(timestamp=sender_timestamp)
    )
    after = datetime.now(timezone.utc)

    assert len(seen) == 1
    assert before <= seen[0].created_at <= after
    assert seen[0].ttl_seconds == 60.0
    assert _response_messages(transport)[0].payload["results"][0][
        "success"
    ] is True


@pytest.mark.asyncio
async def test_receiver_replaces_spoofed_authority_and_session_fields_with_server_owned_provenance() -> None:
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    seen: list[IntentMessage] = []

    async def _target(intent: IntentMessage) -> IntentResult:
        seen.append(copy.deepcopy(intent))
        return IntentResult(
            intent_id=intent.id,
            agent_id="target_agent_001",
            success=True,
        )

    bus.subscribe("target_agent_001", _target, ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
    )
    origin_capture = _CapturingRequestTransport()
    origin_bridge, _, _ = _make_bridge(transport=origin_capture)
    origin_intent = _text_intent(params={
        "text": "hello",
        "from": "captain",
        "federation_source_node": "spoofed",
        "federation_message_id": "spoofed",
        "session": True,
        "session_history": [{"secret": "history"}],
        "is_captain": True,
        "was_mentioned": True,
        "_qualification_test": {"admin": True},
    })
    await origin_bridge.forward_direct_message("node-b", origin_intent)
    request = origin_capture.requests[0][1]
    request.message_id = "federation_message_real"

    await bridge.handle_inbound(request)

    params = seen[0].params
    assert params == {
        "text": "hello",
        "from": "federation:node-a",
        "federation_source_node": "node-a",
        "federation_message_id": "federation_message_real",
        "session": False,
        "session_history": [],
    }
    assert params["from"] != "hxi_profile"
    assert seen[0].context == "federation:node-a"
    assert seen[0].urgency == 0.5


@pytest.mark.asyncio
async def test_directed_wire_drops_private_session_history_context_and_unknown_params() -> None:
    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        return _directed_response(request)

    transport = _CapturingRequestTransport(response_factory=_respond)
    bridge, _, _ = _make_bridge(transport=transport)
    params = {
        "text": "hello",
        "from": "hxi_profile",
        "to": "secret",
        "author_id": "captain",
        "is_captain": True,
        "was_mentioned": True,
        "_qualification_test": {"admin": True},
        "session": True,
        "session_history": [{"private": "turn"}],
        "captain_message": "raw private",
        "_visual_scene": "room",
        "_visual_novelty": 0.9,
        "_visual_summary": "summary",
        "project": {"secret": True},
        "recall": {"secret": True},
        "tool_state": {"secret": True},
        "unknown": {"secret": True},
    }

    result = await bridge.forward_direct_message(
        "node-b", _text_intent(params=params)
    )

    assert result.success is True
    wire = transport.requests[0][1].payload
    assert set(wire) == {
        "delivery_mode",
        "target_node_id",
        "target_agent_id",
        "intent",
        "params",
        "id",
        "ttl_seconds",
    }
    assert wire["params"] == {"text": "hello"}
    assert "context" not in wire
    assert "urgency" not in wire
    assert "thread_id" not in wire


@pytest.mark.asyncio
async def test_target_handler_exception_returns_delivery_failed_and_decoy_is_untouched() -> None:
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    decoy_calls: list[IntentMessage] = []

    async def _target(_intent: IntentMessage) -> IntentResult:
        raise RuntimeError("private target exception")

    async def _decoy(intent: IntentMessage) -> IntentResult:
        decoy_calls.append(intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="decoy_agent_001",
            success=True,
        )

    bus.subscribe("target_agent_001", _target, ["direct_message"])
    bus.subscribe("decoy_agent_001", _decoy, ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
    )

    await bridge.handle_inbound(_directed_request())

    result = _response_messages(transport)[0].payload["results"][0]
    assert result["error"] == "federation_target_delivery_failed"
    assert "private target exception" not in json.dumps(result)
    assert decoy_calls == []
    assert bus.send_calls == 1
    assert bus.broadcast_calls == 0


@pytest.mark.asyncio
async def test_target_handler_cancellation_propagates_without_response_or_fallback() -> None:
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    decoy_calls: list[IntentMessage] = []

    async def _target(_intent: IntentMessage) -> IntentResult:
        raise asyncio.CancelledError

    async def _decoy(intent: IntentMessage) -> IntentResult:
        decoy_calls.append(intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="decoy_agent_001",
            success=True,
        )

    bus.subscribe("target_agent_001", _target, ["direct_message"])
    bus.subscribe("decoy_agent_001", _decoy, ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
    )

    with pytest.raises(asyncio.CancelledError):
        await bridge.handle_inbound(_directed_request())

    assert transport.sent == []
    assert decoy_calls == []
    assert bus.send_calls == 1
    assert bus.broadcast_calls == 0


@pytest.mark.asyncio
async def test_resolver_exception_still_delivers_only_to_target() -> None:
    resolver = _CountingResolver(error=RuntimeError("resolver exploded"))
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    target_calls: list[IntentMessage] = []
    decoy_calls: list[IntentMessage] = []

    async def _target(intent: IntentMessage) -> IntentResult:
        target_calls.append(intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="target_agent_001",
            success=True,
        )

    async def _decoy(intent: IntentMessage) -> IntentResult:
        decoy_calls.append(intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="decoy_agent_001",
            success=True,
        )

    bus.subscribe("target_agent_001", _target, ["direct_message"])
    bus.subscribe("decoy_agent_001", _decoy, ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
        resolver=resolver,
    )

    await bridge.handle_inbound(_directed_request())

    assert len(resolver.calls) == 1
    assert len(target_calls) == 1
    assert decoy_calls == []
    assert _response_messages(transport)[0].payload["results"][0][
        "success"
    ] is True
    assert bus.send_calls == 1
    assert bus.broadcast_calls == 0


@pytest.mark.asyncio
async def test_resolver_cancellation_propagates_before_target_delivery() -> None:
    resolver = _CountingResolver(error=asyncio.CancelledError())
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    target_calls: list[IntentMessage] = []

    async def _target(intent: IntentMessage) -> IntentResult:
        target_calls.append(intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="target_agent_001",
            success=True,
        )

    bus.subscribe("target_agent_001", _target, ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
        resolver=resolver,
    )

    with pytest.raises(asyncio.CancelledError):
        await bridge.handle_inbound(_directed_request())

    assert len(resolver.calls) == 1
    assert target_calls == []
    assert transport.sent == []
    assert bus.send_calls == 0
    assert bus.broadcast_calls == 0


@pytest.mark.asyncio
async def test_response_intent_id_mismatch_is_rejected() -> None:
    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        response = _directed_response(request)
        response.payload["results"][0]["intent_id"] = "other_intent"
        return response

    bridge, _, _ = _make_bridge(
        transport=_CapturingRequestTransport(response_factory=_respond)
    )

    result = await bridge.forward_direct_message("node-b", _text_intent())

    assert result.error == "federation_result_correlation_mismatch"


@pytest.mark.asyncio
async def test_response_agent_id_mismatch_is_rejected() -> None:
    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        response = _directed_response(request)
        response.payload["results"][0]["agent_id"] = "other_agent"
        return response

    bridge, _, _ = _make_bridge(
        transport=_CapturingRequestTransport(response_factory=_respond)
    )

    result = await bridge.forward_direct_message("node-b", _text_intent())

    assert result.error == "federation_result_target_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "results",
    [
        pytest.param([], id="zero"),
        pytest.param(
            [
                {
                    "intent_id": "directed_intent_001",
                    "agent_id": "target_agent_001",
                    "success": True,
                },
                {
                    "intent_id": "directed_intent_001",
                    "agent_id": "target_agent_001",
                    "success": True,
                },
            ],
            id="multiple",
        ),
    ],
)
async def test_zero_or_multiple_results_are_protocol_invalid(
    results: list[dict[str, Any]],
) -> None:
    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        return _directed_response(request, results=results)

    bridge, _, _ = _make_bridge(
        transport=_CapturingRequestTransport(response_factory=_respond)
    )

    result = await bridge.forward_direct_message("node-b", _text_intent())

    assert result.error == "federation_response_invalid"


@pytest.mark.asyncio
async def test_existing_remote_result_validator_can_reject_directed_result() -> None:
    calls: list[IntentResult] = []

    async def _validate(result: IntentResult) -> bool:
        calls.append(result)
        return False

    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        return _directed_response(request)

    bridge, _, _ = _make_bridge(
        transport=_CapturingRequestTransport(response_factory=_respond),
        validate_fn=_validate,
    )

    result = await bridge.forward_direct_message("node-b", _text_intent())

    assert result.error == "federation_result_validation_failed"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_concurrent_same_peer_responses_correlate_by_message_id() -> None:
    bus = MockNATSBus()
    await bus.start()
    transport = NATSFederationTransport(
        node_id="node-a",
        nats_bus=bus,
        peer_node_ids=["node-b"],
    )
    release_first = asyncio.Event()
    requests: list[FederationMessage] = []

    async def _receiver(nats_message: Any) -> None:
        request = transport._deserialize(nats_message.data)
        requests.append(request)
        if request.message_id == "request-one":
            await release_first.wait()
        response = FederationMessage(
            type="intent_response",
            source_node="node-b",
            message_id=request.message_id,
            payload={"delivery_mode": "targeted_dm", "results": []},
        )
        await transport.deliver_response("node-b", response)

    await bus.subscribe_raw("federation.intent.node-b", _receiver)
    first = FederationMessage(
        type="intent_request",
        source_node="node-a",
        message_id="request-one",
        payload={"delivery_mode": "targeted_dm"},
    )
    second = FederationMessage(
        type="intent_request",
        source_node="node-a",
        message_id="request-two",
        payload={"delivery_mode": "targeted_dm"},
    )
    first_task = asyncio.create_task(
        transport.request_peer("node-b", first, 1_000)
    )
    await asyncio.sleep(0)
    second_task = asyncio.create_task(
        transport.request_peer("node-b", second, 1_000)
    )
    second_response = await second_task
    release_first.set()
    first_response = await first_task

    assert [request.message_id for request in requests] == [
        "request-one",
        "request-two",
    ]
    assert first_response is not None
    assert second_response is not None
    assert first_response.message_id == "request-one"
    assert second_response.message_id == "request-two"
    assert transport._pending_requests == {}
    await bus.stop()


@pytest.mark.asyncio
async def test_request_timeout_returns_correlated_peer_timeout() -> None:
    transport = _CapturingRequestTransport(response_factory=lambda *_args: None)
    bridge, _, _ = _make_bridge(transport=transport)

    result = await bridge.forward_direct_message(
        "node-b", _text_intent(ttl_seconds=0.00001)
    )

    assert result.error == "federation_peer_timeout"
    assert transport.requests[0][2] == 1


@pytest.mark.asyncio
async def test_request_cancellation_cleans_pending_future() -> None:
    transport = MockFederationTransport("node-a", MockTransportBus())
    message = FederationMessage(
        type="intent_request",
        source_node="node-a",
        message_id="cancel-request",
        payload={"delivery_mode": "targeted_dm"},
    )
    task = asyncio.create_task(
        transport.request_peer("missing-node", message, 60_000)
    )
    await asyncio.sleep(0)
    assert ("missing-node", "cancel-request") in transport._pending_requests

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert transport._pending_requests == {}


@pytest.mark.asyncio
async def test_stop_clears_pending_futures() -> None:
    transport = MockFederationTransport("node-a", MockTransportBus())
    message = FederationMessage(
        type="intent_request",
        source_node="node-a",
        message_id="stop-request",
        payload={"delivery_mode": "targeted_dm"},
    )
    task = asyncio.create_task(
        transport.request_peer("missing-node", message, 60_000)
    )
    await asyncio.sleep(0)
    pending = transport._pending_requests[("missing-node", "stop-request")]

    await transport.stop()

    assert pending.cancelled()
    assert transport._pending_requests == {}
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_late_directed_response_does_not_poison_legacy_queue() -> None:
    transport = MockFederationTransport("node-a", MockTransportBus())
    late = FederationMessage(
        type="intent_response",
        source_node="node-b",
        message_id="late-directed",
        payload={"delivery_mode": "targeted_dm", "results": []},
    )

    await transport.deliver_response("node-b", late)

    assert await transport.receive_with_timeout("node-b", 1) is None


@pytest.mark.asyncio
async def test_legacy_response_still_enters_and_is_read_from_legacy_queue() -> None:
    transport = MockFederationTransport("node-a", MockTransportBus())
    legacy = FederationMessage(
        type="intent_response",
        source_node="node-b",
        message_id="legacy-response",
        payload={"results": []},
    )

    await transport.deliver_response("node-b", legacy)

    received = await transport.receive_with_timeout("node-b", 10)
    assert received is legacy


def test_nats_and_zmq_directed_serializer_parity() -> None:
    message = _directed_request(
        params={
            "text": "hello",
            "attachment_ref": "a" * 64,
            "vision_messages": [{
                "role": "user",
                "content": [{
                    "type": "image",
                    "source": {
                        "type": "attachment_ref",
                        "sha256": "a" * 64,
                        "media_type": "image/png",
                    },
                }],
            }],
        }
    )
    nats = NATSFederationTransport(
        node_id="node-a", nats_bus=MockNATSBus(), peer_node_ids=[]
    )
    zmq = object.__new__(FederationTransport)

    nats_object = nats._serialize(message)
    zmq_object = json.loads(zmq._serialize(message).decode())

    assert nats_object == zmq_object
    assert nats._deserialize(nats_object) == zmq._deserialize(
        json.dumps(zmq_object).encode()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("params", "forbidden"),
    [
        pytest.param(
            {
                "text": "safe",
                "vision_messages": [{
                    "role": "user",
                    "content": [{
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": "A" * 1024,
                        },
                    }],
                }],
            },
            "base64",
            id="inline-base64",
        ),
        pytest.param(
            {
                "text": "safe",
                "vision_messages": [{
                    "role": "user",
                    "content": [{
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,AAAA"
                        },
                    }],
                }],
            },
            "data:image",
            id="data-url",
        ),
        pytest.param(
            {
                "text": "safe",
                "vision_messages": [{
                    "role": "user",
                    "content": [{
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": "https://images.invalid/private.png",
                        },
                    }],
                }],
            },
            "images.invalid",
            id="image-url",
        ),
        pytest.param(
            {"text": "safe", "unknown": b"raw-png"},
            "raw-png",
            id="python-bytes-unknown-key",
        ),
    ],
)
async def test_directed_wire_contains_only_sha_refs_and_no_inline_binary_forms(
    params: dict[str, Any],
    forbidden: str,
) -> None:
    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        return _directed_response(request)

    transport = _CapturingRequestTransport(response_factory=_respond)
    bridge, _, _ = _make_bridge(transport=transport)

    result = await bridge.forward_direct_message(
        "node-b", _text_intent(params=params)
    )

    assert result.success is True
    serialized = json.dumps(transport.requests[0][1].payload)
    assert forbidden not in serialized
    assert "Authorization" not in serialized
    assert _TOKEN not in serialized


@pytest.mark.asyncio
async def test_directed_request_and_response_are_deeply_detached_from_callers() -> None:
    captured_request: list[FederationMessage] = []
    remote_nested = {"remote": [{"value": 1}]}

    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        captured_request.append(request)
        return _directed_response(
            request,
            results=[{
                "intent_id": request.payload["id"],
                "agent_id": request.payload["target_agent_id"],
                "success": True,
                "result": remote_nested,
                "error": None,
                "confidence": 0.8,
            }],
        )

    params = {
        "text": "hello",
        "attachment_refs": ["a" * 64],
        "vision_messages": [{
            "role": "user",
            "content": [{
                "type": "image",
                "source": {
                    "type": "attachment_ref",
                    "sha256": "a" * 64,
                    "media_type": "image/png",
                },
            }],
        }],
    }
    transport = _CapturingRequestTransport(response_factory=_respond)
    bridge, _, _ = _make_bridge(transport=transport)

    result = await bridge.forward_direct_message(
        "node-b", _text_intent(params=params)
    )
    params["attachment_refs"].append("b" * 64)
    params["vision_messages"][0]["content"][0]["source"]["sha256"] = "c" * 64
    remote_nested["remote"][0]["value"] = 99

    wire_params = captured_request[0].payload["params"]
    assert wire_params["attachment_refs"] == ["a" * 64]
    assert wire_params["vision_messages"][0]["content"][0]["source"][
        "sha256"
    ] == "a" * 64
    assert result.result == {"remote": [{"value": 1}]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exit_kind",
    [
        pytest.param("success", id="success"),
        pytest.param("ordinary-error", id="ordinary-error"),
        pytest.param("cancellation", id="cancellation"),
    ],
)
async def test_original_nested_params_unchanged_on_success_error_and_cancellation(
    exit_kind: str,
) -> None:
    params = {
        "text": "hello",
        "private": {"nested": [1, {"two": 2}]},
        "attachment_refs": ["a" * 64],
        "vision_messages": [{
            "role": "user",
            "content": [{
                "type": "image",
                "source": {
                    "type": "attachment_ref",
                    "sha256": "a" * 64,
                    "media_type": "image/png",
                },
            }],
        }],
    }
    baseline = copy.deepcopy(params)

    if exit_kind == "success":
        def _respond(
            _peer: str, request: FederationMessage, _timeout: int
        ) -> FederationMessage:
            return _directed_response(request)

        transport: Any = _CapturingRequestTransport(
            response_factory=_respond
        )
    elif exit_kind == "ordinary-error":
        class _FailingTransport(_CapturingRequestTransport):
            async def request_peer(
                self,
                peer_node_id: str,
                message: FederationMessage,
                timeout_ms: int,
            ) -> FederationMessage | None:
                self.requests.append((peer_node_id, message, timeout_ms))
                raise RuntimeError("transport failed")

        transport = _FailingTransport()
    else:
        class _CancellingTransport(_CapturingRequestTransport):
            async def request_peer(
                self,
                peer_node_id: str,
                message: FederationMessage,
                timeout_ms: int,
            ) -> FederationMessage | None:
                self.requests.append((peer_node_id, message, timeout_ms))
                raise asyncio.CancelledError

        transport = _CancellingTransport()

    bridge, _, _ = _make_bridge(transport=transport)
    intent = _text_intent(params=params)
    if exit_kind == "cancellation":
        with pytest.raises(asyncio.CancelledError):
            await bridge.forward_direct_message("node-b", intent)
    else:
        await bridge.forward_direct_message("node-b", intent)

    assert params == baseline
    assert intent.params == baseline


@pytest.mark.asyncio
async def test_legacy_untargeted_federation_envelope_is_exact_and_has_no_directed_fields() -> None:
    class _LegacyCapture:
        def __init__(self) -> None:
            self.sent: list[FederationMessage] = []

        @property
        def connected_peers(self) -> list[str]:
            return ["node-b"]

        async def send_to_peer(
            self,
            peer_node_id: str,
            message: FederationMessage,
        ) -> None:
            self.sent.append(message)

        async def receive_with_timeout(
            self,
            peer_node_id: str,
            timeout_ms: int,
        ) -> FederationMessage | None:
            return None

    transport = _LegacyCapture()
    bridge, _, _ = _make_bridge(transport=transport)
    intent = IntentMessage(
        intent="direct_message",
        params={
            "text": "legacy",
            "nested": {"values": [1, 2]},
        },
        urgency=0.7,
        context="legacy-context",
        id="legacy_intent_001",
        ttl_seconds=12.5,
        target_agent_id="local_target_ignored_by_legacy",
    )

    await bridge.forward_intent(intent)

    assert len(transport.sent) == 1
    message = transport.sent[0]
    assert message.type == "intent_request"
    assert message.source_node == "node-a"
    assert message.payload == {
        "intent": "direct_message",
        "params": {
            "text": "legacy",
            "nested": {"values": [1, 2]},
        },
        "urgency": 0.7,
        "context": "legacy-context",
        "id": "legacy_intent_001",
        "ttl_seconds": 12.5,
    }
    assert "delivery_mode" not in message.payload
    assert "target_node_id" not in message.payload
    assert "target_agent_id" not in message.payload
    nats = NATSFederationTransport(
        node_id="node-a", nats_bus=MockNATSBus(), peer_node_ids=[]
    )
    zmq = object.__new__(FederationTransport)
    assert nats._serialize(message) == json.loads(
        zmq._serialize(message).decode()
    )


@pytest.mark.asyncio
async def test_legacy_untargeted_direct_message_still_broadcasts_to_all_matching_local_agents() -> None:
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    calls: list[str] = []

    def _handler(agent_id: str) -> Callable[[IntentMessage], Awaitable[IntentResult]]:
        async def _run(intent: IntentMessage) -> IntentResult:
            calls.append(agent_id)
            return IntentResult(
                intent_id=intent.id,
                agent_id=agent_id,
                success=True,
            )

        return _run

    bus.subscribe("agent-one", _handler("agent-one"), ["direct_message"])
    bus.subscribe("agent-two", _handler("agent-two"), ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
    )
    legacy = FederationMessage(
        type="intent_request",
        source_node="node-a",
        message_id="legacy_message_001",
        payload={
            "intent": "direct_message",
            "params": {"text": "legacy fanout"},
            "id": "legacy_intent_001",
            "ttl_seconds": 5.0,
        },
    )

    await bridge.handle_inbound(legacy)

    assert set(calls) == {"agent-one", "agent-two"}
    assert bus.broadcast_calls == 1
    assert bus.send_calls == 0
    response = _response_messages(transport)[0]
    assert "delivery_mode" not in response.payload
    assert {r["agent_id"] for r in response.payload["results"]} == {
        "agent-one",
        "agent-two",
    }


def test_intent_bus_has_subscriber_is_exact_and_index_independent() -> None:
    bus = IntentBus(SignalManager())

    async def _handler(_intent: IntentMessage) -> IntentResult | None:
        return None

    bus.subscribe("agent-exact", _handler, ["one.intent"])
    bus._intent_index["other.intent"] = {"ghost-agent"}

    assert bus.has_subscriber("agent-exact") is True
    assert bus.has_subscriber("ghost-agent") is False
    assert bus.has_subscriber("agent") is False
    assert bus.has_subscriber("") is False
    assert bus.has_subscriber("one.intent") is False


def test_new_public_signatures_are_exact_and_forward_direct_message_accepts_positional_call() -> None:
    assert str(inspect.signature(FederationBridge.forward_direct_message)) == (
        "(self, target_node_id: 'str', intent: 'IntentMessage') -> 'IntentResult'"
    )
    expected_request = (
        "(self, peer_node_id: 'str', message: 'FederationMessage', "
        "timeout_ms: 'int') -> 'FederationMessage | None'"
    )
    assert str(inspect.signature(NATSFederationTransport.request_peer)) == expected_request
    assert str(inspect.signature(FederationTransport.request_peer)) == expected_request
    assert str(inspect.signature(MockFederationTransport.request_peer)) == expected_request
    assert str(inspect.signature(IntentBus.has_subscriber)) == (
        "(self, agent_id: 'str') -> 'bool'"
    )
    signature = inspect.signature(FederationBridge.forward_direct_message)
    signature.bind(object(), "node-b", _text_intent())


@pytest.mark.asyncio
async def test_validator_cancellation_propagates_and_exception_preserves_log_and_pass() -> None:
    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        return _directed_response(request)

    async def _cancel(_result: IntentResult) -> bool:
        raise asyncio.CancelledError

    cancelling_bridge, _, _ = _make_bridge(
        transport=_CapturingRequestTransport(response_factory=_respond),
        validate_fn=_cancel,
    )
    with pytest.raises(asyncio.CancelledError):
        await cancelling_bridge.forward_direct_message(
            "node-b", _text_intent()
        )

    async def _raise(_result: IntentResult) -> bool:
        raise RuntimeError("validator failed")

    passing_bridge, _, _ = _make_bridge(
        transport=_CapturingRequestTransport(response_factory=_respond),
        validate_fn=_raise,
    )
    result = await passing_bridge.forward_direct_message(
        "node-b", _text_intent()
    )
    assert result.success is True


@pytest.mark.asyncio
async def test_nonserializable_target_result_returns_stable_error_without_body() -> None:
    transport = _CapturingRequestTransport()
    bus = _CountingBus()

    async def _target(intent: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=intent.id,
            agent_id="target_agent_001",
            success=True,
            result={"blob": b"never-on-wire"},
        )

    bus.subscribe("target_agent_001", _target, ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
    )

    await bridge.handle_inbound(_directed_request())

    response = _response_messages(transport)[0]
    result = response.payload["results"][0]
    assert result["error"] == "federation_result_not_serializable"
    assert result["result"] is None
    assert "never-on-wire" not in json.dumps(response.payload)


@pytest.mark.asyncio
async def test_receiver_preserves_outbound_transport_marker_without_reprocessing() -> None:
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    seen: list[IntentMessage] = []

    async def _target(intent: IntentMessage) -> IntentResult:
        seen.append(copy.deepcopy(intent))
        return IntentResult(
            intent_id=intent.id,
            agent_id="target_agent_001",
            success=True,
        )

    bus.subscribe("target_agent_001", _target, ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
    )
    params = {
        "text": "describe",
        "vision_messages": [{
            "role": "user",
            "content": [{
                "type": "image",
                "source": {
                    "type": "attachment_ref",
                    "sha256": "a" * 64,
                    "media_type": "image/png",
                },
            }],
        }],
        "has_image_attachment": True,
        "_transport_stripped": ["vision_messages"],
    }

    await bridge.handle_inbound(_directed_request(params=params))

    assert len(seen) == 1
    assert seen[0].params["_transport_stripped"] == ["vision_messages"]
    assert seen[0].params["vision_messages"] == params["vision_messages"]


@pytest.mark.asyncio
async def test_unknown_delivery_mode_from_configured_peer_returns_one_error_without_dispatch() -> None:
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
    )

    await bridge.handle_inbound(
        _directed_request(delivery_mode="unknown_mode")
    )

    responses = _response_messages(transport)
    assert len(responses) == 1
    assert responses[0].payload["results"][0]["error"] == (
        "federation_delivery_mode_invalid"
    )
    assert bus.send_calls == 0
    assert bus.broadcast_calls == 0


@pytest.mark.asyncio
async def test_disconnected_configured_target_returns_unavailable_before_request() -> None:
    transport = _CapturingRequestTransport(connected_peers=[])
    bridge, _, _ = _make_bridge(transport=transport)

    result = await bridge.forward_direct_message("node-b", _text_intent())

    assert result.error == "federation_target_node_unavailable"
    assert transport.requests == []


@pytest.mark.asyncio
async def test_outbound_non_dm_and_non_dict_params_use_exact_errors() -> None:
    bridge, transport, _ = _make_bridge()

    non_dm = await bridge.forward_direct_message(
        "node-b", _text_intent(intent_name="write_file")
    )
    malformed = await bridge.forward_direct_message(
        "node-b", _text_intent(params=[])
    )

    assert non_dm.error == "federation_directed_intent_not_allowed"
    assert malformed.error == "federation_payload_invalid"
    assert transport.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport_factory",
    [
        pytest.param(
            lambda: NATSFederationTransport(
                node_id="node-a",
                nats_bus=MockNATSBus(),
                peer_node_ids=["node-b"],
            ),
            id="nats",
        ),
        pytest.param(
            lambda: MockFederationTransport(
                "node-a", MockTransportBus()
            ),
            id="mock",
        ),
    ],
)
async def test_request_peer_timeout_returns_none_and_cleans_pending(
    transport_factory: Callable[[], Any],
) -> None:
    transport = transport_factory()
    message = FederationMessage(
        type="intent_request",
        source_node="node-a",
        message_id="timeout-cleanup",
        payload={"delivery_mode": "targeted_dm"},
    )

    response = await transport.request_peer("node-b", message, 1)

    assert response is None
    assert transport._pending_requests == {}


@pytest.mark.asyncio
async def test_zeromq_request_peer_correlation_and_cleanup_without_socket() -> None:
    transport = object.__new__(FederationTransport)
    transport._pending_requests = {}
    sent: list[tuple[str, FederationMessage]] = []

    async def _send(
        peer_node_id: str, message: FederationMessage
    ) -> None:
        sent.append((peer_node_id, message))
        await transport.deliver_response(
            peer_node_id,
            FederationMessage(
                type="intent_response",
                source_node=peer_node_id,
                message_id=message.message_id,
                payload={"delivery_mode": "targeted_dm"},
            ),
        )

    transport.send_to_peer = _send
    request = FederationMessage(
        type="intent_request",
        source_node="node-a",
        message_id="zmq-exact",
        payload={"delivery_mode": "targeted_dm"},
    )

    response = await transport.request_peer("node-b", request, 100)

    assert sent == [("node-b", request)]
    assert response is not None
    assert response.message_id == "zmq-exact"
    assert transport._pending_requests == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transport_factory",
    [
        pytest.param(
            lambda: NATSFederationTransport(
                node_id="node-a",
                nats_bus=MockNATSBus(),
                peer_node_ids=["node-b"],
            ),
            id="nats",
        ),
        pytest.param(
            lambda: MockFederationTransport(
                "node-a", MockTransportBus()
            ),
            id="mock",
        ),
    ],
)
async def test_transport_stop_cancels_outstanding_request_peer(
    transport_factory: Callable[[], Any],
) -> None:
    transport = transport_factory()
    request = FederationMessage(
        type="intent_request",
        source_node="node-a",
        message_id="stop-outstanding",
        payload={"delivery_mode": "targeted_dm"},
    )
    task = asyncio.create_task(
        transport.request_peer("node-b", request, 60_000)
    )
    await asyncio.sleep(0)

    await transport.stop()

    assert transport._pending_requests == {}
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_forward_direct_message_request_wait_cancellation_propagates_and_cleans_pending() -> None:
    transport_bus = MockTransportBus()
    transport = MockFederationTransport("node-a", transport_bus)
    MockFederationTransport("node-b", transport_bus)
    bridge, _, _ = _make_bridge(transport=transport)
    task = asyncio.create_task(
        bridge.forward_direct_message("node-b", _text_intent())
    )
    await asyncio.sleep(0)
    assert len(transport._pending_requests) == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert transport._pending_requests == {}


@pytest.mark.asyncio
async def test_directed_plain_json_nonfinite_unknown_value_is_dropped_by_allowlist() -> None:
    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        return _directed_response(request)

    transport = _CapturingRequestTransport(response_factory=_respond)
    bridge, _, _ = _make_bridge(transport=transport)

    result = await bridge.forward_direct_message(
        "node-b",
        _text_intent(params={"text": "safe", "unknown": math.nan}),
    )

    assert result.success is True
    assert transport.requests[0][1].payload["params"] == {"text": "safe"}


# ---------------------------------------------------------------------------
# AD-730-4 blocked-review corrections C1-C6
# ---------------------------------------------------------------------------


class _HostileList(list):
    touched = 0

    def __iter__(self):
        type(self).touched += 1
        raise AssertionError("hostile list override invoked")

    def __len__(self):
        type(self).touched += 1
        raise AssertionError("hostile list override invoked")

    def __getitem__(self, key):
        type(self).touched += 1
        raise AssertionError("hostile list override invoked")


class _HostileDict(dict):
    touched = 0

    def items(self):
        type(self).touched += 1
        raise AssertionError("hostile dict override invoked")

    def get(self, key, default=None):
        type(self).touched += 1
        raise AssertionError("hostile dict override invoked")

    def __iter__(self):
        type(self).touched += 1
        raise AssertionError("hostile dict override invoked")


class _HostileString(str):
    touched = 0

    def encode(self, *args, **kwargs):
        type(self).touched += 1
        raise AssertionError("hostile string override invoked")

    def lower(self):
        type(self).touched += 1
        raise AssertionError("hostile string override invoked")

    def __eq__(self, other):
        type(self).touched += 1
        raise AssertionError("hostile string override invoked")

    __hash__ = str.__hash__


class _HostileInt(int):
    touched = 0

    def __int__(self):
        type(self).touched += 1
        raise AssertionError("hostile int override invoked")

    def __float__(self):
        type(self).touched += 1
        raise AssertionError("hostile int override invoked")


def _result_policy_value(case: str) -> Any:
    if case == "bytes":
        return b"binary"
    if case == "bytearray":
        return bytearray(b"binary")
    if case == "memoryview":
        return memoryview(b"binary")
    if case == "nan":
        return float("nan")
    if case == "infinity":
        return float("inf")
    if case == "int64-overflow":
        return 2**63
    if case == "cycle":
        cyclic: list[Any] = []
        cyclic.append(cyclic)
        return cyclic
    if case == "depth":
        nested: Any = "leaf"
        for _ in range(17):
            nested = [nested]
        return nested
    if case == "nodes":
        return [None] * 4_096
    if case == "string-chars":
        return "x" * 65_537
    if case == "twenty-megabyte-string":
        return "x" * 20_000_000
    if case == "cumulative-utf8":
        return ["x" * 60_000 for _ in range(5)]
    if case == "response-json-bytes":
        return ["x" * 65_520 for _ in range(4)]
    raise AssertionError(f"unknown result-policy case: {case}")


def _response_for_result_value(
    request: FederationMessage,
    value: Any,
    **overrides: Any,
) -> FederationMessage:
    raw_result = {
        "intent_id": request.payload["id"],
        "agent_id": request.payload["target_agent_id"],
        "success": True,
        "result": value,
        "error": None,
        "confidence": 0.8,
    }
    raw_result.update(overrides)
    return _directed_response(request, results=[raw_result])


@pytest.mark.asyncio
async def test_directed_result_policy_accepts_legitimate_text_and_shallow_object_unchanged() -> None:
    value = {
        "summary": "ordinary text",
        "data": {"rows": [1, 2, None, True, 3.5]},
    }

    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        return _response_for_result_value(request, value)

    bridge, _, _ = _make_bridge(
        transport=_CapturingRequestTransport(response_factory=_respond)
    )

    result = await bridge.forward_direct_message("node-b", _text_intent())
    value["data"]["rows"].append("mutated")

    assert result.success is True
    assert result.result == {
        "summary": "ordinary text",
        "data": {"rows": [1, 2, None, True, 3.5]},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "bytes",
        "bytearray",
        "memoryview",
        "nan",
        "infinity",
        "int64-overflow",
        "cycle",
        "depth",
        "nodes",
        "string-chars",
        "twenty-megabyte-string",
        "cumulative-utf8",
        "response-json-bytes",
    ],
)
async def test_directed_result_policy_rejects_binary_nonfinite_cycle_depth_nodes_string_and_json_byte_limits(
    case: str,
) -> None:
    value = _result_policy_value(case)

    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        return _response_for_result_value(request, value)

    bridge, _, _ = _make_bridge(
        transport=_CapturingRequestTransport(response_factory=_respond)
    )

    result = await bridge.forward_direct_message("node-b", _text_intent())

    assert result.error == "federation_result_not_serializable"
    assert result.result is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        pytest.param(
            " \tDaTa:ImAgE/pNg;BaSe64,AAAA", False, id="data-url"
        ),
        pytest.param(
            {"type": "image_url", "url": "https://private.invalid/x"},
            False,
            id="image-url-type",
        ),
        pytest.param(
            {"image_url": {"url": "https://private.invalid/x"}},
            False,
            id="image-url-key",
        ),
        pytest.param(
            {"type": "base64", "data": "AAAA"},
            False,
            id="base64-data",
        ),
        pytest.param(
            {"type": "image", "data": "AAAA"},
            False,
            id="image-data",
        ),
        pytest.param(
            {"source": {"type": "base64", "data": "AAAA"}},
            False,
            id="base64-source",
        ),
        pytest.param(
            "The terms image_url and data:image are prohibited.",
            True,
            id="ordinary-prose",
        ),
        pytest.param(
            {"data": {"rows": [1, 2]}, "summary": "ok"},
            True,
            id="ordinary-data-object",
        ),
    ],
)
async def test_directed_result_policy_rejects_data_url_image_url_and_base64_source_shapes_but_not_prose_or_ordinary_data_object(
    value: Any,
    accepted: bool,
) -> None:
    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        return _response_for_result_value(request, value)

    bridge, _, _ = _make_bridge(
        transport=_CapturingRequestTransport(response_factory=_respond)
    )

    result = await bridge.forward_direct_message("node-b", _text_intent())

    if accepted:
        assert result.success is True
        assert result.result == value
    else:
        assert result.error == "federation_result_not_serializable"
        assert result.result is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "hostile_type"),
    [
        pytest.param(_HostileList([1]), _HostileList, id="list-subclass"),
        pytest.param(
            _HostileDict({"safe": 1}), _HostileDict, id="dict-subclass"
        ),
        pytest.param(
            {_HostileString("type"): "image_url"},
            _HostileString,
            id="hostile-dict-key-subclass",
        ),
        pytest.param(
            _HostileString("safe"), _HostileString, id="string-subclass"
        ),
        pytest.param(_HostileInt(1), _HostileInt, id="int-subclass"),
    ],
)
async def test_directed_result_policy_rejects_hostile_container_and_scalar_subclasses_without_invoking_overrides(
    value: Any,
    hostile_type: type,
) -> None:
    hostile_type.touched = 0

    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        return _response_for_result_value(request, value)

    bridge, _, _ = _make_bridge(
        transport=_CapturingRequestTransport(response_factory=_respond)
    )

    result = await bridge.forward_direct_message("node-b", _text_intent())

    assert result.error == "federation_result_not_serializable"
    assert hostile_type.touched == 0


def test_directed_result_policy_bounds_million_item_work_before_json_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    million_items = [None] * 1_000_000
    json_called = False

    def _unexpected_json(*_args: Any, **_kwargs: Any) -> str:
        nonlocal json_called
        json_called = True
        raise AssertionError("JSON serialization ran before bounded admission")

    monkeypatch.setattr(bridge_module.json, "dumps", _unexpected_json)

    with pytest.raises(ValueError):
        bridge_module._detach_directed_result_value(million_items)

    source = textwrap.dedent(
        inspect.getsource(bridge_module._detach_directed_result_value)
    )
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_detach_directed_result_value"
    ]
    assert calls == []
    assert "json.dumps" not in source
    assert json_called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["missing", "extra"])
async def test_directed_request_payload_requires_exact_seven_keys_before_prefetch_or_send(
    mutation: str,
) -> None:
    resolver = _CountingResolver()
    transport = _CapturingRequestTransport()
    bus = _CountingBus()

    async def _target(intent: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=intent.id,
            agent_id="target_agent_001",
            success=True,
        )

    bus.subscribe("target_agent_001", _target, ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
        resolver=resolver,
    )
    request = _directed_request()
    if mutation == "missing":
        request.payload.pop("ttl_seconds")
    else:
        request.payload["unknown"] = "not-admitted"

    await bridge.handle_inbound(request)

    response = _response_messages(transport)
    assert len(response) == 1
    assert response[0].payload["results"][0]["error"] == (
        "federation_payload_invalid"
    )
    assert resolver.calls == []
    assert bus.send_calls == 0
    assert bus.broadcast_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "response-extra",
        "response-missing",
        "results-tuple",
        "result-extra",
        "result-missing",
    ],
)
async def test_directed_response_requires_exact_two_key_envelope_and_one_exact_six_key_result(
    mutation: str,
) -> None:
    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        response = _directed_response(request)
        if mutation == "response-extra":
            response.payload["unknown"] = True
        elif mutation == "response-missing":
            response.payload.pop("delivery_mode")
        elif mutation == "results-tuple":
            response.payload["results"] = tuple(response.payload["results"])
        elif mutation == "result-extra":
            response.payload["results"][0]["unknown"] = True
        else:
            response.payload["results"][0].pop("error")
        return response

    bridge, _, _ = _make_bridge(
        transport=_CapturingRequestTransport(response_factory=_respond)
    )

    result = await bridge.forward_direct_message("node-b", _text_intent())

    assert result.error == "federation_response_invalid"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("success", 1, id="non-bool-success"),
        pytest.param("error", 7, id="bad-error-type"),
        pytest.param("error", "x" * 4_097, id="oversized-error"),
        pytest.param("confidence", True, id="bool-confidence"),
        pytest.param("confidence", float("nan"), id="nan-confidence"),
        pytest.param("confidence", float("inf"), id="infinite-confidence"),
        pytest.param("confidence", 10**10000, id="overflow-confidence"),
    ],
)
async def test_directed_result_rejects_non_bool_success_bad_error_and_nonfinite_confidence_before_validator(
    field: str,
    value: Any,
) -> None:
    validator_calls: list[IntentResult] = []

    async def _validate(result: IntentResult) -> bool:
        validator_calls.append(result)
        return True

    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        return _response_for_result_value(request, "safe", **{field: value})

    bridge, _, _ = _make_bridge(
        transport=_CapturingRequestTransport(response_factory=_respond),
        validate_fn=_validate,
    )

    result = await bridge.forward_direct_message("node-b", _text_intent())

    assert result.error == "federation_response_invalid"
    assert validator_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("marker", "accepted"),
    [
        pytest.param(["attachment_ref"], True, id="single"),
        pytest.param(
            ["attachment_ref", "vision_messages"],
            True,
            id="ordered-subset",
        ),
        pytest.param([], False, id="empty"),
        pytest.param(
            ["attachment_ref", "attachment_ref"], False, id="duplicate"
        ),
        pytest.param(
            ["vision_messages", "attachment_ref"], False, id="reordered"
        ),
        pytest.param(["unknown"], False, id="unknown"),
        pytest.param([7], False, id="non-string"),
        pytest.param([_HostileString("attachment_ref")], False, id="subclass"),
    ],
)
async def test_transport_stripped_requires_canonical_ordered_unique_subset_and_rejects_million_entries_without_scan(
    marker: list[Any],
    accepted: bool,
) -> None:
    transport = _CapturingRequestTransport()
    bus = _CountingBus()

    async def _target(intent: IntentMessage) -> IntentResult:
        return IntentResult(
            intent_id=intent.id,
            agent_id="target_agent_001",
            success=True,
        )

    bus.subscribe("target_agent_001", _target, ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
    )
    params = {
        "text": "hello",
        "_transport_stripped": marker,
    }

    await bridge.handle_inbound(_directed_request(params=params))

    result = _response_messages(transport)[0].payload["results"][0]
    if accepted:
        assert result["success"] is True
        assert bus.send_calls == 1
    else:
        assert result["error"] == "federation_payload_invalid"
        assert bus.send_calls == 0

    _HostileString.touched = 0
    bomb = _HostileString("attachment_ref")
    million_marker = [bomb] * 1_000_000
    assert bridge_module._validate_transport_stripped_marker(
        million_marker
    ) is False
    assert _HostileString.touched == 0

    for helper_name in (
        "_validate_transport_stripped_marker",
        "_extract_exact_directed_request_payload",
    ):
        source = textwrap.dedent(
            inspect.getsource(getattr(bridge_module, helper_name))
        )
        tree = ast.parse(source)
        function = tree.body[0]
        loops = [
            node
            for node in ast.walk(function)
            if isinstance(node, (ast.For, ast.comprehension))
        ]
        length_guards = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and (
                isinstance(node.func, ast.Name)
                and node.func.id == "len"
                or isinstance(node.func, ast.Attribute)
                and node.func.attr == "__len__"
            )
        ]
        assert length_guards
        assert loops
        assert min(node.lineno for node in length_guards) < min(
            node.lineno for node in loops
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message_id",
    [
        pytest.param("", id="empty"),
        pytest.param("bad.id", id="punctuation"),
        pytest.param("x" * 129, id="oversized"),
        pytest.param(7, id="non-string"),
        pytest.param(_HostileString("safe-id"), id="string-subclass"),
    ],
)
async def test_directed_malformed_request_message_id_drops_before_provenance_prefetch_send_or_response(
    message_id: Any,
) -> None:
    resolver = _CountingResolver()
    transport = _CapturingRequestTransport()
    bus = _CountingBus()
    target_calls: list[IntentMessage] = []

    async def _target(intent: IntentMessage) -> IntentResult:
        target_calls.append(intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="target_agent_001",
            success=True,
        )

    bus.subscribe("target_agent_001", _target, ["direct_message"])
    bridge, _, _ = _make_bridge(
        node_id="node-b",
        peer_node_id="node-a",
        transport=transport,
        intent_bus=bus,
        resolver=resolver,
    )

    await bridge.handle_inbound(_directed_request(message_id=message_id))

    assert transport.sent == []
    assert resolver.calls == []
    assert target_calls == []
    assert bus.send_calls == 0
    assert bus.broadcast_calls == 0


_TRANSPORT_CASES = [
    pytest.param("nats", id="nats"),
    pytest.param("mock", id="mock"),
    pytest.param("zeromq", id="zeromq"),
]


def _request_transport(case: str) -> Any:
    if case == "nats":
        return NATSFederationTransport(
            node_id="node-a",
            nats_bus=MockNATSBus(),
            peer_node_ids=["node-b"],
        )
    if case == "mock":
        return MockFederationTransport("node-a", MockTransportBus())
    transport = object.__new__(FederationTransport)
    transport._node_id = "node-a"
    transport._running = False
    transport._response_queues = {}
    transport._pending_requests = {}
    transport._request_admission_open = True
    transport._recv_task = None
    transport._dealer_sockets = {}
    transport._router_socket = None
    transport._ctx = None
    return transport


def _transport_request(message_id: Any = "shared-request") -> FederationMessage:
    return FederationMessage(
        type="intent_request",
        source_node="node-a",
        message_id=message_id,
        payload={"delivery_mode": "targeted_dm"},
    )


class _FakeZmqSocket:
    def __init__(self) -> None:
        self._waiter: asyncio.Future[list[bytes]] | None = None

    def bind(self, _address: str) -> None:
        return None

    def connect(self, _address: str) -> None:
        return None

    def setsockopt(self, _name: Any, _value: Any) -> None:
        return None

    async def send(self, _payload: bytes) -> None:
        return None

    async def recv_multipart(self) -> list[bytes]:
        self._waiter = asyncio.get_running_loop().create_future()
        return await self._waiter

    def close(self, *, linger: int = 0) -> None:
        return None


class _FakeZmqContext:
    def __init__(self) -> None:
        self.sockets: list[_FakeZmqSocket] = []

    def socket(self, _socket_type: Any) -> _FakeZmqSocket:
        socket = _FakeZmqSocket()
        self.sockets.append(socket)
        return socket

    def term(self) -> None:
        return None


class _FakeFederationNATSBus:
    connected = True

    async def subscribe_raw(
        self, _subject: str, _handler: Callable[..., Awaitable[None]]
    ) -> object:
        return object()

    async def publish_raw(self, _subject: str, _payload: Any) -> None:
        return None


async def _start_request_transport(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    if case == "nats":
        transport = NATSFederationTransport(
            node_id="node-a",
            nats_bus=_FakeFederationNATSBus(),
            peer_node_ids=["node-b"],
        )
    elif case == "mock":
        transport = MockFederationTransport("node-a", MockTransportBus())
    else:
        fake_context = _FakeZmqContext()
        monkeypatch.setattr(
            federation_transport_module.zmq.asyncio,
            "Context",
            lambda: fake_context,
        )
        transport = FederationTransport(
            node_id="node-a",
            bind_address="tcp://127.0.0.1:65529",
            peers=[
                PeerConfig(
                    node_id="node-b",
                    address="tcp://127.0.0.1:65530",
                )
            ],
        )
    await transport.start()
    return transport


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_case", _TRANSPORT_CASES)
async def test_request_peer_duplicate_live_key_rejected_without_replacing_owner(
    transport_case: str,
) -> None:
    transport = _request_transport(transport_case)
    send_entered = asyncio.Event()
    release_send = asyncio.Event()
    sends: list[FederationMessage] = []

    async def _send(_peer: str, message: FederationMessage) -> None:
        sends.append(message)
        send_entered.set()
        await release_send.wait()

    transport.send_to_peer = _send
    request = _transport_request()
    owner_task = asyncio.create_task(
        transport.request_peer("node-b", request, 60_000)
    )
    await send_entered.wait()
    owner = transport._pending_requests[("node-b", "shared-request")]

    with pytest.raises(
        RuntimeError, match="^federation_request_key_in_use$"
    ):
        await transport.request_peer("node-b", request, 60_000)

    assert transport._pending_requests[("node-b", "shared-request")] is owner
    assert len(sends) == 1
    owner_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner_task
    assert transport._pending_requests == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_case", _TRANSPORT_CASES)
async def test_request_peer_owner_cleanup_cannot_remove_new_same_key_owner(
    transport_case: str,
) -> None:
    transport = _request_transport(transport_case)
    send_entered = asyncio.Event()
    release_send = asyncio.Event()

    async def _send(_peer: str, _message: FederationMessage) -> None:
        send_entered.set()
        await release_send.wait()

    transport.send_to_peer = _send
    task = asyncio.create_task(
        transport.request_peer("node-b", _transport_request(), 60_000)
    )
    await send_entered.wait()
    key = ("node-b", "shared-request")
    old_owner = transport._pending_requests[key]
    new_owner = asyncio.get_running_loop().create_future()
    transport._pending_requests[key] = new_owner

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert old_owner.cancelled()
    assert transport._pending_requests[key] is new_owner
    assert not new_owner.cancelled()
    transport._pending_requests.clear()
    new_owner.cancel()


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_case", _TRANSPORT_CASES)
async def test_request_peer_post_stop_rejected_without_registration_or_send(
    transport_case: str,
) -> None:
    transport = _request_transport(transport_case)
    sends: list[FederationMessage] = []

    async def _send(_peer: str, message: FederationMessage) -> None:
        sends.append(message)

    transport.send_to_peer = _send
    await transport.stop()

    with pytest.raises(RuntimeError, match="^federation_transport_closed$"):
        await transport.request_peer(
            "node-b", _transport_request(), 100
        )

    assert transport._pending_requests == {}
    assert sends == []


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_case", _TRANSPORT_CASES)
@pytest.mark.parametrize(
    ("peer_node_id", "message"),
    [
        pytest.param(
            "bad.peer", _transport_request(), id="bad-peer-id"
        ),
        pytest.param(
            "node-b", _transport_request("bad.id"), id="bad-message-id"
        ),
        pytest.param(
            "node-b", object(), id="non-federation-message"
        ),
    ],
)
async def test_request_peer_invalid_correlation_inputs_reject_before_registration_or_send(
    transport_case: str,
    peer_node_id: str,
    message: Any,
) -> None:
    transport = _request_transport(transport_case)
    sends: list[Any] = []

    async def _send(_peer: str, sent_message: Any) -> None:
        sends.append(sent_message)

    transport.send_to_peer = _send

    with pytest.raises(
        ValueError, match="^federation_correlation_id_invalid$"
    ):
        await transport.request_peer(peer_node_id, message, 100)

    assert transport._pending_requests == {}
    assert sends == []


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_case", _TRANSPORT_CASES)
async def test_request_peer_accepts_existing_underscore_leading_node_id_contract(
    transport_case: str,
) -> None:
    transport = _request_transport(transport_case)

    async def _send(peer: str, message: FederationMessage) -> None:
        await transport.deliver_response(
            peer,
            FederationMessage(
                type="intent_response",
                source_node=peer,
                message_id=message.message_id,
                payload={"delivery_mode": "targeted_dm", "results": []},
            ),
        )

    transport.send_to_peer = _send

    response = await transport.request_peer(
        "_node_b", _transport_request("underscore-node-request"), 100
    )

    assert response is not None
    assert response.source_node == "_node_b"


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_case", _TRANSPORT_CASES)
async def test_request_peer_start_reopens_admission(
    transport_case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = await _start_request_transport(transport_case, monkeypatch)
    await transport.stop()
    with pytest.raises(RuntimeError, match="^federation_transport_closed$"):
        await transport.request_peer(
            "node-b", _transport_request("closed-request"), 100
        )

    await transport.start()

    async def _send(peer: str, message: FederationMessage) -> None:
        await transport.deliver_response(
            peer,
            FederationMessage(
                type="intent_response",
                source_node=peer,
                message_id=message.message_id,
                payload={"delivery_mode": "targeted_dm", "results": []},
            ),
        )

    transport.send_to_peer = _send
    response = await transport.request_peer(
        "node-b", _transport_request("reopened-request"), 100
    )

    assert response is not None
    assert response.message_id == "reopened-request"
    await transport.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_case", _TRANSPORT_CASES)
async def test_request_peer_stop_restart_old_finally_cannot_remove_new_same_key_owner(
    transport_case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = await _start_request_transport(transport_case, monkeypatch)
    old_send_entered = asyncio.Event()
    old_send_release = asyncio.Event()
    new_send_entered = asyncio.Event()
    new_send_release = asyncio.Event()
    send_count = 0

    async def _send(_peer: str, _message: FederationMessage) -> None:
        nonlocal send_count
        send_count += 1
        if send_count == 1:
            old_send_entered.set()
            await old_send_release.wait()
        else:
            new_send_entered.set()
            await new_send_release.wait()

    transport.send_to_peer = _send
    request = _transport_request("restart-shared")
    old_task = asyncio.create_task(
        transport.request_peer("node-b", request, 60_000)
    )
    await old_send_entered.wait()

    await transport.stop()
    await transport.start()
    transport.send_to_peer = _send
    new_task = asyncio.create_task(
        transport.request_peer("node-b", request, 60_000)
    )
    await new_send_entered.wait()
    new_owner = transport._pending_requests[("node-b", "restart-shared")]

    old_send_release.set()
    with pytest.raises(asyncio.CancelledError):
        await old_task

    assert transport._pending_requests[("node-b", "restart-shared")] is new_owner
    assert not new_owner.cancelled()
    new_send_release.set()
    await transport.deliver_response(
        "node-b",
        FederationMessage(
            type="intent_response",
            source_node="node-b",
            message_id="restart-shared",
            payload={"delivery_mode": "targeted_dm", "results": []},
        ),
    )
    response = await new_task
    assert response is not None
    assert transport._pending_requests == {}
    await transport.stop()


@pytest.mark.asyncio
async def test_request_peer_registers_before_synchronous_mock_response() -> None:
    transport = MockFederationTransport("node-a", MockTransportBus())
    owner_seen = False

    async def _send(peer: str, message: FederationMessage) -> None:
        nonlocal owner_seen
        owner_seen = (
            transport._pending_requests.get((peer, message.message_id))
            is not None
        )
        await transport.deliver_response(
            peer,
            FederationMessage(
                type="intent_response",
                source_node=peer,
                message_id=message.message_id,
                payload={"delivery_mode": "targeted_dm", "results": []},
            ),
        )

    transport.send_to_peer = _send

    response = await transport.request_peer(
        "node-b", _transport_request("sync-response"), 100
    )

    assert owner_seen is True
    assert response is not None
    assert response.message_id == "sync-response"


@pytest.mark.asyncio
async def test_bridge_post_stop_rejects_and_start_reopens_directed_admission() -> None:
    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        return _directed_response(request)

    transport = _CapturingRequestTransport(response_factory=_respond)
    bridge, _, _ = _make_bridge(transport=transport)

    await bridge.stop()
    closed = await bridge.forward_direct_message("node-b", _text_intent())
    assert closed.error == "federation_target_node_unavailable"
    assert transport.requests == []

    await bridge.start()
    try:
        reopened = await bridge.forward_direct_message(
            "node-b", _text_intent()
        )
    finally:
        await bridge.stop()

    assert reopened.success is True
    assert len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport_error", "expected_error"),
    [
        pytest.param(
            RuntimeError("federation_transport_closed"),
            "federation_target_node_unavailable",
            id="transport-closed",
        ),
        pytest.param(
            RuntimeError("federation_request_key_in_use"),
            "federation_target_delivery_failed",
            id="duplicate-key",
        ),
        pytest.param(
            ValueError("federation_correlation_id_invalid"),
            "federation_target_delivery_failed",
            id="invalid-correlation-invariant",
        ),
    ],
)
async def test_bridge_maps_transport_admission_errors_to_exact_result_codes(
    transport_error: Exception,
    expected_error: str,
) -> None:
    class _AdmissionFailingTransport(_CapturingRequestTransport):
        async def request_peer(
            self,
            peer_node_id: str,
            message: FederationMessage,
            timeout_ms: int,
        ) -> FederationMessage | None:
            self.requests.append((peer_node_id, message, timeout_ms))
            raise transport_error

    bridge, transport, _ = _make_bridge(
        transport=_AdmissionFailingTransport()
    )

    result = await bridge.forward_direct_message("node-b", _text_intent())

    assert result.error == expected_error
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_nats_swallowed_publish_error_remains_timeout_not_immediate_unavailable() -> None:
    class _FailingNATSBus:
        connected = True

        async def publish_raw(self, _subject: str, _data: Any) -> None:
            raise RuntimeError("publish failed")

    transport = NATSFederationTransport(
        node_id="node-a",
        nats_bus=_FailingNATSBus(),
        peer_node_ids=["node-b"],
    )
    bridge, _, _ = _make_bridge(transport=transport)

    result = await bridge.forward_direct_message(
        "node-b", _text_intent(ttl_seconds=0.00001)
    )

    assert result.error == "federation_peer_timeout"
    assert transport._pending_requests == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_case", _TRANSPORT_CASES)
@pytest.mark.parametrize(
    "message_id",
    [
        pytest.param("", id="empty"),
        pytest.param("bad.id", id="punctuation"),
        pytest.param("x" * 129, id="oversized"),
        pytest.param(7, id="non-string"),
        pytest.param(_HostileString("safe-id"), id="string-subclass"),
    ],
)
async def test_directed_malformed_response_message_id_is_dropped(
    transport_case: str,
    message_id: Any,
) -> None:
    transport = _request_transport(transport_case)
    response = FederationMessage(
        type="intent_response",
        source_node="node-b",
        message_id=message_id,
        payload={"delivery_mode": "targeted_dm", "results": []},
    )

    await transport.deliver_response("node-b", response)

    assert await transport.receive_with_timeout("node-b", 1) is None
    assert transport._pending_requests == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_case", _TRANSPORT_CASES)
@pytest.mark.parametrize(
    "message_id",
    [
        pytest.param("", id="empty"),
        pytest.param("bad.id", id="punctuation"),
        pytest.param("x" * 129, id="oversized"),
        pytest.param(7, id="non-string"),
        pytest.param(_HostileString("safe-id"), id="string-subclass"),
    ],
)
async def test_legacy_malformed_response_message_id_preserves_peer_queue_behavior(
    transport_case: str,
    message_id: Any,
) -> None:
    transport = _request_transport(transport_case)
    response = FederationMessage(
        type="intent_response",
        source_node="node-b",
        message_id=message_id,
        payload={"results": []},
    )

    await transport.deliver_response("node-b", response)

    assert await transport.receive_with_timeout("node-b", 10) is response
    assert transport._pending_requests == {}


class _OutboundCanaryError(RuntimeError):
    def __str__(self) -> str:
        raise AssertionError("outbound exception message was inspected")


class _ValidatorCanaryError(RuntimeError):
    pass


class _ResolverCanaryError(RuntimeError):
    pass


class _TargetCanaryError(RuntimeError):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("boundary", "exception_type", "stable_action"),
    [
        pytest.param(
            "outbound",
            "_OutboundCanaryError",
            "federation_target_delivery_failed",
            id="outbound-request-peer",
        ),
        pytest.param(
            "validator",
            "_ValidatorCanaryError",
            "validator_passed_without_validation",
            id="remote-result-validator",
        ),
        pytest.param(
            "resolver",
            "_ResolverCanaryError",
            "deliver_to_exact_target_without_prefetch",
            id="inbound-attachment-resolver",
        ),
        pytest.param(
            "target",
            "_TargetCanaryError",
            "federation_target_delivery_failed",
            id="exact-target-delivery",
        ),
    ],
)
async def test_directed_exception_logs_are_type_only_without_message_traceback_or_payload(
    boundary: str,
    exception_type: str,
    stable_action: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    canary = "CANARY_SECRET_BLOB_TOKEN_AAAA"
    caplog.set_level("WARNING", logger="probos.federation.bridge")

    if boundary == "outbound":
        class _FailingTransport(_CapturingRequestTransport):
            async def request_peer(
                self,
                peer_node_id: str,
                message: FederationMessage,
                timeout_ms: int,
            ) -> FederationMessage | None:
                self.requests.append((peer_node_id, message, timeout_ms))
                raise _OutboundCanaryError(canary)

        bridge, _, _ = _make_bridge(transport=_FailingTransport())
        result = await bridge.forward_direct_message(
            "node-b", _text_intent(params={"text": "secret dm text"})
        )
        assert result.error == "federation_target_delivery_failed"
    elif boundary == "validator":
        async def _validate(_result: IntentResult) -> bool:
            raise _ValidatorCanaryError(canary)

        def _respond(
            _peer: str, request: FederationMessage, _timeout: int
        ) -> FederationMessage:
            return _directed_response(request)

        bridge, _, _ = _make_bridge(
            transport=_CapturingRequestTransport(response_factory=_respond),
            validate_fn=_validate,
        )
        result = await bridge.forward_direct_message(
            "node-b", _text_intent()
        )
        assert result.success is True
    else:
        transport = _CapturingRequestTransport()
        bus = _CountingBus()

        async def _target(intent: IntentMessage) -> IntentResult:
            if boundary == "target":
                raise _TargetCanaryError(canary)
            return IntentResult(
                intent_id=intent.id,
                agent_id="target_agent_001",
                success=True,
            )

        bus.subscribe("target_agent_001", _target, ["direct_message"])
        resolver = (
            _CountingResolver(error=_ResolverCanaryError(canary))
            if boundary == "resolver"
            else None
        )
        bridge, _, _ = _make_bridge(
            node_id="node-b",
            peer_node_id="node-a",
            transport=transport,
            intent_bus=bus,
            resolver=resolver,
        )
        await bridge.handle_inbound(
            _directed_request(params={"text": "secret dm text"})
        )

    records = [
        record
        for record in caplog.records
        if record.name == "probos.federation.bridge"
    ]
    rendered = "\n".join(record.getMessage() for record in records)
    assert records
    assert exception_type in rendered
    assert f"action={stable_action}" in rendered
    assert canary not in rendered
    assert "secret dm text" not in rendered
    assert _TOKEN not in rendered
    assert "Traceback" not in rendered
    assert all(record.exc_info is None for record in records)


@pytest.mark.asyncio
async def test_directed_result_validator_ordering_follows_schema_correlation_and_bounded_value_checks() -> None:
    validator_calls: list[IntentResult] = []
    response_case = "bad-schema"

    async def _validate(result: IntentResult) -> bool:
        validator_calls.append(result)
        return True

    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        if response_case == "bad-schema":
            return _response_for_result_value(request, "safe", success=1)
        if response_case == "bad-correlation":
            return _response_for_result_value(
                request, "safe", intent_id="other_intent"
            )
        if response_case == "bad-result":
            return _response_for_result_value(request, b"binary")
        return _response_for_result_value(request, {"safe": [1, 2]})

    bridge, _, _ = _make_bridge(
        transport=_CapturingRequestTransport(response_factory=_respond),
        validate_fn=_validate,
    )

    assert (
        await bridge.forward_direct_message("node-b", _text_intent())
    ).error == "federation_response_invalid"
    response_case = "bad-correlation"
    assert (
        await bridge.forward_direct_message("node-b", _text_intent())
    ).error == "federation_result_correlation_mismatch"
    response_case = "bad-result"
    assert (
        await bridge.forward_direct_message("node-b", _text_intent())
    ).error == "federation_result_not_serializable"
    assert validator_calls == []

    response_case = "valid"
    valid = await bridge.forward_direct_message("node-b", _text_intent())
    assert valid.success is True
    assert len(validator_calls) == 1
    assert validator_calls[0].result == {"safe": [1, 2]}


@pytest.mark.asyncio
async def test_directed_result_returns_final_json_loaded_detached_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_dumps = bridge_module.json.dumps

    def _mutating_dumps(value: Any, **kwargs: Any) -> str:
        if (
            type(value) is dict
            and value.get("delivery_mode") == "targeted_dm"
            and type(value.get("results")) is list
            and value["results"]
            and type(value["results"][0]) is dict
            and type(value["results"][0].get("result")) is dict
        ):
            value["results"][0]["result"]["during_encode"] = "mutated"
        return original_dumps(value, **kwargs)

    monkeypatch.setattr(bridge_module.json, "dumps", _mutating_dumps)

    def _respond(
        _peer: str, request: FederationMessage, _timeout: int
    ) -> FederationMessage:
        return _response_for_result_value(request, {"safe": True})

    bridge, _, _ = _make_bridge(
        transport=_CapturingRequestTransport(response_factory=_respond)
    )

    result = await bridge.forward_direct_message("node-b", _text_intent())

    assert result.success is True
    assert result.result == {"safe": True, "during_encode": "mutated"}


@pytest.mark.asyncio
async def test_directed_receiver_requires_exact_intent_result_type_and_fields() -> None:
    class _IntentResultSubclass(IntentResult):
        pass

    for local_result in (
        {"success": True},
        _IntentResultSubclass(
            intent_id="directed_intent_001",
            agent_id="target_agent_001",
            success=True,
        ),
        IntentResult(
            intent_id="directed_intent_001",
            agent_id="target_agent_001",
            success=1,
        ),
    ):
        transport = _CapturingRequestTransport()
        bus = _CountingBus()

        async def _target(_intent: IntentMessage) -> Any:
            return local_result

        bus.subscribe("target_agent_001", _target, ["direct_message"])
        bridge, _, _ = _make_bridge(
            node_id="node-b",
            peer_node_id="node-a",
            transport=transport,
            intent_bus=bus,
        )

        await bridge.handle_inbound(_directed_request())

        result = _response_messages(transport)[0].payload["results"][0]
        assert result["error"] == "federation_result_not_serializable"
        assert result["result"] is None


@pytest.mark.asyncio
async def test_origin_rejects_unsafe_generated_correlation_id_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _CapturingRequestTransport()
    bridge, _, _ = _make_bridge(transport=transport)
    monkeypatch.setattr(
        bridge_module.FederationMessage,
        "__dataclass_fields__",
        bridge_module.FederationMessage.__dataclass_fields__,
        raising=False,
    )

    original_init = bridge_module.FederationMessage.__init__

    def _unsafe_init(self: FederationMessage, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        if self.type == "intent_request" and self.payload.get(
            "delivery_mode"
        ) == "targeted_dm":
            self.message_id = "unsafe.correlation"

    monkeypatch.setattr(bridge_module.FederationMessage, "__init__", _unsafe_init)

    result = await bridge.forward_direct_message("node-b", _text_intent())

    assert result.error == "federation_target_delivery_failed"
    assert transport.requests == []


# ---------------------------------------------------------------------------
# AD-730-4 blocked-review corrections C7-C9
# ---------------------------------------------------------------------------


def _c7_result_fields(
    position: str,
    value: str,
) -> tuple[Any, str | None, bool]:
    if position == "dict-key":
        return {value: "safe value"}, None, True
    if position == "error":
        return None, value, False
    return value, None, True


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["receiver", "origin"])
@pytest.mark.parametrize(
    ("position", "value", "accepted"),
    [
        pytest.param(
            "scalar",
            " \tdata:image/png",
            False,
            id="scalar-prefix",
        ),
        pytest.param(
            "dict-key",
            "\nDaTa:ImAgE/svg+xml",
            False,
            id="mixed-case-dict-key-prefix",
        ),
        pytest.param(
            "error",
            "\rDATA:IMAGE/webp",
            False,
            id="mixed-case-error-prefix",
        ),
        pytest.param(
            "scalar",
            "data:image/" + "x" * 129,
            False,
            id="subtype-longer-than-128",
        ),
        pytest.param(
            "scalar",
            "The terms image_url and data:image are prohibited.",
            True,
            id="ordinary-prose",
        ),
    ],
)
async def test_directed_result_policy_rejects_data_image_prefix_in_scalar_dict_key_error_and_long_subtype_at_receiver_and_origin(
    direction: str,
    position: str,
    value: str,
    accepted: bool,
) -> None:
    result_value, error, success = _c7_result_fields(position, value)
    if direction == "origin":
        def _respond(
            _peer: str,
            request: FederationMessage,
            _timeout: int,
        ) -> FederationMessage:
            return _response_for_result_value(
                request,
                result_value,
                error=error,
                success=success,
            )

        bridge, _, _ = _make_bridge(
            transport=_CapturingRequestTransport(
                response_factory=_respond
            )
        )
        origin_result = await bridge.forward_direct_message(
            "node-b", _text_intent()
        )
        observed = {
            "intent_id": origin_result.intent_id,
            "agent_id": origin_result.agent_id,
            "success": origin_result.success,
            "result": origin_result.result,
            "error": origin_result.error,
            "confidence": origin_result.confidence,
        }
    else:
        transport = _CapturingRequestTransport()
        bus = _CountingBus()

        async def _target(intent: IntentMessage) -> IntentResult:
            return IntentResult(
                intent_id=intent.id,
                agent_id="target_agent_001",
                success=success,
                result=result_value,
                error=error,
                confidence=0.8,
            )

        bus.subscribe("target_agent_001", _target, ["direct_message"])
        bridge, _, _ = _make_bridge(
            node_id="node-b",
            peer_node_id="node-a",
            transport=transport,
            intent_bus=bus,
        )
        await bridge.handle_inbound(_directed_request())
        observed = _response_messages(transport)[0].payload["results"][0]

    if accepted:
        assert observed["success"] is True
        assert observed["result"] == value
        assert observed["error"] is None
    else:
        assert observed == {
            "intent_id": "directed_intent_001",
            "agent_id": "target_agent_001",
            "success": False,
            "result": None,
            "error": "federation_result_not_serializable",
            "confidence": 0.0,
        }


def test_directed_result_error_shares_cumulative_utf8_budget_without_incrementing_nodes() -> None:
    exact_budget_result = {
        "intent_id": "directed_intent_001",
        "agent_id": "target_agent_001",
        "success": False,
        "result": ["x" * 64_512 for _ in range(4)],
        "error": "e" * 4_096,
        "confidence": 0.0,
    }
    detached, error = bridge_module._detach_serialized_directed_result(
        exact_budget_result,
        malformed_error="federation_response_invalid",
    )
    assert error is None
    assert detached is not None

    over_budget_result = dict(exact_budget_result)
    over_budget_result["result"] = [
        "x" * 64_513,
        "x" * 64_512,
        "x" * 64_512,
        "x" * 64_512,
    ]
    detached, error = bridge_module._detach_serialized_directed_result(
        over_budget_result,
        malformed_error="federation_response_invalid",
    )
    assert detached is None
    assert error == "federation_result_not_serializable"

    unencodable_error_result = dict(exact_budget_result)
    unencodable_error_result["result"] = None
    unencodable_error_result["error"] = "\ud800"
    detached, error = bridge_module._detach_serialized_directed_result(
        unencodable_error_result,
        malformed_error="federation_response_invalid",
    )
    assert detached is None
    assert error == "federation_result_not_serializable"

    node_boundary_result = dict(exact_budget_result)
    node_boundary_result["result"] = [None] * 4_095
    node_boundary_result["error"] = "safe"
    detached, error = bridge_module._detach_serialized_directed_result(
        node_boundary_result,
        malformed_error="federation_response_invalid",
    )
    assert error is None
    assert detached is not None


class _C8HostileDict(dict):
    touched = 0

    def items(self):
        type(self).touched += 1
        raise AssertionError("hostile marker dict items override invoked")

    def get(self, key, default=None):
        type(self).touched += 1
        raise AssertionError("hostile marker dict get override invoked")

    def __iter__(self):
        type(self).touched += 1
        raise AssertionError("hostile marker dict iter override invoked")

    def __getitem__(self, key):
        type(self).touched += 1
        raise AssertionError("hostile marker dict item override invoked")

    def __contains__(self, key):
        type(self).touched += 1
        raise AssertionError("hostile marker dict contains override invoked")


def _c8_transport_module(transport_case: str) -> Any:
    if transport_case == "nats":
        return nats_transport_module
    if transport_case == "mock":
        return mock_transport_module
    return federation_transport_module


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_case", _TRANSPORT_CASES)
async def test_transport_targeted_marker_classifier_uses_exact_builtins_without_hostile_overrides(
    transport_case: str,
) -> None:
    exact_targeted = _request_transport(transport_case)
    targeted_message = FederationMessage(
        type="intent_response",
        source_node="node-b",
        message_id="exact-targeted",
        payload={"delivery_mode": "targeted_dm", "results": []},
    )
    await exact_targeted.deliver_response("node-b", targeted_message)
    assert await exact_targeted.receive_with_timeout("node-b", 1) is None

    hostile_payload = _C8HostileDict({
        "delivery_mode": "targeted_dm",
        "results": [],
    })
    _C8HostileDict.touched = 0
    dict_subclass_transport = _request_transport(transport_case)
    dict_subclass_message = FederationMessage(
        type="intent_response",
        source_node="node-b",
        message_id="dict-subclass-marker",
        payload=hostile_payload,
    )
    await dict_subclass_transport.deliver_response(
        "node-b", dict_subclass_message
    )
    assert await dict_subclass_transport.receive_with_timeout(
        "node-b", 10
    ) is dict_subclass_message
    assert _C8HostileDict.touched == 0

    hostile_key = _HostileString("delivery_mode")
    key_subclass_payload = {hostile_key: "targeted_dm", "results": []}
    _HostileString.touched = 0
    key_subclass_transport = _request_transport(transport_case)
    key_subclass_message = FederationMessage(
        type="intent_response",
        source_node="node-b",
        message_id="key-subclass-marker",
        payload=key_subclass_payload,
    )
    await key_subclass_transport.deliver_response(
        "node-b", key_subclass_message
    )
    assert await key_subclass_transport.receive_with_timeout(
        "node-b", 10
    ) is key_subclass_message
    assert _HostileString.touched == 0

    hostile_value = _HostileString("targeted_dm")
    value_subclass_payload = {
        "delivery_mode": hostile_value,
        "results": [],
    }
    _HostileString.touched = 0
    value_subclass_transport = _request_transport(transport_case)
    value_subclass_message = FederationMessage(
        type="intent_response",
        source_node="node-b",
        message_id="value-subclass-marker",
        payload=value_subclass_payload,
    )
    await value_subclass_transport.deliver_response(
        "node-b", value_subclass_message
    )
    assert await value_subclass_transport.receive_with_timeout(
        "node-b", 10
    ) is value_subclass_message
    assert _HostileString.touched == 0

    classifier = _c8_transport_module(
        transport_case
    )._is_targeted_directed_response
    classifier_source = textwrap.dedent(inspect.getsource(classifier))
    assert "dict.items(payload)" in classifier_source
    assert "payload.get" not in classifier_source
    assert "payload[" not in classifier_source
    assert "dict.get" not in classifier_source
    assert "dict.__contains__" not in classifier_source


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_case", _TRANSPORT_CASES)
async def test_transport_malformed_marker_preserves_legacy_queue_but_exact_targeted_malformed_id_drops(
    transport_case: str,
) -> None:
    for message_id in ("safe-legacy-marker", "bad.legacy.id"):
        malformed_transport = _request_transport(transport_case)
        malformed_message = FederationMessage(
            type="intent_response",
            source_node="node-b",
            message_id=message_id,
            payload={"delivery_mode": "TARGETED_DM", "results": []},
        )
        await malformed_transport.deliver_response(
            "node-b", malformed_message
        )
        assert await malformed_transport.receive_with_timeout(
            "node-b", 10
        ) is malformed_message

    exact_targeted_transport = _request_transport(transport_case)
    exact_targeted_message = FederationMessage(
        type="intent_response",
        source_node="node-b",
        message_id="bad.targeted.id",
        payload={"delivery_mode": "targeted_dm", "results": []},
    )
    await exact_targeted_transport.deliver_response(
        "node-b", exact_targeted_message
    )
    assert await exact_targeted_transport.receive_with_timeout(
        "node-b", 1
    ) is None


def test_legacy_validator_log_literal_matches_base_utf8_em_dash() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    relative_path = "src/probos/federation/bridge.py"
    head_source = subprocess.run(
        ["git", "show", f"HEAD:{relative_path}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    worktree_source = (repo_root / relative_path).read_text(encoding="utf-8")
    expected = (
        "Federation message validator failed — message passed without validation"
    )

    def _extract_literal(source: str) -> str:
        literals = [
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant)
            and type(node.value) is str
            and node.value.startswith("Federation message validator failed")
        ]
        assert len(literals) == 1
        return literals[0]

    for source in (head_source, worktree_source):
        literal = _extract_literal(source)
        assert literal == expected
        encoded = literal.encode("utf-8")
        assert b"\xe2\x80\x94" in encoded
        assert "â€”".encode("utf-8") not in encoded
