# AD-637: NATS Unified Event Bus

## Overview

Replace ProbOS's three ad-hoc event dispatch patterns with NATS as the unified event bus for all internal agent communication. This is a foundational architecture change that enables guaranteed delivery, persistence, priority, backpressure, and federation-ready transport.

## Problem

ProbOS currently has three independent, incompatible event dispatch patterns:

1. **IntentBus** (`mesh/intent.py`): Direct `await handler(intent)` — no queue, no priority, blocks caller until agent completes full cognitive chain. Used for agent-to-agent intent delivery.

2. **EventEmitter** (`protocols.py`): Synchronous `_emit_event()` callbacks via `EventEmitterMixin` and `EventEmitterProtocol`. Used for HXI events, trust updates, system notifications. Fire-and-forget, no persistence.

3. **Ward Room Router** (`ward_room_router.py` + `startup/communication.py`): `asyncio.create_task(_bounded_route())` with `asyncio.Semaphore(10)` — fire-and-forget task spawning. No ordering guarantees, no backpressure beyond semaphore, no delivery confirmation.

**Symptoms exposed 2026-04-16:** Captain all-hands post reached only 6/14 crew. Root cause: Captain's sequential `route_event()` loop was starved by concurrent agent-reply routing tasks (spawned by fire-and-forget `create_task`) and proactive think cycles, all competing for LLM time with no priority or queuing.

Band-aids applied: AD-616 (semaphore), AD-636 (LLM priority scheduling). These treat symptoms, not architecture.

## Decision

Standardize on **NATS** (with JetStream) as the unified event bus.

**Why NATS:**
- Subject hierarchy maps naturally to ProbOS: `probos.{ship_did}.wardroom.{channel}`, `probos.{ship_did}.intent.{agent_id}`
- JetStream = persistence, replay, at-least-once delivery
- Request/reply pattern maps directly to IntentBus send/respond
- Single ~20MB binary, mature Python client (`nats-py`, async-native)
- Superclustering / leaf nodes = federation transport without custom topology code
- Pull consumers = backpressure without custom semaphore hacks

**Alternatives evaluated:** asyncio.PriorityQueue (no federation, no persistence), ZeroMQ (already used but too raw — DIY everything), Redis Streams (heavier, weaker federation), MQTT (no replay/request-reply), Pulsar/Kafka (overkill deployment weight), Aeron (too raw), lmdb custom (DIY months).

## Subject Hierarchy Design

```
probos.{ship_did}.
├── wardroom.
│   ├── ship                    # Ship-wide channel (Captain all-hands, general discussion)
│   ├── dept.{department}       # Department channels (medical, science, engineering, etc.)
│   ├── dm.{sorted_pair_hash}   # 1:1 DM channels
│   └── thread.{thread_id}      # Thread-specific subjects (for reply targeting)
├── intent.
│   ├── {agent_id}              # Agent-specific intent delivery (replaces IntentBus)
│   └── broadcast               # Ship-wide intent broadcast
├── system.
│   ├── event.{event_type}      # System events (replaces EventEmitter)
│   ├── priority.captain        # Captain-priority delivery queue
│   └── lifecycle               # Agent start/stop/health
└── federation.
    ├── gossip                  # Trust gossip protocol
    └── global_wardroom         # Cross-ship Ward Room (public feed)
```

## Sub-ADs

### AD-637a: NATS Integration Layer (Foundation)
**Scope:** `NATSBus` abstraction class in `src/probos/mesh/nats_bus.py`. Manages NATS server lifecycle (embedded `nats-server` subprocess or external connection), `nats-py` client connection/reconnection, health monitoring. Exposes `publish()`, `subscribe()`, `request()`, `js_publish()` (JetStream). Configurable via `system.yaml` (`nats.embedded: true`, `nats.url`, `nats.jetstream.enabled`).

**Key design:** Protocol-based (`NATSBusProtocol`) so tests can swap in a mock. Startup: `startup/nats.py` phase module, runs before communication.py. Graceful shutdown with drain.

**Dependency:** `nats-py` added to pyproject.toml. NATS server binary bundled or documented as prerequisite.

**Tests:** Connection lifecycle, reconnection, JetStream stream creation, publish/subscribe round-trip, request/reply, graceful drain.

### AD-637b: IntentBus Migration (Request/Reply)
**Scope:** Replace `IntentBus.send()` direct `await handler(intent)` with NATS request/reply on `probos.{ship_did}.intent.{agent_id}`. Each agent subscribes to its intent subject on registration. `send()` becomes `nats.request()` with timeout. Response flows back via NATS reply subject.

**Key design:** Preserve `IntentBus` API surface — callers don't change. Internal transport switches from direct function call to NATS request/reply. Fallback: if NATS unavailable, degrade to current direct-call pattern (defense in depth).

**Priority:** Captain intents published to `priority.captain` subject with higher consumer priority. AD-636 LLM priority scheduling remains — NATS handles message delivery priority, AD-636 handles LLM scheduling priority. Complementary layers.

**Tests:** Intent round-trip via NATS, timeout behavior, priority ordering, fallback to direct call.

### AD-637c: Ward Room Event Migration (Pub/Sub + JetStream)
**Scope:** Replace `create_task(_bounded_route())` fire-and-forget with JetStream publish on ward room subjects. Ward Room Router becomes a NATS subscriber dispatcher. Each agent subscribes to relevant ward room subjects (ship channel, their department, their DM channels).

**Key design:**
- Captain posts → `probos.{ship}.wardroom.ship` with JetStream (guaranteed delivery, persistence)
- Agent posts → same subject, different consumer priority
- Department posts → `probos.{ship}.wardroom.dept.{dept}`
- DMs → `probos.{ship}.wardroom.dm.{pair_hash}`
- Pull consumers with `MaxAckPending=1` per agent = natural backpressure (agent processes one message at a time)
- JetStream replay = new agents can catch up on missed messages

**Captain delivery guarantee:** Captain messages use a dedicated stream with `MaxDeliver` retry. All crew agents are durable consumers on the ship channel. Delivery is confirmed per-agent via ack.

**Tests:** Captain post reaches all 14 crew, agent reply doesn't block Captain delivery, DM delivery, department channel delivery, backpressure (agent processing one at a time), message persistence and replay.

### AD-637d: System Event Migration (EventEmitter → NATS)
**Scope:** Replace `EventEmitterMixin._emit()` and `EventEmitterProtocol` with NATS publish on `probos.{ship}.system.event.{event_type}`. Subscribers (HXI WebSocket bridge, Counselor, VitalsMonitor) subscribe to relevant event subjects.

**Key design:** Preserve `emit_event()` API on Runtime — internally publishes to NATS. `add_event_listener()` becomes NATS subscription. Events that need persistence (trust updates, circuit breaker trips) use JetStream. Ephemeral events (HXI UI updates) use core NATS (no persistence).

**Tests:** Event round-trip, HXI bridge receives events, Counselor receives trust events, subscription filtering.

### AD-637e: Federation Transport Migration
**Scope:** Replace ZeroMQ DEALER-ROUTER federation transport with NATS leaf nodes. Each ProbOS instance runs a NATS server. Federation = leaf node connections between instances. Global Ward Room = subjects on a shared supercluster.

**Key design:** `probos.{ship}.federation.gossip` for trust gossip. `federation.global_wardroom` for cross-ship public posts. Leaf node configuration in `system.yaml` (`federation.leaf_nodes: [{url: "nats://..."}]`). Authentication via DID-based NATS credentials.

**Deferred:** This is the lowest priority sub-AD. Current ZeroMQ federation works. Migrate after internal bus is stable.

**Tests:** Leaf node connection, cross-instance message delivery, DID-based auth.

### AD-637f: Priority & Guaranteed Delivery
**Scope:** Formalize priority model across NATS subjects. Captain messages get highest priority via dedicated consumer configuration. Social obligation messages (DM recipient, @mention, thread participant) get elevated priority. Proactive think cycles get lowest priority.

**Key design:**
- Three priority tiers: CRITICAL (Captain, @mention), NORMAL (ward room participation, DM), LOW (proactive think)
- Priority implemented via consumer `DeliverPolicy` and subject partitioning, not message-level priority (NATS doesn't support per-message priority natively)
- Agent processes CRITICAL subject before NORMAL before LOW via ordered subscription checking

**Tests:** Captain message processed before agent reply, proactive think deferred during ward room activity.

## Implementation Order

```
AD-637a (Foundation)     ← FIRST: NATSBus, server lifecycle, nats-py dependency
    ↓
AD-637b (IntentBus)      ← Request/reply migration, preserves API
AD-637c (Ward Room)      ← Pub/sub migration, fixes the Captain delivery bug
AD-637d (System Events)  ← EventEmitter migration
    ↓
AD-637f (Priority)       ← Once subjects exist, add priority model
    ↓
AD-637e (Federation)     ← Last: ZeroMQ replacement, lowest urgency
```

AD-637b and AD-637c can be built in parallel after AD-637a. AD-637d is independent of both. AD-637f depends on subjects existing. AD-637e is deferred.

## Immediate BFs (Pre-NATS, Can Ship Now)

These bugs exist regardless of NATS and should be fixed on the current architecture:

### BF-187: DM Social Obligation
**Problem:** Receiving a DM does not set any social obligation flag. Agents can analyze a DM as SILENT and never respond. Only `_from_captain` and `_was_mentioned` bypass SILENT.
**Fix:** Add `_is_dm` to chain context. In `cognitive_agent.py` `_execute_sub_task_chain()`, detect `direct_message` intent and set `observation["_is_dm"] = True`. In `_should_short_circuit()`, `EvaluateHandler.__call__()`, and `ReflectHandler.__call__()`, add `_is_dm` to the social obligation bypass checks alongside `_from_captain` and `_was_mentioned`.
**Scope:** 4 files (cognitive_agent.py, compose.py, evaluate.py, reflect.py), ~10 tests.

### BF-188: Captain Delivery Ordering
**Problem:** Captain's `route_event()` processes agents sequentially via `await`, but agent reply events spawn concurrent `create_task` fire-and-forget routing that can preempt remaining Captain delivery.
**Fix:** In `startup/communication.py`, when the event is a Captain post (`author_id == "captain"`), use `await` instead of `create_task` — ensure all agents receive Captain's message before any agent-reply routing begins. This is a stopgap; AD-637c is the proper fix.
**Scope:** 1 file (startup/communication.py), ~5 tests.

## Dependencies

- `nats-py` (PyPI): Async Python client for NATS. MIT licensed. Mature (3.3k GitHub stars).
- `nats-server` binary: ~20MB standalone binary. Options: (1) bundled in repo as platform-specific binary, (2) installed via system package manager, (3) Docker sidecar. Recommend option 2 for OSS, option 3 for commercial/cloud.

## Configuration (system.yaml additions)

```yaml
nats:
  enabled: true
  embedded: true              # Start nats-server as subprocess
  url: "nats://localhost:4222" # Connection URL (if not embedded)
  jetstream:
    enabled: true
    store_dir: "data/nats"    # JetStream storage directory
    max_memory: "256MB"
  federation:
    leaf_nodes: []            # [{url: "nats://remote:7422", credentials: "..."}]
```

## Files

- **New:** `src/probos/mesh/nats_bus.py` — NATSBus class
- **New:** `src/probos/startup/nats.py` — Startup phase module
- **Modify:** `src/probos/mesh/intent.py` — IntentBus transport swap (AD-637b)
- **Modify:** `src/probos/ward_room_router.py` — Pub/sub migration (AD-637c)
- **Modify:** `src/probos/startup/communication.py` — Remove fire-and-forget pattern (AD-637c)
- **Modify:** `src/probos/protocols.py` — EventEmitter migration (AD-637d)
- **Modify:** `config/system.yaml` — NATS configuration section
- **Modify:** `pyproject.toml` — Add nats-py dependency

## Prior Art to Preserve

- **AD-616:** Semaphore(10) backpressure — replaced by NATS pull consumers. Remove semaphore after migration.
- **AD-636:** LLM Priority Scheduling — COMPLEMENTARY, not replaced. NATS handles message delivery priority, AD-636 handles LLM scheduling priority. Both needed.
- **BF-184/185/186:** Social obligation bypass flags — preserved, extended with `_is_dm` in BF-187.
- **Ward Room Router:** `find_targets()` and `find_targets_for_agent()` routing logic — preserved. NATS changes the transport, not the routing decisions. These functions determine WHICH agents subscribe to WHICH subjects.

## Engineering Principles Compliance

- **DRY:** One event bus (NATS), not three (IntentBus + EventEmitter + create_task).
- **Open/Closed:** NATSBus is protocol-based — swap implementations without changing callers.
- **Dependency Inversion:** Callers depend on NATSBusProtocol, not nats-py directly.
- **Fail Fast:** NATS connection loss → log warning, degrade to direct calls (not crash).
- **Defense in Depth:** Fallback to direct-call pattern if NATS unavailable. JetStream persistence for critical messages. Ack-based delivery confirmation.
- **Cloud-Ready:** NATS server can be external (commercial overlay swaps embedded → managed NATS cluster).
