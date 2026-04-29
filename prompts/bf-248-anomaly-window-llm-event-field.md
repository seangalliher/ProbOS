# BF-248: AD-673 Anomaly Window Reads Wrong Event Field for LLM Status

## Problem

The AD-673 `_wire_anomaly_window` listener in `finalize.py` reads `data.get("status")` from `LLM_HEALTH_CHANGED` events, but the actual event field is `new_status` (not `status`). The anomaly window also checks for `"healthy"` but the event uses `"operational"`.

**Code (finalize.py, line 58):**
```python
status = data.get("status", "") if isinstance(data, dict) else ""
if status in ("degraded", "offline"):
    manager.open_window("llm_degraded", f"LLM status: {status}")
elif status == "healthy" and manager.is_active():
```

**Actual `LlmHealthChangedEvent.to_dict()` produces (events.py lines 605-612, 247-255):**
```python
{
    "type": "llm_health_changed",
    "data": {
        "old_status": "operational",   # NOT "status"
        "new_status": "degraded",      # NOT "status"
        "consecutive_failures": 5,
        "consecutive_successes": 0,
        "downtime_seconds": 0.0
    }
}
```

**Consequences:**
1. `data.get("status")` always returns `""` — anomaly windows NEVER open for LLM degradation
2. The check for `"healthy"` should be `"operational"` (the status values are: operational, degraded, offline, recovering)
3. The `TRUST_CASCADE_WARNING` branch works because it doesn't need field extraction — it just calls `str(data)`

## Prior Art

- **AD-673** (Complete): Built `AnomalyWindowManager`. The prompt spec (line 169-175) showed `data.get("status")` — the spec was wrong about the event schema.
- **BF-069** (Closed): Defined the `LlmHealthChangedEvent` with `old_status`/`new_status` fields.
- **AD-576**: Emitter in `ProactiveCognitiveLoop._update_llm_status()` uses `LlmHealthChangedEvent(old_status=..., new_status=...)`.

## Root Cause

The AD-673 prompt assumed the event data contained a flat `"status"` key. The actual event structure uses `"new_status"` and `"old_status"` (designed for transition tracking). The builder implemented the prompt faithfully — the spec was wrong. This is a prompt verification gap (the architect should have verified the event schema before approving).

## Fix

### Section 1: Fix event field extraction

**File:** `src/probos/startup/finalize.py`

SEARCH (around line 57-64):
```python
            elif event_type_value == EventType.LLM_HEALTH_CHANGED.value:
                status = data.get("status", "") if isinstance(data, dict) else ""
                if status in ("degraded", "offline"):
                    manager.open_window("llm_degraded", f"LLM status: {status}")
                elif status == "healthy" and manager.is_active():
                    active_window = manager.get_active_window()
                    if active_window:
                        manager.close_window(active_window)
```

REPLACE:
```python
            elif event_type_value == EventType.LLM_HEALTH_CHANGED.value:
                # BF-248: LlmHealthChangedEvent uses new_status/old_status, not status
                new_status = data.get("new_status", "") if isinstance(data, dict) else ""
                if new_status in ("degraded", "offline"):
                    manager.open_window("llm_degraded", f"LLM status: {new_status}")
                elif new_status == "operational" and manager.is_active():
                    active_window = manager.get_active_window()
                    if active_window:
                        manager.close_window(active_window)
```

### Section 2: Fix tests

**File:** `tests/test_ad673_anomaly_window.py`

The existing tests pass dicts with `{"status": "degraded"}` which matched the broken code. Update to match the real event schema.

SEARCH (test_llm_degraded_triggers, around line 173):
```python
    await listener({"type": EventType.LLM_HEALTH_CHANGED.value, "data": {"status": "degraded"}})
```

REPLACE:
```python
    await listener({"type": EventType.LLM_HEALTH_CHANGED.value, "data": {"new_status": "degraded", "old_status": "operational"}})
```

SEARCH (test_llm_healthy_closes, around line 188-189):
```python
    await listener({"type": EventType.LLM_HEALTH_CHANGED.value, "data": {"status": "degraded"}})
    await listener({"type": EventType.LLM_HEALTH_CHANGED.value, "data": {"status": "healthy"}})
```

REPLACE:
```python
    await listener({"type": EventType.LLM_HEALTH_CHANGED.value, "data": {"new_status": "degraded", "old_status": "operational"}})
    await listener({"type": EventType.LLM_HEALTH_CHANGED.value, "data": {"new_status": "operational", "old_status": "degraded"}})
```

## Tests

No new test file needed. The 3 existing AD-673 tests covering LLM events are updated in Section 2 above. After the fix, these tests exercise the correct field names and status values.

## What This Does NOT Change

- No changes to `AnomalyWindowManager` class itself
- No changes to `LlmHealthChangedEvent` definition
- No changes to the trust cascade branch (it works correctly)
- No changes to event emission in `proactive.py`

## Tracking

- `PROGRESS.md`: Add BF-248 as CLOSED
- `docs/development/roadmap.md`: Add BF-248 to Bug Tracker table

## Acceptance Criteria

- Anomaly window opens when `LLM_HEALTH_CHANGED` event has `new_status: "degraded"` or `"offline"`
- Anomaly window closes when `LLM_HEALTH_CHANGED` event has `new_status: "operational"`
- Test event payloads match `LlmHealthChangedEvent.to_dict()` output
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`
