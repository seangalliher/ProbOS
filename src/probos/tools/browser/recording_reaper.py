"""AD-706b: Recording retention reaper.

Background sweeper that deletes Playwright-recorded ``.webm`` files older than
``BrowserToolConfig.recording_retention_days`` and enforces the per-session
size cap. Lives outside the BrowserTool to keep substrate teardown clean.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.config import BrowserToolConfig

logger = logging.getLogger(__name__)


class RecordingReaper:
    """AD-706b: deletes expired ``.webm`` files on a configurable schedule."""

    def __init__(
        self,
        *,
        cfg: BrowserToolConfig,
        emit_event_fn: Any | None = None,
    ) -> None:
        self._cfg = cfg
        self._emit_event = emit_event_fn
        self._task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        """Start the background reap loop."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="ad706b-recording-reaper")

    async def stop(self) -> None:
        """Signal the loop to exit, cancel if needed, await cleanup."""
        self._stop_event.set()
        if self._task is None:
            return
        if not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.warning("AD-706b: reaper task raised on cancel", exc_info=True)
        self._task = None

    async def _loop(self) -> None:
        """Sleep / reap cadence."""
        interval = max(1, int(self._cfg.recording_reaper_interval_seconds))
        try:
            while not self._stop_event.is_set():
                try:
                    await self.reap_once()
                except Exception:
                    logger.warning(
                        "AD-706b: reap_once raised; continuing loop",
                        exc_info=True,
                    )
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            # Standing async discipline: cleanup + re-raise.
            raise

    async def reap_once(self) -> int:
        """Sweep recording_dir once; return number of files deleted.

        Tier-2 throughout: FileNotFoundError / PermissionError on individual
        files are logged at warning and skipped, never raised.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._reap_sync)

    def _reap_sync(self) -> int:
        deleted = 0
        root = Path(self._cfg.recording_dir)
        if not root.exists():
            return 0
        retention_seconds = int(self._cfg.recording_retention_days) * 86400
        max_bytes = int(self._cfg.recording_max_size_mb_per_session) * 1024 * 1024
        now = time.time()
        for subdir in root.iterdir():
            if not subdir.is_dir():
                continue
            try:
                webms = sorted(subdir.glob("*.webm"), key=lambda p: p.stat().st_mtime)
            except OSError:
                logger.warning(
                    "AD-706b: failed to scan session subdir %s", subdir, exc_info=True
                )
                continue

            # 1) Age-based expiry.
            survivors: list[Path] = []
            for webm in webms:
                try:
                    age = now - webm.stat().st_mtime
                except OSError:
                    logger.warning(
                        "AD-706b: stat failed for %s", webm, exc_info=True
                    )
                    continue
                if age > retention_seconds:
                    try:
                        webm.unlink()
                        deleted += 1
                        self._safe_emit(
                            EventType.BROWSER_RECORDING_EXPIRED,
                            {
                                "session_id": subdir.name,
                                "path": str(webm),
                                "reason": "retention",
                            },
                        )
                    except OSError:
                        logger.warning(
                            "AD-706b: unlink failed for %s", webm, exc_info=True
                        )
                else:
                    survivors.append(webm)

            # 2) Per-session size cap (oldest first).
            total = 0
            sizes: list[tuple[Path, int]] = []
            for webm in survivors:
                try:
                    s = webm.stat().st_size
                except OSError:
                    s = 0
                sizes.append((webm, s))
                total += s
            sizes.sort(key=lambda pair: pair[0].stat().st_mtime if pair[0].exists() else 0)
            i = 0
            while total > max_bytes and i < len(sizes):
                webm, s = sizes[i]
                i += 1
                try:
                    webm.unlink()
                    total -= s
                    deleted += 1
                    self._safe_emit(
                        EventType.BROWSER_RECORDING_EXPIRED,
                        {
                            "session_id": subdir.name,
                            "path": str(webm),
                            "reason": "size_cap",
                        },
                    )
                except OSError:
                    logger.warning(
                        "AD-706b: unlink failed for %s", webm, exc_info=True
                    )

            # 3) Remove empty session subdir.
            try:
                if not any(subdir.iterdir()):
                    subdir.rmdir()
            except OSError:
                logger.debug(
                    "AD-706b: rmdir failed for %s (not empty?)", subdir, exc_info=True
                )

        return deleted

    def _safe_emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        if self._emit_event is None:
            return
        try:
            self._emit_event(event_type, payload)
        except Exception:
            logger.debug(
                "AD-706b: emit_event failed for %s", event_type, exc_info=True
            )
