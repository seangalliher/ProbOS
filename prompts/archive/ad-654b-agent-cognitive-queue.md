# AD-654b: Agent Cognitive Queue — Priority Mailbox

**Priority:** Soon — enables reactive agent-to-agent interaction  
**Depends:** AD-654a (Async Ward Room Dispatch) ✅  
**Plan:** `cheerful-tinkering-pudding.md` (AD-654 decomposition)

## Problem

Agents process cognitive work in two disconnected paths with no priority ordering:

1. **JetStream dispatch** (`intent.py:143-180`): `_on_dispatch()` deserializes and calls `handler(intent)` inline. `max_ack_pending=1` serializes messages, but with no priority awareness — a Captain directive waits behind a routine thread notification.

2. **Proactive loop** (`proactive.py:571`): `_think_for_agent()` calls `agent.handle_intent(intent)` directly, bypassing IntentBus entirely. The 120s timer iterates all agents sequentially with stagger delay.

Neither path knows about the other. An agent cannot be interrupted from a 5-minute ambient think cycle to handle a Captain @mention. There is no backpressure — if an agent is mid-cognitive-chain, incoming work is silently delayed (JetStream) or skipped entirely (proactive).

**Fix:** Interpose an `AgentCognitiveQueue` between JetStream dispatch and `agent.handle_intent()`. The queue orders work by priority. The processing loop drains highest-priority items first. The proactive loop is **unchanged** in AD-654b — it becomes an ambient-priority enqueue source in AD-654c.

## Architecture Change

**Before:**
```
JetStream consumer → agent.handle_intent() (inline, no priority)
Proactive loop    → agent.handle_intent() (direct call, timer-driven)
```

**After:**
```
JetStream consumer → queue.enqueue(intent, CRITICAL)  →  queue processor loop → agent.handle_intent()
Proactive loop    → agent.handle_intent() (unchanged — AD-654c scope)
```

The queue processor is a per-agent `asyncio.Task` that:
- Drains items by priority (CRITICAL first, NORMAL next, LOW last)
- Checks circuit breaker state at dequeue time (not enqueue)
- Checks token budget at dequeue time
- Yields to higher-priority items between cognitive chain completions
- Respects JetStream ack semantics (see Ack Semantics Matrix below)

### JetStream Ack Semantics Matrix

| Outcome | Action | Reason |
|---------|--------|--------|
| Handler success | `ack()` | Work complete, remove from stream |
| Handler error (exception) | `term()` | LLM already ran — retrying causes duplicates |
| Guard rejection (circuit breaker) | `nak(delay=60)` | Transient — agent may recover, redeliver later. Bounded by `max_deliver=10` on consumer. |
| Guard rejection (permanent) | `term()` | e.g., agent decommissioned — don't retry |
| Queue overflow (shed) | `term()` | Intentional discard of lowest-priority item |
| Shutdown (pending items) | Leave un-acked | JetStream redelivers on restart |

## Engineering Principles Compliance

- **SOLID/S:** `AgentCognitiveQueue` has one responsibility — priority-ordered work intake and dispatch. It does NOT run cognitive chains, post to ward room, or manage budgets. It asks "should I process this?" and delegates to the agent.
- **SOLID/I:** New `AgentCognitiveQueueProtocol` in `protocols.py` — narrow interface that consumers depend on (enqueue, drain, shutdown). Follows the existing `@runtime_checkable Protocol` pattern (9 existing protocols). Uses concrete types (`IntentMessage`, `Priority`), not `Any`.
- **SOLID/O:** IntentBus `_on_dispatch()` callback extended to enqueue instead of direct call. Existing `send()` and `dispatch_async()` preserved.
- **SOLID/D:** Queue depends on `Priority` enum (existing in `types.py:76-96`), not concrete agent classes. Dequeue checks use injected callbacks for circuit breaker and budget queries.
- **Law of Demeter:** Queue does not reach into agent internals. It calls `agent.handle_intent(intent)` — the same public API both paths already use. The existing `handler.__self__` reach-through in `_on_dispatch()` (lines 164-170) is replaced with an injected `record_response` callback — see Section 5a.
- **DRY:** Reuses the existing `Priority` enum with its `classify()` method. Does NOT create a separate priority system.
- **Fail Fast:** Queue overflow → shed lowest-priority item + emit `QUEUE_ITEM_SHED` event + log at priority-appropriate level (CRITICAL shed = error, NORMAL = warning, LOW = debug). Never silently drop CRITICAL items.
- **Cloud-Ready:** In-memory queue is intentional — JetStream is the durable layer. Queue is volatile; if the process dies, JetStream redelivers unacked messages on restart.

---

## Section 1: Priority Enum Verification (No Changes)

**File:** `src/probos/types.py`

The existing `Priority` enum (lines 76-96) already has the three tiers needed:

```python
class Priority(StrEnum):
    CRITICAL = "critical"  # Captain, @mentions, DMs → "immediate" in UAAA paper
    NORMAL = "normal"      # Ward room, standard intents → "soon" in UAAA paper
    LOW = "low"            # Proactive think cycles → "ambient" in UAAA paper
```

The existing `Priority.classify()` method (lines 89-96) correctly classifies:
- Captain posts, @mentions, DMs → `CRITICAL`
- `proactive_think` → `LOW`
- Everything else → `NORMAL`

**Signature:** `Priority.classify(*, intent: str = "", is_captain: bool = False, was_mentioned: bool = False) -> Priority`

**Action:** No changes to `types.py`. Document in code comments within the queue class that `CRITICAL` = immediate (<10s), `NORMAL` = soon (30-60s), `LOW` = ambient (5min). The UAAA paper's three-tier model maps 1:1 to the existing enum.

---

## Section 2: EventType Additions

**File:** `src/probos/events.py`

Add four new event types to the `EventType` enum. Place after the existing `BOOT_CAMP_*` / `TIERED_TRUST_*` event types, before any `# Sub-task` or subsequent section separator:

```python
# ── Agent Cognitive Queue (AD-654b) ─────────────────────────────
QUEUE_ITEM_ENQUEUED = "queue_item_enqueued"
QUEUE_ITEM_DEQUEUED = "queue_item_dequeued"
QUEUE_ITEM_SHED = "queue_item_shed"
QUEUE_OVERFLOW = "queue_overflow"
```

`QUEUE_ITEM_DEQUEUED` includes a `wait_ms` field measuring time between enqueue and dequeue — this is the queue latency metric for VitalsMonitor observability.

These are diagnostic events — they do NOT need subscribers initially. They enable future VitalsMonitor observation and HXI dashboard visibility.

**IMPORTANT:** All emit calls in the queue implementation MUST use `EventType.QUEUE_ITEM_ENQUEUED.value` etc., not raw strings. This is the project convention — grep for `EventType.` in `proactive.py` or `cognitive_agent.py` for examples.

---

## Section 3: AgentCognitiveQueueProtocol

**File:** `src/probos/protocols.py`

Add a new protocol after `EventEmitterProtocol` (line 109). Follow the existing pattern — `@runtime_checkable`, docstring, `...` method bodies.

**IMPORTANT:** Use concrete types from `probos.types` (`IntentMessage`, `Priority`), not `Any`. This is SOLID/I — the protocol should express what it actually expects. `IntentMessage` and `Priority` are both defined in `probos.types` (lines 50 and 76), which is safe to import from `protocols.py` without circular dependencies.

```python
from probos.types import IntentMessage, Priority  # Add to existing imports at top


@runtime_checkable
class AgentCognitiveQueueProtocol(Protocol):
    """Priority-ordered cognitive work queue for a single agent (AD-654b).

    Interposed between activation sources (JetStream, proactive loop)
    and agent.handle_intent(). Items are dequeued by priority:
    CRITICAL first, NORMAL next, LOW last.
    """

    def enqueue(
        self,
        intent: IntentMessage,
        priority: Priority,
        *,
        js_msg: Any | None = None,
    ) -> bool:
        """Add a work item to the queue.

        Args:
            intent: IntentMessage to process.
            priority: Priority enum value (CRITICAL/NORMAL/LOW).
            js_msg: JetStream message for ack/term semantics. None for
                    proactive-loop items (no JetStream backing).
                    Typed as Any because the concrete type is nats.aio.msg.Msg
                    and we don't want nats-py as a protocol layer dependency.

        Returns:
            True if enqueued, False if shed (queue full, lowest priority shed).
        """
        ...

    def pending_count(self) -> int:
        """Number of items currently in the queue."""
        ...

    def is_processing(self) -> bool:
        """Whether the queue processor loop is actively running a cognitive chain."""
        ...

    async def start(self) -> None:
        """Start the queue processor loop (asyncio.Task)."""
        ...

    async def shutdown(self) -> None:
        """Stop the processor loop. In-flight handler gets grace period, then cancel."""
        ...
```

---

## Section 4: AgentCognitiveQueue Implementation

**File:** `src/probos/cognitive/queue.py` (NEW)

### 4a: Module docstring and imports

```python
"""AD-654b: Agent Cognitive Queue — Priority Mailbox.

Actor Model mailbox pattern: each agent gets a priority-ordered inbox
that replaces inline handler dispatch. Activation sources (JetStream
consumers, proactive loop) enqueue work items. A per-agent processor
loop drains items by priority: CRITICAL → NORMAL → LOW.

Context travels with the event (UAAA Principle 3): the IntentMessage
carries all context needed for the cognitive chain.

Priority mapping to UAAA research paper:
    CRITICAL = immediate (< 10s) — Captain, @mentions, DMs, game moves
    NORMAL   = soon (30-60s) — ward room threads, peer questions
    LOW      = ambient (5 min) — proactive observations, monitoring
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from probos.events import EventType
from probos.types import Priority

logger = logging.getLogger(__name__)
```

### 4b: QueueItem dataclass

```python
@dataclass(order=False)
class QueueItem:
    """A single work item in the cognitive queue.

    Items are NOT compared by dataclass ordering — the queue uses
    explicit priority sorting. Fields:

    - intent: The IntentMessage to process
    - priority: CRITICAL/NORMAL/LOW
    - enqueued_at: monotonic timestamp for FIFO within same priority
    - js_msg: JetStream message object for ack/term (None if from proactive loop)
    """

    intent: Any  # IntentMessage (Any to avoid circular import at runtime)
    priority: Priority
    enqueued_at: float = field(default_factory=time.monotonic)
    js_msg: Any | None = None  # JetStream msg for ack/term semantics
```

### 4c: AgentCognitiveQueue class

```python
# Priority sort order: lower number = higher priority (dequeued first)
_PRIORITY_ORDER: dict[Priority, int] = {
    Priority.CRITICAL: 0,
    Priority.NORMAL: 1,
    Priority.LOW: 2,
}

# Log levels by priority of shed/dropped item
_SHED_LOG_LEVEL: dict[Priority, int] = {
    Priority.CRITICAL: logging.ERROR,    # Shedding CRITICAL = serious
    Priority.NORMAL: logging.WARNING,    # Shedding NORMAL = notable
    Priority.LOW: logging.DEBUG,         # Shedding LOW = expected under load
}

# Default capacity. Generous — JetStream already rate-limits via max_ack_pending.
_DEFAULT_MAX_QUEUE_SIZE = 50


class AgentCognitiveQueue:
    """Priority-ordered cognitive work queue for a single agent.

    Thread-safe via asyncio (single event loop, no threading).
    """

    def __init__(
        self,
        *,
        agent_id: str,
        handler: Callable[[Any], Awaitable[Any]],
        max_size: int = _DEFAULT_MAX_QUEUE_SIZE,
        should_process: Callable[[Any, Any], tuple[bool, bool]] | None = None,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        """
        Args:
            agent_id: Agent this queue belongs to.
            handler: async callable — agent.handle_intent(intent).
            max_size: Maximum queue depth. Overflow sheds lowest-priority item.
            should_process: Optional guard — called at dequeue time with
                (QueueItem, js_msg). Returns (allow: bool, transient: bool).
                allow=False, transient=True → nak(delay=60) for redelivery.
                allow=False, transient=False → term() permanently.
                If None, all items are processed.
            emit_event: Optional event emitter for diagnostic events.
        """
        self._agent_id = agent_id
        self._handler = handler
        self._max_size = max_size
        self._should_process = should_process
        self._emit_event = emit_event

        self._queue: list[QueueItem] = []
        self._processing = False
        self._task: asyncio.Task[None] | None = None
        self._cleanup_tasks: set[asyncio.Task] = set()  # tracked background tasks
        self._notify = asyncio.Event()
        self._shutdown_requested = False

    def enqueue(
        self,
        intent: Any,
        priority: Priority,
        *,
        js_msg: Any | None = None,
    ) -> bool:
        """Add a work item. Returns True if accepted, False if shed.

        Must be called from a running asyncio event loop if js_msg is provided
        (the shed path uses create_task for term()). Non-JetStream callers
        (proactive loop, fallback path) pass js_msg=None and are safe from
        any context.
        """
        item = QueueItem(intent=intent, priority=priority, js_msg=js_msg)

        if len(self._queue) >= self._max_size:
            # Shed the lowest-priority, oldest item
            if not self._queue:
                return False

            # Find worst item (highest priority number = lowest priority)
            worst_idx = max(
                range(len(self._queue)),
                key=lambda i: (
                    _PRIORITY_ORDER.get(self._queue[i].priority, 99),
                    self._queue[i].enqueued_at,
                ),
            )
            worst = self._queue[worst_idx]

            # Don't shed if incoming item is lower priority than worst
            incoming_order = _PRIORITY_ORDER.get(priority, 99)
            worst_order = _PRIORITY_ORDER.get(worst.priority, 99)
            if incoming_order >= worst_order:
                # Incoming is same or lower priority — reject incoming
                log_level = _SHED_LOG_LEVEL.get(priority, logging.WARNING)
                logger.log(
                    log_level,
                    "AD-654b: Queue full for %s, rejecting %s (%s)",
                    self._agent_id[:12], intent.intent, priority.value,
                )
                if self._emit_event:
                    self._emit_event(EventType.QUEUE_OVERFLOW.value, {
                        "agent_id": self._agent_id,
                        "rejected_intent": intent.intent,
                        "rejected_priority": priority.value,
                        "queue_size": len(self._queue),
                    })
                return False

            # Shed worst to make room for higher-priority incoming
            self._queue.pop(worst_idx)
            # term() the shed JetStream message — it won't be processed
            if worst.js_msg:
                task = asyncio.get_running_loop().create_task(worst.js_msg.term())
                self._cleanup_tasks.add(task)
                task.add_done_callback(self._cleanup_tasks.discard)
            log_level = _SHED_LOG_LEVEL.get(worst.priority, logging.WARNING)
            logger.log(
                log_level,
                "AD-654b: Queue full for %s, shedding %s (%s) for %s (%s)",
                self._agent_id[:12],
                worst.intent.intent, worst.priority.value,
                intent.intent, priority.value,
            )
            if self._emit_event:
                self._emit_event(EventType.QUEUE_ITEM_SHED.value, {
                    "agent_id": self._agent_id,
                    "shed_intent": worst.intent.intent,
                    "shed_priority": worst.priority.value,
                    "incoming_intent": intent.intent,
                    "incoming_priority": priority.value,
                })

        self._queue.append(item)
        if self._emit_event:
            self._emit_event(EventType.QUEUE_ITEM_ENQUEUED.value, {
                "agent_id": self._agent_id,
                "intent": intent.intent,
                "priority": priority.value,
                "queue_depth": len(self._queue),
            })
        # Wake up processor
        self._notify.set()
        return True

    def pending_count(self) -> int:
        """Number of items waiting to be processed."""
        return len(self._queue)

    def is_processing(self) -> bool:
        """Whether the processor is actively running a cognitive chain."""
        return self._processing

    def _dequeue(self) -> QueueItem | None:
        """Remove and return the highest-priority item (FIFO within tier)."""
        if not self._queue:
            return None
        # Sort: lowest priority order number first, then oldest first
        best_idx = min(
            range(len(self._queue)),
            key=lambda i: (
                _PRIORITY_ORDER.get(self._queue[i].priority, 99),
                self._queue[i].enqueued_at,
            ),
        )
        return self._queue.pop(best_idx)

    async def start(self) -> None:
        """Start the queue processor loop."""
        if self._task and not self._task.done():
            return
        self._shutdown_requested = False
        self._task = asyncio.create_task(
            self._processor_loop(),
            name=f"cognitive-queue-{self._agent_id[:12]}",
        )

    async def shutdown(self) -> None:
        """Stop the processor, give in-flight handler up to 10s to finish, then force cancel.

        Pending JetStream messages are left UN-ACKED — JetStream server retains
        them and redelivers on consumer reconnect. Clearing the local queue list
        is safe because it only removes the in-memory references; the server-side
        un-acked messages remain.
        """
        self._shutdown_requested = True
        self._notify.set()  # Wake up if sleeping

        if self._task and not self._task.done():
            # Give in-flight handler up to 10s to complete, then force cancel
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None

        # Wait for cleanup tasks (term() calls from shedding) with timeout
        if self._cleanup_tasks:
            done, pending = await asyncio.wait(
                self._cleanup_tasks, timeout=5.0
            )
            for t in pending:
                t.cancel()
            self._cleanup_tasks.clear()

        # Pending JetStream messages: leave UN-ACKED for redelivery.
        # Do NOT term() them — they represent valid work that should be
        # processed when the agent restarts. Clearing the local list is safe —
        # JetStream server retains un-acked messages and redelivers on
        # consumer reconnect.
        remaining = len(self._queue)
        if remaining:
            logger.info(
                "AD-654b: Shutdown %s — %d pending items left for JetStream redelivery",
                self._agent_id[:12], remaining,
            )
        self._queue.clear()

    async def _processor_loop(self) -> None:
        """Main processing loop — drain queue by priority.

        Wakeup race fix: clear THEN check THEN wait. If an item is enqueued
        between clear() and the emptiness check, _notify will be set again
        and wait() returns immediately.
        """
        while not self._shutdown_requested:
            # Clear notification BEFORE checking queue — prevents race where
            # enqueue sets _notify between emptiness check and wait.
            self._notify.clear()

            if not self._queue:
                try:
                    await asyncio.wait_for(self._notify.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    return

            while self._queue and not self._shutdown_requested:
                item = self._dequeue()
                if item is None:
                    break

                # Emit dequeue event with wait latency
                wait_ms = (time.monotonic() - item.enqueued_at) * 1000
                if self._emit_event:
                    self._emit_event(EventType.QUEUE_ITEM_DEQUEUED.value, {
                        "agent_id": self._agent_id,
                        "intent": item.intent.intent,
                        "priority": item.priority.value,
                        "wait_ms": round(wait_ms, 1),
                        "queue_depth": len(self._queue),
                    })

                # Dequeue-time guard (circuit breaker, budget, etc.)
                if self._should_process:
                    allow, transient = self._should_process(item, item.js_msg)
                    if not allow:
                        if item.js_msg:
                            try:
                                if transient:
                                    # Transient rejection (circuit breaker) — redeliver later
                                    await item.js_msg.nak(delay=60)
                                else:
                                    # Permanent rejection — don't retry
                                    await item.js_msg.term()
                            except Exception:
                                pass
                        log_level = _SHED_LOG_LEVEL.get(item.priority, logging.DEBUG)
                        logger.log(
                            log_level,
                            "AD-654b: Guard rejected %s for %s (transient=%s)",
                            item.intent.intent, self._agent_id[:12], transient,
                        )
                        continue

                # Process the item
                self._processing = True
                try:
                    await self._handler(item.intent)
                    # ack() JetStream message on success
                    if item.js_msg:
                        try:
                            await item.js_msg.ack()
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning(
                        "AD-654b: Handler error for %s (%s): %s",
                        self._agent_id[:12], item.intent.intent, e,
                    )
                    # term() on error — LLM already ran, don't retry
                    if item.js_msg:
                        try:
                            await item.js_msg.term()
                        except Exception:
                            pass
                finally:
                    self._processing = False
```

**Key design decisions:**
- `_queue` is a `list`, not `heapq` — queue size is small (≤50), linear scan is simpler and debuggable. Premature optimization for 50 items is YAGNI.
- `should_process` callback is checked at dequeue time, not enqueue time. Reason: circuit breaker state and token budget change between enqueue and dequeue. An item enqueued while budget was available should be rechecked when it's about to be processed.
- `should_process` returns `(allow, transient)` tuple — transient rejections use `nak(delay=60)` for redelivery (circuit breaker may recover), permanent rejections use `term()`.
- `js_msg` ack/term is handled by the queue, not the handler. The handler (`agent.handle_intent()`) is unaware of JetStream — it just processes an `IntentMessage`. This is **SOLID/S**: the queue owns delivery semantics, the agent owns cognition.
- The processor loop yields between items (Python's `await` cooperates with the event loop). Higher-priority items enqueued during a cognitive chain execute next.
- `_notify.clear()` happens BEFORE the emptiness check — prevents the wakeup race where enqueue sets the event between check and wait.
- `_cleanup_tasks` tracks fire-and-forget `term()` calls — prevents task leak warnings. Uses `add_done_callback(discard)` for automatic cleanup.
- Shutdown leaves pending JetStream messages UN-ACKED (not `term()`). JetStream redelivers them on restart. Only the in-flight handler gets a grace period.
- Log levels are tiered by priority of the shed/dropped item: CRITICAL shed = `error`, NORMAL = `warning`, LOW = `debug`.

---

## Section 5: IntentBus JetStream Consumer Integration

**File:** `src/probos/mesh/intent.py`

### 5a: Fix `handler.__self__` Law of Demeter violation

The existing `_on_dispatch()` (lines 164-170) reaches through `handler.__self__._runtime.ward_room_router` to call `record_agent_response()`. This violates Law of Demeter — the callback shouldn't know the agent's internal structure.

**Fix:** Inject a `record_response` callback into IntentBus during startup. The callback is a simple `Callable[[str, str], None]` that maps `(agent_id, thread_id)` → `ward_room_router.record_agent_response()`.

Add to `IntentBus.__init__()` (after `self._intent_index` initialization):

```python
# AD-654b: Per-agent cognitive queues
self._agent_queues: dict[str, Any] = {}  # agent_id -> AgentCognitiveQueue

# AD-654b: Injected callback for response recording (replaces handler.__self__ reach-through)
self._record_response: Callable[[str, str], None] | None = None  # (agent_id, thread_id)
```

Add these methods after `dispatch_async()`:

```python
def set_record_response(self, callback: Callable[[str, str], None]) -> None:
    """AD-654b: Inject response recording callback.

    Replaces the handler.__self__._runtime.ward_room_router reach-through
    that violated Law of Demeter. Called from finalize.py with
    ward_room_router.record_agent_response.
    """
    self._record_response = callback

def register_queue(self, agent_id: str, queue: Any) -> None:
    """Register an agent's cognitive queue (AD-654b)."""
    self._agent_queues[agent_id] = queue

def unregister_queue(self, agent_id: str) -> None:
    """Remove an agent's cognitive queue (AD-654b)."""
    self._agent_queues.pop(agent_id, None)
```

Wire `unregister_queue` into the existing `unsubscribe()` method (line ~197). Add one line after `self._subscribers.pop(agent_id, None)`:

```python
def unsubscribe(self, agent_id: str) -> None:
    """Remove an agent's subscription and intent index entries."""
    self._subscribers.pop(agent_id, None)
    self.unregister_queue(agent_id)  # AD-654b: clean up cognitive queue
    for agent_set in self._intent_index.values():
        ...
```

Add `_get_agent_queue` in the same block:

```python
def _get_agent_queue(self, agent_id: str) -> Any | None:
    """Get the cognitive queue for an agent (AD-654b)."""
    return self._agent_queues.get(agent_id)
```

### 5b: Modify `_js_subscribe_agent_dispatch()` (lines 143-180)

Replace the current `_on_dispatch()` callback. Instead of calling `handler(intent)` inline, enqueue to the agent's cognitive queue. The queue takes over ack/term responsibility.

Replace the `_on_dispatch` inner function and everything after it (lines 155-180) with:

```python
    async def _on_dispatch(msg: Any) -> None:
        """JetStream dispatch callback — deserialize and enqueue.

        AD-654b: Enqueues to cognitive queue instead of inline processing.
        The queue manages ack/term, priority ordering, and handler dispatch.
        """
        try:
            intent_msg = self._deserialize_intent(msg.data)
            # AD-654a/BF-198: Record response BEFORE handler runs to close
            # the proactive-loop race window.
            # Uses injected callback instead of handler.__self__ reach-through.
            if self._record_response:
                _thread_id = intent_msg.params.get("thread_id", "")
                if _thread_id:
                    self._record_response(intent_msg.target_agent_id, _thread_id)

            # AD-654b: Enqueue with priority classification
            queue = self._get_agent_queue(agent_id)
            if queue:
                priority = Priority.classify(
                    intent=intent_msg.intent,
                    is_captain=intent_msg.params.get("is_captain", False),
                    was_mentioned=intent_msg.params.get("was_mentioned", False),
                )
                accepted = queue.enqueue(intent_msg, priority, js_msg=msg)
                if not accepted:
                    # Queue rejected it (full + lower priority). term() it.
                    await msg.term()
            else:
                # No queue — fall back to direct handler.
                # This is normal for substrate agents (IntrospectAgent, VitalsMonitor, etc.)
                # which don't have cognitive queues. Log at debug, not warning.
                logger.debug("AD-654b: No queue for %s, direct dispatch", agent_id[:12])
                await handler(intent_msg)
                await msg.ack()
        except Exception as e:
            logger.warning(
                "AD-654b: Dispatch callback error for %s: %s",
                agent_id[:8], e,
            )
            await msg.term()

    # Durable name must be NATS-safe (alphanumeric + dash).
    durable_name = f"agent-dispatch-{agent_id}"

    # AD-654b: max_deliver=10 bounds nak() redelivery loops.
    # With circuit breaker nak(delay=60) + max_deliver=10, a stuck breaker
    # causes at most 10 redeliveries (~10 min) before JetStream auto-discards.
    # Without this, nak loops are unbounded.
    sub = await self._nats_bus.js_subscribe(
        subject,
        _on_dispatch,
        durable=durable_name,
        stream="INTENT_DISPATCH",
        max_ack_pending=1,
        ack_wait=300,
        manual_ack=True,
        max_deliver=10,
    )
    if sub:
        logger.debug("AD-654b: JetStream dispatch consumer for %s", agent_id[:12])
```

**NOTE:** `max_deliver=10` is new in AD-654b. The existing AD-654a consumer at `intent.py:185-192` does not set `max_deliver` (defaults to unlimited). AD-654b changes this because the new `nak(delay=60)` path for circuit breaker rejection would otherwise cause unbounded redelivery for persistently-tripped agents.

**Key changes from AD-654a version:**
1. `handler.__self__` reach-through replaced with `self._record_response` injected callback
2. Enqueues to cognitive queue instead of inline `handler(intent)` call
3. Queue manages ack/term — callback does NOT ack on enqueue
4. "No queue" fallback logs at `debug` level — substrate agents intentionally skip queues

### 5b.5: Add `max_deliver` Parameter to `NATSBus.js_subscribe()`

**File:** `src/probos/mesh/nats_bus.py`

The `max_deliver=10` in Section 5b requires plumbing through `NATSBus.js_subscribe()`, which currently does not accept this parameter.

**NATSBus (real, line ~424):**

Add `max_deliver: int | None = None` parameter after `manual_ack`:

```python
async def js_subscribe(
    self,
    subject: str,
    callback: MessageCallback,
    durable: str | None = None,
    stream: str | None = None,
    max_ack_pending: int | None = None,
    ack_wait: int | None = None,
    manual_ack: bool = False,
    max_deliver: int | None = None,  # AD-654b
) -> Any:
```

Thread it into the `ConsumerConfig` construction (lines ~475-482). The existing guard creates a `ConsumerConfig` only when `max_ack_pending` or `ack_wait` is set. Extend the condition:

```python
if max_ack_pending is not None or ack_wait is not None or max_deliver is not None:
    from nats.js.api import ConsumerConfig
    config_kwargs: dict[str, Any] = {}
    if max_ack_pending is not None:
        config_kwargs["max_ack_pending"] = max_ack_pending
    if ack_wait is not None:
        config_kwargs["ack_wait"] = ack_wait
    if max_deliver is not None:
        config_kwargs["max_deliver"] = max_deliver
    subscribe_kwargs["config"] = ConsumerConfig(**config_kwargs)
```

Add `max_deliver` to the `_active_subs` kwargs dict (lines ~491-497) so prefix-change re-subscription preserves it:

```python
"kwargs": {
    k: v for k, v in {
        "durable": durable,
        "stream": stream,
        "max_ack_pending": max_ack_pending,
        "ack_wait": ack_wait,
        "manual_ack": manual_ack if manual_ack else None,
        "max_deliver": max_deliver,
    }.items() if v is not None
},
```

**MockNATSBus (line ~832):**

Add the same `max_deliver: int | None = None` parameter. Store in `_active_subs` kwargs dict (same pattern as real). MockNATSBus does not enforce `max_deliver` — it's test-visible metadata only.

```python
async def js_subscribe(
    self,
    subject: str,
    callback: MessageCallback,
    durable: str | None = None,
    stream: str | None = None,
    max_ack_pending: int | None = None,
    ack_wait: int | None = None,
    manual_ack: bool = False,
    max_deliver: int | None = None,  # AD-654b
) -> str:
```

And in the `_active_subs` kwargs dict (lines ~851-858):

```python
"kwargs": {
    k: v for k, v in {
        "durable": durable,
        "stream": stream,
        "max_ack_pending": max_ack_pending,
        "ack_wait": ack_wait,
        "manual_ack": manual_ack if manual_ack else None,
        "max_deliver": max_deliver,
    }.items() if v is not None
},
```

**NATSBusProtocol (protocols.py line ~184):**

Update the Protocol signature to match:

```python
async def js_subscribe(self, subject: str, callback: Any, durable: str | None = None, stream: str | None = None, max_ack_pending: int | None = None, ack_wait: int | None = None, manual_ack: bool = False, max_deliver: int | None = None) -> Any: ...
```

### 5c: Import Priority

Add to the imports at the top of `intent.py`:

```python
from probos.types import Priority
```

---

## Section 6: `is_captain` Propagation

**File:** `src/probos/ward_room_router.py`

`Priority.classify()` needs `is_captain` to classify Captain posts as CRITICAL. Currently, `is_captain` is computed at `ward_room_router.py:268` (`is_captain = (author_id == "captain")`) but NOT propagated to the intent params built at lines 518-536.

Add `is_captain` to the intent params dict at line 529 (after `"was_mentioned": agent_id in mentioned_agent_ids,`):

```python
                    "was_mentioned": agent_id in mentioned_agent_ids,
                    "is_captain": is_captain,  # AD-654b: For Priority.classify()
                    "is_dm_channel": getattr(channel, 'channel_type', '') == "dm",
```

**Verification:** `is_captain` is already in scope at line 518 — it's computed at line 268 as `is_captain = (author_id == "captain")`.

---

## Section 7: Startup Wiring — Queue Creation and Lifecycle

**File:** `src/probos/startup/finalize.py`

### 7a: Create queues and inject response callback

The queues must be created BEFORE `create_dispatch_consumers()` at line 186. Place this block after the proactive loop start (line 80) and trust dampening wiring (line 90), and before the emergence metrics wiring (line 92). The proactive loop local variable `proactive_loop` is available at this point.

```python
# ── AD-654b: Agent Cognitive Queues ──────────────────────────────
from probos.cognitive.queue import AgentCognitiveQueue
from probos.cognitive.circuit_breaker import BreakerState

_intent_bus = runtime.intent_bus

if _intent_bus:
    # AD-654b: Inject response recording callback (replaces handler.__self__ reach-through)
    _wr_router = getattr(runtime, 'ward_room_router', None)
    if _wr_router:
        _intent_bus.set_record_response(_wr_router.record_agent_response)

    # Create per-agent cognitive queues for crew agents.
    # Guard uses lazy lookup of proactive_loop via runtime.proactive_loop
    # (attribute at runtime.py:521) rather than capturing the local variable.
    # This is robust to wiring order — if proactive_loop isn't set yet,
    # the guard simply skips the breaker check (allows processing).
    def _make_should_process(agent_ref: Any) -> Callable:
        """Create dequeue-time guard for an agent.

        Returns (allow, transient) tuple:
        - (True, _) → process the item
        - (False, True) → transient rejection, nak(delay=60) for redelivery
        - (False, False) → permanent rejection, term()

        Uses lazy lookup: runtime.proactive_loop resolved at dequeue time,
        not at queue construction time. Safe against wiring-order changes.
        """
        def _guard(item: Any, js_msg: Any) -> tuple[bool, bool]:
            # Lazy lookup — resolved at dequeue time, not construction time
            _pl = getattr(runtime, 'proactive_loop', None)
            if _pl:
                breaker = _pl.circuit_breaker
                status = breaker.get_status(agent_ref.id)
                if status.get("state") == BreakerState.OPEN.value:
                    return (False, True)  # Transient — nak for redelivery
            return (True, False)
        return _guard

    _queue_count = 0
    for agent in runtime.registry.all():
        if not is_crew_agent(agent, runtime.ontology):
            continue

        queue = AgentCognitiveQueue(
            agent_id=agent.id,
            handler=agent.handle_intent,
            should_process=_make_should_process(agent),
            emit_event=runtime.emit_event,
        )
        _intent_bus.register_queue(agent.id, queue)
        await queue.start()
        _queue_count += 1

    logger.info("Startup [finalize]: AD-654b cognitive queues created for %d agents", _queue_count)
```

**Key changes from original:**
1. `_make_should_process` factory function is defined OUTSIDE the loop (not inside it) — avoids creating a new function definition per iteration. Takes only `agent_ref`, not `proactive_ref`.
2. Guard uses **lazy lookup** of `runtime.proactive_loop` (public attribute, `runtime.py:521`) at dequeue time — not captured at construction time. Safe against finalize.py wiring-order changes.
3. Guard returns `(allow, transient)` tuple matching the ack semantics matrix.
4. `emit_event` uses `runtime.emit_event` (public API at `runtime.py:763`) — follows the same pattern used by trust dampening wiring at line 89.
5. Response callback injection happens here: `_intent_bus.set_record_response(_wr_router.record_agent_response)`.

**Signature references:**
- `is_crew_agent(agent, ontology)` is already imported in `finalize.py` (line 17: `from probos.crew_utils import is_crew_agent`)
- `runtime.proactive_loop` — `runtime.py:521`, type: `ProactiveCognitiveLoop | None`
- `runtime.emit_event(event, data)` — `runtime.py:763`, signature: `def emit_event(self, event: BaseEvent | str, data: dict[str, Any] | None = None) -> None`
- `BreakerState` — `from probos.cognitive.circuit_breaker import BreakerState`

### 7b: Queue shutdown

**File:** `src/probos/startup/shutdown.py`

Add queue shutdown BEFORE the proactive loop stops (queue must drain before the event loop closes):

```python
# AD-654b: Shutdown cognitive queues
if hasattr(runtime, 'intent_bus') and runtime.intent_bus:
    for agent_id, queue in list(runtime.intent_bus._agent_queues.items()):
        await queue.shutdown()
    logger.info("Shutdown: cognitive queues stopped")
```

---

## Section 8: Fallback Path — No NATS

**File:** `src/probos/mesh/intent.py`

The existing `dispatch_async()` fallback (lines 420-450 from AD-654a) uses `create_task(handler(intent))` when NATS is disconnected. Add queue-based dispatch as a higher-priority fallback, keeping the `create_task` path as the bottom-tier fallback for substrate agents that don't have queues.

In `dispatch_async()`, add this block **BEFORE** the existing `handler = self._subscribers.get(...)` line (line 421). The new code runs first; the existing `create_task` fallback only executes if no queue is registered (substrate agents) or if `enqueue()` returns False (queue full, lower priority rejected):

```python
        # AD-654b: Try cognitive queue even when NATS is down.
        # This PRECEDES the existing create_task fallback — if the queue
        # accepts the item, return early. If no queue exists (substrate agents)
        # or enqueue is rejected (full + lower priority), fall through to
        # the create_task direct-dispatch path below.
        queue = self._get_agent_queue(intent.target_agent_id)
        if queue:
            priority = Priority.classify(
                intent=intent.intent,
                is_captain=intent.params.get("is_captain", False),
                was_mentioned=intent.params.get("was_mentioned", False),
            )
            # js_msg=None — no JetStream backing for fallback path
            if queue.enqueue(intent, priority):
                return
            # enqueue returned False — fall through to create_task

        # Existing AD-654a fallback: direct handler invocation for agents
        # without cognitive queues (substrate agents) or when queue is full.
```

**IMPORTANT:** Do NOT remove the existing `create_task(handler(intent))` fallback code. The new queue block goes BEFORE it. The `create_task` path is the bottom-tier fallback for substrate agents (IntrospectAgent, VitalsMonitor, etc.) that never get cognitive queues.

---

## Section 9: Tests

**File:** `tests/test_ad654b_cognitive_queue.py` (NEW)

Write ~24 tests covering:

### Priority ordering (5 tests)
1. CRITICAL dequeued before NORMAL
2. NORMAL dequeued before LOW
3. FIFO within same priority tier
4. Mixed priorities — verify exact dequeue order
5. Empty queue returns None from `_dequeue()`

### Enqueue/overflow (4 tests)
6. Enqueue returns True when queue has space
7. Queue at capacity — incoming CRITICAL sheds existing LOW
8. Queue at capacity — incoming LOW rejected (doesn't shed CRITICAL)
9. Shed item's JetStream msg gets `term()` called

### Processor loop (5 tests)
10. Processor calls handler with correct intent
11. Handler success → JetStream `ack()` called
12. Handler error → JetStream `term()` called (no retry)
13. `should_process` guard returning `(False, True)` → item skipped, `nak(delay=60)` called (transient)
14. `should_process` guard returning `(False, False)` → item skipped, `term()` called (permanent)

### Priority preemption (1 test)
15. CRITICAL item enqueued during NORMAL processing → CRITICAL processed next after NORMAL handler completes. Verify: enqueue NORMAL, let handler start (use asyncio.Event to synchronize), enqueue CRITICAL, let handler complete, verify CRITICAL is dequeued next (not another NORMAL if one exists).

### Integration (4 tests)
16. IntentBus `register_queue()`/`_get_agent_queue()` round-trip
17. JetStream `_on_dispatch()` enqueues with correct priority (Captain → CRITICAL, via `is_captain=True` in params)
18. JetStream `_on_dispatch()` enqueues with correct priority (normal post → NORMAL)
19. Fallback path uses queue when available — enqueue returns True, create_task NOT called
19b. Fallback path falls through to `create_task(handler)` when no queue is registered (substrate agent regression)

### Lifecycle (3 tests)
20. `start()` creates asyncio task
21. `shutdown()` does NOT `term()` pending JetStream items — assert `msg.term.assert_not_called()` on pending items after shutdown, confirming messages are left for JetStream redelivery
22. `pending_count()` and `is_processing()` accuracy

### Event emission (1 test)
23. QUEUE_ITEM_DEQUEUED event includes `wait_ms` latency metric

**Test helpers:**

```python
from unittest.mock import AsyncMock, MagicMock
from probos.cognitive.queue import AgentCognitiveQueue, QueueItem
from probos.types import Priority

def _make_intent(intent_name="ward_room_notification", **params):
    """Create a minimal IntentMessage-like object."""
    mock = MagicMock()
    mock.intent = intent_name
    mock.params = params
    mock.target_agent_id = "test-agent"
    return mock

def _make_js_msg():
    """Create a mock JetStream message with ack/term/nak."""
    msg = AsyncMock()
    msg.ack = AsyncMock()
    msg.term = AsyncMock()
    msg.nak = AsyncMock()
    return msg
```

---

## Verification

```bash
# New tests
pytest tests/test_ad654b_cognitive_queue.py -v

# AD-654a regression (async dispatch still works)
pytest tests/test_ad654a_async_dispatch.py -v

# Ward Room regression
pytest tests/test_ward_room.py tests/test_routing.py tests/test_ward_room_agents.py -v

# Intent bus regression
pytest tests/test_intent.py -v

# Proactive loop regression (unchanged in AD-654b)
pytest tests/test_proactive.py -v

# Full suite
pytest -n auto
```

---

## What This Does NOT Do

1. **Does NOT change the proactive loop.** `proactive_think` intents continue via direct `agent.handle_intent()` call. The proactive loop becomes an ambient-priority enqueue source in AD-654c.
2. **Does NOT add a TaskEvent protocol.** That is AD-654c scope.
3. **Does NOT change `send()` or `broadcast()`.** Synchronous request/reply callers are unaffected.
4. **Does NOT add Ward Room @mention priority escalation.** That is AD-654d scope (WardRoom as TaskEvent emitter).
5. **Does NOT add queue depth to VitalsMonitor.** Queue diagnostic events are emitted but not consumed yet. VitalsMonitor integration is a follow-up.
6. **Does NOT modify `proactive.py`.** The proactive loop is completely unchanged. Its integration with the cognitive queue is AD-654c scope.

## Files Changed

| File | Change |
|------|--------|
| `src/probos/cognitive/queue.py` | NEW — `AgentCognitiveQueue`, `QueueItem` |
| `src/probos/events.py` | Add 4 queue EventTypes (including QUEUE_ITEM_DEQUEUED) |
| `src/probos/protocols.py` | Add `AgentCognitiveQueueProtocol` (concrete types, not Any) |
| `src/probos/mesh/intent.py` | Modify `_on_dispatch()` to enqueue; add queue registry; add `set_record_response()`; import Priority |
| `src/probos/ward_room_router.py` | Add `is_captain` to ward_room_notification intent params |
| `src/probos/startup/finalize.py` | Create queues, inject response callback |
| `src/probos/startup/shutdown.py` | Shutdown queues |
| `tests/test_ad654b_cognitive_queue.py` | NEW — ~24 tests |

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Queue adds latency to ward room response path | Low | Medium | Queue dequeue is O(n) on ≤50 items — microseconds. JetStream ack_wait=300s unchanged. |
| Circuit breaker nak(delay=60) causes redelivery storm | Low | Medium | JetStream max_ack_pending=1 limits to one message at a time. Delay provides 60s recovery window. |
| Queue processor task leak on agent recycle | Medium | Low | `shutdown()` drains in-flight + clears queue. `unregister_queue()` on unsubscribe. `_cleanup_tasks` tracked. |
| Proactive loop unchanged — no priority benefit for proactive thinks | Expected | None | By design. AD-654c integrates proactive loop with queue. AD-654b focuses on JetStream dispatch priority. |
| `_notify` wakeup race (enqueue between check and wait) | Resolved | — | Fixed in design: clear→check→wait ordering. No residual risk. |
