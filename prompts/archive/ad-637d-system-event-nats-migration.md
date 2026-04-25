# AD-637d: System Event Migration (EventEmitter → NATS)

**Issue:** #308  
**Parent:** AD-637 (NATS Event Bus, Issue #270)  
**Depends:** AD-637a (NATSBus foundation), AD-637b (IntentBus), AD-637c (Ward Room)  
**Status:** Ready for builder

## Context

ProbOS has an in-memory EventEmitter pattern (`runtime._emit_event()` + `runtime.add_event_listener()`) that broadcasts events to registered callbacks. This is the same fire-and-forget `asyncio.create_task()` anti-pattern that AD-637 was created to eliminate — no persistence, no ordering, no backpressure, task failures silently lost.

**Current architecture (runtime.py:649-674, search: `def _emit_event`):**
- `_emit_event()` iterates `_event_listeners` list, calling each sync or scheduling async via `create_task()`
- `add_event_listener(fn, event_types=None)` (search: `def add_event_listener`) appends to in-memory list with optional type filter
- Night Orders escalation (`_check_night_order_escalation`, search: `def _check_night_order_escalation`) runs synchronously after every event
- ~176 event types (see `events.py:19-183`), ~190 emit sites across 31 files

**Current subscribers (5 total):**

| Subscriber | Location | Filter | Callback Type |
|------------|----------|--------|---------------|
| HXI WebSocket bridge | `api.py:168` (search: `add_event_listener` in api.py) | ALL events (no filter) | sync (`_on_runtime_event` → `_broadcast_event`) |
| Counselor agent | `counselor.py:580-608` (search: `add_event_listener` in counselor.py) | 23 event types | async (`_on_event_async`) |
| Dream reactive trigger | `dreaming.py:238-241` (search: `TASK_EXECUTION_COMPLETE` in dreaming.py) | `TASK_EXECUTION_COMPLETE` | async |
| Dream fallback learning | `dreaming.py:250-253` (search: `PROCEDURE_FALLBACK_LEARNING` in dreaming.py) | `PROCEDURE_FALLBACK_LEARNING` | async |
| Game completion cleanup | `finalize.py:370-373` (search: `GAME_COMPLETED` in finalize.py) | `GAME_COMPLETED` | async |

**Note:** Counselor and game-completion listeners are registered late (during finalize phase, after NATS stream setup). This is handled: `add_event_listener()` checks `nats_bus.connected` on each call and creates the NATS subscription immediately if connected. The bulk `_setup_nats_event_subscriptions()` only covers early-startup listeners.

**Night Orders escalation (runtime.py:750-787, search: `def _check_night_order_escalation`):** Synchronous check on every event. Only acts on 4 event types: `trust_change`, `alert_condition_change`, `build_failure`, `security_alert`. Must remain synchronous and local — it fires bridge alerts to wake the Captain and must not depend on NATS availability.

## What This AD Does NOT Do

1. **Does NOT change emit sites.** All 190 call sites that call `_emit_event()`, `emit_event()`, `_emit()`, or `emit_event_fn()` remain unchanged. The migration is entirely inside `runtime._emit_event()` and `runtime.add_event_listener()`.

2. **Does NOT migrate Ward Room events.** AD-637c already handles `wardroom.events.*` via its own JetStream stream. Those events flow through the `_ward_room_emit` callback in `communication.py`, not through `runtime._emit_event()`.

3. **Does NOT split events into persistent vs ephemeral.** The parent AD-637 spec suggested JetStream for some events and core NATS for others. This is premature optimization — all system events go through one JetStream stream. The retention is short (1 hour), the volume is manageable, and splitting creates complexity with no proven benefit. If needed later, AD-637f (Priority) can add subject partitioning.

4. **Does NOT change EventEmitterMixin.** Services that use `EventEmitterMixin._emit()` (WardRoomService, WorkItemStore, PersistentTaskStore, AssignmentService) call their stored `_emit_event` callback which ultimately reaches `runtime._emit_event()`. The mixin is untouched.

## Design Decisions

### Single JetStream stream for all system events

- **Stream name:** `SYSTEM_EVENTS`
- **Subjects:** `system.events.>` (wildcard — all event types)
- **Subject pattern:** `system.events.{event_type}` (e.g., `system.events.trust_update`)
- **MaxAge:** 3600s (1 hour — events are operational, not archival)
- **MaxMsgs:** 50,000 (bounded buffer; ~176 types × frequency)

### Publish side: `_emit_event()` dual-writes

`_emit_event()` must continue to work synchronously (callers don't await it). The NATS publish is fire-and-forget via `create_task`, same pattern as AD-637c's `_ward_room_emit`.

**Event flow after migration:**
1. Serialize event to `{"type": str, "data": dict, "timestamp": float}` (existing format)
2. Night Orders escalation check (synchronous, local — always runs)
3. If NATS connected: `create_task(nats_bus.js_publish("system.events.{type}", payload))`
4. If NATS disconnected: iterate `_event_listeners` directly (current behavior, fallback)

**Critical:** NATS publish and local dispatch are mutually exclusive paths (no-dual-delivery, same principle as AD-637b/c). When NATS is connected, subscribers receive events via their NATS subscriptions. When disconnected, they receive via the in-memory listener list.

**JSON serialization:** All current event payloads are JSON-safe (`BaseEvent.to_dict()` uses `dataclasses.asdict()` producing primitives; manual event dicts use strings, ints, floats, bools). `js_publish()` calls `json.dumps(data).encode()` — if a non-serializable type is introduced in the future, the publish will raise `TypeError` and the `create_task` error callback logs it. No pre-serialization wrapper is needed for v1.

### Subscribe side: `add_event_listener()` creates NATS subscriptions

When NATS is connected, `add_event_listener()` creates NATS subscriptions instead of appending to the in-memory list. The in-memory list becomes the fallback-only path.

**Type filtering via NATS subjects:** Instead of receiving all events and filtering in the callback (current behavior), filtered listeners subscribe to specific subjects:
- `event_types=["trust_update", "dream_complete"]` → subscribes to `system.events.trust_update` and `system.events.dream_complete`
- `event_types=None` (all events) → subscribes to `system.events.>` (wildcard)

**Consumer configuration:**
- All consumers are **ephemeral** (no `durable` parameter passed to `js_subscribe`). This is intentional:
  - Eliminates redelivery risk on NATS reconnect (no stored consumer offset to replay from)
  - System events are operational, not transactional — missing an event during a brief disconnect is acceptable
  - The fallback path (`_emit_event_local`) covers the disconnect window
  - If durable delivery is needed later, AD-637f (Priority) can add it per-subscriber
- No `max_ack_pending` tuning for v1 — default JetStream flow control is sufficient for current event volume (~176 types, 5 subscribers)

### WebSocket bridge special handling

The HXI WebSocket bridge (`api.py:163-168`) receives ALL events and forwards to WebSocket clients. This is the highest-volume consumer and the most latency-sensitive (UI updates).

**Design:** The WebSocket bridge subscribes to `system.events.>` via NATS. Its callback is the existing `_broadcast_event()` function. No durable consumer needed — WebSocket events are ephemeral (if the UI reconnects, it gets a full state snapshot via `/ws/events` connect handler at `api.py:216-222`).

### Graceful degradation

Same principle as AD-637b/c:
- NATS connected → events flow through NATS (publish → subscribe)
- NATS disconnected → events flow through in-memory listener list (current behavior)
- One path per event, never both

### Task reference safety

Same pattern as AD-637c: publish tasks stored in a set to prevent GC, `add_done_callback` to discard completed tasks, `asyncio.get_running_loop()` to safely get the loop.

## Files to Modify (4 files)

### 1. `src/probos/runtime.py` — NATS-aware event emission and subscription

**Modify `_emit_event()` (lines 649-674, search: `def _emit_event`):**

```python
def _emit_event(self, event_type: str | EventType, data: dict[str, Any] | None = None) -> None:
    """Fire-and-forget event to all registered listeners (AD-254).

    AD-637d: When NATS connected, publishes to JetStream. Subscribers
    receive via their NATS subscriptions. Falls back to in-memory dispatch
    when NATS disconnected.
    """
    # Step 1: Serialize event (unchanged)
    if isinstance(event_type, BaseEvent):
        event = event_type.to_dict()
    elif isinstance(event_type, EventType):
        event = {"type": event_type.value, "data": data or {}, "timestamp": time.time()}
    else:
        event = {"type": event_type, "data": data or {}, "timestamp": time.time()}
    type_str = event.get("type", "")

    # Step 2: Night Orders escalation (always local, synchronous)
    # AD-471: Intentionally runs BEFORE dispatch (inverted from original ordering).
    # Current code runs escalation AFTER iterating listeners. Moving it before
    # dispatch ensures escalation fires even if NATS publish or local dispatch
    # fails. Night Orders checks only 4 event types and is very fast.
    self._check_night_order_escalation(type_str, event.get("data", {}))

    # Step 3: Route — NATS or fallback (mutually exclusive)
    if getattr(self, 'nats_bus', None) and self.nats_bus.connected:
        # AD-637d: JetStream publish
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("AD-637d: _emit_event called outside event loop, using fallback")
            self._emit_event_local(event, type_str)
            return
        subject = f"system.events.{type_str}"
        task = loop.create_task(self.nats_bus.js_publish(subject, event))
        self._nats_publish_tasks.add(task)
        task.add_done_callback(self._nats_publish_tasks.discard)
    else:
        # Fallback: in-memory dispatch (original behavior)
        self._emit_event_local(event, type_str)
```

**Extract `_emit_event_local()` — current listener dispatch logic:**

```python
def _emit_event_local(self, event: dict[str, Any], type_str: str) -> None:
    """In-memory event dispatch to registered listeners (fallback path)."""
    for fn, type_filter in self._event_listeners:
        if type_filter is not None and type_str not in type_filter:
            continue
        try:
            if asyncio.iscoroutinefunction(fn):
                asyncio.create_task(fn(event))
            else:
                fn(event)
        except Exception:
            logger.debug("Event listener failed for %s", type_str, exc_info=True)
```

**Modify `add_event_listener()` (lines 627-641, search: `def add_event_listener`):**

```python
def add_event_listener(
    self,
    fn: Callable[..., Any],
    event_types: Iterable[str] | None = None,
) -> None:
    """Register a listener for system events.

    AD-637d: When NATS connected, creates NATS subscriptions for the
    specified event types. Falls back to in-memory listener list when
    NATS disconnected.
    """
    type_filter = frozenset(str(t) for t in event_types) if event_types else None
    # Always append to local list (used as fallback when NATS disconnected)
    self._event_listeners.append((fn, type_filter))

    # AD-637d: Also create NATS subscriptions when connected
    if getattr(self, 'nats_bus', None) and self.nats_bus.connected:
        self._create_nats_event_subscription(fn, type_filter)
```

**Add `_create_nats_event_subscription()` helper:**

```python
def _create_nats_event_subscription(
    self,
    fn: Callable[..., Any],
    type_filter: frozenset[str] | None,
) -> None:
    """Create NATS subscription(s) for an event listener (AD-637d)."""
    async def _nats_callback(msg: Any) -> None:
        event = msg.data
        try:
            if asyncio.iscoroutinefunction(fn):
                await fn(event)
            else:
                fn(event)
        except Exception:
            logger.debug("NATS event listener failed for %s",
                         event.get("type", ""), exc_info=True)

    async def _do_subscribe() -> None:
        if type_filter:
            # Subscribe to each specific event type
            for event_type in type_filter:
                subject = f"system.events.{event_type}"
                await self.nats_bus.js_subscribe(
                    subject,
                    _nats_callback,
                    stream="SYSTEM_EVENTS",
                )
        else:
            # No filter — subscribe to all events
            await self.nats_bus.js_subscribe(
                "system.events.>",
                _nats_callback,
                stream="SYSTEM_EVENTS",
            )

    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_do_subscribe())
        self._nats_publish_tasks.add(task)
        task.add_done_callback(self._nats_publish_tasks.discard)
    except RuntimeError:
        pass  # No event loop — local-only listener
```

**Add `_nats_publish_tasks` set initialization in `__init__` (near line 545, search: `_event_listeners`):**

```python
self._nats_publish_tasks: set[asyncio.Task] = set()  # AD-637d: prevents GC of publish tasks
```

**Add `_setup_nats_event_subscriptions()` — bulk wire existing listeners to NATS:**

This is called from finalize.py after the SYSTEM_EVENTS stream is ensured. It wires all listeners that were registered before NATS was connected (during early startup phases).

```python
def _setup_nats_event_subscriptions(self) -> None:
    """Wire existing event listeners to NATS subscriptions (AD-637d).

    Called from finalize phase after SYSTEM_EVENTS stream is ensured.
    Listeners registered during early startup phases (before NATS was
    available) get retroactively wired to NATS subscriptions.
    """
    if not (getattr(self, 'nats_bus', None) and self.nats_bus.connected):
        return
    for fn, type_filter in self._event_listeners:
        self._create_nats_event_subscription(fn, type_filter)
```

### 2. `src/probos/startup/finalize.py` — Stream + subscription wiring

**Add SYSTEM_EVENTS stream setup after WARDROOM stream setup (around line 188):**

Find the existing AD-637c WARDROOM stream block. After it, add:

```python
# AD-637d: System Events JetStream stream + subscription wiring
if getattr(runtime, 'nats_bus', None) and runtime.nats_bus.connected:
    await runtime.nats_bus.ensure_stream(
        "SYSTEM_EVENTS",
        ["system.events.>"],
        max_msgs=50000,
        max_age=3600,  # 1 hour retention
    )
    # Wire existing listeners (registered during early startup) to NATS
    runtime._setup_nats_event_subscriptions()
    logger.info("AD-637d: SYSTEM_EVENTS stream ensured, %d listeners wired to NATS",
                len(runtime._event_listeners))
```

**Placement:** This MUST come after all `add_event_listener()` calls in finalize.py (the game completion handler at line 370, and the Counselor initialization at line 452 which calls `add_event_listener_fn`). Therefore, place the NATS wiring block **after the Counselor initialization** — near the end of `init_finalize()`, before the final log statement.

**Important ordering:**
1. Early startup phases register listeners via `add_event_listener()` (appends to in-memory list)
2. Finalize phase registers remaining listeners (game completion, Counselor)
3. NATS stream is ensured
4. `_setup_nats_event_subscriptions()` bulk-wires all listeners to NATS
5. From this point forward, `_emit_event()` publishes to NATS; listeners receive via subscriptions

### 3. `src/probos/startup/communication.py` — Pass nats_bus through (already done by AD-637c)

No changes needed. AD-637c already added `nats_bus` parameter to `init_communication()`.

### 4. `tests/test_ad637d_system_events_nats.py` — New test file

## Tests (10 new)

All tests use `MockNATSBus` — no real NATS server required.

### Test 1: `test_emit_event_publishes_to_nats_when_connected`
Create a runtime-like object with `nats_bus` (MockNATSBus, connected) and `_event_listeners`. Call `_emit_event("trust_update", {"agent_id": "a1"})`. Verify MockNATSBus.published contains `("...system.events.trust_update", {"type": "trust_update", "data": {...}, "timestamp": ...})`.

### Test 2: `test_emit_event_falls_back_when_nats_disconnected`
Same setup but MockNATSBus disconnected (`_connected = False`). Call `_emit_event()`. Verify the in-memory listener callback was invoked. Verify MockNATSBus.published is empty.

### Test 3: `test_no_dual_delivery`
MockNATSBus connected. Register a listener with an invocation counter. Call `_setup_nats_event_subscriptions()` to wire NATS subscriptions. Then call `_emit_event()`. Deliver the event via the NATS mock subscription callback. Assert the counter is exactly 1 — the listener received the event once (via NATS path). Verify `_emit_event_local` was NOT called (NATS-connected branch skips it).

**Why counter == 1, not 0:** The reviewer concern was about verifying "not called via local path." The stronger assertion is that delivery happens exactly once total: once via NATS, zero via local. A counter proves both — if local also fired, counter would be 2.

### Test 4: `test_add_event_listener_creates_nats_subscription`
MockNATSBus connected. Call `add_event_listener(fn, event_types=["trust_update", "dream_complete"])`. Verify MockNATSBus has subscriptions for `system.events.trust_update` and `system.events.dream_complete`. Then publish to those subjects and verify `fn` is called.

### Test 5: `test_add_event_listener_wildcard_subscription`
MockNATSBus connected. Call `add_event_listener(fn)` with no event_types filter. Verify MockNATSBus has a subscription for `system.events.>`. Publish any event type and verify `fn` is called.

### Test 6: `test_night_orders_always_runs_locally`
MockNATSBus connected. Set up a mock `_night_orders_mgr` with `active=True` and a trigger map entry. Call `_emit_event("build_failure", {})`. Verify `_check_night_order_escalation` was called (night orders runs regardless of NATS path).

### Test 7: `test_stream_ensure_config`
Verify `ensure_stream` is called with `name="SYSTEM_EVENTS"`, `subjects=["system.events.>"]`, `max_msgs=50000`, `max_age=3600`.

### Test 8: `test_setup_nats_event_subscriptions_wires_existing`
Register 3 listeners via `add_event_listener()` with NATS disconnected (goes to local list only). Then connect NATS and call `_setup_nats_event_subscriptions()`. Verify all 3 listeners now have NATS subscriptions.

### Test 9: `test_event_payload_format_preserved`
Publish a `BaseEvent` instance, an `EventType` enum, and a legacy string. Verify all three serialize to the same `{"type": str, "data": dict, "timestamp": float}` format in the NATS message payload.

### Test 10: `test_emit_outside_event_loop_uses_fallback`
Call `_emit_event()` from outside an event loop (no running loop). Verify it falls back to `_emit_event_local()` with a warning log, not a crash.

## Verification

```bash
# Targeted tests
pytest tests/test_ad637d_system_events_nats.py -v

# AD-637 regression (prior sub-ADs)
pytest tests/test_ad637c_wardroom_nats.py tests/test_intent.py -v

# Related event system tests
pytest tests/ -k "event" -v

# Full suite (background)
pytest -n auto
```

## Engineering Principles Compliance

- **SOLID/S:** `_emit_event_local()` extracted — single responsibility for local dispatch vs NATS dispatch
- **SOLID/O:** `_emit_event()` extended with NATS path, original API preserved — all 190 call sites unchanged
- **SOLID/D:** Depends on `nats_bus.connected` property (protocol), not concrete NATSBus
- **Law of Demeter:** No reaching through objects; `_emit_event()` uses `self.nats_bus` (own attribute)
- **Fail Fast:** `RuntimeError` from `get_running_loop()` caught and falls back, logged as warning
- **DRY:** Reuses `js_publish`, `js_subscribe`, `ensure_stream` from AD-637a; same task-safety pattern as AD-637c
- **No-dual-delivery:** Structural — `if/else` on `nats_bus.connected`, one path per event

## Prior Work Absorbed

- **AD-637a:** NATSBus, MockNATSBus, `js_publish`/`js_subscribe`/`ensure_stream` API
- **AD-637b:** No-dual-delivery principle, `connected` check pattern, fallback design
- **AD-637c:** Task reference safety (`_nats_publish_tasks` set), `get_running_loop()` pattern, `create_task` from sync function, stream config pattern (max_msgs/max_age)
- **AD-254:** Original EventEmitter design (preserved as fallback)
- **AD-527:** Typed event system (`BaseEvent`, `EventType` enum) — serialization format preserved
- **AD-471:** Night Orders escalation — kept as synchronous local check
- **AD-503:** Type-filtered async listeners — type filtering now done via NATS subject matching

## Risk Assessment

### Race: Listeners registered after `_setup_nats_event_subscriptions()`

If `add_event_listener()` is called after the bulk wiring, the new listener must also get a NATS subscription. This is handled: `add_event_listener()` checks `nats_bus.connected` and creates the NATS subscription immediately if connected. The bulk wiring only covers the early-startup listeners.

### Event ordering across types

JetStream guarantees ordering within a single subject. Events of different types are on different subjects (`system.events.trust_update` vs `system.events.dream_complete`). Cross-type ordering is not guaranteed by NATS. This is acceptable — the current in-memory system also doesn't guarantee cross-listener ordering (async listeners via `create_task` are unordered).

### Night Orders must not depend on NATS

`_check_night_order_escalation()` runs BEFORE the NATS/fallback branch. It's always local, always synchronous. Even if NATS is down, Night Orders escalation still works.

### WebSocket bridge is sync, NATS callbacks are async

The WebSocket bridge callback `_on_runtime_event()` (api.py:163) is sync — it calls `_broadcast_event()` which schedules `create_task` for each WS client. When wrapped as a NATS subscriber, `_nats_callback` checks `iscoroutinefunction` and calls sync functions directly. This preserves the existing behavior.

### `remove_event_listener()` does not clean up NATS subscriptions

`runtime.py` has a `remove_event_listener(fn)` method (line 643) that removes a listener from the in-memory list by function identity. This method does NOT unsubscribe from NATS. **Current risk: zero** — `remove_event_listener` has zero callers in the entire codebase (verified via grep). All 5 listeners are registered at startup and never removed. If a future feature needs dynamic listener removal, the NATS subscription cleanup must be added at that time. Not worth building now.
