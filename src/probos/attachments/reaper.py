"""AD-733-1: Attachment retention / LRU reaper.

Two policies, run in sequence each tick:
  1. Age TTL -- origin=perception_frame older than frame_retention_seconds.
  2. LRU cap -- if total > attachments.max_store_bytes, evict oldest
     perception_frame entries first, then oldest chat_attachment entries,
     until under cap.

Tier-2 honest-degrade: any filesystem error is logged at WARNING; the
sweep continues with the next candidate. Never raises out of the loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.attachments.store import AttachmentStore
    from probos.config import AttachmentsConfig, PerceptionConfig

logger = logging.getLogger(__name__)


# Eviction order for the LRU pass. Less-durable origins are evicted first.
_LRU_EVICTION_ORDER: tuple[str, ...] = (
    "perception_frame",
    "browser_screenshot",
    "avatar_render",
    "chat_attachment",
)


class AttachmentReaper:
    """AD-733-1: background sweeper for AttachmentStore retention.

    Constructed once per runtime; ``start()`` schedules the loop,
    ``stop()`` cancels with a 2s grace and awaits cleanup. ``sweep_once``
    is exposed for tests.
    """

    def __init__(
        self,
        store: "AttachmentStore",
        *,
        perception_cfg: "PerceptionConfig",
        attachments_cfg: "AttachmentsConfig",
        event_emitter: Any | None = None,
    ) -> None:
        self._store = store
        self._perception_cfg = perception_cfg
        self._attachments_cfg = attachments_cfg
        self._emit_event = event_emitter
        self._task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()

    # ---- lifecycle ----------------------------------------------------

    async def start(self) -> None:
        """Start the background reap loop. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._loop(), name="ad733-1-attachment-reaper"
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
                    "AD-733-1: AttachmentReaper task raised on cancel",
                    exc_info=True,
                )
        self._task = None

    async def _loop(self) -> None:
        interval = max(1, int(self._perception_cfg.reaper_interval_seconds))
        try:
            while not self._stop_event.is_set():
                try:
                    await self.sweep_once()
                except Exception:
                    logger.warning(
                        "AD-733-1: sweep_once raised; continuing loop",
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

    async def sweep_once(self) -> dict[str, int]:
        """Run both policies once.

        Returns ``{age_ttl_removed, lru_removed, freed_bytes}``. Never
        raises -- per-candidate failures are logged + skipped.
        """
        age_ttl_removed, age_ttl_freed = await self._sweep_age_ttl()
        lru_removed, lru_freed = await self._sweep_lru()
        total_removed = age_ttl_removed + lru_removed
        total_freed = age_ttl_freed + lru_freed
        if total_removed > 0 and self._emit_event is not None:
            try:
                self._emit_event(
                    EventType.ATTACHMENT_REAPED,
                    {
                        "age_ttl_removed": age_ttl_removed,
                        "lru_removed": lru_removed,
                        "freed_bytes": total_freed,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-733-1: ATTACHMENT_REAPED emit failed",
                    exc_info=True,
                )
        return {
            "age_ttl_removed": age_ttl_removed,
            "lru_removed": lru_removed,
            "freed_bytes": total_freed,
        }

    async def _sweep_age_ttl(self) -> tuple[int, int]:
        """Evict perception_frame entries older than the retention window."""
        retention = int(self._perception_cfg.frame_retention_seconds)
        if retention <= 0:
            return (0, 0)
        cutoff = time.time() - retention
        try:
            candidates = await self._store.list_by_origin("perception_frame")
        except Exception:
            logger.warning(
                "AD-733-1: list_by_origin(perception_frame) failed",
                exc_info=True,
            )
            return (0, 0)
        removed = 0
        freed = 0
        for sha, written_at in candidates:
            if written_at >= cutoff:
                break  # list is sorted oldest-first.
            freed_one = await self._safe_unlink(sha)
            if freed_one is not None:
                removed += 1
                freed += freed_one
        return (removed, freed)

    async def _sweep_lru(self) -> tuple[int, int]:
        """Evict oldest entries until total <= max_store_bytes.

        Less-durable origins (perception_frame) are evicted first; if
        that's not enough, walk through browser_screenshot, then
        avatar_render, then chat_attachment.
        """
        cap = int(self._attachments_cfg.max_store_bytes)
        if cap <= 0:
            return (0, 0)
        try:
            total = await self._store.total_size_bytes()
        except Exception:
            logger.warning(
                "AD-733-1: total_size_bytes failed; skipping LRU pass",
                exc_info=True,
            )
            return (0, 0)
        if total <= cap:
            return (0, 0)
        removed = 0
        freed = 0
        for origin in _LRU_EVICTION_ORDER:
            if total <= cap:
                break
            try:
                candidates = await self._store.list_by_origin(origin)
            except Exception:
                logger.warning(
                    "AD-733-1: list_by_origin(%s) failed during LRU sweep",
                    origin,
                    exc_info=True,
                )
                continue
            for sha, _written_at in candidates:
                if total <= cap:
                    break
                freed_one = await self._safe_unlink(sha)
                if freed_one is not None:
                    removed += 1
                    freed += freed_one
                    total -= freed_one
        return (removed, freed)

    async def _safe_unlink(self, sha: str) -> int | None:
        """Best-effort unlink. Returns bytes freed or ``None`` on failure."""
        size_bytes = 0
        try:
            size_bytes = await self._store.size(sha)
        except FileNotFoundError:
            # Concurrent unlink already removed the blob; still try to
            # clear the index entry below.
            size_bytes = 0
        except Exception:
            logger.warning(
                "AD-733-1: size(%s) failed during sweep",
                sha[:8],
                exc_info=True,
            )
        try:
            ok = await self._store.unlink(sha)
        except FileNotFoundError:
            return 0
        except Exception:
            logger.warning(
                "AD-733-1: unlink(%s) failed during sweep; skipping",
                sha[:8],
                exc_info=True,
            )
            return None
        if not ok:
            return 0
        return size_bytes
