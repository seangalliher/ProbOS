"""AD-672: Per-agent concurrency management.

Enforces a configurable ceiling on concurrent thought threads per agent,
with priority-ordered queuing for excess intents and capacity-approaching
event emission.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass
class ThreadEntry:
    """Metadata for an active thought thread."""

    thread_id: str
    intent_type: str
    priority: int
    started_at: float = field(default_factory=time.monotonic)
    resource_key: str | None = None


@dataclass
class QueuedIntent:
    """An intent waiting for a concurrency slot."""

    intent_type: str
    priority: int
    resource_key: str | None
    queued_at: float = field(default_factory=time.monotonic)
    future: asyncio.Future[str] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )
    thread_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


class ConcurrencyManager:
    """Per-agent concurrency ceiling with priority queue and arbitration."""

    def __init__(
        self,
        agent_id: str,
        max_concurrent: int = 4,
        queue_max_size: int = 10,
        capacity_warning_ratio: float = 0.75,
        emit_event_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._max_concurrent = max(1, max_concurrent)
        self._queue_max_size = max(0, queue_max_size)
        self._capacity_warning_ratio = capacity_warning_ratio
        self._emit_event_fn = emit_event_fn
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._active: dict[str, ThreadEntry] = {}
        self._queue: list[QueuedIntent] = []
        self._lock = asyncio.Lock()
        self._last_capacity_warning: float = 0.0
        self._capacity_warning_cooldown: float = 30.0

    @property
    def active_count(self) -> int:
        """Return the number of active thought threads."""
        return len(self._active)

    @property
    def queue_depth(self) -> int:
        """Return the number of queued intents."""
        return len(self._queue)

    @property
    def max_concurrent(self) -> int:
        """Return the configured concurrency ceiling."""
        return self._max_concurrent

    @property
    def at_capacity(self) -> bool:
        """Return True when active threads have reached the ceiling."""
        return self.active_count >= self._max_concurrent

    async def acquire(
        self,
        intent_type: str,
        priority: int = 5,
        resource_key: str | None = None,
    ) -> str:
        """Acquire a concurrency slot or await priority-ordered queue promotion."""
        async with self._lock:
            threshold = max(1, int(self._max_concurrent * self._capacity_warning_ratio))
            if self.active_count >= threshold and self.active_count < self._max_concurrent:
                self._emit_capacity_warning()

            if not self.at_capacity:
                await self._semaphore.acquire()
                thread_id = uuid.uuid4().hex[:12]
                self._active[thread_id] = ThreadEntry(
                    thread_id=thread_id,
                    intent_type=intent_type,
                    priority=priority,
                    resource_key=resource_key,
                )
                return thread_id

            if len(self._queue) >= self._queue_max_size:
                raise ValueError(
                    f"AD-672: Concurrency queue full for agent {self._agent_id} "
                    f"({len(self._queue)}/{self._queue_max_size}); caller should degrade"
                )

            queued_intent = QueuedIntent(
                intent_type=intent_type,
                priority=priority,
                resource_key=resource_key,
            )
            self._queue.append(queued_intent)
            self._queue.sort(key=lambda queued: (-queued.priority, queued.queued_at))
            logger.info(
                "AD-672: Intent '%s' queued for agent %s at priority=%d; "
                "active=%d/%d queue_depth=%d; waiting for release",
                intent_type,
                self._agent_id,
                priority,
                self.active_count,
                self._max_concurrent,
                len(self._queue),
            )

        return await queued_intent.future

    async def release(self, thread_id: str) -> None:
        """Release a concurrency slot and promote the next queued intent."""
        async with self._lock:
            entry = self._active.pop(thread_id, None)
            if entry is None:
                logger.warning(
                    "AD-672: release() ignored unknown thread_id %s on agent %s; "
                    "active slots unchanged",
                    thread_id,
                    self._agent_id,
                )
                return

            self._semaphore.release()
            while self._queue:
                next_intent = self._queue.pop(0)
                if next_intent.future.cancelled():
                    logger.debug(
                        "AD-672: Skipping cancelled queued intent '%s' for agent %s",
                        next_intent.intent_type,
                        self._agent_id,
                    )
                    continue

                await self._semaphore.acquire()
                self._active[next_intent.thread_id] = ThreadEntry(
                    thread_id=next_intent.thread_id,
                    intent_type=next_intent.intent_type,
                    priority=next_intent.priority,
                    resource_key=next_intent.resource_key,
                )
                logger.info(
                    "AD-672: Promoted queued intent '%s' for agent %s at priority=%d",
                    next_intent.intent_type,
                    self._agent_id,
                    next_intent.priority,
                )
                if not next_intent.future.done():
                    next_intent.future.set_result(next_intent.thread_id)
                break

    async def arbitrate(self, resource_key: str) -> str | None:
        """Return the lower-priority thread for a shared-resource conflict."""
        async with self._lock:
            contenders = [
                entry for entry in self._active.values()
                if entry.resource_key == resource_key
            ]
            if len(contenders) < 2:
                return None

            contenders.sort(key=lambda entry: (entry.priority, entry.started_at))
            yielding = contenders[0]
            winner = contenders[-1]
            logger.info(
                "AD-672: Arbitration on resource '%s' for agent %s; thread %s "
                "priority=%d yields to thread %s priority=%d",
                resource_key,
                self._agent_id,
                yielding.thread_id,
                yielding.priority,
                winner.thread_id,
                winner.priority,
            )
            return yielding.thread_id

    @asynccontextmanager
    async def slot(
        self,
        intent_type: str,
        priority: int = 5,
        resource_key: str | None = None,
    ) -> AsyncIterator[str]:
        """Acquire and release a concurrency slot around a lifecycle body."""
        thread_id = await self.acquire(intent_type, priority, resource_key)
        try:
            yield thread_id
        finally:
            await self.release(thread_id)

    def snapshot(self) -> dict[str, Any]:
        """Return a diagnostic snapshot of active and queued concurrency state."""
        return {
            "agent_id": self._agent_id,
            "max_concurrent": self._max_concurrent,
            "active_count": self.active_count,
            "queue_depth": self.queue_depth,
            "active_threads": [
                {
                    "thread_id": entry.thread_id,
                    "intent_type": entry.intent_type,
                    "priority": entry.priority,
                    "age_s": round(time.monotonic() - entry.started_at, 2),
                }
                for entry in self._active.values()
            ],
        }

    def _emit_capacity_warning(self) -> None:
        """Emit AGENT_CAPACITY_APPROACHING with debounce protection."""
        if self._emit_event_fn is None:
            return
        now = time.monotonic()
        if now - self._last_capacity_warning < self._capacity_warning_cooldown:
            return
        self._last_capacity_warning = now
        try:
            self._emit_event_fn(EventType.AGENT_CAPACITY_APPROACHING, {
                "agent_id": self._agent_id,
                "active_count": self.active_count,
                "max_concurrent": self._max_concurrent,
                "queue_depth": self.queue_depth,
            })
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug(
                "AD-672: Failed to emit capacity warning for agent %s; "
                "continuing without saturation telemetry",
                self._agent_id,
                exc_info=True,
            )
