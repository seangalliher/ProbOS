"""Signal manager — TTL enforcement and message expiry."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from probos.types import IntentMessage

logger = logging.getLogger(__name__)


class SignalManager:
    """Tracks live intent signals and reaps expired ones.

    Every intent broadcast through the mesh is registered here.
    A background reaper loop removes intents whose TTL has elapsed.
    """

    def __init__(self, reap_interval: float = 1.0) -> None:
        self._signals: dict[str, IntentMessage] = {}
        self._reap_interval = reap_interval
        self._reaper_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._on_expired: list[Callable[[str], Any]] = []

    def on_expired(self, callback: Callable[[str], Any]) -> None:
        """Register a callback invoked when a signal expires."""
        self._on_expired.append(callback)

    def track(self, intent: IntentMessage) -> None:
        """Start tracking an intent signal."""
        self._signals[intent.id] = intent

    def untrack(self, intent_id: str) -> None:
        """Stop tracking (intent was fulfilled)."""
        self._signals.pop(intent_id, None)

    def is_alive(self, intent_id: str) -> bool:
        """Check if an intent signal is still within its TTL."""
        intent = self._signals.get(intent_id)
        if intent is None:
            return False
        elapsed = (datetime.now(timezone.utc) - intent.created_at).total_seconds()
        return elapsed < intent.ttl_seconds

    @property
    def active_count(self) -> int:
        return len(self._signals)

    async def start(self) -> None:
        self._stop_event.clear()
        self._reaper_task = asyncio.create_task(
            self._reaper_loop(), name="signal-reaper"
        )

    async def stop(self) -> None:
        self._stop_event.set()
        if self._reaper_task and not self._reaper_task.done():
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass

    async def _reaper_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._reap_interval
                )
                break
            except asyncio.TimeoutError:
                pass
            await self._reap()

    async def _reap(self) -> None:
        now = datetime.now(timezone.utc)
        expired: list[str] = []
        for intent_id, intent in self._signals.items():
            elapsed = (now - intent.created_at).total_seconds()
            if elapsed >= intent.ttl_seconds:
                expired.append(intent_id)

        for intent_id in expired:
            self._signals.pop(intent_id, None)
            logger.debug("Signal expired: %s", intent_id[:8])
            for cb in self._on_expired:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(intent_id)
                    else:
                        cb(intent_id)
                except Exception:
                    logger.exception("Signal expiry callback error")
