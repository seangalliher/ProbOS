"""AD-1019c: MCP workbench idle-TTL adapter reaper.

Mirrors :class:`~probos.attachments.reaper.AttachmentReaper` for lifecycle shape
(``start()`` schedules the loop, ``stop()`` cancels with grace + awaits cleanup,
``sweep_once`` is exposed for tests). Each tick it asks the workbench which warm
adapters have been idle longer than the TTL and unloads them back to the toolbox
— so a tool an agent searched for once does not stay registered forever.

Layer discipline: the reaper lives beside :class:`MCPBridge` (integration state)
but the workbench it drives lives in the cognitive layer. To avoid an
integration→cognitive import, the reaper depends only on the narrow
:class:`IdleAdapterSource` ``Protocol`` (Interface Segregation + Dependency
Inversion); :class:`~probos.cognitive.mcp_workbench.MCPWorkbench` satisfies it
structurally.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class IdleAdapterSource(Protocol):
    """The narrow surface the reaper needs from the workbench."""

    def idle_tool_ids(self, ttl_seconds: float) -> list[str]:
        """Return ids of warm adapters idle longer than ``ttl_seconds``."""
        ...

    async def unload_tool(self, tool_id: str) -> None:
        """Unload one warm adapter (unregister + untrack)."""
        ...


class McpWorkbenchReaper:
    """AD-1019c: background sweeper that unloads idle MCP workbench adapters.

    Constructed once per runtime; ``start()`` schedules the loop, ``stop()``
    cancels with a grace period and awaits cleanup. ``sweep_once`` is exposed for
    tests and returns the number of adapters unloaded.
    """

    def __init__(
        self,
        source: IdleAdapterSource,
        *,
        idle_ttl_seconds: float,
        interval_seconds: float,
    ) -> None:
        self._source = source
        self._idle_ttl_seconds = float(idle_ttl_seconds)
        self._interval_seconds = max(1.0, float(interval_seconds))
        self._task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()

    # ---- lifecycle ----------------------------------------------------

    async def start(self) -> None:
        """Start the background reap loop. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._loop(), name="ad1019c-mcp-workbench-reaper"
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
                    "AD-1019c: McpWorkbenchReaper task raised on cancel",
                    exc_info=True,
                )
        self._task = None

    async def _loop(self) -> None:
        interval = max(1, int(self._interval_seconds))
        try:
            while not self._stop_event.is_set():
                try:
                    await self.sweep_once()
                except Exception:
                    logger.warning(
                        "AD-1019c: sweep_once raised; continuing loop",
                        exc_info=True,
                    )
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=interval
                    )
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            # Standing async discipline: cleanup + re-raise.
            raise

    # ---- sweep --------------------------------------------------------

    async def sweep_once(self) -> int:
        """Unload every adapter idle past the TTL. Returns the count unloaded.

        Never raises out of the loop — a per-adapter unload failure is logged
        and skipped (Tier-2 honest-degrade).
        """
        unloaded = 0
        for tool_id in self._source.idle_tool_ids(self._idle_ttl_seconds):
            try:
                await self._source.unload_tool(tool_id)
                unloaded += 1
            except Exception:
                logger.warning(
                    "AD-1019c: failed to unload idle MCP adapter %s; skipping",
                    tool_id,
                    exc_info=True,
                )
        return unloaded
