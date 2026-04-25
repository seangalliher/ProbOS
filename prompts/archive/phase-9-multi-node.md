# Phase 9: Multi-Node Federation — The Unit Cell Tiles

**Goal:** ProbOS becomes a multi-process system. Each process is a sovereign Cognitive Mesh (Noöplex §4.2) with its own agents, trust network, Hebbian weights, and episodic memory. Nodes communicate via ZeroMQ over localhost, forwarding intents to peers and collecting remote results. The mesh gossip protocol extends across node boundaries. The architecture is the same at any population size — what changes is the number of nodes, not the design.

This phase implements Layer 4 of the Noöplex architecture — the messaging fabric that connects Cognitive Meshes:

> *"A high-throughput, low-latency messaging system connects all components of the Noöplex, enabling real-time communication between agents, meshes, and infrastructure services."* — Noöplex §4.4

And validates the fractal property:

> *"The mesh is topology-agnostic — it spans one process today, could span a network tomorrow. What changes at scale is population size, not architecture."*

---

## Context

ProbOS currently runs as a single Python process with 24 agents across 8 pools. All communication is in-process via `IntentBus.broadcast()` and `GossipProtocol`. Trust, Hebbian weights, episodic memory, dreaming, workflow cache, and pool scaling all operate within this single process.

This phase adds:
1. A `FederationTransport` wrapping ZeroMQ for cross-process messaging
2. A `FederationBridge` connecting the local `IntentBus` to the transport layer
3. A `FederationRouter` implementing the Noöplex query routing function R: Q → 2^M
4. A `NodeSelfModel` (Noöplex Ψ) broadcasting capabilities to peers via gossip
5. Inbound intent handling with loop prevention
6. Remote results passing through local consensus validation
7. Static peer discovery via YAML config
8. Shell commands and panels for federation visibility
9. A multi-node launch script for demo

**What stays local (independent brains):** Trust network, Hebbian weights, episodic memory, dreaming, workflow cache, pool scaling. Each node develops its own learned topology from its own experience (Noöplex §4.2: "Each mesh maintains its own internal state").

**What crosses the wire:** Intent broadcasts (as federated queries), intent results, gossip self-models. This maps directly to Noöplex §5.2 (inter-mesh flows: federated queries, embedding translation, graph linking — we implement the first).

---

## ⚠ AD Numbering: Start at AD-101

AD-94 through AD-100 exist from Phase 8. All architectural decisions in this phase start at **AD-101**. Do NOT reuse AD-94 through AD-100.

---

## ⚠ Pre-Build Audit: IntentBus.broadcast() Signature

**Before writing any code**, examine the current `IntentBus.broadcast()` method signature and all call sites:
- `runtime.py` calls to `submit_intent()` and `submit_intent_with_consensus()`
- `DAGExecutor._execute_node()`
- Any test that calls `broadcast()` directly

The federation changes add a `federated: bool = True` parameter to `broadcast()`. This must be backward compatible — all existing call sites that don't pass `federated` must behave identically to today. Verify no tests break from the signature change.

Also check `IntentBus.__init__()` for how to add the `_federation_fn` attribute without breaking existing construction.

---

## Dependencies

Add `pyzmq` to the project:

```bash
uv add pyzmq
```

This provides `zmq` and `zmq.asyncio` for async ZeroMQ sockets. pyzmq bundles pre-compiled wheels for Windows — no C compiler required.

---

## Deliverables

### 1. Add `FederationConfig` to `src/probos/config.py`

```python
class PeerConfig(BaseModel):
    """Configuration for a single peer node."""
    node_id: str
    address: str  # e.g. "tcp://127.0.0.1:5556"

class FederationConfig(BaseModel):
    """Multi-node federation configuration."""

    enabled: bool = False  # Disabled by default — single-node is still the default
    node_id: str = "node-1"
    bind_address: str = "tcp://127.0.0.1:5555"  # This node's ZeroMQ ROUTER address
    peers: list[PeerConfig] = []  # Static peer list
    forward_timeout_ms: int = 5000  # Timeout waiting for peer responses
    gossip_interval_seconds: float = 10.0  # How often to broadcast self-model to peers
    validate_remote_results: bool = True  # Pass remote results through local consensus
```

Add `federation: FederationConfig = FederationConfig()` to `SystemConfig`.

Add `federation:` section to `config/system.yaml` with defaults (enabled: false, no peers).

Create example multi-node configs:

```
config/node-1.yaml  — bind tcp://127.0.0.1:5555, peers: [node-2 at :5556, node-3 at :5557]
config/node-2.yaml  — bind tcp://127.0.0.1:5556, peers: [node-1 at :5555, node-3 at :5557]
config/node-3.yaml  — bind tcp://127.0.0.1:5557, peers: [node-1 at :5555, node-2 at :5556]
```

Each node config should also have a distinct `node_id` and can override pool sizes (e.g., node-2 might specialize with more file readers, node-3 with more shell agents).

### 2. Add federation types to `src/probos/types.py`

```python
class NodeSelfModel(BaseModel):
    """A node's self-assessment of its capabilities and health (Noöplex Ψ).

    Broadcast to peers via gossip so they can make routing decisions.
    """
    node_id: str
    capabilities: list[str]  # Intent names this node handles (e.g., ["read_file", "write_file"])
    pool_sizes: dict[str, int]  # pool_name → current_size
    agent_count: int
    health: float  # Average agent confidence (same as shell prompt health)
    uptime_seconds: float
    timestamp: float  # monotonic time of generation

class FederationMessage(BaseModel):
    """Wire protocol message between nodes."""
    type: str  # "intent_request", "intent_response", "gossip_self_model", "ping", "pong"
    source_node: str
    message_id: str  # UUID for request/response correlation
    payload: dict  # Type-specific data
    timestamp: float
```

### 3. Create `src/probos/federation/__init__.py`

Package root. Export `FederationTransport`, `MockFederationTransport`, `FederationRouter`, `FederationBridge`.

### 4. Create `FederationTransport` — `src/probos/federation/transport.py`

The transport layer wraps ZeroMQ for async message passing between nodes.

```python
class FederationTransport:
    """ZeroMQ transport for cross-node communication.

    Each node runs:
    - One ROUTER socket (server) bound to bind_address, receiving requests from peers
    - One DEALER socket per peer, connecting to their ROUTER addresses

    Message format on the wire: JSON-encoded FederationMessage.
    """

    def __init__(
        self,
        node_id: str,
        bind_address: str,
        peers: list[PeerConfig],
    ) -> None:
        self._node_id = node_id
        self._bind_address = bind_address
        self._peers = peers
        self._ctx: zmq.asyncio.Context | None = None
        self._router: zmq.asyncio.Socket | None = None
        self._dealers: dict[str, zmq.asyncio.Socket] = {}  # peer_node_id → DEALER socket
        self._running = False
        self._inbound_handler: Callable | None = None  # Set by bridge

    async def start(self) -> None:
        """Create ZeroMQ context, bind ROUTER, connect DEALERs to peers."""

    async def stop(self) -> None:
        """Close all sockets, destroy context."""

    async def send_to_peer(self, peer_node_id: str, message: FederationMessage) -> None:
        """Send a message to a specific peer via its DEALER socket."""

    async def send_to_all_peers(self, message: FederationMessage) -> list[str]:
        """Send a message to all connected peers. Returns list of peer IDs sent to."""

    async def receive_with_timeout(
        self, peer_node_id: str, timeout_ms: int
    ) -> FederationMessage | None:
        """Wait for a response from a specific peer. Returns None on timeout."""

    async def _inbound_loop(self) -> None:
        """Background loop receiving messages on the ROUTER socket.

        Dispatches to self._inbound_handler (set by bridge).
        """

    @property
    def connected_peers(self) -> list[str]:
        """Return list of peer node IDs with active DEALER connections."""
```

**Design constraints:**
- Use `zmq.asyncio.Context` and `zmq.asyncio.Socket` for full asyncio compatibility
- ROUTER socket uses `zmq.ROUTER` type (async multi-client server)
- DEALER sockets use `zmq.DEALER` type (async client)
- All messages are JSON-encoded UTF-8 bytes on the wire
- `send_to_peer()` prepends the peer's routing identity for ROUTER/DEALER addressing
- `_inbound_loop()` runs as a background asyncio task (started in `start()`)
- Socket linger is set to 0 on shutdown to prevent hanging

### 5. Create `MockFederationTransport` — `src/probos/federation/mock_transport.py`

```python
class MockFederationTransport:
    """In-memory federation transport for testing.

    Simulates multi-node communication without ZeroMQ.
    Messages are routed through an in-memory message bus.
    Multiple MockFederationTransport instances can be wired together
    via a shared MockTransportBus.
    """

    def __init__(self, node_id: str, bus: "MockTransportBus") -> None: ...

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send_to_peer(self, peer_node_id: str, message: FederationMessage) -> None: ...
    async def send_to_all_peers(self, message: FederationMessage) -> list[str]: ...
    async def receive_with_timeout(self, peer_node_id: str, timeout_ms: int) -> FederationMessage | None: ...

    @property
    def connected_peers(self) -> list[str]: ...


class MockTransportBus:
    """Shared message bus connecting multiple MockFederationTransport instances.

    Instantiate one bus, pass it to each MockFederationTransport.
    Messages sent to a peer are delivered to that peer's inbound queue.
    """

    def __init__(self) -> None:
        self._transports: dict[str, MockFederationTransport] = {}
        self._queues: dict[str, asyncio.Queue] = {}  # node_id → inbound queue

    def register(self, transport: MockFederationTransport) -> None: ...
    async def deliver(self, target_node_id: str, message: FederationMessage) -> None: ...
```

This is the **only** transport used in tests. All tests must pass without ZeroMQ sockets.

### 6. Create `FederationRouter` — `src/probos/federation/router.py`

The routing function from Noöplex §5.2 — decides which peers should receive a forwarded intent.

```python
class FederationRouter:
    """Federated query routing function R: intent → set[peer_node_ids].

    Decides which peers should receive a forwarded intent based on
    peer self-models (capabilities, health, pool sizes).

    Phase 9: Returns all connected peers (degenerate case with 2-3 nodes).
    Future phases can add semantic matching and cost-benefit estimation
    per Noöplex §5.2 query routing specification.
    """

    def __init__(self) -> None:
        self._peer_models: dict[str, NodeSelfModel] = {}  # node_id → latest self-model

    def update_peer_model(self, model: NodeSelfModel) -> None:
        """Update stored self-model for a peer (received via gossip)."""

    def select_peers(self, intent_name: str, available_peers: list[str]) -> list[str]:
        """Select which peers should receive this intent.

        Phase 9 implementation: return all available_peers.
        Future: filter by capability match, health threshold, cost-benefit.
        """
        return available_peers

    def peer_has_capability(self, peer_node_id: str, intent_name: str) -> bool:
        """Check if a peer has advertised capability for this intent.

        Used for informational display, not for routing (Phase 9 routes to all).
        """

    @property
    def known_peers(self) -> dict[str, NodeSelfModel]:
        """Return all known peer self-models."""
```

### 7. Create `FederationBridge` — `src/probos/federation/bridge.py`

The bridge connects the local `IntentBus` to the `FederationTransport`. This is the core integration point.

```python
class FederationBridge:
    """Connects the local IntentBus to the federation transport layer.

    Outbound: Forwards local intents to peers, collects remote results.
    Inbound: Receives intents from peers, broadcasts locally, returns results.
    Gossip: Periodically sends this node's self-model to all peers.
    """

    def __init__(
        self,
        node_id: str,
        transport: FederationTransport,  # or MockFederationTransport
        router: FederationRouter,
        intent_bus: IntentBus,
        config: FederationConfig,
        self_model_fn: Callable[[], NodeSelfModel],  # Runtime provides this
        validate_fn: Callable | None = None,  # Optional: validate remote results via consensus
    ) -> None:
        self._node_id = node_id
        self._transport = transport
        self._router = router
        self._intent_bus = intent_bus
        self._config = config
        self._self_model_fn = self_model_fn
        self._validate_fn = validate_fn
        self._gossip_task: asyncio.Task | None = None
        self._stats = {"intents_forwarded": 0, "intents_received": 0, "results_collected": 0}

    async def start(self) -> None:
        """Start the bridge: register as transport inbound handler, start gossip loop."""

    async def stop(self) -> None:
        """Stop gossip loop."""

    async def forward_intent(self, intent: IntentMessage) -> list[IntentResult]:
        """Forward an intent to selected peers and collect results.

        This is the function registered as IntentBus._federation_fn.

        Flow:
        1. Router selects peers: router.select_peers(intent.intent, transport.connected_peers)
        2. Build FederationMessage(type="intent_request", payload=intent serialized)
        3. Send to each selected peer
        4. Collect responses with timeout (config.forward_timeout_ms)
        5. Deserialize IntentResult from each response
        6. If validate_fn is set, pass remote results through local consensus validation
        7. Return collected results
        """

    async def handle_inbound(self, message: FederationMessage) -> None:
        """Handle a message received from a peer.

        Dispatches by message type:
        - intent_request: broadcast locally (federated=False), send results back
        - intent_response: route to pending request (correlation by message_id)
        - gossip_self_model: update router's peer model
        - ping: respond with pong
        """

    async def _gossip_loop(self) -> None:
        """Periodically broadcast this node's self-model to all peers."""

    def federation_status(self) -> dict:
        """Return federation status for shell/panels.

        Includes: node_id, connected_peers, known_peer_models,
        intents_forwarded, intents_received, results_collected.
        """
```

**Important design constraints:**
- `forward_intent()` is an async callable registered as `IntentBus._federation_fn`. The IntentBus calls it after collecting local results.
- Inbound intents are broadcast with `federated=False` to prevent infinite forwarding loops (AD-104).
- `self_model_fn` is a callable the runtime provides that returns a fresh `NodeSelfModel` on demand. The bridge doesn't hold a runtime reference — same injection pattern as AD-98/AD-99.
- `validate_fn` is an optional callable for consensus validation of remote results. If the runtime has consensus enabled and `config.validate_remote_results` is True, the runtime provides a validation function.
- Pending requests are tracked by `message_id` for response correlation.
- Timeout handling: if a peer doesn't respond within `forward_timeout_ms`, its results are silently dropped. Partial results from responsive peers are still returned.

### 8. Modify `IntentBus` — `src/probos/mesh/intent.py`

Minimal changes to support federation:

```python
# In IntentBus.__init__, add:
self._federation_fn: Callable[[IntentMessage], Awaitable[list[IntentResult]]] | None = None

# Modify broadcast() signature:
async def broadcast(self, intent: IntentMessage, *, federated: bool = True) -> list[IntentResult]:
    # ... existing local collection logic (unchanged) ...
    local_results = [...]

    # Record broadcast timestamp (existing Phase 8 demand tracking)
    self.record_broadcast(intent.intent)

    # Federation: forward to peers if enabled and not an inbound federated intent
    if federated and self._federation_fn:
        try:
            remote_results = await self._federation_fn(intent)
            local_results.extend(remote_results)
        except Exception as e:
            logger.debug(f"Federation forwarding failed: {e}")
            # Local results still returned — federation failure is not fatal

    return local_results
```

**Critical:** The `federated` parameter defaults to `True`, so all existing call sites that don't pass it get federation forwarding automatically. When the bridge handles an inbound intent from a peer, it calls `broadcast(intent, federated=False)` to prevent loops. The keyword-only syntax (`*,`) ensures no accidental positional passing.

**Do NOT restructure** the existing `broadcast()` method. The federation integration is 5-8 lines added at the end. All existing behavior is preserved.

### 9. Modify `runtime.py` — Wire federation

```python
# In __init__:
self.federation_bridge: FederationBridge | None = None

# In start(), after pool creation and scaler wiring, before red team spawn:
if self.config.federation.enabled:
    from probos.federation import FederationTransport, FederationRouter, FederationBridge

    transport = FederationTransport(
        node_id=self.config.federation.node_id,
        bind_address=self.config.federation.bind_address,
        peers=self.config.federation.peers,
    )
    await transport.start()

    router = FederationRouter()

    bridge = FederationBridge(
        node_id=self.config.federation.node_id,
        transport=transport,
        router=router,
        intent_bus=self.intent_bus,
        config=self.config.federation,
        self_model_fn=self._build_self_model,
        validate_fn=self._validate_remote_result if self.config.federation.validate_remote_results else None,
    )
    await bridge.start()

    # Register federation function on IntentBus
    self.intent_bus._federation_fn = bridge.forward_intent
    self.federation_bridge = bridge

    self._federation_transport = transport  # Keep reference for stop()

# New method:
def _build_self_model(self) -> NodeSelfModel:
    """Build this node's self-model (Ψ) for gossip broadcast."""
    capabilities = []
    for template_cls in self.spawner._templates.values():
        for desc in getattr(template_cls, 'intent_descriptors', []):
            capabilities.append(desc.name)
    pool_sizes = {name: pool.current_size for name, pool in self.pools.items()}
    agent_count = sum(pool.current_size for pool in self.pools.values())
    health = self._compute_health()  # Existing method used by shell prompt
    uptime = time.monotonic() - self._start_time
    return NodeSelfModel(
        node_id=self.config.federation.node_id,
        capabilities=sorted(set(capabilities)),
        pool_sizes=pool_sizes,
        agent_count=agent_count,
        health=health,
        uptime_seconds=uptime,
        timestamp=time.monotonic(),
    )

# New method (optional, for remote result validation):
async def _validate_remote_result(self, result: IntentResult) -> bool:
    """Validate a remote result through local red team verification.

    This implements Noöplex §4.3.4: "sandboxed evaluation of cross-mesh knowledge."
    Only applied to results that would normally require consensus (writes, commands, fetches).
    Read results are trusted without validation.
    """
    # Only validate results from consensus-requiring intents
    consensus_intents = {"write_file", "run_command", "http_fetch"}
    if result.intent not in consensus_intents:
        return True  # Read results trusted
    # Run through red team verification
    # ... (use existing red team verification path)
    return True  # Placeholder — implement based on existing consensus pipeline

# In stop():
if self.federation_bridge:
    await self.federation_bridge.stop()
if hasattr(self, '_federation_transport') and self._federation_transport:
    await self._federation_transport.stop()

# In status():
# Add "federation" key with bridge.federation_status() or {"enabled": False}
```

**Store `self._start_time = time.monotonic()` in `__init__`** for uptime calculation.

### 10. Add `/federation` and `/peers` commands to shell — `src/probos/experience/shell.py`

```python
# In command dispatch:
elif cmd == "/federation":
    if self.runtime.federation_bridge:
        from probos.experience.panels import render_federation_panel
        self.console.print(render_federation_panel(self.runtime.federation_bridge.federation_status()))
    else:
        self.console.print("[yellow]Federation not enabled[/yellow]")

elif cmd == "/peers":
    if self.runtime.federation_bridge:
        from probos.experience.panels import render_peers_panel
        status = self.runtime.federation_bridge.federation_status()
        self.console.print(render_peers_panel(status.get("peer_models", {})))
    else:
        self.console.print("[yellow]Federation not enabled[/yellow]")

# Add to /help listing
```

### 11. Add `render_federation_panel()` and `render_peers_panel()` to `src/probos/experience/panels.py`

**`render_federation_panel()`** — Rich table showing:
- Node ID
- Bind address
- Connected peers count
- Intents forwarded / received / results collected
- Gossip interval

**`render_peers_panel()`** — Rich table showing per-peer:
- Peer node ID
- Address
- Capabilities (comma-separated)
- Agent count
- Health
- Last gossip timestamp (seconds ago)

### 12. Add federation events to renderer — `src/probos/experience/renderer.py`

Handle `federation_forward` and `federation_receive` events in the `on_event` callback:
- `"⇆ Forwarded read_file to 2 peers"` 
- `"⇇ Received read_file from node-2"`

These are informational — don't interrupt the execution display.

### 13. Create multi-node launch script — `scripts/launch_multi.py`

A helper script that launches 2-3 ProbOS nodes as separate processes:

```python
"""Launch multiple ProbOS nodes for multi-node demo.

Usage:
    uv run python scripts/launch_multi.py          # 3 nodes
    uv run python scripts/launch_multi.py --nodes 2 # 2 nodes

Each node runs in a separate subprocess with its own config file.
"""
import subprocess
import sys
import time

def main():
    nodes = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == "--nodes" else 3
    processes = []
    for i in range(1, nodes + 1):
        config_path = f"config/node-{i}.yaml"
        proc = subprocess.Popen(
            [sys.executable, "-m", "probos", "--config", config_path],
            # Each in its own terminal would be ideal, but for simplicity:
            # just launch as background processes
        )
        processes.append(proc)
        print(f"Node {i} started (PID {proc.pid}), config: {config_path}")
        time.sleep(1)  # Stagger startup so nodes can connect to each other

    print(f"\n{nodes} nodes running. Press Ctrl+C to stop all.")
    try:
        for p in processes:
            p.wait()
    except KeyboardInterrupt:
        for p in processes:
            p.terminate()
```

Also update `__main__.py` to accept a `--config` argument for specifying an alternate config path.

### 14. Update `__main__.py` to accept `--config`

```python
import argparse

parser = argparse.ArgumentParser(description="ProbOS — Probabilistic Agent-Native OS")
parser.add_argument("--config", default="config/system.yaml", help="Path to config YAML")
args = parser.parse_args()

config = load_config(args.config)
```

This allows each node to load its own config file with distinct `node_id`, `bind_address`, and `peers`.

---

## Test Plan — ~35 new tests in `tests/test_federation.py`

All tests use `MockFederationTransport` and `MockTransportBus`. No ZeroMQ sockets in tests.

### TestFederationConfig (3 tests)
1. Defaults: enabled=False, no peers, node-1
2. Custom values: enabled=True, 2 peers, custom bind address
3. PeerConfig round-trip: node_id and address preserved

### TestFederationTypes (3 tests)
4. NodeSelfModel round-trip: all fields serialize/deserialize
5. FederationMessage round-trip: all fields serialize/deserialize
6. FederationMessage payload carries IntentMessage data

### TestMockTransportBus (4 tests)
7. Register two transports, send from A to B, B receives
8. Send to unregistered peer raises or returns gracefully
9. send_to_all_peers delivers to all registered peers
10. Timeout returns None when no response

### TestFederationRouter (4 tests)
11. select_peers with no peer models returns all available_peers
12. update_peer_model stores model, retrievable via known_peers
13. peer_has_capability returns True when intent in model capabilities
14. peer_has_capability returns False for unknown intent

### TestFederationBridgeOutbound (5 tests)
15. forward_intent sends to all peers and collects results
16. forward_intent with one unresponsive peer returns partial results from responsive peer
17. forward_intent with all peers unresponsive returns empty list
18. forward_intent increments stats (intents_forwarded, results_collected)
19. forward_intent with validate_fn calls it on each remote result

### TestFederationBridgeInbound (4 tests)
20. Inbound intent_request broadcasts locally and sends results back
21. Inbound intent_request calls broadcast(federated=False) — no re-forwarding
22. Inbound gossip_self_model updates router's peer model
23. Inbound ping responds with pong

### TestFederationBridgeLoopPrevention (2 tests)
24. Intent forwarded to peer, peer broadcasts locally but does NOT forward back
25. Two-node ring: A forwards to B, B handles locally, response returns to A (no infinite loop)

### TestIntentBusFederation (3 tests)
26. broadcast() with _federation_fn calls it and merges results
27. broadcast(federated=False) does NOT call _federation_fn
28. broadcast() with _federation_fn=None behaves as before (backward compat)

### TestFederationBridgeGossip (2 tests)
29. Gossip loop sends self-model to all peers on interval
30. Receiving gossip updates router's peer model

### TestRuntimeFederation (4 tests)
31. Runtime creates FederationBridge when federation.enabled=True
32. Runtime does NOT create bridge when federation.enabled=False
33. Runtime _build_self_model returns correct capabilities and health
34. status() includes federation info

### TestFederationPanels (2 tests)
35. render_federation_panel shows node ID and stats
36. render_peers_panel shows peer capabilities and health

### TestShellFederation (2 tests)
37. /federation command renders panel (or "not enabled" message)
38. /peers command renders peer panel (or "not enabled" message)

---

## Build Order

Follow this sequence. Run `uv run pytest tests/ -v` after each step and confirm all tests pass before moving on.

1. **Pre-build audit**: Examine `IntentBus.broadcast()` signature, all call sites, all tests that call broadcast. Verify adding `*, federated: bool = True` parameter won't break anything.
2. **FederationConfig**: Add `PeerConfig`, `FederationConfig` to `config.py` and `SystemConfig`. Add to `system.yaml`. Write tests 1–3.
3. **Federation types**: Add `NodeSelfModel`, `FederationMessage` to `types.py`. Write tests 4–6.
4. **MockTransportBus + MockFederationTransport**: Create `federation/mock_transport.py`. Write tests 7–10.
5. **FederationRouter**: Create `federation/router.py`. Write tests 11–14.
6. **FederationBridge**: Create `federation/bridge.py`. Write tests 15–23.
7. **Loop prevention**: Verify inbound intents don't re-forward. Write tests 24–25.
8. **IntentBus changes**: Add `_federation_fn` attribute and `federated` parameter to `broadcast()`. Write tests 26–28.
9. **Gossip integration**: Add gossip loop to bridge. Write tests 29–30.
10. **Runtime wiring**: Wire federation in runtime start/stop/status. Add `_build_self_model()`. Wire `_federation_fn` to IntentBus. Write tests 31–34.
11. **Shell and panels**: Add `/federation` and `/peers` commands, `render_federation_panel()`, `render_peers_panel()`. Write tests 35–38.
12. **Renderer events**: Add federation event handling.
13. **FederationTransport (real ZeroMQ)**: Create `federation/transport.py`. This is NOT tested in the test suite — it's verified manually via the launch script.
14. **Node configs**: Create `config/node-1.yaml`, `config/node-2.yaml`, `config/node-3.yaml`.
15. **__main__.py --config**: Add argparse for config path selection.
16. **Launch script**: Create `scripts/launch_multi.py`.
17. **`/help` update**: Add `/federation` and `/peers` to help output.
18. **PROGRESS.md update**: Document Phase 9, all ADs (starting at AD-101), test counts.
19. **Final verification**: `uv run pytest tests/ -v` — all tests pass.

---

## Architectural Decisions to Document

- **AD-101**: Each ProbOS process is a sovereign Cognitive Mesh (Noöplex §4.2). Trust, Hebbian weights, episodic memory, dreaming, and workflow cache stay local. Each node develops its own learned topology from its own experience. What crosses the wire: intents, results, gossip self-models.
- **AD-102**: Static peer discovery via YAML config. Each node lists its peers' addresses explicitly. Multicast/broadcast discovery is a future phase. Static config is simpler and more debuggable — when something breaks, topology is known and the problem is in the transport or protocol layer, not discovery.
- **AD-103**: ZeroMQ ROUTER/DEALER pattern for async request-response. ROUTER socket (server) bound to node's address receives from any peer. DEALER sockets (clients) connect to each peer. JSON-encoded FederationMessage on the wire. pyzmq's asyncio integration provides native asyncio compatibility.
- **AD-104**: Loop prevention via `federated` parameter on `IntentBus.broadcast()`. Default `True` means existing calls automatically get federation forwarding. Inbound intents from peers call `broadcast(federated=False)` to prevent re-forwarding. This is a one-parameter, backward-compatible change.
- **AD-105**: Federation routing function R returns all peers in Phase 9. The `FederationRouter` is structured as a proper routing function (Noöplex §5.2) that can be extended with capability matching, health thresholds, and cost-benefit estimation. Phase 9 is the degenerate case where the mesh is small enough that all peers are relevant.
- **AD-106**: NodeSelfModel (Ψ) broadcast via gossip loop. Each node periodically sends its capabilities, pool sizes, health, and uptime to all peers. This is the Noöplex mesh self-model that enables routing decisions. In Phase 9 it's informational (routing sends to all peers); in future phases it becomes the routing signal.
- **AD-107**: MockFederationTransport for all tests. The real ZeroMQ transport (`FederationTransport`) is never used in the test suite. MockTransportBus connects multiple mock transports via in-memory queues. This keeps tests deterministic, fast, and network-independent.
- **AD-108**: Remote result validation through local consensus is optional. When `validate_remote_results=True`, the bridge passes remote results through a validation function before including them. For reads, validation is skipped. For writes/commands/fetches, local red team agents verify the result. This implements Noöplex §4.3.4 "sandboxed evaluation of cross-mesh knowledge."
- **AD-109**: Federation failure is never fatal. If `_federation_fn` raises an exception or all peers time out, local results are still returned. Federation augments local capability — it doesn't gate it. The system degrades to single-node behavior on federation failure.

---

## Non-Goals

- **Multicast/broadcast peer discovery**: Static config only. Dynamic discovery is a future phase.
- **Cross-node trust synchronization**: Trust stays local. The Noöplex paper confirms this — each mesh maintains independent trust. Cross-mesh trust transitivity (T(A→C) = T(A→B) × T(B→C) × δ, Noöplex §4.3.4) is a future phase.
- **Cross-node Hebbian weight sync**: Hebbian weights stay local. Each node learns its own routing preferences.
- **Cross-node episodic memory**: Episodic memory stays local. Federated memory queries (Noöplex §4.3.2) are a future phase.
- **Smart routing**: Phase 9 routes to all peers. Capability-aware, health-weighted, cost-benefit routing is future work once the self-model gossip is proven.
- **Encryption/authentication**: Localhost communication only. TLS and node authentication are required for network-spanning deployment but out of scope for Phase 9.
- **Node auto-restart**: If a node process dies, it stays dead. Cluster management and node health monitoring are a future phase.
