"""AD-876: cadence ticker for the Quartermaster work-board reconciler.

Runs :meth:`QuartermasterAgent.reconcile` once at warm boot (after a short
startup delay) and then on a fixed interval. The agent stays intent-driven;
this ticker owns only the cadence, holds its own task reference (no
fire-and-forget), and honest-degrades per sweep.

Mirrors :class:`AttachmentReaper` for lifecycle shape: ``start()`` schedules
the loop, ``stop()`` cancels + awaits cleanup, both idempotent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class BoardReconcilerTicker:
    """Drives periodic + warm-boot ``agent.reconcile()`` calls."""

    def __init__(
        self,
        *,
        agent: Any,
        interval_seconds: int,
        warm_boot: bool,
        startup_delay: float = 10.0,
    ) -> None:
        self._agent = agent
        self._interval = max(1, int(interval_seconds))
        self._warm_boot = warm_boot
        self._startup_delay = startup_delay
        self._task: asyncio.Task[Any] | None = None

    # ---- lifecycle ----------------------------------------------------

    def start(self) -> None:
        """Schedule the cadence loop. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(
            self._loop(), name="ad876-board-reconciler"
        )

    async def stop(self) -> None:
        """Cancel the loop and await cleanup. Idempotent."""
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
                    "AD-876: BoardReconcilerTicker task raised on cancel",
                    exc_info=True,
                )
        self._task = None

    # ---- loop ---------------------------------------------------------

    async def _loop(self) -> None:
        try:
            if self._warm_boot:
                await asyncio.sleep(self._startup_delay)
                await self._safe_reconcile()
            while True:
                await asyncio.sleep(self._interval)
                await self._safe_reconcile()
        except asyncio.CancelledError:
            # Standing async discipline: cleanup + re-raise.
            raise

    async def _safe_reconcile(self) -> None:
        """Run one reconcile sweep; never let an error kill the loop."""
        try:
            await self._agent.reconcile()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "AD-876: board reconcile sweep raised; continuing cadence",
                exc_info=True,
            )
