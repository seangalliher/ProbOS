# AD-637e: Federation Transport Migration (ZeroMQ → NATS)

**Issue:** #311  
**Parent:** AD-637 (NATS Event Bus, Issue #270)  
**Depends:** AD-637a (NATSBus foundation)  
**Status:** Ready for builder

## Context

ProbOS federation allows multiple ProbOS instances (ships) to cooperate — forwarding intents, exchanging gossip self-models, and (future) sharing Ward Room posts across instances. The current transport uses ZeroMQ DEALER-ROUTER sockets (`src/probos/federation/transport.py`). With AD-637a–d migrating all internal messaging to NATS, the federation transport is the last ZeroMQ dependency.

**Why migrate now:** AD-637a–d are complete. NATS provides built-in request/reply, pub/sub, reconnection, and (via leaf nodes) multi-instance topology — all things the ZeroMQ transport implements manually. Eliminating ZeroMQ removes a dependency and unifies all ProbOS messaging on one bus.

**Current architecture:**
- `FederationTransport` (search: `class FederationTransport` in `federation/transport.py`) — ZeroMQ DEALER-ROUTER sockets, 205 lines. Binds a ROUTER, connects DEALERs to peers, manual `_recv_loop()`, manual serialization.
- `FederationBridge` (search: `class FederationBridge` in `federation/bridge.py`) — Orchestrator, 263 lines. Transport-agnostic. Calls transport interface methods (`send_to_peer`, `send_to_all_peers`, `receive_with_timeout`, `deliver_response`). Handles intent forwarding, inbound dispatch, gossip loop.
- `MockFederationTransport` (search: `class MockFederationTransport` in `federation/mock_transport.py`) — In-memory mock, 124 lines. All 42 federation tests use this. **Unchanged by this AD.**
- `FederationRouter` (search: `class FederationRouter` in `federation/router.py`) — Peer selection, 47 lines. Degenerate `select_peers()` returns all. **Unchanged by this AD.**
- Startup wiring in `fleet_organization.py:139-183` (search: `federation` in `fleet_organization.py`).

**Key insight:** `FederationBridge` is already transport-agnostic. It calls the transport interface (`start`, `stop`, `send_to_peer`, `send_to_all_peers`, `receive_with_timeout`, `deliver_response`, `connected_peers`, `node_id`). NATS replaces the transport layer. Bridge correlation logic (response queues, timeout waiting) is unchanged.

## Critical: Cross-Ship Subject Namespace

**Problem:** AD-637a's `NATSBus._full_subject()` prepends a per-ship prefix (`probos.{ship_did}`) to every subject. This isolates ships from each other — which is correct for internal messaging but **breaks federation**. Federation requires cross-ship communication on shared subjects:

- Ship-1 publishes gossip → `probos.ship-1.federation.gossip`
- Ship-2 subscribes to gossip → `probos.ship-2.federation.gossip`
- They never see each other. Federation is dead silent.

**Today this is masked:** AD-637a's ship DID wiring is effectively dead code (all ships default to `probos.local`), so all ships happen to share a prefix. The moment ship DID assignment works correctly, federation breaks silently — with all tests passing (because tests share a single prefix).

**Solution: Raw (unprefixed) publish/subscribe methods.** Federation subjects are shared across ships by definition. Add `publish_raw()` and `subscribe_raw()` to `NATSBus` and `MockNATSBus` — identical to `publish()` and `subscribe()` but skip the `_full_subject()` prefix. Federation subjects become bare `federation.gossip`, `federation.intent.{node_id}` with NO ship prefix.

This preserves ship isolation for all other subjects (ward room, system events, intents) while making federation a clearly-labeled exception.

## NATS Topology Prerequisite

**Requirement:** For two ProbOS instances to federate over NATS, their NATS servers must be connected in a shared topology (single shared server, NATS cluster, or leaf node mesh). Without shared NATS infrastructure, `NATSFederationTransport` cannot deliver messages to remote ships — NATS pub/sub is scoped to the connected cluster.

**Current state:** ProbOS does not ship a default multi-instance NATS topology. Each instance connects to its own `nats://localhost:4222`. Until ProbOS ships a multi-instance topology story:
- **NATS federation is dev/single-cluster only** (two instances pointing at the same NATS server).
- **ZeroMQ remains the production multi-instance transport** (direct TCP peer connections, no shared infra needed).
- The ZeroMQ fallback is **NOT optional** — any future "remove ZeroMQ" AD must first deliver a shipped NATS topology.

**Supported bootstrap topology:** Two+ ProbOS instances connecting to the same NATS server or cluster. Multi-cluster federation (NATS leaf nodes, gateways) is an ops concern documented separately.

**`PeerConfig.address` field:** Currently `tcp://...` (ZeroMQ). For NATS transport, `address` is unused — peer reachability is determined by NATS topology, not explicit TCP addresses. The `node_id` field is the only relevant peer identifier. Document this: "When using NATS transport, `PeerConfig.address` is ignored. Peer reachability depends on NATS cluster topology."

## Transport Interface Contract

The new `NATSFederationTransport` MUST implement this exact interface (verified from `mock_transport.py` and `transport.py`):

```python
class NATSFederationTransport:
    """NATS-based federation transport.
    
    Same interface as FederationTransport / MockFederationTransport
    so FederationBridge can use any interchangeably.
    """
    
    @property
    def node_id(self) -> str: ...
    
    @property
    def connected_peers(self) -> list[str]: ...
    
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    
    async def send_to_peer(self, peer_node_id: str, message: FederationMessage) -> None: ...
    async def send_to_all_peers(self, message: FederationMessage) -> list[str]: ...
    
    async def receive_with_timeout(
        self, peer_node_id: str, timeout_ms: int
    ) -> FederationMessage | None: ...
    
    async def deliver_response(self, from_node_id: str, message: FederationMessage) -> None: ...
    
    # Bridge sets this directly (see Law of Demeter note below)
    _inbound_handler: Callable[[FederationMessage], Awaitable[None]] | None
```

### Law of Demeter: `_inbound_handler`

`FederationBridge.start()` (bridge.py:59) sets `self._transport._inbound_handler = self.handle_inbound`. This is a Law of Demeter violation — the bridge reaches into a private attribute. However, both existing transport implementations (`FederationTransport`, `MockFederationTransport`) expose `_inbound_handler` as a settable attribute. Changing this interface is out of scope — preserve the existing pattern for compatibility. Document it in the new transport's docstring as a known interface contract.

### `connected_peers` Semantic Change

**ZeroMQ:** Returns peers with active DEALER sockets — a proxy for "configured peers, transport up."
**NATS:** Returns configured peer IDs when NATS is connected. NATS does not expose per-peer connectivity — an unreachable peer on the NATS topology is invisible to this transport.

**Implication:** `connected_peers` post-migration means "peers we might be able to reach if the NATS topology is set up correctly," not "peers we have confirmed connections to." `bridge.federation_status()` will show all configured peers as "connected" even when some are unreachable.

**Document this in the class docstring.** Gossip-based liveness (tracking last-gossip-received per peer) is the correct future fix but is out of scope for this transport swap. Flag as a future enhancement.

### Pre-existing Issues (Not Fixed, Documented)

**Sequential `receive_with_timeout` per-peer:** `forward_intent` loops over peers calling `receive_with_timeout(peer_id, timeout)` sequentially. If peer-1 is slow but peer-2 is fast, total wall time = sum of timeouts, not max. This is identical behavior to the ZeroMQ transport. Out of scope for transport swap — flag as future optimization.

**Unbounded `_response_queues`:** Queues are created per peer on first message and never deleted. Same as ZeroMQ today. Out of scope — flag as future cleanup.

## NATS Subject Mapping

Federation subjects are **unprefixed** (use `publish_raw` / `subscribe_raw`) because they must be visible across ships with different `subject_prefix` values:

```
federation.gossip                     # Trust gossip — pub/sub to all peers
federation.intent.{node_id}           # Unicast intent/response delivery to specific node
federation.ping.{node_id}             # Ping delivery to specific node
```

### Message type → NATS pattern mapping:

| Message Type | Bridge Calls | NATS Pattern | Subject |
|---|---|---|---|
| `gossip_self_model` | `send_to_all_peers()` | `publish_raw()` — all peers subscribe | `federation.gossip` |
| `intent_request` | `send_to_peer()` | `publish_raw()` to peer-specific subject | `federation.intent.{peer_node_id}` |
| `intent_response` | `send_to_peer()` | `publish_raw()` to peer-specific subject | `federation.intent.{peer_node_id}` |
| `ping` | `send_to_peer()` | `publish_raw()` (fire-and-forget) | `federation.intent.{peer_node_id}` |
| `pong` | `send_to_peer()` | `publish_raw()` (fire-and-forget) | `federation.intent.{peer_node_id}` |

### Transport simplicity: no type-dispatch in `send_to_peer`

The bridge already knows the semantics: gossip goes via `send_to_all_peers()`, everything else goes via `send_to_peer()`. The transport should NOT switch on `message.type`:

- **`send_to_peer(peer_node_id, message)`** — always publishes to `federation.intent.{peer_node_id}`.
- **`send_to_all_peers(message)`** — always publishes to `federation.gossip`.

This matches the ZeroMQ transport, which doesn't switch on type either — `send_to_peer` just sends to the dealer for that peer, `send_to_all_peers` sends to all dealers. Preserve that simplicity.

### Core NATS, not JetStream

Federation messages are ephemeral inter-instance messages. No persistence needed — if a peer is offline, gossip will resume when it reconnects. Use `publish_raw()` and `subscribe_raw()` (core NATS), NOT JetStream. Do not switch to JetStream without restructuring the inbound dispatch — the `_inbound_handler` receives deserialized `FederationMessage`, not `NATSMessage`, so ack/nak semantics are not available.

## Files to Modify

### 1. `src/probos/mesh/nats_bus.py` — Add `publish_raw()` / `subscribe_raw()`

Add two methods to `NATSBus` and `MockNATSBus`. These are identical to `publish()` / `subscribe()` but skip `_full_subject()` — subjects are used as-is. This is the federation namespace fix.

**NATSBus (search: `class NATSBus` in `nats_bus.py`):**

```python
async def publish_raw(
    self,
    subject: str,
    data: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> None:
    """Publish without subject prefix — for cross-ship federation subjects."""
    if not self.connected:
        return
    payload = json.dumps(data).encode()
    await self._nc.publish(subject, payload, headers=headers)

async def subscribe_raw(
    self,
    subject: str,
    callback: MessageCallback,
    queue: str = "",
) -> Any:
    """Subscribe without subject prefix — for cross-ship federation subjects."""
    if not self.connected:
        return None

    async def _handler(msg: Any) -> None:
        try:
            raw_data = json.loads(msg.data) if msg.data else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.debug("NATS: invalid JSON on %s", msg.subject)
            return
        wrapped = NATSMessage(
            subject=msg.subject,
            data=raw_data,
            reply=msg.reply or "",
            headers=dict(msg.headers) if msg.headers else {},
            _msg=msg,
        )
        try:
            await callback(wrapped)
        except Exception:
            logger.error(
                "NATS subscriber error on %s", msg.subject, exc_info=True
            )

    sub = await self._nc.subscribe(subject, queue=queue, cb=_handler)
    self._subscriptions.append(sub)
    return sub
```

**MockNATSBus (search: `class MockNATSBus` in `nats_bus.py`):**

```python
async def publish_raw(
    self,
    subject: str,
    data: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> None:
    """Publish without subject prefix — for cross-ship federation subjects."""
    if not self._connected:
        return
    # Use subject as-is (no _full_subject)
    self.published.append((subject, data))
    msg = NATSMessage(subject=subject, data=data, headers=headers or {})
    for pattern, cbs in self._subs.items():
        if self._match_subject(pattern, subject):
            for cb in cbs:
                await cb(msg)

async def subscribe_raw(
    self,
    subject: str,
    callback: MessageCallback,
    queue: str = "",
) -> str:
    """Subscribe without subject prefix — for cross-ship federation subjects."""
    # Use subject as-is (no _full_subject)
    if subject not in self._subs:
        self._subs[subject] = []
    self._subs[subject].append(callback)
    return subject
```

### 2. `src/probos/protocols.py` — Add to `NATSBusProtocol`

Add `publish_raw` and `subscribe_raw` to the protocol (search: `class NATSBusProtocol` in `protocols.py`, around line 180):

```python
async def publish_raw(self, subject: str, data: dict[str, Any], headers: dict[str, str] | None = None) -> None: ...
async def subscribe_raw(self, subject: str, callback: Any, queue: str = "") -> Any: ...
```

## Files to Create

### 3. `src/probos/federation/nats_transport.py` — NEW

NATS-based federation transport implementing the same interface as `FederationTransport`.

```python
"""NATS federation transport — replaces ZeroMQ DEALER-ROUTER (AD-637e).

Uses NATS pub/sub for inter-instance communication via unprefixed
(raw) subjects, bypassing per-ship subject_prefix isolation.
Requires NATSBus (AD-637a) to be started before federation.

Topology prerequisite: federated ProbOS instances must share a NATS
namespace (same server, cluster, or leaf-node mesh). Without shared
NATS infrastructure, messages cannot reach remote ships. ZeroMQ
fallback remains available for direct TCP peer connections.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Awaitable
from typing import Any

from probos.mesh.nats_bus import NATSBus, NATSMessage
from probos.types import FederationMessage

logger = logging.getLogger(__name__)


class NATSFederationTransport:
    """NATS-based federation transport.

    Provides the same interface as FederationTransport / MockFederationTransport
    so FederationBridge can use any interchangeably.

    Design:
    - send_to_peer() publishes to `federation.intent.{peer_node_id}`
    - send_to_all_peers() publishes to `federation.gossip`
    - Each node subscribes to its own `federation.intent.{node_id}` + `federation.gossip`
    - All subjects are unprefixed (publish_raw/subscribe_raw) because federation
      crosses ship boundaries with different subject_prefix values.

    connected_peers semantic note: Returns configured peer IDs when NATS is
    connected. NATS pub/sub has no per-peer connection state — an unreachable
    peer is invisible. Gossip-based liveness is a future enhancement.

    Note: _inbound_handler is set directly by FederationBridge.start().
    This is a known interface contract shared with FederationTransport
    and MockFederationTransport (bridge.py:59).
    """

    def __init__(
        self,
        node_id: str,
        nats_bus: NATSBus,
        peer_node_ids: list[str],
    ) -> None:
        self._node_id = node_id
        self._nats_bus = nats_bus
        self._peer_node_ids = peer_node_ids
        self._running = False
        self._inbound_handler: (
            Callable[[FederationMessage], Awaitable[None]] | None
        ) = None
        self._response_queues: dict[str, asyncio.Queue[FederationMessage]] = {}
        self._subscriptions: list[Any] = []

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def connected_peers(self) -> list[str]:
        """Return configured peer node IDs when NATS is connected.

        Note: This does NOT verify per-peer reachability. NATS pub/sub
        has no per-peer connection state. Unreachable peers are invisible.
        Gossip-based liveness tracking is a future enhancement.
        """
        if not self._nats_bus.connected:
            return []
        return list(self._peer_node_ids)
```

**`start()` implementation:**
- Subscribe (using `subscribe_raw`) to `federation.gossip` (receive gossip from all peers)
- Subscribe (using `subscribe_raw`) to `federation.intent.{self._node_id}` (receive intents, responses, pings, pongs addressed to this node)
- Store subscription handles in `self._subscriptions`
- **Check return values:** If `subscribe_raw` returns `None`, log a warning — NATS may have disconnected between the `connected` check and the subscribe call. This is not fatal (graceful degradation to ZeroMQ) but should be visible.
- Set `self._running = True`

**`stop()` implementation:**
- Set `_running = False`
- Clear `_subscriptions` list

**`send_to_peer()` implementation — NO type dispatch:**
- Serialize `FederationMessage` to dict via `_serialize(message)`
- `await self._nats_bus.publish_raw(f"federation.intent.{peer_node_id}", data)`
- If `publish_raw` raises, log and return (fail fast, don't propagate)

**`send_to_all_peers()` implementation:**
- Serialize `FederationMessage` to dict via `_serialize(message)`
- `await self._nats_bus.publish_raw("federation.gossip", data)`
- Return `list(self._peer_node_ids)` (all configured peers, matching current semantics)

**`receive_with_timeout()` implementation:**
- Wait on `_response_queues[peer_node_id]` with `asyncio.wait_for(timeout_ms / 1000)`
- Return `FederationMessage` or `None` on timeout
- Same implementation as current ZeroMQ transport (bridge calls this after `send_to_peer`)

**`deliver_response()` implementation:**
- Same as ZeroMQ transport — put message in `_response_queues[from_node_id]`

**Inbound intent subscription callback:**
```python
async def _on_intent_message(self, nats_msg: NATSMessage) -> None:
    """Handle inbound intent/response/ping/pong messages."""
    message = self._deserialize(nats_msg.data)

    if message.type == "intent_response":
        # Route to pending request's response queue
        await self.deliver_response(message.source_node, message)
    elif self._inbound_handler:
        await self._inbound_handler(message)
```

**Inbound gossip subscription callback:**
```python
async def _on_gossip_message(self, nats_msg: NATSMessage) -> None:
    """Handle inbound gossip messages. Filters self-gossip."""
    message = self._deserialize(nats_msg.data)
    # Don't process our own gossip
    if message.source_node == self._node_id:
        return
    if self._inbound_handler:
        await self._inbound_handler(message)
```

**Serialization methods:** `_serialize(message: FederationMessage) -> dict` and `_deserialize(data: dict) -> FederationMessage`. Same logic as ZeroMQ transport (`transport.py:184-204`, search: `def _serialize` in `transport.py`) but works with dicts, not bytes (NATSBus handles JSON encoding).

### 4. `src/probos/startup/fleet_organization.py` — Lines 139-183 (search: `federation` in fleet_organization.py)

**First: Add `nats_bus` parameter to the function signature.**

Current signature (search: `async def organize_fleet` in `fleet_organization.py`):
```python
async def organize_fleet(
    *,
    config: "SystemConfig",
    ...
    validate_remote_result_fn: Callable[..., Any] | None,
) -> FleetOrganizationResult:
```

Add `nats_bus: Any | None = None` as a keyword parameter.

**Second: Add the corresponding argument at the caller.** In `runtime.py:1194` (search: `organize_fleet(` in `runtime.py`), add `nats_bus=self.nats_bus` to the call. `self.nats_bus` is available — initialized at `runtime.py:1150` (Phase 1/2), before fleet organization (Phase 3).

**Third: Replace the transport instantiation.**

Current code (lines 142-183):
```python
if config.federation.enabled:
    from probos.federation import FederationRouter, FederationBridge
    from probos.federation.mock_transport import MockFederationTransport, MockTransportBus

    # Use real transport if pyzmq available, else skip
    transport = None
    try:
        from probos.federation.transport import FederationTransport
        transport = FederationTransport(
            node_id=config.federation.node_id,
            bind_address=config.federation.bind_address,
            peers=config.federation.peers,
        )
        await transport.start()
    except ImportError:
        logger.warning("pyzmq not available; federation transport disabled")
    except Exception as e:
        logger.warning("Federation transport failed to start: %s", e)

    if transport is not None:
        router = FederationRouter()
        validate_fn = (
            validate_remote_result_fn
            if config.federation.validate_remote_results
            else None
        )
        bridge = FederationBridge(
            node_id=config.federation.node_id,
            transport=transport,
            router=router,
            intent_bus=intent_bus,
            config=config.federation,
            self_model_fn=build_self_model_fn,
            validate_fn=validate_fn,
        )
        await bridge.start()
        intent_bus.set_federation_handler(bridge.forward_intent)
        federation_bridge = bridge
        federation_transport = transport
        logger.info("Federation started: node=%s", config.federation.node_id)
```

**New code:**
```python
if config.federation.enabled:
    from probos.federation import FederationRouter, FederationBridge

    transport = None

    # Prefer NATS transport when available
    if nats_bus is not None and nats_bus.connected:
        try:
            from probos.federation.nats_transport import NATSFederationTransport

            peer_node_ids = [p.node_id for p in config.federation.peers]
            transport = NATSFederationTransport(
                node_id=config.federation.node_id,
                nats_bus=nats_bus,
                peer_node_ids=peer_node_ids,
            )
            await transport.start()
            logger.info("Federation using NATS transport")
        except Exception as e:
            logger.warning("NATS federation transport failed: %s", e)
            transport = None

    # Fallback: ZeroMQ transport (direct TCP, no shared infra needed)
    if transport is None:
        try:
            from probos.federation.transport import FederationTransport

            transport = FederationTransport(
                node_id=config.federation.node_id,
                bind_address=config.federation.bind_address,
                peers=config.federation.peers,
            )
            await transport.start()
            logger.info("Federation using ZeroMQ transport (fallback)")
        except ImportError:
            logger.warning(
                "No federation transport available "
                "(NATS not connected, pyzmq not installed)"
            )
        except Exception as e:
            logger.warning("Federation transport failed to start: %s", e)

    # Bridge construction — unchanged from existing code,
    # only the transport instance is swapped
    if transport is not None:
        router = FederationRouter()
        validate_fn = (
            validate_remote_result_fn
            if config.federation.validate_remote_results
            else None
        )
        bridge = FederationBridge(
            node_id=config.federation.node_id,
            transport=transport,
            router=router,
            intent_bus=intent_bus,
            config=config.federation,
            self_model_fn=build_self_model_fn,
            validate_fn=validate_fn,
        )
        await bridge.start()
        intent_bus.set_federation_handler(bridge.forward_intent)
        federation_bridge = bridge
        federation_transport = transport
        logger.info("Federation started: node=%s", config.federation.node_id)
```

**Note:** The `MockFederationTransport, MockTransportBus` import on the old line 144 is dead weight — it's imported but never used in production code. The new code intentionally drops it. This is cleanup, not accidental deletion.

### 5. `src/probos/federation/__init__.py` — Verify exports

Ensure `NATSFederationTransport` is importable from the package. Check current `__init__.py` (search: `__init__` in `federation/`). Add export if needed.

### 6. `src/probos/federation/transport.py` — **NO CHANGES**

Keep the ZeroMQ transport as fallback. Do NOT delete it. ZeroMQ remains the production transport for multi-instance deployments until ProbOS ships a default NATS topology. `pyzmq` stays as an optional dependency.

## Design Decisions

### No new config fields

`NatsConfig` already has `url`, `subject_prefix`, and `jetstream_domain`. `FederationConfig` already has `peers`, `node_id`, `forward_timeout_ms`, `gossip_interval_seconds`. No new config needed.

**`PeerConfig.address`** is unused by NATS transport (peer reachability is determined by NATS topology). Document this in the transport docstring. Do NOT remove the field — ZeroMQ fallback uses it.

**`forward_timeout_ms`** is not threaded into the new transport constructor. It's a bridge-level concern — `receive_with_timeout` receives the timeout from the bridge caller (`config.forward_timeout_ms`). The transport does not need its own copy.

### Peer list is a startup snapshot

`peer_node_ids: list[str]` is captured at construction. If a peer is added at runtime, the new transport doesn't pick it up. Document this constraint — it matches the ZeroMQ transport behavior (DEALER sockets are created once at `start()`).

### Self-gossip filtering

When a node publishes gossip to `federation.gossip`, it receives its own message (since it's subscribed to the same subject). The `_on_gossip_message` callback filters `message.source_node == self._node_id`. This is explicit and robust — do not use NATS `no_echo` flag, which is connection-level and would affect all subscriptions system-wide.

## Engineering Principles Compliance

- **SOLID/D (Dependency Inversion):** Transport depends on `NATSBus` via constructor injection, not direct import.
- **SOLID/S (Single Responsibility):** `NATSFederationTransport` does transport only — no type-dispatch, no routing logic. Bridge does orchestration. Router does peer selection.
- **SOLID/O (Open/Closed):** New transport class added, existing transport unchanged. Bridge uses either without modification.
- **SOLID/L (Liskov):** `NATSFederationTransport` is a drop-in replacement — same interface contract as `FederationTransport` and `MockFederationTransport`.
- **Law of Demeter:** No reaching through objects. `_inbound_handler` pattern preserved (documented as known contract).
- **Fail Fast:** NATS subscription failures → log warning, proceed (graceful degradation). NATS connection loss → fallback to ZeroMQ. Per-peer publish failures → log and continue.
- **DRY:** Reuses `NATSBus.publish_raw()`, `subscribe_raw()` from the new raw API. Serialization mirrors `transport.py`.
- **Defense in Depth:** ZeroMQ fallback preserved. NATS → ZeroMQ → no federation (degraded but functional).

## Risk Assessment

### Cross-ship namespace isolation (RESOLVED)
**Risk:** Per-ship `subject_prefix` prevents cross-ship federation.
**Mitigation:** `publish_raw()` / `subscribe_raw()` bypass prefix. Federation subjects are shared. Test `test_cross_ship_gossip_visible_with_different_prefixes` validates this explicitly.

### Self-gossip loop
**Risk:** Node receives its own gossip messages.
**Mitigation:** `_on_gossip_message` checks `message.source_node == self._node_id` and returns early.

### Response correlation
**Risk:** Intent responses arrive on the shared `federation.intent.{node_id}` subscription. The callback must distinguish `intent_request` (dispatch to bridge) from `intent_response` (route to response queue).
**Mitigation:** `_on_intent_message` checks `message.type` — same pattern as ZeroMQ transport's `_recv_loop` (transport.py:173-177, search: `intent_response` in transport.py).

### NATS subject collision with internal events
**Risk:** Federation subjects could collide with prefixed internal subjects.
**Mitigation:** Federation subjects are unprefixed (`federation.gossip`). Internal subjects are prefixed (`probos.{ship}.system.events.*`). No collision possible.

### Test isolation
**Risk:** Federation tests must continue passing unchanged.
**Mitigation:** `MockFederationTransport` is untouched. New tests use `MockNATSBus`. 42 existing tests verified green (baseline run: 42 passed, 0 failed).

### `connected_peers` semantic change
**Risk:** Post-migration, `connected_peers` reports configured peers without per-peer liveness verification. `bridge.federation_status()` will show all configured peers as "connected" even when some are unreachable.
**Mitigation:** Documented as intentional semantic change. Gossip-based liveness is a future enhancement. Matches current behavior under ZeroMQ when a peer's DEALER connects but the peer process is down (ZeroMQ DEALER connects succeed to non-listening addresses).

### Subscription error handling
**Risk:** `subscribe_raw()` returns `None` if NATS disconnects between `connected` check and subscribe call. Transport thinks it's started but receives nothing.
**Mitigation:** `start()` checks return values from `subscribe_raw()`. If `None`, log warning. Not fatal — ZeroMQ fallback handles the case where NATS transport fails entirely.

### Reconnection behavior
**Risk:** When NATS disconnects and reconnects, do federation subscriptions survive?
**Mitigation:** `nats-py` preserves subscription objects across reconnects automatically (the client object survives). After `_closed_cb` (hard close), subscriptions are gone — but at that point `nats_bus.connected` returns `False`, so `connected_peers` returns `[]` and the bridge stops forwarding. Test `test_federation_subscriptions_survive_nats_reconnect` validates.

## Tests (11 new in `tests/test_federation_nats.py`)

All tests use `MockNATSBus` — no real NATS server needed.

1. **`test_nats_transport_start_subscribes`** — After `start()`, subscriptions exist for gossip and intent subjects on MockNATSBus. Verify via `MockNATSBus._subs`.

2. **`test_nats_transport_start_checks_subscription_results`** — `start()` with a disconnected MockNATSBus logs warnings (subscribe returns None).

3. **`test_nats_transport_stop_clears_state`** — After `stop()`, `_running` is False.

4. **`test_send_to_peer_publishes_to_intent_subject`** — `send_to_peer("node-2", msg)` publishes to `federation.intent.node-2` (unprefixed). Verify via `MockNATSBus.published`.

5. **`test_send_to_all_peers_publishes_to_gossip`** — `send_to_all_peers(msg)` publishes to `federation.gossip` (unprefixed). Verify via `MockNATSBus.published`.

6. **`test_inbound_intent_dispatches_to_handler`** — Simulate a message arriving on `federation.intent.{node_id}`. Verify `_inbound_handler` is called with deserialized `FederationMessage`.

7. **`test_inbound_response_routes_to_response_queue`** — Simulate an `intent_response` arriving on the intent subscription. Verify `receive_with_timeout()` returns it.

8. **`test_self_gossip_filtered`** — Publish a gossip message with `source_node == self._node_id`. Verify `_inbound_handler` is NOT called.

9. **`test_connected_peers_empty_when_nats_disconnected`** — When `MockNATSBus.connected` is False, `connected_peers` returns `[]`.

10. **`test_cross_ship_gossip_visible_with_different_prefixes`** — **Critical namespace test.** Create two `MockNATSBus` instances with different `subject_prefix` values (`probos.ship-1` and `probos.ship-2`). Create two `NATSFederationTransport` instances using a shared `MockNATSBus` (simulating shared NATS cluster). Verify gossip published by node-1 is received by node-2. This test MUST fail if `publish`/`subscribe` (prefixed) are used instead of `publish_raw`/`subscribe_raw`.

    **Implementation note:** For this test, both transports must share a single `MockNATSBus` instance (simulating the shared NATS cluster). The two different `subject_prefix` values are set on the transports' NATSBus, but federation subjects bypass the prefix entirely — that's the point of the test.

11. **`test_falls_back_to_zmq_when_nats_disconnected`** — In `fleet_organization.py`, when `nats_bus` is `None` or disconnected, verify the code attempts ZeroMQ transport import. Mock the ZeroMQ import to verify the fallback path is taken. (This tests the wiring, not the transport itself.)

## Verification

```bash
# New federation NATS tests
pytest tests/test_federation_nats.py -v

# Existing federation tests (MUST still pass unchanged — baseline: 42 passed)
pytest tests/test_federation.py -v

# Raw API tests (new methods on NATSBus/MockNATSBus)
pytest tests/test_nats.py -v

# Full suite (background)
pytest -n auto
```

## Prior Work Absorbed

- **AD-637a:** NATSBus, MockNATSBus, `publish()`, `subscribe()` APIs (extended with `publish_raw`/`subscribe_raw`)
- **AD-637b:** No-dual-delivery principle, NATS-first with fallback pattern
- **AD-637c:** Ward Room JetStream emission pattern (federation uses core NATS, not JetStream — intentional difference)
- **AD-637d:** Ephemeral subscriber pattern, no-dual-delivery structural `if/else`
