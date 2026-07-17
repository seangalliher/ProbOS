"""AD-731a-1d: reference-only federation attachment send tests."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from collections.abc import Iterator, Mapping
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

import httpx
import pytest
from fastapi import FastAPI

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.cognitive_agent import _enrich_vision_messages_with_context
from probos.cognitive.llm_client import OpenAICompatibleClient
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
from probos.federation.attachment_resolve import (
    extract_attachment_shas,
    resolve_missing_attachments,
)
from probos.federation.bridge import (
    _FEDERATED_ATTACHMENT_CANDIDATE_SCAN_LIMIT,
    _FEDERATED_ATTACHMENT_REF_LIMIT,
    _FEDERATED_VISION_SCAN_LIMIT,
    FederationBridge,
)
from probos.federation.nats_transport import NATSFederationTransport
from probos.federation.router import FederationRouter
from probos.federation.transport import FederationTransport
from probos.mesh.intent import IntentBus
from probos.mesh.nats_bus import MockNATSBus
from probos.mesh.signal import SignalManager
from probos.routers import federation_attachments
from probos.startup.fleet_organization import organize_fleet
from probos.substrate.pool_group import PoolGroupRegistry
from probos.types import (
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
_TOKEN = "ad731a-1d-token"
_INLINE_SENTINEL = "A" * (500 * 1024)


class _HostileOverrideInvoked(BaseException):
    pass


def _raise_hostile_override(*_args: Any, **_kwargs: Any) -> Any:
    raise _HostileOverrideInvoked("hostile built-in override was invoked")


class _HostileDict(dict):
    __contains__ = _raise_hostile_override
    __getitem__ = _raise_hostile_override
    __iter__ = _raise_hostile_override
    __len__ = _raise_hostile_override
    get = _raise_hostile_override
    items = _raise_hostile_override


class _HostileList(list):
    __getitem__ = _raise_hostile_override
    __iter__ = _raise_hostile_override
    __len__ = _raise_hostile_override


class _HostileTuple(tuple):
    __getitem__ = _raise_hostile_override
    __iter__ = _raise_hostile_override
    __len__ = _raise_hostile_override


class _HostileStr(str):
    __contains__ = _raise_hostile_override
    __eq__ = _raise_hostile_override
    __hash__ = _raise_hostile_override
    __iter__ = _raise_hostile_override
    __len__ = _raise_hostile_override
    __ne__ = _raise_hostile_override


class _ArmedHostileStr(str):
    def __new__(
        cls,
        value: str,
        calls: list[str],
    ) -> "_ArmedHostileStr":
        instance = str.__new__(cls, value)
        instance._calls = calls
        instance._armed = False
        return instance

    def arm(self) -> None:
        self._armed = True

    def _guard(self, operation: str) -> None:
        if self._armed:
            self._calls.append(operation)
            raise _HostileOverrideInvoked(
                f"armed hostile string key invoked {operation}"
            )

    def __hash__(self) -> int:
        self._guard("__hash__")
        return str.__hash__(self)

    def __eq__(self, other: object) -> bool:
        self._guard("__eq__")
        return bool(str.__eq__(self, other))

    def __str__(self) -> str:
        self._guard("__str__")
        return str.__str__(self)

    def __repr__(self) -> str:
        self._guard("__repr__")
        return str.__repr__(self)

    def __iter__(self) -> Iterator[str]:
        self._guard("__iter__")
        return str.__iter__(self)

    def __len__(self) -> int:
        self._guard("__len__")
        return str.__len__(self)

    def __contains__(self, item: object) -> bool:
        self._guard("__contains__")
        return str.__contains__(self, item)


class _ArmedHostileKey:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self._armed = False
        self._hash = hash("attachment_ref")

    def arm(self) -> None:
        self._armed = True

    def _guard(self, operation: str) -> None:
        if self._armed:
            self._calls.append(operation)
            raise _HostileOverrideInvoked(
                f"armed hostile object key invoked {operation}"
            )

    def __hash__(self) -> int:
        self._guard("__hash__")
        return self._hash

    def __eq__(self, other: object) -> bool:
        self._guard("__eq__")
        return self is other

    def __str__(self) -> str:
        self._guard("__str__")
        return object.__str__(self)

    def __repr__(self) -> str:
        self._guard("__repr__")
        return object.__repr__(self)

    def __iter__(self) -> Iterator[object]:
        self._guard("__iter__")
        return iter(())

    def __len__(self) -> int:
        self._guard("__len__")
        return 0

    def __contains__(self, item: object) -> bool:
        self._guard("__contains__")
        return False


class _ArbitraryMapping(Mapping[str, Any]):
    def __getitem__(self, key: str) -> Any:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


class _ArbitraryIterable:
    def __iter__(self) -> Iterator[str]:
        return iter(("arbitrary",))


class _HostileAttributeObject:
    def __getattribute__(self, _name: str) -> Any:
        raise _HostileOverrideInvoked("hostile attribute access was invoked")


class _HostileNestedValue:
    def __init__(self, calls: list[str]) -> None:
        object.__setattr__(self, "_calls", calls)

    def _raise(self, operation: str) -> Any:
        calls = object.__getattribute__(self, "_calls")
        calls.append(operation)
        raise _HostileOverrideInvoked(
            f"hostile nested value invoked {operation}"
        )

    def __getattribute__(self, name: str) -> Any:
        if name == "_raise":
            return object.__getattribute__(self, name)
        return self._raise(f"__getattribute__:{name}")

    def __contains__(self, _item: object) -> bool:
        return self._raise("__contains__")

    def __eq__(self, _other: object) -> bool:
        return self._raise("__eq__")

    def __getitem__(self, _key: object) -> Any:
        return self._raise("__getitem__")

    def __hash__(self) -> int:
        return self._raise("__hash__")

    def __iter__(self) -> Iterator[object]:
        return self._raise("__iter__")

    def __len__(self) -> int:
        return self._raise("__len__")

    def __repr__(self) -> str:
        return self._raise("__repr__")

    def __str__(self) -> str:
        return self._raise("__str__")

    def get(self, _key: object, _default: Any = None) -> Any:
        return self._raise("get")

    def items(self) -> Any:
        return self._raise("items")


def _exact_container_graph_signature(value: Any) -> tuple[Any, ...]:
    """Capture exact-container topology without invoking hostile overrides."""
    if type(value) is dict:
        return (
            "dict",
            id(value),
            tuple(
                (id(key), _exact_container_graph_signature(child))
                for key, child in dict.items(value)
            ),
        )
    if type(value) is list:
        return (
            "list",
            id(value),
            tuple(_exact_container_graph_signature(child) for child in value),
        )
    if type(value) is tuple:
        return (
            "tuple",
            id(value),
            tuple(_exact_container_graph_signature(child) for child in value),
        )
    return ("leaf", id(value), type(value))


def _sha(index: int) -> str:
    return hashlib.sha256(f"ad731a-1d-{index}".encode()).hexdigest()


def _ref_block(
    sha: str,
    media_type: Any = "image/png",
    **source_extras: Any,
) -> dict[str, Any]:
    return {
        "type": "image",
        "source": {
            "type": "attachment_ref",
            "sha256": sha,
            "media_type": media_type,
            **source_extras,
        },
    }


def _vision_messages(*blocks: Any) -> list[dict[str, Any]]:
    return [{
        "role": "user",
        "content": [
            {"type": "text", "text": "duplicate transport text"},
            *blocks,
        ],
    }]


class _CapturingTransport:
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


async def _capture_forwarded_message(
    params: Any,
) -> tuple[FederationMessage, IntentMessage]:
    transport = _CapturingTransport()
    bridge = FederationBridge(
        node_id="node-a",
        transport=transport,
        router=FederationRouter(),
        intent_bus=IntentBus(SignalManager()),
        config=FederationConfig(
            enabled=True,
            node_id="node-a",
            peers=[
                PeerConfig(
                    node_id="node-b",
                    address="tcp://127.0.0.1:65530",
                )
            ],
            forward_timeout_ms=1,
        ),
        self_model_fn=lambda: NodeSelfModel(node_id="node-a"),
    )
    intent = IntentMessage(
        intent="direct_message",
        params={},
        id="ad731a-1d-captured",
    )
    intent.params = params
    await bridge.forward_intent(intent)
    assert len(transport.sent) == 1
    return transport.sent[0], intent


def _serialized_transport_forms(
    message: FederationMessage,
) -> tuple[bytes, bytes]:
    nats_transport = NATSFederationTransport(
        node_id="measure-nats",
        nats_bus=MockNATSBus(),
        peer_node_ids=[],
    )
    nats_bytes = json.dumps(nats_transport._serialize(message)).encode("utf-8")
    zmq_transport = object.__new__(FederationTransport)
    zmq_bytes = zmq_transport._serialize(message)
    return nats_bytes, zmq_bytes


def _fleet_config(
    *,
    node_id: str,
    peer_node_id: str,
    serve_remote_enabled: bool,
    auto_resolve_remote_enabled: bool,
    a2a_peers: list[A2APeerConfig],
) -> SystemConfig:
    return SystemConfig(
        attachments=AttachmentsConfig(
            serve_remote_enabled=serve_remote_enabled,
            auto_resolve_remote_enabled=auto_resolve_remote_enabled,
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
        build_self_model_fn=lambda: NodeSelfModel(node_id=config.federation.node_id),
        validate_remote_result_fn=None,
        attachment_resolver_fn=attachment_resolver_fn,
        nats_bus=nats_bus,
    )


async def _stop_node(result: Any) -> None:
    if result.federation_bridge is not None:
        await result.federation_bridge.stop()
    if result.federation_transport is not None:
        await result.federation_transport.stop()


@pytest.mark.asyncio
async def test_cross_host_nats_reference_only_prefetches_before_vision_dm_broadcast(
    tmp_path,
) -> None:
    origin_store = FilesystemAttachmentStore(tmp_path / "origin-attachments")
    receiver_store = FilesystemAttachmentStore(tmp_path / "receiver-attachments")
    await origin_store.write(_PNG_SHA, _PNG_BYTES, "image/png")

    origin_config = _fleet_config(
        node_id="node-a",
        peer_node_id="node-b",
        serve_remote_enabled=True,
        auto_resolve_remote_enabled=True,
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
        auto_resolve_remote_enabled=True,
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

    shared_bus = MockNATSBus()
    await shared_bus.start()
    origin_result = None
    receiver_result = None
    inbound_params: list[dict[str, Any]] = []
    store_state_at_broadcast: list[bool] = []
    origin_bus = IntentBus(SignalManager())
    receiver_bus = IntentBus(SignalManager())

    async def _consume_vision_dm(intent: IntentMessage) -> IntentResult:
        inbound_params.append(copy.deepcopy(intent.params))
        blob_present = await receiver_store.exists(_PNG_SHA)
        store_state_at_broadcast.append(blob_present)
        assert blob_present, (
            "receiver attachment was not prefetched before local broadcast"
        )
        return IntentResult(
            intent_id=intent.id,
            agent_id="receiver-vision-consumer",
            success=True,
            result="vision-ready",
        )

    receiver_bus.subscribe(
        "receiver-vision-consumer",
        _consume_vision_dm,
        intent_names=["direct_message"],
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
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
            assert isinstance(
                origin_result.federation_transport, NATSFederationTransport
            )
            assert isinstance(
                receiver_result.federation_transport, NATSFederationTransport
            )

            intent = IntentMessage(
                intent="direct_message",
                params={
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
                },
                id="ad731a-1d-cross-host",
            )
            baseline = copy.deepcopy(intent.params)

            results = await origin_result.federation_bridge.forward_intent(intent)
            receiver_has_blob = await receiver_store.exists(_PNG_SHA)
            receiver_has_vision = bool(
                inbound_params and "vision_messages" in inbound_params[0]
            )
            response_succeeded = bool(results and results[0].success)
            original_unchanged = intent.params == baseline

            assert (
                receiver_has_vision
                and fetches["count"] == 1
                and receiver_has_blob
                and store_state_at_broadcast == [True]
                and response_succeeded
                and original_unchanged
            ), (
                "AD-731a-1d red: receiver lacks vision_messages="
                f"{not receiver_has_vision}; ASGI fetch count={fetches['count']}; "
                f"receiver blob present={receiver_has_blob}; "
                "store present at broadcast="
                f"{store_state_at_broadcast}; response succeeded="
                f"{response_succeeded}; original unchanged="
                f"{original_unchanged}"
            )
        finally:
            if receiver_result is not None:
                await _stop_node(receiver_result)
            if origin_result is not None:
                await _stop_node(origin_result)
            await shared_bus.stop()


@pytest.mark.asyncio
async def test_receiver_prefetched_ref_reaches_vision_dm_vendor_boundary(
    tmp_path,
) -> None:
    origin_store = FilesystemAttachmentStore(tmp_path / "origin-vendor")
    receiver_store = FilesystemAttachmentStore(tmp_path / "receiver-vendor")
    await origin_store.write(_PNG_SHA, _PNG_BYTES, "image/png")
    message, _ = await _capture_forwarded_message({
        "text": "Describe it.",
        "vision_messages": _vision_messages(_ref_block(_PNG_SHA)),
        "has_image_attachment": True,
    })

    origin_config = _fleet_config(
        node_id="node-a",
        peer_node_id="node-b",
        serve_remote_enabled=True,
        auto_resolve_remote_enabled=False,
        a2a_peers=[],
    )
    receiver_config = _fleet_config(
        node_id="node-b",
        peer_node_id="node-a",
        serve_remote_enabled=False,
        auto_resolve_remote_enabled=True,
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
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://origin.test",
    ) as asgi_client:
        stored = await resolve_missing_attachments(
            receiver_runtime,
            message.payload["params"],
            "node-a",
            http=asgi_client,
        )

    assert stored == 1
    assert await receiver_store.read(_PNG_SHA) == _PNG_BYTES
    inbound_vision = message.payload["params"]["vision_messages"]
    enriched = _enrich_vision_messages_with_context(
        inbound_vision,
        "Captain says: Describe it.",
    )
    assert enriched is not None
    client = OpenAICompatibleClient(
        base_url="http://example",
        api_key="key",
        models={"standard": "model"},
        attachment_store=receiver_store,
    )
    resolved = await client._resolve_attachment_refs_for_openai(enriched)

    image = resolved[0]["content"][1]
    assert image["type"] == "image_url"
    data_url = image["image_url"]["url"]
    assert data_url.startswith("data:image/png;base64,")
    assert base64.b64decode(data_url.split(",", 1)[1]) == _PNG_BYTES


@pytest.mark.asyncio
async def test_current_reference_only_vision_shape_forwards_reference_blocks() -> None:
    message, _ = await _capture_forwarded_message({
        "text": "Describe it.",
        "vision_messages": _vision_messages(_ref_block(_PNG_SHA)),
        "has_image_attachment": True,
    })

    params = message.payload["params"]
    assert params["vision_messages"] == [{
        "role": "user",
        "content": [_ref_block(_PNG_SHA)],
    }]
    assert params["has_image_attachment"] is True
    assert params["_transport_stripped"] == ["vision_messages"]
    assert "duplicate transport text" not in json.dumps(params)


@pytest.mark.asyncio
async def test_inline_base64_only_vision_degrades_to_text_only() -> None:
    params = {
        "text": "Describe it.",
        "vision_messages": _vision_messages({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": _INLINE_SENTINEL,
            },
        }),
        "has_image_attachment": True,
    }
    message, _ = await _capture_forwarded_message(params)
    nats_bytes, zmq_bytes = _serialized_transport_forms(message)

    sent = message.payload["params"]
    assert sent["text"] == "Describe it."
    assert "vision_messages" not in sent
    assert "has_image_attachment" not in sent
    assert sent["_transport_stripped"] == [
        "vision_messages",
        "has_image_attachment",
    ]
    assert _INLINE_SENTINEL.encode() not in nats_bytes
    assert _INLINE_SENTINEL.encode() not in zmq_bytes
    assert len(nats_bytes) < 4_096
    assert len(zmq_bytes) < 4_096


@pytest.mark.asyncio
async def test_data_url_and_image_url_blocks_are_rejected() -> None:
    data_url = "data:image/png;base64," + _INLINE_SENTINEL
    message, _ = await _capture_forwarded_message({
        "text": "safe text",
        "vision_messages": _vision_messages(
            {
                "type": "image_url",
                "image_url": {"url": data_url},
            },
            {
                "type": "image",
                "source": {"type": "url", "url": data_url},
            },
        ),
        "has_image_attachment": True,
    })
    nats_bytes, zmq_bytes = _serialized_transport_forms(message)

    params = message.payload["params"]
    assert "vision_messages" not in params
    assert "has_image_attachment" not in params
    assert b"data:image" not in nats_bytes
    assert b"image_url" not in nats_bytes
    assert b"data:image" not in zmq_bytes
    assert b"image_url" not in zmq_bytes


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [b"raw", bytearray(b"raw"), memoryview(b"raw")])
async def test_python_bytes_bytearray_and_memoryview_blocks_are_rejected_without_json_error(
    raw: Any,
) -> None:
    message, _ = await _capture_forwarded_message({
        "text": "safe text",
        "vision_messages": _vision_messages(
            {"type": "image", "source": raw},
            {
                "type": "image",
                "source": {
                    "type": "attachment_ref",
                    "sha256": raw,
                    "media_type": "image/png",
                },
            },
        ),
        "has_image_attachment": True,
    })

    nats_bytes, zmq_bytes = _serialized_transport_forms(message)
    assert "vision_messages" not in message.payload["params"]
    assert b"raw" not in nats_bytes
    assert b"raw" not in zmq_bytes


@pytest.mark.asyncio
async def test_mixed_safe_ref_and_inline_blocks_retains_only_safe_ref() -> None:
    params = {
        "text": "mixed",
        "vision_messages": _vision_messages(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": _INLINE_SENTINEL,
                },
            },
            _ref_block(_PNG_SHA),
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,bad"},
            },
        ),
        "has_image_attachment": True,
    }
    message, _ = await _capture_forwarded_message(params)
    nats_bytes, zmq_bytes = _serialized_transport_forms(message)

    assert message.payload["params"]["vision_messages"] == [{
        "role": "user",
        "content": [_ref_block(_PNG_SHA)],
    }]
    assert _INLINE_SENTINEL.encode() not in nats_bytes
    assert _INLINE_SENTINEL.encode() not in zmq_bytes
    assert b"data:image" not in nats_bytes
    assert b"data:image" not in zmq_bytes
    assert len(nats_bytes) < 4_096
    assert len(zmq_bytes) < 4_096


@pytest.mark.asyncio
async def test_valid_ref_with_inline_extra_fields_is_rebuilt_exactly() -> None:
    message, _ = await _capture_forwarded_message({
        "vision_messages": _vision_messages({
            "type": "image",
            "metadata": {"untrusted": True},
            "image_url": {"url": "data:image/png;base64,bad"},
            "source": {
                "type": "attachment_ref",
                "sha256": _PNG_SHA,
                "media_type": "image/png",
                "data": _INLINE_SENTINEL,
                "url": "https://untrusted.invalid/blob",
                "custom": {"nested": "metadata"},
            },
        }),
    })

    block = message.payload["params"]["vision_messages"][0]["content"][0]
    assert block == _ref_block(_PNG_SHA)
    assert set(block) == {"type", "source"}
    assert set(block["source"]) == {"type", "sha256", "media_type"}
    serialized = json.dumps(message.payload)
    assert "untrusted.invalid" not in serialized
    assert "custom" not in serialized
    assert _INLINE_SENTINEL not in serialized


@pytest.mark.asyncio
async def test_empty_malformed_unknown_and_text_only_vision_shapes_degrade() -> None:
    malformed_values: list[Any] = [
        None,
        {},
        "vision",
        [],
        ["not-a-message"],
        [{"role": "user", "content": "not-a-list"}],
        [{"role": "user", "content": [{"type": "text", "text": "only"}]}],
        [
            {"role": "user", "content": [{"type": "text", "text": "first"}]},
            {"role": "user", "content": [_ref_block(_PNG_SHA)]},
        ],
        _vision_messages({"type": "unknown", "payload": "ignored"}),
    ]
    for value in malformed_values:
        message, _ = await _capture_forwarded_message({
            "text": "preserved",
            "vision_messages": value,
            "has_image_attachment": True,
        })
        params = message.payload["params"]
        assert params["text"] == "preserved"
        assert "vision_messages" not in params
        assert "has_image_attachment" not in params

    message, _ = await _capture_forwarded_message(["not", "a", "mapping"])
    assert message.payload["params"] == {"_transport_stripped": ["params"]}


@pytest.mark.asyncio
async def test_invalid_sha_and_mime_matrix_is_rejected() -> None:
    invalid_blocks = [
        _ref_block("a" * 63),
        _ref_block("a" * 65),
        _ref_block("A" * 64),
        _ref_block("g" * 64),
        _ref_block(123),
        _ref_block(_PNG_SHA, None),
        _ref_block(_PNG_SHA, b"image/png"),
        _ref_block(_PNG_SHA, "image/tiff"),
        {
            "type": "image",
            "source": {
                "type": "other",
                "sha256": _PNG_SHA,
                "media_type": "image/png",
            },
        },
    ]
    for block in invalid_blocks:
        message, _ = await _capture_forwarded_message({
            "vision_messages": _vision_messages(block),
            "has_image_attachment": True,
        })
        params = message.payload["params"]
        assert "vision_messages" not in params
        assert "has_image_attachment" not in params


@pytest.mark.asyncio
async def test_reference_count_and_scan_bounds_keep_first_eight() -> None:
    shas = [_sha(index) for index in range(10)]
    params = {
        "attachment_ref": shas[0],
        "attachment_refs": [shas[0], shas[0], *shas[1:]],
        "vision_messages": _vision_messages(
            *[_ref_block(sha) for sha in shas],
            _ref_block(shas[0]),
        ),
    }
    baseline = copy.deepcopy(params)
    message, intent = await _capture_forwarded_message(params)
    sent = message.payload["params"]

    assert _FEDERATED_ATTACHMENT_REF_LIMIT == 8
    assert sent["attachment_ref"] == shas[0]
    assert sent["attachment_refs"] == shas[:8]
    assert [
        block["source"]["sha256"]
        for block in sent["vision_messages"][0]["content"]
    ] == shas[:8]
    assert shas[8] not in json.dumps(sent)
    assert shas[9] not in json.dumps(sent)
    assert sent["_transport_stripped"] == [
        "attachment_ref",
        "attachment_refs",
        "vision_messages",
    ]
    assert intent.params == baseline

    assert _FEDERATED_ATTACHMENT_CANDIDATE_SCAN_LIMIT == 64
    assert _FEDERATED_VISION_SCAN_LIMIT == 64
    unscanned_sha = _sha(100)
    scan_message, _ = await _capture_forwarded_message({
        "vision_messages": [{
            "role": "user",
            "content": [
                *[{"type": "unknown"} for _ in range(64)],
                _ref_block(unscanned_sha),
            ],
        }],
    })
    assert "vision_messages" not in scan_message.payload["params"]
    assert unscanned_sha not in json.dumps(scan_message.payload)


@pytest.mark.asyncio
async def test_sanitizer_rejects_hostile_builtin_subclasses_without_invoking_overrides() -> None:
    hostile_sha = _HostileStr(_PNG_SHA)
    hostile_mime = _HostileStr("image/png")
    cases: list[tuple[Any, list[str]]] = [
        (_HostileDict({"attachment_ref": _PNG_SHA}), ["params"]),
        ({"attachment_refs": _HostileList([_PNG_SHA])}, ["attachment_refs"]),
        ({"attachment_refs": _HostileTuple((_PNG_SHA,))}, ["attachment_refs"]),
        ({"vision_messages": _HostileList([])}, ["vision_messages"]),
        ({"vision_messages": [_HostileDict({"content": []})]}, ["vision_messages"]),
        ({"vision_messages": [{"content": _HostileList([])}]}, ["vision_messages"]),
        ({
            "vision_messages": [{"content": [_HostileDict({"type": "image"})]}]
        }, ["vision_messages"]),
        ({
            "vision_messages": [{
                "content": [{"type": "image", "source": _HostileDict({})}]
            }]
        }, ["vision_messages"]),
        ({"attachment_ref": hostile_sha}, ["attachment_ref"]),
        ({
            "vision_messages": [{
                "content": [{
                    "type": _HostileStr("image"),
                    "source": {
                        "type": "attachment_ref",
                        "sha256": _PNG_SHA,
                        "media_type": "image/png",
                    },
                }]
            }]
        }, ["vision_messages"]),
        ({
            "vision_messages": [{
                "content": [{
                    "type": "image",
                    "source": {
                        "type": _HostileStr("attachment_ref"),
                        "sha256": _PNG_SHA,
                        "media_type": "image/png",
                    },
                }]
            }]
        }, ["vision_messages"]),
        ({
            "vision_messages": [{
                "content": [{
                    "type": "image",
                    "source": {
                        "type": "attachment_ref",
                        "sha256": hostile_sha,
                        "media_type": "image/png",
                    },
                }]
            }]
        }, ["vision_messages"]),
        ({
            "vision_messages": [{
                "content": [{
                    "type": "image",
                    "source": {
                        "type": "attachment_ref",
                        "sha256": _PNG_SHA,
                        "media_type": hostile_mime,
                    },
                }]
            }]
        }, ["vision_messages"]),
    ]

    for params, expected_marker in cases:
        message, _ = await _capture_forwarded_message(params)
        nats_bytes, zmq_bytes = _serialized_transport_forms(message)
        assert message.payload["params"] == {
            "_transport_stripped": expected_marker
        }
        assert json.loads(nats_bytes)
        assert json.loads(zmq_bytes)


@pytest.mark.asyncio
async def test_top_level_recognized_looking_hostile_str_key_fails_closed_without_override() -> None:
    calls: list[str] = []
    hostile_key = _ArmedHostileStr("attachment_ref", calls)
    params: dict[Any, Any] = {"safe_before": "discarded"}
    params[hostile_key] = _PNG_SHA
    params["safe_after"] = {"also": "discarded"}
    hostile_key.arm()

    message, _ = await _capture_forwarded_message(params)

    sent = message.payload["params"]
    assert len(sent) == 1
    assert dict.get(sent, "_transport_stripped") == ["params"]
    nats_bytes, zmq_bytes = _serialized_transport_forms(message)
    assert json.loads(nats_bytes)
    assert json.loads(zmq_bytes)
    assert calls == []


@pytest.mark.asyncio
async def test_top_level_unrelated_hostile_keys_fail_closed_without_override() -> None:
    string_calls: list[str] = []
    object_calls: list[str] = []
    cases = (
        (_ArmedHostileStr("note", string_calls), string_calls),
        (_ArmedHostileKey(object_calls), object_calls),
    )
    for hostile_key, calls in cases:
        params: dict[Any, Any] = {"safe_before": "discarded"}
        params[hostile_key] = "unsafe-key-value"
        params["safe_after"] = {"also": "discarded"}
        hostile_key.arm()

        message, _ = await _capture_forwarded_message(params)

        sent = message.payload["params"]
        assert len(sent) == 1
        assert dict.get(sent, "_transport_stripped") == ["params"]
        nats_bytes, zmq_bytes = _serialized_transport_forms(message)
        assert json.loads(nats_bytes)
        assert json.loads(zmq_bytes)
        assert calls == []


@pytest.mark.asyncio
async def test_top_level_exact_string_keys_preserve_generic_params_and_attachment_marker_order() -> None:
    nested_generic = {"nested": [1, 2, {"three": True}]}
    params = {
        "safe_before": nested_generic,
        "has_image_attachment": "spoofed",
        "vision_messages": _vision_messages(_ref_block(_PNG_SHA)),
        "attachment_refs": [_PNG_SHA, "invalid", _sha(1)],
        "attachment_ref": _PNG_SHA,
        "safe_after": "preserved",
    }
    baseline = copy.deepcopy(params)

    message, intent = await _capture_forwarded_message(params)

    sent = message.payload["params"]
    assert sent["safe_before"] is nested_generic
    assert sent["safe_after"] == "preserved"
    assert sent["attachment_ref"] == _PNG_SHA
    assert sent["attachment_refs"] == [_PNG_SHA, _sha(1)]
    assert sent["vision_messages"] == [{
        "role": "user",
        "content": [_ref_block(_PNG_SHA)],
    }]
    assert "has_image_attachment" not in sent
    assert sent["_transport_stripped"] == [
        "attachment_ref",
        "attachment_refs",
        "vision_messages",
        "has_image_attachment",
    ]
    assert intent.params == baseline


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("level", "key_kind", "recognized_field"),
    [
        ("message", "recognized_string_subclass", "content"),
        ("message", "unrelated_string_subclass", None),
        ("message", "non_string", None),
        ("block", "recognized_string_subclass", "type"),
        ("block", "recognized_string_subclass", "source"),
        ("block", "unrelated_string_subclass", None),
        ("block", "non_string", None),
        ("source", "recognized_string_subclass", "type"),
        ("source", "recognized_string_subclass", "sha256"),
        ("source", "recognized_string_subclass", "media_type"),
        ("source", "unrelated_string_subclass", None),
        ("source", "non_string", None),
    ],
)
async def test_nested_hostile_keys_degrade_at_exact_level_without_override(
    level: str,
    key_kind: str,
    recognized_field: str | None,
) -> None:
    calls: list[str] = []
    if key_kind == "recognized_string_subclass":
        assert recognized_field is not None
        hostile_key: Any = _ArmedHostileStr(recognized_field, calls)
    elif key_kind == "unrelated_string_subclass":
        hostile_key = _ArmedHostileStr("note", calls)
    else:
        hostile_key = _ArmedHostileKey(calls)

    safe_before = _ref_block(_sha(401))
    safe_after = _ref_block(_sha(402))
    unsafe_source: dict[Any, Any]
    unsafe_block: dict[Any, Any]
    first_message: dict[Any, Any]

    if level == "message":
        first_message = {}
        if key_kind == "recognized_string_subclass":
            first_message[hostile_key] = [safe_before, safe_after]
        else:
            first_message["content"] = [safe_before, safe_after]
            first_message[hostile_key] = "unsafe-message-key"
        first_message["role"] = "user"
    elif level == "block":
        unsafe_block = {}
        if key_kind == "recognized_string_subclass":
            if recognized_field == "type":
                unsafe_block[hostile_key] = "image"
                unsafe_block["source"] = _ref_block(_sha(403))["source"]
            else:
                unsafe_block["type"] = "image"
                unsafe_block[hostile_key] = _ref_block(_sha(403))["source"]
        else:
            unsafe_block["type"] = "image"
            unsafe_block["source"] = _ref_block(_sha(403))["source"]
            unsafe_block[hostile_key] = "unsafe-block-key"
        first_message = {
            "role": "user",
            "content": [safe_before, unsafe_block, safe_after],
        }
    else:
        unsafe_source = {}
        if key_kind == "recognized_string_subclass":
            safe_source_values = {
                "type": "attachment_ref",
                "sha256": _sha(403),
                "media_type": "image/png",
            }
            for source_key, source_value in safe_source_values.items():
                if source_key == recognized_field:
                    unsafe_source[hostile_key] = source_value
                else:
                    unsafe_source[source_key] = source_value
        else:
            unsafe_source["type"] = "attachment_ref"
            unsafe_source["sha256"] = _sha(403)
            unsafe_source["media_type"] = "image/png"
            unsafe_source[hostile_key] = "unsafe-source-key"
        unsafe_block = {"type": "image", "source": unsafe_source}
        first_message = {
            "role": "user",
            "content": [safe_before, unsafe_block, safe_after],
        }

    generic_before = {"nested": ["preserved"]}
    generic_after = ["also", "preserved"]
    params: dict[str, Any] = {
        "safe_before": generic_before,
        "attachment_ref": _sha(399),
        "attachment_refs": [_sha(400)],
        "vision_messages": [first_message],
        "has_image_attachment": True,
        "safe_after": generic_after,
    }
    original_signature = _exact_container_graph_signature(params)
    hostile_key.arm()

    message, intent = await _capture_forwarded_message(params)
    sent = message.payload["params"]
    nats_bytes, zmq_bytes = _serialized_transport_forms(message)

    assert sent["safe_before"] is generic_before
    assert sent["safe_after"] is generic_after
    assert sent["attachment_ref"] == _sha(399)
    assert sent["attachment_refs"] == [_sha(400)]
    if level == "message":
        assert "vision_messages" not in sent
        assert "has_image_attachment" not in sent
        assert sent["_transport_stripped"] == [
            "attachment_ref",
            "attachment_refs",
            "vision_messages",
            "has_image_attachment",
        ]
    else:
        assert sent["vision_messages"] == [{
            "role": "user",
            "content": [safe_before, safe_after],
        }]
        assert sent["has_image_attachment"] is True
        assert sent["_transport_stripped"] == [
            "attachment_ref",
            "attachment_refs",
            "vision_messages",
        ]
        for safe_block in sent["vision_messages"][0]["content"]:
            assert set(safe_block) == {"type", "source"}
            assert set(safe_block["source"]) == {
                "type",
                "sha256",
                "media_type",
            }
    assert json.loads(nats_bytes)
    assert json.loads(zmq_bytes)
    assert calls == []
    assert intent.params is params
    assert _exact_container_graph_signature(params) == original_signature


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["message", "block", "source"])
async def test_nested_unknown_exact_string_values_are_never_touched(
    level: str,
) -> None:
    calls: list[str] = []
    hostile_value = _HostileNestedValue(calls)
    safe_before = _ref_block(_sha(411))
    safe_candidate = _ref_block(_sha(412))
    safe_after = _ref_block(_sha(413))

    if level == "message":
        first_message: dict[str, Any] = {
            "content": [safe_candidate],
            "unknown_message_field": hostile_value,
        }
    elif level == "block":
        candidate = {
            **safe_candidate,
            "unknown_block_field": hostile_value,
        }
        first_message = {
            "content": [safe_before, candidate, safe_after],
        }
    else:
        candidate = {
            "type": "image",
            "source": {
                **safe_candidate["source"],
                "unknown_source_field": hostile_value,
            },
        }
        first_message = {
            "content": [safe_before, candidate, safe_after],
        }

    params = {
        "vision_messages": [first_message],
        "has_image_attachment": True,
    }
    original_signature = _exact_container_graph_signature(params)

    message, intent = await _capture_forwarded_message(params)
    sent = message.payload["params"]
    nats_bytes, zmq_bytes = _serialized_transport_forms(message)

    expected_blocks = (
        [safe_candidate]
        if level == "message"
        else [safe_before, safe_candidate, safe_after]
    )
    assert sent["vision_messages"] == [{
        "role": "user",
        "content": expected_blocks,
    }]
    assert sent["has_image_attachment"] is True
    assert sent["_transport_stripped"] == ["vision_messages"]
    for safe_block in sent["vision_messages"][0]["content"]:
        assert set(safe_block) == {"type", "source"}
        assert set(safe_block["source"]) == {
            "type",
            "sha256",
            "media_type",
        }
    assert json.loads(nats_bytes)
    assert json.loads(zmq_bytes)
    assert calls == []
    assert intent.params is params
    assert _exact_container_graph_signature(params) == original_signature


@pytest.mark.asyncio
async def test_sanitizer_is_total_for_arbitrary_recognized_values() -> None:
    value_factories: list[Callable[[], Any]] = [
        object,
        lambda: (value for value in ("generator",)),
        _ArbitraryMapping,
        _ArbitraryIterable,
        lambda: None,
        lambda: True,
        lambda: 7,
        lambda: b"bytes",
        lambda: bytearray(b"bytearray"),
        lambda: memoryview(b"memoryview"),
        _HostileAttributeObject,
    ]
    recognized_keys = (
        "attachment_ref",
        "attachment_refs",
        "vision_messages",
        "has_image_attachment",
    )

    for key in recognized_keys:
        for value_factory in value_factories:
            value = value_factory()
            message, intent = await _capture_forwarded_message({key: value})
            assert message.payload["params"] == {
                "_transport_stripped": [key]
            }
            nats_bytes, zmq_bytes = _serialized_transport_forms(message)
            assert json.loads(nats_bytes)
            assert json.loads(zmq_bytes)
            assert intent.params[key] is value


@pytest.mark.asyncio
async def test_plural_scan_cap_counts_invalid_and_duplicate_candidates() -> None:
    duplicate_sha = _sha(200)
    unscanned_sha = _sha(201)
    first_64 = [
        duplicate_sha if index % 2 == 0 else "invalid"
        for index in range(64)
    ]

    message, _ = await _capture_forwarded_message({
        "attachment_refs": [*first_64, unscanned_sha],
    })

    assert _FEDERATED_ATTACHMENT_CANDIDATE_SCAN_LIMIT == 64
    assert message.payload["params"]["attachment_refs"] == [duplicate_sha]
    assert unscanned_sha not in json.dumps(message.payload)


@pytest.mark.asyncio
async def test_plural_scan_never_reads_candidate_65() -> None:
    untouched = _HostileStr(_sha(300))
    message, _ = await _capture_forwarded_message({
        "attachment_refs": [*["invalid"] * 64, untouched],
    })

    assert "attachment_refs" not in message.payload["params"]
    assert message.payload["params"]["_transport_stripped"] == [
        "attachment_refs"
    ]


@pytest.mark.asyncio
async def test_bare_and_plural_reference_surfaces_validate_and_bound() -> None:
    shas = [_sha(index) for index in range(12)]
    params = {
        "attachment_ref": shas[0],
        "attachment_refs": [
            shas[0],
            shas[0],
            "bad",
            b"raw",
            *shas[1:],
        ],
        "unrelated": {"keep": [1, 2, 3]},
    }
    baseline = copy.deepcopy(params)
    message, intent = await _capture_forwarded_message(params)

    sent = message.payload["params"]
    assert sent["attachment_ref"] == shas[0]
    assert sent["attachment_refs"] == shas[:8]
    assert sent["unrelated"] == params["unrelated"]
    assert sent["_transport_stripped"] == [
        "attachment_ref",
        "attachment_refs",
    ]
    assert intent.params == baseline


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {
            "text": "safe",
            "vision_messages": _vision_messages(_ref_block(_PNG_SHA)),
            "has_image_attachment": True,
        },
        {
            "text": "mixed",
            "vision_messages": _vision_messages(
                _ref_block(_PNG_SHA),
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "data": _INLINE_SENTINEL,
                        "media_type": "image/png",
                    },
                },
            ),
            "has_image_attachment": True,
        },
        {
            "text": "inline",
            "vision_messages": _vision_messages({
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,bad"},
            }),
            "has_image_attachment": True,
        },
    ],
)
async def test_original_intent_params_deeply_unchanged_for_safe_mixed_and_inline_inputs(
    params: dict[str, Any],
) -> None:
    baseline = copy.deepcopy(params)
    _, intent = await _capture_forwarded_message(params)
    assert intent.params == baseline


@pytest.mark.asyncio
async def test_unrelated_params_are_preserved_exactly_and_transport_marker_is_authoritative() -> None:
    unrelated = {
        "text": "keep",
        "tool": {"arguments": ["A" * 8_192, {"nested": True}]},
        "signature": "not-an-attachment",
    }
    with_attachment = {
        **copy.deepcopy(unrelated),
        "attachment_ref": _PNG_SHA,
        "_transport_stripped": ["spoofed", "vision_messages"],
    }
    message, _ = await _capture_forwarded_message(with_attachment)
    sent = message.payload["params"]
    for key, value in unrelated.items():
        assert sent[key] == value
    assert sent["_transport_stripped"] == ["attachment_ref"]

    no_attachment = {
        **copy.deepcopy(unrelated),
        "_transport_stripped": ["caller-owned-on-no-attachment-path"],
    }
    no_attachment_message, _ = await _capture_forwarded_message(no_attachment)
    assert no_attachment_message.payload["params"] == no_attachment


@pytest.mark.asyncio
async def test_has_image_attachment_is_derived_from_safe_vision_refs_on_sanitation() -> None:
    safe_true, _ = await _capture_forwarded_message({
        "vision_messages": _vision_messages(_ref_block(_PNG_SHA)),
        "has_image_attachment": True,
    })
    assert safe_true.payload["params"]["has_image_attachment"] is True
    assert safe_true.payload["params"]["_transport_stripped"] == [
        "vision_messages"
    ]

    for value in (False, 1, "true", None):
        message, _ = await _capture_forwarded_message({
            "vision_messages": _vision_messages(_ref_block(_PNG_SHA)),
            "has_image_attachment": value,
        })
        params = message.payload["params"]
        assert "has_image_attachment" not in params
        assert params["_transport_stripped"] == [
            "vision_messages",
            "has_image_attachment",
        ]

    alone, _ = await _capture_forwarded_message({"has_image_attachment": True})
    assert alone.payload["params"] == {
        "_transport_stripped": ["has_image_attachment"]
    }


@pytest.mark.asyncio
async def test_nats_and_zeromq_serializers_are_reference_only_and_bounded() -> None:
    shas = [_sha(index) for index in range(8)]
    vision_message, _ = await _capture_forwarded_message({
        "text": "short",
        "vision_messages": _vision_messages(
            *[_ref_block(sha) for sha in shas]
        ),
        "has_image_attachment": True,
    })
    vision_params = vision_message.payload["params"]
    vision_envelope_bytes = len(
        json.dumps(vision_params["vision_messages"]).encode("utf-8")
    )
    vision_nats, vision_zmq = _serialized_transport_forms(vision_message)
    assert vision_envelope_bytes < 2_048
    assert len(vision_nats) < 4_096
    assert len(vision_zmq) < 4_096

    combined_message, _ = await _capture_forwarded_message({
        "text": "short",
        "attachment_ref": shas[0],
        "attachment_refs": shas,
        "vision_messages": _vision_messages(
            *[_ref_block(sha) for sha in shas]
        ),
        "has_image_attachment": True,
    })
    combined = combined_message.payload["params"]
    assert len(combined["attachment_refs"]) == 8
    assert len(combined["vision_messages"][0]["content"]) == 8
    combined_nats, combined_zmq = _serialized_transport_forms(combined_message)
    assert len(combined_nats) < 4_096
    assert len(combined_zmq) < 4_096

    mixed_message, _ = await _capture_forwarded_message({
        "text": "short",
        "vision_messages": _vision_messages(
            _ref_block(shas[0]),
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": _INLINE_SENTINEL,
                },
            },
        ),
    })
    mixed_nats, mixed_zmq = _serialized_transport_forms(mixed_message)
    assert _INLINE_SENTINEL.encode() not in mixed_nats
    assert _INLINE_SENTINEL.encode() not in mixed_zmq
    assert len(mixed_nats) < 4_096
    assert len(mixed_zmq) < 4_096


def test_receiver_extracts_singular_plural_and_vision_refs_first_seen_dedup() -> None:
    sha_1, sha_2, sha_3, sha_4 = (_sha(index) for index in range(4))
    params = {
        "attachment_ref": sha_1,
        "attachment_refs": [sha_1, sha_2, "bad", 123, sha_3, sha_2],
        "vision_messages": _vision_messages(
            _ref_block(sha_3),
            _ref_block(sha_4),
            _ref_block(sha_1),
        ),
    }
    assert extract_attachment_shas(params) == [sha_1, sha_2, sha_3, sha_4]


@pytest.mark.asyncio
async def test_receiver_plural_refs_fetch_all_missing_accepted_shas(
    tmp_path,
) -> None:
    blobs = [
        b"\x89PNG\r\n\x1a\nplural-one",
        b"\x89PNG\r\n\x1a\nplural-two",
    ]
    shas = [hashlib.sha256(blob).hexdigest() for blob in blobs]
    store = FilesystemAttachmentStore(tmp_path / "receiver-plural")
    config = _fleet_config(
        node_id="node-b",
        peer_node_id="node-a",
        serve_remote_enabled=False,
        auto_resolve_remote_enabled=True,
        a2a_peers=[
            A2APeerConfig(
                node_id="node-a",
                peer_url="http://origin.test",
                auth_token=_TOKEN,
            )
        ],
    )
    runtime = SimpleNamespace(config=config, attachment_store=store)
    calls: list[str] = []

    def _respond(request: httpx.Request) -> httpx.Response:
        requested_sha = request.url.path.rsplit("/", 1)[-1]
        calls.append(requested_sha)
        blob = blobs[shas.index(requested_sha)]
        return httpx.Response(
            200,
            content=blob,
            headers={"content-type": "image/png"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_respond)
    ) as client:
        count = await resolve_missing_attachments(
            runtime,
            {"attachment_ref": shas[0], "attachment_refs": [*shas, shas[0]]},
            "node-a",
            http=client,
        )

    assert count == 2
    assert calls == shas
    assert [await store.read(sha) for sha in shas] == blobs


@pytest.mark.asyncio
async def test_non_attachment_intent_transport_payload_is_value_equal_to_head() -> None:
    params = {
        "text": "plain",
        "nested": {"values": [1, 2, {"three": True}]},
        "_transport_stripped": ["pre-existing-marker"],
    }
    message, _ = await _capture_forwarded_message(params)
    assert message.payload["params"] == params


class _FailingWriteStore(FilesystemAttachmentStore):
    async def write(
        self,
        content_hash: str,
        blob: bytes,
        mime: str,
        *,
        origin: str = "chat_attachment",
    ) -> Any:
        raise RuntimeError("injected receiver-store write failure")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_case",
    [
        "404",
        "500",
        "missing_content_type",
        "oversize",
        "tampered",
        "store_write",
    ],
)
async def test_cross_host_prefetch_failure_matrix_still_broadcasts_reference(
    tmp_path,
    failure_case: str,
) -> None:
    if failure_case == "oversize":
        response_blob = b"x" * (10 * 1024 * 1024 + 1)
        requested_sha = hashlib.sha256(response_blob).hexdigest()
    else:
        response_blob = _PNG_BYTES
        requested_sha = _PNG_SHA

    if failure_case == "store_write":
        store: FilesystemAttachmentStore = _FailingWriteStore(
            tmp_path / f"receiver-{failure_case}"
        )
    else:
        store = FilesystemAttachmentStore(tmp_path / f"receiver-{failure_case}")

    def _respond(_request: httpx.Request) -> httpx.Response:
        if failure_case == "404":
            return httpx.Response(404)
        if failure_case == "500":
            return httpx.Response(500)
        if failure_case == "missing_content_type":
            return httpx.Response(200, content=response_blob)
        if failure_case == "tampered":
            return httpx.Response(
                200,
                content=b"tampered",
                headers={"content-type": "image/png"},
            )
        return httpx.Response(
            200,
            content=response_blob,
            headers={"content-type": "image/png"},
        )

    receiver_config = _fleet_config(
        node_id="node-b",
        peer_node_id="node-a",
        serve_remote_enabled=False,
        auto_resolve_remote_enabled=True,
        a2a_peers=[
            A2APeerConfig(
                node_id="node-a",
                peer_url="http://origin.test",
                auth_token=_TOKEN,
            )
        ],
    )
    runtime = SimpleNamespace(
        config=receiver_config,
        attachment_store=store,
    )
    inbound: list[dict[str, Any]] = []
    intent_bus = IntentBus(SignalManager())

    async def _record(intent: IntentMessage) -> IntentResult:
        inbound.append(copy.deepcopy(intent.params))
        return IntentResult(
            intent_id=intent.id,
            agent_id="receiver",
            success=True,
        )

    intent_bus.subscribe("receiver", _record, intent_names=["direct_message"])
    client = httpx.AsyncClient(transport=httpx.MockTransport(_respond))

    async def _resolver(params: dict[str, Any], source_node: str) -> int:
        return await resolve_missing_attachments(
            runtime,
            params,
            source_node,
            http=client,
        )

    transport = _CapturingTransport()
    bridge = FederationBridge(
        node_id="node-b",
        transport=transport,
        router=FederationRouter(),
        intent_bus=intent_bus,
        config=receiver_config.federation,
        self_model_fn=lambda: NodeSelfModel(node_id="node-b"),
        attachment_resolver=_resolver,
    )
    outbound, _ = await _capture_forwarded_message({
        "text": "Describe it.",
        "vision_messages": _vision_messages(_ref_block(requested_sha)),
        "has_image_attachment": True,
    })
    inbound_message = FederationMessage(
        type="intent_request",
        source_node="node-a",
        message_id=f"failure-{failure_case}",
        payload=outbound.payload,
        timestamp=1.0,
    )
    try:
        await bridge.handle_inbound(inbound_message)
    finally:
        await client.aclose()

    assert len(inbound) == 1
    assert inbound[0]["vision_messages"] == [{
        "role": "user",
        "content": [_ref_block(requested_sha)],
    }]
    assert not await store.exists(requested_sha)
    assert "base64" not in json.dumps(inbound[0])
    assert len(transport.sent) == 1
    assert transport.sent[0].type == "intent_response"
