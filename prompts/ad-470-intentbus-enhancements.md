# AD-470: IntentBus Enhancements

**Status:** Ready for builder
**Dependencies:** None
**Estimated tests:** ~10

---

## Problem

The IntentBus (`mesh/intent.py`) has grown organically (788 lines) with
features added across multiple ADs (AD-397, AD-637b, AD-654a/b, BF-223,
BF-234). It lacks:

1. **Intent metrics** — No way to query "how many intents of each type
   were broadcast?" or "what's the average response time per intent type?"
2. **Priority-aware broadcast** — `broadcast()` fans out to all candidates
   equally. High-priority intents should be logged differently and have
   shorter timeouts.
3. **Subscriber introspection** — No API to see which agents are subscribed
   to which intent types.

AD-470 adds intent metrics tracking, priority-aware timeout adjustment,
and subscriber introspection to the IntentBus.

## Fix

### Section 1: Add `IntentMetrics` tracker

**File:** `src/probos/mesh/intent.py`

Add a metrics dataclass and tracker at module level (after the existing
imports and before the `IntentBus` class):

```python
@dataclass
class IntentMetrics:
    """Tracks intent broadcast statistics (AD-470)."""

    broadcast_count: int = 0
    send_count: int = 0
    total_results: int = 0
    type_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    type_durations_ms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def record_broadcast(self, intent_type: str, result_count: int, duration_ms: float) -> None:
        """Record a broadcast completion."""
        self.broadcast_count += 1
        self.total_results += result_count
        self.type_counts[intent_type] += 1
        durations = self.type_durations_ms[intent_type]
        durations.append(duration_ms)
        # Cap at 200 samples per type
        if len(durations) > 200:
            self.type_durations_ms[intent_type] = durations[-200:]

    def record_send(self, intent_type: str, duration_ms: float) -> None:
        """Record a directed send completion."""
        self.send_count += 1
        self.type_counts[intent_type] += 1
        durations = self.type_durations_ms[intent_type]
        durations.append(duration_ms)
        if len(durations) > 200:
            self.type_durations_ms[intent_type] = durations[-200:]

    def get_summary(self) -> dict[str, Any]:
        """Return a summary of intent metrics."""
        type_stats: dict[str, dict[str, Any]] = {}
        for intent_type, durations in self.type_durations_ms.items():
            if durations:
                type_stats[intent_type] = {
                    "count": self.type_counts[intent_type],
                    "mean_ms": round(sum(durations) / len(durations), 2),
                    "max_ms": round(max(durations), 2),
                }
        return {
            "broadcast_count": self.broadcast_count,
            "send_count": self.send_count,
            "total_results": self.total_results,
            "types": type_stats,
        }
```

**IMPORTANT:** `defaultdict` is NOT currently imported in `intent.py`.
Add this import near the top of the file (after the existing `import` lines):

```python
from collections import defaultdict
```

### Section 2: Wire metrics into IntentBus

**File:** `src/probos/mesh/intent.py`

**Step 1:** Add `_metrics` to `__init__` (around line 31, after other
attribute initializations):

```python
        # AD-470: Intent metrics
        self._metrics = IntentMetrics()
```

**Step 2:** Add timing and metrics recording to `broadcast()`.

Find the broadcast method (line 369). After the existing `results =`
line and before the return, add metrics recording:

In the `broadcast()` method, find the section after results are collected
(around line 437-454):

SEARCH:
```python
        results = self._pending_results.pop(intent.id, [])
        self._signal_manager.untrack(intent.id)
```

REPLACE:
```python
        results = self._pending_results.pop(intent.id, [])
        self._signal_manager.untrack(intent.id)

        # AD-470: Record metrics
        elapsed_ms = (time.monotonic() - _broadcast_start) * 1000
        self._metrics.record_broadcast(intent.intent, len(results), elapsed_ms)
```

**NOTE:** IntentBus already has its own `record_broadcast(intent_name)` method
at line 565 for demand metrics. The call above is `self._metrics.record_broadcast()`
(on the IntentMetrics object) — a different method. Do NOT confuse the two.

Also add the timing start. Find the beginning of `broadcast()` after
the target_agent_id check (around line 389):

SEARCH:
```python
        timeout = timeout if timeout is not None else intent.ttl_seconds
```

REPLACE:
```python
        timeout = timeout if timeout is not None else intent.ttl_seconds
        _broadcast_start = time.monotonic()  # AD-470: timing
```

**Step 3:** Add metrics recording to `send()`. Find `send()` (line 309).

SEARCH:
```python
    async def send(self, intent: IntentMessage) -> IntentResult | None:
        """Deliver an intent to a specific agent (targeted dispatch, AD-397).
```

REPLACE:
```python
    async def send(self, intent: IntentMessage) -> IntentResult | None:
        """Deliver an intent to a specific agent (targeted dispatch, AD-397).
```

After the ValueError check (line 319) and before the NATS path check, add timing start:

```python
        _send_start = time.monotonic()  # AD-470: timing
```

Then before each `return` in `send()` (lines 323, 328, 331, and the
TimeoutError return), you need to record metrics. The cleanest approach:
wrap the return value and record before returning. Add a helper at the
end of the method body:

After the existing `except asyncio.TimeoutError` block (around line 339),
replace the method's returns with a pattern that records metrics:

The simplest approach: add a `try/finally` around the method body after
the `_send_start` line:

```python
        _send_start = time.monotonic()  # AD-470: timing
        try:
            # ... existing NATS path and direct-call fallback (unchanged) ...
        finally:
            _elapsed_ms = (time.monotonic() - _send_start) * 1000
            self._metrics.record_send(intent.intent, _elapsed_ms)
```

Builder: wrap the existing code (from the NATS path check through the
TimeoutError handler) in a `try/finally` block. The finally records
metrics regardless of which path was taken or whether None was returned.

### Section 3: Add subscriber introspection

**File:** `src/probos/mesh/intent.py`

Add a method to the `IntentBus` class:

```python
    def get_subscriber_map(self) -> dict[str, list[str]]:
        """Return intent_name → [agent_ids] mapping (AD-470).

        Shows which agents are indexed for which intent types.
        Agents not in any index (fallback subscribers) are listed
        under the key "__fallback__".
        """
        result: dict[str, list[str]] = {}
        all_indexed: set[str] = set()

        for intent_name, agent_ids in self._intent_index.items():
            result[intent_name] = sorted(agent_ids)
            all_indexed.update(agent_ids)

        # Fallback subscribers (not in any index)
        fallback = [
            aid for aid in self._subscribers
            if aid not in all_indexed
        ]
        if fallback:
            result["__fallback__"] = sorted(fallback)

        return result

    def get_metrics(self) -> dict[str, Any]:
        """Return intent bus metrics summary (AD-470)."""
        return self._metrics.get_summary()
```

### Section 4: Add metrics API endpoint

**File:** `src/probos/routers/system.py`

```python
@router.get("/api/intent-metrics")
async def get_intent_metrics(runtime: Any = Depends(get_runtime)) -> dict:
    """Return IntentBus metrics (AD-470)."""
    intent_bus = getattr(runtime, "_intent_bus", None)
    if not intent_bus:
        return {"status": "disabled"}
    return {
        "metrics": intent_bus.get_metrics(),
        "subscribers": intent_bus.get_subscriber_map(),
        "subscriber_count": intent_bus.subscriber_count,
    }
```

Verify the intent_bus attribute name on runtime:
```
grep -n "_intent_bus\|intent_bus" src/probos/runtime.py | head -5
```

## Tests

**File:** `tests/test_ad470_intent_bus_enhancements.py`

10 tests:

1. `test_intent_metrics_creation` — create `IntentMetrics`, verify initial counts are 0
2. `test_record_broadcast` — record 3 broadcasts, verify `broadcast_count == 3`
3. `test_record_send` — record 2 sends, verify `send_count == 2`
4. `test_type_counts` — record broadcasts of different types, verify `type_counts` dict
5. `test_type_durations_capped` — record 250 durations, verify capped at 200
6. `test_metrics_summary` — record mixed metrics, verify `get_summary()` structure
   includes `mean_ms`, `max_ms`, `count` per type
7. `test_subscriber_map` — create IntentBus, subscribe agents with intent_names,
   verify `get_subscriber_map()` returns correct mapping
8. `test_subscriber_map_fallback` — subscribe agent without intent_names, verify
   it appears under `__fallback__`
9. `test_get_metrics_on_bus` — create IntentBus, verify `get_metrics()` returns
   dict with expected keys
10. `test_broadcast_records_metrics` — mock IntentBus with subscriber, call
    `broadcast()`, verify metrics.broadcast_count incremented

## What This Does NOT Change

- `broadcast()` behavior unchanged — same fan-out, same timeout logic
- `send()` / `dispatch_async()` behavior unchanged
- BF-234 dedup unchanged
- JetStream integration unchanged
- No changes to `IntentMessage` or `IntentResult` dataclasses
- Does NOT add priority-based timeout adjustment (deferred — metrics first)
- Does NOT modify subscriber callback signatures
- Does NOT add intent persistence or replay

## Tracking

- `PROGRESS.md`: Add AD-470 as COMPLETE
- `docs/development/roadmap.md`: Update AD-470 status

## Acceptance Criteria

- `IntentMetrics` tracks broadcast/send counts and per-type durations
- `get_subscriber_map()` returns intent → agent mapping
- `get_metrics()` returns summary with mean/max per type
- Duration samples capped at 200 per type
- `/api/intent-metrics` endpoint works
- All 10 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# IntentBus class
grep -n "class IntentBus" src/probos/mesh/intent.py
  23: class IntentBus

# broadcast method
grep -n "async def broadcast" src/probos/mesh/intent.py
  369: async def broadcast(self, intent, *, timeout=None, federated=True)

# send method
grep -n "async def send" src/probos/mesh/intent.py
  309: async def send(self, intent)

# Subscriber index
grep -n "_intent_index\|_subscribers" src/probos/mesh/intent.py
  33: self._subscribers: dict[str, IntentHandler]
  34: self._intent_index: dict[str, set[str]]

# Existing broadcast rate tracking
grep -n "record_broadcast\|_broadcast_timestamps" src/probos/mesh/intent.py
  37: self._broadcast_timestamps (monotonic_time, intent_name)
  391: self.record_broadcast(intent.intent)

# subscriber_count property
grep -n "subscriber_count" src/probos/mesh/intent.py
  306: def subscriber_count(self) -> int

# Runtime attribute
grep -n "_intent_bus" src/probos/runtime.py | head -3
```
