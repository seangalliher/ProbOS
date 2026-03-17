"""Lightweight in-session task scheduler (AD-281).

Executes deferred and recurring tasks within a running ``probos serve``
session.  Tasks do NOT survive server restarts — persistent checkpointing
is deferred to Phase 25.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """A single scheduled task."""

    id: str
    created_at: float
    execute_at: float
    intent_text: str
    interval_seconds: float | None = None
    channel_id: str | None = None
    status: str = "pending"  # pending | running | completed | failed
    last_result: dict[str, Any] | None = None


class TaskScheduler:
    """Background scheduler that fires tasks at their ``execute_at`` time.

    Follows the ``DreamScheduler`` pattern: a background ``asyncio.Task``
    with a 1-second tick, ``start()``/``stop()`` lifecycle.
    """

    def __init__(
        self,
        process_fn: Any = None,
        channel_adapters: list[Any] | None = None,
    ) -> None:
        self._process_fn = process_fn  # async (text) -> dict
        self._channel_adapters: list[Any] = channel_adapters or []
        self._tasks: dict[str, ScheduledTask] = {}
        self._task: asyncio.Task[None] | None = None
        self._stopped = False

    # -- public API -------------------------------------------------------

    def schedule(
        self,
        text: str,
        delay_seconds: float,
        interval_seconds: float | None = None,
        channel_id: str | None = None,
    ) -> ScheduledTask:
        """Create a new scheduled task."""
        now = time.monotonic()
        task = ScheduledTask(
            id=uuid.uuid4().hex[:12],
            created_at=now,
            execute_at=now + delay_seconds,
            intent_text=text,
            interval_seconds=interval_seconds,
            channel_id=channel_id,
        )
        self._tasks[task.id] = task
        logger.debug("Scheduled task %s at +%.1fs: %s", task.id, delay_seconds, text)
        return task

    def cancel(self, task_id: str) -> bool:
        """Cancel a pending task.  Returns True if found and removed."""
        task = self._tasks.pop(task_id, None)
        return task is not None

    def list_tasks(self) -> list[ScheduledTask]:
        """Return all tasks sorted by next execution time."""
        return sorted(self._tasks.values(), key=lambda t: t.execute_at)

    def get_stats(self) -> dict[str, Any]:
        """Summary statistics for status panels."""
        by_status: dict[str, int] = {}
        for t in self._tasks.values():
            by_status[t.status] = by_status.get(t.status, 0) + 1
        upcoming = min(
            (t for t in self._tasks.values() if t.status == "pending"),
            key=lambda t: t.execute_at,
            default=None,
        )
        return {
            "total": len(self._tasks),
            "by_status": by_status,
            "next_execute_in": (
                round(upcoming.execute_at - time.monotonic(), 1)
                if upcoming
                else None
            ),
        }

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Start the background tick loop."""
        if self._task is not None:
            return
        self._stopped = False
        self._task = asyncio.ensure_future(self._tick_loop())

    async def stop(self) -> None:
        """Stop the background tick loop."""
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    # -- internals --------------------------------------------------------

    async def _tick_loop(self) -> None:
        """Check for due tasks every second."""
        while not self._stopped:
            try:
                await asyncio.sleep(1.0)
                now = time.monotonic()
                for task in list(self._tasks.values()):
                    if task.status == "pending" and task.execute_at <= now:
                        await self._execute_task(task)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("TaskScheduler tick error")

    async def _execute_task(self, task: ScheduledTask) -> None:
        """Run a single task, catching all errors."""
        task.status = "running"
        try:
            if self._process_fn:
                result = await self._process_fn(task.intent_text)
            else:
                result = {"response": "(no runtime connected)"}
            task.last_result = result
            task.status = "completed"
            logger.debug("Task %s completed", task.id)

            # Deliver to channel if requested
            if task.channel_id:
                await self._deliver_to_channel(task)

        except Exception as e:
            task.status = "failed"
            task.last_result = {"error": str(e)}
            logger.warning("Task %s failed: %s", task.id, e)

        # Reschedule if recurring
        if task.interval_seconds is not None:
            task.execute_at = time.monotonic() + task.interval_seconds
            task.status = "pending"

    async def _deliver_to_channel(self, task: ScheduledTask) -> None:
        """Send task result to the appropriate channel adapter."""
        if not task.channel_id or not task.last_result:
            return

        from probos.channels.response_formatter import extract_response_text

        text = extract_response_text(task.last_result)
        if not text:
            return

        for adapter in self._channel_adapters:
            try:
                await adapter.send_response(task.channel_id, text)
                return  # delivered
            except Exception as e:
                logger.warning(
                    "Channel delivery failed for task %s: %s", task.id, e,
                )
