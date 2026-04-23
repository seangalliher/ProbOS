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
