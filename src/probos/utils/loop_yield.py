"""BF-932 (#1670): give the event loop a turn every N units of synchronous work.

A coroutine that loops over synchronous work (file reads, pair comparisons, store calls) without an ``await`` holds
the event loop for the whole loop. ``LoopYield.due()`` counts units; on every ``every``-th unit it returns True and
the caller awaits ``asyncio.sleep(0)``, which lets each ready callback run once. The budget is a count of units, not
a time, and the work and its order are unchanged.
"""

from __future__ import annotations


class LoopYield:
    """Counts units of synchronous work; ``due()`` is True on every ``every``-th unit."""

    __slots__ = ("_count", "_every")

    def __init__(self, every: int) -> None:
        if every < 1:
            raise ValueError("every must be at least 1")
        self._every = every
        self._count = 0

    def due(self) -> bool:
        """Count one unit; True when the caller should ``await asyncio.sleep(0)`` now."""
        self._count += 1
        if self._count >= self._every:
            self._count = 0
            return True
        return False
