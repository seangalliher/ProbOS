# BF-241: NATS JetStream Reconnect Resilience

**Status:** Ready for builder  
**Priority:** Medium  
**Phase:** Bug Fix  
**Related:** BF-229 (subject sanitization), BF-230 (publish retry), BF-231 (stale streams), BF-232 (recreate_stream), AD-637 (NATS migration)  
**Symptom:** After ~13 hours of stable operation, all JetStream publishes fail with "nats: no response from stream" and fall back to core NATS. Persists until ProbOS restart.

---

## Root Cause

`NATSBus._reconnected_cb` (nats_bus.py, line 285) only sets `self._connected = True` and logs. It does **not**:

1. Verify that JetStream streams still exist on the server
2. Recreate streams if they're missing
3. Re-establish JetStream consumer subscriptions

When the NATS server restarts mid-session (crash, manual restart, Windows update, resource limits), JetStream state can be lost even with file-backed storage (data dir wipe, `--jetstream` flag missing on restart, server replacement). The nats-py client auto-reconnects and auto-resubscribes core NATS subscriptions (nats-py `_attempt_reconnect` replays `self._subs`), but JetStream streams and durable consumers exist on the **server**, not the client — the client must explicitly recreate them.

The existing `set_subject_prefix()` method (line 126) already has the full stream-recreation + consumer-resubscription logic for prefix changes. The reconnect handler must perform the same recovery.

## Prior Art (What Already Works)

- **BF-232:** `recreate_stream()` (line 626) — delete-then-create pattern for streams
- **BF-223:** Consumer deletion before re-subscribe on prefix change (lines 201-217)
- **BF-230:** `js_publish()` retry + fallback (line 440) — masks the problem but doesn't fix it
- **set_subject_prefix()** (line 126) — full stream + consumer + subscription re-creation; the template for the reconnect handler
- **_resubscribing flag** (line 114) — prevents double-tracking in `_active_subs` during re-subscription

## Engineering Principles

- **Fail Fast (log-and-degrade):** Log stream recreation failures at ERROR. Continue with remaining streams — partial JetStream is better than none. `js_publish()` BF-230 fallback already provides degraded-mode resilience.
- **Defense in Depth:** File-backed streams are the primary defense (survive server restart). Reconnect recreation is the secondary defense (survive state loss). BF-230 publish fallback is the tertiary defense (event delivery via core NATS).
- **DRY:** Extract the stream-recreation + consumer-resubscription logic into a reusable `_recover_jetstream()` method called by both `set_subject_prefix()` and `_reconnected_cb`. Do not duplicate the loop.
- **Single Responsibility:** `_recover_jetstream()` handles JetStream recovery. `_on_reconnected()` dispatches to it. `set_subject_prefix()` handles prefix change then dispatches to it. Reconnect logic is extracted from a nested closure into a testable instance method.
- **Async Hygiene:** `CancelledError` must propagate — swallowing it during shutdown-coinciding-with-reconnect would silently kill the callback.
- **Cloud-Ready Storage:** No change to storage abstraction — NATS is infrastructure, not business-logic storage.

---

## Implementation

### Step 1: Extract `_recover_jetstream()` from `set_subject_prefix()`

**File:** `src/probos/mesh/nats_bus.py`

Create a new private method `_recover_jetstream()` that contains the stream-recreation and consumer-resubscription logic currently inline in `set_subject_prefix()` (lines 157-223).

```python
async def _recover_jetstream(self, *, reason: str = "reconnect") -> None:
    """Recreate JetStream streams and re-subscribe consumers.

    Called on NATS reconnection (BF-241) and subject prefix change (BF-232).
    Streams are recreated via delete-then-create to handle stale server state.
    Consumer subscriptions are re-established from _active_subs tracking.

    Processing order: all JS streams first, then all JS consumers. Subscription
    processing order changes from the prior interleaved order in
    set_subject_prefix() to js-first, core-second. No test depends on the
    prior order.

    Tolerates mid-flight disconnects — each stream/consumer operation has its
    own try/except, so partial recovery is acceptable. Concurrent js_publish()
    calls during recovery will fail and use BF-230 fallback; no lock is added
    to avoid serializing and starving publishers.

    Stale entry["sub"] references from prior failed recoveries are handled
    gracefully — the unsubscribe will fail (already-invalid handle) and
    continue to the re-subscribe attempt.

    Failures are logged at ERROR but do not propagate — partial JetStream
    is better than none, and BF-230 fallback provides degraded delivery.
    """
    if not self._js:
        logger.debug("BF-241: _recover_jetstream skipped (JetStream disabled)")
        return

    # --- Phase 1: Recreate streams ---
    if self._stream_configs:
        logger.info(
            "BF-241: Recovering %d JetStream streams (reason=%s)",
            len(self._stream_configs), reason,
        )
        for sc in self._stream_configs:
            stream_name = sc["name"]
            try:
                await self.recreate_stream(
                    stream_name,
                    sc["subjects"],
                    max_msgs=sc.get("max_msgs", -1),
                    max_age=sc.get("max_age", 0),
                )
            except Exception as e:
                logger.error(
                    "BF-241: Stream recreate failed for %s (reason=%s): %s — "
                    "JetStream publishes to this stream will use BF-230 fallback.",
                    stream_name, reason, e,
                )

    # --- Phase 2: Re-subscribe JetStream consumers ---
    js_entries = [e for e in self._active_subs if e["kind"] == "js"]
    if js_entries:
        logger.info(
            "BF-241: Re-subscribing %d JetStream consumers (reason=%s)",
            len(js_entries), reason,
        )
        self._resubscribing = True
        try:
            for entry in js_entries:
                old_sub = entry["sub"]
                if old_sub is not None:
                    try:
                        await old_sub.unsubscribe()
                    except Exception as e:
                        logger.debug("BF-241: Unsubscribe stale consumer: %s", e)

                # BF-223: Delete stale durable consumer before re-subscribe
                durable_name = entry["kwargs"].get("durable")
                stream_name = entry["kwargs"].get("stream")
                if durable_name and stream_name:
                    try:
                        await self.delete_consumer(stream_name, durable_name)
                        logger.debug(
                            "BF-241: Deleted stale consumer %s/%s before re-subscribe",
                            stream_name, durable_name,
                        )
                    except Exception as e:
                        logger.debug(
                            "BF-241: Consumer delete before re-subscribe: %s", e
                        )

                try:
                    new_sub = await self.js_subscribe(
                        entry["subject"], entry["callback"], **entry["kwargs"]
                    )
                    entry["sub"] = new_sub
                except Exception as e:
                    logger.error(
                        "BF-241: Consumer re-subscribe failed for %s (reason=%s): %s",
                        entry["subject"], reason, e,
                    )
        finally:
            self._resubscribing = False
```

**Place this method** after `_full_subject()` (line 272) and before `start()` (line 274). It must be an instance method of `NATSBus`.

### Step 2: Update `set_subject_prefix()` to call `_recover_jetstream()`

**File:** `src/probos/mesh/nats_bus.py`

Replace the inline stream-recreation loop (lines 157-177) and consumer-resubscription loop (lines 184-223) with a single call:

```python
if self.connected:
    await self._recover_jetstream(reason="prefix_change")
else:
    logger.warning(
        "set_subject_prefix: skipping JetStream recovery (not connected)"
    )
```

**Keep** the core NATS re-subscription loop (lines 184-223 handles both `core` and `js` entries — after extraction, `set_subject_prefix()` should still re-subscribe `core` entries itself). The extracted `_recover_jetstream()` only handles `js` entries. Core NATS re-subscription stays in `set_subject_prefix()` because core subs need the old-sub unsubscribe + new-sub creation with the new prefix, and this only applies on prefix change, not on reconnect (nats-py handles core resubscription on reconnect automatically).

**Revised `set_subject_prefix()` structure after refactor:**

**Note:** Subscription processing order changes from interleaved (mixed core+js in one loop) to js-first (via `_recover_jetstream`), then core-second. No test depends on the prior order.

```python
async def set_subject_prefix(self, prefix: str) -> None:
    # ... sanitization, early return if unchanged, prefix swap (unchanged) ...

    if self.connected:
        # BF-241: Reuse shared recovery for streams + JS consumers
        await self._recover_jetstream(reason="prefix_change")

        # Core NATS re-subscription (not handled by _recover_jetstream —
        # nats-py auto-resubscribes core subs on reconnect but not on
        # prefix change, so this is prefix-change-only logic)
        core_entries = [e for e in self._active_subs if e["kind"] == "core"]
        if core_entries:
            for entry in core_entries:
                old_sub = entry["sub"]
                if old_sub is not None:
                    try:
                        await old_sub.unsubscribe()
                    except Exception as e:
                        logger.debug("Unsubscribe during prefix change: %s", e)
                new_sub = await self.subscribe(
                    entry["subject"], entry["callback"], **entry["kwargs"]
                )
                entry["sub"] = new_sub
    else:
        logger.warning(
            "set_subject_prefix: skipping recovery (not connected)"
        )
```

### Step 3: Extract `_reconnected_cb` closure to instance method `_on_reconnected`

**File:** `src/probos/mesh/nats_bus.py`

The current `_reconnected_cb` is a **nested closure** defined inside `start()` at line 285 and passed to `nats.connect()` at line 303. Closures hide testable surface area — extract to an instance method so tests can invoke it directly.

**Add new instance method** to `NATSBus` (place after `_recover_jetstream`, before `start()`):

```python
async def _on_reconnected(self) -> None:
    """BF-241: Reconnect callback — restore JetStream state.

    Extracted from the nested closure in start() so it can be tested
    directly. nats-py auto-resubscribes core NATS subscriptions on
    reconnect, but JetStream streams and consumers must be explicitly
    recreated.
    """
    self._connected = True
    logger.info("NATS reconnected to %s", self._nc.connected_url)
    if self._js:
        try:
            await self._recover_jetstream(reason="reconnect")
        except asyncio.CancelledError:
            raise  # propagate — shutdown in progress
        except Exception as e:
            logger.error(
                "BF-241: JetStream recovery on reconnect failed: %s — "
                "JetStream publishes will use BF-230 fallback until next "
                "reconnect or restart.",
                e,
            )
```

**Update `start()`** — replace the nested `_reconnected_cb` definition (lines 285-287):

```python
# BEFORE (delete these lines):
async def _reconnected_cb() -> None:
    self._connected = True
    logger.info("NATS reconnected to %s", self._nc.connected_url)
```

And update the `nats.connect()` call (line 303) to reference the instance method:

```python
# BEFORE:
reconnected_cb=_reconnected_cb,

# AFTER:
reconnected_cb=self._on_reconnected,
```

**Note:** `asyncio` must be imported at module level (it already is — verify). The `CancelledError` carve-out ensures shutdown-coinciding-with-reconnect propagates correctly instead of being swallowed by the broad `except Exception`.

### Step 4: MockNATSBus parity

**File:** `src/probos/mesh/nats_bus.py`

`MockNATSBus` (line 774) is the test double. It does not have a real NATS connection, so no reconnect scenario exists. Add a no-op `_recover_jetstream()` for interface parity:

```python
async def _recover_jetstream(self, *, reason: str = "reconnect") -> None:
    """No-op for mock bus — no server-side state to recover."""
    pass
```

Place after `set_subject_prefix()` (line 802) in the `MockNATSBus` class.

---

## Tests

**File:** `tests/test_bf241_nats_reconnect_resilience.py`

All tests use `MockNATSBus` or mock `NATSBus` — no real NATS server required.

### Test 1: `_recover_jetstream` recreates all tracked streams

```python
async def test_recover_jetstream_recreates_streams():
    """Verify _recover_jetstream calls recreate_stream for each tracked config."""
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._subject_prefix = "probos.test"
    bus._js = True  # Truthy — not None
    bus._connected = True
    bus._resubscribing = False
    bus._active_subs = []
    bus._stream_configs = [
        {"name": "SYSTEM_EVENTS", "subjects": ["system.events.>"], "max_msgs": 50000, "max_age": 3600},
        {"name": "WARDROOM", "subjects": ["wardroom.events.>"], "max_msgs": 10000, "max_age": 3600},
    ]

    recreated = []
    async def mock_recreate(name, subjects, max_msgs=-1, max_age=0):
        recreated.append({"name": name, "subjects": subjects, "max_msgs": max_msgs, "max_age": max_age})

    bus.recreate_stream = mock_recreate
    await bus._recover_jetstream(reason="test")

    assert len(recreated) == 2
    assert recreated[0]["name"] == "SYSTEM_EVENTS"
    assert recreated[1]["name"] == "WARDROOM"
```

### Test 2: `_recover_jetstream` re-subscribes JetStream consumers

```python
async def test_recover_jetstream_resubscribes_consumers():
    """Verify JS consumer entries in _active_subs are re-subscribed."""
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._subject_prefix = "probos.test"
    bus._js = True
    bus._connected = True
    bus._resubscribing = False
    bus._stream_configs = []

    callback = lambda msg: None
    bus._active_subs = [
        {
            "kind": "js",
            "subject": "wardroom.events.>",
            "callback": callback,
            "kwargs": {"durable": "wardroom-router", "stream": "WARDROOM"},
            "sub": None,
        },
        {
            "kind": "core",  # Should NOT be re-subscribed by _recover_jetstream
            "subject": "system.ping",
            "callback": callback,
            "kwargs": {},
            "sub": None,
        },
    ]

    js_resubscribed = []
    async def mock_js_subscribe(subject, cb, **kwargs):
        js_resubscribed.append(subject)
        return "mock_sub"

    deleted_consumers = []
    async def mock_delete_consumer(stream, durable):
        deleted_consumers.append((stream, durable))

    bus.js_subscribe = mock_js_subscribe
    bus.delete_consumer = mock_delete_consumer
    await bus._recover_jetstream(reason="test")

    # Only JS entry re-subscribed, not core
    assert len(js_resubscribed) == 1
    assert js_resubscribed[0] == "wardroom.events.>"
    # Stale consumer deleted before re-subscribe (BF-223 pattern)
    assert ("WARDROOM", "wardroom-router") in deleted_consumers
    # Sub reference updated (critical — stale ref breaks next recovery cycle)
    assert bus._active_subs[0]["sub"] == "mock_sub"
```

### Test 3: `_recover_jetstream` skips if no `_js` context

```python
async def test_recover_jetstream_skips_without_js():
    """Verify _recover_jetstream returns early when _js is None (JetStream disabled)."""
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._subject_prefix = "probos.test"
    bus._js = None  # JetStream not initialized
    bus._connected = True
    bus._resubscribing = False
    bus._stream_configs = [
        {"name": "SYSTEM_EVENTS", "subjects": ["system.events.>"], "max_msgs": 50000, "max_age": 3600},
    ]
    bus._active_subs = []

    recreated = []
    async def mock_recreate(name, subjects, max_msgs=-1, max_age=0):
        recreated.append(name)

    bus.recreate_stream = mock_recreate
    await bus._recover_jetstream(reason="test")

    # Early return guard means mock was never called
    assert len(recreated) == 0
```

### Test 4: `_on_reconnected` triggers `_recover_jetstream`

```python
async def test_on_reconnected_triggers_recovery():
    """Verify the _on_reconnected instance method invokes JetStream recovery."""
    from unittest.mock import MagicMock
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._subject_prefix = "probos.test"
    bus._js = True
    bus._connected = False
    bus._resubscribing = False
    bus._stream_configs = []
    bus._active_subs = []
    bus._nc = MagicMock()
    bus._nc.connected_url = "nats://localhost:4222"

    recovery_calls = []
    async def mock_recover(*, reason="reconnect"):
        recovery_calls.append(reason)
    bus._recover_jetstream = mock_recover

    await bus._on_reconnected()

    assert bus._connected is True
    assert "reconnect" in recovery_calls
```

### Test 5: Stream recreation failure does not abort consumer re-subscription

```python
import logging

async def test_recover_jetstream_partial_failure(caplog):
    """Stream failure must not prevent consumer re-subscription (fail-fast: log-and-degrade)."""
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._subject_prefix = "probos.test"
    bus._js = True
    bus._connected = True
    bus._resubscribing = False
    bus._stream_configs = [
        {"name": "BROKEN_STREAM", "subjects": ["broken.>"], "max_msgs": 100, "max_age": 60},
    ]

    callback = lambda msg: None
    bus._active_subs = [
        {
            "kind": "js",
            "subject": "wardroom.events.>",
            "callback": callback,
            "kwargs": {"durable": "test-consumer", "stream": "WARDROOM"},
            "sub": None,
        },
    ]

    async def mock_recreate_fails(name, subjects, max_msgs=-1, max_age=0):
        raise Exception("Server unavailable")

    js_resubscribed = []
    async def mock_js_subscribe(subject, cb, **kwargs):
        js_resubscribed.append(subject)
        return "mock_sub"

    async def mock_delete_consumer(stream, durable):
        pass

    bus.recreate_stream = mock_recreate_fails
    bus.js_subscribe = mock_js_subscribe
    bus.delete_consumer = mock_delete_consumer

    # Should not raise despite stream failure
    with caplog.at_level(logging.ERROR):
        await bus._recover_jetstream(reason="test")

    # Consumer re-subscription still happened
    assert len(js_resubscribed) == 1
    # Stream failure was logged at ERROR (log-and-degrade contract)
    assert any("BF-241: Stream recreate failed" in r.message for r in caplog.records)
```

### Test 6: `_resubscribing` flag prevents double-tracking

```python
async def test_recover_jetstream_resubscribing_flag():
    """Verify _resubscribing is True during consumer re-subscription and reset after."""
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._subject_prefix = "probos.test"
    bus._js = True
    bus._connected = True
    bus._resubscribing = False
    bus._stream_configs = []

    flag_during_subscribe = []
    callback = lambda msg: None
    bus._active_subs = [
        {
            "kind": "js",
            "subject": "test.>",
            "callback": callback,
            "kwargs": {"durable": "test-dur", "stream": "TEST"},
            "sub": None,
        },
    ]

    async def mock_js_subscribe(subject, cb, **kwargs):
        flag_during_subscribe.append(bus._resubscribing)
        return "mock_sub"

    async def mock_delete_consumer(stream, durable):
        pass

    bus.js_subscribe = mock_js_subscribe
    bus.delete_consumer = mock_delete_consumer
    await bus._recover_jetstream(reason="test")

    # Flag was True during subscribe call
    assert flag_during_subscribe == [True]
    # Flag reset after
    assert bus._resubscribing is False
```

### Test 7: MockNATSBus has `_recover_jetstream` (interface parity)

```python
async def test_mock_bus_has_recover_jetstream():
    """MockNATSBus must have _recover_jetstream for interface parity."""
    from probos.mesh.nats_bus import MockNATSBus

    bus = MockNATSBus()
    # Should not raise
    await bus._recover_jetstream(reason="test")
```

### Test 8: `set_subject_prefix` uses `_recover_jetstream` (DRY)

```python
async def test_set_subject_prefix_calls_recover_jetstream():
    """Verify set_subject_prefix delegates to _recover_jetstream (DRY: BF-241)."""
    from probos.mesh.nats_bus import NATSBus

    bus = NATSBus.__new__(NATSBus)
    bus._subject_prefix = "probos.old"
    bus._js = True
    bus._connected = True
    bus._resubscribing = False
    bus._stream_configs = []
    bus._active_subs = []
    bus._subscriptions = []
    bus._prefix_change_callbacks = []

    recovery_calls = []
    async def mock_recover(*, reason="reconnect"):
        recovery_calls.append(reason)
    bus._recover_jetstream = mock_recover

    await bus.set_subject_prefix("probos.new")

    assert "prefix_change" in recovery_calls
    assert bus._subject_prefix == "probos.new"
```

---

## Tracker Updates

### PROGRESS.md

Add under current bug fixes:

```
| BF-241 | NATS JetStream reconnect resilience | Medium | Closed |
```

### docs/development/roadmap.md

Add to Bug Tracker table:

```
| BF-241 | **NATS JetStream reconnect resilience.** After NATS server restart mid-session, `_reconnected_cb` only sets `connected=True` — does not recreate streams or re-subscribe JetStream consumers. All `js_publish()` calls fail with "no response from stream" until ProbOS restart. **Fix:** Extract `_recover_jetstream()` from `set_subject_prefix()` (DRY). Call from `_reconnected_cb`. Recreates streams via `recreate_stream()` (BF-232 pattern), deletes stale consumers (BF-223 pattern), re-subscribes from `_active_subs` tracking. Log-and-degrade on partial failure. Completes NATS resilience stack: BF-229 (prefix) → BF-230 (publish retry) → BF-231 (stale streams) → BF-232 (recreate) → BF-241 (reconnect). 8 new tests. | Medium | **Closed** |
```

### DECISIONS.md

```
## BF-241: NATS JetStream Reconnect Resilience

**Context:** After ~13 hours of stable operation, all JetStream publishes failed with "no response from stream." Root cause: NATS server restarted, losing JetStream state. `_reconnected_cb` restored `connected=True` but did not recreate streams or consumers. The `set_subject_prefix()` method already contained the full recovery logic for prefix changes.

**Decision:** Extract `_recover_jetstream()` as shared method called by both `set_subject_prefix()` and `_reconnected_cb`. File-backed storage (NATS default) is primary defense; reconnect recreation is secondary defense; BF-230 publish fallback is tertiary defense.

**Consequences:** Three-layer defense-in-depth for JetStream continuity. DRY extraction eliminates divergence risk between prefix-change and reconnect recovery paths. No new config — uses existing `_stream_configs` and `_active_subs` tracking.
```
