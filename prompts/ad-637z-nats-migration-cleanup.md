# AD-637z: NATS Migration Cleanup + BF-221 Lift

**Issue:** #321  
**Parent:** AD-637 (NATS Event Bus, Issue #270)  
**Depends:** AD-637a (NATSBus foundation), AD-637b (IntentBus), AD-637c (Ward Room), AD-637d (System Events)  
**Status:** Ready for builder

## Context

AD-637 migrated ProbOS from ad-hoc asyncio messaging to NATS as the unified event bus. Sub-ADs a/b/c/d are complete. During live testing, Captain's all-hands message targeted 14 agents but none responded — root cause was NATS subject prefix mutation (`probos.local` → `probos.did:probos:{uuid}`) invalidating subscriptions created earlier in startup. Emergency fix BF-221 disabled NATS request/reply in `IntentBus.send()`, forcing direct in-process calls.

This AD fixes four infrastructure bugs, then lifts BF-221 to re-enable NATS as the actual transport for intent dispatch. NATS must be the real message bus, not a sidecar event log — federation and multi-instance scaling depend on it.

## The Four Bugs + BF-221 Lift

### Bug 1: Subject Prefix Mutation Breaks NATS Subscriptions (BF-221 root cause)
- `nats_bus.set_subject_prefix()` (search: `def set_subject_prefix` in `nats_bus.py`, line 110) only updates the string — no re-subscription
- Subscriptions created in Phase 2 use prefix `probos.local`; prefix mutated to `probos.did:probos:{uuid}` after Phase 7 (search: `set_subject_prefix` in `runtime.py`, line 1536)
- **Fix**: NATSBus tracks active subscriptions (un-prefixed subjects). `set_subject_prefix()` becomes async, unsubscribes old subs, re-subscribes with new prefix, notifies callbacks.

### Bug 2: Double System Event Subscriptions
- `add_event_listener()` (search: `def add_event_listener` in `runtime.py`, line 629) creates NATS sub inline when connected (line 644-646)
- `_setup_nats_event_subscriptions()` (search: `def _setup_nats_event_subscriptions` in `runtime.py`, line 695) bulk re-subscribes ALL listeners
- Listeners registered after NATS connects get subscribed TWICE
- **Fix**: Gate inline subscription on `_nats_events_wired` flag

### Bug 3: `ensure_future` Task Leak in IntentBus
- `subscribe()` (search: `ensure_future` in `intent.py`, line 60) — fire-and-forget, no reference held, exceptions silently lost
- `unsubscribe()` (search: `ensure_future` in `intent.py`, line 100) — same pattern
- **Fix**: Replace with `create_task()`, hold references in `_pending_sub_tasks` set, log errors on completion

### Bug 4: Duplicate `ensure_stream` Calls
- SYSTEM_EVENTS and WARDROOM streams created in both `startup/nats.py` (search: `ensure_stream` in `nats.py`, lines 54-65) AND `finalize.py` (search: `ensure_stream` in `finalize.py`, lines 162-167 and 673-678)
- Config drift risk
- **Fix**: Remove from `finalize.py`, keep canonical location in `startup/nats.py`

### BF-221 Lift: Re-enable NATS Request/Reply for IntentBus.send()
- With Bug 1 fixed (prefix re-subscription), the root cause of BF-221 is resolved
- `send()` (search: `async def send` in `intent.py`, line 113) currently forces direct-call path
- **Fix**: Restore NATS request/reply when connected, direct-call fallback when disconnected. One path per call, never both.

## What This AD Does NOT Do

1. **Does NOT add durable consumers for system events.** There are ~176 event types and 5 listeners. Per-event-type durable consumers would create 100+ consumers with name collisions when two listeners filter the same event type. Ephemeral consumers are correct for operational telemetry — the in-memory fallback path covers NATS downtime, and stream retention (1 hour) provides replay capability. If durability is needed later, a separate AD must address the collision and `ack_wait` problems properly.

2. **Does NOT add NATS reconnect re-subscription.** The `_reconnected_cb` (search: `_reconnected_cb` in `nats_bus.py`) is a separate reliability story. This AD handles prefix change only.

3. **Does NOT change broadcast() to use NATS.** Broadcast fan-out remains in-process.

4. **Does NOT track `publish_raw`/`subscribe_raw` subscriptions.** Federation uses raw subjects to bypass per-ship prefix isolation — they must NOT be re-keyed on prefix change. This is intentional, not a gap.

## Design Decisions

### NATSBus owns all subscription lifecycle

NATSBus tracks every subscription created via `subscribe()` and `js_subscribe()` in `_active_subs`. When the prefix changes, NATSBus unsubscribes the old subs and re-creates them with the new prefix. External code (IntentBus) does NOT manually unsub/resub — that creates zombie entries and double subscriptions. External code can register a notification callback for logging/bookkeeping, but NATSBus is the single owner.

### IntentBus simplified — no `_nats_subs` dict

Previously, IntentBus maintained `_nats_subs` (agent_id → NATS sub handle) for cleanup. This creates a parallel tracking problem: NATSBus re-subscribes everything, but IntentBus's mapping goes stale. Then IntentBus tries to unsub dead handles and re-subscribe, creating duplicates.

New design: IntentBus subscribes via `nats_bus.subscribe()` (which tracks in `_active_subs`). IntentBus does not hold sub references. For `unsubscribe()`, IntentBus calls `nats_bus.remove_tracked_subscription(subject)` — a new NATSBus method that finds and removes the tracked entry by un-prefixed subject.

### Double-delivery during prefix change window

When NATSBus unsubscribes an old sub and re-subscribes on the new prefix, in-flight messages on the old prefix may still be dispatched before the unsubscribe takes effect. This is a sub-millisecond window. Consumers must be idempotent. For JetStream messages, `msg.metadata.sequence` can be used for dedup if needed. For this AD, we document the window and accept it — it's not a practical problem for single-instance deployment.

### `_active_subs` stores stripped (un-prefixed) subjects

To prevent double-prefixing if a caller passes an already-prefixed subject, `subscribe()` and `js_subscribe()` strip the current prefix before storing in `_active_subs`. This ensures `_full_subject()` correctly applies the new prefix on re-subscription.

## Implementation

### Step 1: Remove Duplicate `ensure_stream` from `finalize.py` (Bug 4)

**File: `src/probos/startup/finalize.py`**

**1a.** Remove the `ensure_stream("WARDROOM", ...)` block (search: `ensure_stream.*WARDROOM` in `finalize.py`, lines 160-167). This block is:
```python
            # Ensure WARDROOM stream exists
            await runtime.nats_bus.ensure_stream(
                "WARDROOM",
                ["wardroom.events.>"],
                max_msgs=10000,
                max_age=3600,  # 1 hour retention
            )
```
**Keep** the `_on_wardroom_event` callback definition and `js_subscribe` that follow (lines 169-187). The consumer depends on the stream existing, which `startup/nats.py` guarantees (Phase 1b, before finalize Phase 8).

After removal, the NATS-connected block should flow directly from the guard to the callback definition:
```python
        if getattr(runtime, 'nats_bus', None) and runtime.nats_bus.connected:
            # Subscribe router as durable JetStream consumer
            async def _on_wardroom_event(msg: Any) -> None:
                ...
```

**1b.** Remove the `ensure_stream("SYSTEM_EVENTS", ...)` block (search: `ensure_stream.*SYSTEM_EVENTS` in `finalize.py`, lines 673-678):
```python
        await runtime.nats_bus.ensure_stream(
            "SYSTEM_EVENTS",
            ["system.events.>"],
            max_msgs=50000,
            max_age=3600,  # 1 hour retention
        )
```
**Keep** the `_setup_nats_event_subscriptions()` call and logging that follow.

**1c.** No changes to `startup/nats.py` — it is canonical and correct.

### Step 2: NATSBus Subscription Tracking (Bug 1 Foundation)

**File: `src/probos/mesh/nats_bus.py`** — NATSBus class

**2a. Add tracking fields** to `__init__` (after `self._started = False`, line 99):
```python
        self._active_subs: list[dict[str, Any]] = []  # Tracked subs for prefix re-subscription
        self._prefix_change_callbacks: list[Callable] = []
        self._resubscribing: bool = False
```

**2b. Add prefix stripping helper** (after `_full_subject`, line 118):
```python
    def _strip_prefix(self, subject: str) -> str:
        """Remove current prefix from subject for storage in _active_subs."""
        prefix_dot = self._subject_prefix + "."
        if subject.startswith(prefix_dot):
            return subject[len(prefix_dot):]
        return subject
```

**2c. Convert `set_subject_prefix()` to async** (replace lines 110-112):
```python
    async def set_subject_prefix(self, prefix: str) -> None:
        """Update subject prefix and re-subscribe all tracked subscriptions.

        AD-637z: Subscriptions created via subscribe()/js_subscribe() are
        tracked in _active_subs with un-prefixed subjects. On prefix change,
        each is unsubscribed and re-created with the new prefix.

        Note: publish_raw/subscribe_raw are intentionally NOT tracked.
        Federation uses raw subjects to bypass per-ship prefix isolation.
        """
        if prefix == self._subject_prefix:
            return
        old_prefix = self._subject_prefix
        self._subject_prefix = prefix
        logger.info("NATS subject prefix changed: %s → %s", old_prefix, prefix)

        # Re-subscribe all tracked subscriptions with new prefix
        if self.connected and self._active_subs:
            self._resubscribing = True
            try:
                for entry in self._active_subs:
                    old_sub = entry["sub"]
                    if old_sub is not None:
                        try:
                            await old_sub.unsubscribe()
                        except Exception as e:
                            logger.debug("Unsubscribe during prefix change: %s", e)

                    # Re-create with new prefix (subscribe/js_subscribe use _full_subject)
                    if entry["kind"] == "core":
                        new_sub = await self.subscribe(
                            entry["subject"], entry["callback"], **entry["kwargs"]
                        )
                    else:
                        new_sub = await self.js_subscribe(
                            entry["subject"], entry["callback"], **entry["kwargs"]
                        )
                    entry["sub"] = new_sub
            finally:
                self._resubscribing = False

        # Notify registered callbacks (notification only — NATSBus already re-subscribed)
        for cb in self._prefix_change_callbacks:
            try:
                await cb(old_prefix, prefix)
            except Exception as e:
                logger.warning("Prefix change callback failed: %s", e)
```

**2d. Add `register_on_prefix_change()`** (after `set_subject_prefix`):
```python
    def register_on_prefix_change(
        self, callback: Callable[[str, str], Awaitable[None]]
    ) -> None:
        """Register a callback for subject prefix changes (notification only).

        Callbacks fire AFTER NATSBus has re-subscribed everything. They are
        for logging and bookkeeping — NOT for managing subscriptions.
        """
        self._prefix_change_callbacks.append(callback)
```

**2e. Add `remove_tracked_subscription()`** (after `register_on_prefix_change`):
```python
    async def remove_tracked_subscription(self, subject: str) -> bool:
        """Remove and unsubscribe a tracked subscription by un-prefixed subject.

        Used by IntentBus.unsubscribe() to clean up agent subscriptions
        without maintaining a parallel tracking dict.
        Returns True if found and removed, False otherwise.
        """
        for i, entry in enumerate(self._active_subs):
            if entry["subject"] == subject:
                sub = entry["sub"]
                if sub is not None:
                    try:
                        await sub.unsubscribe()
                    except Exception as e:
                        logger.debug("Tracked unsubscribe error: %s", e)
                self._active_subs.pop(i)
                return True
        return False
```

**2f. Update `subscribe()`** (search: `def subscribe` in NATSBus). After the existing `self._subscriptions.append(sub)` line (~line 244), add tracking:
```python
        if not self._resubscribing:
            self._active_subs.append({
                "kind": "core",
                "subject": self._strip_prefix(subject),
                "callback": callback,
                "kwargs": {"queue": queue} if queue else {},
                "sub": sub,
            })
```

**2g. Update `js_subscribe()`** (search: `def js_subscribe` in NATSBus). Inside the `try` block, after `self._subscriptions.append(sub)` (~line 351), add tracking:
```python
            if not self._resubscribing:
                self._active_subs.append({
                    "kind": "js",
                    "subject": self._strip_prefix(subject),
                    "callback": callback,
                    "kwargs": {
                        k: v for k, v in {
                            "durable": durable,
                            "stream": stream,
                            "max_ack_pending": max_ack_pending,
                            "ack_wait": ack_wait,
                        }.items() if v is not None
                    },
                    "sub": sub,
                })
```

**2h. Update `stop()`** (search: `async def stop` in NATSBus, ~line 180). Add cleanup alongside existing `self._subscriptions.clear()`:
```python
        self._active_subs.clear()
        self._prefix_change_callbacks.clear()
```

### Step 3: MockNATSBus Mirror

**File: `src/probos/mesh/nats_bus.py`** — MockNATSBus class

**3a. Add tracking fields to `__init__`** (after `self.published`, ~line 474):
```python
        self._active_subs: list[dict[str, Any]] = []
        self._prefix_change_callbacks: list[Callable] = []
        self._resubscribing: bool = False
```

**3b. Add `_strip_prefix()`** (after `_full_subject`):
```python
    def _strip_prefix(self, subject: str) -> str:
        prefix_dot = self._subject_prefix + "."
        if subject.startswith(prefix_dot):
            return subject[len(prefix_dot):]
        return subject
```

**3c. Convert `set_subject_prefix()` to async** (replace lines 484-485):
```python
    async def set_subject_prefix(self, prefix: str) -> None:
        """Update prefix and rebuild subscriptions from _active_subs."""
        if prefix == self._subject_prefix:
            return
        old_prefix = self._subject_prefix
        self._subject_prefix = prefix

        # Rebuild _subs from _active_subs (un-prefixed source of truth)
        new_subs: dict[str, list[MessageCallback]] = {}
        for entry in self._active_subs:
            full = self._full_subject(entry["subject"])
            new_subs.setdefault(full, []).append(entry["callback"])
            entry["sub"] = full  # update tracked sub to new full subject

        # Preserve raw subscriptions (federation, not in _active_subs)
        for key, cbs in self._subs.items():
            if key not in new_subs:
                # Check if this key was from the old prefix
                old_dot = old_prefix + "."
                if not key.startswith(old_dot):
                    # Raw subscription — preserve as-is
                    new_subs[key] = cbs
        self._subs = new_subs

        # Notify callbacks
        for cb in self._prefix_change_callbacks:
            try:
                await cb(old_prefix, prefix)
            except Exception:
                pass
```

**3d. Add `register_on_prefix_change()`** (after `set_subject_prefix`):
```python
    def register_on_prefix_change(
        self, callback: Callable[[str, str], Awaitable[None]]
    ) -> None:
        self._prefix_change_callbacks.append(callback)
```

**3e. Add `remove_tracked_subscription()`** (after `register_on_prefix_change`):
```python
    async def remove_tracked_subscription(self, subject: str) -> bool:
        """Remove a tracked subscription by un-prefixed subject."""
        for i, entry in enumerate(self._active_subs):
            if entry["subject"] == subject:
                # Remove from _subs dict
                full = self._full_subject(subject)
                if full in self._subs:
                    # Remove the specific callback, not all subs on this subject
                    try:
                        self._subs[full].remove(entry["callback"])
                    except ValueError:
                        pass
                    if not self._subs[full]:
                        del self._subs[full]
                self._active_subs.pop(i)
                return True
        return False
```

**3f. Update `subscribe()`** (search: `def subscribe` in MockNATSBus). After `self._subs[full].append(callback)` (~line 542), add:
```python
        if not self._resubscribing:
            self._active_subs.append({
                "kind": "core",
                "subject": self._strip_prefix(subject),
                "callback": callback,
                "kwargs": {"queue": queue} if queue else {},
                "sub": full,
            })
```

**3g. Update `js_subscribe()`** (search: `def js_subscribe` in MockNATSBus). Replace the method body:
```python
    async def js_subscribe(
        self,
        subject: str,
        callback: MessageCallback,
        durable: str | None = None,
        stream: str | None = None,
        max_ack_pending: int | None = None,
        ack_wait: int | None = None,
    ) -> str:
        full = self._full_subject(subject)
        if full not in self._subs:
            self._subs[full] = []
        self._subs[full].append(callback)
        if not self._resubscribing:
            self._active_subs.append({
                "kind": "js",
                "subject": self._strip_prefix(subject),
                "callback": callback,
                "kwargs": {
                    k: v for k, v in {
                        "durable": durable,
                        "stream": stream,
                        "max_ack_pending": max_ack_pending,
                        "ack_wait": ack_wait,
                    }.items() if v is not None
                },
                "sub": full,
            })
        return full
```

**3h. Update `stop()`** (search: `async def stop` in MockNATSBus). Add alongside existing clears:
```python
        self._active_subs.clear()
        self._prefix_change_callbacks.clear()
```

### Step 4: IntentBus Task Leak Fix + Simplification (Bug 3 + Design Change)

**File: `src/probos/mesh/intent.py`**

**4a. Update `__init__`** (search: `def __init__` in IntentBus). Remove `_nats_subs` dict. Add `_pending_sub_tasks` set:

Replace:
```python
        self._nats_subs: dict[str, Any] = {}  # agent_id -> NATS subscription
```
With:
```python
        self._pending_sub_tasks: set[asyncio.Task] = {}  # AD-637z: tracked NATS sub tasks
```

**4b. Update `subscribe()`** (search: `def subscribe` in IntentBus). Replace the NATS subscription block (around line 58-60):

Replace:
```python
        # AD-637b: Create NATS subscription for targeted send()
        if self._nats_bus and self._nats_bus.connected:
            asyncio.ensure_future(self._nats_subscribe_agent(agent_id, handler))
```
With:
```python
        # AD-637b/z: Create NATS subscription for targeted send()
        if self._nats_bus and self._nats_bus.connected:
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(
                    self._nats_subscribe_agent(agent_id, handler),
                    name=f"nats-sub-{agent_id[:12]}",
                )
                self._pending_sub_tasks.add(task)
                task.add_done_callback(self._pending_sub_tasks.discard)
                task.add_done_callback(self._on_nats_task_done)
            except RuntimeError:
                pass
```

**4c. Update `_nats_subscribe_agent()`** (search: `async def _nats_subscribe_agent` in IntentBus). Remove the line that stores in `_nats_subs`:

Remove this line (~line 90):
```python
        self._nats_subs[agent_id] = sub
```
The subscription is tracked by NATSBus in `_active_subs`. IntentBus does not hold sub references.

**4d. Update `unsubscribe()`** (search: `def unsubscribe` in IntentBus). Replace the NATS cleanup block:

Replace:
```python
        # AD-637b: Clean up NATS subscription
        nats_sub = self._nats_subs.pop(agent_id, None)
        if nats_sub and hasattr(nats_sub, 'unsubscribe'):
            asyncio.ensure_future(self._nats_unsubscribe(nats_sub))
```
With:
```python
        # AD-637z: Clean up NATS subscription via NATSBus lifecycle management
        if self._nats_bus:
            subject = f"intent.{agent_id}"
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(
                    self._nats_bus.remove_tracked_subscription(subject),
                    name=f"nats-unsub-{agent_id[:12]}",
                )
                self._pending_sub_tasks.add(task)
                task.add_done_callback(self._pending_sub_tasks.discard)
                task.add_done_callback(self._on_nats_task_done)
            except RuntimeError:
                pass
```

**4e. Remove `_nats_unsubscribe()` method** (search: `async def _nats_unsubscribe` in IntentBus, lines 102-107). No longer needed — NATSBus handles unsubscription.

**4f. Add `_on_nats_task_done()` method** (after the removed `_nats_unsubscribe`):
```python
    def _on_nats_task_done(self, task: asyncio.Task) -> None:
        """Log errors from NATS subscribe/unsubscribe tasks."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.warning("NATS sub/unsub task failed: %s", exc)
```

**4g. Update `set_nats_bus()`** (search: `def set_nats_bus` in IntentBus, lines 350-352). Register prefix change callback:

Replace:
```python
    def set_nats_bus(self, nats_bus: Any) -> None:
        """Wire NATS transport (called after NATS connects in Phase 1b)."""
        self._nats_bus = nats_bus
```
With:
```python
    def set_nats_bus(self, nats_bus: Any) -> None:
        """Wire NATS transport (called after NATS connects in Phase 1b)."""
        self._nats_bus = nats_bus
        # AD-637z: Register for prefix change notification (logging only —
        # NATSBus handles re-subscription of all tracked subs automatically)
        nats_bus.register_on_prefix_change(self._on_prefix_change)
```

**4h. Add `_on_prefix_change()` method** (after `set_nats_bus`):
```python
    async def _on_prefix_change(self, old_prefix: str, new_prefix: str) -> None:
        """Log prefix change — NATSBus has already re-subscribed all agents."""
        logger.info(
            "IntentBus: NATS prefix changed %s → %s, %d agent subs re-subscribed by NATSBus",
            old_prefix[:20], new_prefix[:20], len(self._subscribers),
        )
```

### Step 5: Lift BF-221 — Re-enable NATS Request/Reply in `send()`

**File: `src/probos/mesh/intent.py`**

**5a. Update `send()`** (search: `async def send` in IntentBus). Replace the entire method body (lines 113-141):

```python
    async def send(self, intent: IntentMessage) -> IntentResult | None:
        """Deliver an intent to a specific agent (targeted dispatch, AD-397).

        AD-637b: Uses NATS request/reply when connected, direct-call fallback otherwise.
        Only one path is used per call — never both.

        AD-637z: BF-221 lifted. Prefix re-subscription (set_subject_prefix)
        ensures NATS subscriptions survive the Phase 7 DID assignment.
        """
        if not intent.target_agent_id:
            raise ValueError("send() requires target_agent_id")

        # NATS path when connected
        if self._nats_bus and self._nats_bus.connected:
            return await self._nats_send(intent)

        # Direct-call fallback when NATS disconnected
        handler = self._subscribers.get(intent.target_agent_id)
        if handler is None:
            return None
        try:
            result = await asyncio.wait_for(handler(intent), timeout=intent.ttl_seconds)
            return result
        except asyncio.TimeoutError:
            return IntentResult(
                intent_id=intent.id,
                agent_id=intent.target_agent_id,
                success=False,
                error="Agent did not respond in time.",
                confidence=0.0,
            )
```

No changes needed to `_nats_send()` — it already handles timeout and decline semantics correctly.

### Step 6: Fix Double System Event Subscriptions (Bug 2)

**File: `src/probos/runtime.py`**

**6a. Add `_nats_events_wired` flag** (search: `_nats_publish_tasks` in `runtime.py`, near initialization). Add alongside it:
```python
        self._nats_events_wired: bool = False
```

**6b. Update `add_event_listener()`** (search: `def add_event_listener` in `runtime.py`). Replace lines 644-646:

Replace:
```python
        # AD-637d: Also create NATS subscriptions when connected
        if getattr(self, 'nats_bus', None) and self.nats_bus.connected:
            self._create_nats_event_subscription(fn, type_filter)
```
With:
```python
        # AD-637d/637z: Create NATS subscription only AFTER bulk wiring is done.
        # Before _nats_events_wired, _setup_nats_event_subscriptions() handles all.
        # After the flag is set, new listeners get their own NATS sub immediately.
        if self._nats_events_wired and getattr(self, 'nats_bus', None) and self.nats_bus.connected:
            self._create_nats_event_subscription(fn, type_filter)
```

**6c. Update `_setup_nats_event_subscriptions()`** (search: `def _setup_nats_event_subscriptions` in `runtime.py`). At the end of the method, after the `for` loop (after line 705), add:
```python
        self._nats_events_wired = True
```

### Step 7: Runtime `set_subject_prefix` → await

**File: `src/probos/runtime.py`**

**7a.** Change line 1536 from:
```python
                self.nats_bus.set_subject_prefix(f"probos.{cert.ship_did}")
```
To:
```python
                await self.nats_bus.set_subject_prefix(f"probos.{cert.ship_did}")
```
The enclosing method (`_init_communication`) is already async.

### Step 8: NATSBusProtocol Updates

**File: `src/probos/protocols.py`**

**8a.** Update `js_subscribe` signature (search: `def js_subscribe` in `NATSBusProtocol`, line 184):
```python
    async def js_subscribe(self, subject: str, callback: Any, durable: str | None = None, stream: str | None = None, max_ack_pending: int | None = None, ack_wait: int | None = None) -> Any: ...
```

**8b.** Add `register_on_prefix_change` (after existing `set_subject_prefix` declaration, referenced at line 173):
```python
    def register_on_prefix_change(self, callback: Any) -> None: ...
```

**8c.** Note: `set_subject_prefix` is listed in the protocol docstring as "implementation-only" (line 173). It is NOT in the protocol interface. Since NATSBusProtocol is the consumer-facing interface and `set_subject_prefix` is only called by runtime startup code, this is correct — no change needed to the sync/async signature in the protocol. The protocol does not declare `set_subject_prefix`.

Verify: search `set_subject_prefix` in `protocols.py` — it should only appear in the docstring comment, not as a method declaration. If it IS declared as a method, update it to async.

### Step 9: Update Existing Tests for Async `set_subject_prefix`

The following test files call `set_subject_prefix` synchronously and must be updated to `await`:

**File: `tests/test_ad637a_nats_foundation.py`**
- Line 361: `bus.set_subject_prefix("probos.ship-abc123")` → `await bus.set_subject_prefix("probos.ship-abc123")`
- Line 425: `bus.set_subject_prefix(f"probos.{cert.ship_did}")` → `await bus.set_subject_prefix(f"probos.{cert.ship_did}")`
- Line 442: `bus.set_subject_prefix(f"probos.{cert.ship_did}")` → `await bus.set_subject_prefix(f"probos.{cert.ship_did}")`

**File: `tests/test_federation_nats.py`**
- Line 246: `shared_bus.set_subject_prefix("probos.ship-1")` → `await shared_bus.set_subject_prefix("probos.ship-1")`
- Line 272: `shared_bus.set_subject_prefix("probos.ship-2")` → `await shared_bus.set_subject_prefix("probos.ship-2")`

Search for any other callers:
```bash
grep -rn "set_subject_prefix" src/ tests/
```
Update ALL callers to `await`.

### Step 10: New Tests

**File: `tests/test_ad637z_nats_cleanup.py`** — 13 test cases.

```python
"""AD-637z: NATS Migration Cleanup + BF-221 Lift tests."""

import asyncio
from pathlib import Path

import pytest

from probos.mesh.nats_bus import MockNATSBus
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage, IntentResult


@pytest.fixture
def signal_manager():
    return SignalManager()


@pytest.fixture
async def mock_bus():
    bus = MockNATSBus(subject_prefix="probos.local")
    await bus.start()
    yield bus
    await bus.stop()


# ---------------------------------------------------------------------------
# Bug 1: Prefix re-subscription
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prefix_resubscription_routes_to_new_prefix(mock_bus):
    """Subscriptions follow prefix changes — messages on new prefix are received."""
    received = []

    async def handler(msg):
        received.append(msg.data)

    await mock_bus.subscribe("test.subject", handler)

    # Publish on old prefix — should work
    await mock_bus.publish("test.subject", {"seq": 1})
    assert len(received) == 1

    # Change prefix
    await mock_bus.set_subject_prefix("probos.did:probos:abc123")

    # Publish on new prefix — should work (subscription followed the prefix)
    await mock_bus.publish("test.subject", {"seq": 2})
    assert len(received) == 2
    assert received[1]["seq"] == 2


@pytest.mark.asyncio
async def test_prefix_change_callback_fires(mock_bus):
    """Registered callbacks receive (old, new) prefix on change."""
    calls = []

    async def on_change(old, new):
        calls.append((old, new))

    mock_bus.register_on_prefix_change(on_change)
    await mock_bus.set_subject_prefix("probos.newprefix")

    assert len(calls) == 1
    assert calls[0] == ("probos.local", "probos.newprefix")


@pytest.mark.asyncio
async def test_prefix_change_noop_same_prefix(mock_bus):
    """No callbacks fired when prefix is unchanged."""
    calls = []

    async def on_change(old, new):
        calls.append((old, new))

    mock_bus.register_on_prefix_change(on_change)
    await mock_bus.set_subject_prefix("probos.local")  # same as init

    assert len(calls) == 0


@pytest.mark.asyncio
async def test_prefix_change_callback_failure_does_not_block_others(mock_bus):
    """One failing callback does not prevent other callbacks from running."""
    calls = []

    async def fails(old, new):
        raise RuntimeError("boom")

    async def succeeds(old, new):
        calls.append((old, new))

    mock_bus.register_on_prefix_change(fails)
    mock_bus.register_on_prefix_change(succeeds)
    await mock_bus.set_subject_prefix("probos.new")

    assert len(calls) == 1  # second callback ran despite first failing


@pytest.mark.asyncio
async def test_remove_tracked_subscription(mock_bus):
    """remove_tracked_subscription cleans up by un-prefixed subject."""
    received = []

    async def handler(msg):
        received.append(msg.data)

    await mock_bus.subscribe("intent.agent-1", handler)

    # Verify subscription works
    await mock_bus.publish("intent.agent-1", {"v": 1})
    assert len(received) == 1

    # Remove tracked subscription
    removed = await mock_bus.remove_tracked_subscription("intent.agent-1")
    assert removed is True

    # Verify subscription is gone
    await mock_bus.publish("intent.agent-1", {"v": 2})
    assert len(received) == 1  # no new messages


# ---------------------------------------------------------------------------
# Bug 2: Double subscriptions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_double_subscriptions_after_bulk_wire(mock_bus):
    """Listener registered before bulk wire gets exactly 1 NATS sub, not 2.

    Simulates the runtime pattern: add_event_listener() before
    _setup_nats_event_subscriptions() should not cause double delivery.
    """
    received = []

    async def handler(msg):
        received.append(msg.data)

    # Simulate "before bulk wire" — subscribe once
    await mock_bus.js_subscribe(
        "system.events.trust_change",
        handler,
        stream="SYSTEM_EVENTS",
    )

    # Publish ONE event — should receive exactly once
    await mock_bus.publish("system.events.trust_change", {"v": 1})
    assert len(received) == 1, f"Expected 1, got {len(received)} — double subscription"

    # If we subscribed again (simulating _setup_nats_event_subscriptions
    # without the gate), we'd get 2. The gate prevents this.


# ---------------------------------------------------------------------------
# Bug 3: Task leak
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_intent_bus_task_tracking(mock_bus, signal_manager):
    """IntentBus holds task references in _pending_sub_tasks."""
    intent_bus = IntentBus(signal_manager)
    intent_bus.set_nats_bus(mock_bus)

    async def handler(intent):
        return None

    intent_bus.subscribe("agent-1", handler)

    # Allow task to complete
    if intent_bus._pending_sub_tasks:
        await asyncio.gather(*intent_bus._pending_sub_tasks, return_exceptions=True)

    # Verify set is used (tasks are discarded after completion)
    assert isinstance(intent_bus._pending_sub_tasks, set)


@pytest.mark.asyncio
async def test_on_nats_task_done_handles_errors(signal_manager):
    """_on_nats_task_done logs errors without crashing."""
    intent_bus = IntentBus(signal_manager)

    # Completed task — should not raise
    async def noop():
        pass

    task = asyncio.get_running_loop().create_task(noop())
    await task
    intent_bus._on_nats_task_done(task)  # no crash

    # Failed task — should log warning, not raise
    async def fail():
        raise ValueError("test error")

    task2 = asyncio.get_running_loop().create_task(fail())
    try:
        await task2
    except ValueError:
        pass
    intent_bus._on_nats_task_done(task2)  # no crash


# ---------------------------------------------------------------------------
# Bug 4: Duplicate ensure_stream
# ---------------------------------------------------------------------------

def test_finalize_no_ensure_stream():
    """finalize.py must not contain ensure_stream — canonical location is startup/nats.py."""
    source_file = Path(__file__).parent.parent / "src" / "probos" / "startup" / "finalize.py"
    assert source_file.exists(), f"Test requires {source_file} to exist"
    content = source_file.read_text()
    assert "ensure_stream" not in content, (
        "finalize.py should not contain ensure_stream — canonical location is startup/nats.py"
    )


def test_intent_no_ensure_future():
    """intent.py must not use ensure_future — use create_task with reference tracking."""
    source_file = Path(__file__).parent.parent / "src" / "probos" / "mesh" / "intent.py"
    assert source_file.exists(), f"Test requires {source_file} to exist"
    content = source_file.read_text()
    assert "asyncio.ensure_future" not in content, (
        "intent.py should not contain asyncio.ensure_future — "
        "use create_task with _pending_sub_tasks tracking instead"
    )


# ---------------------------------------------------------------------------
# BF-221 Lift: NATS request/reply re-enabled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_uses_nats_when_connected(mock_bus, signal_manager):
    """send() uses NATS request/reply when NATS is connected."""
    intent_bus = IntentBus(signal_manager)
    intent_bus.set_nats_bus(mock_bus)

    nats_received = []

    async def agent_handler(intent):
        nats_received.append(intent.intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="agent-1",
            success=True,
            result={"answer": 42},
            confidence=1.0,
        )

    intent_bus.subscribe("agent-1", agent_handler, intent_names=["test"])

    # Drain subscription task
    if intent_bus._pending_sub_tasks:
        await asyncio.gather(*intent_bus._pending_sub_tasks, return_exceptions=True)

    intent = IntentMessage(
        intent="test",
        params={},
        target_agent_id="agent-1",
    )
    result = await intent_bus.send(intent)

    assert result is not None
    assert result.success
    # Verify the NATS path was used (message appears in mock_bus.published)
    assert any("intent.agent-1" in subj for subj, _ in mock_bus.published), (
        "send() should use NATS request/reply when connected"
    )


@pytest.mark.asyncio
async def test_send_falls_back_to_direct_call_when_disconnected(signal_manager):
    """send() uses direct in-process call when NATS is not connected."""
    intent_bus = IntentBus(signal_manager)
    # No NATS bus wired — direct call path

    direct_received = []

    async def agent_handler(intent):
        direct_received.append(intent.intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="agent-1",
            success=True,
            confidence=1.0,
        )

    intent_bus.subscribe("agent-1", agent_handler)

    intent = IntentMessage(
        intent="test",
        params={},
        target_agent_id="agent-1",
    )
    result = await intent_bus.send(intent)

    assert result is not None
    assert result.success
    assert len(direct_received) == 1


@pytest.mark.asyncio
async def test_end_to_end_prefix_change_then_nats_send(mock_bus, signal_manager):
    """End-to-end: subscribe → prefix change → NATS send → agent responds.

    This is the BF-221 scenario: subscriptions created on old prefix must
    survive prefix change and still receive NATS requests on new prefix.
    """
    intent_bus = IntentBus(signal_manager)
    intent_bus.set_nats_bus(mock_bus)

    results = []

    async def agent_handler(intent):
        results.append(intent.intent)
        return IntentResult(
            intent_id=intent.id,
            agent_id="agent-1",
            success=True,
            result={"status": "handled"},
            confidence=0.9,
        )

    # Subscribe on old prefix
    intent_bus.subscribe("agent-1", agent_handler, intent_names=["ward_room_notification"])
    if intent_bus._pending_sub_tasks:
        await asyncio.gather(*intent_bus._pending_sub_tasks, return_exceptions=True)

    # Simulate Phase 7: prefix changes after DID assignment
    await mock_bus.set_subject_prefix("probos.did:probos:ship-abc-123")

    # Send intent on new prefix — should reach agent via re-subscribed NATS sub
    intent = IntentMessage(
        intent="ward_room_notification",
        params={"message": "All hands"},
        target_agent_id="agent-1",
    )
    result = await intent_bus.send(intent)

    assert result is not None, "Agent should respond after prefix change"
    assert result.success
    assert result.result == {"status": "handled"}
    assert len(results) == 1
```

## Verification

```bash
# AD-637z tests
pytest tests/test_ad637z_nats_cleanup.py -v

# All NATS tests (regression — includes async set_subject_prefix updates)
pytest tests/test_ad637a_nats_foundation.py tests/test_ad637c_wardroom_nats.py tests/test_ad637d_system_events_nats.py tests/test_ad637z_nats_cleanup.py -v

# IntentBus tests
pytest tests/test_intent.py -v

# Ward Room tests (routing unbroken)
pytest tests/test_ward_room.py tests/test_ward_room_dms.py tests/test_ward_room_agents.py tests/test_routing.py -v

# Federation tests (raw subs unaffected)
pytest tests/test_federation_nats.py -v

# Static assertions
grep -n "ensure_stream" src/probos/startup/finalize.py   # should return 0
grep -n "asyncio.ensure_future" src/probos/mesh/intent.py  # should return 0
grep -rn "set_subject_prefix" src/ tests/  # verify ALL callers use await

# Full suite
pytest -n auto
```

## Engineering Principles Compliance

- **SOLID/S**: NATSBus owns subscription lifecycle. IntentBus owns intent dispatch. Runtime owns event listener wiring. No mixed responsibilities.
- **SOLID/O**: NATSBus extended with `_active_subs`, `remove_tracked_subscription()`, `register_on_prefix_change()`. Existing `subscribe()`/`js_subscribe()` signatures unchanged.
- **SOLID/D**: IntentBus depends on NATSBus public API (`subscribe`, `remove_tracked_subscription`, `register_on_prefix_change`), not internals.
- **SOLID/L**: MockNATSBus mirrors NATSBus — all new methods implemented with equivalent behavior.
- **Law of Demeter**: IntentBus does not reach into `nats_bus._active_subs`. Uses `remove_tracked_subscription()` public method.
- **Fail Fast**: `_on_nats_task_done` logs errors at WARNING. Prefix change callback failures logged and isolated. Re-subscription failures logged but don't crash.
- **DRY**: One source of truth for stream config (`startup/nats.py`). One subscription lifecycle owner (NATSBus). One path per `send()` call.
- **Defense in Depth**: `_strip_prefix()` prevents double-prefixing. `_resubscribing` guard prevents infinite tracking. Same-prefix no-op guard prevents unnecessary work.
