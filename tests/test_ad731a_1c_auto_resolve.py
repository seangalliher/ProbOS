"""AD-731a-1c: receive-side auto-resolution of cross-host attachment refs (#638).

BF-287: real ``FilesystemAttachmentStore`` on ``tmp_path`` + real
``AttachmentsConfig`` / ``FederationConfig`` / ``A2APeerConfig`` — NO MagicMock
at the substrate boundary. The fetch seam uses httpx ``MockTransport`` so no
real network is touched, and the request counter proves the off path is
byte-identical (zero requests).
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import inspect
import textwrap
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

import httpx
import pytest

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.config import (
    A2APeerConfig,
    AttachmentsConfig,
    FederationA2AConfig,
    FederationConfig,
    MedicalConfig,
    ScalingConfig,
    SelfModConfig,
    SystemConfig,
    UtilityAgentsConfig,
)
from probos.federation.attachment_resolve import (
    extract_attachment_shas,
    resolve_missing_attachments,
    resolve_sender_peer,
)
from probos.federation.bridge import FederationBridge
from probos.federation.mock_transport import (
    MockFederationTransport,
    MockTransportBus,
)
from probos.federation.router import FederationRouter
from probos.mesh.intent import IntentBus
from probos.mesh.nats_bus import MockNATSBus
from probos.mesh.signal import SignalManager
from probos.runtime import ProbOSRuntime
from probos.startup import fleet_organization as fleet_organization_module
from probos.startup.fleet_organization import organize_fleet
from probos.substrate.pool_group import PoolGroupRegistry
from probos.types import FederationMessage, IntentMessage, IntentResult


_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-png-body-for-ad731a-1c"
_PNG_SHA = hashlib.sha256(_PNG_BYTES).hexdigest()
_PNG_MIME = "image/png"
_OTHER_SHA = hashlib.sha256(b"a-different-attachment").hexdigest()


# ---------------------------------------------------------------------------
# Helpers — real store + real config + httpx MockTransport (BF-287)
# ---------------------------------------------------------------------------

def _make_runtime(
    tmp_path,
    *,
    auto_resolve_remote_enabled: bool,
    peers: list[A2APeerConfig],
) -> tuple[Any, FilesystemAttachmentStore]:
    """Real-ish runtime stub: real Pydantic config + real filesystem store."""
    store = FilesystemAttachmentStore(tmp_path / "attachments")
    config = SimpleNamespace(
        attachments=AttachmentsConfig(
            auto_resolve_remote_enabled=auto_resolve_remote_enabled
        ),
        federation=FederationConfig(
            a2a=FederationA2AConfig(outbound_peers=peers)
        ),
    )
    runtime = SimpleNamespace(config=config, attachment_store=store)
    return runtime, store


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _serving_handler(calls: dict) -> Any:
    """200 + matching bytes + good mime; records each request."""
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        calls["auth"] = request.headers.get("authorization", "")
        calls["url"] = str(request.url)
        return httpx.Response(
            200, content=_PNG_BYTES, headers={"content-type": _PNG_MIME}
        )
    return handler


def _peer(node_id: str = "peer-A") -> A2APeerConfig:
    return A2APeerConfig(peer_url="http://peer", auth_token="tok", node_id=node_id)


class _RecordingAttachmentResolverOwner:
    def __init__(self, store: FilesystemAttachmentStore) -> None:
        self._store = store
        self.calls: list[tuple[dict[str, Any], str]] = []

    async def resolve(
        self,
        params: dict[str, Any],
        source_node: str,
    ) -> int:
        self.calls.append((params, source_node))
        await self._store.write(_PNG_SHA, _PNG_BYTES, _PNG_MIME)
        return 1


class _ExplodingAttachmentStore:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def exists(self, content_hash: str) -> bool:
        self.calls.append("exists")
        raise AssertionError("flag-off resolver touched the attachment store")

    async def write(
        self,
        content_hash: str,
        blob: bytes,
        mime: str,
        *,
        origin: str = "chat_attachment",
    ) -> None:
        self.calls.append("write")
        raise AssertionError("flag-off resolver wrote to the attachment store")


def _production_config(
    *,
    federation_enabled: bool = True,
    auto_resolve_remote_enabled: bool = True,
    peers: list[A2APeerConfig] | None = None,
) -> SystemConfig:
    return SystemConfig(
        attachments=AttachmentsConfig(
            auto_resolve_remote_enabled=auto_resolve_remote_enabled
        ),
        federation=FederationConfig(
            enabled=federation_enabled,
            node_id="node-local",
            peers=[],
            validate_remote_results=False,
            gossip_interval_seconds=100.0,
            a2a=FederationA2AConfig(outbound_peers=peers or []),
        ),
        scaling=ScalingConfig(enabled=False),
        utility_agents=UtilityAgentsConfig(enabled=False),
        medical=MedicalConfig(enabled=False),
        self_mod=SelfModConfig(enabled=False),
    )


async def _organize_with_nats(
    *,
    config: SystemConfig,
    intent_bus: IntentBus,
    attachment_resolver_fn: (
        Callable[[dict[str, Any], str], Awaitable[int]] | None
    ),
) -> tuple[Any, MockNATSBus]:
    nats_bus = MockNATSBus()
    await nats_bus.start()
    result = await organize_fleet(
        config=config,
        pools={},
        pool_groups=PoolGroupRegistry(),
        escalation_manager=SimpleNamespace(),
        intent_bus=intent_bus,
        trust_network=SimpleNamespace(),
        llm_client=SimpleNamespace(),
        build_pool_intent_map_fn=lambda: {},
        find_consensus_pools_fn=lambda: set(),
        build_self_model_fn=lambda: SimpleNamespace(),
        validate_remote_result_fn=None,
        attachment_resolver_fn=attachment_resolver_fn,
        nats_bus=nats_bus,
    )
    return result, nats_bus


async def _stop_organized(result: Any, nats_bus: MockNATSBus) -> None:
    if result.federation_bridge is not None:
        await result.federation_bridge.stop()
    if result.federation_transport is not None:
        await result.federation_transport.stop()
    await nats_bus.stop()


def _make_direct_bridge(
    *,
    attachment_resolver: (
        Callable[[dict[str, Any], str], Awaitable[int]] | None
    ) = None,
) -> tuple[FederationBridge, MockFederationTransport, IntentBus]:
    intent_bus = IntentBus(SignalManager())
    transport = MockFederationTransport("node-local", MockTransportBus())
    bridge = FederationBridge(
        node_id="node-local",
        transport=transport,
        router=FederationRouter(),
        intent_bus=intent_bus,
        config=FederationConfig(
            enabled=True,
            node_id="node-local",
            gossip_interval_seconds=100.0,
        ),
        self_model_fn=lambda: SimpleNamespace(),
        attachment_resolver=attachment_resolver,
    )
    return bridge, transport, intent_bus


async def _noop_attachment_resolver(
    params: dict[str, Any],
    source_node: str,
) -> int:
    return 0


# ---------------------------------------------------------------------------
# BF-672: real Phase-3 production construction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_production_organize_fleet_wires_attachment_resolver_before_broadcast(
    tmp_path,
):
    store = FilesystemAttachmentStore(tmp_path / "production-attachments")
    resolver_owner = _RecordingAttachmentResolverOwner(store)
    config = _production_config(peers=[_peer()])
    intent_bus = IntentBus(SignalManager())
    store_state_at_broadcast: list[bool] = []

    async def _record_store_state(intent: IntentMessage) -> IntentResult:
        store_state_at_broadcast.append(await store.exists(_PNG_SHA))
        return IntentResult(
            intent_id=intent.id,
            agent_id="local-consumer",
            success=True,
        )

    intent_bus.subscribe(
        "local-consumer",
        _record_store_state,
        intent_names=["inspect_attachment"],
    )
    result, nats_bus = await _organize_with_nats(
        config=config,
        intent_bus=intent_bus,
        attachment_resolver_fn=resolver_owner.resolve,
    )
    try:
        assert result.federation_bridge is not None
        assert result.federation_transport is not None
        await nats_bus.publish_raw(
            "federation.intent.node-local",
            {
                "type": "intent_request",
                "source_node": "peer-A",
                "message_id": "bf672-production-wire",
                "payload": {
                    "intent": "inspect_attachment",
                    "params": {"attachment_ref": _PNG_SHA},
                },
                "timestamp": 1.0,
            },
        )

        assert store_state_at_broadcast == [True], (
            "production organize_fleet did not inject attachment resolution "
            "before local broadcast"
        )
        assert resolver_owner.calls == [({"attachment_ref": _PNG_SHA}, "peer-A")]
        responses = [
            data
            for subject, data in nats_bus.published
            if subject == "federation.intent.peer-A"
            and data["type"] == "intent_response"
        ]
        assert len(responses) == 1
        assert intent_bus._federation_fn == result.federation_bridge.forward_intent
    finally:
        await _stop_organized(result, nats_bus)


@pytest.mark.asyncio
async def test_runtime_adapter_delegates_to_existing_resolver(monkeypatch):
    calls: list[tuple[Any, dict[str, Any], str]] = []

    async def _record(
        runtime: Any,
        params: dict[str, Any],
        source_node: str,
    ) -> int:
        calls.append((runtime, params, source_node))
        return 3

    monkeypatch.setattr(
        "probos.federation.attachment_resolve.resolve_missing_attachments",
        _record,
    )
    runtime = object.__new__(ProbOSRuntime)
    params = {"attachment_ref": _PNG_SHA}

    count = await runtime._resolve_federated_attachments(params, "peer-A")

    assert count == 3
    assert calls == [(runtime, params, "peer-A")]


def test_production_source_contract_uses_narrow_constructor_callback():
    runtime_tree = ast.parse(textwrap.dedent(inspect.getsource(ProbOSRuntime.start)))
    organize_calls = [
        node
        for node in ast.walk(runtime_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "organize_fleet"
    ]
    assert len(organize_calls) == 1
    keywords = {keyword.arg: keyword.value for keyword in organize_calls[0].keywords}
    callback = keywords["attachment_resolver_fn"]
    assert isinstance(callback, ast.Attribute)
    assert isinstance(callback.value, ast.Name)
    assert callback.value.id == "self"
    assert callback.attr == "_resolve_federated_attachments"

    fleet_tree = ast.parse(inspect.getsource(organize_fleet))
    bridge_calls = [
        node
        for node in ast.walk(fleet_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "FederationBridge"
    ]
    assert len(bridge_calls) == 1
    start_awaits = [
        node
        for node in ast.walk(fleet_tree)
        if isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and isinstance(node.value.func.value, ast.Name)
        and node.value.func.value.id == "bridge"
        and node.value.func.attr == "start"
    ]
    assert len(start_awaits) == 1
    bridge_callback = {
        keyword.arg: keyword.value for keyword in bridge_calls[0].keywords
    }["attachment_resolver"]
    assert isinstance(bridge_callback, ast.Name)
    assert bridge_callback.id == "attachment_resolver_fn"
    assert bridge_calls[0].lineno < start_awaits[0].lineno
    bridge_source = inspect.getsource(FederationBridge)
    bridge_tree = ast.parse(textwrap.dedent(bridge_source))
    bridge_attribute_names = {
        node.attr for node in ast.walk(bridge_tree) if isinstance(node, ast.Attribute)
    }
    bridge_function_names = {
        node.name
        for node in ast.walk(bridge_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_" + "runtime_ref" not in bridge_attribute_names
    assert "set_" + "runtime_ref" not in bridge_function_names

    production_constructors: list[tuple[str, int]] = []
    for source_path in (ProbOSRuntime, fleet_organization_module):
        source = inspect.getsource(source_path)
        tree = ast.parse(textwrap.dedent(source))
        production_constructors.extend(
            (getattr(source_path, "__name__", type(source_path).__name__), node.lineno)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (
                isinstance(node.func, ast.Name)
                and node.func.id == "FederationBridge"
            )
        )
    assert len(production_constructors) == 1


@pytest.mark.asyncio
async def test_federation_disabled_creates_no_bridge_or_callback():
    callback_calls: list[tuple[dict[str, Any], str]] = []

    async def _record(params: dict[str, Any], source_node: str) -> int:
        callback_calls.append((params, source_node))
        return 0

    result, nats_bus = await _organize_with_nats(
        config=_production_config(federation_enabled=False),
        intent_bus=IntentBus(SignalManager()),
        attachment_resolver_fn=_record,
    )
    try:
        assert result.federation_bridge is None
        assert result.federation_transport is None
        assert callback_calls == []
    finally:
        await _stop_organized(result, nats_bus)


@pytest.mark.asyncio
async def test_production_wiring_missing_params_normalize_and_broadcast():
    broadcasts: list[dict[str, Any]] = []
    intent_bus = IntentBus(SignalManager())

    async def _record(intent: IntentMessage) -> IntentResult:
        broadcasts.append(intent.params)
        return IntentResult(intent_id=intent.id, agent_id="consumer", success=True)

    intent_bus.subscribe("consumer", _record, intent_names=["malformed_params"])
    result, nats_bus = await _organize_with_nats(
        config=_production_config(),
        intent_bus=intent_bus,
        attachment_resolver_fn=_noop_attachment_resolver,
    )
    try:
        await nats_bus.publish_raw(
            "federation.intent.node-local",
            {
                "type": "intent_request",
                "source_node": "peer-A",
                "message_id": "bf672-malformed",
                "payload": {
                    "intent": "malformed_params",
                },
                "timestamp": 1.0,
            },
        )
        assert broadcasts == [{}]
    finally:
        await _stop_organized(result, nats_bus)


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [None, [], "malformed"])
async def test_resolver_malformed_non_dict_params_returns_without_store_or_fetch(
    params,
):
    store = _ExplodingAttachmentStore()
    runtime = SimpleNamespace(
        config=_production_config(peers=[_peer()]),
        attachment_store=store,
    )

    count = await resolve_missing_attachments(runtime, params, "peer-A")

    assert count == 0
    assert store.calls == []


@pytest.mark.asyncio
async def test_production_wiring_flag_off_touches_no_store_or_network():
    store = _ExplodingAttachmentStore()
    runtime = SimpleNamespace(
        config=_production_config(
            auto_resolve_remote_enabled=False,
            peers=[_peer()],
        ),
        attachment_store=store,
    )
    intent_bus = IntentBus(SignalManager())
    broadcasts: list[str] = []

    async def _record(intent: IntentMessage) -> IntentResult:
        assert store.calls == []
        broadcasts.append(intent.id)
        return IntentResult(intent_id=intent.id, agent_id="consumer", success=True)

    intent_bus.subscribe("consumer", _record, intent_names=["flag_off"])
    result, nats_bus = await _organize_with_nats(
        config=runtime.config,
        intent_bus=intent_bus,
        attachment_resolver_fn=lambda params, source: resolve_missing_attachments(
            runtime, params, source
        ),
    )
    try:
        await nats_bus.publish_raw(
            "federation.intent.node-local",
            {
                "type": "intent_request",
                "source_node": "peer-A",
                "message_id": "bf672-flag-off",
                "payload": {
                    "intent": "flag_off",
                    "params": {"attachment_ref": _PNG_SHA},
                    "id": "flag-off-intent",
                },
                "timestamp": 1.0,
            },
        )
        assert broadcasts == ["flag-off-intent"]
        responses = [
            data
            for subject, data in nats_bus.published
            if subject == "federation.intent.peer-A"
            and data["type"] == "intent_response"
        ]
        assert len(responses) == 1
    finally:
        await _stop_organized(result, nats_bus)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("params", "source_node"),
    [({}, "peer-A"), ({"attachment_ref": _PNG_SHA}, "")],
)
async def test_production_wiring_no_refs_or_empty_source_broadcasts_without_fetch(
    tmp_path,
    params,
    source_node,
):
    store = FilesystemAttachmentStore(tmp_path / "empty-boundary-attachments")
    config = _production_config(peers=[_peer()])
    runtime = SimpleNamespace(
        config=config,
        attachment_store=store,
    )
    broadcasts: list[dict[str, Any]] = []
    intent_bus = IntentBus(SignalManager())

    async def _record(intent: IntentMessage) -> IntentResult:
        broadcasts.append(intent.params)
        return IntentResult(intent_id=intent.id, agent_id="consumer", success=True)

    intent_bus.subscribe("consumer", _record, intent_names=["empty_boundary"])
    result, nats_bus = await _organize_with_nats(
        config=config,
        intent_bus=intent_bus,
        attachment_resolver_fn=lambda incoming, source: resolve_missing_attachments(
            runtime, incoming, source
        ),
    )
    try:
        await nats_bus.publish_raw(
            "federation.intent.node-local",
            {
                "type": "intent_request",
                "source_node": source_node,
                "message_id": "bf672-empty-boundary",
                "payload": {"intent": "empty_boundary", "params": params},
                "timestamp": 1.0,
            },
        )
        assert broadcasts == [params]
        assert not await store.exists(_PNG_SHA)
    finally:
        await _stop_organized(result, nats_bus)


@pytest.mark.asyncio
async def test_attachment_resolver_exception_still_broadcasts_and_responds(
    caplog,
):
    async def _raise(params: dict[str, Any], source_node: str) -> int:
        raise RuntimeError("resolver failed")

    bridge, transport, intent_bus = _make_direct_bridge(
        attachment_resolver=_raise
    )
    broadcasts: list[str] = []

    async def _record(intent: IntentMessage) -> IntentResult:
        broadcasts.append(intent.id)
        return IntentResult(intent_id=intent.id, agent_id="consumer", success=True)

    intent_bus.subscribe("consumer", _record, intent_names=["resolver_error"])
    responses: list[FederationMessage] = []

    async def _capture(peer_id: str, message: FederationMessage) -> None:
        responses.append(message)

    transport.send_to_peer = _capture

    await bridge.handle_inbound(FederationMessage(
        type="intent_request",
        source_node="peer-A",
        message_id="bf672-error",
        payload={"intent": "resolver_error", "id": "resolver-error-intent"},
        timestamp=1.0,
    ))

    assert broadcasts == ["resolver-error-intent"]
    assert len(responses) == 1
    assert responses[0].type == "intent_response"
    assert any(
        "attachment resolution failed" in message for message in caplog.messages
    )


@pytest.mark.asyncio
async def test_attachment_resolver_cancelled_propagates_without_broadcast():
    async def _cancel(params: dict[str, Any], source_node: str) -> int:
        raise asyncio.CancelledError

    bridge, transport, intent_bus = _make_direct_bridge(
        attachment_resolver=_cancel
    )
    broadcasts: list[str] = []

    async def _record(intent: IntentMessage) -> IntentResult:
        broadcasts.append(intent.id)
        return IntentResult(intent_id=intent.id, agent_id="consumer", success=True)

    intent_bus.subscribe("consumer", _record, intent_names=["resolver_cancel"])
    responses: list[FederationMessage] = []

    async def _capture(peer_id: str, message: FederationMessage) -> None:
        responses.append(message)

    transport.send_to_peer = _capture

    with pytest.raises(asyncio.CancelledError):
        await bridge.handle_inbound(FederationMessage(
            type="intent_request",
            source_node="peer-A",
            message_id="bf672-cancel",
            payload={"intent": "resolver_cancel", "id": "cancelled-intent"},
            timestamp=1.0,
        ))

    assert broadcasts == []
    assert responses == []


@pytest.mark.asyncio
async def test_bridge_without_resolver_preserves_inbound_behavior():
    bridge, transport, intent_bus = _make_direct_bridge()
    broadcasts: list[str] = []

    async def _record(intent: IntentMessage) -> IntentResult:
        broadcasts.append(intent.id)
        return IntentResult(intent_id=intent.id, agent_id="consumer", success=True)

    intent_bus.subscribe("consumer", _record, intent_names=["no_resolver"])
    responses: list[FederationMessage] = []

    async def _capture(peer_id: str, message: FederationMessage) -> None:
        responses.append(message)

    transport.send_to_peer = _capture

    await bridge.handle_inbound(FederationMessage(
        type="intent_request",
        source_node="peer-A",
        message_id="bf672-no-resolver",
        payload={"intent": "no_resolver", "id": "no-resolver-intent"},
        timestamp=1.0,
    ))

    assert broadcasts == ["no-resolver-intent"]
    assert len(responses) == 1
    assert responses[0].type == "intent_response"


# ---------------------------------------------------------------------------
# 1. off -> byte-identical
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_off_byte_identical_no_fetch(tmp_path):
    """Flag False + missing ref + valid sender -> 0, ZERO requests, not stored."""
    runtime, store = _make_runtime(
        tmp_path, auto_resolve_remote_enabled=False, peers=[_peer()]
    )
    calls = {"n": 0}
    client = _mock_client(_serving_handler(calls))
    try:
        n = await resolve_missing_attachments(
            runtime, {"attachment_ref": _PNG_SHA}, "peer-A", http=client
        )
    finally:
        await client.aclose()

    assert n == 0
    assert calls["n"] == 0
    assert not await store.exists(_PNG_SHA)


# ---------------------------------------------------------------------------
# 2. on + missing + known A2A sender -> fetched + stored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_missing_known_sender_fetches_and_stores(tmp_path):
    """Flag on + missing ref + matching peer.node_id -> 1, stored, bytes match."""
    runtime, store = _make_runtime(
        tmp_path, auto_resolve_remote_enabled=True, peers=[_peer()]
    )
    calls = {"n": 0}
    client = _mock_client(_serving_handler(calls))
    try:
        n = await resolve_missing_attachments(
            runtime, {"attachment_ref": _PNG_SHA}, "peer-A", http=client
        )
    finally:
        await client.aclose()

    assert n == 1
    assert calls["n"] == 1
    assert calls["auth"] == "Bearer tok"
    assert calls["url"].endswith(f"/api/federation/attachments/{_PNG_SHA}")
    assert await store.exists(_PNG_SHA)
    assert await store.read(_PNG_SHA) == _PNG_BYTES


# ---------------------------------------------------------------------------
# 3. on + already-local -> idempotent, no fetch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_already_local_is_idempotent_no_fetch(tmp_path):
    """Pre-stored sha -> 0 and the peer is NOT called for it."""
    runtime, store = _make_runtime(
        tmp_path, auto_resolve_remote_enabled=True, peers=[_peer()]
    )
    await store.write(_PNG_SHA, _PNG_BYTES, _PNG_MIME)
    calls = {"n": 0}
    client = _mock_client(_serving_handler(calls))
    try:
        n = await resolve_missing_attachments(
            runtime, {"attachment_ref": _PNG_SHA}, "peer-A", http=client
        )
    finally:
        await client.aclose()

    assert n == 0
    assert calls["n"] == 0
    assert await store.exists(_PNG_SHA)


@pytest.mark.asyncio
async def test_production_wiring_already_local_broadcast_sees_blob_without_fetch(
    tmp_path,
):
    store = FilesystemAttachmentStore(tmp_path / "local-hit-attachments")
    await store.write(_PNG_SHA, _PNG_BYTES, _PNG_MIME)
    config = _production_config(peers=[_peer()])
    runtime = SimpleNamespace(config=config, attachment_store=store)
    intent_bus = IntentBus(SignalManager())
    store_state_at_broadcast: list[bool] = []

    async def _record(intent: IntentMessage) -> IntentResult:
        store_state_at_broadcast.append(await store.exists(_PNG_SHA))
        return IntentResult(intent_id=intent.id, agent_id="consumer", success=True)

    intent_bus.subscribe("consumer", _record, intent_names=["local_hit"])
    result, nats_bus = await _organize_with_nats(
        config=config,
        intent_bus=intent_bus,
        attachment_resolver_fn=lambda params, source: resolve_missing_attachments(
            runtime, params, source
        ),
    )
    try:
        await nats_bus.publish_raw(
            "federation.intent.node-local",
            {
                "type": "intent_request",
                "source_node": "peer-A",
                "message_id": "bf672-local-hit",
                "payload": {
                    "intent": "local_hit",
                    "params": {"attachment_ref": _PNG_SHA},
                },
                "timestamp": 1.0,
            },
        )
        assert store_state_at_broadcast == [True]
    finally:
        await _stop_organized(result, nats_bus)


# ---------------------------------------------------------------------------
# 4. on + non-A2A sender -> no fetch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_unmapped_sender_no_fetch(tmp_path):
    """source_node matches no peer node_id (and an empty-node_id peer) -> 0."""
    runtime, store = _make_runtime(
        tmp_path,
        auto_resolve_remote_enabled=True,
        peers=[A2APeerConfig(peer_url="http://peer", auth_token="tok")],  # node_id=""
    )
    calls = {"n": 0}
    client = _mock_client(_serving_handler(calls))
    try:
        n = await resolve_missing_attachments(
            runtime, {"attachment_ref": _PNG_SHA}, "peer-A", http=client
        )
    finally:
        await client.aclose()

    assert n == 0
    assert calls["n"] == 0
    assert not await store.exists(_PNG_SHA)


@pytest.mark.asyncio
async def test_production_wiring_unmapped_sender_broadcasts_without_fetch(
    tmp_path,
):
    store = FilesystemAttachmentStore(tmp_path / "unmapped-attachments")
    config = _production_config(
        peers=[A2APeerConfig(peer_url="http://peer", auth_token="tok")]
    )
    runtime = SimpleNamespace(config=config, attachment_store=store)
    broadcasts: list[str] = []
    intent_bus = IntentBus(SignalManager())

    async def _record(intent: IntentMessage) -> IntentResult:
        broadcasts.append(intent.id)
        return IntentResult(intent_id=intent.id, agent_id="consumer", success=True)

    intent_bus.subscribe("consumer", _record, intent_names=["unmapped"])
    result, nats_bus = await _organize_with_nats(
        config=config,
        intent_bus=intent_bus,
        attachment_resolver_fn=lambda params, source: resolve_missing_attachments(
            runtime, params, source
        ),
    )
    try:
        await nats_bus.publish_raw(
            "federation.intent.node-local",
            {
                "type": "intent_request",
                "source_node": "peer-A",
                "message_id": "bf672-unmapped",
                "payload": {
                    "intent": "unmapped",
                    "params": {"attachment_ref": _PNG_SHA},
                    "id": "unmapped-intent",
                },
                "timestamp": 1.0,
            },
        )
        assert broadcasts == ["unmapped-intent"]
        assert not await store.exists(_PNG_SHA)
    finally:
        await _stop_organized(result, nats_bus)


# ---------------------------------------------------------------------------
# 5. fetch-failure -> swallowed, non-blocking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_failure_swallowed_returns_zero(tmp_path):
    """Peer 500 -> orchestrator swallows, returns 0, no exception, not stored."""
    runtime, store = _make_runtime(
        tmp_path, auto_resolve_remote_enabled=True, peers=[_peer()]
    )
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500)

    client = _mock_client(handler)
    try:
        n = await resolve_missing_attachments(
            runtime, {"attachment_ref": _PNG_SHA}, "peer-A", http=client
        )
    finally:
        await client.aclose()

    assert n == 0
    assert calls["n"] == 1  # the fetch WAS attempted, then degraded
    assert not await store.exists(_PNG_SHA)


# ---------------------------------------------------------------------------
# 6. tamper still rejected -> not stored
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tamper_rejected_not_stored(tmp_path):
    """Bytes whose sha256 != requested -> fetch False, store.write NOT called."""
    runtime, store = _make_runtime(
        tmp_path, auto_resolve_remote_enabled=True, peers=[_peer()]
    )
    tampered = b"TAMPERED-bytes-do-not-match-the-requested-sha"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=tampered, headers={"content-type": _PNG_MIME}
        )

    client = _mock_client(handler)
    try:
        n = await resolve_missing_attachments(
            runtime, {"attachment_ref": _PNG_SHA}, "peer-A", http=client
        )
    finally:
        await client.aclose()

    assert n == 0
    assert not await store.exists(_PNG_SHA)


# ---------------------------------------------------------------------------
# 7. pure resolve_sender_peer
# ---------------------------------------------------------------------------

def test_resolve_sender_peer_matching_and_misses():
    """Matches non-empty node_id; None on empty/no-match/all-empty node_ids."""
    matched = _peer("peer-A")
    a2a = FederationA2AConfig(outbound_peers=[matched])
    assert resolve_sender_peer(a2a, "peer-A") is matched
    # Empty source_node -> None.
    assert resolve_sender_peer(a2a, "") is None
    # No matching node_id -> None.
    assert resolve_sender_peer(a2a, "peer-Z") is None
    # All peers have empty node_id -> never an auto-resolution source.
    a2a_empty = FederationA2AConfig(
        outbound_peers=[A2APeerConfig(peer_url="http://p", auth_token="t")]
    )
    assert resolve_sender_peer(a2a_empty, "peer-A") is None


# ---------------------------------------------------------------------------
# 8. pure extract_attachment_shas
# ---------------------------------------------------------------------------

def test_extract_attachment_shas_shapes_dedup_and_validation():
    """Bare ref; vision_messages source.sha256; dedup; drop non-64-hex."""
    # Bare ref shape.
    assert extract_attachment_shas({"attachment_ref": _PNG_SHA}) == [_PNG_SHA]
    # Vision-block shape.
    vision = {
        "vision_messages": [
            {"content": [
                {"type": "image", "source": {"sha256": _OTHER_SHA}},
                {"type": "text", "text": "ignored"},
            ]}
        ]
    }
    assert extract_attachment_shas(vision) == [_OTHER_SHA]
    # Dedup across both shapes, first-seen order preserved.
    both = {
        "attachment_ref": _PNG_SHA,
        "vision_messages": [
            {"content": [
                {"type": "image", "source": {"sha256": _PNG_SHA}},
                {"type": "image", "source": {"sha256": _OTHER_SHA}},
            ]}
        ],
    }
    assert extract_attachment_shas(both) == [_PNG_SHA, _OTHER_SHA]
    # Drop non-64-hex / non-string / wrong-length / no refs.
    assert extract_attachment_shas({"attachment_ref": "not-a-hash"}) == []
    assert extract_attachment_shas({"attachment_ref": "a" * 63}) == []
    assert extract_attachment_shas({"attachment_ref": 12345}) == []
    assert extract_attachment_shas({}) == []
    assert extract_attachment_shas({"vision_messages": "garbage"}) == []


# ---------------------------------------------------------------------------
# 9. runtime None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_runtime_none_returns_zero():
    """resolve_missing_attachments(None, ...) -> 0 (no config access)."""
    n = await resolve_missing_attachments(
        None, {"attachment_ref": _PNG_SHA}, "peer-A"
    )
    assert n == 0


# ---------------------------------------------------------------------------
# 10. config defaults
# ---------------------------------------------------------------------------

def test_config_defaults_are_off_and_empty():
    """auto_resolve_remote_enabled default False; node_id default ''."""
    assert AttachmentsConfig().auto_resolve_remote_enabled is False
    assert A2APeerConfig(peer_url="x").node_id == ""
