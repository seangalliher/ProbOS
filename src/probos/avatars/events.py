"""AD-722b: per-agent avatar-telemetry event bus.

Lightweight ``asyncio.Event`` registry keyed by agent_id. Trigger sites
(``enter_dm``, ``exit_dm``, ``enter_chain``, ``exit_chain``,
``enter_popout``, ``exit_popout``, ``mark_reply_emitted``) call
``notify(agent_id)`` to wake any subscribers (the WS publish loop).
Subscribers obtain a fresh ``asyncio.Event`` via ``subscribe(agent_id)``
and ``await event.wait()`` inside their loop, ``event.clear()`` after
processing.

Thread-safety: ``asyncio.Event.set()`` is safe to call from synchronous
code IF the event was created on a running loop; we create on first
``subscribe`` (which always runs from the WS handler coroutine, i.e.
on the loop). ``notify`` may be called from sync code (e.g. the DM
trigger site in routers/agents.py — FastAPI sync handler section).
That is also safe — ``Event.set()`` is documented as thread-safe-in-
practice for the CPython implementation when the event was bound
to the running loop.

State is volatile by design — restart resets all events.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class AvatarEventBus:
    """Per-agent ``asyncio.Event`` registry.

    Multiple subscribers per agent are supported: each ``subscribe()``
    returns a distinct ``asyncio.Event``; ``notify(agent_id)`` sets all
    events bound to that agent. Subscribers ``clear()`` their own event
    after handling a wake.
    """

    def __init__(self) -> None:
        # agent_id -> set of asyncio.Event instances.
        self._subscribers: dict[str, set[asyncio.Event]] = defaultdict(set)

    def subscribe(self, agent_id: str) -> asyncio.Event:
        """Create + register a fresh event for an agent. Caller owns
        the lifecycle and MUST call ``unsubscribe`` on close.
        """
        event = asyncio.Event()
        self._subscribers[agent_id].add(event)
        return event

    def unsubscribe(self, agent_id: str, event: asyncio.Event) -> None:
        """Remove a subscriber. Tier-2 — silent on missing key."""
        bucket = self._subscribers.get(agent_id)
        if bucket is None:
            return
        bucket.discard(event)
        if not bucket:
            # Drop empty bucket so unbounded agent_ids don't accumulate.
            self._subscribers.pop(agent_id, None)

    def notify(self, agent_id: str) -> None:
        """Wake every subscriber bound to ``agent_id``. Safe from sync
        and async code. No-op when no subscribers."""
        bucket = self._subscribers.get(agent_id)
        if not bucket:
            return
        for event in bucket:
            try:
                event.set()
            except Exception:
                # Tier-2: a corrupted event is a one-off; log and skip.
                logger.debug(
                    "AD-722b: avatar_event_bus.notify failed for agent=%s",
                    agent_id, exc_info=True,
                )

    def subscriber_count(self, agent_id: str) -> int:
        """Test-only introspection."""
        return len(self._subscribers.get(agent_id, ()))
