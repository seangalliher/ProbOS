# AD-637b: IntentBus NATS Migration — `send()` Transport + Wiring + Cleanup

**Status:** Ready for builder
**Scope:** Migrate `send()` to NATS request/reply with direct-call fallback. Add `publish()` alias (fixes latent bug). Clean up federation handler wiring. `broadcast()` stays direct-call (deferred to AD-637c with JetStream).
**Parent design:** `prompts/ad-637-nats-event-bus.md`
**Depends on:** AD-637a (NATS Foundation Layer — `NATSBus`, `MockNATSBus`, `NATSBusProtocol`)

---

## Overview

The IntentBus currently dispatches all intents by directly `await`-ing agent handler functions. This works but provides no queuing, no persistence, and couples the caller to the handler's event loop.

AD-637b migrates `send()` (targeted, single-agent dispatch) to NATS request/reply. When NATS is connected, `send()` publishes to `intent.{agent_id}` and waits for a reply. When NATS is unavailable, it falls back to the existing direct-call path. `broadcast()` stays on direct-call — its fan-out-and-collect pattern requires JetStream consumers (AD-637c).

**What changes:** `send()` dispatch path in `mesh/intent.py`, agent NATS subscription on registration.
**What stays the same:** `broadcast()`, all public API signatures, all callers. No caller files modified.

---

## Prior Work to Read

Read these files before writing any code:

- **`src/probos/mesh/intent.py`** — Current IntentBus (261 lines). Study `subscribe()`, `unsubscribe()`, `send()`, `broadcast()`, `_invoke_handler()`, `set_federation_handler()`, demand metrics. All public API methods are preserved with identical signatures.
- **`src/probos/mesh/nats_bus.py`** — AD-637a NATSBus and MockNATSBus. Study `publish()`, `subscribe()`, `request()`, `_full_subject()`. This is the transport layer for `send()`.
- **`src/probos/types.py`** — `IntentMessage` (lines 50-60) and `IntentResult` (lines 63-73). These are the message types serialized over NATS.
- **`src/probos/runtime.py:689`** — `_dispatch_watch_intent()` calls `self.intent_bus.publish(intent)` — but `IntentBus` has NO `publish()` method. This is a latent bug. Fix it in this AD.
- **`src/probos/runtime.py:296`** — IntentBus construction: `IntentBus(self.signal_manager)`. Do NOT change this line.
- **`src/probos/runtime.py:1069`** — Phase 1b: `self.nats_bus = await init_nats(self.config)`. Add wiring after this line.
- **`src/probos/startup/fleet_organization.py:180`** — `intent_bus._federation_fn = bridge.forward_intent`. Bypasses public API. Clean it up.
- **`tests/test_intent.py`** — 6 existing tests. All must continue to pass unchanged.

---

## Design Decisions

These resolve the architectural concerns identified during prompt review:

### No dual-delivery
`send()` uses NATS **or** direct-call, never both. When NATS is connected, the intent goes through NATS only. The `_subscribers` dict is still populated (needed by `broadcast()` which stays direct-call), but `send()` skips it when NATS is available. Fallback means "NATS unavailable → direct call", not "try both paths".

### Cancellation semantics
Current `send()` uses `asyncio.wait_for(handler(intent), timeout=...)` which cancels the handler coroutine on timeout. With NATS, the caller wraps `_nats_bus.request()` in `asyncio.wait_for` — on timeout, the caller stops waiting. The subscriber-side handler may run to completion. This is correct distributed-system semantics: you can't cancel a remote handler. The direct-call fallback preserves the current cancellation behavior.

### Serialization of `result: Any`
`IntentResult.result` is typed `Any`. The serialization helper passes it through as-is. If a handler puts a non-JSON-serializable object in `result`, serialization will raise — fail fast, not silent data loss. This is acceptable: the NATS path is new, handlers need to produce serializable results. Document the constraint in the serialization helper docstring.

### `subscribe()` stays synchronous
`subscribe()` remains a sync method. When NATS is connected, it fires `asyncio.ensure_future()` to create the NATS subscription asynchronously. The NATS sub may not be ready for the first few milliseconds after subscribe — acceptable because agents are subscribed during onboarding, well before any intents arrive.

---

## Changes

### 1. Add NATS bus attribute and setter

**File:** `src/probos/mesh/intent.py`

Update imports:

```python
from __future__ import annotations

import asyncio
import time
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Awaitable

if TYPE_CHECKING:
    from probos.mesh.nats_bus import NATSBus
```

Note: there's a duplicate `import time` on lines 5 and 8. Remove the duplicate.

Add to `__init__` (after existing attributes):

```python
self._nats_bus: Any = None  # AD-637b: wired via set_nats_bus()
self._nats_subs: dict[str, Any] = {}  # agent_id -> NATS subscription
```

Add setter after `set_federation_handler()`:

```python
def set_nats_bus(self, nats_bus: Any) -> None:
    """Wire NATS transport (called after NATS connects in Phase 1b)."""
    self._nats_bus = nats_bus
```

**IMPORTANT:** The constructor signature does NOT change. `IntentBus(self.signal_manager)` continues to work.

### 2. NATS subscription on agent registration

**File:** `src/probos/mesh/intent.py`

Modify `subscribe()` to also create a NATS subscription when NATS is available:

```python
def subscribe(self, agent_id: str, handler: IntentHandler, intent_names: list[str] | None = None) -> None:
    """Register an agent's intent handler."""
    # Existing logic — keep all of it
    self._subscribers[agent_id] = handler
    if intent_names:
        for name in intent_names:
            if name not in self._intent_index:
                self._intent_index[name] = set()
            self._intent_index[name].add(agent_id)

    # AD-637b: Create NATS subscription for targeted send()
    if self._nats_bus and self._nats_bus.connected:
        asyncio.ensure_future(self._nats_subscribe_agent(agent_id, handler))
```

Add helper:

```python
async def _nats_subscribe_agent(self, agent_id: str, handler: IntentHandler) -> None:
    """Subscribe an agent to their NATS intent subject for send() delivery."""
    subject = f"intent.{agent_id}"

    async def _on_nats_intent(msg: Any) -> None:
        """NATS message adapter: deserialize → handler → serialize reply."""
        try:
            intent = self._deserialize_intent(msg.data)
            result = await handler(intent)
            if msg.reply:
                if result is not None:
                    await msg.respond(self._serialize_result(result))
                else:
                    # Agent declined — send empty success response
                    await msg.respond({"declined": True})
        except Exception as e:
            logger.warning("NATS intent handler error for %s: %s", agent_id[:8], e)
            if msg.reply:
                error_result = IntentResult(
                    intent_id=msg.data.get("id", "") if isinstance(msg.data, dict) else "",
                    agent_id=agent_id,
                    success=False,
                    error=str(e),
                    confidence=0.0,
                )
                await msg.respond(self._serialize_result(error_result))

    sub = await self._nats_bus.subscribe(subject, _on_nats_intent)
    self._nats_subs[agent_id] = sub
```

### 3. NATS-aware `unsubscribe()`

**File:** `src/probos/mesh/intent.py`

Modify `unsubscribe()` to clean up NATS subscription:

```python
def unsubscribe(self, agent_id: str) -> None:
    """Remove an agent's subscription and intent index entries."""
    self._subscribers.pop(agent_id, None)
    for agent_set in self._intent_index.values():
        agent_set.discard(agent_id)
    # AD-637b: Clean up NATS subscription
    nats_sub = self._nats_subs.pop(agent_id, None)
    if nats_sub and hasattr(nats_sub, 'unsubscribe'):
        asyncio.ensure_future(self._nats_unsubscribe(nats_sub))

async def _nats_unsubscribe(self, sub: Any) -> None:
    """Unsubscribe from NATS subject."""
    try:
        await sub.unsubscribe()
    except Exception as e:
        logger.debug("NATS unsubscribe error: %s", e)
```

### 4. `send()` — NATS request/reply with fallback

**File:** `src/probos/mesh/intent.py`

Replace `send()` with NATS-first dispatch:

```python
async def send(self, intent: IntentMessage) -> IntentResult | None:
    """Deliver an intent to a specific agent (targeted dispatch, AD-397).

    AD-637b: Uses NATS request/reply when connected, direct-call fallback otherwise.
    Only one path is used per call — never both.
    """
    if not intent.target_agent_id:
        raise ValueError("send() requires target_agent_id")

    # AD-637b: NATS path (when connected and agent has NATS subscription)
    if (self._nats_bus and self._nats_bus.connected
            and intent.target_agent_id in self._nats_subs):
        return await self._nats_send(intent)

    # Direct-call fallback (original behavior, also used when NATS unavailable)
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

Add helper:

```python
async def _nats_send(self, intent: IntentMessage) -> IntentResult | None:
    """Send intent via NATS request/reply to target agent."""
    subject = f"intent.{intent.target_agent_id}"
    try:
        reply = await asyncio.wait_for(
            self._nats_bus.request(subject, self._serialize_intent(intent)),
            timeout=intent.ttl_seconds,
        )
    except asyncio.TimeoutError:
        return IntentResult(
            intent_id=intent.id,
            agent_id=intent.target_agent_id or "",
            success=False,
            error="Agent did not respond in time.",
            confidence=0.0,
        )
    if reply is None:
        return None
    data = reply.data if hasattr(reply, 'data') else reply
    if isinstance(data, dict) and data.get("declined"):
        return None
    return self._deserialize_result(data)
```

**Key design:** `send()` checks `self._nats_subs` to confirm the target agent has a NATS subscription before using the NATS path. If the agent was subscribed before NATS connected (or NATS is down), the direct-call path is used. No dual-delivery possible.

### 5. `broadcast()` — UNCHANGED

**Do NOT modify `broadcast()`.** It stays on direct-call fan-out. NATS migration for broadcast requires JetStream consumer patterns for proper fan-out-and-collect (AD-637c).

### 6. Add `publish()` alias — fix latent bug

**File:** `src/probos/mesh/intent.py`

`runtime.py:689` calls `self.intent_bus.publish(intent)` but `IntentBus` has no `publish()` method. Watch intents from WatchManager have been silently failing with `AttributeError` since AD-471. Add `publish()` as an alias for `broadcast()`:

```python
async def publish(self, intent: IntentMessage, **kwargs: Any) -> list[IntentResult]:
    """Alias for broadcast() — used by WatchManager dispatch (runtime.py:689)."""
    return await self.broadcast(intent, **kwargs)
```

Place immediately after the `broadcast()` method.

### 7. Serialization helpers

**File:** `src/probos/mesh/intent.py`

Add at the end of the class:

```python
@staticmethod
def _serialize_intent(intent: IntentMessage) -> dict[str, Any]:
    """Serialize IntentMessage for NATS transport.

    All fields must be JSON-serializable. params dict values that are
    not JSON-serializable will raise TypeError — fail fast.
    """
    return {
        "intent": intent.intent,
        "params": intent.params,
        "urgency": intent.urgency,
        "context": intent.context,
        "ttl_seconds": intent.ttl_seconds,
        "id": intent.id,
        "created_at": intent.created_at.isoformat(),
        "target_agent_id": intent.target_agent_id,
    }

@staticmethod
def _deserialize_intent(data: dict[str, Any]) -> IntentMessage:
    """Deserialize IntentMessage from NATS transport."""
    created_at = data.get("created_at")
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)
    else:
        created_at = datetime.now(timezone.utc)
    return IntentMessage(
        intent=data["intent"],
        params=data.get("params", {}),
        urgency=data.get("urgency", 0.5),
        context=data.get("context", ""),
        ttl_seconds=data.get("ttl_seconds", 60.0),
        id=data.get("id", ""),
        created_at=created_at,
        target_agent_id=data.get("target_agent_id"),
    )

@staticmethod
def _serialize_result(result: IntentResult) -> dict[str, Any]:
    """Serialize IntentResult for NATS reply.

    result.result must be JSON-serializable. Non-serializable values
    will raise TypeError — this is intentional (fail fast). Handlers
    using the NATS path must return serializable results.
    """
    return {
        "intent_id": result.intent_id,
        "agent_id": result.agent_id,
        "success": result.success,
        "result": result.result,
        "error": result.error,
        "confidence": result.confidence,
        "timestamp": result.timestamp.isoformat(),
    }

@staticmethod
def _deserialize_result(data: dict[str, Any]) -> IntentResult:
    """Deserialize IntentResult from NATS reply."""
    ts = data.get("timestamp")
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    else:
        ts = datetime.now(timezone.utc)
    return IntentResult(
        intent_id=data.get("intent_id", ""),
        agent_id=data.get("agent_id", ""),
        success=data.get("success", False),
        result=data.get("result"),
        error=data.get("error"),
        confidence=data.get("confidence", 0.0),
        timestamp=ts,
    )
```

### 8. Fix federation handler wiring

**File:** `src/probos/startup/fleet_organization.py`

Line 180 directly patches a private attribute:
```python
# Current (violates Law of Demeter):
intent_bus._federation_fn = bridge.forward_intent
```

Change to use the existing public method:
```python
# Fixed:
intent_bus.set_federation_handler(bridge.forward_intent)
```

### 9. Wire NATS bus in runtime Phase 1b

**File:** `src/probos/runtime.py`

After line 1069 (`self.nats_bus = await init_nats(self.config)`), add:

```python
# AD-637b: Wire NATS transport into IntentBus
if self.nats_bus:
    self.intent_bus.set_nats_bus(self.nats_bus)
```

---

## Files Modified

| File | Change | Lines (est.) |
|------|--------|-------------|
| `src/probos/mesh/intent.py` | NATS transport for `send()`, subscriptions, `publish()` alias, serialization, `set_nats_bus()` | +130 |
| `src/probos/runtime.py` | Wire NATS bus into IntentBus after Phase 1b init | +3 |
| `src/probos/startup/fleet_organization.py` | Use `set_federation_handler()` instead of `_federation_fn` assignment | ~1 |
| `tests/test_intent.py` | New tests for NATS send, fallback, publish alias, serialization | +100 |

**No new files.** This AD modifies existing files only.

---

## Tests

Add to `tests/test_intent.py`. All 6 existing tests MUST continue to pass unchanged.

Use `MockNATSBus` from `probos.mesh.nats_bus` for tests requiring NATS. Call `await mock_bus.start()` to set `connected=True`.

### New tests:

**Test 7: `test_send_via_nats_request_reply`**
Create IntentBus. Create MockNATSBus, `await start()`. Call `set_nats_bus(mock_bus)`. Subscribe an agent with a handler that returns an IntentResult. Call `send()` with `target_agent_id`. Verify the result is returned correctly via the NATS round-trip. Verify the handler WAS invoked (use a flag or side-effect).

**Test 8: `test_send_fallback_when_nats_disconnected`**
Create IntentBus with MockNATSBus but do NOT call `start()` (so `connected=False`). Subscribe an agent. Call `send()`. Verify the direct-call fallback is used — handler is invoked and result returned.

**Test 9: `test_send_fallback_when_no_nats`**
Create IntentBus with `nats_bus=None` (default). Subscribe an agent. Call `send()`. Verify direct-call path (identical to pre-637b behavior).

**Test 10: `test_send_no_dual_delivery`**
Create IntentBus with started MockNATSBus. Subscribe an agent with a handler that increments a counter. Call `send()`. Verify the handler is invoked exactly ONCE (not twice via both NATS and direct-call).

**Test 11: `test_nats_subscribe_creates_subscription`**
Create IntentBus with started MockNATSBus. Subscribe an agent. Wait briefly for `ensure_future` to complete (`await asyncio.sleep(0)`). Verify `agent_id` is in `_nats_subs`.

**Test 12: `test_unsubscribe_cleans_nats_subscription`**
Subscribe then unsubscribe an agent. Verify `agent_id` is removed from `_nats_subs`.

**Test 13: `test_publish_alias_calls_broadcast`**
Subscribe an agent. Call `intent_bus.publish(intent)`. Verify the handler is invoked and results returned — same as `broadcast()`.

**Test 14: `test_publish_targeted_delegates_to_send`**
Subscribe an agent. Call `intent_bus.publish(intent)` where `intent.target_agent_id` is set. Verify it works (delegates through `broadcast()` → `send()`).

**Test 15: `test_intent_serialization_roundtrip`**
Create an IntentMessage with all fields set (target_agent_id, non-default urgency, non-empty params). Serialize via `_serialize_intent()`, deserialize via `_deserialize_intent()`. Verify all fields match.

**Test 16: `test_result_serialization_roundtrip`**
Create an IntentResult with all fields set (string result, non-default confidence). Serialize via `_serialize_result()`, deserialize via `_deserialize_result()`. Verify all fields match.

**Test 17: `test_broadcast_still_uses_direct_call`**
Create IntentBus with started MockNATSBus. Subscribe agents. Call `broadcast()`. Verify handlers are invoked directly (broadcast behavior unchanged by NATS).

**Test 18: `test_set_nats_bus_wires_reference`**
Create IntentBus. Verify `_nats_bus is None`. Call `set_nats_bus(mock)`. Verify `_nats_bus is mock`.

**Test 19: `test_set_federation_handler`**
Verify `set_federation_handler()` sets `_federation_fn`. Create a mock federation function. Subscribe an agent. Call `broadcast(federated=True)`. Verify the federation function was called. (Validates the fleet_organization.py cleanup doesn't break anything.)

---

## Verification Checklist

Before marking complete:

1. All 6 existing `test_intent.py` tests pass (no regressions)
2. All new tests (7-19) pass
3. AD-637a tests still pass (24/24)
4. `send()` uses NATS when connected, direct-call when not — never both
5. `broadcast()` behavior is IDENTICAL to pre-637b
6. `publish()` method exists on IntentBus (fixes runtime.py:689 latent bug)
7. `runtime.py` wires NATS bus into IntentBus after Phase 1b init
8. `fleet_organization.py` uses `set_federation_handler()` not direct `_federation_fn` assignment
9. Duplicate `import time` removed from intent.py
10. When `nats.enabled: false` in config, IntentBus behavior is identical to pre-637b
11. No caller files modified — only `mesh/intent.py`, `runtime.py`, `fleet_organization.py`, tests

---

## Engineering Principles Compliance

- **Open/Closed:** IntentBus gains NATS transport without changing its public API. All callers unchanged.
- **Dependency Inversion:** IntentBus depends on `NATSBusProtocol` (via duck typing), not `NATSBus` directly.
- **Law of Demeter:** `fleet_organization.py` fixed — uses public `set_federation_handler()` instead of patching `_federation_fn`.
- **Fail Fast:** Non-serializable `IntentResult.result` raises TypeError on NATS path. `publish()` alias makes watch intent failures visible instead of silent AttributeError.
- **Defense in Depth:** Direct-call path preserved as fallback. NATS is an enhancement, not a hard dependency.
- **DRY:** Serialization helpers are static methods, reusable by AD-637c/637d.
