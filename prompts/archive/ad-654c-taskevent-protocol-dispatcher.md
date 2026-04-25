# AD-654c: TaskEvent Protocol & Dispatcher

**Priority:** Foundation for Phase 2+ of UAAA  
**Depends:** AD-654a (Async Dispatch) ✅, AD-654b (Cognitive Queue) ✅  
**Plan:** `cheerful-tinkering-pudding.md` (AD-654 decomposition)

## Problem

ProbOS has two activation paths that speak different languages:

1. **IntentBus dispatch** (`intent.py:415-495`): Creates `IntentMessage` with `intent="ward_room_notification"`, publishes to JetStream subject `intent.dispatch.{agent_id}`. The consumer callback (`_on_dispatch`, line 159) enqueues into the cognitive queue (AD-654b). Priority is inferred from `is_captain`/`was_mentioned` flags via `Priority.classify()`.

2. **Proactive loop** (`proactive.py:366-463`): Creates `IntentMessage` with `intent="proactive_think"`, calls `agent.handle_intent(intent)` directly. Bypasses both IntentBus and cognitive queue. Priority is implicitly LOW.

Both paths manually construct `IntentMessage` and manually classify priority. The ward room router (`ward_room_router.py:518-537`) builds intent params by hand. Recreation, workforce, and agent-to-agent signals don't exist as activation sources at all — the only way tic-tac-toe can trigger an agent is by posting to the ward room and hoping the router dispatches it.

**What's missing:**

- **No universal event format.** Each activation source creates `IntentMessage` with ad-hoc `params` dicts. There's no contract for what a "game move required" or "task assigned" event looks like.
- **No routing layer.** IntentBus.dispatch_async() delivers to a specific `agent_id`. There's no way to say "send this to whoever handles game moves" (capability) or "notify the Science department" (department broadcast).
- **No target resolution.** Ward room router manually iterates `runtime.registry.all()` and applies 8+ filter layers (cooldown, round tracking, trust, capacity). This logic is bespoke to ward room — no other event source can reuse it.

**Fix:** Introduce the TaskEvent protocol (universal activation format) and Dispatcher (routing layer) from the UAAA research paper. TaskEvent is the lingua franca for all activation sources. The Dispatcher resolves abstract targets to concrete agents and enqueues into cognitive queues.

## Architecture Change

**Before (AD-654b — current):**
```
Ward Room Router → IntentMessage(intent="ward_room_notification", params={...})
                 → IntentBus.dispatch_async(intent)
                 → JetStream publish → consumer → queue.enqueue()

Proactive Loop   → IntentMessage(intent="proactive_think", params={...})
                 → agent.handle_intent() (direct, no queue)

Recreation       → WardRoom.create_post() (posts text, hopes router picks it up)
```

**After (AD-654c):**
```
Ward Room Router → IntentMessage → IntentBus.dispatch_async()      (UNCHANGED)
                   (existing path preserved — AD-654d migrates it)

Proactive Loop   → IntentMessage → agent.handle_intent()           (UNCHANGED)
                   (AD-654d migrates to Dispatcher)

New emitters     → TaskEvent → Dispatcher.dispatch()
(AD-654d)          → resolve target → queue.enqueue()
```

AD-654c builds the **protocol and routing infrastructure**. AD-654d wires emitters to it. The existing IntentBus path is NOT migrated in this AD — that's explicitly AD-654d scope. This AD delivers:

1. `TaskEvent` dataclass — the universal activation format
2. `AgentTarget` dataclass — abstract target resolution (agent, capability, department, broadcast)
3. `Dispatcher` class — routes TaskEvents to cognitive queues
4. `DispatcherProtocol` — narrow interface for consumers
5. Integration tests proving the dispatch path works end-to-end

## TaskEvent Protocol

### TaskEvent Dataclass

New file: `src/probos/activation/task_event.py`

```python
@dataclass(frozen=True)
class TaskEvent:
    """Universal activation event — the lingua franca for all event sources.

    Every activation source (ward room, game, agent, kanban, external)
    creates a TaskEvent. The Dispatcher routes it to the right agent(s).

    Note: frozen=True prevents field reassignment but does NOT prevent
    mutation of the payload dict's contents. Consumers MUST treat
    payload as read-only. (MappingProxyType considered but adds
    serialization friction for minimal gain at this layer.)
    """
    source_type: str            # "ward_room" | "game" | "agent" | "captain" | "kanban" | "system"
    source_id: str              # Specific emitter ID (channel_id, game_id, agent_id, ...)
    event_type: str             # "ward_room_notification" | "move_required" | "task_assigned" | ...
    priority: Priority          # Uses existing Priority enum (CRITICAL/NORMAL/LOW)
    target: AgentTarget         # Who should receive this (see below)
    payload: dict[str, Any]     # Event-specific context — travels with the event (UAAA Principle 3)
    thread_id: str | None = None          # Conversational continuity (ward room thread, game session, ...)
    deadline: float | None = None         # Monotonic timestamp — when response is needed (None = no deadline)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)  # Unique event ID for dedup
    created_at: float = field(default_factory=time.monotonic)  # For latency tracking
```

**Design decisions:**
- `frozen=True` — events are immutable after creation. Routing metadata is never mutated. `payload` dict contents are not enforced immutable — documented in docstring.
- `priority` uses the existing `Priority` enum from `types.py:76-96`. No new priority system.
- `payload` is `dict[str, Any]` — intentionally untyped. Each event_type defines its own schema. This mirrors how `IntentMessage.params` works today.
- `thread_id` and `deadline` default to `None`. `id` and `created_at` use `field(default_factory=...)`. Non-defaulted fields (source_type through payload) come first — satisfies Python's dataclass ordering rule.
- `deadline` is `float | None`, not a datetime — monotonic timestamps for comparison, no timezone issues.
- `created_at` is `time.monotonic()` — for latency tracking (how long event waited before dispatch).
- No `ttl_seconds` — that's an IntentMessage concept for request/reply. TaskEvents don't expire; they're enqueued or dropped.

### AgentTarget Dataclass

Also in `src/probos/activation/task_event.py`:

```python
@dataclass(frozen=True)
class AgentTarget:
    """Specifies who should receive a TaskEvent.

    Exactly one of agent_id, capability, department_id must be set.
    If broadcast=True, all crew agents receive the event.
    """
    agent_id: str | None = None       # Explicit agent (e.g., "scout-abc123")
    capability: str | None = None     # Route to agent(s) with this capability
    department_id: str | None = None  # All agents in this department
    broadcast: bool = False           # All crew agents

    def __post_init__(self) -> None:
        """Validate exactly one targeting mode is set."""
        modes = sum([
            self.agent_id is not None,
            self.capability is not None,
            self.department_id is not None,
            self.broadcast,
        ])
        if modes != 1:
            raise ValueError(
                f"AgentTarget must specify exactly one of agent_id, capability, "
                f"department_id, or broadcast=True (got {modes} modes)"
            )
```

**Target resolution strategies:**
- `agent_id` → `registry.get(agent_id)` — direct delivery
- `capability` → `registry.get_by_capability(capability)` — all agents with that capability
- `department_id` → iterate `registry.all()`, filter by `ontology.get_agent_department(agent.agent_type) == department_id`
- `broadcast` → all crew agents via `is_crew_agent()` filter

### Factory Functions

Convenience constructors for common patterns:

```python
def task_event_for_agent(
    *,
    agent_id: str,
    source_type: str,
    source_id: str,
    event_type: str,
    priority: Priority,
    payload: dict[str, Any],
    thread_id: str | None = None,
    deadline: float | None = None,
) -> TaskEvent:
    """Create a TaskEvent targeted at a specific agent."""
    return TaskEvent(
        source_type=source_type,
        source_id=source_id,
        event_type=event_type,
        priority=priority,
        target=AgentTarget(agent_id=agent_id),
        payload=payload,
        thread_id=thread_id,
        deadline=deadline,
    )

def task_event_for_department(
    *,
    department_id: str,
    source_type: str,
    source_id: str,
    event_type: str,
    priority: Priority,
    payload: dict[str, Any],
    thread_id: str | None = None,
) -> TaskEvent:
    """Create a TaskEvent for all agents in a department."""
    return TaskEvent(
        source_type=source_type,
        source_id=source_id,
        event_type=event_type,
        priority=priority,
        target=AgentTarget(department_id=department_id),
        payload=payload,
        thread_id=thread_id,
    )

def task_event_broadcast(
    *,
    source_type: str,
    source_id: str,
    event_type: str,
    priority: Priority,
    payload: dict[str, Any],
    thread_id: str | None = None,
) -> TaskEvent:
    """Create a TaskEvent for all crew agents."""
    return TaskEvent(
        source_type=source_type,
        source_id=source_id,
        event_type=event_type,
        priority=priority,
        target=AgentTarget(broadcast=True),
        payload=payload,
        thread_id=thread_id,
    )
```

## Dispatcher

New file: `src/probos/activation/dispatcher.py`

The Dispatcher is the routing layer between TaskEvent emitters and agent cognitive queues. It resolves abstract targets to concrete agents, converts TaskEvents to IntentMessages (for queue compatibility), and enqueues.

### Constructor Dependencies

```python
class Dispatcher:
    """Routes TaskEvents to agent cognitive queues.

    Resolves abstract targets (capability, department, broadcast) to
    concrete agent IDs using the registry and ontology. Converts
    TaskEvents to IntentMessages for cognitive queue consumption.

    Does NOT replace IntentBus — they coexist. IntentBus handles
    request/reply (send) and legacy dispatch_async. Dispatcher handles
    fire-and-forget TaskEvent routing. AD-654d migrates existing
    emitters from IntentBus to Dispatcher.
    """

    def __init__(
        self,
        *,
        registry: Any,          # AgentRegistry — agent lookup
        ontology: Any | None,   # VesselOntologyService — department resolution
        get_queue: Callable[[str], Any | None],  # agent_id → cognitive queue (or None)
        dispatch_async_fn: Callable[..., Any] | None = None,  # Fallback for queueless agents
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
```

**Why inject a queue lookup function?** The cognitive queues are registered on `IntentBus._agent_queues` (private dict). Rather than injecting the IntentBus and reaching into `_get_agent_queue()` (Law of Demeter violation), the Dispatcher receives a `get_queue: Callable[[str], Any | None]` — a closure over IntentBus._agent_queues. Created in finalize.py: `get_queue=_intent_bus._get_agent_queue`. Single source of truth, no private member access from outside.

**Alternative considered and rejected:** Having Dispatcher maintain its own queue registry. This would require double-registration of queues (both IntentBus and Dispatcher) during startup. Single source of truth is better.

### Core Method: dispatch()

```python
async def dispatch(self, event: TaskEvent) -> DispatchResult:
    """Route a TaskEvent to the appropriate agent(s).

    Returns DispatchResult with counts of accepted/rejected/unroutable.

    Resolution order:
    1. Resolve AgentTarget → list of agent_ids
    2. For each agent: convert TaskEvent → IntentMessage
    3. Enqueue into cognitive queue (via get_queue callback)
    4. Fallback: dispatch_async_fn for substrate agents without queues
    5. If no dispatch_async_fn: fire-and-forget via asyncio.create_task().
       Track in `_pending_fallback_tasks: set[asyncio.Task]` with a
       done-callback that discards the task from the set (prevents GC
       collection of running tasks). This is the last-resort path — most
       agents will have cognitive queues after AD-654b.

    Does NOT check cooldowns, round tracking, or EA trust gates.
    Those are ward-room-specific concerns that stay in the router.
    The Dispatcher is a low-level routing primitive.

    Implementation notes:
    - Broadcast dispatches log at INFO level: "Dispatching {event_type} to {n} crew agents"
    - When an agent has no cognitive queue and dispatch_async_fn is used
      as fallback, dispatch_async_fn may itself re-check the queue. This
      redundancy is intentional — dispatch_async has its own fallback
      chain (JetStream → queue → create_task) and the Dispatcher treats
      it as opaque.
    """
```

**What the Dispatcher does NOT do:**
- Cooldown tracking — ward room router concern
- Round/loop prevention — ward room router concern  
- EA trust gating — proactive loop concern
- Token budget checking — dequeue-time guard (AD-654b `should_process`)
- Circuit breaker — dequeue-time guard (AD-654b `should_process`)
- Similarity guard — post-pipeline concern (AD-654a)
- Response posting — agent concern (AD-654a self-posting)

The Dispatcher is intentionally thin. It does routing, not policy. Policy is enforced at the queue level (dequeue guards) or the emitter level (ward room router filters).

### TaskEvent → IntentMessage Conversion

```python
def _to_intent_message(self, event: TaskEvent, agent_id: str) -> IntentMessage:
    """Convert TaskEvent to IntentMessage for cognitive queue consumption.

    The cognitive queue (AD-654b) processes IntentMessages. Until the
    queue is refactored to accept TaskEvents directly (future AD),
    the Dispatcher converts at the boundary.
    """
    return IntentMessage(
        intent=event.event_type,          # "move_required" → intent name
        params={
            **event.payload,
            "_task_event_id": event.id,    # Provenance tracking
            "_source_type": event.source_type,
            "_source_id": event.source_id,
        },
        context="",                        # Emitter populates payload, not context
        target_agent_id=agent_id,
        ttl_seconds=max(event.deadline - time.monotonic(), 1.0) if event.deadline else 120.0,
    )
```

### Target Resolution

```python
def _resolve_target(self, target: AgentTarget) -> list[str]:
    """Resolve AgentTarget to concrete agent IDs.

    Returns list of agent_ids. May be empty if no agents match.

    When ontology is None (e.g., tests, minimal startup):
    - agent_id targeting works normally (registry-only)
    - capability targeting works normally (registry-only)
    - department targeting returns [] (requires ontology)
    - broadcast returns all agents via is_crew_agent(a, None) fallback
    """
    if target.agent_id:
        agent = self._registry.get(target.agent_id)
        return [target.agent_id] if agent else []

    if target.capability:
        agents = self._registry.get_by_capability(target.capability)
        return [a.id for a in agents]

    if target.department_id:
        from probos.crew_utils import is_crew_agent
        return [
            a.id for a in self._registry.all()
            if is_crew_agent(a, self._ontology)
            and self._ontology
            and self._ontology.get_agent_department(a.agent_type) == target.department_id
        ]

    if target.broadcast:
        from probos.crew_utils import is_crew_agent
        return [
            a.id for a in self._registry.all()
            if is_crew_agent(a, self._ontology)
        ]

    return []
```

### DispatchResult

```python
@dataclass
class DispatchResult:
    """Result of dispatching a TaskEvent."""
    event_id: str               # TaskEvent.id
    target_count: int           # How many agents were targeted
    accepted: int               # Enqueued successfully
    rejected: int               # Queue overflow / shed
    unroutable: int             # No queue, no fallback
    agent_ids: list[str]        # Agents that received the event
    dispatch_ms: float          # Wall-clock time for dispatch (monotonic delta × 1000)
```

### Event Emission

The Dispatcher emits diagnostic events via the `emit_event` callback. The `EventType` entries are added in `events.py` (see "EventType Additions" section below) — the Dispatcher references them by string value, same pattern as AD-654b queue events.

- **`TASK_EVENT_DISPATCHED`** (`"task_event_dispatched"`) — emitted after routing completes. Data: `{event_id, event_type, source_type, target_mode, agent_count, accepted, rejected}`.
- **`TASK_EVENT_UNROUTABLE`** (`"task_event_unroutable"`) — emitted when target resolution finds zero agents. Data: `{event_id, event_type, target, reason}`.

## Protocol

New protocol in `src/probos/protocols.py`:

```python
@runtime_checkable
class DispatcherProtocol(Protocol):
    """Routes TaskEvents to agent cognitive queues (AD-654c).

    Consumers depend on this narrow interface, not the concrete
    Dispatcher class. Follows the existing Protocol pattern
    (9 existing protocols in this file).
    """

    async def dispatch(self, event: "TaskEvent") -> "DispatchResult":
        """Route a TaskEvent to the appropriate agent(s)."""
        ...
```

Use `from __future__ import annotations` and string annotation `"TaskEvent"` to avoid circular import with `activation/task_event.py`. The Protocol is in `protocols.py` (the existing protocol registry), not in the `activation/` package.

## Package Structure

```
src/probos/activation/
    __init__.py          # Re-export TaskEvent, AgentTarget, Dispatcher, factories
    task_event.py        # TaskEvent, AgentTarget, factory functions
    dispatcher.py        # Dispatcher, DispatchResult
```

`__init__.py` re-exports for clean imports:
```python
from probos.activation.task_event import (
    AgentTarget,
    TaskEvent,
    task_event_broadcast,
    task_event_for_agent,
    task_event_for_department,
)
from probos.activation.dispatcher import Dispatcher, DispatchResult
```

Also add `DispatcherProtocol` to the re-exports in `src/probos/protocols.py`'s `__all__` (if one exists) or to any barrel-export file that re-exports protocols. The Protocol lives in `protocols.py`, not in `activation/` — follow the existing pattern for how `AgentCognitiveQueueProtocol` is exported.

## Startup Wiring

In `src/probos/startup/finalize.py`, after cognitive queues are created (line ~229):

```python
# AD-654c: Create Dispatcher
from probos.activation.dispatcher import Dispatcher

dispatcher = Dispatcher(
    registry=runtime.registry,
    ontology=runtime.ontology,
    get_queue=_intent_bus._get_agent_queue,
    dispatch_async_fn=_intent_bus.dispatch_async,
    emit_event=runtime._emit_event,
)
runtime.dispatcher = dispatcher
logger.info("AD-654c: Dispatcher created")
```

**No shutdown needed.** The Dispatcher is stateless — it holds references to registry/ontology/intent_bus but owns no tasks, connections, or resources. When runtime shuts down, GC handles it.

## EventType Additions

In `src/probos/events.py`, add under the AD-654b queue events:

```python
# ── TaskEvent Dispatcher (AD-654c) ─────────────────────────────
TASK_EVENT_DISPATCHED = "task_event_dispatched"
TASK_EVENT_UNROUTABLE = "task_event_unroutable"
```

## Runtime Attribute

In `src/probos/runtime.py`, add the dispatcher attribute:

Search for the pattern where other services are declared (e.g., `self.ward_room_post_pipeline`, `self.recreation_service`). Add:

```python
self.dispatcher: Any | None = None  # AD-654c: TaskEvent Dispatcher
```

## Engineering Principles Compliance

- **SOLID/S:** `Dispatcher` routes TaskEvents to queues. It does NOT manage queues (IntentBus owns that), enforce policy (guards do that), or process intents (agents do that). `TaskEvent` is a data class — no behavior. `AgentTarget` is a data class with validation.
- **SOLID/O:** IntentBus is NOT modified. Dispatcher coexists. Future ADs (654d) migrate emitters to Dispatcher without changing Dispatcher itself.
- **SOLID/I:** New `DispatcherProtocol` — single method (`dispatch`). Follows the existing `@runtime_checkable Protocol` pattern.
- **SOLID/D:** Dispatcher depends on abstractions — registry (duck-typed `.get()`, `.all()`, `.get_by_capability()`), ontology (duck-typed `.get_agent_department()`), `get_queue` callback (plain `Callable[[str], Any | None]`), `dispatch_async_fn` callback. No concrete class imports.
- **Law of Demeter:** Dispatcher receives `get_queue` callback (a closure, not the IntentBus object) and `dispatch_async_fn` callback. It does NOT access `intent_bus._agent_queues` or any private members. Target resolution uses `registry.get()`, `registry.get_by_capability()`, `registry.all()`, `ontology.get_agent_department()` — all public APIs.
- **DRY:** Reuses `Priority` enum, `IntentMessage`, `AgentCognitiveQueue.enqueue()`, `is_crew_agent()`. No duplication of existing infrastructure.
- **Fail Fast:** `AgentTarget.__post_init__()` validates exactly one targeting mode. Empty target resolution → `TASK_EVENT_UNROUTABLE` event + warning log. Queue rejection → counted in `DispatchResult.rejected`.
- **Cloud-Ready:** Dispatcher is stateless and in-process. In Nooplex Cloud, the NATS JetStream layer provides cross-instance routing; the Dispatcher handles intra-instance resolution only.

## Files Changed

| File | Change |
|------|--------|
| `src/probos/activation/__init__.py` | **NEW** — package init with re-exports |
| `src/probos/activation/task_event.py` | **NEW** — TaskEvent, AgentTarget, factory functions |
| `src/probos/activation/dispatcher.py` | **NEW** — Dispatcher, DispatchResult |
| `src/probos/protocols.py` | Add `DispatcherProtocol` |
| `src/probos/events.py` | Add 2 EventType entries |
| `src/probos/runtime.py` | Add `self.dispatcher` attribute |
| `src/probos/startup/finalize.py` | Wire Dispatcher creation |
| `tests/test_ad654c_taskevent_dispatcher.py` | **NEW** — ~26 tests |

## What This Does NOT Do

1. **Does NOT migrate ward room router.** The router continues using `IntentBus.dispatch_async()`. AD-654d migrates it to emit TaskEvents via Dispatcher.
2. **Does NOT migrate proactive loop.** The proactive loop continues calling `agent.handle_intent()` directly. AD-654d adds ambient-priority Dispatcher path.
3. **Does NOT modify IntentBus.** IntentBus is unchanged — Dispatcher coexists alongside it. No IntentBus.publish() changes.
4. **Does NOT add JetStream streams.** The Dispatcher enqueues into existing in-memory cognitive queues. JetStream is the upstream durable layer (AD-654a). Cross-instance dispatch (federation) is AD-654e.
5. **Does NOT enforce ward-room-specific policy.** No cooldowns, round tracking, similarity guards, or EA trust gates. Those stay in the ward room router.
6. **Does NOT add `handle_task_event()` to agents.** Agents continue receiving `IntentMessage` via `handle_intent()`. The Dispatcher converts at the boundary.

## Tests

File: `tests/test_ad654c_taskevent_dispatcher.py`

### TaskEvent & AgentTarget (7 tests)

1. **test_task_event_frozen** — TaskEvent is immutable (frozen=True)
2. **test_agent_target_exactly_one_mode** — ValueError if 0 or 2+ modes set
3. **test_agent_target_agent_id** — valid with just agent_id
4. **test_agent_target_capability** — valid with just capability
5. **test_agent_target_department** — valid with just department_id
6. **test_agent_target_broadcast** — valid with just broadcast=True
7. **test_factory_functions** — `task_event_for_agent`, `task_event_for_department`, `task_event_broadcast` create valid TaskEvents

### Target Resolution (5 tests)

8. **test_resolve_agent_id_found** — returns [agent_id] when agent exists
9. **test_resolve_agent_id_not_found** — returns [] when agent doesn't exist
10. **test_resolve_capability** — returns agent_ids matching capability
11. **test_resolve_department** — returns crew agents in the department
12. **test_resolve_broadcast** — returns all crew agents

### Dispatch (8 tests)

13. **test_dispatch_to_agent_enqueues** — TaskEvent with agent_id target enqueues into cognitive queue
14. **test_dispatch_to_capability_enqueues_all** — all capable agents receive event
15. **test_dispatch_to_department_enqueues_dept** — only department agents receive event
16. **test_dispatch_broadcast_enqueues_all_crew** — all crew agents receive event
17. **test_dispatch_result_counts** — accepted/rejected/unroutable counts are accurate
18. **test_dispatch_unroutable_emits_event** — TASK_EVENT_UNROUTABLE when no agents match
19. **test_dispatch_no_queue_fallback** — agents without queue get dispatch_async_fn fallback
20. **test_dispatch_queue_overflow_counted** — queue.enqueue() returning False increments rejected count

### Integration (6 tests)

21. **test_taskevent_to_intent_message_conversion** — payload preserved, _task_event_id injected
22. **test_dispatched_event_emitted** — TASK_EVENT_DISPATCHED event with correct data
23. **test_priority_preserved_through_dispatch** — CRITICAL TaskEvent → CRITICAL queue item
24. **test_dispatcher_protocol_compliance** — Dispatcher satisfies DispatcherProtocol
25. **test_end_to_end_dispatch_to_handler** — TaskEvent → Dispatcher → queue → processor → agent.handle_intent()
26. **test_broadcast_mixed_queues** — broadcast with 3 crew agents: 2 have cognitive queues (enqueued), 1 has no queue (dispatch_async_fn fallback). Verify accepted=2, fallback called once, DispatchResult.agent_ids includes all 3.

### Test Helpers

```python
def _make_agent(agent_id, agent_type="scout", capabilities=None, pool="science"):
    """Create a mock agent with registry-compatible interface."""
    ...

def _make_registry(*agents):
    """Create a mock registry with get/all/get_by_capability."""
    ...

def _make_ontology(dept_map=None):
    """Create a mock ontology with get_agent_department."""
    ...

def _make_event(target, event_type="test_event", priority=Priority.NORMAL, **kwargs):
    """Create a TaskEvent with sensible defaults."""
    ...
```

Use `unittest.mock.MagicMock` and `AsyncMock` for registry/ontology/intent_bus mocks. Do NOT import runtime or require database fixtures.

## Verification

```bash
# AD-654c tests
pytest tests/test_ad654c_taskevent_dispatcher.py -v

# Protocol regression
pytest tests/test_protocols.py -v

# Intent bus regression (unchanged)
pytest tests/test_intent.py -v

# Cognitive queue regression (unchanged)
pytest tests/test_ad654b_cognitive_queue.py -v

# Full suite
pytest -n auto
```
