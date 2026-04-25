# AD-637c: Ward Room Event Emission → NATS JetStream

**Status:** Ready for builder
**Scope:** Replace fire-and-forget `create_task()` Ward Room event dispatch with NATS JetStream publish/subscribe. Router subscribes as durable consumer. Graceful degradation to `create_task` when NATS unavailable. Extend `js_subscribe()` with consumer config parameters for flow control.
**Parent design:** `prompts/ad-637-nats-event-bus.md`
**Depends on:** AD-637a (NATSBus foundation), AD-637b (IntentBus NATS migration)

---

## Overview

Ward Room event dispatch currently uses `asyncio.create_task()` fire-and-forget in `startup/communication.py:130`. When a post is created, `WardRoomService` calls `_ward_room_emit()` which: (1) emits to WebSocket via `emit_event_fn`, then (2) spawns `asyncio.create_task(_bounded_route())` to route the event to agents. This is the exact anti-pattern AD-637 was created to eliminate — no persistence, no ordering guarantees, task failures silently lost.

AD-637b already migrated the *delivery* side — `intent_bus.send()` uses NATS when connected. What remains is the *emission* side: WardRoomService → WardRoomRouter. This AD replaces the `create_task` pattern with JetStream publish (emission side) → durable consumer (router side).

**What changes:** Event emission callback in `communication.py`, router wiring in `finalize.py`, `js_subscribe()` gains consumer config parameters, JetStream setup consolidated in finalize phase.
**What stays the same:** WardRoomRouter routing logic (1090 lines), `route_event_coalesced()`, BF-188 Captain ordering, all loop prevention, all targeting logic. No routing logic changes.

---

## Prior Work to Read

Read these files before writing any code:

- **`src/probos/startup/communication.py`** — Focus on lines 110-141. Study `_ward_room_emit()` callback, `_ward_room_router_ref` mutable list hack, `_ward_room_semaphore` (AD-616 backpressure). This is the primary file to modify.
- **`src/probos/startup/finalize.py`** — Focus on lines 134-153. Study WardRoomRouter instantiation, `_ward_room_router_ref[0]` wiring, `populate_membership_cache()`. JetStream setup (stream + consumer) goes here.
- **`src/probos/mesh/nats_bus.py`** — Study `js_publish()` (line 275), `js_subscribe()` (line 295), `ensure_stream()` (line 347). Also study MockNATSBus equivalents (lines 517-545). Note: `js_publish()` catches exceptions internally and logs — it never raises to the caller.
- **`src/probos/ward_room_router.py`** — Study `__init__()` (line 38), `route_event_coalesced()` (line 193), `route_event()` (line 229), BF-188 coordination (lines 80-83, 403-433). Do NOT modify routing logic.
- **`src/probos/runtime.py`** — Study Phase 7 (line 1379-1397) where `init_communication` is called, and Phase 1b (line 1069) where `nats_bus` is initialized. NATS is available before communication phase. Thread `nats_bus` parameter through.
- **`tests/test_ad637a_nats_foundation.py`** — Existing NATS tests. Study patterns for MockNATSBus testing.
- **`tests/test_intent.py`** — AD-637b tests. Study NATS send patterns. All must continue to pass.

---

## Design Decisions

### Router stays as coordinator
The parent AD-637 vision imagined agents subscribing directly to NATS ward room subjects. This is impractical — the WardRoomRouter (1090 lines) contains critical business logic: loop prevention, coalescing, targeting, Captain ordering (BF-188), depth caps, cooldowns, action extraction. This logic cannot be distributed. The router subscribes to JetStream as a single durable consumer and orchestrates delivery.

### No dual-delivery
When NATS is connected, events go to JetStream ONLY. When NATS is disconnected, events go through `create_task` fallback ONLY. Never both paths. Same principle as AD-637b. This invariant is enforced structurally: `_ward_room_router_ref[0]` is only wired when NATS is unavailable. When NATS is connected, the ref stays `None`, making the fallback path inert.

### Ordering semantics unchanged
The current code uses `asyncio.Semaphore(10)` which allows up to 10 concurrent `route_event_coalesced()` calls. BF-188's `_captain_delivery_done` Event coordinates across concurrent calls — agent-reply routing waits for Captain routing to complete. `max_ack_pending=10` on the JetStream consumer is semantically equivalent to `Semaphore(10)`. BF-188's cross-event Event synchronization works identically because both approaches allow the same concurrency window. No ordering semantic change.

### JetStream provides backpressure
`max_ack_pending` on the JetStream consumer replaces `asyncio.Semaphore(10)` from AD-616. The router acks after `route_event_coalesced()` returns. JetStream won't deliver beyond the pending limit until acks clear. Set to `10` to match current concurrency limit.

### ack_wait must cover slow routing
`route_event_coalesced()` has two paths: (1) post events schedule a 200ms `call_later` and return immediately — the JetStream auto-ack fires before routing completes, which is acceptable for transient notifications; (2) non-post events (thread creation) call `route_event()` directly, which includes cognitive chain processing that can take 30-120s. Set `ack_wait=120` seconds to prevent premature redelivery on the slow path.

### At-least-once delivery semantics
JetStream provides at-least-once delivery. The current `create_task` system is effectively at-most-once (fire-and-forget, lost on crash). This is a semantic upgrade, not a regression. However, redelivery can occur if a message takes longer than `ack_wait`. The router must handle duplicate events gracefully. `route_event_coalesced()` already has idempotency properties: coalescing deduplicates rapid-fire posts, `_responded_threads` prevents duplicate agent responses, depth caps and cooldowns prevent runaway chains. No additional deduplication is needed, but a test must verify this.

### BF-188 Captain ordering preserved
`_captain_delivery_done` asyncio.Event (ward_room_router.py:82) is intra-router coordination that works with concurrent `route_event()` calls. Agent-reply events wait for Captain delivery to complete (line 403-408). Captain events clear/set the Event around `_route_to_agents()` (lines 420-433). This mechanism is orthogonal to the transport layer — it works identically whether events arrive via JetStream or `create_task`.

### Coalescing preserved
`route_event_coalesced()` has its own 200ms coalescing timer (AD-616). This stays unchanged. JetStream delivery and the coalescing timer compose naturally.

### Stream configuration
- Stream name: `WARDROOM`
- Subjects: `wardroom.events.>`
- Subject hierarchy: `wardroom.events.{event_type}` (e.g., `wardroom.events.ward_room_post_created`)
- MaxAge: 3600 seconds (1 hour — events are transient)
- MaxMsgs: 10000 (bounded buffer)

### Event payload
Ward Room event data is already `dict[str, Any]`. Add `event_type` as a top-level field in the JetStream payload so the consumer can extract it. No new serialization helpers needed — the data dict maps directly to JetStream payload.

### No `nats_bus` on WardRoomRouter
Do NOT add a `nats_bus` parameter to `WardRoomRouter.__init__()`. The router receives events via its JetStream consumer callback — it doesn't need a reference to the bus. Add it in a future AD when/if the router needs it for health or metrics.

---

## Changes

### 1. Extend `js_subscribe()` with consumer config parameters

**File:** `src/probos/mesh/nats_bus.py`

Update `NATSBus.js_subscribe()` to accept `max_ack_pending` and `ack_wait`:

```python
async def js_subscribe(
    self,
    subject: str,
    callback: MessageCallback,
    durable: str | None = None,
    stream: str | None = None,
    max_ack_pending: int | None = None,  # NEW: flow control
    ack_wait: int | None = None,  # NEW: seconds before redelivery
) -> Any:
```

In the implementation, build a `ConsumerConfig` if either parameter is provided:

```python
    try:
        subscribe_kwargs: dict[str, Any] = {
            "durable": durable,
            "stream": stream,
            "cb": _handler,
        }
        if max_ack_pending is not None or ack_wait is not None:
            from nats.js.api import ConsumerConfig
            config_kwargs: dict[str, Any] = {}
            if max_ack_pending is not None:
                config_kwargs["max_ack_pending"] = max_ack_pending
            if ack_wait is not None:
                config_kwargs["ack_wait"] = ack_wait
            subscribe_kwargs["config"] = ConsumerConfig(**config_kwargs)
        sub = await self._js.subscribe(full_subject, **subscribe_kwargs)
```

**IMPORTANT:** Verify the nats-py `JetStreamContext.subscribe()` API accepts `config=ConsumerConfig(...)`. If it uses different parameter names (e.g., `consumer_config=`), adjust accordingly. The critical thing is that `max_ack_pending` limits concurrent unacked messages and `ack_wait` controls redelivery timeout.

Update `MockNATSBus.js_subscribe()` to accept the same parameters (ignored in mock):

```python
async def js_subscribe(
    self,
    subject: str,
    callback: MessageCallback,
    durable: str | None = None,
    stream: str | None = None,
    max_ack_pending: int | None = None,  # NEW: accepted but ignored in mock
    ack_wait: int | None = None,  # NEW: accepted but ignored in mock
) -> str:
    return await self.subscribe(subject, callback)
```

### 2. Thread NATS bus into communication phase

**File:** `src/probos/runtime.py`

Add `nats_bus` parameter to the `init_communication()` call (~line 1382):

```python
comm = await init_communication(
    config=self.config,
    data_dir=self._data_dir,
    checkpoint_dir=self._checkpoint_dir,
    registry=self.registry,
    identity_registry=self.identity_registry,
    episodic_memory=self.episodic_memory,
    hebbian_router=self.hebbian_router,
    emit_event_fn=self._emit_event,
    process_natural_language_fn=self.process_natural_language,
    register_workforce_resources_fn=self._register_workforce_resources,
    journal_prune_loop_fn=self._journal_prune_loop,
    nats_bus=self.nats_bus,  # AD-637c: NATS JetStream for Ward Room events
)
```

### 3. Update `init_communication` function signature

**File:** `src/probos/startup/communication.py`

Add `nats_bus` parameter:

```python
async def init_communication(
    *,
    config: "SystemConfig",
    data_dir: Path,
    checkpoint_dir: Path,
    registry: "AgentRegistry",
    identity_registry: "AgentIdentityRegistry | None",
    episodic_memory: Any,
    hebbian_router: Any,
    emit_event_fn: Callable[..., Any],
    process_natural_language_fn: Callable[..., Any],
    register_workforce_resources_fn: Callable[..., Any],
    journal_prune_loop_fn: Callable[[], Any],
    nats_bus: Any = None,  # AD-637c: NATS event bus for JetStream ward room dispatch
) -> CommunicationResult:
```

### 4. Replace `_ward_room_emit` callback with NATS-aware dispatch

**File:** `src/probos/startup/communication.py`

Replace the entire block from `_ward_room_router_ref` through `_ward_room_emit` (~lines 114-130) with NATS-aware dispatch:

```python
        # Ward room event emitter — routes to WebSocket + JetStream (AD-637c).
        # When NATS is connected, events publish to JetStream for durable delivery.
        # When NATS is disconnected, falls back to create_task direct dispatch.
        _ward_room_router_ref: list[Any] = [None]  # mutable ref for fallback path only

        # AD-616: Semaphore bounds concurrent route_event() calls (fallback path only)
        _ward_room_semaphore = asyncio.Semaphore(
            getattr(config.ward_room, 'router_concurrency_limit', 10)
        )

        # AD-637c: Task set holds references to publish tasks (prevents GC + silent loss)
        _wardroom_publish_tasks: set[asyncio.Task] = set()

        def _ward_room_emit(event_type: str, data: dict) -> None:
            # Step 1: Always emit to WebSocket (synchronous)
            emit_event_fn(event_type, data)

            # Step 2: Route to WardRoomRouter via NATS or fallback
            if nats_bus and nats_bus.connected:
                # AD-637c: JetStream publish — durable, ordered, backpressure-aware
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    logger.warning("AD-637c: Ward room emit called outside event loop, skipping NATS publish")
                    return
                payload = {"event_type": event_type, **data}
                subject = f"wardroom.events.{event_type}"
                task = loop.create_task(nats_bus.js_publish(subject, payload))
                _wardroom_publish_tasks.add(task)
                task.add_done_callback(_wardroom_publish_tasks.discard)
            else:
                # Fallback: direct dispatch via create_task (original behavior)
                router = _ward_room_router_ref[0]
                if router:
                    async def _bounded_route() -> None:
                        async with _ward_room_semaphore:
                            await router.route_event_coalesced(event_type, data)
                    asyncio.create_task(_bounded_route())
```

**Key design points:**
- `asyncio.get_running_loop()` instead of bare `create_task()` — safe when called outside event loop.
- `_wardroom_publish_tasks` set holds task references — prevents GC collection and makes failures observable via `add_done_callback`.
- `js_publish()` already catches exceptions internally and logs — no try/except wrapper needed on the caller side. If JetStream publish fails, `js_publish` logs the error and the event is dropped (acceptable: if JetStream is truly failing, `nats_bus.connected` will flip false on subsequent calls, activating the fallback path).
- No dead fallback code — `js_publish` handles its own errors.

### 5. Ensure WARDROOM stream and wire consumer in finalize phase

**File:** `src/probos/startup/finalize.py`

After the WardRoomRouter is created and `populate_membership_cache()` is called (~line 153), add the complete JetStream setup (stream + consumer subscription in one place):

```python
        # AD-637c: JetStream setup — stream ensure + consumer subscription
        # Both are in finalize.py to avoid split-phase race conditions.
        if getattr(runtime, 'nats_bus', None) and runtime.nats_bus.connected:
            # Ensure WARDROOM stream exists
            await runtime.nats_bus.ensure_stream(
                "WARDROOM",
                ["wardroom.events.>"],
                max_msgs=10000,
                max_age=3600,  # 1 hour retention
            )

            # Subscribe router as durable JetStream consumer
            async def _on_wardroom_event(msg: Any) -> None:
                """JetStream consumer callback — extract event_type and route."""
                event_type = msg.data.get("event_type", "")
                if not event_type:
                    logger.debug("AD-637c: Ward room event missing event_type, skipping")
                    return
                # Remove event_type from data before routing (router expects raw event data)
                data = {k: v for k, v in msg.data.items() if k != "event_type"}
                await ward_room_router.route_event_coalesced(event_type, data)

            await runtime.nats_bus.js_subscribe(
                "wardroom.events.>",
                _on_wardroom_event,
                durable="wardroom-router",
                stream="WARDROOM",
                max_ack_pending=10,  # Matches AD-616 concurrency limit
                ack_wait=120,  # Seconds — must exceed slow cognitive chain time
            )
            logger.info("AD-637c: WARDROOM JetStream stream + consumer wired")
```

**IMPORTANT:** The `js_subscribe` handler auto-acks on success and naks on exception (see `nats_bus.py:326-332`). For post events, `route_event_coalesced()` returns immediately after scheduling a `call_later` timer — the ack fires before actual routing. This is acceptable for transient notifications. For non-post events (thread creation), the handler blocks through the full `route_event()` call — `ack_wait=120` prevents premature redelivery.

### 6. Make `_ward_room_router_ref` wiring conditional on NATS

**File:** `src/probos/startup/finalize.py`

Replace the existing router ref wiring (~lines 149-151):

```python
        # Wire the router ref so Ward Room emit callback can route events
        if hasattr(runtime.ward_room, '_ward_room_router_ref'):
            runtime.ward_room._ward_room_router_ref[0] = ward_room_router
```

With NATS-conditional wiring:

```python
        # AD-637c: Only wire router ref for fallback path (NATS disconnected).
        # When NATS is connected, events flow through JetStream → consumer callback.
        # Not wiring the ref when NATS is active makes no-dual-delivery structural.
        if not (getattr(runtime, 'nats_bus', None) and runtime.nats_bus.connected):
            if hasattr(runtime.ward_room, '_ward_room_router_ref'):
                runtime.ward_room._ward_room_router_ref[0] = ward_room_router
```

This makes the no-dual-delivery invariant structural, not policy. When NATS is connected, `_ward_room_router_ref[0]` stays `None`, so the fallback branch in `_ward_room_emit` is inert.

---

## Tests

Create **`tests/test_ad637c_wardroom_nats.py`**. 11 tests.

### Test 1: `test_wardroom_event_publishes_to_jetstream`
When NATS is connected, a ward room emit publishes to JetStream with correct subject and payload.

Setup: Create MockNATSBus, start it. Build the `_ward_room_emit` callback as production code does. Call `_ward_room_emit("ward_room_post_created", {"thread_id": "t1", "post_id": "p1"})`. Wait for task completion. Verify `nats_bus.published` contains an entry with subject matching `wardroom.events.ward_room_post_created` and payload containing `event_type`.

### Test 2: `test_wardroom_fallback_when_nats_disconnected`
When NATS is not connected, ward room events fall back to `create_task` dispatch.

Setup: Create MockNATSBus but do NOT call `start()` (connected=False). Build the callback with a mock router in `_ward_room_router_ref[0]`. Emit an event. Verify `route_event_coalesced` is called on the mock router and `nats_bus.published` is empty.

### Test 3: `test_no_dual_delivery_with_counter`
Events go through JetStream OR fallback, never both. Uses a counter to prove structural enforcement.

Setup: Create started MockNATSBus (connected=True). Create a mock router with a `route_event_coalesced` call counter. Set `_ward_room_router_ref[0] = mock_router` (simulating a potential regression where both paths are wired). Emit 5 events. Verify: `nats_bus.published` count == 5, AND `mock_router.route_event_coalesced` call count == 0. The structural enforcement (`_ward_room_router_ref[0]` should be `None` when NATS is active) prevents dual delivery.

### Test 4: `test_router_receives_via_jetstream_consumer`
Router receives events through its JetStream subscription.

Setup: Create MockNATSBus, start it, ensure WARDROOM stream. Subscribe a mock callback as durable consumer. Publish to `wardroom.events.ward_room_post_created` with `{"event_type": "ward_room_post_created", "thread_id": "t1"}`. Verify callback received the event with `event_type` extracted and `thread_id` in data.

### Test 5: `test_js_subscribe_consumer_config_parameters`
`js_subscribe()` and `MockNATSBus.js_subscribe()` accept `max_ack_pending` and `ack_wait` without error.

```python
async def test_js_subscribe_consumer_config_parameters():
    bus = MockNATSBus()
    await bus.start()

    received = []
    async def handler(msg):
        received.append(msg)

    sub = await bus.js_subscribe(
        "test.>", handler, durable="test-consumer",
        max_ack_pending=10, ack_wait=120,
    )
    assert sub is not None
```

### Test 6: `test_wardroom_stream_ensure_config`
Stream `WARDROOM` is created with correct subjects, MaxAge, MaxMsgs.

Setup: Create MockNATSBus, start it. Call `ensure_stream("WARDROOM", ["wardroom.events.>"], max_msgs=10000, max_age=3600)`. Verify `bus._streams["WARDROOM"]` has expected config.

### Test 7: `test_wardroom_event_payload_includes_event_type`
JetStream payload includes `event_type` field for consumer extraction.

Setup: Publish a ward room event via the NATS-aware emit. Inspect `nats_bus.published[-1]` payload. Verify it has `event_type` key matching the original event type and original data fields are preserved.

### Test 8: `test_end_to_end_post_to_consumer_callback`
End-to-end: event published to JetStream → consumer callback receives with correct extraction.

Setup: Create MockNATSBus, start it. Subscribe a tracking callback. Publish event with `{"event_type": "ward_room_post_created", "thread_id": "t1", "content": "hello"}`. Verify callback received data with `event_type` == `"ward_room_post_created"` and data dict contains `thread_id` and `content` but NOT `event_type`.

### Test 9: `test_router_ref_not_wired_when_nats_connected`
When NATS is connected, `_ward_room_router_ref[0]` stays `None` (structural no-dual-delivery).

Setup: Simulate finalize phase wiring with NATS connected. Verify `_ward_room_router_ref[0]` is `None`. Then simulate with NATS disconnected. Verify `_ward_room_router_ref[0]` is the router.

### Test 10: `test_redelivery_handled_gracefully`
At-least-once delivery: duplicate events don't cause double routing.

Setup: Create MockNATSBus, start it. Subscribe a consumer callback that wraps a mock `route_event_coalesced`. Manually invoke the callback twice with the same event (simulating JetStream redelivery). Verify `route_event_coalesced` is called twice (router's own deduplication handles it via coalescing, `_responded_threads`, and cooldowns — this test confirms the consumer doesn't crash or produce unexpected behavior on duplicates).

### Test 11: `test_emit_returns_immediately`
Emit is non-blocking — the core user-facing benefit of JetStream.

Setup: Subscribe a consumer callback that sleeps for 2 seconds (simulating slow routing). Emit 10 events in rapid succession. Assert all 10 `_ward_room_emit` calls complete in under 200ms total (they should be instant since `js_publish` is fire-and-forget via `create_task`).

---

## Files Modified Summary

| File | Change |
|------|--------|
| `src/probos/mesh/nats_bus.py` | `js_subscribe()` gains `max_ack_pending` + `ack_wait` params (both NATSBus and MockNATSBus) |
| `src/probos/startup/communication.py` | NATS-aware `_ward_room_emit`, task set, `nats_bus` param |
| `src/probos/startup/finalize.py` | JetStream stream + consumer subscription, conditional router ref wiring |
| `src/probos/runtime.py` | Thread `nats_bus` into `init_communication()` call |
| `tests/test_ad637c_wardroom_nats.py` | 11 new tests |

**5 files modified** (not 6 — `ward_room_router.py` is NOT modified).

---

## Verification Checklist

```bash
# 1. Targeted tests pass
pytest tests/test_ad637c_wardroom_nats.py -v

# 2. AD-637b tests still pass (no regression)
pytest tests/test_intent.py -v

# 3. AD-637a tests still pass
pytest tests/test_ad637a_nats_foundation.py -v

# 4. Ward Room tests still pass
pytest tests/test_ward_room.py tests/test_ward_room_dms.py tests/test_ward_room_agents.py tests/test_routing.py tests/test_communications_settings.py -v

# 5. Full suite
pytest -n auto
```

## Engineering Principles Applied

- **SOLID/D (Dependency Inversion):** Emit callback depends on `nats_bus` protocol (connected property, js_publish method), not concrete NATSBus class. Typed as `Any` for the closure.
- **SOLID/S (Single Responsibility):** communication.py emits events, finalize.py wires the consumer. Separated by NATS transport.
- **SOLID/O (Open/Closed):** `js_subscribe()` extended with new optional parameters — existing callers unchanged.
- **Law of Demeter:** No reaching through objects. Router receives events via its own subscription callback, not by peeking into WardRoomService internals.
- **Fail Fast:** JetStream publish failures logged by `js_publish` internally. No dead fallback code — failures are visible, not silently swallowed.
- **DRY:** Reuses existing `js_publish()`, `js_subscribe()`, `ensure_stream()` from AD-637a. No duplicated transport logic.
- **YAGNI:** No `nats_bus` parameter added to WardRoomRouter — add it when something actually needs it.
- **Cloud-Ready:** JetStream stream config (MaxAge, MaxMsgs) is hardcoded for now. Commercial overlay can override via config if needed.
