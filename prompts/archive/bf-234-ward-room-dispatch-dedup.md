# BF-234: Duplicate Ward Room Responses — Consumer-Side Dedup Gate

**Status:** Ready for builder
**Priority:** Medium
**Files:** `src/probos/mesh/intent.py`, `src/probos/startup/finalize.py`, `tests/test_bf234_ward_room_dispatch_dedup.py`

## Problem

When the Captain posts a new All Hands thread, some agents (observed: 4 of 12) post duplicate responses within milliseconds. Duplicate content varies slightly (different LLM runs) or is identical, confirming two independent handler executions with the same prompt context.

**Observed:**
```
Nova: "Standing ready..." (post 1)
Nova: "Standing ready..." (post 2, ~50ms later)
Keiko: "Acknowledged..." (identical duplicate)
Sage: "Understood..." (identical duplicate)
Lyra: "Ready to assist..." (identical duplicate)
```

Agents that responded faster (Anvil, Wesley, Sentinel, Ezri) did not duplicate — their pipeline completed before a second dispatch could arrive.

## Root Cause

Exhaustive code-path analysis confirmed every application-level routing path dispatches exactly once per agent per event. The duplicate originates at the NATS transport layer — either JetStream redelivery edge case, or `js_publish` timeout-then-succeed producing two messages on the INTENT_DISPATCH stream (BF-230 retry: if attempt 0 times out on client but succeeds on server, attempt 1 publishes a second copy with identical payload including `intent.id`).

Only 4 of 12 agents duplicated because their pipeline was slower (LLM chain still running when the second copy arrived). Faster agents completed and ack'd before redelivery. This subset pattern can only be explained by per-agent consumer timing — the router dispatches identically to all agents.

The application lacks defense-in-depth at the consumer layer:

1. **`_on_dispatch()` in `intent.py:159` has no dedup** — it deserializes, records response, and enqueues every message regardless of whether the same `intent.id` was already processed.

2. **`has_agent_responded()` is dead code in the routing path** — `ward_room_router.py:95` implements the check, `record_agent_response()` at line 89 writes the tracker, but `has_agent_responded()` is never called during routing or dispatch. It is only used in `proactive.py` (3 call sites) for proactive-loop dedup. BF-198 stays semantic ("already spoken in this round") — it is NOT the right mechanism for transport-layer dedup.

## What This Does NOT Change

- `ward_room_router.py` — no changes. Router dispatches exactly once; the duplication happens after dispatch.
- `ward_room_pipeline.py` — no changes. Post-boundary defense is a separate concern (BF-236 if needed).
- `proactive.py` — its 3 existing `has_agent_responded()` call sites are unaffected.
- `dispatch_async()` in `intent.py` — no changes to JetStream publish path.
- NATS stream configuration — no changes to INTENT_DISPATCH stream.
- BF-197 similarity guard in `ward_room_pipeline.py` — kept as-is.
- BF-198 `record_agent_response()` / `has_agent_responded()` — semantic round-tracking, unchanged.
- Cognitive queue (`queue.py`) — no changes to queue processing.

---

## Section 1: Add Dedup State to `IntentBus.__init__`

**File:** `src/probos/mesh/intent.py`

### 1a: Add state dict and counter

After the existing `_record_response` line (line 51), add:

```python
        # BF-234: Consumer-side dedup — tracks recently-seen intent IDs to
        # suppress transport-layer duplicates (JetStream redelivery, js_publish
        # timeout-then-succeed). Keyed by intent_id, value is monotonic timestamp.
        self._seen_intents: dict[str, float] = {}
        self._last_seen_eviction: float = time.monotonic()
        self._duplicate_suppressed_count: int = 0

        # BF-234: Injected event emitter for duplicate-suppressed telemetry.
        # Wired from finalize.py via set_emit_event().
        self._emit_event_fn: Callable[[str, dict[str, Any]], None] | None = None
```

### 1b: Add dedup check + eviction methods

After the existing `_on_prefix_change()` method (around line 620), add a new section:

```python
    # ------------------------------------------------------------------
    # BF-234: Consumer-side dispatch dedup
    # ------------------------------------------------------------------

    # Window must be ≥ JetStream ack_wait to catch duplicates queued behind
    # a slow handler. With max_ack_pending=1, msg #2 waits until msg #1 acks
    # (5–60s for a cognitive chain). 300s matches ack_wait=300 in
    # _js_subscribe_agent_dispatch. Memory: ~84KB worst case at 12 agents ×
    # 10 events/min × 600s eviction.
    _WARD_ROOM_DISPATCH_DEDUP_WINDOW: float = 300.0  # seconds — matches ack_wait

    def _is_duplicate_intent(self, intent_id: str) -> bool:
        """BF-234: Check if intent_id was already seen within the dedup window."""
        if not intent_id:
            return False
        last = self._seen_intents.get(intent_id)
        if last is not None and (time.monotonic() - last) < self._WARD_ROOM_DISPATCH_DEDUP_WINDOW:
            return True
        return False

    def _record_seen_intent(self, intent_id: str) -> None:
        """BF-234: Record that intent_id has been consumed."""
        if intent_id:
            self._seen_intents[intent_id] = time.monotonic()

    def _evict_stale_seen_intents(self, max_age: float = 600.0) -> None:
        """BF-234: Evict seen-intent records older than ``max_age`` seconds."""
        cutoff = time.monotonic() - max_age
        self._seen_intents = {
            k: v for k, v in self._seen_intents.items() if v > cutoff
        }
        self._last_seen_eviction = time.monotonic()

    def _maybe_evict_seen_intents(self, interval: float = 300.0) -> None:
        """BF-234: Periodic eviction — runs at most once per ``interval`` seconds."""
        if time.monotonic() - self._last_seen_eviction >= interval:
            self._evict_stale_seen_intents()

    def get_duplicate_suppressed_count(self) -> int:
        """BF-234: Return total number of transport-layer duplicates suppressed."""
        return self._duplicate_suppressed_count

    def set_emit_event(self, fn: Callable[[str, dict[str, Any]], None]) -> None:
        """BF-234: Inject event emitter for duplicate-suppressed telemetry."""
        self._emit_event_fn = fn
```

---

## Section 2: Wire Dedup Gate into `_on_dispatch()` Callback

**File:** `src/probos/mesh/intent.py`

In `_js_subscribe_agent_dispatch()` (line 147), modify the `_on_dispatch()` inner function (line 159). After the `intent_msg = self._deserialize_intent(msg.data)` line (line 166), insert the dedup gate **before** `record_response` and queue enqueue. The gate applies **only** to `ward_room_notification` intents.

Current code at lines 165-173:
```python
            try:
                intent_msg = self._deserialize_intent(msg.data)
                # AD-654a/BF-198: Record response BEFORE handler runs to close
                # the proactive-loop race window.
                # Uses injected callback instead of handler.__self__ reach-through.
                if self._record_response:
                    _thread_id = intent_msg.params.get("thread_id", "")
                    if _thread_id:
                        self._record_response(intent_msg.target_agent_id, _thread_id)
```

Replace with:
```python
            try:
                intent_msg = self._deserialize_intent(msg.data)

                # BF-234: Consumer-side dedup gate — suppress transport-layer
                # duplicates (JetStream redelivery, js_publish timeout-then-succeed).
                # Only ward_room_notification intents need this; other intent types
                # are idempotent or use request/reply (not fire-and-forget).
                # NOTE: This is structural dedup (same intent.id delivered twice).
                # BF-198 record_agent_response/has_agent_responded is semantic
                # round-tracking (agent spoke in this thread) — different invariant.
                if intent_msg.intent == "ward_room_notification":
                    if self._is_duplicate_intent(intent_msg.id):
                        _first_seen_ts = self._seen_intents[intent_msg.id]
                        _age_ms = (time.monotonic() - _first_seen_ts) * 1000
                        self._duplicate_suppressed_count += 1
                        logger.warning(
                            "BF-234: Suppressed duplicate ward_room_notification "
                            "for %s (intent=%s, age=%.0fms, total_suppressed=%d)",
                            agent_id[:12], intent_msg.id[:8], _age_ms,
                            self._duplicate_suppressed_count,
                        )
                        if self._emit_event_fn:
                            self._emit_event_fn(
                                "wardroom.dispatch.duplicate_suppressed",
                                {
                                    "agent_id": agent_id,
                                    "thread_id": intent_msg.params.get("thread_id", ""),
                                    "intent_id": intent_msg.id,
                                    "age_ms": round(_age_ms, 1),
                                },
                            )
                        await msg.ack()
                        return
                    self._record_seen_intent(intent_msg.id)
                    self._maybe_evict_seen_intents()  # periodic sweep — after gate, not before

                # AD-654a/BF-198: Record response BEFORE handler runs to close
                # the proactive-loop race window.
                # Uses injected callback instead of handler.__self__ reach-through.
                if self._record_response:
                    _thread_id = intent_msg.params.get("thread_id", "")
                    if _thread_id:
                        self._record_response(intent_msg.target_agent_id, _thread_id)
```

**Key details:**
- `msg.ack()` on duplicate — tells JetStream the message is consumed. Without this, JetStream redelivers up to `max_deliver=10` times.
- `msg.nak()` is NOT called — nak would cause redelivery, defeating the purpose.
- `return` after ack — skips `record_response`, queue enqueue, and handler. The duplicate never enters the cognitive pipeline.
- `intent_msg.id` is a UUID hex generated at `IntentMessage` creation (`types.py:58`). For JetStream redelivery, the same message has the same payload, so the same `id`. For BF-230 retry (timeout-then-succeed), `js_publish` retries with the same serialized payload, so the same `id`.
- Filter to `ward_room_notification` only — other intent types (targeted `send()`, broadcast) use request/reply or are idempotent. Scoping prevents false positives from legitimate same-id retransmissions in other contexts.

---

## Section 3: Wire Event Emitter in Startup

**File:** `src/probos/startup/finalize.py`

After the existing `_intent_bus.set_record_response(...)` call (line 214), add the event emitter injection:

```python
        _intent_bus.set_record_response(_wr_router.record_agent_response)
        _intent_bus.set_emit_event(runtime.emit_event)  # BF-234: dedup telemetry
```

---

## Section 4: Tests

**File:** `tests/test_bf234_ward_room_dispatch_dedup.py`

**Imports needed:**
```python
import logging
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.types import IntentMessage
```

**Fixture pattern:** Tests use `IntentBus(SignalManager())` — the real class, no mocks of the bus itself. Mock `_js` and `_nats_bus` where JetStream interaction is needed.

### Test 1: `test_dedup_blocks_second_intent`

Create an `IntentBus`. Call `_record_seen_intent("intent-1")`. Assert `_is_duplicate_intent("intent-1")` returns True. Assert `_is_duplicate_intent("intent-2")` returns False (different intent).

### Test 2: `test_dedup_expires_after_window`

Call `_record_seen_intent("intent-1")`. Manually set `bus._seen_intents["intent-1"]` to `time.monotonic() - 301.0` (beyond the 300s window). Assert `_is_duplicate_intent("intent-1")` returns False.

### Test 3: `test_eviction_removes_stale_entries`

Record 5 intents. Set 3 of their timestamps to `time.monotonic() - 15.0`. Call `_evict_stale_seen_intents(max_age=10.0)`. Assert only 2 remain in `_seen_intents`.

### Test 4: `test_on_dispatch_suppresses_duplicate_ward_room_notification`

Integration test of the full `_on_dispatch` callback. Setup:
1. Create `IntentBus(SignalManager())`.
2. Set `bus._record_response = MagicMock()`.
3. Create a handler `AsyncMock()`.
4. Build an `IntentMessage(intent="ward_room_notification", params={"thread_id": "t1"}, target_agent_id="agent-1")`.
5. Pre-record the intent ID: `bus._record_seen_intent(intent_msg.id)`.
6. Create a mock NATS msg with `msg.data = bus._serialize_intent(intent_msg)`, `msg.ack = AsyncMock()`, `msg.term = AsyncMock()`.
7. Call `_js_subscribe_agent_dispatch` — but since this creates a JetStream subscription, instead **extract the `_on_dispatch` callback** by:
   - Mock `bus._nats_bus = MagicMock()`, `bus._nats_bus.js_subscribe = AsyncMock(return_value=MagicMock())`.
   - Call `await bus._js_subscribe_agent_dispatch("agent-1", handler)`.
   - Verify `js_subscribe` was called with positional args `(subject, callback, ...)`.
   - Capture the callback: `callback = bus._nats_bus.js_subscribe.call_args.args[1]`.
   - Call `await callback(msg)`.
8. Assert:
   - `msg.ack.assert_awaited_once()` — duplicate was ack'd (not left for redelivery).
   - `msg.term.assert_not_awaited()` — not terminated.
   - `bus._record_response.assert_not_called()` — response not recorded for duplicate.
   - `handler.assert_not_awaited()` — handler was not invoked.
   - `bus._duplicate_suppressed_count == 1`.

### Test 5: `test_on_dispatch_allows_first_ward_room_notification`

Same setup as Test 4, but do NOT pre-record the intent ID. Register a mock cognitive queue via `bus.register_queue("agent-1", mock_queue)` where `mock_queue.enqueue = MagicMock(return_value=True)`. Assert:
- `mock_queue.enqueue.assert_called_once()` — intent was enqueued (not suppressed).
- `bus._record_response.assert_called_once()` — response recorded.
- `bus._duplicate_suppressed_count == 0`.
- `intent_msg.id in bus._seen_intents` — first delivery recorded for future dedup.

### Test 6: `test_on_dispatch_skips_dedup_for_non_ward_room_intent`

Same setup but use `intent="some_other_intent"`. Pre-record the intent ID. Assert the handler/queue path proceeds normally (no dedup filtering). This verifies the `ward_room_notification` filter.

### Test 7: `test_dedup_emits_event_on_hit`

Setup with `bus._emit_event_fn = MagicMock()`. Pre-record an intent. Trigger the duplicate callback (same as Test 4). Assert:
- `bus._emit_event_fn.assert_called_once()`.
- First arg is `"wardroom.dispatch.duplicate_suppressed"`.
- Second arg dict contains keys `agent_id`, `thread_id`, `intent_id`, `age_ms`.

### Test 8: `test_dedup_logs_warning_on_hit`

Same setup as Test 4 with `caplog.at_level(logging.WARNING)`. Assert `"BF-234"` appears in `caplog.text`. Assert `"Suppressed duplicate"` appears in `caplog.text`.

### Test 9: `test_duplicate_suppressed_counter`

Record an intent. Trigger the duplicate callback 3 times. Assert `bus.get_duplicate_suppressed_count() == 3`.

### Test 10: `test_duplicate_path_latency`

Time the duplicate suppression path. Setup: pre-record an intent, build a mock msg. Measure `time.monotonic()` before and after calling the callback. Assert elapsed time is < 1ms (`elapsed < 0.001`). The eviction sweep runs on the non-duplicate path (after `_record_seen_intent`), so the duplicate hit path is just a dict lookup + log + ack. This guards against future regressions that move the gate below an expensive operation.

### Test 11: `test_msg_nak_not_called_on_duplicate`

Same as Test 4. Explicitly add `msg.nak = AsyncMock()`. Assert `msg.nak.assert_not_awaited()`. Without this, JetStream would redeliver forever.

---

## Tracker Updates

### PROGRESS.md
Add row:
```
| BF-234 | Duplicate ward room responses — consumer-side dedup | Medium | **Closed** |
```

### docs/development/roadmap.md
In the Bug Tracker table, add:
```
| BF-234 | **Duplicate ward room responses on Captain new-thread.** 4 of 12 agents posted duplicate replies (millisecond timing) due to transport-layer duplicate delivery (JetStream redelivery or js_publish timeout-then-succeed). Application lacked consumer-side defense-in-depth. **Fix:** `_seen_intents` dict in `IntentBus._on_dispatch()` — 300s sliding-window (matches ack_wait) keyed by `intent.id`, filtered to `ward_room_notification` only. WARN log + `_duplicate_suppressed_count` counter + `wardroom.dispatch.duplicate_suppressed` event. `msg.ack()` on hit (no redelivery). Uses `time.monotonic()`. BF-198 remains semantic round-tracking only. 11 new tests. | Medium | **Closed** |
```

### DECISIONS.md
Add entry:
```
**BF-234: Consumer-side dispatch dedup is the authoritative gate against transport-layer duplicates.** Gate placed in `IntentBus._on_dispatch()` (JetStream consumer callback in `intent.py`), not in the router (publisher side). Router dispatches exactly once — the duplication happens at or after JetStream publish (BF-230 retry, server redelivery). Only the consumer sees the second copy. Scoped to `ward_room_notification` intent type only. Window is 300s (matches JetStream `ack_wait=300` in `_js_subscribe_agent_dispatch`) — with `max_ack_pending=1`, msg #2 queues behind msg #1's full cognitive chain, so the window must cover max handler duration. BF-198 `has_agent_responded()` / `record_agent_response()` remain semantic round-tracking for proactive-loop dedup — different invariant, different window, different key. Post-boundary defense (pipeline-level gate) deferred to BF-236 if consumer-side counter shows residual duplicates.
```
