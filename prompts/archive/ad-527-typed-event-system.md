# AD-527: Typed Event System

## Context

ProbOS has ~55 unique event types emitted across 15 source files via `_emit_event(event_type: str, data: dict[str, Any])`. All event types are raw string literals, all payloads are untyped dicts. No schema validation, no IDE autocomplete on payloads, no event catalog. Typos in event type strings fail silently.

This AD replaces string-literal event types with a formal registry and typed event dataclasses. Backward-compatible — existing dict consumers still work during migration.

## Scope

### What to build

1. **Event type registry** — `EventType` enum with all ~55 event types
2. **Typed event dataclasses** — one per event type (or grouped by domain)
3. **Updated `_emit_event`** — accepts both new typed events AND old string+dict (backward compat)
4. **Migration of all 15 producer files** — replace string literals with enum + dataclass
5. **Tests** — registry completeness, serialization round-trip, backward compat

### What NOT to do

- Do NOT change the WebSocket broadcast format (HXI frontend expects `{"type": str, "data": dict, "timestamp": float}`)
- Do NOT change EventLog (separate system — SQLite audit trail for agent lifecycle, not related)
- Do NOT change the `on_event` callback pattern used by decomposer.py/renderer.py (these use a different callback chain, not `_emit_event`)
- Do NOT refactor test logic — only update event references if event types change shape

## Step 1: Create event type registry and base class

Create `src/probos/events.py`:

```python
"""Typed event system (AD-527)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """Registry of all ProbOS event types.

    Grouped by domain. The string value matches the existing event type
    strings for backward compatibility with HXI WebSocket consumers.
    """

    # Build pipeline
    BUILD_QUEUE_ITEM = "build_queue_item"
    BUILD_QUEUE_UPDATE = "build_queue_update"
    BUILD_STARTED = "build_started"
    BUILD_PROGRESS = "build_progress"
    BUILD_GENERATED = "build_generated"
    BUILD_RESOLVED = "build_resolved"
    BUILD_SUCCESS = "build_success"
    BUILD_FAILURE = "build_failure"

    # Self-modification
    SELF_MOD_STARTED = "self_mod_started"
    SELF_MOD_IMPORT_APPROVED = "self_mod_import_approved"
    SELF_MOD_PROGRESS = "self_mod_progress"
    SELF_MOD_SUCCESS = "self_mod_success"
    SELF_MOD_RETRY_COMPLETE = "self_mod_retry_complete"
    SELF_MOD_FAILURE = "self_mod_failure"

    # Design pipeline
    DESIGN_STARTED = "design_started"
    DESIGN_PROGRESS = "design_progress"
    DESIGN_GENERATED = "design_generated"
    DESIGN_FAILURE = "design_failure"

    # Trust & routing
    TRUST_UPDATE = "trust_update"
    HEBBIAN_UPDATE = "hebbian_update"
    CONSENSUS = "consensus"

    # Transporter / builder
    TRANSPORTER_ASSEMBLED = "transporter_assembled"
    TRANSPORTER_VALIDATED = "transporter_validated"
    TRANSPORTER_DECOMPOSED = "transporter_decomposed"
    TRANSPORTER_WAVE_START = "transporter_wave_start"
    TRANSPORTER_CHUNK_DONE = "transporter_chunk_done"
    TRANSPORTER_EXECUTION_DONE = "transporter_execution_done"

    # Ward Room
    WARD_ROOM_PRUNED = "ward_room_pruned"
    WARD_ROOM_THREAD_CREATED = "ward_room_thread_created"
    WARD_ROOM_THREAD_UPDATED = "ward_room_thread_updated"
    WARD_ROOM_POST_CREATED = "ward_room_post_created"
    WARD_ROOM_ENDORSEMENT = "ward_room_endorsement"

    # Dream / system mode
    SYSTEM_MODE = "system_mode"
    CAPABILITY_GAP_PREDICTED = "capability_gap_predicted"

    # Agent lifecycle
    AGENT_STATE = "agent_state"

    # Assignments
    ASSIGNMENT_CREATED = "assignment_created"
    ASSIGNMENT_UPDATED = "assignment_updated"
    ASSIGNMENT_COMPLETED = "assignment_completed"

    # Work items / workforce
    WORK_ITEM_CREATED = "work_item_created"
    WORK_ITEM_UPDATED = "work_item_updated"
    WORK_ITEM_STATUS_CHANGED = "work_item_status_changed"
    WORK_ITEM_ASSIGNED = "work_item_assigned"
    WORK_ITEM_CLAIMED = "work_item_claimed"
    BOOKING_STARTED = "booking_started"
    BOOKING_COMPLETED = "booking_completed"
    BOOKING_CANCELLED = "booking_cancelled"

    # Scheduled tasks
    SCHEDULED_TASK_CREATED = "scheduled_task_created"
    SCHEDULED_TASK_CANCELLED = "scheduled_task_cancelled"
    SCHEDULED_TASK_DAG_RESUMED = "scheduled_task_dag_resumed"
    SCHEDULED_TASK_FIRED = "scheduled_task_fired"
    SCHEDULED_TASK_UPDATED = "scheduled_task_updated"
    SCHEDULED_TASK_DAG_STALE = "scheduled_task_dag_stale"

    # Notifications / tasks
    NOTIFICATION = "notification"
    NOTIFICATION_ACK = "notification_ack"
    NOTIFICATION_SNAPSHOT = "notification_snapshot"
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"

    # Initiative
    INITIATIVE_PROPOSAL = "initiative_proposal"

    # NL pipeline
    DECOMPOSE_START = "decompose_start"
    DECOMPOSE_COMPLETE = "decompose_complete"

    # Bridge
    BRIDGE_ALERT = "bridge_alert"
    PROACTIVE_THOUGHT = "proactive_thought"


@dataclass
class BaseEvent:
    """Base class for all typed events.

    Subclasses define domain-specific fields. Serializes to the same
    {"type": str, "data": dict, "timestamp": float} format the HXI
    WebSocket expects.
    """

    event_type: EventType
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire format HXI expects."""
        data = {k: v for k, v in asdict(self).items()
                if k not in ("event_type", "timestamp")}
        return {
            "type": self.event_type.value,
            "data": data,
            "timestamp": self.timestamp,
        }
```

**IMPORTANT:** Verify the enum values above against actual call sites. If you find an event type string in the code that is NOT in this enum, ADD it. If an enum entry has no call site, REMOVE it. The list above is from a manual survey and may have gaps.

**Search for completeness:**
```bash
grep -rn "_emit_event\|emit_event" src/probos/ --include="*.py" | grep -oP '"[a-z_]+"' | sort -u
```

## Step 2: Create domain event dataclasses

Add typed dataclasses for the highest-traffic event domains. Group in `events.py` below `BaseEvent`:

```python
@dataclass
class BuildProgressEvent(BaseEvent):
    """Build pipeline progress update."""
    event_type: EventType = field(default=EventType.BUILD_PROGRESS, init=False)
    phase: str = ""
    message: str = ""
    build_id: str = ""
    agent_id: str = ""

@dataclass
class TrustUpdateEvent(BaseEvent):
    """Trust score change."""
    event_type: EventType = field(default=EventType.TRUST_UPDATE, init=False)
    agent_id: str = ""
    callsign: str = ""
    old_score: float = 0.0
    new_score: float = 0.0
    reason: str = ""
```

**Do NOT exhaustively type all 55 event types.** Start with these high-traffic domains (sorted by call-site count):

| Priority | Domain | Event Types | File |
|----------|--------|------------|------|
| A | Build pipeline | 8 types, 16 call sites | `routers/build.py` |
| A | Self-mod pipeline | 6 types, 9 call sites | `routers/chat.py` |
| A | Trust & routing | 3 types, 7 call sites | `runtime.py`, `proactive.py`, `ward_room.py` |
| B | Task tracker | 4 types, 10 call sites | `task_tracker.py` |
| B | Workforce | 7 types, 7 call sites | `workforce.py` |
| B | Ward Room | 5 types, 6 call sites | `ward_room.py` |
| B | Design pipeline | 3 types, 6 call sites | `routers/design.py` |
| C | Scheduled tasks | 6 types, 6 call sites | `persistent_tasks.py` |
| C | Assignments | 3 types, 4 call sites | `assignment.py` |
| C | Transporter | 6 types, varies | `builder.py` |
| C | Dream/system | 2 types, 3 call sites | `dream_adapter.py` |

For Priority C and any types you don't have time to fully type, they can continue using the string+dict path via the backward-compatible `_emit_event` signature.

For each typed event, examine the actual `data` dict at the call site to determine the fields. Example pattern:

```python
# BEFORE (routers/build.py):
self.runtime._emit_event("build_progress", {
    "phase": "generating",
    "message": f"Generating code for {node.name}",
    "build_id": build_id,
})

# AFTER:
self.runtime.emit_event(BuildProgressEvent(
    phase="generating",
    message=f"Generating code for {node.name}",
    build_id=build_id,
))
```

## Step 3: Update `_emit_event` for backward compatibility

In `runtime.py`, update the emit method to accept both typed events and legacy string+dict:

```python
from probos.events import BaseEvent, EventType

def _emit_event(self, event_type: str | EventType, data: dict[str, Any] | None = None) -> None:
    """Fire-and-forget event to all registered listeners (AD-254)."""
    if isinstance(event_type, BaseEvent):
        event = event_type.to_dict()
    elif isinstance(event_type, EventType):
        event = {"type": event_type.value, "data": data or {}, "timestamp": time.time()}
    else:
        event = {"type": event_type, "data": data or {}, "timestamp": time.time()}
    for fn in self._event_listeners:
        try:
            fn(event)
        except Exception:
            logger.debug("Event listener failed for %s", event.get("type", "?"), exc_info=True)
    self._check_night_order_escalation(event.get("type", ""), event.get("data", {}))

def emit_event(self, event: BaseEvent | str, data: dict[str, Any] | None = None) -> None:
    """Public typed event emission. Delegates to _emit_event."""
    if isinstance(event, BaseEvent):
        self._emit_event(event)
    else:
        self._emit_event(event, data or {})
```

**Also update `EventEmitterProtocol` in `protocols.py`:**

```python
from probos.events import BaseEvent

class EventEmitterProtocol(Protocol):
    """What modules need to emit HXI events."""
    def emit_event(self, event: BaseEvent | str, data: dict[str, Any] | None = None) -> None: ...
    def add_event_listener(self, fn: Callable[..., Any]) -> None: ...
    def remove_event_listener(self, fn: Callable[..., Any]) -> None: ...
```

**NOTE:** The protocol currently says `emit_event` (public) but runtime implements `_emit_event` (private). Keep both working — `emit_event` is the new public API, `_emit_event` stays for backward compat with internal callers.

## Step 4: Migrate producer files

For each producer file, replace string literals with `EventType` enum values or typed event instances.

**Migration order (priority):**

### 4a. `routers/build.py` — 16 call sites, 8 event types

Replace all `self.runtime._emit_event("build_...", {...})` with typed `BuildProgressEvent`, `BuildStartedEvent`, etc.

### 4b. `routers/chat.py` — 9 call sites, 6 event types

Replace all `self.runtime._emit_event("self_mod_...", {...})` with typed events.

### 4c. `runtime.py` — 7 call sites, 4 event types

Replace trust_update, hebbian_update, consensus, build_queue_item emissions.

### 4d. `task_tracker.py` — 10 call sites, 4 event types

Replace notification and task events.

### 4e. Remaining files

`ward_room.py`, `workforce.py`, `routers/design.py`, `persistent_tasks.py`, `assignment.py`, `dream_adapter.py`, `agent_onboarding.py`.

**For each migration:**
1. Add import: `from probos.events import EventType, SomeEvent`
2. Replace string literal with enum or typed event
3. Run tests for that file: `.venv/Scripts/python.exe -m pytest tests/test_<corresponding>.py -x -q`

### 4f. Proactive loop and initiative — special case

`proactive.py` and `initiative.py` emit full `{"type": ..., "data": ...}` dicts directly (not via `_emit_event`). These are bridged by lambdas in `startup/structural_services.py` and `startup/finalize.py`. Update these to use `EventType` enum values but keep the dict format since they go through the bridge lambdas.

```python
# BEFORE (proactive.py):
on_event({"type": "bridge_alert", "data": {...}})

# AFTER:
on_event({"type": EventType.BRIDGE_ALERT.value, "data": {...}})
```

Do NOT refactor the bridge lambda pattern — that's a separate concern.

### 4g. Decomposer / builder on_event callbacks

`decomposer.py` and `builder.py` use `on_event` callbacks with their own event types (`node_start`, `node_complete`, `node_failed`, `escalation_start`, etc.). These flow through a separate callback chain to `renderer.py`, NOT through `_emit_event`.

**Two options (pick one):**
1. **Add to EventType enum but don't migrate call sites** — just register them for catalog completeness
2. **Leave them out of EventType** — they're a separate internal callback system

**Recommended:** Option 1. Add them to the enum for documentation/catalog purposes. Replace the string literals in decomposer.py and builder.py with enum values. The renderer.py consumer matches on `event_type == "node_start"` etc. — update those to use `EventType.NODE_START.value`.

Add these to the enum:
```python
# DAG execution (on_event callback chain, not _emit_event)
NODE_START = "node_start"
NODE_COMPLETE = "node_complete"
NODE_FAILED = "node_failed"
ESCALATION_START = "escalation_start"
ESCALATION_RESOLVED = "escalation_resolved"
ESCALATION_EXHAUSTED = "escalation_exhausted"
```

## Step 5: Night Orders integration check

`_check_night_order_escalation(event_type, data)` at `runtime.py:652` receives string event types. After migration, it will receive `EventType` enum values (which are `str` subclass due to `str, Enum`). Verify this works — since `EventType(str, Enum)`, the `.value` is a string with the same value. The `_check_night_order_escalation` method may compare against string literals internally — update those comparisons too.

Search:
```bash
grep -n "_check_night_order_escalation\|night_order" src/probos/runtime.py
```

## Step 6: Tests

Create `tests/test_events.py`:

1. **Registry completeness** — every `_emit_event` call site in the codebase uses a string that exists in `EventType`. Write a test that greps the source and validates.
   ```python
   def test_all_event_types_registered():
       """Every event type string used in _emit_event has an EventType entry."""
       # ... grep source files for _emit_event calls, extract strings, assert in EventType
   ```

2. **Serialization round-trip** — each typed event's `to_dict()` produces the expected wire format.
   ```python
   def test_base_event_to_dict():
       event = BuildProgressEvent(phase="generating", message="test", build_id="b1")
       d = event.to_dict()
       assert d["type"] == "build_progress"
       assert d["data"]["phase"] == "generating"
       assert "timestamp" in d
       assert "event_type" not in d["data"]
   ```

3. **Backward compatibility** — `_emit_event` still works with raw strings.
   ```python
   def test_emit_event_backward_compat(mock_runtime):
       """Legacy string+dict calls still work."""
       events = []
       mock_runtime.add_event_listener(lambda e: events.append(e))
       mock_runtime._emit_event("test_event", {"key": "value"})
       assert events[0]["type"] == "test_event"
   ```

4. **Enum string identity** — `EventType.BUILD_PROGRESS == "build_progress"` must be `True` (guaranteed by `str, Enum`).

## Validation

### After each file migration:
```bash
.venv/Scripts/python.exe -m pytest tests/test_<file>.py -x -q
```

### After all migrations:
```bash
.venv/Scripts/python.exe -m pytest tests/ -x -q
```

### Verify no orphaned string literals:
```bash
# Should return 0 hits after full migration (excluding test files and comments)
grep -rn "_emit_event(\"" src/probos/ --include="*.py"
```

## Critical Rules

1. **Wire format must NOT change.** The HXI frontend parses `{"type": string, "data": dict, "timestamp": float}`. The `to_dict()` method must produce exactly this shape.

2. **Don't break existing tests.** Tests that check `event["type"] == "some_string"` still work because `EventType` is a `str` subclass. But verify.

3. **Don't type ALL 55 events.** Priority A domains get full typed dataclasses. Priority B/C get enum values but can keep dict payloads. The enum is the minimum — every string literal becomes `EventType.SOMETHING`.

4. **`str, Enum` is critical.** The enum must inherit from `str` so that `EventType.BUILD_PROGRESS == "build_progress"` is `True`. This preserves backward compat with all string comparisons.

5. **Imports must be lightweight.** `events.py` should have zero heavy imports (no runtime, no services). It's a leaf module that everything else imports.

## Reference

- Current `_emit_event`: `runtime.py:574`
- `EventEmitterProtocol`: `protocols.py:81`
- API WebSocket broadcast: `api.py:163-265` (`_on_runtime_event` → `_broadcast_event`)
- Night Orders check: `runtime.py:652` (`_check_night_order_escalation`)
- Bridge lambdas: `startup/structural_services.py:94`, `startup/finalize.py:64`
- Renderer callback: `experience/renderer.py:445`
- EventLog (SEPARATE, do not touch): `substrate/event_log.py`
