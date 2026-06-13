"""AD-986d: transcript retention reaper.

The canonical chat recording (:class:`~probos.threads.ChatThreadStore`) is ground
truth and the contagion firewall for cross-agent recall, but it must not persist
forever. This background sweeper hard-deletes rooms whose last activity is older
than ``memory.transcript_retention_days``, leaving an AD-986d tombstone for each
so a participant who still holds a subjective memory of the room is honestly told
the recording was purged (rather than silently relying on a lossy recollection).

Default OFF: when ``transcript_retention_days <= 0`` the reaper is never started
(see ``startup/finalize.py``), so the transcript store is byte-identical until the
Captain opts in. Pinned rooms are always exempt. Tier-2 honest-degrade: any error
is logged at WARNING and the loop continues; it never raises out.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from probos.threads import ChatThreadStore

logger = logging.getLogger(__name__)

_SECONDS_PER_DAY = 86400


class TranscriptReaper:
    """AD-986d: background sweeper for ChatThreadStore transcript retention.

    Constructed once per runtime when retention is enabled; ``start()`` schedules
    the loop, ``stop()`` cancels with grace and awaits cleanup. ``sweep_once`` is
    exposed for tests.
    """

    def __init__(
        self,
        store: "ChatThreadStore",
        *,
        retention_days: int,
        interval_seconds: int = 3600,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._retention_days = int(retention_days)
        self._interval = max(60, int(interval_seconds))
        self._clock = clock
        self._task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()

    # ---- lifecycle ----------------------------------------------------

    async def start(self) -> None:
        """Start the background reap loop. Idempotent; no-op when retention <= 0."""
        if self._retention_days <= 0:
            return
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._loop(), name="ad986d-transcript-reaper"
        )

    async def stop(self) -> None:
        """Signal exit, cancel if needed, await cleanup. Idempotent."""
        self._stop_event.set()
        task = self._task
        if task is None:
            return
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.warning(
                    "AD-986d: TranscriptReaper task raised on cancel", exc_info=True
                )
        self._task = None

    async def _loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    await self.sweep_once()
                except Exception:
                    logger.warning(
                        "AD-986d: transcript sweep_once raised; continuing loop",
                        exc_info=True,
                    )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._interval
                    )
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            # Standing async discipline: cleanup + re-raise.
            raise

    # ---- sweep --------------------------------------------------------

    async def sweep_once(self) -> int:
        """Purge transcripts past the retention window once.

        Returns the number of rooms purged. Never raises — a store error is
        logged and reported as 0 purged. The synchronous store call runs in the
        default executor so the event loop is not blocked.
        """
        if self._retention_days <= 0:
            return 0
        cutoff = self._clock() - self._retention_days * _SECONDS_PER_DAY
        try:
            loop = asyncio.get_running_loop()
            purged = await loop.run_in_executor(
                None,
                lambda: self._store.purge_threads_older_than(
                    cutoff, exclude_pinned=True
                ),
            )
        except Exception:
            logger.warning(
                "AD-986d: purge_threads_older_than failed; nothing purged this sweep",
                exc_info=True,
            )
            return 0
        n = len(purged)
        if n > 0:
            logger.info(
                "AD-986d: TranscriptReaper purged %d transcript(s) "
                "older than %d day(s)",
                n,
                self._retention_days,
            )
        return n
